"""Validador de convenciones de naming basado en copeinca_conventions.yaml.

Verifica que los nombres de artefactos generados sigan los patrones
definidos en el archivo de convenciones del proyecto.

Checks:
- Entidades: PascalCase
- Microflows: {Prefix}_{Entity}_{Action} pattern
- Páginas: {Entity}_{Action} pattern
- Atributos: PascalCase (no underscores excepto prefijo de módulo)
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import structlog

from mendex.schema.intermediate import IntermediateSchema
from mendex.validators.post_generation import (
    Severity,
    ValidationIssue,
    ValidationReport,
)

logger = structlog.get_logger(__name__)

# Known microflow prefixes
MF_PREFIXES = {
    "ACT",   # Action
    "VAL",   # Validation
    "DS",    # DataSource
    "SUB",   # Sub-microflow
    "ASe",   # After Startup
    "BCo",   # Before Commit
    "ACo",   # After Commit
    "BDe",   # Before Delete
    "OCl",   # On Change
}

# Known page suffixes
PAGE_SUFFIXES = {
    "Overview",
    "NewEdit",
    "New",
    "Edit",
    "Detail",
    "Configuracion",
}

PASCAL_CASE_RE = re.compile(r"^[A-Z][a-zA-Z0-9]*$")


def is_pascal_case(name: str) -> bool:
    """Check if name follows PascalCase convention.

    Must start with uppercase, contain at least one lowercase letter,
    and have no underscores.
    """
    if not PASCAL_CASE_RE.match(name):
        return False
    # Must have at least one lowercase letter (not ALL CAPS)
    return any(c.islower() for c in name)


def load_conventions(path: Path | None = None) -> dict[str, Any]:
    """Load conventions from YAML file."""
    if path is None:
        # Default path relative to project root
        candidates = [
            Path("conventions/copeinca_conventions.yaml"),
            Path("copeinca_conventions.yaml"),
        ]
        for candidate in candidates:
            if candidate.exists():
                path = candidate
                break

    if path is None or not path.exists():
        return {}

    try:
        import yaml

        with open(path) as f:
            return yaml.safe_load(f) or {}
    except ImportError:
        logger.warning("pyyaml_not_installed", msg="Cannot load conventions YAML")
        return {}
    except Exception as e:
        logger.warning("conventions_load_error", error=str(e))
        return {}


class ConventionsValidator:
    """Valida naming conventions de un IntermediateSchema.

    Uso:
        validator = ConventionsValidator()
        report = validator.validate(schema)
    """

    def __init__(self, conventions_path: Path | None = None) -> None:
        self._conventions = load_conventions(conventions_path)

    def validate(self, schema: IntermediateSchema) -> ValidationReport:
        """Ejecuta validación de convenciones."""
        report = ValidationReport()

        self._validate_entity_names(schema, report)
        self._validate_attribute_names(schema, report)
        self._validate_microflow_names(schema, report)
        self._validate_page_names(schema, report)

        return report

    def _validate_entity_names(
        self,
        schema: IntermediateSchema,
        report: ValidationReport,
    ) -> None:
        """Entidades deben ser PascalCase."""
        for entity in schema.entities:
            if not is_pascal_case(entity.name):
                report.issues.append(
                    ValidationIssue(
                        severity=Severity.WARNING,
                        category="naming",
                        artifact_type="entity",
                        artifact_name=entity.name,
                        message=(
                            f"Entity name '{entity.name}' is not PascalCase"
                        ),
                    )
                )

    def _validate_attribute_names(
        self,
        schema: IntermediateSchema,
        report: ValidationReport,
    ) -> None:
        """Atributos deben ser PascalCase (con posible prefijo módulo)."""
        for entity in schema.entities:
            for attr in entity.attributes:
                name = attr.name
                # Allow module prefix like SGP_NombreCampo
                if "_" in name:
                    parts = name.split("_", 1)
                    # If first part is all-caps short prefix (2-4 chars), allow it
                    if len(parts[0]) <= 4 and parts[0].isupper():
                        name = parts[1]

                if not is_pascal_case(name):
                    report.issues.append(
                        ValidationIssue(
                            severity=Severity.INFO,
                            category="naming",
                            artifact_type="attribute",
                            artifact_name=f"{entity.name}.{attr.name}",
                            message=(
                                f"Attribute name '{attr.name}' doesn't follow "
                                f"PascalCase convention"
                            ),
                        )
                    )

    def _validate_microflow_names(
        self,
        schema: IntermediateSchema,
        report: ValidationReport,
    ) -> None:
        """Microflows deben seguir {Prefix}_{Entity}_{Action}."""
        for mf in schema.microflows:
            name = mf.name
            # Check if it has a recognized prefix
            has_prefix = False
            for prefix in MF_PREFIXES:
                if name.startswith(f"{prefix}_"):
                    has_prefix = True
                    break

            if not has_prefix:
                # Some microflows don't need prefix (e.g., Afterstartup)
                # Only warn if it contains underscore but with wrong prefix
                if "_" in name:
                    prefix_part = name.split("_")[0]
                    if prefix_part not in MF_PREFIXES:
                        report.issues.append(
                            ValidationIssue(
                                severity=Severity.INFO,
                                category="naming",
                                artifact_type="microflow",
                                artifact_name=mf.name,
                                message=(
                                    f"Microflow prefix '{prefix_part}' is not a "
                                    f"recognized convention prefix. "
                                    f"Known: {', '.join(sorted(MF_PREFIXES))}"
                                ),
                            )
                        )

    def _validate_page_names(
        self,
        schema: IntermediateSchema,
        report: ValidationReport,
    ) -> None:
        """Páginas deben seguir {Entity}_{Action}."""
        for page in schema.pages:
            name = page.name
            # Check if it follows Entity_Action pattern
            if "_" not in name and name != "Configuracion":
                report.issues.append(
                    ValidationIssue(
                        severity=Severity.INFO,
                        category="naming",
                        artifact_type="page",
                        artifact_name=page.name,
                        message=(
                            f"Page name '{name}' doesn't follow "
                            f"'Entity_Action' pattern"
                        ),
                    )
                )
            elif "_" in name:
                suffix = name.rsplit("_", 1)[-1]
                if suffix not in PAGE_SUFFIXES:
                    report.issues.append(
                        ValidationIssue(
                            severity=Severity.INFO,
                            category="naming",
                            artifact_type="page",
                            artifact_name=page.name,
                            message=(
                                f"Page suffix '{suffix}' is not a recognized "
                                f"convention suffix. "
                                f"Known: {', '.join(sorted(PAGE_SUFFIXES))}"
                            ),
                        )
                    )
