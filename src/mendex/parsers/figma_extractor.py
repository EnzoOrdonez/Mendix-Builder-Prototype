"""Extractor de Figma REST API v1 a IntermediateSchema.

Lee un frame de Figma via la REST API, interpreta la jerarquía de nodos
según convenciones de naming (ver docs/figma_naming_conventions.md), y
genera un IntermediateSchema unificado.

Convenciones de naming en Figma:
- form_{EntityName}        → Entidad (frame principal)
- input_{FieldName}_{type} → Atributo (text|number|decimal|date|bool|enum|textarea)
- label_{FieldName}        → Etiqueta del campo
- required_{FieldName}     → Marca de campo requerido
- btn_{Action}             → Botón (Submit/Save genera microflow)
- group_{SectionName}      → Grupo/sección (visual, no genera entidad)

Autenticación:
- Variable de entorno FIGMA_ACCESS_TOKEN (Personal Access Token)
- Header: X-Figma-Token: {token}

Fase 7: Implementación completa.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, parse_qs

import structlog

from mendex.schema.intermediate import (
    AttributeSchema,
    EntitySchema,
    FigmaExtractionMetadata,
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


FIGMA_API_BASE = "https://api.figma.com/v1"

# Mapeo de sufijo de tipo Figma a MendixDataType
FIGMA_TYPE_MAP: dict[str, MendixDataType] = {
    "text": MendixDataType.STRING,
    "string": MendixDataType.STRING,
    "number": MendixDataType.INTEGER,
    "integer": MendixDataType.INTEGER,
    "int": MendixDataType.INTEGER,
    "decimal": MendixDataType.DECIMAL,
    "float": MendixDataType.DECIMAL,
    "date": MendixDataType.DATETIME,
    "datetime": MendixDataType.DATETIME,
    "bool": MendixDataType.BOOLEAN,
    "boolean": MendixDataType.BOOLEAN,
    "enum": MendixDataType.ENUMERATION,
    "textarea": MendixDataType.STRING,
}

# Mapeo de tipo Figma a WidgetType
FIGMA_WIDGET_MAP: dict[str, WidgetType] = {
    "text": WidgetType.TEXT_INPUT,
    "string": WidgetType.TEXT_INPUT,
    "number": WidgetType.NUMBER_INPUT,
    "integer": WidgetType.NUMBER_INPUT,
    "int": WidgetType.NUMBER_INPUT,
    "decimal": WidgetType.NUMBER_INPUT,
    "float": WidgetType.NUMBER_INPUT,
    "date": WidgetType.DATE_PICKER,
    "datetime": WidgetType.DATE_PICKER,
    "bool": WidgetType.CHECK_BOX,
    "boolean": WidgetType.CHECK_BOX,
    "enum": WidgetType.DROP_DOWN,
    "textarea": WidgetType.TEXT_AREA,
}

# Botones que generan microflows
SUBMIT_ACTIONS = {"submit", "save", "guardar", "enviar", "confirmar"}
DELETE_ACTIONS = {"delete", "eliminar", "borrar", "remove"}


# ─── Excepciones ─────────────────────────────────────────────


class FigmaExtractorError(Exception):
    """Error general del extractor de Figma."""


class FigmaAuthError(FigmaExtractorError):
    """Error de autenticación con Figma API."""


class FigmaAPIError(FigmaExtractorError):
    """Error al comunicarse con Figma API."""


class FigmaStructureError(FigmaExtractorError):
    """Error en la estructura del frame de Figma."""


# ─── Data classes para nodos parseados ───────────────────────


class _ParsedField:
    """Campo parseado de un nodo input_* de Figma."""

    def __init__(
        self,
        name: str,
        figma_type: str,
        mendix_type: MendixDataType,
        widget_type: WidgetType | None = None,
        label: str | None = None,
        required: bool = False,
    ) -> None:
        self.name = name
        self.figma_type = figma_type
        self.mendix_type = mendix_type
        self.widget_type = widget_type
        self.label = label or name
        self.required = required


class _ParsedForm:
    """Formulario parseado de un frame form_* de Figma."""

    def __init__(self, entity_name: str) -> None:
        self.entity_name = entity_name
        self.fields: list[_ParsedField] = []
        self.labels: dict[str, str] = {}  # field_name → label text
        self.required_fields: set[str] = set()
        self.buttons: list[str] = []  # action names
        self.nested_forms: list[_ParsedForm] = []
        self.warnings: list[str] = []


# ─── Extractor ───────────────────────────────────────────────


class FigmaExtractor:
    """Extrae diseños de Figma y los convierte a IntermediateSchema.

    Usa la Figma REST API v1 para obtener el árbol de nodos de un frame
    específico, luego interpreta la jerarquía según convenciones de naming.

    Uso:
        extractor = FigmaExtractor(access_token="figd_...")
        schema = extractor.extract(
            file_key="abc123",
            node_id="456:789",
            module="Operaciones",
        )

    Alternativamente, desde URL:
        schema = extractor.extract_from_url(
            "https://www.figma.com/file/abc123/MiProyecto?node-id=456:789",
            module="Operaciones",
        )
    """

    def __init__(
        self,
        access_token: str,
        generate_pages: bool = True,
        generate_microflows: bool = True,
    ) -> None:
        if not access_token:
            raise FigmaAuthError(
                "FIGMA_ACCESS_TOKEN no proporcionado. "
                "Configura la variable de entorno o pasa el token al constructor."
            )
        self._token = access_token
        self._generate_pages = generate_pages
        self._generate_microflows = generate_microflows

    def extract(
        self,
        file_key: str,
        node_id: str,
        *,
        module: str = "MyFirstModule",
    ) -> IntermediateSchema:
        """Extrae un frame de Figma y lo convierte a IntermediateSchema.

        Args:
            file_key: Key del archivo Figma (de la URL).
            node_id: ID del nodo/frame a extraer.
            module: Módulo Mendix destino.

        Returns:
            IntermediateSchema con entidades, páginas y microflows.
        """
        logger.info(
            "figma_extraction_started",
            file_key=file_key,
            node_id=node_id,
        )

        # 1. Fetch del árbol de nodos
        file_data = self._fetch_file_metadata(file_key)
        nodes_data = self._fetch_nodes(file_key, node_id)

        # 2. Obtener el nodo raíz
        node_key = node_id.replace("-", ":")
        if node_key not in nodes_data.get("nodes", {}):
            raise FigmaStructureError(
                f"Nodo '{node_id}' no encontrado en el archivo Figma. "
                "Verifica que el node-id sea correcto."
            )

        root_node = nodes_data["nodes"][node_key]["document"]

        # 3. Parsear el árbol
        forms = self._parse_node_tree(root_node)
        if not forms:
            raise FigmaStructureError(
                f"No se encontró ningún frame con prefijo 'form_' en el nodo "
                f"'{node_id}'. Asegúrate de seguir las convenciones de naming "
                "(ver docs/figma_naming_conventions.md)."
            )

        # 4. Convertir a IntermediateSchema
        all_warnings: list[str] = []
        entities: list[EntitySchema] = []
        pages: list[PageSchema] = []
        microflows: list[MicroflowSchema] = []

        for form in forms:
            entity, form_pages, form_mfs = self._form_to_schema(form, module)
            entities.append(entity)
            pages.extend(form_pages)
            microflows.extend(form_mfs)
            all_warnings.extend(form.warnings)

        metadata = FigmaExtractionMetadata(
            file_key=file_key,
            node_id=node_id,
            frame_name=root_node.get("name", "unknown"),
            extraction_timestamp=datetime.now(timezone.utc),
            figma_last_modified=file_data.get("lastModified"),
            warnings=all_warnings,
        )

        logger.info(
            "figma_extraction_complete",
            entities=len(entities),
            pages=len(pages),
            microflows=len(microflows),
            warnings=len(all_warnings),
        )

        return IntermediateSchema(
            source=InputSource.FIGMA,
            source_file=f"figma://{file_key}/{node_id}",
            entities=entities,
            pages=pages,
            microflows=microflows,
            figma_metadata=metadata,
        )

    def extract_from_url(
        self,
        figma_url: str,
        *,
        module: str = "MyFirstModule",
    ) -> IntermediateSchema:
        """Extrae desde una URL de Figma.

        Args:
            figma_url: URL completa de Figma (con node-id en query params).
            module: Módulo Mendix destino.

        Returns:
            IntermediateSchema.
        """
        file_key, node_id = self.parse_figma_url(figma_url)
        return self.extract(file_key, node_id, module=module)

    def extract_from_node_data(
        self,
        node_data: dict[str, Any],
        *,
        file_key: str = "local",
        node_id: str = "0:0",
        module: str = "MyFirstModule",
        last_modified: str | None = None,
    ) -> IntermediateSchema:
        """Extrae desde datos de nodo ya obtenidos (para tests/offline).

        Args:
            node_data: Árbol de nodos Figma (formato de la API).
            file_key: Key del archivo (informativo).
            node_id: ID del nodo (informativo).
            module: Módulo Mendix destino.
            last_modified: Fecha de última modificación.

        Returns:
            IntermediateSchema.
        """
        forms = self._parse_node_tree(node_data)
        if not forms:
            raise FigmaStructureError(
                "No se encontró ningún frame con prefijo 'form_' en los datos."
            )

        all_warnings: list[str] = []
        entities: list[EntitySchema] = []
        pages: list[PageSchema] = []
        microflows: list[MicroflowSchema] = []

        for form in forms:
            entity, form_pages, form_mfs = self._form_to_schema(form, module)
            entities.append(entity)
            pages.extend(form_pages)
            microflows.extend(form_mfs)
            all_warnings.extend(form.warnings)

        metadata = FigmaExtractionMetadata(
            file_key=file_key,
            node_id=node_id,
            frame_name=node_data.get("name", "unknown"),
            extraction_timestamp=datetime.now(timezone.utc),
            figma_last_modified=last_modified,
            warnings=all_warnings,
        )

        return IntermediateSchema(
            source=InputSource.FIGMA,
            source_file=f"figma://{file_key}/{node_id}",
            entities=entities,
            pages=pages,
            microflows=microflows,
            figma_metadata=metadata,
        )

    # ─── API calls ───────────────────────────────────────────

    def _fetch_file_metadata(self, file_key: str) -> dict[str, Any]:
        """Obtiene metadata del archivo Figma."""
        try:
            import httpx
        except ImportError:
            raise FigmaExtractorError(
                "httpx no instalado. Ejecuta: pip install httpx"
            )

        url = f"{FIGMA_API_BASE}/files/{file_key}"
        headers = {"X-Figma-Token": self._token}

        try:
            response = httpx.get(
                url,
                headers=headers,
                params={"depth": 1},  # Solo metadata, no el árbol completo
                timeout=30,
            )
        except httpx.HTTPError as e:
            raise FigmaAPIError(f"Error de conexión con Figma API: {e}") from e

        if response.status_code == 403:
            raise FigmaAuthError(
                "Token de Figma inválido o sin permisos para este archivo."
            )
        if response.status_code == 404:
            raise FigmaAPIError(
                f"Archivo Figma '{file_key}' no encontrado."
            )
        if response.status_code == 429:
            raise FigmaAPIError(
                "Rate limit de Figma API excedido. Espera unos minutos e intenta de nuevo."
            )
        if response.status_code != 200:
            raise FigmaAPIError(
                f"Figma API retornó status {response.status_code}: {response.text[:200]}"
            )

        return response.json()

    def _fetch_nodes(self, file_key: str, node_id: str) -> dict[str, Any]:
        """Obtiene los nodos de un frame específico."""
        try:
            import httpx
        except ImportError:
            raise FigmaExtractorError(
                "httpx no instalado. Ejecuta: pip install httpx"
            )

        # La API usa : como separador, las URLs usan -
        api_node_id = node_id.replace("-", ":")
        url = f"{FIGMA_API_BASE}/files/{file_key}/nodes"
        headers = {"X-Figma-Token": self._token}

        try:
            response = httpx.get(
                url,
                headers=headers,
                params={"ids": api_node_id},
                timeout=30,
            )
        except httpx.HTTPError as e:
            raise FigmaAPIError(f"Error de conexión con Figma API: {e}") from e

        if response.status_code != 200:
            raise FigmaAPIError(
                f"Figma API retornó status {response.status_code} al obtener nodos"
            )

        return response.json()

    # ─── Parseo del árbol de nodos ───────────────────────────

    def _parse_node_tree(self, node: dict[str, Any]) -> list[_ParsedForm]:
        """Parsea recursivamente el árbol de nodos buscando form_* frames."""
        forms: list[_ParsedForm] = []
        name = node.get("name", "")

        # ¿Es un form_* frame?
        if self._is_form_frame(name):
            entity_name = self._extract_form_name(name)
            form = _ParsedForm(entity_name)
            self._collect_form_children(node, form)
            # Resolver labels y required
            self._resolve_field_metadata(form)
            forms.append(form)
            # También agregar nested forms
            forms.extend(form.nested_forms)
        else:
            # Buscar recursivamente en children
            for child in node.get("children", []):
                forms.extend(self._parse_node_tree(child))

        return forms

    def _collect_form_children(
        self, node: dict[str, Any], form: _ParsedForm
    ) -> None:
        """Recolecta campos, labels, botones y subforms de un nodo form_*."""
        for child in node.get("children", []):
            name = child.get("name", "")
            node_type = child.get("type", "")

            if self._is_form_frame(name):
                # Nested form → entidad hija
                nested_entity = self._extract_form_name(name)
                nested_form = _ParsedForm(nested_entity)
                self._collect_form_children(child, nested_form)
                self._resolve_field_metadata(nested_form)
                form.nested_forms.append(nested_form)

            elif self._is_input_node(name):
                field = self._parse_input_node(name, form)
                if field:
                    form.fields.append(field)

            elif self._is_label_node(name):
                field_name = self._extract_label_name(name)
                # Intentar obtener el texto del label
                label_text = self._extract_text_content(child)
                form.labels[field_name] = label_text or field_name

            elif self._is_required_node(name):
                field_name = self._extract_required_name(name)
                form.required_fields.add(field_name)

            elif self._is_button_node(name):
                action = self._extract_button_action(name)
                form.buttons.append(action)

            elif self._is_group_node(name):
                # Recurse into group (it's visual-only grouping)
                self._collect_form_children(child, form)

            else:
                # Check for asterisk text nodes (required indicator)
                if node_type == "TEXT":
                    text = child.get("characters", "").strip()
                    if text == "*":
                        # Try to find adjacent input
                        pass  # Handled by required_ convention primarily

                # Recurse into unknown containers (FRAME, INSTANCE, GROUP, etc.)
                if child.get("children"):
                    self._collect_form_children(child, form)

    def _resolve_field_metadata(self, form: _ParsedForm) -> None:
        """Resuelve labels y required para los campos parseados."""
        for field in form.fields:
            # Resolver label
            if field.name in form.labels:
                field.label = form.labels[field.name]

            # Resolver required
            if field.name in form.required_fields:
                field.required = True

    # ─── Node type detection ─────────────────────────────────

    @staticmethod
    def _is_form_frame(name: str) -> bool:
        return name.lower().startswith("form_")

    @staticmethod
    def _is_input_node(name: str) -> bool:
        return name.lower().startswith("input_")

    @staticmethod
    def _is_label_node(name: str) -> bool:
        return name.lower().startswith("label_")

    @staticmethod
    def _is_required_node(name: str) -> bool:
        return name.lower().startswith("required_")

    @staticmethod
    def _is_button_node(name: str) -> bool:
        return name.lower().startswith("btn_")

    @staticmethod
    def _is_group_node(name: str) -> bool:
        return name.lower().startswith("group_")

    # ─── Name extraction ─────────────────────────────────────

    @staticmethod
    def _extract_form_name(name: str) -> str:
        """Extrae el nombre de entidad de form_{EntityName}."""
        # Remove 'form_' prefix (case-insensitive)
        raw = re.sub(r"^form_", "", name, flags=re.IGNORECASE).strip()
        return raw or "UnnamedEntity"

    @staticmethod
    def _extract_label_name(name: str) -> str:
        """Extrae el nombre del campo de label_{FieldName}."""
        return re.sub(r"^label_", "", name, flags=re.IGNORECASE).strip()

    @staticmethod
    def _extract_required_name(name: str) -> str:
        """Extrae el nombre del campo de required_{FieldName}."""
        return re.sub(r"^required_", "", name, flags=re.IGNORECASE).strip()

    @staticmethod
    def _extract_button_action(name: str) -> str:
        """Extrae la acción del botón de btn_{Action}."""
        return re.sub(r"^btn_", "", name, flags=re.IGNORECASE).strip()

    def _parse_input_node(
        self, name: str, form: _ParsedForm
    ) -> _ParsedField | None:
        """Parsea un nodo input_{FieldName}_{type} a _ParsedField."""
        # Remove 'input_' prefix
        raw = re.sub(r"^input_", "", name, flags=re.IGNORECASE).strip()
        if not raw:
            form.warnings.append(f"Nodo input vacío: '{name}'")
            return None

        # Split by last underscore to get field_name and type
        parts = raw.rsplit("_", 1)
        if len(parts) == 2:
            field_name, type_suffix = parts
            type_suffix = type_suffix.lower()
        else:
            field_name = parts[0]
            type_suffix = "text"
            form.warnings.append(
                f"Input '{name}' sin sufijo de tipo — asumiendo 'text'"
            )

        # Map type
        mendix_type = FIGMA_TYPE_MAP.get(type_suffix)
        widget_type = FIGMA_WIDGET_MAP.get(type_suffix)

        if mendix_type is None:
            form.warnings.append(
                f"Tipo '{type_suffix}' no reconocido en '{name}' — "
                "asumiendo String (text)"
            )
            mendix_type = MendixDataType.STRING
            widget_type = WidgetType.TEXT_INPUT

        return _ParsedField(
            name=field_name,
            figma_type=type_suffix,
            mendix_type=mendix_type,
            widget_type=widget_type,
        )

    @staticmethod
    def _extract_text_content(node: dict[str, Any]) -> str | None:
        """Extrae el contenido de texto de un nodo o sus hijos."""
        # Direct text node
        if node.get("type") == "TEXT":
            return node.get("characters", "").strip() or None

        # Search in children for text
        for child in node.get("children", []):
            if child.get("type") == "TEXT":
                text = child.get("characters", "").strip()
                if text:
                    return text

        return None

    # ─── Conversion to IntermediateSchema ────────────────────

    def _form_to_schema(
        self, form: _ParsedForm, module: str
    ) -> tuple[EntitySchema, list[PageSchema], list[MicroflowSchema]]:
        """Convierte un _ParsedForm a EntitySchema + pages + microflows."""
        attributes: list[AttributeSchema] = []

        for field in form.fields:
            validations: list[ValidationRuleSchema] = []
            if field.required:
                validations.append(
                    ValidationRuleSchema(
                        type=ValidationType.REQUIRED,
                        params={},
                        error_message=f"El campo {field.name} es requerido",
                    )
                )

            attributes.append(
                AttributeSchema(
                    name=field.name,
                    mendix_type=field.mendix_type,
                    label=field.label,
                    required=field.required,
                    validations=validations,
                    widget_type=field.widget_type,
                )
            )

        if not attributes:
            form.warnings.append(
                f"Formulario '{form.entity_name}' no contiene campos (inputs)"
            )

        entity = EntitySchema(
            name=form.entity_name,
            module=module,
            attributes=attributes,
        )

        # Pages
        pages: list[PageSchema] = []
        if self._generate_pages and attributes:
            pages = [
                PageSchema(
                    name=f"{form.entity_name}_Create",
                    page_type=PageType.CREATE,
                    entity=form.entity_name,
                    module=module,
                    title=f"{form.entity_name} — Create",
                ),
                PageSchema(
                    name=f"{form.entity_name}_Overview",
                    page_type=PageType.OVERVIEW,
                    entity=form.entity_name,
                    module=module,
                    title=f"{form.entity_name} — Overview",
                ),
            ]

        # Microflows
        microflows: list[MicroflowSchema] = []
        if self._generate_microflows and attributes:
            # Always generate validation + save
            microflows.append(
                MicroflowSchema(
                    name=f"VAL_{form.entity_name}_Validate",
                    microflow_type=MicroflowType.VALIDATION,
                    entity=form.entity_name,
                    module=module,
                    logic_description=(
                        f"Valida campos requeridos de {form.entity_name}."
                    ),
                )
            )
            microflows.append(
                MicroflowSchema(
                    name=f"ACT_{form.entity_name}_Save",
                    microflow_type=MicroflowType.SAVE,
                    entity=form.entity_name,
                    module=module,
                    logic_description=(
                        f"Ejecuta validación y guarda {form.entity_name}."
                    ),
                )
            )

            # Delete microflow if there's a delete button
            for btn in form.buttons:
                if btn.lower() in DELETE_ACTIONS:
                    microflows.append(
                        MicroflowSchema(
                            name=f"ACT_{form.entity_name}_Delete",
                            microflow_type=MicroflowType.DELETE,
                            entity=form.entity_name,
                            module=module,
                            logic_description=(
                                f"Elimina la entidad {form.entity_name} "
                                "con confirmación."
                            ),
                        )
                    )
                    break

        return entity, pages, microflows

    # ─── URL parsing ─────────────────────────────────────────

    @staticmethod
    def parse_figma_url(url: str) -> tuple[str, str]:
        """Parsea una URL de Figma y extrae file_key y node_id.

        Formatos soportados:
        - https://www.figma.com/file/{key}/{name}?node-id={id}
        - https://www.figma.com/design/{key}/{name}?node-id={id}

        Returns:
            Tupla (file_key, node_id).
        """
        parsed = urlparse(url)

        if not parsed.hostname or "figma.com" not in parsed.hostname:
            raise FigmaExtractorError(
                f"URL no es de Figma: {url}"
            )

        # Extract file_key from path
        path_parts = [p for p in parsed.path.split("/") if p]
        # Expected: ['file'|'design', '{key}', '{name}']
        if len(path_parts) < 2:
            raise FigmaExtractorError(
                f"URL de Figma inválida (falta file key): {url}"
            )

        if path_parts[0] not in ("file", "design"):
            raise FigmaExtractorError(
                f"URL de Figma inválida (tipo no reconocido: {path_parts[0]}): {url}"
            )

        file_key = path_parts[1]

        # Extract node_id from query params
        query_params = parse_qs(parsed.query)
        node_ids = query_params.get("node-id", [])
        if not node_ids:
            raise FigmaExtractorError(
                f"URL de Figma sin node-id: {url}. "
                "Selecciona un frame y copia su URL con node-id."
            )

        node_id = node_ids[0]

        return file_key, node_id
