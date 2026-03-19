"""Motor de dry-run, idempotency checker y sistema de veredictos BP.

Antes de modificar cualquier .mpr, el agente SIEMPRE muestra un preview
detallado de exactamente qué va a crear o modificar. El usuario debe
confirmar explícitamente antes de que se ejecute cualquier cambio.

El reporte incluye:
- Lista de artefactos a crear
- Veredictos de BP (CONFORME / NO_CONFORME / SIN_DATOS)
- Advertencias de idempotencia (artefacto ya existe)
- Política de conflicto aplicada (skip / overwrite / abort)

Fase 5: Implementación completa.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

import structlog

from mendex.bridge.sdk_client import SDKClient
from mendex.knowledge.bp_evaluator import BPEvaluation, BPEvaluator
from mendex.logging.decision_logger import BPVerdict, DecisionLogger, PatternSource
from mendex.schema.intermediate import (
    EntitySchema,
    IntermediateSchema,
    MicroflowSchema,
    PageSchema,
)

logger = structlog.get_logger(__name__)


# ─── Enums y configuración ──────────────────────────────────────


class ConflictPolicy(str, Enum):
    """Política ante colisión con artefacto existente."""

    SKIP = "skip"
    OVERWRITE = "overwrite"
    ABORT = "abort"


class ArtifactType(str, Enum):
    ENTITY = "entity"
    PAGE = "page"
    MICROFLOW = "microflow"


class ConflictStatus(str, Enum):
    NONE = "none"
    EXISTS_SKIP = "exists_skip"
    EXISTS_OVERWRITE = "exists_overwrite"
    EXISTS_ABORT = "exists_abort"


# ─── Modelos del reporte ────────────────────────────────────────


@dataclass
class DryRunArtifact:
    """Un artefacto individual en el reporte de dry-run."""

    artifact_type: ArtifactType
    name: str
    module: str
    bp_evaluation: BPEvaluation | None = None
    conflict: ConflictStatus = ConflictStatus.NONE
    will_execute: bool = True
    warnings: list[str] = field(default_factory=list)

    @property
    def bp_verdict(self) -> BPVerdict:
        if self.bp_evaluation:
            return self.bp_evaluation.verdict
        return BPVerdict.SIN_DATOS

    def as_report_lines(self, index: int) -> str:
        """Genera líneas de reporte legibles para este artefacto."""
        icon_type = {
            ArtifactType.ENTITY: "📦",
            ArtifactType.PAGE: "📄",
            ArtifactType.MICROFLOW: "⚙️",
        }
        icon_verdict = {
            BPVerdict.CONFORME: "✓",
            BPVerdict.NO_CONFORME: "✗",
            BPVerdict.SIN_DATOS: "?",
        }
        icon_conflict = {
            ConflictStatus.NONE: "",
            ConflictStatus.EXISTS_SKIP: " [SKIP — ya existe]",
            ConflictStatus.EXISTS_OVERWRITE: " [OVERWRITE — sobreescribirá]",
            ConflictStatus.EXISTS_ABORT: " [ABORT — colisión detectada]",
        }

        tipo = icon_type.get(self.artifact_type, "")
        lines = [
            f"[{index}] {tipo} {self.artifact_type.value.title()} "
            f'"{self.name}" en módulo "{self.module}"'
            f"{icon_conflict.get(self.conflict, '')}"
        ]

        # BP verdict
        v = self.bp_verdict
        verdict_icon = icon_verdict.get(v, "")
        if self.bp_evaluation:
            lines.append(
                f"    BP: {v.value} {verdict_icon} ({self.bp_evaluation.reason})"
            )
            if self.bp_evaluation.recommendation:
                lines.append(
                    f"    → Recomendación: {self.bp_evaluation.recommendation}"
                )
            if self.bp_evaluation.convention_conflict:
                lines.append(
                    f"    ⚠ Conflicto convenciones: {self.bp_evaluation.convention_conflict}"
                )
        else:
            lines.append(f"    BP: {v.value} {verdict_icon} (sin evaluación)")

        # Warnings
        for w in self.warnings:
            lines.append(f"    ⚠ {w}")

        # Ejecución
        if not self.will_execute:
            lines.append("    → NO se ejecutará")

        return "\n".join(lines)


@dataclass
class DryRunReport:
    """Reporte completo de dry-run."""

    artifacts: list[DryRunArtifact] = field(default_factory=list)
    conflict_policy: ConflictPolicy = ConflictPolicy.SKIP
    strict_mode: bool = False
    aborted: bool = False
    abort_reason: str = ""
    generated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @property
    def total_conforme(self) -> int:
        return sum(1 for a in self.artifacts if a.bp_verdict == BPVerdict.CONFORME)

    @property
    def total_no_conforme(self) -> int:
        return sum(1 for a in self.artifacts if a.bp_verdict == BPVerdict.NO_CONFORME)

    @property
    def total_sin_datos(self) -> int:
        return sum(1 for a in self.artifacts if a.bp_verdict == BPVerdict.SIN_DATOS)

    @property
    def total_conflicts(self) -> int:
        return sum(1 for a in self.artifacts if a.conflict != ConflictStatus.NONE)

    @property
    def total_will_execute(self) -> int:
        return sum(1 for a in self.artifacts if a.will_execute)

    @property
    def has_no_conforme(self) -> bool:
        return self.total_no_conforme > 0

    @property
    def entities(self) -> list[DryRunArtifact]:
        return [a for a in self.artifacts if a.artifact_type == ArtifactType.ENTITY]

    @property
    def pages(self) -> list[DryRunArtifact]:
        return [a for a in self.artifacts if a.artifact_type == ArtifactType.PAGE]

    @property
    def microflows(self) -> list[DryRunArtifact]:
        return [a for a in self.artifacts if a.artifact_type == ArtifactType.MICROFLOW]

    def as_text_report(self) -> str:
        """Genera el reporte completo como texto legible."""
        lines: list[str] = []
        lines.append("=" * 60)
        lines.append("  MendixFormAgent — Dry-Run Report")
        lines.append("=" * 60)
        lines.append("")

        if self.aborted:
            lines.append(f"⛔ ABORTADO: {self.abort_reason}")
            lines.append("")

        # Resumen
        n_ent = len(self.entities)
        n_pag = len(self.pages)
        n_mf = len(self.microflows)
        lines.append(
            f"Artefactos a generar: {n_ent} entidades, "
            f"{n_pag} páginas, {n_mf} microflows"
        )
        lines.append(
            f"Política de conflicto: --on-conflict={self.conflict_policy.value}"
        )
        if self.strict_mode:
            lines.append("Modo: --strict (aborta si hay NO_CONFORME)")
        lines.append("")

        # Artefactos
        for i, artifact in enumerate(self.artifacts, 1):
            lines.append(artifact.as_report_lines(i))
            lines.append("")

        # Totales
        lines.append("-" * 60)
        lines.append(
            f"Resumen: {self.total_conforme} CONFORME | "
            f"{self.total_no_conforme} NO_CONFORME | "
            f"{self.total_sin_datos} SIN_DATOS"
        )
        if self.total_conflicts > 0:
            lines.append(f"Colisiones: {self.total_conflicts}")
        lines.append(f"Se ejecutarán: {self.total_will_execute} de {len(self.artifacts)}")

        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Serializa el reporte a dict (para JSON response en API)."""
        return {
            "status": "aborted" if self.aborted else "dry_run_complete",
            "abort_reason": self.abort_reason if self.aborted else None,
            "conflict_policy": self.conflict_policy.value,
            "strict_mode": self.strict_mode,
            "artifacts": [
                {
                    "type": a.artifact_type.value,
                    "name": a.name,
                    "module": a.module,
                    "bp_verdict": a.bp_verdict.value,
                    "conflict": a.conflict.value,
                    "will_execute": a.will_execute,
                    "warnings": a.warnings,
                }
                for a in self.artifacts
            ],
            "summary": {
                "total": len(self.artifacts),
                "conforme": self.total_conforme,
                "no_conforme": self.total_no_conforme,
                "sin_datos": self.total_sin_datos,
                "conflicts": self.total_conflicts,
                "will_execute": self.total_will_execute,
            },
            "generated_at": self.generated_at.isoformat(),
        }

    def to_json(self, indent: int = 2) -> str:
        """Serializa a JSON."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


# ─── DryRunEngine ────────────────────────────────────────────────


class DryRunEngine:
    """Motor de dry-run con idempotency check y evaluación de BP.

    Recibe un IntermediateSchema y un path de .mpr, y para cada
    artefacto a generar:
    1. Verifica si ya existe (idempotency check via SDK Bridge)
    2. Evalúa contra BPs oficiales (via BPEvaluator)
    3. Aplica la política de conflicto
    4. Genera entrada en el reporte

    Uso:
        engine = DryRunEngine(
            sdk_client=sdk_client,
            bp_evaluator=bp_evaluator,
            decision_logger=decision_logger,
        )
        report = engine.run(
            schema=intermediate_schema,
            mpr_path=Path("proyecto.mpr"),
            conflict_policy=ConflictPolicy.SKIP,
            strict=False,
        )
        print(report.as_text_report())
    """

    def __init__(
        self,
        sdk_client: SDKClient,
        bp_evaluator: BPEvaluator | None = None,
        decision_logger: DecisionLogger | None = None,
    ) -> None:
        self._sdk = sdk_client
        self._bp_evaluator = bp_evaluator
        self._decision_logger = decision_logger

    def run(
        self,
        schema: IntermediateSchema,
        mpr_path: Path,
        *,
        conflict_policy: ConflictPolicy = ConflictPolicy.SKIP,
        strict: bool = False,
        input_hash: str = "",
    ) -> DryRunReport:
        """Ejecuta el dry-run completo.

        Args:
            schema: IntermediateSchema con los artefactos a generar.
            mpr_path: Path al .mpr destino.
            conflict_policy: skip | overwrite | abort.
            strict: Si True, aborta si hay algún NO_CONFORME.
            input_hash: Hash del input original (para logging).

        Returns:
            DryRunReport con todos los artefactos evaluados.
        """
        report = DryRunReport(
            conflict_policy=conflict_policy,
            strict_mode=strict,
        )

        logger.info(
            "dry_run_started",
            entities=len(schema.entities),
            pages=len(schema.pages),
            microflows=len(schema.microflows),
            policy=conflict_policy.value,
            strict=strict,
        )

        # 1. Procesar entidades
        for entity in schema.entities:
            artifact = self._process_entity(
                entity, mpr_path, conflict_policy, input_hash
            )
            report.artifacts.append(artifact)

            # Abort policy: detener si hay colisión
            if (
                conflict_policy == ConflictPolicy.ABORT
                and artifact.conflict != ConflictStatus.NONE
            ):
                report.aborted = True
                report.abort_reason = (
                    f"Colisión detectada: entity '{entity.name}' ya existe "
                    f"en módulo '{entity.module}' (--on-conflict=abort)"
                )
                self._log_dry_run(report, input_hash)
                return report

        # 2. Procesar páginas
        for page in schema.pages:
            artifact = self._process_page(
                page, mpr_path, conflict_policy, input_hash
            )
            report.artifacts.append(artifact)

            if (
                conflict_policy == ConflictPolicy.ABORT
                and artifact.conflict != ConflictStatus.NONE
            ):
                report.aborted = True
                report.abort_reason = (
                    f"Colisión detectada: page '{page.name}' ya existe "
                    f"en módulo '{page.module}' (--on-conflict=abort)"
                )
                self._log_dry_run(report, input_hash)
                return report

        # 3. Procesar microflows
        for mf in schema.microflows:
            artifact = self._process_microflow(
                mf, mpr_path, conflict_policy, input_hash
            )
            report.artifacts.append(artifact)

            if (
                conflict_policy == ConflictPolicy.ABORT
                and artifact.conflict != ConflictStatus.NONE
            ):
                report.aborted = True
                report.abort_reason = (
                    f"Colisión detectada: microflow '{mf.name}' ya existe "
                    f"en módulo '{mf.module}' (--on-conflict=abort)"
                )
                self._log_dry_run(report, input_hash)
                return report

        # 4. Strict mode: abortar si hay NO_CONFORME
        if strict and report.has_no_conforme:
            report.aborted = True
            no_conforme_names = [
                a.name for a in report.artifacts
                if a.bp_verdict == BPVerdict.NO_CONFORME
            ]
            report.abort_reason = (
                f"Modo --strict: {report.total_no_conforme} artefacto(s) "
                f"NO_CONFORME detectados: {', '.join(no_conforme_names)}"
            )

        self._log_dry_run(report, input_hash)

        logger.info(
            "dry_run_complete",
            total=len(report.artifacts),
            conforme=report.total_conforme,
            no_conforme=report.total_no_conforme,
            sin_datos=report.total_sin_datos,
            conflicts=report.total_conflicts,
            aborted=report.aborted,
        )

        return report

    def _process_entity(
        self,
        entity: EntitySchema,
        mpr_path: Path,
        policy: ConflictPolicy,
        input_hash: str,
    ) -> DryRunArtifact:
        """Procesa una entidad: idempotency check + BP evaluation."""
        artifact = DryRunArtifact(
            artifact_type=ArtifactType.ENTITY,
            name=entity.name,
            module=entity.module,
        )

        # Idempotency check
        exists = self._check_exists(mpr_path, "entity", entity.module, entity.name)
        if exists:
            artifact.conflict = self._resolve_conflict(policy)
            if policy == ConflictPolicy.SKIP:
                artifact.will_execute = False
                artifact.warnings.append(
                    f"Entity '{entity.name}' ya existe — se omitirá (--on-conflict=skip)"
                )

        # BP evaluation
        bp_patterns = self._build_entity_bp_patterns(entity)
        artifact.bp_evaluation = self._evaluate_bp(bp_patterns, input_hash)

        # Warnings adicionales
        if not entity.access_rules:
            artifact.warnings.append(
                "Sin reglas de acceso definidas — BP recomienda definir access rules explícitas"
            )

        if len(entity.attributes) > 20:
            artifact.warnings.append(
                f"Entidad con {len(entity.attributes)} atributos — "
                "BP recomienda máximo 20 atributos por entidad"
            )

        return artifact

    def _process_page(
        self,
        page: PageSchema,
        mpr_path: Path,
        policy: ConflictPolicy,
        input_hash: str,
    ) -> DryRunArtifact:
        """Procesa una página: idempotency check + BP evaluation."""
        artifact = DryRunArtifact(
            artifact_type=ArtifactType.PAGE,
            name=page.name,
            module=page.module,
        )

        exists = self._check_exists(mpr_path, "page", page.module, page.name)
        if exists:
            artifact.conflict = self._resolve_conflict(policy)
            if policy == ConflictPolicy.SKIP:
                artifact.will_execute = False
                artifact.warnings.append(
                    f"Page '{page.name}' ya existe — se omitirá"
                )

        bp_desc = (
            f"Page '{page.name}' of type {page.page_type.value} "
            f"for entity '{page.entity}' in module '{page.module}' "
            f"using layout '{page.layout}'"
        )
        artifact.bp_evaluation = self._evaluate_bp(bp_desc, input_hash)

        return artifact

    def _process_microflow(
        self,
        mf: MicroflowSchema,
        mpr_path: Path,
        policy: ConflictPolicy,
        input_hash: str,
    ) -> DryRunArtifact:
        """Procesa un microflow: idempotency check + BP evaluation."""
        artifact = DryRunArtifact(
            artifact_type=ArtifactType.MICROFLOW,
            name=mf.name,
            module=mf.module,
        )

        exists = self._check_exists(mpr_path, "microflow", mf.module, mf.name)
        if exists:
            artifact.conflict = self._resolve_conflict(policy)
            if policy == ConflictPolicy.SKIP:
                artifact.will_execute = False
                artifact.warnings.append(
                    f"Microflow '{mf.name}' ya existe — se omitirá"
                )

        bp_desc = (
            f"Microflow '{mf.name}' of type {mf.microflow_type.value} "
            f"for entity '{mf.entity}' in module '{mf.module}'"
        )
        artifact.bp_evaluation = self._evaluate_bp(bp_desc, input_hash)

        return artifact

    def _check_exists(
        self, mpr_path: Path, artifact_type: str, module: str, name: str
    ) -> bool:
        """Verifica si un artefacto ya existe via SDK Bridge."""
        try:
            return self._sdk.check_artifact_exists(
                mpr_path, artifact_type, module, name
            )
        except Exception as e:
            logger.warning(
                "idempotency_check_failed",
                artifact_type=artifact_type,
                name=name,
                error=str(e),
            )
            return False

    def _evaluate_bp(self, pattern_description: str, input_hash: str) -> BPEvaluation | None:
        """Evalúa un patrón contra BPs si el evaluator está disponible."""
        if self._bp_evaluator is None:
            return None

        try:
            return self._bp_evaluator.evaluate(
                pattern_description, input_hash=input_hash
            )
        except Exception as e:
            logger.warning("bp_evaluation_failed", error=str(e))
            return None

    def _build_entity_bp_patterns(self, entity: EntitySchema) -> str:
        """Construye descripción del patrón de una entidad para evaluación BP."""
        parts = [
            f"Entity '{entity.name}' in module '{entity.module}'",
            f"with {len(entity.attributes)} attributes",
        ]

        if entity.access_rules:
            roles = [r.role for r in entity.access_rules]
            parts.append(f"with access rules for roles: {', '.join(roles)}")
        else:
            parts.append("without explicit access rules")

        if entity.is_persistable:
            parts.append("(persistable)")
        else:
            parts.append("(non-persistable)")

        # Naming check
        if not entity.name:
            parts.append("with empty name")
        elif entity.name[0].isupper() and "_" not in entity.name:
            parts.append("using PascalCase naming")
        elif "_" in entity.name:
            parts.append("using snake_case naming")
        else:
            parts.append(f"with naming pattern: {entity.name}")

        return " ".join(parts)

    @staticmethod
    def _resolve_conflict(policy: ConflictPolicy) -> ConflictStatus:
        """Mapea política de conflicto a estado de conflicto."""
        return {
            ConflictPolicy.SKIP: ConflictStatus.EXISTS_SKIP,
            ConflictPolicy.OVERWRITE: ConflictStatus.EXISTS_OVERWRITE,
            ConflictPolicy.ABORT: ConflictStatus.EXISTS_ABORT,
        }[policy]

    def _log_dry_run(self, report: DryRunReport, input_hash: str) -> None:
        """Registra el dry-run en el decision logger."""
        if self._decision_logger is None:
            return

        self._decision_logger.log(
            operation="dry_run",
            input_hash=input_hash,
            action_taken="aborted" if report.aborted else "dry_run_complete",
            warnings=[report.abort_reason] if report.aborted else [],
            extra={
                "total_artifacts": len(report.artifacts),
                "conforme": report.total_conforme,
                "no_conforme": report.total_no_conforme,
                "sin_datos": report.total_sin_datos,
                "conflicts": report.total_conflicts,
                "policy": report.conflict_policy.value,
                "strict": report.strict_mode,
            },
        )
