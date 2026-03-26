"""Validador post-generación para verificar integridad de artefactos.

Después de que todos los generadores corren (entities, pages, microflows,
associations), este validador verifica que las referencias cruzadas son
válidas y no hay artefactos huérfanos.

Checks:
1. Microflows referenciados en botones existen
2. Páginas referenciadas en botones existen
3. Entidades referenciadas en pages/microflows existen
4. Asociaciones apuntan a entidades válidas
5. Huérfanos: páginas sin entidad, microflows sin actividades
6. Convenciones de naming (delegado a conventions.py)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import structlog

from mendex.schema.intermediate import IntermediateSchema, MicroflowType, PageType

logger = structlog.get_logger(__name__)


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class ValidationIssue:
    """Un problema detectado en la validación."""

    severity: Severity
    category: str
    message: str
    artifact_type: str = ""
    artifact_name: str = ""

    def __str__(self) -> str:
        prefix = {"error": "[ERROR]", "warning": "[WARN]", "info": "[INFO]"}
        return (
            f"{prefix[self.severity]} [{self.category}] "
            f"{self.artifact_type}:{self.artifact_name} — {self.message}"
        )


@dataclass
class ValidationReport:
    """Resultado completo de la validación post-generación."""

    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == Severity.ERROR]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == Severity.WARNING]

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    @property
    def error_count(self) -> int:
        return len(self.errors)

    @property
    def warning_count(self) -> int:
        return len(self.warnings)

    def summary(self) -> str:
        lines = [
            f"Validation: {self.error_count} errors, {self.warning_count} warnings"
        ]
        for issue in self.issues:
            lines.append(f"  {issue}")
        return "\n".join(lines)


class PostGenerationValidator:
    """Valida la integridad de un IntermediateSchema antes/después de generar.

    Uso:
        validator = PostGenerationValidator()
        report = validator.validate(schema)
        if not report.is_valid:
            print(report.summary())
    """

    def validate(self, schema: IntermediateSchema) -> ValidationReport:
        """Ejecuta todas las validaciones sobre el schema."""
        report = ValidationReport()

        # Build lookup sets
        entity_names = {e.name for e in schema.entities}
        entity_qualified = {f"{e.module}.{e.name}" for e in schema.entities}
        microflow_names = {mf.name for mf in schema.microflows}
        microflow_qualified = {
            f"{mf.module}.{mf.name}" for mf in schema.microflows
        }
        page_names = {p.name for p in schema.pages}

        self._validate_page_entities(schema, entity_names, report)
        self._validate_microflow_entities(schema, entity_names, report)
        self._validate_association_entities(schema, entity_names, report)
        self._validate_button_references(
            schema, microflow_qualified, microflow_names, page_names, report
        )
        self._validate_orphans(schema, report)
        self._validate_microflow_calls(
            schema, microflow_qualified, microflow_names, report
        )
        self._validate_lookup_ds_microflows(schema, microflow_names, entity_names, report)
        self._validate_return_types(schema, entity_names, report)

        if report.is_valid:
            logger.info(
                "post_generation_validation_passed",
                warnings=report.warning_count,
            )
        else:
            logger.warning(
                "post_generation_validation_failed",
                errors=report.error_count,
                warnings=report.warning_count,
            )

        return report

    def _validate_page_entities(
        self,
        schema: IntermediateSchema,
        entity_names: set[str],
        report: ValidationReport,
    ) -> None:
        """Verifica que cada página referencia una entidad existente."""
        for page in schema.pages:
            if page.entity and page.entity not in entity_names:
                report.issues.append(
                    ValidationIssue(
                        severity=Severity.ERROR,
                        category="entity_ref",
                        artifact_type="page",
                        artifact_name=page.name,
                        message=f"Entity '{page.entity}' not found in schema",
                    )
                )
            if page.filter_entity and page.filter_entity not in entity_names:
                report.issues.append(
                    ValidationIssue(
                        severity=Severity.ERROR,
                        category="entity_ref",
                        artifact_type="page",
                        artifact_name=page.name,
                        message=f"Filter entity '{page.filter_entity}' not found in schema",
                    )
                )

    def _validate_microflow_entities(
        self,
        schema: IntermediateSchema,
        entity_names: set[str],
        report: ValidationReport,
    ) -> None:
        """Verifica que cada microflow referencia una entidad existente."""
        for mf in schema.microflows:
            if mf.entity and mf.entity not in entity_names:
                report.issues.append(
                    ValidationIssue(
                        severity=Severity.ERROR,
                        category="entity_ref",
                        artifact_type="microflow",
                        artifact_name=mf.name,
                        message=f"Entity '{mf.entity}' not found in schema",
                    )
                )

    def _validate_association_entities(
        self,
        schema: IntermediateSchema,
        entity_names: set[str],
        report: ValidationReport,
    ) -> None:
        """Verifica que las asociaciones apuntan a entidades válidas."""
        for assoc in schema.associations:
            if assoc.parent_entity not in entity_names:
                report.issues.append(
                    ValidationIssue(
                        severity=Severity.ERROR,
                        category="entity_ref",
                        artifact_type="association",
                        artifact_name=assoc.name,
                        message=f"Parent entity '{assoc.parent_entity}' not found",
                    )
                )
            if assoc.child_entity not in entity_names:
                report.issues.append(
                    ValidationIssue(
                        severity=Severity.ERROR,
                        category="entity_ref",
                        artifact_type="association",
                        artifact_name=assoc.name,
                        message=f"Child entity '{assoc.child_entity}' not found",
                    )
                )

    def _validate_button_references(
        self,
        schema: IntermediateSchema,
        microflow_qualified: set[str],
        microflow_names: set[str],
        page_names: set[str],
        report: ValidationReport,
    ) -> None:
        """Verifica que botones apuntan a microflows/páginas existentes."""
        for page in schema.pages:
            for button in page.buttons:
                # Check microflow references
                if button.microflow:
                    mf_ref = button.microflow
                    # Try qualified and unqualified
                    if (
                        mf_ref not in microflow_qualified
                        and mf_ref not in microflow_names
                    ):
                        # Also try extracting just the name part
                        mf_simple = mf_ref.split(".")[-1] if "." in mf_ref else mf_ref
                        if mf_simple not in microflow_names:
                            report.issues.append(
                                ValidationIssue(
                                    severity=Severity.WARNING,
                                    category="button_ref",
                                    artifact_type="page",
                                    artifact_name=page.name,
                                    message=(
                                        f"Button '{button.label}' references microflow "
                                        f"'{mf_ref}' which is not in schema"
                                    ),
                                )
                            )

                # Check page references
                if button.target_page:
                    if button.target_page not in page_names:
                        report.issues.append(
                            ValidationIssue(
                                severity=Severity.WARNING,
                                category="button_ref",
                                artifact_type="page",
                                artifact_name=page.name,
                                message=(
                                    f"Button '{button.label}' references page "
                                    f"'{button.target_page}' which is not in schema"
                                ),
                            )
                        )

    def _validate_orphans(
        self,
        schema: IntermediateSchema,
        report: ValidationReport,
    ) -> None:
        """Detecta artefactos huérfanos o vacíos."""
        # Pages without entity (except Config which is valid)
        for page in schema.pages:
            if not page.entity and page.page_type != PageType.CONFIG:
                report.issues.append(
                    ValidationIssue(
                        severity=Severity.WARNING,
                        category="orphan",
                        artifact_type="page",
                        artifact_name=page.name,
                        message="Page has no entity reference",
                    )
                )

        # Custom microflows without any activities or description
        for mf in schema.microflows:
            if (
                mf.microflow_type == MicroflowType.CUSTOM
                and not mf.logic_description
            ):
                report.issues.append(
                    ValidationIssue(
                        severity=Severity.INFO,
                        category="orphan",
                        artifact_type="microflow",
                        artifact_name=mf.name,
                        message="Custom microflow has no logic_description",
                    )
                )

    def _validate_microflow_calls(
        self,
        schema: IntermediateSchema,
        microflow_qualified: set[str],
        microflow_names: set[str],
        report: ValidationReport,
    ) -> None:
        """Verifica que MicroflowCallActivity targets existen."""
        for mf in schema.microflows:
            if mf.microflow_type == MicroflowType.SAVE:
                # Save microflows call VAL_{Entity}_Validate
                val_name = f"VAL_{mf.entity}_Validate"
                if val_name not in microflow_names:
                    report.issues.append(
                        ValidationIssue(
                            severity=Severity.WARNING,
                            category="microflow_call",
                            artifact_type="microflow",
                            artifact_name=mf.name,
                            message=(
                                f"Save microflow calls '{val_name}' "
                                f"which is not in schema"
                            ),
                        )
                    )

    def _validate_lookup_ds_microflows(
        self,
        schema: IntermediateSchema,
        microflow_names: set[str],
        entity_names: set[str],
        report: ValidationReport,
    ) -> None:
        """Verifica que lookup entities tienen DS_OS_ microflows correspondientes."""
        for entity in schema.entities:
            if entity.is_lookup:
                ds_name = f"DS_OS_{entity.name}"
                if ds_name not in microflow_names:
                    report.issues.append(
                        ValidationIssue(
                            severity=Severity.WARNING,
                            category="selectable_objects",
                            artifact_type="entity",
                            artifact_name=entity.name,
                            message=(
                                f"Lookup entity '{entity.name}' has no "
                                f"DS_OS_ microflow in schema"
                            ),
                        )
                    )

    def _validate_return_types(
        self,
        schema: IntermediateSchema,
        entity_names: set[str],
        report: ValidationReport,
    ) -> None:
        """Verifica que return_entity en DataSource microflows es válido."""
        for mf in schema.microflows:
            if mf.microflow_type == MicroflowType.DATA_SOURCE and mf.return_entity:
                if mf.return_entity not in entity_names:
                    report.issues.append(
                        ValidationIssue(
                            severity=Severity.ERROR,
                            category="return_type",
                            artifact_type="microflow",
                            artifact_name=mf.name,
                            message=(
                                f"Return entity '{mf.return_entity}' not found in schema"
                            ),
                        )
                    )
