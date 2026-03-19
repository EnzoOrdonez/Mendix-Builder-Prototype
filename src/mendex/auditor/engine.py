"""Motor de auditoría de buenas prácticas para proyectos Mendix existentes.

Lee un .mpr existente via SDK Bridge, extrae todos los artefactos
(entidades, páginas, microflows) y evalúa cada uno contra:
1. Reglas deterministas locales (naming, access rules, attribute count, etc.)
2. BP oficiales via RAG + LLM (BPEvaluator), si está disponible

Genera un AuditReport completo con hallazgos por severidad.

Fase 10: Implementación completa.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

import structlog

from mendex.auditor.rules import AuditFinding, AuditRule, FindingSeverity, get_default_rules
from mendex.bridge.sdk_client import (
    EntityInfo,
    ModuleInfo,
    ProjectStructure,
    SDKClient,
    SDKClientError,
)
from mendex.knowledge.bp_evaluator import BPEvaluation, BPEvaluator
from mendex.logging.decision_logger import BPVerdict, DecisionLogger

logger = structlog.get_logger(__name__)


# ─── Resultado ───────────────────────────────────────────────


class AuditStatus(str, Enum):
    """Estado global de la auditoría."""

    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    ERROR = "error"


@dataclass
class AuditedArtifact:
    """Un artefacto auditado con sus hallazgos."""

    artifact_type: str  # "entity", "page", "microflow"
    name: str
    module: str
    findings: list[AuditFinding] = field(default_factory=list)
    bp_evaluation: BPEvaluation | None = None

    @property
    def has_critical(self) -> bool:
        return any(f.severity == FindingSeverity.CRITICAL for f in self.findings)

    @property
    def has_warning(self) -> bool:
        return any(f.severity == FindingSeverity.WARNING for f in self.findings)

    @property
    def max_severity(self) -> FindingSeverity:
        if not self.findings:
            return FindingSeverity.INFO
        return max(self.findings, key=lambda f: f.severity_order).severity

    def as_report_lines(self) -> list[str]:
        """Genera líneas de reporte legibles."""
        icon = {"entity": "📦", "page": "📄", "microflow": "⚙️"}
        lines = [f"{icon.get(self.artifact_type, '•')} {self.module}.{self.name}"]
        for f in self.findings:
            lines.append(f"    {f.as_report_line()}")
        if self.bp_evaluation and self.bp_evaluation.verdict == BPVerdict.NO_CONFORME:
            lines.append(
                f"    ✗ BP: {self.bp_evaluation.reason}"
            )
            if self.bp_evaluation.recommendation:
                lines.append(f"      → {self.bp_evaluation.recommendation}")
        return lines


@dataclass
class AuditReport:
    """Reporte completo de auditoría de un proyecto Mendix."""

    mpr_path: str = ""
    artifacts: list[AuditedArtifact] = field(default_factory=list)
    generated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    scan_error: str | None = None

    @property
    def total_findings(self) -> int:
        return sum(len(a.findings) for a in self.artifacts)

    @property
    def total_critical(self) -> int:
        return sum(
            1 for a in self.artifacts for f in a.findings
            if f.severity == FindingSeverity.CRITICAL
        )

    @property
    def total_warnings(self) -> int:
        return sum(
            1 for a in self.artifacts for f in a.findings
            if f.severity == FindingSeverity.WARNING
        )

    @property
    def total_info(self) -> int:
        return sum(
            1 for a in self.artifacts for f in a.findings
            if f.severity == FindingSeverity.INFO
        )

    @property
    def status(self) -> AuditStatus:
        if self.scan_error:
            return AuditStatus.ERROR
        if self.total_critical > 0:
            return AuditStatus.FAIL
        if self.total_warnings > 0:
            return AuditStatus.WARN
        return AuditStatus.PASS

    @property
    def entities(self) -> list[AuditedArtifact]:
        return [a for a in self.artifacts if a.artifact_type == "entity"]

    @property
    def pages(self) -> list[AuditedArtifact]:
        return [a for a in self.artifacts if a.artifact_type == "page"]

    @property
    def microflows(self) -> list[AuditedArtifact]:
        return [a for a in self.artifacts if a.artifact_type == "microflow"]

    def as_text_report(self) -> str:
        """Genera el reporte completo como texto legible."""
        lines: list[str] = []
        lines.append("=" * 60)
        lines.append("  MendixFormAgent — Audit Report")
        lines.append("=" * 60)
        lines.append(f"Proyecto: {self.mpr_path}")
        lines.append(f"Fecha: {self.generated_at.isoformat()}")
        lines.append("")

        if self.scan_error:
            lines.append(f"⛔ ERROR: {self.scan_error}")
            return "\n".join(lines)

        # Summary
        status_icon = {
            AuditStatus.PASS: "✓ PASS",
            AuditStatus.WARN: "⚠ WARN",
            AuditStatus.FAIL: "✗ FAIL",
            AuditStatus.ERROR: "⛔ ERROR",
        }
        lines.append(f"Estado: {status_icon[self.status]}")
        lines.append(
            f"Artefactos auditados: {len(self.artifacts)} "
            f"({len(self.entities)} entidades, {len(self.pages)} páginas, "
            f"{len(self.microflows)} microflows)"
        )
        lines.append(
            f"Hallazgos: {self.total_critical} critical, "
            f"{self.total_warnings} warning, {self.total_info} info"
        )
        lines.append("")

        # Artifacts with findings
        artifacts_with_findings = [a for a in self.artifacts if a.findings]
        if artifacts_with_findings:
            lines.append("-" * 60)
            lines.append("Hallazgos:")
            lines.append("")
            for artifact in artifacts_with_findings:
                for line in artifact.as_report_lines():
                    lines.append(line)
                lines.append("")

        # Clean artifacts
        clean_count = len(self.artifacts) - len(artifacts_with_findings)
        if clean_count > 0:
            lines.append(f"({clean_count} artefactos sin hallazgos)")

        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Serializa el reporte a dict (para JSON response en API)."""
        return {
            "status": self.status.value,
            "mpr_path": self.mpr_path,
            "scan_error": self.scan_error,
            "artifacts": [
                {
                    "type": a.artifact_type,
                    "name": a.name,
                    "module": a.module,
                    "findings": [f.to_dict() for f in a.findings],
                    "bp_verdict": (
                        a.bp_evaluation.verdict.value
                        if a.bp_evaluation
                        else None
                    ),
                }
                for a in self.artifacts
            ],
            "summary": {
                "total_artifacts": len(self.artifacts),
                "total_findings": self.total_findings,
                "critical": self.total_critical,
                "warnings": self.total_warnings,
                "info": self.total_info,
            },
            "generated_at": self.generated_at.isoformat(),
        }

    def to_json(self, indent: int = 2) -> str:
        """Serializa a JSON."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


# ─── Engine ───────────────────────────────────────────────────


class AuditEngine:
    """Motor de auditoría de buenas prácticas para proyectos Mendix.

    Lee un .mpr existente, extrae la estructura del proyecto y evalúa
    cada artefacto contra reglas deterministas y (opcionalmente) BP
    oficiales via RAG + LLM.

    Uso:
        engine = AuditEngine(sdk_client=sdk_client)
        report = engine.audit(mpr_path=Path("proyecto.mpr"))
        print(report.as_text_report())
    """

    def __init__(
        self,
        sdk_client: SDKClient,
        bp_evaluator: BPEvaluator | None = None,
        decision_logger: DecisionLogger | None = None,
        rules: list[AuditRule] | None = None,
    ) -> None:
        self._sdk = sdk_client
        self._bp_evaluator = bp_evaluator
        self._decision_logger = decision_logger
        self._rules = rules if rules is not None else get_default_rules()

    def audit(
        self,
        mpr_path: Path,
        *,
        include_bp: bool = True,
        input_hash: str = "",
    ) -> AuditReport:
        """Ejecuta la auditoría completa de un proyecto .mpr.

        Args:
            mpr_path: Path al archivo .mpr.
            include_bp: Si True, evalúa contra BP oficiales via LLM.
            input_hash: Hash del input (para logging).

        Returns:
            AuditReport con todos los hallazgos.
        """
        report = AuditReport(mpr_path=str(mpr_path))

        logger.info("audit_started", mpr_path=str(mpr_path))

        # 1. Leer estructura del proyecto
        try:
            structure = self._sdk.read_project_structure(mpr_path)
        except SDKClientError as e:
            report.scan_error = f"No se pudo leer el proyecto: {e}"
            logger.error("audit_scan_failed", error=str(e))
            self._log_audit(report, input_hash)
            return report

        # 2. Auditar cada módulo
        for module in structure.modules:
            self._audit_module(module, report, mpr_path, include_bp, input_hash)

        # 3. Log
        self._log_audit(report, input_hash)

        logger.info(
            "audit_complete",
            artifacts=len(report.artifacts),
            findings=report.total_findings,
            critical=report.total_critical,
            warnings=report.total_warnings,
            status=report.status.value,
        )

        return report

    def _audit_module(
        self,
        module: ModuleInfo,
        report: AuditReport,
        mpr_path: Path,
        include_bp: bool,
        input_hash: str,
    ) -> None:
        """Audita todos los artefactos de un módulo."""
        # Entidades
        for entity in module.entities:
            artifact = self._audit_entity(
                entity, module.name, include_bp, input_hash
            )
            report.artifacts.append(artifact)

        # Páginas
        for page_name in module.pages:
            artifact = self._audit_page(
                page_name, module.name, include_bp, input_hash
            )
            report.artifacts.append(artifact)

        # Microflows
        for mf_name in module.microflows:
            artifact = self._audit_microflow(
                mf_name, module.name, include_bp, input_hash
            )
            report.artifacts.append(artifact)

    def _audit_entity(
        self,
        entity: EntityInfo,
        module: str,
        include_bp: bool,
        input_hash: str,
    ) -> AuditedArtifact:
        """Audita una entidad contra reglas y BP."""
        artifact = AuditedArtifact(
            artifact_type="entity",
            name=entity.name,
            module=module,
        )

        # Reglas deterministas
        context = {
            "artifact_type": "entity",
            "name": entity.name,
            "module": module,
            "attributes": entity.attributes,
            "attribute_count": len(entity.attributes),
        }
        for rule in self._rules:
            if rule.applies_to("entity"):
                finding = rule.check(context)
                if finding:
                    artifact.findings.append(finding)

        # BP evaluation via LLM
        if include_bp and self._bp_evaluator:
            bp_desc = (
                f"Entity '{entity.name}' in module '{module}' "
                f"with {len(entity.attributes)} attributes: "
                f"{', '.join(entity.attributes[:10])}"
            )
            artifact.bp_evaluation = self._evaluate_bp(bp_desc, input_hash)

        return artifact

    def _audit_page(
        self,
        page_name: str,
        module: str,
        include_bp: bool,
        input_hash: str,
    ) -> AuditedArtifact:
        """Audita una página contra reglas y BP."""
        artifact = AuditedArtifact(
            artifact_type="page",
            name=page_name,
            module=module,
        )

        context = {
            "artifact_type": "page",
            "name": page_name,
            "module": module,
        }
        for rule in self._rules:
            if rule.applies_to("page"):
                finding = rule.check(context)
                if finding:
                    artifact.findings.append(finding)

        if include_bp and self._bp_evaluator:
            bp_desc = f"Page '{page_name}' in module '{module}'"
            artifact.bp_evaluation = self._evaluate_bp(bp_desc, input_hash)

        return artifact

    def _audit_microflow(
        self,
        mf_name: str,
        module: str,
        include_bp: bool,
        input_hash: str,
    ) -> AuditedArtifact:
        """Audita un microflow contra reglas y BP."""
        artifact = AuditedArtifact(
            artifact_type="microflow",
            name=mf_name,
            module=module,
        )

        context = {
            "artifact_type": "microflow",
            "name": mf_name,
            "module": module,
        }
        for rule in self._rules:
            if rule.applies_to("microflow"):
                finding = rule.check(context)
                if finding:
                    artifact.findings.append(finding)

        if include_bp and self._bp_evaluator:
            bp_desc = f"Microflow '{mf_name}' in module '{module}'"
            artifact.bp_evaluation = self._evaluate_bp(bp_desc, input_hash)

        return artifact

    def _evaluate_bp(
        self, pattern_description: str, input_hash: str
    ) -> BPEvaluation | None:
        """Evalúa un patrón contra BP oficiales via LLM."""
        if self._bp_evaluator is None:
            return None
        try:
            return self._bp_evaluator.evaluate(
                pattern_description, input_hash=input_hash
            )
        except Exception as e:
            logger.warning("audit_bp_evaluation_failed", error=str(e))
            return None

    def _log_audit(self, report: AuditReport, input_hash: str) -> None:
        """Registra la auditoría en el decision logger."""
        if self._decision_logger is None:
            return
        self._decision_logger.log(
            operation="audit",
            input_hash=input_hash,
            action_taken=report.status.value,
            warnings=[
                f"{a.artifact_type}:{a.module}.{a.name} — {f.message}"
                for a in report.artifacts
                for f in a.findings
                if f.severity in (FindingSeverity.CRITICAL, FindingSeverity.WARNING)
            ],
            extra={
                "mpr_path": report.mpr_path,
                "total_artifacts": len(report.artifacts),
                "total_findings": report.total_findings,
                "critical": report.total_critical,
                "warnings": report.total_warnings,
                "info": report.total_info,
            },
        )
