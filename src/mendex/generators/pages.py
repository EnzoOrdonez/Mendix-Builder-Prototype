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
    AssociationSchema,
    AttributeSchema,
    ButtonSchema,
    EntitySchema,
    FieldVisibility,
    IntermediateSchema,
    MendixDataType,
    PageSchema,
    PageType,
    SectionSchema,
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
    MendixDataType.BINARY: "FileManager",
}

# Visibility rules: which FieldVisibility values are allowed per PageType
_VISIBILITY_ALLOWED: dict[PageType, set[FieldVisibility]] = {
    PageType.CREATE: {FieldVisibility.ALL, FieldVisibility.CREATE_ONLY},
    PageType.EDIT: {FieldVisibility.ALL, FieldVisibility.EDIT_ONLY},
    PageType.OVERVIEW: {FieldVisibility.ALL, FieldVisibility.OVERVIEW_ONLY},
    PageType.CONFIG: {FieldVisibility.ALL},
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

        # Build lookup associations per child entity
        lookup_assocs_by_entity: dict[str, list[AssociationSchema]] = {}
        for assoc in schema.associations:
            if assoc.is_lookup:
                lookup_assocs_by_entity.setdefault(assoc.child_entity, []).append(assoc)

        logger.info(
            "page_generation_started",
            pages=len(schema.pages),
        )

        # Build filter entity lookup
        filter_entity_map = {e.name: e for e in schema.entities if e.is_filter_entity}

        for page in schema.pages:
            entity = entity_map.get(page.entity)
            entity_lookups = lookup_assocs_by_entity.get(page.entity, [])
            filter_entity = filter_entity_map.get(page.filter_entity or "")
            page_result = self._create_page(
                page, entity, mpr_path, entity_lookups, filter_entity, entity_map
            )
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
        lookup_associations: list[AssociationSchema] | None = None,
    ) -> PageResult:
        """Genera una sola página."""
        return self._create_page(page, entity, mpr_path, lookup_associations or [])

    def _create_page(
        self,
        page: PageSchema,
        entity: EntitySchema | None,
        mpr_path: Path,
        lookup_associations: list[AssociationSchema] | None = None,
        filter_entity: EntitySchema | None = None,
        entity_map: dict[str, EntitySchema] | None = None,
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
        page_data = self._build_page_data(
            page, entity, lookup_associations or [], filter_entity, entity_map
        )

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
        lookup_associations: list[AssociationSchema] | None = None,
        filter_entity: EntitySchema | None = None,
        entity_map: dict[str, EntitySchema] | None = None,
    ) -> dict[str, Any]:
        """Construye los datos de la página para el SDK Bridge."""
        widgets = self._generate_widgets(
            page, entity, lookup_associations or [], filter_entity, entity_map
        ) if entity else []

        data: dict[str, Any] = {
            "name": page.name,
            "page_type": page.page_type.value,
            "entity": page.entity,
            "module": page.module,
            "title": page.title or f"{page.entity} — {page.page_type.value}",
            "layout": page.layout,
            "widgets": widgets,
        }

        # Include sections filtered by page type visibility
        if page.sections and entity:
            allowed = _VISIBILITY_ALLOWED.get(page.page_type, {FieldVisibility.ALL})
            visible_attrs = {
                a.name for a in entity.attributes if a.visibility in allowed
            }
            sections_data = []
            for sec in page.sections:
                filtered_attrs = [a for a in sec.attributes if a in visible_attrs]
                if filtered_attrs:
                    sections_data.append({
                        "name": sec.name,
                        "order": sec.order,
                        "attributes": filtered_attrs,
                    })
            if sections_data:
                data["sections"] = sections_data

        # Generate buttons (explicit or auto-derived)
        buttons = self._generate_buttons(page, entity)
        if buttons:
            data["buttons"] = buttons

        # Popup layout override
        if page.is_popup:
            data["layout"] = "PopupLayout"

        return data

    def _generate_widgets(
        self,
        page: PageSchema,
        entity: EntitySchema,
        lookup_associations: list[AssociationSchema] | None = None,
        filter_entity: EntitySchema | None = None,
        entity_map: dict[str, EntitySchema] | None = None,
    ) -> list[dict[str, Any]]:
        """Genera la lista de widgets para la página según el tipo.

        Create/Edit: widgets editables por atributo + ReferenceSelector
                     for lookup associations, filtered by visibility.
        Overview: columnas de tabla (read-only), filtered by visibility.
                  If filter_entity is set, adds filter DropDown widgets.
        Config: navigation list items for lookup CRUD pages.
        """
        allowed = _VISIBILITY_ALLOWED.get(page.page_type, {FieldVisibility.ALL})
        visible_attrs = [a for a in entity.attributes if a.visibility in allowed]

        widgets: list[dict[str, Any]] = []

        if page.page_type == PageType.CONFIG:
            # Config page: navigation items to lookup CRUD pages
            for nav_item in (page.navigation_items or []):
                widgets.append({
                    "widget_type": "NavigationListItem",
                    "target_page": nav_item,
                    "label": nav_item.replace("_", " "),
                })
            return widgets

        if page.page_type in (PageType.CREATE, PageType.EDIT):
            for attr in visible_attrs:
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

                widget_data: dict[str, Any] = {
                    "widget_type": widget_type,
                    "attribute": attr.name,
                    "label": attr.label,
                    "editable": True,
                    "required": attr.required,
                }
                if attr.section:
                    widget_data["section"] = attr.section
                if attr.conditional_visibility:
                    widget_data["conditional_visibility"] = {
                        "depends_on": attr.conditional_visibility.depends_on,
                        "operator": attr.conditional_visibility.operator,
                        "value": attr.conditional_visibility.value,
                    }
                widgets.append(widget_data)

            # Add ReferenceSelector widgets for lookup associations
            for assoc in (lookup_associations or []):
                if assoc.visibility not in allowed:
                    continue
                widget_data = {
                    "widget_type": "ReferenceSelector",
                    "association": assoc.name,
                    "display_attribute": "Name",
                    "label": assoc.label or assoc.parent_entity,
                    "editable": True,
                    "required": assoc.required,
                    "selectable_objects_source": f"DS_OS_{assoc.parent_entity}",
                }
                if assoc.section:
                    widget_data["section"] = assoc.section
                widgets.append(widget_data)

            # Add NestedListView widgets for master-detail
            for nested in (page.nested_lists or []):
                child_entity = (entity_map or {}).get(nested.child_entity)
                columns = []
                if child_entity:
                    for attr in child_entity.attributes[:5]:
                        columns.append({
                            "widget_type": "DataGridColumn",
                            "attribute": attr.name,
                            "label": attr.label,
                        })
                elif nested.display_attributes:
                    for attr_name in nested.display_attributes:
                        columns.append({
                            "widget_type": "DataGridColumn",
                            "attribute": attr_name,
                            "label": attr_name,
                        })

                nested_buttons = []
                if nested.allow_add:
                    nested_buttons.append({
                        "label": "Agregar",
                        "action": "show_page",
                        "target_page": nested.child_page or f"{nested.child_entity}_NewEdit",
                        "open_as": "popup",
                    })
                if nested.allow_delete:
                    nested_buttons.append({
                        "label": "Eliminar",
                        "action": "call_microflow",
                        "microflow": f"ACT_{nested.child_entity}_Delete",
                        "style": "Danger",
                    })

                widgets.append({
                    "widget_type": "NestedListView",
                    "child_entity": nested.child_entity,
                    "association": nested.association,
                    "columns": columns,
                    "buttons": nested_buttons,
                })

        elif page.page_type == PageType.OVERVIEW:
            # Add filter DropDown widgets if filter entity is set
            if filter_entity:
                for f_attr in filter_entity.attributes:
                    widgets.append({
                        "widget_type": "DropDown",
                        "attribute": f_attr.name,
                        "label": f_attr.label,
                        "editable": True,
                        "required": False,
                        "is_filter": True,
                        "filter_entity": filter_entity.name,
                    })

            for attr in visible_attrs:
                widget_data = {
                    "widget_type": "DataGridColumn",
                    "attribute": attr.name,
                    "label": attr.label,
                    "editable": False,
                    "required": False,
                }
                widgets.append(widget_data)

            # Add lookup association columns in overview
            for assoc in (lookup_associations or []):
                if assoc.visibility not in allowed:
                    continue
                widget_data = {
                    "widget_type": "DataGridColumn",
                    "association": assoc.name,
                    "display_attribute": "Name",
                    "label": assoc.label or assoc.parent_entity,
                    "editable": False,
                    "required": False,
                }
                widgets.append(widget_data)

            # Add SearchField widgets for DataGrid search bar
            if page.enable_search_bar:
                searchable_types = {
                    MendixDataType.STRING,
                    MendixDataType.DATETIME,
                    MendixDataType.ENUMERATION,
                }
                for attr in visible_attrs:
                    if attr.mendix_type in searchable_types:
                        widgets.append({
                            "widget_type": "SearchField",
                            "attribute": attr.name,
                            "label": attr.label,
                            "search_type": "contains" if attr.mendix_type == MendixDataType.STRING else "equals",
                        })
                # SearchField for lookup associations
                for assoc in (lookup_associations or []):
                    if assoc.visibility not in allowed:
                        continue
                    widgets.append({
                        "widget_type": "SearchField",
                        "association": assoc.name,
                        "display_attribute": "Name",
                        "label": assoc.label or assoc.parent_entity,
                        "search_type": "equals",
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
            WidgetType.FILE_UPLOAD: "FileManager",
            WidgetType.IMAGE_UPLOAD: "ImageUploader",
            WidgetType.RICH_TEXT: "RichTextEditor",
        }.get(widget_type, "TextBox")

    def _generate_buttons(
        self,
        page: PageSchema,
        entity: EntitySchema | None,
    ) -> list[dict[str, Any]]:
        """Genera botones para la página.

        Si page.buttons tiene items explícitos, los usa.
        Si no, auto-genera según el tipo de página:
        - Create/Edit: Guardar (Primary) + Cancelar
        - Overview: Nuevo + per-row Editar + per-row Eliminar
        - Config: sin botones
        """
        # Use explicit buttons if provided
        if page.buttons:
            return [
                {
                    "widget_type": "ActionButton",
                    "label": btn.label,
                    "button_type": btn.button_type.value,
                    "action": "call_microflow" if btn.microflow else "show_page" if btn.target_page else "close_page",
                    "microflow": btn.microflow,
                    "target_page": btn.target_page,
                    "style": btn.style,
                    "open_as": btn.open_as,
                    "placement": btn.placement,
                }
                for btn in page.buttons
            ]

        if not entity:
            return []

        entity_name = page.entity
        buttons: list[dict[str, Any]] = []

        if page.page_type in (PageType.CREATE, PageType.EDIT):
            buttons.append({
                "widget_type": "ActionButton",
                "label": "Guardar",
                "button_type": "Save",
                "action": "call_microflow",
                "microflow": f"ACT_{entity_name}_Save",
                "style": "Primary",
                "placement": "top",
            })
            buttons.append({
                "widget_type": "ActionButton",
                "label": "Cancelar",
                "button_type": "Cancel",
                "action": "close_page",
                "style": "Default",
                "placement": "top",
            })

        elif page.page_type == PageType.OVERVIEW:
            buttons.append({
                "widget_type": "ActionButton",
                "label": "Nuevo",
                "button_type": "New",
                "action": "show_page",
                "target_page": f"{entity_name}_Create",
                "style": "Primary",
                "placement": "top",
            })
            buttons.append({
                "widget_type": "ActionButton",
                "label": "Editar",
                "button_type": "Edit",
                "action": "show_page",
                "target_page": f"{entity_name}_Edit",
                "style": "Default",
                "placement": "row",
            })
            buttons.append({
                "widget_type": "ActionButton",
                "label": "Eliminar",
                "button_type": "Delete",
                "action": "call_microflow",
                "microflow": f"ACT_{entity_name}_Delete",
                "style": "Danger",
                "placement": "row",
            })

        return buttons
