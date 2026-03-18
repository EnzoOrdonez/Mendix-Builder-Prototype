"""IntermediateSchema — Contrato de datos unificado.

Output de los parsers (Excel, Figma), input de los generadores (Domain Model, Pages, Microflows).
Todos los componentes del sistema dependen de estos modelos.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class MendixDataType(str, Enum):
    STRING = "String"
    INTEGER = "Integer"
    LONG = "Long"
    DECIMAL = "Decimal"
    BOOLEAN = "Boolean"
    DATETIME = "DateTime"
    ENUMERATION = "Enumeration"
    HASHED_STRING = "HashedString"
    AUTONUMBER = "AutoNumber"


class ValidationType(str, Enum):
    REQUIRED = "required"
    MIN_LENGTH = "min_length"
    MAX_LENGTH = "max_length"
    REGEX = "regex"
    RANGE = "range"
    UNIQUE = "unique"
    CUSTOM = "custom"


class PageType(str, Enum):
    CREATE = "Create"
    EDIT = "Edit"
    OVERVIEW = "Overview"


class MicroflowType(str, Enum):
    VALIDATION = "Validation"
    SAVE = "Save"
    DELETE = "Delete"
    CUSTOM = "Custom"


class WidgetType(str, Enum):
    TEXT_INPUT = "TextInput"
    NUMBER_INPUT = "NumberInput"
    DATE_PICKER = "DatePicker"
    CHECK_BOX = "CheckBox"
    DROP_DOWN = "DropDown"
    TEXT_AREA = "TextArea"
    RADIO_BUTTONS = "RadioButtons"
    REFERENCE_SELECTOR = "ReferenceSelector"


class InputSource(str, Enum):
    EXCEL = "excel"
    FIGMA = "figma"


class BPVerdict(str, Enum):
    CONFORME = "CONFORME"
    NO_CONFORME = "NO_CONFORME"
    SIN_DATOS = "SIN_DATOS"


# ---------------------------------------------------------------------------
# Sub-schemas
# ---------------------------------------------------------------------------

class ValidationRuleSchema(BaseModel):
    """Regla de validación para un atributo."""

    type: ValidationType
    params: dict[str, str | int | float] = Field(default_factory=dict)
    error_message: str


class AttributeSchema(BaseModel):
    """Atributo de una entidad Mendix."""

    name: str
    mendix_type: MendixDataType
    label: str
    required: bool = False
    validations: list[ValidationRuleSchema] = Field(default_factory=list)
    enum_values: list[str] | None = None
    default_value: str | None = None
    widget_type: WidgetType | None = None


class AccessRuleSchema(BaseModel):
    """Regla de acceso por rol para una entidad."""

    role: str
    can_create: bool = False
    can_read: bool = True
    can_write: bool = False
    can_delete: bool = False


class EntitySchema(BaseModel):
    """Entidad del Domain Model de Mendix."""

    name: str
    module: str
    attributes: list[AttributeSchema]
    access_rules: list[AccessRuleSchema] = Field(default_factory=list)
    is_persistable: bool = True


class PageSchema(BaseModel):
    """Página de formulario de Mendix."""

    name: str
    page_type: PageType
    entity: str
    module: str
    title: str | None = None
    layout: str = "Atlas_Default"


class MicroflowSchema(BaseModel):
    """Microflow de Mendix (validación, guardado, etc.)."""

    name: str
    microflow_type: MicroflowType
    entity: str
    module: str
    logic_description: str


class FigmaExtractionMetadata(BaseModel):
    """Metadata de la extracción desde Figma."""

    file_key: str
    node_id: str
    frame_name: str
    extraction_timestamp: datetime
    figma_last_modified: str | None = None
    warnings: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Root schema
# ---------------------------------------------------------------------------

class IntermediateSchema(BaseModel):
    """Contrato de datos unificado: output de parsers, input de generadores."""

    source: InputSource
    source_file: str | None = None
    entities: list[EntitySchema]
    pages: list[PageSchema] = Field(default_factory=list)
    microflows: list[MicroflowSchema] = Field(default_factory=list)
    figma_metadata: FigmaExtractionMetadata | None = None
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
