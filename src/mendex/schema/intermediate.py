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
    BINARY = "Binary"


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
    CONFIG = "Config"


class MicroflowType(str, Enum):
    VALIDATION = "Validation"
    SAVE = "Save"
    DELETE = "Delete"
    CUSTOM = "Custom"
    DATA_SOURCE = "DataSource"
    SEQUENCE = "Sequence"


class WidgetType(str, Enum):
    TEXT_INPUT = "TextInput"
    NUMBER_INPUT = "NumberInput"
    DATE_PICKER = "DatePicker"
    CHECK_BOX = "CheckBox"
    DROP_DOWN = "DropDown"
    TEXT_AREA = "TextArea"
    RADIO_BUTTONS = "RadioButtons"
    REFERENCE_SELECTOR = "ReferenceSelector"
    FILE_UPLOAD = "FileUpload"
    IMAGE_UPLOAD = "ImageUpload"
    RICH_TEXT = "RichText"


class InputSource(str, Enum):
    EXCEL = "excel"
    FIGMA = "figma"


class AssociationType(str, Enum):
    ONE_TO_MANY = "1-*"
    MANY_TO_MANY = "*-*"
    ONE_TO_ONE = "1-1"


class FieldVisibility(str, Enum):
    ALL = "Todos"
    CREATE_ONLY = "SoloCrear"
    EDIT_ONLY = "SoloEditar"
    OVERVIEW_ONLY = "SoloOverview"


class ButtonType(str, Enum):
    SAVE = "Save"
    CANCEL = "Cancel"
    DELETE = "Delete"
    NEW = "New"
    EDIT = "Edit"


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


class ConditionalVisibilitySchema(BaseModel):
    """Condición para mostrar/ocultar un widget según otro campo."""

    depends_on: str           # nombre de atributo, ej: "TipoDocumento"
    operator: str = "equals"  # "equals" | "not_empty" | "contains"
    value: str | None = None  # ej: "Otro"


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
    section: str | None = None
    visibility: FieldVisibility = FieldVisibility.ALL
    is_calculated: bool = False
    calculation_expression: str | None = None
    conditional_visibility: ConditionalVisibilitySchema | None = None


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
    generalization: str | None = None
    is_lookup: bool = False
    seed_values: list[str] = Field(default_factory=list)
    has_sequential: bool = False
    is_filter_entity: bool = False


class SectionSchema(BaseModel):
    """Sección visual de una página (agrupa campos)."""

    name: str
    order: int = 0
    attributes: list[str] = Field(default_factory=list)


class ButtonSchema(BaseModel):
    """Botón de acción en una página de Mendix."""

    label: str
    button_type: ButtonType
    microflow: str | None = None      # ej: "ACT_Recepcion_Save"
    target_page: str | None = None    # ej: "Recepcion_Create"
    style: str = "Default"            # "Primary", "Danger", "Default"
    open_as: str = "content"          # "content" | "popup"
    placement: str = "top"            # "top" | "row" (row = per-row in DataGrid)


class NestedListSchema(BaseModel):
    """Lista de entidad hija embebida en un formulario padre (Master-Detail)."""

    child_entity: str
    association: str              # nombre de la asociacion padre-hijo
    display_attributes: list[str] = Field(default_factory=list)
    allow_add: bool = True
    allow_delete: bool = True
    child_page: str | None = None  # pagina que se abre para agregar/editar


class PageSchema(BaseModel):
    """Página de formulario de Mendix."""

    name: str
    page_type: PageType
    entity: str
    module: str
    title: str | None = None
    layout: str = "Atlas_Default"
    sections: list[SectionSchema] = Field(default_factory=list)
    filter_entity: str | None = None
    navigation_items: list[str] = Field(default_factory=list)
    buttons: list[ButtonSchema] = Field(default_factory=list)
    enable_search_bar: bool = True
    nested_lists: list[NestedListSchema] = Field(default_factory=list)
    is_popup: bool = False


class MicroflowSchema(BaseModel):
    """Microflow de Mendix (validación, guardado, etc.)."""

    name: str
    microflow_type: MicroflowType
    entity: str
    module: str
    logic_description: str
    return_entity: str | None = None


class AssociationSchema(BaseModel):
    """Asociación entre dos entidades del Domain Model."""

    name: str
    parent_entity: str
    child_entity: str
    association_type: AssociationType = AssociationType.ONE_TO_MANY
    owner: str = "default"
    cascade_delete: bool = False
    is_lookup: bool = False
    label: str | None = None
    section: str | None = None
    visibility: FieldVisibility = FieldVisibility.ALL
    required: bool = False


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
    associations: list[AssociationSchema] = Field(default_factory=list)
    config: dict[str, str] = Field(default_factory=dict)
    figma_metadata: FigmaExtractionMetadata | None = None
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
