"""Generador de páginas (Create/Edit/Overview) via Model SDK.

Recibe PageSchema del IntermediateSchema y crea páginas en el .mpr
con los widgets apropiados según el tipo de atributo de la entidad
asociada. Cada tipo de atributo mapea a un widget Mendix específico.

Fase 9: Implementación completa.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

from mendex.bridge.sdk_client import SDKClient, SDKClientError
from mendex.logging.decision_logger import DecisionLogger
from mendex.schema.intermediate import (
    EntitySchema,
    IntermediateSchema,
    MendixDataType,
    PageSchema,
    PageType,
    WidgetType,
)

logger = structlog.get_logger(__name__)


# ─── Widget mapping ─────────────────────────────────────────

# Mapeo de MendixDataType → widget Mendix a crear en la página
WIDGET_FOR_TYPE: dict[MendixDataType, str] = {
    MendixDataType.STRING: "TextBox",
    MendixDataType.INTEGER: "TextBox",  # Mendix usa TextBox con formatting
    MendixDataType.LONG: "TextBox",
    MendixDataType.DECIMAL: "TextBox",
    MendixDataType.BOOLEAN: "CheckBox",
    MendixDataType.DATETIME: "DatePicker",
    MendixDataType.ENUMERATION: "DropDown",
    MendixDataType.HASHED_STRING: "TextBox",
    MendixDataType.AUTONUMBER: "TextBox",
}


# ─── Resultado ───────────────────────────────────────────────


@dataclass
class PageResult:
    """Resultado de la creación de una página."""

    name: str
    module: str
    page_type: str
    success: bool
    widgets_count: int = 0
    error: str | None = None

    def __repr__(self) -> str:
        status = "✓" if self.success else "✗"
        return f"PageResult({status} {self.module}.{self.name} [{self.page_type}])"


@dataclass
class PageGenerationResult:
    """Resultado completo de la generación de páginas."""

    pages: list[PageResult] = field(default_factory=list)
    total_created: int = 0
    total_skipped: int = 0
    total_failed: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.total_failed == 0

    def summary(self) -> str:
        return (
            f"Page Generation: {self.total_created} created, "
            f"{self.total_skipped} skipped, {self.total_failed} failed"
        )


# ─── Generador ───────────────────────────────────────────────


class PageGenerator:
    """Genera páginas de formulario en un .mpr via SDK Bridge.

    Crea páginas con widgets apropiados según el tipo de cada atributo
    de la entidad asociada. Soporta Create, Edit y Overview.

    Uso:
        generator = PageGenerator(sdk_client=sdk_client)
        result = generator.generate(schema, mpr_path)
    """

    def __init__(
        self,
        sdk_client: SDKClient,
        decision_logger: DecisionLogger | None = None,
        skip_existing: bool = True,
    ) -> None:
        self._sdk = sdk_client
        self._decision_logger = decision_logger
        self._skip_existing = skip_existing

    def generate(
        self,
        schema: IntermediateSchema,
        mpr_path: Path,
        *,
        input_hash: str = "",
    ) -> PageGenerationResult:
        """Genera todas las páginas del schema.

        Args:
            schema: IntermediateSchema con páginas a crear.
            mpr_path: Path al .mpr.
            input_hash: Hash del input (para logging).

        Returns:
            PageGenerationResult.
        """
        result = PageGenerationResult()

        if not schema.pages:
            return result

        # Build entity lookup for widget generation
        entity_map = {e.name: e for e in schema.entities}

        logger.info(
            "page_generation_started",
            pages=len(schema.pages),
        )

        for page in schema.pages:
            entity = entity_map.get(page.entity)
            page_result = self._create_page(page, entity, mpr_path)
            result.pages.append(page_result)

            if page_result.success and page_result.error is None:
                result.total_created += 1
            elif page_result.success and page_result.error:
                # Skipped (exists)
                result.total_skipped += 1
            else:
                result.total_failed += 1
                result.errors.append(page_result.error or "Unknown error")

        # Log
        if self._decision_logger:
            self._decision_logger.log(
                operation="page_generation",
                input_hash=input_hash,
                action_taken="generated" if result.success else "failed",
                warnings=result.errors,
                extra={
                    "total_created": result.total_created,
                    "total_skipped": result.total_skipped,
                    "total_failed": result.total_failed,
                },
            )

        logger.info(
            "page_generation_complete",
            created=result.total_created,
            skipped=result.total_skipped,
            failed=result.total_failed,
        )

        return result

    def generate_single(
        self,
        page: PageSchema,
        entity: EntitySchema | None,
        mpr_path: Path,
    ) -> PageResult:
        """Genera una sola página."""
        return self._create_page(page, entity, mpr_path)

    def _create_page(
        self,
        page: PageSchema,
        entity: EntitySchema | None,
        mpr_path: Path,
    ) -> PageResult:
        """Crea una página via SDK Bridge."""
        # Check existing
        if self._skip_existing:
            try:
                if self._sdk.check_artifact_exists(
                    mpr_path, "page", page.module, page.name
                ):
                    return PageResult(
                        name=page.name,
                        module=page.module,
                        page_type=page.page_type.value,
                        success=True,
                        error=f"Page '{page.name}' ya existe — omitida",
                    )
            except SDKClientError:
                pass

        # Build page data
        page_data = self._build_page_data(page, entity)

        try:
            self._sdk.create_page(mpr_path, page_data)
            widgets_count = len(page_data.get("widgets", []))
            logger.info(
                "page_created",
                page=page.name,
                module=page.module,
                type=page.page_type.value,
                widgets=widgets_count,
            )
            return PageResult(
                name=page.name,
                module=page.module,
                page_type=page.page_type.value,
                success=True,
                widgets_count=widgets_count,
            )
        except SDKClientError as e:
            return PageResult(
                name=page.name,
                module=page.module,
                page_type=page.page_type.value,
                success=False,
                error=str(e),
            )

    def _build_page_data(
        self,
        page: PageSchema,
        entity: EntitySchema | None,
    ) -> dict[str, Any]:
        """Construye los datos de la página para el SDK Bridge."""
        widgets = self._generate_widgets(page, entity) if entity else []

        data: dict[str, Any] = {
            "name": page.name,
            "page_type": page.page_type.value,
            "entity": page.entity,
            "module": page.module,
            "title": page.title or f"{page.entity} — {page.page_type.value}",
            "layout": page.layout,
            "widgets": widgets,
        }

        return data

    def _generate_widgets(
        self,
        page: PageSchema,
        entity: EntitySchema,
    ) -> list[dict[str, Any]]:
        """Genera la lista de widgets para la página según el tipo.

        Create/Edit: widgets editables por atributo.
        Overview: columnas de tabla (read-only).
        """
        widgets: list[dict[str, Any]] = []

        if page.page_type in (PageType.CREATE, PageType.EDIT):
            for attr in entity.attributes:
                # AutoNumber no es editable en Create/Edit
                if (
                    attr.mendix_type == MendixDataType.AUTONUMBER
                    and page.page_type == PageType.CREATE
                ):
                    continue

                widget_type = WIDGET_FOR_TYPE.get(
                    attr.mendix_type, "TextBox"
                )
                # Override with explicit widget_type if set
                if attr.widget_type:
                    widget_type = self._map_schema_widget(attr.widget_type)

                widgets.append({
                    "widget_type": widget_type,
                    "attribute": attr.name,
                    "label": attr.label,
                    "editable": True,
                    "required": attr.required,
                })

        elif page.page_type == PageType.OVERVIEW:
            for attr in entity.attributes:
                widgets.append({
                    "widget_type": "DataGridColumn",
                    "attribute": attr.name,
                    "label": attr.label,
                    "editable": False,
                    "required": False,
                })

        return widgets

    @staticmethod
    def _map_schema_widget(widget_type: WidgetType) -> str:
        """Mapea WidgetType del schema a nombre de widget Mendix."""
        return {
            WidgetType.TEXT_INPUT: "TextBox",
            WidgetType.NUMBER_INPUT: "TextBox",
            WidgetType.DATE_PICKER: "DatePicker",
            WidgetType.CHECK_BOX: "CheckBox",
            WidgetType.DROP_DOWN: "DropDown",
            WidgetType.TEXT_AREA: "TextArea",
            WidgetType.RADIO_BUTTONS: "RadioButtons",
            WidgetType.REFERENCE_SELECTOR: "ReferenceSelector",
        }.get(widget_type, "TextBox")
