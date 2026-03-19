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
    AttributeSchema,
    EntitySchema,
    InputSource,
    IntermediateSchema,
    MendixDataType,
    MicroflowSchema,
    MicroflowType,
    PageSchema,
    PageType,
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
}

# Mapeo de MendixDataType a WidgetType por defecto
DEFAULT_WIDGET_MAP: dict[MendixDataType, WidgetType] = {
    MendixDataType.STRING: WidgetType.TEXT_INPUT,
    MendixDataType.INTEGER: WidgetType.NUMBER_INPUT,
    MendixDataType.LONG: WidgetType.NUMBER_INPUT,
    MendixDataType.DECIMAL: WidgetType.NUMBER_INPUT,
    MendixDataType.BOOLEAN: WidgetType.CHECK_BOX,
    MendixDataType.DATETIME: WidgetType.DATE_PICKER,
    MendixDataType.ENUMERATION: WidgetType.DROP_DOWN,
    MendixDataType.HASHED_STRING: WidgetType.TEXT_INPUT,
    MendixDataType.AUTONUMBER: WidgetType.TEXT_INPUT,
}

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
        all_errors: list[str] = []

        for sheet_name in wb.sheetnames:
            # Ignorar hojas que empiezan con _ o # (convención para metadata/docs)
            if sheet_name.startswith(("_", "#")):
                logger.debug("sheet_skipped", sheet=sheet_name, reason="prefix")
                continue

            ws = wb[sheet_name]
            try:
                entity, sheet_pages, sheet_mfs = self._parse_sheet(
                    ws, sheet_name
                )
                entities.append(entity)
                pages.extend(sheet_pages)
                microflows.extend(sheet_mfs)
                logger.debug(
                    "sheet_parsed",
                    sheet=sheet_name,
                    attributes=len(entity.attributes),
                )
            except ExcelValidationError as e:
                all_errors.extend(
                    f"[{sheet_name}] {err}" for err in e.errors
                )
            except ExcelParserError as e:
                all_errors.append(f"[{sheet_name}] {e}")

        wb.close()

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
        )

        return IntermediateSchema(
            source=InputSource.EXCEL,
            source_file=str(excel_path),
            entities=entities,
            pages=pages,
            microflows=microflows,
        )

    def _parse_sheet(
        self, ws: Any, sheet_name: str
    ) -> tuple[EntitySchema, list[PageSchema], list[MicroflowSchema]]:
        """Parsea una hoja del Excel como una entidad.

        Returns:
            Tupla (entity, pages, microflows).
        """
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

        # 6. Normalizar nombre de entidad
        entity_name = self._normalize_entity_name(sheet_name)

        entity = EntitySchema(
            name=entity_name,
            module=module,
            attributes=attributes,
        )

        # 7. Generar páginas y microflows
        pages: list[PageSchema] = []
        microflows: list[MicroflowSchema] = []

        if self._generate_pages:
            pages = self._generate_default_pages(entity_name, module, rows, col_map)

        if self._generate_microflows:
            microflows = self._generate_default_microflows(entity_name, module)

        return entity, pages, microflows

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
        col_map: dict[str, int] = {}
        for i, h in enumerate(headers):
            normalized = self._normalize_column_name(h)
            if normalized:
                col_map[normalized] = i

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
                errors.append(
                    f"Fila {row_idx}: TipoDato '{raw_type}' no reconocido para '{name}'. "
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

            # Widget type (inferido del tipo de dato)
            widget_type = DEFAULT_WIDGET_MAP.get(mendix_type)

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

        for pt in sorted(page_types, key=lambda x: x.value):
            page_name = f"{entity_name}_{pt.value}"
            pages.append(
                PageSchema(
                    name=page_name,
                    page_type=pt,
                    entity=entity_name,
                    module=module,
                    title=f"{entity_name} — {pt.value}",
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
        """Parsea una regla de validación individual."""
        rule = rule.strip()

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
