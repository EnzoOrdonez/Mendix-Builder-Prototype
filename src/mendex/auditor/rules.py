"""Reglas deterministas de auditoría para artefactos Mendix.

Cada regla implementa AuditRule y verifica un aspecto específico
sin necesidad de LLM. Basadas en las buenas prácticas oficiales
de Mendix y convenciones comunes.

Fase 10: Implementación completa.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any


# ─── Modelos ──────────────────────────────────────────────────


class FindingSeverity(str, Enum):
    """Severidad de un hallazgo de auditoría."""

    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"

    @property
    def severity_order(self) -> int:
        return {"critical": 3, "warning": 2, "info": 1}[self.value]


@dataclass
class AuditFinding:
    """Un hallazgo individual de auditoría."""

    rule_id: str
    severity: FindingSeverity
    message: str
    recommendation: str | None = None

    @property
    def severity_order(self) -> int:
        return self.severity.severity_order

    def as_report_line(self) -> str:
        icon = {
            FindingSeverity.CRITICAL: "✗",
            FindingSeverity.WARNING: "⚠",
            FindingSeverity.INFO: "ℹ",
        }
        line = f"{icon[self.severity]} [{self.rule_id}] {self.message}"
        if self.recommendation:
            line += f"\n      → {self.recommendation}"
        return line

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "severity": self.severity.value,
            "message": self.message,
            "recommendation": self.recommendation,
        }


# ─── Base ─────────────────────────────────────────────────────


class AuditRule(ABC):
    """Regla de auditoría determinista."""

    rule_id: str
    description: str
    artifact_types: list[str]  # ["entity", "page", "microflow"]

    def applies_to(self, artifact_type: str) -> bool:
        return artifact_type in self.artifact_types

    @abstractmethod
    def check(self, context: dict[str, Any]) -> AuditFinding | None:
        """Evalúa la regla. Retorna AuditFinding si hay violación, None si ok."""
        ...


# ─── Reglas de naming ─────────────────────────────────────────


class EntityPascalCaseRule(AuditRule):
    """Las entidades deben usar PascalCase (BP oficial Mendix)."""

    rule_id = "NM-001"
    description = "Entity names must use PascalCase"
    artifact_types = ["entity"]

    def check(self, context: dict[str, Any]) -> AuditFinding | None:
        name = context.get("name", "")
        if not name:
            return AuditFinding(
                rule_id=self.rule_id,
                severity=FindingSeverity.CRITICAL,
                message="Entity name is empty",
                recommendation="Provide a meaningful PascalCase name",
            )
        # PascalCase: starts with uppercase, no underscores
        if not name[0].isupper() or "_" in name:
            return AuditFinding(
                rule_id=self.rule_id,
                severity=FindingSeverity.WARNING,
                message=f"Entity '{name}' does not use PascalCase naming",
                recommendation=f"Rename to '{self._to_pascal(name)}'",
            )
        return None

    @staticmethod
    def _to_pascal(name: str) -> str:
        parts = re.split(r"[_\-\s]+", name)
        return "".join(p.capitalize() for p in parts if p)


class PageNamingRule(AuditRule):
    """Las páginas deben seguir el patrón Entity_Action (BP Mendix)."""

    rule_id = "NM-002"
    description = "Page names should follow Entity_Action pattern"
    artifact_types = ["page"]

    _VALID_SUFFIXES = (
        "_Create", "_Edit", "_Overview", "_Detail",
        "_New", "_List", "_View", "_Select",
    )

    def check(self, context: dict[str, Any]) -> AuditFinding | None:
        name = context.get("name", "")
        if not name:
            return AuditFinding(
                rule_id=self.rule_id,
                severity=FindingSeverity.CRITICAL,
                message="Page name is empty",
            )
        if not any(name.endswith(suffix) for suffix in self._VALID_SUFFIXES):
            return AuditFinding(
                rule_id=self.rule_id,
                severity=FindingSeverity.INFO,
                message=(
                    f"Page '{name}' does not follow Entity_Action naming pattern"
                ),
                recommendation=(
                    "Use pattern like 'Customer_Create', 'Order_Overview'"
                ),
            )
        return None


class MicroflowNamingRule(AuditRule):
    """Los microflows deben seguir el patrón Prefijo_Entity_Action (BP Mendix)."""

    rule_id = "NM-003"
    description = "Microflow names should follow PREFIX_Entity_Action pattern"
    artifact_types = ["microflow"]

    _VALID_PREFIXES = (
        "ACT_", "VAL_", "SUB_", "DS_", "IVK_",
        "OCh_", "OEx_", "TA_", "BCo_", "BAf_",
        "BDe_", "BCr_",
    )

    def check(self, context: dict[str, Any]) -> AuditFinding | None:
        name = context.get("name", "")
        if not name:
            return AuditFinding(
                rule_id=self.rule_id,
                severity=FindingSeverity.CRITICAL,
                message="Microflow name is empty",
            )
        if not any(name.startswith(prefix) for prefix in self._VALID_PREFIXES):
            return AuditFinding(
                rule_id=self.rule_id,
                severity=FindingSeverity.WARNING,
                message=(
                    f"Microflow '{name}' does not follow PREFIX_Entity_Action naming"
                ),
                recommendation=(
                    "Use prefixes: ACT_ (action), VAL_ (validation), "
                    "SUB_ (sub), DS_ (data source), etc."
                ),
            )
        return None


# ─── Reglas de estructura ────────────────────────────────────


class EntityAttributeCountRule(AuditRule):
    """Las entidades no deben tener demasiados atributos (BP: max ~20)."""

    rule_id = "ST-001"
    description = "Entities should not exceed 20 attributes"
    artifact_types = ["entity"]

    MAX_ATTRIBUTES = 20
    WARN_THRESHOLD = 15

    def check(self, context: dict[str, Any]) -> AuditFinding | None:
        count = context.get("attribute_count", 0)
        name = context.get("name", "")

        if count > self.MAX_ATTRIBUTES:
            return AuditFinding(
                rule_id=self.rule_id,
                severity=FindingSeverity.WARNING,
                message=(
                    f"Entity '{name}' has {count} attributes "
                    f"(recommended max: {self.MAX_ATTRIBUTES})"
                ),
                recommendation=(
                    "Consider splitting into multiple entities or using "
                    "a 1-1 association for less-used attributes"
                ),
            )
        if self.WARN_THRESHOLD <= count < self.MAX_ATTRIBUTES:
            return AuditFinding(
                rule_id=self.rule_id,
                severity=FindingSeverity.INFO,
                message=(
                    f"Entity '{name}' has {count} attributes "
                    f"(approaching the {self.MAX_ATTRIBUTES} limit)"
                ),
            )
        return None


class AttributeNamingRule(AuditRule):
    """Los atributos deben usar PascalCase (BP Mendix)."""

    rule_id = "NM-004"
    description = "Attribute names must use PascalCase"
    artifact_types = ["entity"]

    def check(self, context: dict[str, Any]) -> AuditFinding | None:
        attributes: list[str] = context.get("attributes", [])
        bad_attrs = [
            a for a in attributes
            if a and (not a[0].isupper() or "_" in a)
        ]
        if bad_attrs:
            return AuditFinding(
                rule_id=self.rule_id,
                severity=FindingSeverity.WARNING,
                message=(
                    f"Attributes with non-PascalCase names: "
                    f"{', '.join(bad_attrs[:5])}"
                    f"{' ...' if len(bad_attrs) > 5 else ''}"
                ),
                recommendation="Rename attributes to PascalCase",
            )
        return None


class ModuleNamingRule(AuditRule):
    """Los módulos deben usar PascalCase sin espacios."""

    rule_id = "NM-005"
    description = "Module names should use PascalCase without spaces"
    artifact_types = ["entity", "page", "microflow"]

    def check(self, context: dict[str, Any]) -> AuditFinding | None:
        module = context.get("module", "")
        if not module:
            return None
        if " " in module:
            return AuditFinding(
                rule_id=self.rule_id,
                severity=FindingSeverity.WARNING,
                message=f"Module '{module}' contains spaces",
                recommendation="Use PascalCase without spaces",
            )
        return None


# ─── Registry ─────────────────────────────────────────────────


def get_default_rules() -> list[AuditRule]:
    """Retorna la lista completa de reglas de auditoría por defecto."""
    return [
        EntityPascalCaseRule(),
        PageNamingRule(),
        MicroflowNamingRule(),
        EntityAttributeCountRule(),
        AttributeNamingRule(),
        ModuleNamingRule(),
    ]
