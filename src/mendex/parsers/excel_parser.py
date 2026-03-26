"""Parser de archivos Excel (.xlsx) a IntermediateSchema.

Lee un archivo .xlsx con la estructura de un formulario Mendix y lo
convierte al schema intermedio unificado. Soporta múltiples entidades
(hojas) y genera automáticamente páginas y microflows asociados.

Columnas esperadas en el Excel:
- NombreCampo (requerida): Nombre del atributo en PascalCase
- TipoDato (requerida): Tipo de dato (texto, entero, decimal, fecha, booleano, enum, autonumero, etc.)
- Requerido (opcional): Sí/No o True/False
- Validacion (opcional): Regla de validación (ej: "max_length:100", "regex:^[A-Z]", "range:0-1000")
- Etiqueta (opcional): Label visible en el formulario
- Pagina (opcional): Tipo de página a generar (Create, Edit, Overview)
- ModuloDestino (opcional): Módulo Mendix destino
- ValoresEnum (opcional): Valores para enumeraciones, separados por coma
- ValorDefault (opcional): Valor por defecto del campo

Uso:
    parser = ExcelParser()
    schema = parser.parse(Path("formulario.xlsx"))

Fase 6: Implementación completa.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import structlog

from mendex.schema.intermediate import (
    AccessRuleSchema,
    AssociationSchema,
    AssociationType,
    AttributeSchema,
    ConditionalVisibilitySchema,
    EntitySchema,
    FieldVisibility,
    InputSource,
    IntermediateSchema,
    MendixDataType,
    MicroflowSchema,
    MicroflowType,
    NestedListSchema,
    PageSchema,
    PageType,
    SectionSchema,
    ValidationRuleSchema,
    ValidationType,
    WidgetType,
)

logger = structlog.get_logger(__name__)


# ─── Constantes ──────────────────────────────────────────────


# Columnas requeridas (case-insensitive, stripped)
REQUIRED_COLUMNS = {"nombrecampo", "tipodato"}

# Columnas reconocidas
KNOWN_COLUMNS = {
    "nombrecampo",
    "tipodato",
    "requerido",
    "validacion",
    "etiqueta",
    "pagina",
    "modulodestino",
    "valoresenum",
    "valordefault",
    # Nuevas columnas v2
    "seccion",
    "widget",
    "visibleen",
    "calculado",
    "ordenseccion",
    "visiblesi",
}

# Mapeo de tipos de dato del Excel a MendixDataType
DATA_TYPE_MAP: dict[str, MendixDataType] = {
    # Español
    "texto": MendixDataType.STRING,
    "cadena": MendixDataType.STRING,
    "string": MendixDataType.STRING,
    "entero": MendixDataType.INTEGER,
    "integer": MendixDataType.INTEGER,
    "int": MendixDataType.INTEGER,
    "largo": MendixDataType.LONG,
    "long": MendixDataType.LONG,
    "decimal": MendixDataType.DECIMAL,
    "float": MendixDataType.DECIMAL,
    "double": MendixDataType.DECIMAL,
    "numero": MendixDataType.DECIMAL,
    "booleano": MendixDataType.BOOLEAN,
    "boolean": MendixDataType.BOOLEAN,
    "bool": MendixDataType.BOOLEAN,
    "fecha": MendixDataType.DATETIME,
    "datetime": MendixDataType.DATETIME,
    "date": MendixDataType.DATETIME,
    "fechahora": MendixDataType.DATETIME,
    "enum": MendixDataType.ENUMERATION,
    "enumeracion": MendixDataType.ENUMERATION,
    "enumeration": MendixDataType.ENUMERATION,
    "hash": MendixDataType.HASHED_STRING,
    "hashedstring": MendixDataType.HASHED_STRING,
    "password": MendixDataType.HASHED_STRING,
    "contrasena": MendixDataType.HASHED_STRING,
    "autonumero": MendixDataType.AUTONUMBER,
    "autonumber": MendixDataType.AUTONUMBER,
    "auto": MendixDataType.AUTONUMBER,
    # Nuevos tipos v2
    "archivo": MendixDataType.BINARY,
    "file": MendixDataType.BINARY,
    "binary": MendixDataType.BINARY,
    "imagen": MendixDataType.BINARY,
    "image": MendixDataType.BINARY,
    "textogrande": MendixDataType.STRING,
    "textarea": MendixDataType.STRING,
    "memo": MendixDataType.STRING,
    "richtext": MendixDataType.STRING,
    "textorico": MendixDataType.STRING,
}

# Mapeo de MendixDataType a WidgetType por defecto
DEFAULT_WIDGET_MAP: dict[MendixDataType, WidgetType] = {
    MendixDataType.STRING: WidgetType.TEXT_INPUT,
    MendixDataType.INTEGER: WidgetType.NUMBER_INPUT,
    MendixDataType.LONG: WidgetType.NUMBER_INPUT,
    MendixDataType.DECIMAL: WidgetType.NUMBER_INPUT,
    MendixDataType.BOOLEAN: WidgetType.CHECK_BOX,
    MendixDataType.DATETIME: WidgetType.DATE_PICKER,
    # ENUMERATION no longer maps to a widget — enums become lookup entities
    # with ReferenceSelector widgets generated from associations
    MendixDataType.HASHED_STRING: WidgetType.TEXT_INPUT,
    MendixDataType.AUTONUMBER: WidgetType.TEXT_INPUT,
    MendixDataType.BINARY: WidgetType.FILE_UPLOAD,
}

# Mapeo de aliases de tipo de dato del Excel a widget override
# Tipos que se parsean como STRING pero necesitan un widget distinto
DATA_TYPE_WIDGET_OVERRIDES: dict[str, WidgetType] = {
    "textogrande": WidgetType.TEXT_AREA,
    "textarea": WidgetType.TEXT_AREA,
    "memo": WidgetType.TEXT_AREA,
    "richtext": WidgetType.RICH_TEXT,
    "textorico": WidgetType.RICH_TEXT,
    "imagen": WidgetType.IMAGE_UPLOAD,
    "image": WidgetType.IMAGE_UPLOAD,
}

# Mapeo de widget name del Excel a WidgetType
WIDGET_NAME_MAP: dict[str, WidgetType] = {
    "textinput": WidgetType.TEXT_INPUT,
    "numberinput": WidgetType.NUMBER_INPUT,
    "datepicker": WidgetType.DATE_PICKER,
    "checkbox": WidgetType.CHECK_BOX,
    "dropdown": WidgetType.DROP_DOWN,
    "textarea": WidgetType.TEXT_AREA,
    "radiobuttons": WidgetType.RADIO_BUTTONS,
    "referenceselector": WidgetType.REFERENCE_SELECTOR,
    "fileupload": WidgetType.FILE_UPLOAD,
    "imageupload": WidgetType.IMAGE_UPLOAD,
    "richtext": WidgetType.RICH_TEXT,
}

# Mapeo de VisibleEn del Excel a FieldVisibility
VISIBILITY_MAP: dict[str, FieldVisibility] = {
    "todos": FieldVisibility.ALL,
    "all": FieldVisibility.ALL,
    "soloeditar": FieldVisibility.EDIT_ONLY,
    "editonly": FieldVisibility.EDIT_ONLY,
    "solooverview": FieldVisibility.OVERVIEW_ONLY,
    "overviewonly": FieldVisibility.OVERVIEW_ONLY,
    "sololista": FieldVisibility.OVERVIEW_ONLY,
    "solocrear": FieldVisibility.CREATE_ONLY,
    "createonly": FieldVisibility.CREATE_ONLY,
}

# Mapeo de tipos de asociación del Excel
ASSOCIATION_TYPE_MAP: dict[str, AssociationType] = {
    "1-*": AssociationType.ONE_TO_MANY,
    "1-n": AssociationType.ONE_TO_MANY,
    "*-*": AssociationType.MANY_TO_MANY,
    "n-n": AssociationType.MANY_TO_MANY,
    "1-1": AssociationType.ONE_TO_ONE,
}

# Tipos de dato que implican generalización de System.FileDocument/Image
FILE_GENERALIZATIONS: dict[str, str] = {
    "archivo": "System.FileDocument",
    "file": "System.FileDocument",
    "binary": "System.FileDocument",
    "imagen": "System.Image",
    "image": "System.Image",
}

# Hojas especiales (prefijo _)
SPECIAL_SHEETS = {"_config", "_relaciones", "_seguridad"}

# Valores truthy para la columna "Requerido"
TRUTHY_VALUES = {"sí", "si", "yes", "true", "1", "x", "✓", "✔"}

# Módulo destino por defecto
DEFAULT_MODULE = "MyFirstModule"


# ─── Excepciones ─────────────────────────────────────────────


class ExcelParserError(Exception):
    """Error al parsear un archivo Excel."""


class ExcelValidationError(ExcelParserError):
    """Error de validación del contenido del Excel."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__(f"Errores de validación: {'; '.join(errors)}")


# ─── Parser ──────────────────────────────────────────────────


class ExcelParser:
    """Parsea archivos .xlsx a IntermediateSchema.

    Cada hoja del Excel se interpreta como una entidad distinta.
    El nombre de la hoja se usa como nombre de la entidad (si sigue
    PascalCase), o se normaliza.

    Uso:
        parser = ExcelParser(default_module="Operaciones")
        schema = parser.parse(Path("formulario.xlsx"))
    """

    def __init__(
        self,
        default_module: str = DEFAULT_MODULE,
        generate_pages: bool = True,
        generate_microflows: bool = True,
    ) -> None:
        """Inicializa el parser.

        Args:
            default_module: Módulo destino si no se especifica en el Excel.
            generate_pages: Si True, genera PageSchemas automáticamente.
            generate_microflows: Si True, genera MicroflowSchemas automáticamente.
        """
        self._default_module = default_module
        self._generate_pages = generate_pages
        self._generate_microflows = generate_microflows

    def parse(self, excel_path: Path) -> IntermediateSchema:
        """Parsea un archivo .xlsx y retorna IntermediateSchema.

        Args:
            excel_path: Path al archivo .xlsx.

        Returns:
            IntermediateSchema con entidades, páginas y microflows.

        Raises:
            ExcelParserError: Si el archivo no existe o no es .xlsx.
            ExcelValidationError: Si el contenido no es válido.
        """
        # Validar archivo
        if not excel_path.exists():
            raise ExcelParserError(f"Archivo no encontrado: {excel_path}")
        if excel_path.suffix.lower() not in (".xlsx", ".xlsm"):
            raise ExcelParserError(
                f"Formato no soportado: {excel_path.suffix}. Use .xlsx o .xlsm"
            )

        try:
            import openpyxl
        except ImportError:
            raise ExcelParserError(
                "openpyxl no instalado. Ejecuta: pip install openpyxl"
            )

        logger.info("excel_parse_started", path=str(excel_path))

        wb = openpyxl.load_workbook(excel_path, read_only=True, data_only=True)
        entities: list[EntitySchema] = []
        pages: list[PageSchema] = []
        microflows: list[MicroflowSchema] = []
        associations: list[AssociationSchema] = []
        config: dict[str, str] = {}
        security_rules: dict[str, list[AccessRuleSchema]] = {}
        all_errors: list[str] = []

        # Primera pasada: leer hojas especiales (_Config, _Relaciones, _Seguridad)
        for sheet_name in wb.sheetnames:
            normalized = sheet_name.strip().lower()
            if normalized == "_config":
                config = self._parse_config_sheet(wb[sheet_name])
            elif normalized == "_relaciones":
                try:
                    associations = self._parse_relaciones_sheet(wb[sheet_name])
                except ExcelValidationError as e:
                    all_errors.extend(
                        f"[_Relaciones] {err}" for err in e.errors
                    )
            elif normalized == "_seguridad":
                try:
                    security_rules = self._parse_seguridad_sheet(wb[sheet_name])
                except ExcelValidationError as e:
                    all_errors.extend(
                        f"[_Seguridad] {err}" for err in e.errors
                    )

        # Aplicar config defaults
        if "modulodestino" in config:
            self._default_module = config["modulodestino"]

        # Segunda pasada: leer hojas de entidad
        seen_lookups: dict[str, EntitySchema] = {}  # dedup by name

        for sheet_name in wb.sheetnames:
            # Ignorar hojas que empiezan con _ o # (convención para metadata/docs)
            if sheet_name.startswith(("_", "#")):
                logger.debug("sheet_skipped", sheet=sheet_name, reason="prefix")
                continue

            ws = wb[sheet_name]
            try:
                entity, sheet_lookups, sheet_pages, sheet_mfs, sheet_lookup_assocs = (
                    self._parse_sheet(ws, sheet_name, config)
                )

                # Aplicar security rules (match by prefixed name, raw sheet name, or wildcard)
                raw_name = self._normalize_entity_name(sheet_name)
                entity_rules = (
                    security_rules.get(entity.name, [])
                    or security_rules.get(raw_name, [])
                ) + security_rules.get("*", [])
                if entity_rules:
                    entity.access_rules = entity_rules

                entities.append(entity)
                pages.extend(sheet_pages)
                microflows.extend(sheet_mfs)

                # Collect lookup entities (deduplicate by name)
                for lookup in sheet_lookups:
                    if lookup.name not in seen_lookups:
                        seen_lookups[lookup.name] = lookup
                    else:
                        # Merge seed values if same lookup from different sheets
                        existing = seen_lookups[lookup.name]
                        merged = list(existing.seed_values)
                        for v in lookup.seed_values:
                            if v not in merged:
                                merged.append(v)
                        existing.seed_values = merged

                associations.extend(sheet_lookup_assocs)

                logger.debug(
                    "sheet_parsed",
                    sheet=sheet_name,
                    attributes=len(entity.attributes),
                    lookups=len(sheet_lookups),
                )
            except ExcelValidationError as e:
                all_errors.extend(
                    f"[{sheet_name}] {err}" for err in e.errors
                )
            except ExcelParserError as e:
                all_errors.append(f"[{sheet_name}] {e}")

        # Add deduplicated lookup entities
        entities.extend(seen_lookups.values())

        # --- Post-processing: Create global filter entity ---
        # Collect all lookup association targets (non-lookup entities that have lookups)
        prefix = config.get("prefijoentidad", "")
        lookup_assoc_map: dict[str, list[str]] = {}  # child_entity -> [lookup_names]
        for assoc in associations:
            if assoc.is_lookup:
                lookup_assoc_map.setdefault(assoc.child_entity, []).append(
                    assoc.parent_entity
                )

        if lookup_assoc_map:
            # Build ONE global filter entity with attributes for all lookups
            filter_name = f"{prefix}Filtros" if prefix else "Filtros"
            filter_attrs: list[AttributeSchema] = []
            seen_filter_attrs: set[str] = set()

            for _child, lookup_names in lookup_assoc_map.items():
                for lookup_name in lookup_names:
                    # Remove prefix from lookup name for the filter attribute
                    clean_lookup = lookup_name
                    if prefix and clean_lookup.startswith(prefix):
                        clean_lookup = clean_lookup[len(prefix):]
                    attr_name = f"Filtro_{clean_lookup}"
                    if attr_name not in seen_filter_attrs:
                        seen_filter_attrs.add(attr_name)
                        filter_attrs.append(AttributeSchema(
                            name=attr_name,
                            mendix_type=MendixDataType.STRING,
                            label=clean_lookup,
                        ))

            if filter_attrs:
                entities.append(EntitySchema(
                    name=filter_name,
                    module=self._default_module,
                    attributes=filter_attrs,
                    is_persistable=False,
                    is_filter_entity=True,
                ))

                # Set filter_entity on Overview pages for entities that have lookups
                for page in pages:
                    if (
                        page.page_type == PageType.OVERVIEW
                        and page.entity in lookup_assoc_map
                    ):
                        page.filter_entity = filter_name

        # --- Post-processing: Config Page + Lookup CRUD ---
        if seen_lookups:
            nav_items: list[str] = []

            for lookup in seen_lookups.values():
                # Overview page for lookup entity
                overview_name = f"{lookup.name}_Overview"
                pages.append(PageSchema(
                    name=overview_name,
                    page_type=PageType.OVERVIEW,
                    entity=lookup.name,
                    module=lookup.module,
                    title=f"{lookup.name} — Overview",
                ))
                nav_items.append(overview_name)

                # NewEdit page for lookup entity
                pages.append(PageSchema(
                    name=f"{lookup.name}_NewEdit",
                    page_type=PageType.CREATE,
                    entity=lookup.name,
                    module=lookup.module,
                    title=f"{lookup.name} — Nuevo/Editar",
                ))

                # CRUD microflows for lookup entity
                microflows.append(MicroflowSchema(
                    name=f"ACT_{lookup.name}_Save",
                    microflow_type=MicroflowType.SAVE,
                    entity=lookup.name,
                    module=lookup.module,
                    logic_description=f"Guardar {lookup.name}",
                ))
                microflows.append(MicroflowSchema(
                    name=f"ACT_{lookup.name}_Delete",
                    microflow_type=MicroflowType.DELETE,
                    entity=lookup.name,
                    module=lookup.module,
                    logic_description=f"Eliminar {lookup.name}",
                ))

                # Default access rules for lookup entity (if none set)
                if not lookup.access_rules:
                    lookup.access_rules = [
                        AccessRuleSchema(
                            role="Administrator",
                            can_create=True,
                            can_read=True,
                            can_write=True,
                            can_delete=True,
                        ),
                        AccessRuleSchema(
                            role="User",
                            can_create=False,
                            can_read=True,
                            can_write=False,
                            can_delete=False,
                        ),
                    ]

            # Configuracion page with navigation items
            if nav_items:
                pages.append(PageSchema(
                    name="Configuracion",
                    page_type=PageType.CONFIG,
                    entity=nav_items[0].replace("_Overview", ""),  # first lookup
                    module=self._default_module,
                    title="Configuración",
                    navigation_items=nav_items,
                ))

        # --- Post-processing: Master-Detail (nested lists) ---
        # For non-lookup 1-* associations, create nested lists on parent pages
        entity_map_local = {e.name: e for e in entities}
        existing_mf_names = {m.name for m in microflows}
        existing_page_names = {p.name for p in pages}

        for assoc in associations:
            if (
                assoc.association_type == AssociationType.ONE_TO_MANY
                and not assoc.is_lookup
            ):
                parent_name = assoc.parent_entity
                child_name = assoc.child_entity
                child_entity = entity_map_local.get(child_name)

                if not child_entity:
                    continue

                # Get child display attributes
                display_attrs = [a.name for a in child_entity.attributes[:5]]

                # Create NestedListSchema
                nested = NestedListSchema(
                    child_entity=child_name,
                    association=assoc.name,
                    display_attributes=display_attrs,
                    child_page=f"{child_name}_NewEdit",
                )

                # Attach nested list to parent's Create/Edit pages
                for page in pages:
                    if (
                        page.entity == parent_name
                        and page.page_type in (PageType.CREATE, PageType.EDIT)
                    ):
                        page.nested_lists.append(nested)

                # Auto-generate child NewEdit page as popup (if not exists)
                child_newedit = f"{child_name}_NewEdit"
                if child_newedit not in existing_page_names:
                    pages.append(PageSchema(
                        name=child_newedit,
                        page_type=PageType.CREATE,
                        entity=child_name,
                        module=child_entity.module,
                        title=f"{child_name} — Nuevo/Editar",
                        is_popup=True,
                        layout="PopupLayout",
                    ))
                    existing_page_names.add(child_newedit)

                # Auto-generate child CRUD microflows if needed
                for mf_name, mf_type, mf_desc in [
                    (f"ACT_{child_name}_Save", MicroflowType.SAVE, f"Guardar {child_name}"),
                    (f"ACT_{child_name}_Delete", MicroflowType.DELETE, f"Eliminar {child_name}"),
                ]:
                    if mf_name not in existing_mf_names:
                        microflows.append(MicroflowSchema(
                            name=mf_name,
                            microflow_type=mf_type,
                            entity=child_name,
                            module=child_entity.module,
                            logic_description=mf_desc,
                        ))
                        existing_mf_names.add(mf_name)

        wb.close()

        # Apply entity prefix to association references and validate
        entity_names = {e.name for e in entities}
        prefix = config.get("prefijoentidad", "")
        for assoc in associations:
            # Try to resolve with prefix if raw name not found
            if assoc.parent_entity not in entity_names:
                prefixed = prefix + assoc.parent_entity if prefix else ""
                if prefixed in entity_names:
                    assoc.parent_entity = prefixed
                else:
                    all_errors.append(
                        f"[_Relaciones] EntidadOrigen '{assoc.parent_entity}' "
                        "no corresponde a ninguna hoja de entidad"
                    )
            if assoc.child_entity not in entity_names:
                prefixed = prefix + assoc.child_entity if prefix else ""
                if prefixed in entity_names:
                    assoc.child_entity = prefixed
                else:
                    all_errors.append(
                        f"[_Relaciones] EntidadDestino '{assoc.child_entity}' "
                        "no corresponde a ninguna hoja de entidad"
                    )
            # Also update association name if prefix was applied
            if prefix and not assoc.name.startswith(prefix):
                assoc.name = f"{assoc.parent_entity}_{assoc.child_entity}"

        if all_errors:
            raise ExcelValidationError(all_errors)

        if not entities:
            raise ExcelParserError(
                "No se encontraron entidades válidas en el archivo Excel. "
                "Asegúrate de que al menos una hoja tenga las columnas "
                "NombreCampo y TipoDato."
            )

        logger.info(
            "excel_parse_complete",
            entities=len(entities),
            pages=len(pages),
            microflows=len(microflows),
            associations=len(associations),
        )

        return IntermediateSchema(
            source=InputSource.EXCEL,
            source_file=str(excel_path),
            entities=entities,
            pages=pages,
            microflows=microflows,
            associations=associations,
            config=config,
        )

    def _parse_sheet(
        self, ws: Any, sheet_name: str, config: dict[str, str] | None = None
    ) -> tuple[
        EntitySchema,
        list[EntitySchema],
        list[PageSchema],
        list[MicroflowSchema],
        list[AssociationSchema],
    ]:
        """Parsea una hoja del Excel como una entidad.

        Returns:
            Tupla (entity, lookup_entities, pages, microflows, lookup_associations).
        """
        config = config or {}

        # 1. Leer headers (primera fila)
        headers = self._read_headers(ws)
        if not headers:
            raise ExcelParserError(f"Hoja vacía o sin headers")

        # 2. Validar columnas requeridas
        col_map = self._validate_columns(headers)

        # 3. Leer filas de datos
        rows = self._read_data_rows(ws, headers)
        if not rows:
            raise ExcelParserError("Sin filas de datos (solo headers)")

        # 4. Parsear atributos
        attributes, errors = self._parse_attributes(rows, col_map)
        if errors:
            raise ExcelValidationError(errors)
        if not attributes:
            raise ExcelParserError("No se encontraron atributos válidos")

        # 5. Determinar módulo
        module = self._determine_module(rows, col_map)

        # 6. Normalizar nombre de entidad y apply prefix
        entity_name = self._normalize_entity_name(sheet_name)
        prefix = config.get("prefijoentidad", "")
        if prefix and not entity_name.startswith(prefix):
            entity_name = prefix + entity_name

        # Apply attribute prefix
        attr_prefix = config.get("prefijoatributo", "")
        if attr_prefix:
            for attr in attributes:
                if not attr.name.startswith(attr_prefix):
                    attr.name = attr_prefix + attr.name

        # 7. Detect generalization (file/image entities)
        generalization = self._detect_generalization(rows)

        # 8. Extract ENUMERATION attributes → lookup entities + associations
        lookup_entities: list[EntitySchema] = []
        lookup_associations: list[AssociationSchema] = []
        remaining_attrs: list[AttributeSchema] = []

        for attr in attributes:
            if attr.mendix_type == MendixDataType.ENUMERATION and attr.enum_values:
                lookup_name = prefix + attr.name if prefix else attr.name
                lookup_entities.append(
                    EntitySchema(
                        name=lookup_name,
                        module=module,
                        attributes=[
                            AttributeSchema(
                                name="Name",
                                mendix_type=MendixDataType.STRING,
                                label="Nombre",
                                required=True,
                                validations=[
                                    ValidationRuleSchema(
                                        type=ValidationType.REQUIRED,
                                        params={},
                                        error_message="El campo Name es requerido",
                                    )
                                ],
                            )
                        ],
                        is_lookup=True,
                        seed_values=attr.enum_values,
                    )
                )
                lookup_associations.append(
                    AssociationSchema(
                        name=f"{entity_name}_{lookup_name}",
                        parent_entity=lookup_name,
                        child_entity=entity_name,
                        association_type=AssociationType.ONE_TO_MANY,
                        is_lookup=True,
                        label=attr.label,
                        section=attr.section,
                        visibility=attr.visibility,
                        required=attr.required,
                    )
                )
                logger.debug(
                    "enum_to_lookup",
                    field=attr.name,
                    lookup_entity=lookup_name,
                    seed_values=attr.enum_values,
                )
            else:
                remaining_attrs.append(attr)

        attributes = remaining_attrs

        # Detect sequential numbering fields
        sequential_patterns = re.compile(
            r"(secuencia|orden|correlativo|numero|nro|seq)", re.IGNORECASE
        )
        has_sequential = any(
            sequential_patterns.search(attr.name) for attr in attributes
        )

        entity = EntitySchema(
            name=entity_name,
            module=module,
            attributes=attributes,
            generalization=generalization,
            has_sequential=has_sequential,
        )

        # 9. Generar páginas y microflows
        pages: list[PageSchema] = []
        microflows: list[MicroflowSchema] = []

        if self._generate_pages:
            pages = self._generate_default_pages(
                entity_name, module, rows, col_map, attributes
            )

        if self._generate_microflows:
            microflows = self._generate_default_microflows(entity_name, module)

        return entity, lookup_entities, pages, microflows, lookup_associations

    def _read_headers(self, ws: Any) -> list[str]:
        """Lee los headers de la primera fila."""
        headers: list[str] = []
        for cell in ws[1]:
            val = cell.value
            if val is not None:
                headers.append(str(val).strip())
            else:
                headers.append("")
        # Eliminar headers vacíos al final
        while headers and not headers[-1]:
            headers.pop()
        return headers

    def _validate_columns(self, headers: list[str]) -> dict[str, int]:
        """Valida que las columnas requeridas existan y retorna el mapeo.

        Returns:
            Dict de nombre_columna_normalizado → índice.
        """
        from difflib import get_close_matches

        col_map: dict[str, int] = {}
        unknown_columns: list[str] = []
        for i, h in enumerate(headers):
            normalized = self._normalize_column_name(h)
            if normalized:
                if normalized in KNOWN_COLUMNS:
                    col_map[normalized] = i
                else:
                    unknown_columns.append(h)

        # Warn about unknown columns with fuzzy suggestions
        if unknown_columns:
            known_friendly = sorted(KNOWN_COLUMNS)
            for col in unknown_columns:
                norm = self._normalize_column_name(col)
                matches = get_close_matches(norm, known_friendly, n=1, cutoff=0.5)
                hint = f" ¿Quisiste decir '{matches[0]}'?" if matches else ""
                logger.warning(
                    "unknown_column",
                    column=col,
                    suggestion=matches[0] if matches else None,
                    msg=f"Columna '{col}' no reconocida.{hint}",
                )

        missing = REQUIRED_COLUMNS - set(col_map.keys())
        if missing:
            friendly = {
                "nombrecampo": "NombreCampo",
                "tipodato": "TipoDato",
            }
            missing_names = [friendly.get(m, m) for m in sorted(missing)]
            raise ExcelValidationError(
                [f"Columna(s) requerida(s) faltante(s): {', '.join(missing_names)}"]
            )

        return col_map

    def _read_data_rows(
        self, ws: Any, headers: list[str]
    ) -> list[dict[str, Any]]:
        """Lee todas las filas de datos (excluyendo headers)."""
        rows: list[dict[str, Any]] = []
        n_cols = len(headers)

        for row_idx, row in enumerate(ws.iter_rows(min_row=2), start=2):
            values = [cell.value for cell in row[:n_cols]]

            # Ignorar filas completamente vacías
            if all(v is None for v in values):
                continue

            row_dict: dict[str, Any] = {"_row_idx": row_idx}
            for i, h in enumerate(headers):
                normalized = self._normalize_column_name(h)
                if normalized and i < len(values):
                    row_dict[normalized] = values[i]

            rows.append(row_dict)

        return rows

    def _parse_attributes(
        self, rows: list[dict[str, Any]], col_map: dict[str, int]
    ) -> tuple[list[AttributeSchema], list[str]]:
        """Parsea las filas a AttributeSchema."""
        attributes: list[AttributeSchema] = []
        errors: list[str] = []
        seen_names: set[str] = set()

        for row in rows:
            row_idx = row.get("_row_idx", "?")

            # NombreCampo
            raw_name = row.get("nombrecampo")
            if not raw_name:
                continue  # skip empty rows silently
            name = str(raw_name).strip()
            if not name:
                continue

            # Validar nombre
            if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
                errors.append(
                    f"Fila {row_idx}: NombreCampo '{name}' contiene "
                    "caracteres no válidos (use solo letras, números y _)"
                )
                continue

            # Duplicados
            if name.lower() in seen_names:
                errors.append(
                    f"Fila {row_idx}: NombreCampo '{name}' duplicado"
                )
                continue
            seen_names.add(name.lower())

            # TipoDato
            raw_type = row.get("tipodato")
            if not raw_type:
                errors.append(f"Fila {row_idx}: TipoDato vacío para '{name}'")
                continue
            mendix_type = self._map_data_type(str(raw_type).strip())
            if mendix_type is None:
                suggestion = self._suggest_data_type(str(raw_type).strip())
                hint = f" ¿Quisiste decir '{suggestion}'?" if suggestion else ""
                errors.append(
                    f"Fila {row_idx}: TipoDato '{raw_type}' no reconocido para '{name}'.{hint} "
                    f"Tipos válidos: {', '.join(sorted(DATA_TYPE_MAP.keys()))}"
                )
                continue

            # Requerido
            required = self._parse_boolean(row.get("requerido"))

            # Etiqueta
            label = str(row.get("etiqueta") or name).strip()

            # Validaciones
            validations = self._parse_validations(
                row.get("validacion"), name, required, row_idx
            )

            # Enum values
            enum_values = self._parse_enum_values(
                row.get("valoresenum"), mendix_type, name, row_idx, errors
            )

            # Default value
            default_value = None
            raw_default = row.get("valordefault")
            if raw_default is not None:
                default_value = str(raw_default).strip()

            # Widget type: explicit override > data type alias override > default
            raw_type_normalized = re.sub(
                r"[\s\-_]", "", str(raw_type).lower()
            )
            widget_type = DEFAULT_WIDGET_MAP.get(mendix_type)
            # Check if data type alias implies a specific widget
            alias_widget = DATA_TYPE_WIDGET_OVERRIDES.get(raw_type_normalized)
            if alias_widget:
                widget_type = alias_widget
            # Explicit Widget column override
            raw_widget = row.get("widget")
            if raw_widget:
                explicit_widget = WIDGET_NAME_MAP.get(
                    re.sub(r"[\s\-_]", "", str(raw_widget).lower())
                )
                if explicit_widget:
                    widget_type = explicit_widget

            # Section
            section = None
            raw_section = row.get("seccion")
            if raw_section:
                section = str(raw_section).strip() or None

            # VisibleEn
            visibility = FieldVisibility.ALL
            raw_vis = row.get("visibleen")
            if raw_vis:
                vis_key = re.sub(r"[\s\-_]", "", str(raw_vis).lower())
                visibility = VISIBILITY_MAP.get(vis_key, FieldVisibility.ALL)

            # Calculado
            is_calculated = False
            calculation_expression = None
            raw_calc = row.get("calculado")
            if raw_calc:
                is_calculated = True
                calculation_expression = str(raw_calc).strip()

            # VisibleSi (conditional visibility)
            conditional_visibility = None
            raw_cond = row.get("visiblesi")
            if raw_cond:
                cond_str = str(raw_cond).strip()
                parts = cond_str.split("=", 1)
                if len(parts) == 2 and parts[1].strip():
                    conditional_visibility = ConditionalVisibilitySchema(
                        depends_on=parts[0].strip(),
                        operator="equals",
                        value=parts[1].strip(),
                    )
                elif parts[0].strip():
                    conditional_visibility = ConditionalVisibilitySchema(
                        depends_on=parts[0].strip(),
                        operator="not_empty",
                    )

            attributes.append(
                AttributeSchema(
                    name=name,
                    mendix_type=mendix_type,
                    label=label,
                    required=required,
                    validations=validations,
                    enum_values=enum_values,
                    default_value=default_value,
                    widget_type=widget_type,
                    section=section,
                    visibility=visibility,
                    is_calculated=is_calculated,
                    calculation_expression=calculation_expression,
                    conditional_visibility=conditional_visibility,
                )
            )

        return attributes, errors

    def _determine_module(
        self, rows: list[dict[str, Any]], col_map: dict[str, int]
    ) -> str:
        """Determina el módulo destino de las filas."""
        for row in rows:
            module = row.get("modulodestino")
            if module and str(module).strip():
                return str(module).strip()
        return self._default_module

    def _generate_default_pages(
        self,
        entity_name: str,
        module: str,
        rows: list[dict[str, Any]],
        col_map: dict[str, int],
        attributes: list[AttributeSchema] | None = None,
    ) -> list[PageSchema]:
        """Genera páginas por defecto para la entidad."""
        pages: list[PageSchema] = []

        # Determinar qué tipos de página generar
        page_types: set[PageType] = set()
        for row in rows:
            raw_page = row.get("pagina")
            if raw_page:
                pt = self._map_page_type(str(raw_page).strip())
                if pt:
                    page_types.add(pt)

        # Si no se especificó ninguna, generar Create y Overview por defecto
        if not page_types:
            page_types = {PageType.CREATE, PageType.OVERVIEW}

        # Build sections from attributes (if any have section set)
        all_sections = self._build_sections(attributes or [])

        for pt in sorted(page_types, key=lambda x: x.value):
            page_name = f"{entity_name}_{pt.value}"

            # Filter sections by page type visibility
            page_sections = self._filter_sections_for_page_type(
                all_sections, attributes or [], pt
            )

            pages.append(
                PageSchema(
                    name=page_name,
                    page_type=pt,
                    entity=entity_name,
                    module=module,
                    title=f"{entity_name} — {pt.value}",
                    sections=page_sections,
                )
            )

        return pages

    def _generate_default_microflows(
        self, entity_name: str, module: str
    ) -> list[MicroflowSchema]:
        """Genera microflows de validación y guardado por defecto."""
        return [
            MicroflowSchema(
                name=f"VAL_{entity_name}_Validate",
                microflow_type=MicroflowType.VALIDATION,
                entity=entity_name,
                module=module,
                logic_description=(
                    f"Valida todos los campos requeridos y reglas de "
                    f"validación de la entidad {entity_name}."
                ),
            ),
            MicroflowSchema(
                name=f"ACT_{entity_name}_Save",
                microflow_type=MicroflowType.SAVE,
                entity=entity_name,
                module=module,
                logic_description=(
                    f"Ejecuta validación y guarda la entidad {entity_name}. "
                    f"Muestra mensaje de confirmación al usuario."
                ),
            ),
            MicroflowSchema(
                name=f"ACT_{entity_name}_Delete",
                microflow_type=MicroflowType.DELETE,
                entity=entity_name,
                module=module,
                logic_description=(
                    f"Eliminar {entity_name} con confirmación al usuario."
                ),
            ),
        ]

    # ─── Métodos auxiliares ──────────────────────────────────

    @staticmethod
    def _normalize_column_name(name: str) -> str:
        """Normaliza un nombre de columna para comparación."""
        # Remover espacios, guiones, underscores; lowercase
        return re.sub(r"[\s\-_]", "", name.lower().strip())

    @staticmethod
    def _normalize_entity_name(sheet_name: str) -> str:
        """Normaliza el nombre de hoja a PascalCase para entidad."""
        name = sheet_name.strip()

        # Si ya es PascalCase válido, usar tal cual
        if re.match(r"^[A-Z][a-zA-Z0-9]*$", name):
            return name

        # Convertir snake_case o spaces a PascalCase
        parts = re.split(r"[\s_\-]+", name)
        pascal = "".join(p.capitalize() for p in parts if p)

        # Asegurar que empiece con letra
        if pascal and not pascal[0].isalpha():
            pascal = "E" + pascal

        return pascal or "UnnamedEntity"

    @staticmethod
    def _map_data_type(raw_type: str) -> MendixDataType | None:
        """Mapea un tipo de dato del Excel a MendixDataType."""
        normalized = re.sub(r"[\s\-_]", "", raw_type.lower())
        return DATA_TYPE_MAP.get(normalized)

    @staticmethod
    def _suggest_data_type(raw_type: str) -> str | None:
        """Sugiere el tipo más cercano usando fuzzy matching."""
        from difflib import get_close_matches

        normalized = re.sub(r"[\s\-_]", "", raw_type.lower())
        matches = get_close_matches(normalized, DATA_TYPE_MAP.keys(), n=1, cutoff=0.5)
        return matches[0] if matches else None

    @staticmethod
    def _parse_boolean(value: Any) -> bool:
        """Parsea un valor a booleano."""
        if value is None:
            return False
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in TRUTHY_VALUES

    @staticmethod
    def _map_page_type(raw: str) -> PageType | None:
        """Mapea un tipo de página del Excel."""
        normalized = raw.lower().strip()
        mapping = {
            "create": PageType.CREATE,
            "crear": PageType.CREATE,
            "nuevo": PageType.CREATE,
            "new": PageType.CREATE,
            "edit": PageType.EDIT,
            "editar": PageType.EDIT,
            "modificar": PageType.EDIT,
            "overview": PageType.OVERVIEW,
            "lista": PageType.OVERVIEW,
            "listado": PageType.OVERVIEW,
            "list": PageType.OVERVIEW,
        }
        return mapping.get(normalized)

    @staticmethod
    def _parse_validations(
        raw: Any,
        field_name: str,
        required: bool,
        row_idx: Any,
    ) -> list[ValidationRuleSchema]:
        """Parsea reglas de validación de la columna Validacion.

        Formatos soportados:
        - "max_length:100"
        - "min_length:3"
        - "regex:^[A-Z]"
        - "range:0-1000"
        - "unique"
        - Múltiples separadas por ";"
        """
        validations: list[ValidationRuleSchema] = []

        # Añadir required como validación si aplica
        if required:
            validations.append(
                ValidationRuleSchema(
                    type=ValidationType.REQUIRED,
                    params={},
                    error_message=f"El campo {field_name} es requerido",
                )
            )

        if not raw:
            return validations

        raw_str = str(raw).strip()
        rules = [r.strip() for r in raw_str.split(";") if r.strip()]

        for rule in rules:
            parsed = ExcelParser._parse_single_validation(rule, field_name)
            if parsed:
                validations.append(parsed)

        return validations

    @staticmethod
    def _parse_single_validation(
        rule: str, field_name: str
    ) -> ValidationRuleSchema | None:
        """Parsea una regla de validación individual.

        Intenta primero la sintaxis técnica (max_length:100).
        Si no matchea, intenta aliases en lenguaje natural.
        """
        rule = rule.strip()

        # Intentar alias natural primero
        natural = ExcelParser._parse_natural_validation(rule, field_name)
        if natural:
            return natural

        if ":" in rule:
            vtype, value = rule.split(":", 1)
            vtype = vtype.strip().lower()
            value = value.strip()
        else:
            vtype = rule.lower()
            value = ""

        # Normalizar tipo
        vtype = re.sub(r"[\s\-]", "_", vtype)

        if vtype == "max_length" and value:
            return ValidationRuleSchema(
                type=ValidationType.MAX_LENGTH,
                params={"max": int(value)},
                error_message=f"{field_name} no puede exceder {value} caracteres",
            )
        elif vtype == "min_length" and value:
            return ValidationRuleSchema(
                type=ValidationType.MIN_LENGTH,
                params={"min": int(value)},
                error_message=f"{field_name} debe tener al menos {value} caracteres",
            )
        elif vtype == "regex" and value:
            return ValidationRuleSchema(
                type=ValidationType.REGEX,
                params={"pattern": value},
                error_message=f"{field_name} no cumple con el formato requerido",
            )
        elif vtype == "range" and value:
            parts = value.split("-", 1)
            if len(parts) == 2:
                return ValidationRuleSchema(
                    type=ValidationType.RANGE,
                    params={"min": float(parts[0]), "max": float(parts[1])},
                    error_message=f"{field_name} debe estar entre {parts[0]} y {parts[1]}",
                )
        elif vtype == "unique":
            return ValidationRuleSchema(
                type=ValidationType.UNIQUE,
                params={},
                error_message=f"{field_name} debe ser único",
            )
        elif vtype == "required":
            return ValidationRuleSchema(
                type=ValidationType.REQUIRED,
                params={},
                error_message=f"El campo {field_name} es requerido",
            )

        return None

    @staticmethod
    def _parse_enum_values(
        raw: Any,
        mendix_type: MendixDataType,
        field_name: str,
        row_idx: Any,
        errors: list[str],
    ) -> list[str] | None:
        """Parsea valores de enumeración."""
        if mendix_type != MendixDataType.ENUMERATION:
            return None

        if not raw:
            errors.append(
                f"Fila {row_idx}: Campo '{field_name}' es tipo Enumeration "
                "pero no tiene ValoresEnum definidos"
            )
            return None

        values = [v.strip() for v in str(raw).split(",") if v.strip()]
        if not values:
            errors.append(
                f"Fila {row_idx}: ValoresEnum vacíos para '{field_name}'"
            )
            return None

        return values

    # ─── Validaciones en lenguaje natural ────────────────────

    @staticmethod
    def _parse_natural_validation(
        rule: str, field_name: str
    ) -> ValidationRuleSchema | None:
        """Parsea validaciones en lenguaje natural (español/inglés)."""
        lower = rule.lower().strip()

        # "maximo N caracteres" / "max N chars"
        m = re.match(r"(?:maximo|máximo|max)\s+(\d+)\s*(?:caracteres|chars?)?", lower)
        if m:
            return ValidationRuleSchema(
                type=ValidationType.MAX_LENGTH,
                params={"max": int(m.group(1))},
                error_message=f"{field_name} no puede exceder {m.group(1)} caracteres",
            )

        # "minimo N caracteres" / "min N chars"
        m = re.match(r"(?:minimo|mínimo|min)\s+(\d+)\s*(?:caracteres|chars?)?", lower)
        if m:
            return ValidationRuleSchema(
                type=ValidationType.MIN_LENGTH,
                params={"min": int(m.group(1))},
                error_message=f"{field_name} debe tener al menos {m.group(1)} caracteres",
            )

        # "entre N y M" / "between N and M"
        m = re.match(r"(?:entre|between)\s+([\d.]+)\s+(?:y|and)\s+([\d.]+)", lower)
        if m:
            return ValidationRuleSchema(
                type=ValidationType.RANGE,
                params={"min": float(m.group(1)), "max": float(m.group(2))},
                error_message=f"{field_name} debe estar entre {m.group(1)} y {m.group(2)}",
            )

        # "unico" / "unique"
        if lower in ("unico", "único", "unique"):
            return ValidationRuleSchema(
                type=ValidationType.UNIQUE,
                params={},
                error_message=f"{field_name} debe ser único",
            )

        # "email"
        if lower == "email":
            return ValidationRuleSchema(
                type=ValidationType.REGEX,
                params={"pattern": r"^[^@]+@[^@]+\.[^@]+$"},
                error_message=f"{field_name} debe ser un email válido",
            )

        # "telefono" / "phone"
        if lower in ("telefono", "teléfono", "phone"):
            return ValidationRuleSchema(
                type=ValidationType.REGEX,
                params={"pattern": r"^[+]?[0-9\s\-()]+$"},
                error_message=f"{field_name} debe ser un teléfono válido",
            )

        return None

    # ─── Hojas especiales ────────────────────────────────────

    def _parse_config_sheet(self, ws: Any) -> dict[str, str]:
        """Parsea la hoja _Config (clave-valor)."""
        config: dict[str, str] = {}
        for row in ws.iter_rows(min_row=1, values_only=True):
            if not row or len(row) < 2:
                continue
            key = row[0]
            value = row[1]
            if key is not None and value is not None:
                normalized_key = re.sub(r"[\s\-_]", "", str(key).lower().strip())
                config[normalized_key] = str(value).strip()
        logger.debug("config_sheet_parsed", keys=list(config.keys()))
        return config

    def _parse_relaciones_sheet(self, ws: Any) -> list[AssociationSchema]:
        """Parsea la hoja _Relaciones (asociaciones entre entidades)."""
        headers = self._read_headers(ws)
        if not headers:
            return []

        col_map: dict[str, int] = {}
        for i, h in enumerate(headers):
            normalized = self._normalize_column_name(h)
            if normalized:
                col_map[normalized] = i

        # Validate required columns
        required = {"entidadorigen", "entidaddestino", "tipo"}
        missing = required - set(col_map.keys())
        if missing:
            raise ExcelValidationError(
                [f"Columnas requeridas faltantes en _Relaciones: {', '.join(missing)}"]
            )

        associations: list[AssociationSchema] = []
        errors: list[str] = []

        for row_idx, row in enumerate(ws.iter_rows(min_row=2), start=2):
            values = [cell.value for cell in row[:len(headers)]]
            if all(v is None for v in values):
                continue

            def get_col(name: str) -> str:
                idx = col_map.get(name)
                if idx is not None and idx < len(values) and values[idx] is not None:
                    return str(values[idx]).strip()
                return ""

            parent = self._normalize_entity_name(get_col("entidadorigen"))
            child = self._normalize_entity_name(get_col("entidaddestino"))
            raw_type = get_col("tipo").lower().replace(" ", "")

            if not parent or not child:
                continue

            assoc_type = ASSOCIATION_TYPE_MAP.get(raw_type)
            if not assoc_type:
                errors.append(
                    f"Fila {row_idx}: Tipo de relación '{raw_type}' no reconocido. "
                    f"Use: 1-*, *-*, 1-1"
                )
                continue

            name = get_col("nombreasociacion") or f"{parent}_{child}"
            cascade = self._parse_boolean(get_col("cascadedelete"))

            associations.append(
                AssociationSchema(
                    name=name,
                    parent_entity=parent,
                    child_entity=child,
                    association_type=assoc_type,
                    cascade_delete=cascade,
                )
            )

        if errors:
            raise ExcelValidationError(errors)

        logger.debug("relaciones_sheet_parsed", count=len(associations))
        return associations

    def _parse_seguridad_sheet(
        self, ws: Any
    ) -> dict[str, list[AccessRuleSchema]]:
        """Parsea la hoja _Seguridad (access rules por entidad y rol)."""
        headers = self._read_headers(ws)
        if not headers:
            return {}

        col_map: dict[str, int] = {}
        for i, h in enumerate(headers):
            normalized = self._normalize_column_name(h)
            if normalized:
                col_map[normalized] = i

        required = {"entidad", "rol"}
        missing = required - set(col_map.keys())
        if missing:
            raise ExcelValidationError(
                [f"Columnas requeridas faltantes en _Seguridad: {', '.join(missing)}"]
            )

        rules: dict[str, list[AccessRuleSchema]] = {}

        for row in ws.iter_rows(min_row=2, values_only=True):
            if not row or all(v is None for v in row):
                continue

            def get_val(name: str) -> str:
                idx = col_map.get(name)
                if idx is not None and idx < len(row) and row[idx] is not None:
                    return str(row[idx]).strip()
                return ""

            entity = get_val("entidad")
            role = get_val("rol")
            if not entity or not role:
                continue

            # Normalize entity name (except wildcard *)
            if entity != "*":
                entity = self._normalize_entity_name(entity)

            rule = AccessRuleSchema(
                role=role,
                can_create=self._parse_boolean(get_val("crear")),
                can_read=self._parse_boolean(get_val("leer") or "Si"),
                can_write=self._parse_boolean(get_val("escribir")),
                can_delete=self._parse_boolean(get_val("eliminar")),
            )

            if entity not in rules:
                rules[entity] = []
            rules[entity].append(rule)

        logger.debug(
            "seguridad_sheet_parsed",
            entities=len(rules),
            total_rules=sum(len(v) for v in rules.values()),
        )
        return rules

    # ─── Helpers para secciones ──────────────────────────────

    @staticmethod
    def _build_sections(
        attributes: list[AttributeSchema],
    ) -> list[SectionSchema]:
        """Construye SectionSchemas a partir de los atributos con sección."""
        section_map: dict[str, list[str]] = {}
        section_order: dict[str, int] = {}

        for attr in attributes:
            if attr.section:
                if attr.section not in section_map:
                    section_map[attr.section] = []
                    section_order[attr.section] = len(section_map)
                section_map[attr.section].append(attr.name)

        return [
            SectionSchema(
                name=name,
                order=section_order.get(name, i),
                attributes=attrs,
            )
            for i, (name, attrs) in enumerate(section_map.items())
        ]

    @staticmethod
    def _filter_sections_for_page_type(
        sections: list[SectionSchema],
        attributes: list[AttributeSchema],
        page_type: PageType,
    ) -> list[SectionSchema]:
        """Filtra secciones según la visibilidad de atributos para un tipo de página."""
        if not sections:
            return []

        # Build visibility lookup
        attr_vis = {a.name: a.visibility for a in attributes}

        # Visibility compatibility per page type
        visible_for: dict[PageType, set[FieldVisibility]] = {
            PageType.CREATE: {FieldVisibility.ALL, FieldVisibility.CREATE_ONLY},
            PageType.EDIT: {FieldVisibility.ALL, FieldVisibility.EDIT_ONLY},
            PageType.OVERVIEW: {FieldVisibility.ALL, FieldVisibility.OVERVIEW_ONLY},
        }
        allowed = visible_for.get(page_type, {FieldVisibility.ALL})

        filtered: list[SectionSchema] = []
        for section in sections:
            visible_attrs = [
                a for a in section.attributes
                if attr_vis.get(a, FieldVisibility.ALL) in allowed
            ]
            if visible_attrs:
                filtered.append(
                    SectionSchema(
                        name=section.name,
                        order=section.order,
                        attributes=visible_attrs,
                    )
                )

        return filtered

    @staticmethod
    def _detect_generalization(rows: list[dict[str, Any]]) -> str | None:
        """Detecta si algún campo implica una generalización (file/image)."""
        for row in rows:
            raw_type = row.get("tipodato")
            if raw_type:
                normalized = re.sub(r"[\s\-_]", "", str(raw_type).lower())
                gen = FILE_GENERALIZATIONS.get(normalized)
                if gen:
                    return gen
        return None
