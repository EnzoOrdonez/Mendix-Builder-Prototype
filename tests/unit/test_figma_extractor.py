"""Tests para el extractor de Figma a IntermediateSchema.

Fase 7: Tests unitarios completos.

Todos los tests usan extract_from_node_data() para evitar llamadas
reales a la Figma API. El fixture figma_response_mock.json simula
una respuesta real de la API.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from mendex.parsers.figma_extractor import (
    FigmaAuthError,
    FigmaExtractor,
    FigmaExtractorError,
    FigmaStructureError,
)
from mendex.schema.intermediate import (
    InputSource,
    MendixDataType,
    MicroflowType,
    PageType,
    ValidationType,
    WidgetType,
)


# ─── Fixtures ────────────────────────────────────────────────


@pytest.fixture
def extractor() -> FigmaExtractor:
    """Extractor con token dummy (solo para extract_from_node_data)."""
    return FigmaExtractor(access_token="figd_test_token_12345")


@pytest.fixture
def mock_figma_data() -> dict[str, Any]:
    """Carga el mock de respuesta Figma desde el fixture JSON."""
    fixture_path = Path(__file__).parent.parent.parent / "fixtures" / "figma_response_mock.json"
    with open(fixture_path, encoding="utf-8") as f:
        return json.load(f)


def _make_simple_form(
    entity_name: str = "TestEntity",
    fields: list[dict[str, str]] | None = None,
    buttons: list[str] | None = None,
    labels: dict[str, str] | None = None,
    required: list[str] | None = None,
) -> dict[str, Any]:
    """Helper para crear un nodo form_* Figma simple."""
    children: list[dict[str, Any]] = []

    for field in (fields or [{"name": "Campo1", "type": "text"}]):
        fname = field["name"]
        ftype = field.get("type", "text")

        # Label
        if labels and fname in labels:
            children.append({
                "name": f"label_{fname}",
                "type": "TEXT",
                "characters": labels[fname],
            })
        else:
            children.append({
                "name": f"label_{fname}",
                "type": "TEXT",
                "characters": fname,
            })

        # Input
        children.append({
            "name": f"input_{fname}_{ftype}",
            "type": "INSTANCE",
            "children": [],
        })

        # Required
        if required and fname in required:
            children.append({
                "name": f"required_{fname}",
                "type": "TEXT",
                "characters": "*",
            })

    for btn in (buttons or []):
        children.append({
            "name": f"btn_{btn}",
            "type": "INSTANCE",
            "children": [],
        })

    return {
        "name": f"form_{entity_name}",
        "type": "FRAME",
        "children": children,
    }


# ─── Tests: Constructor ─────────────────────────────────────


class TestFigmaExtractorInit:
    """Tests para inicialización del extractor."""

    def test_init_with_token(self):
        ext = FigmaExtractor(access_token="figd_token")
        assert ext is not None

    def test_init_without_token_raises(self):
        with pytest.raises(FigmaAuthError, match="FIGMA_ACCESS_TOKEN"):
            FigmaExtractor(access_token="")

    def test_init_none_token_raises(self):
        with pytest.raises(FigmaAuthError):
            FigmaExtractor(access_token=None)  # type: ignore[arg-type]


# ─── Tests: Parseo del fixture completo ──────────────────────


class TestFigmaFullFixture:
    """Tests con el fixture figma_response_mock.json completo."""

    def test_extract_entities(self, extractor: FigmaExtractor, mock_figma_data: dict):
        schema = extractor.extract_from_node_data(mock_figma_data, module="Operaciones")
        assert schema.source == InputSource.FIGMA
        # Should find OrdenCompra (root) + LineaDetalle (nested)
        assert len(schema.entities) == 2
        names = {e.name for e in schema.entities}
        assert "OrdenCompra" in names
        assert "LineaDetalle" in names

    def test_orden_compra_attributes(self, extractor: FigmaExtractor, mock_figma_data: dict):
        schema = extractor.extract_from_node_data(mock_figma_data, module="Op")
        oc = next(e for e in schema.entities if e.name == "OrdenCompra")
        attr_names = {a.name for a in oc.attributes}
        assert "Numero" in attr_names
        assert "FechaCreacion" in attr_names
        assert "MontoTotal" in attr_names
        assert "Descripcion" in attr_names
        assert "Estado" in attr_names
        assert "Activo" in attr_names

    def test_attribute_types(self, extractor: FigmaExtractor, mock_figma_data: dict):
        schema = extractor.extract_from_node_data(mock_figma_data)
        oc = next(e for e in schema.entities if e.name == "OrdenCompra")
        attrs = {a.name: a for a in oc.attributes}
        assert attrs["Numero"].mendix_type == MendixDataType.INTEGER
        assert attrs["FechaCreacion"].mendix_type == MendixDataType.DATETIME
        assert attrs["MontoTotal"].mendix_type == MendixDataType.DECIMAL
        assert attrs["Descripcion"].mendix_type == MendixDataType.STRING
        assert attrs["Estado"].mendix_type == MendixDataType.ENUMERATION
        assert attrs["Activo"].mendix_type == MendixDataType.BOOLEAN

    def test_widget_types(self, extractor: FigmaExtractor, mock_figma_data: dict):
        schema = extractor.extract_from_node_data(mock_figma_data)
        oc = next(e for e in schema.entities if e.name == "OrdenCompra")
        attrs = {a.name: a for a in oc.attributes}
        assert attrs["Numero"].widget_type == WidgetType.NUMBER_INPUT
        assert attrs["FechaCreacion"].widget_type == WidgetType.DATE_PICKER
        assert attrs["MontoTotal"].widget_type == WidgetType.NUMBER_INPUT
        assert attrs["Descripcion"].widget_type == WidgetType.TEXT_AREA
        assert attrs["Estado"].widget_type == WidgetType.DROP_DOWN
        assert attrs["Activo"].widget_type == WidgetType.CHECK_BOX

    def test_required_fields(self, extractor: FigmaExtractor, mock_figma_data: dict):
        schema = extractor.extract_from_node_data(mock_figma_data)
        oc = next(e for e in schema.entities if e.name == "OrdenCompra")
        attrs = {a.name: a for a in oc.attributes}
        assert attrs["Numero"].required is True
        assert attrs["FechaCreacion"].required is True
        assert attrs["MontoTotal"].required is True
        assert attrs["Descripcion"].required is False
        assert attrs["Estado"].required is False

    def test_labels_from_text(self, extractor: FigmaExtractor, mock_figma_data: dict):
        schema = extractor.extract_from_node_data(mock_figma_data)
        oc = next(e for e in schema.entities if e.name == "OrdenCompra")
        attrs = {a.name: a for a in oc.attributes}
        assert attrs["Numero"].label == "Número de Orden"
        assert attrs["FechaCreacion"].label == "Fecha de Creación"
        assert attrs["MontoTotal"].label == "Monto Total"
        assert attrs["Descripcion"].label == "Descripción"

    def test_nested_entity_linea_detalle(self, extractor: FigmaExtractor, mock_figma_data: dict):
        schema = extractor.extract_from_node_data(mock_figma_data)
        ld = next(e for e in schema.entities if e.name == "LineaDetalle")
        attr_names = {a.name for a in ld.attributes}
        assert "Producto" in attr_names
        assert "Cantidad" in attr_names
        assert "PrecioUnitario" in attr_names

    def test_nested_entity_required(self, extractor: FigmaExtractor, mock_figma_data: dict):
        schema = extractor.extract_from_node_data(mock_figma_data)
        ld = next(e for e in schema.entities if e.name == "LineaDetalle")
        attrs = {a.name: a for a in ld.attributes}
        assert attrs["Producto"].required is True
        assert attrs["Cantidad"].required is False

    def test_pages_generated(self, extractor: FigmaExtractor, mock_figma_data: dict):
        schema = extractor.extract_from_node_data(mock_figma_data)
        # 2 entities × 2 pages (Create + Overview) = 4
        assert len(schema.pages) == 4
        page_names = {p.name for p in schema.pages}
        assert "OrdenCompra_Create" in page_names
        assert "OrdenCompra_Overview" in page_names
        assert "LineaDetalle_Create" in page_names

    def test_microflows_generated(self, extractor: FigmaExtractor, mock_figma_data: dict):
        schema = extractor.extract_from_node_data(mock_figma_data)
        mf_names = {mf.name for mf in schema.microflows}
        # OrdenCompra: Validate + Save + Delete (btn_Delete present)
        assert "VAL_OrdenCompra_Validate" in mf_names
        assert "ACT_OrdenCompra_Save" in mf_names
        assert "ACT_OrdenCompra_Delete" in mf_names
        # LineaDetalle: Validate + Save (no delete button)
        assert "VAL_LineaDetalle_Validate" in mf_names
        assert "ACT_LineaDetalle_Save" in mf_names

    def test_figma_metadata(self, extractor: FigmaExtractor, mock_figma_data: dict):
        schema = extractor.extract_from_node_data(
            mock_figma_data,
            file_key="abc123",
            node_id="1:2",
            last_modified="2025-01-15T10:00:00Z",
        )
        assert schema.figma_metadata is not None
        assert schema.figma_metadata.file_key == "abc123"
        assert schema.figma_metadata.node_id == "1:2"
        assert schema.figma_metadata.figma_last_modified == "2025-01-15T10:00:00Z"
        assert schema.figma_metadata.frame_name == "form_OrdenCompra"

    def test_source_file_format(self, extractor: FigmaExtractor, mock_figma_data: dict):
        schema = extractor.extract_from_node_data(
            mock_figma_data, file_key="abc", node_id="1:2"
        )
        assert schema.source_file == "figma://abc/1:2"


# ─── Tests: Parseo simple ───────────────────────────────────


class TestFigmaSimpleForm:
    """Tests con formularios construidos in-memory."""

    def test_single_text_field(self, extractor: FigmaExtractor):
        node = _make_simple_form(
            entity_name="Producto",
            fields=[{"name": "Nombre", "type": "text"}],
        )
        schema = extractor.extract_from_node_data(node)
        assert len(schema.entities) == 1
        assert schema.entities[0].name == "Producto"
        assert len(schema.entities[0].attributes) == 1
        assert schema.entities[0].attributes[0].name == "Nombre"
        assert schema.entities[0].attributes[0].mendix_type == MendixDataType.STRING

    def test_multiple_field_types(self, extractor: FigmaExtractor):
        node = _make_simple_form(
            fields=[
                {"name": "Texto", "type": "text"},
                {"name": "Num", "type": "number"},
                {"name": "Dec", "type": "decimal"},
                {"name": "Fech", "type": "date"},
                {"name": "Flag", "type": "bool"},
                {"name": "Tipo", "type": "enum"},
            ],
        )
        schema = extractor.extract_from_node_data(node)
        attrs = {a.name: a for a in schema.entities[0].attributes}
        assert attrs["Texto"].mendix_type == MendixDataType.STRING
        assert attrs["Num"].mendix_type == MendixDataType.INTEGER
        assert attrs["Dec"].mendix_type == MendixDataType.DECIMAL
        assert attrs["Fech"].mendix_type == MendixDataType.DATETIME
        assert attrs["Flag"].mendix_type == MendixDataType.BOOLEAN
        assert attrs["Tipo"].mendix_type == MendixDataType.ENUMERATION

    def test_required_fields(self, extractor: FigmaExtractor):
        node = _make_simple_form(
            fields=[
                {"name": "Nombre", "type": "text"},
                {"name": "Edad", "type": "number"},
            ],
            required=["Nombre"],
        )
        schema = extractor.extract_from_node_data(node)
        attrs = {a.name: a for a in schema.entities[0].attributes}
        assert attrs["Nombre"].required is True
        assert attrs["Edad"].required is False

    def test_required_adds_validation(self, extractor: FigmaExtractor):
        node = _make_simple_form(
            fields=[{"name": "Nombre", "type": "text"}],
            required=["Nombre"],
        )
        schema = extractor.extract_from_node_data(node)
        validations = schema.entities[0].attributes[0].validations
        assert any(v.type == ValidationType.REQUIRED for v in validations)

    def test_labels_applied(self, extractor: FigmaExtractor):
        node = _make_simple_form(
            fields=[{"name": "NombreCompleto", "type": "text"}],
            labels={"NombreCompleto": "Nombre Completo del Usuario"},
        )
        schema = extractor.extract_from_node_data(node)
        assert schema.entities[0].attributes[0].label == "Nombre Completo del Usuario"

    def test_label_defaults_to_field_name(self, extractor: FigmaExtractor):
        node = _make_simple_form(
            fields=[{"name": "Campo", "type": "text"}],
        )
        schema = extractor.extract_from_node_data(node)
        assert schema.entities[0].attributes[0].label == "Campo"

    def test_submit_button_generates_microflows(self, extractor: FigmaExtractor):
        node = _make_simple_form(
            fields=[{"name": "Campo", "type": "text"}],
            buttons=["Submit"],
        )
        schema = extractor.extract_from_node_data(node)
        mf_names = {mf.name for mf in schema.microflows}
        assert "VAL_TestEntity_Validate" in mf_names
        assert "ACT_TestEntity_Save" in mf_names

    def test_delete_button_generates_delete_microflow(self, extractor: FigmaExtractor):
        node = _make_simple_form(
            fields=[{"name": "Campo", "type": "text"}],
            buttons=["Submit", "Delete"],
        )
        schema = extractor.extract_from_node_data(node)
        mf_names = {mf.name for mf in schema.microflows}
        assert "ACT_TestEntity_Delete" in mf_names

    def test_module_assignment(self, extractor: FigmaExtractor):
        node = _make_simple_form(
            fields=[{"name": "Campo", "type": "text"}],
        )
        schema = extractor.extract_from_node_data(node, module="Operaciones")
        assert schema.entities[0].module == "Operaciones"
        for page in schema.pages:
            assert page.module == "Operaciones"
        for mf in schema.microflows:
            assert mf.module == "Operaciones"


# ─── Tests: Grupos ───────────────────────────────────────────


class TestFigmaGroups:
    """Tests para nodos group_* (secciones visuales)."""

    def test_group_children_collected(self, extractor: FigmaExtractor):
        """Fields inside groups are collected into the parent form."""
        node = {
            "name": "form_Test",
            "type": "FRAME",
            "children": [
                {
                    "name": "group_Section1",
                    "type": "FRAME",
                    "children": [
                        {"name": "input_Campo1_text", "type": "INSTANCE", "children": []},
                    ],
                },
                {
                    "name": "group_Section2",
                    "type": "FRAME",
                    "children": [
                        {"name": "input_Campo2_number", "type": "INSTANCE", "children": []},
                    ],
                },
            ],
        }
        schema = extractor.extract_from_node_data(node)
        assert len(schema.entities) == 1
        assert len(schema.entities[0].attributes) == 2


# ─── Tests: Nested forms ────────────────────────────────────


class TestFigmaNestedForms:
    """Tests para formularios anidados (relación 1-N)."""

    def test_nested_form_separate_entity(self, extractor: FigmaExtractor):
        node = {
            "name": "form_Parent",
            "type": "FRAME",
            "children": [
                {"name": "input_Nombre_text", "type": "INSTANCE", "children": []},
                {
                    "name": "form_Child",
                    "type": "FRAME",
                    "children": [
                        {"name": "input_Detalle_text", "type": "INSTANCE", "children": []},
                    ],
                },
            ],
        }
        schema = extractor.extract_from_node_data(node)
        assert len(schema.entities) == 2
        names = {e.name for e in schema.entities}
        assert "Parent" in names
        assert "Child" in names

    def test_nested_form_parent_excludes_child_fields(self, extractor: FigmaExtractor):
        node = {
            "name": "form_Parent",
            "type": "FRAME",
            "children": [
                {"name": "input_ParentField_text", "type": "INSTANCE", "children": []},
                {
                    "name": "form_Child",
                    "type": "FRAME",
                    "children": [
                        {"name": "input_ChildField_text", "type": "INSTANCE", "children": []},
                    ],
                },
            ],
        }
        schema = extractor.extract_from_node_data(node)
        parent = next(e for e in schema.entities if e.name == "Parent")
        child = next(e for e in schema.entities if e.name == "Child")
        assert len(parent.attributes) == 1
        assert parent.attributes[0].name == "ParentField"
        assert len(child.attributes) == 1
        assert child.attributes[0].name == "ChildField"


# ─── Tests: Warnings ────────────────────────────────────────


class TestFigmaWarnings:
    """Tests para warnings generados durante extracción."""

    def test_input_without_type_suffix(self, extractor: FigmaExtractor):
        node = {
            "name": "form_Test",
            "type": "FRAME",
            "children": [
                {"name": "input_SinTipo", "type": "INSTANCE", "children": []},
            ],
        }
        schema = extractor.extract_from_node_data(node)
        assert schema.entities[0].attributes[0].mendix_type == MendixDataType.STRING
        assert schema.figma_metadata is not None
        assert any("sin sufijo" in w.lower() or "asumiendo" in w.lower()
                    for w in schema.figma_metadata.warnings)

    def test_unknown_type_suffix(self, extractor: FigmaExtractor):
        node = {
            "name": "form_Test",
            "type": "FRAME",
            "children": [
                {"name": "input_Campo_file", "type": "INSTANCE", "children": []},
            ],
        }
        schema = extractor.extract_from_node_data(node)
        assert schema.entities[0].attributes[0].mendix_type == MendixDataType.STRING
        assert any("file" in w for w in schema.figma_metadata.warnings)

    def test_empty_form_warning(self, extractor: FigmaExtractor):
        node = {
            "name": "form_Empty",
            "type": "FRAME",
            "children": [],
        }
        schema = extractor.extract_from_node_data(node)
        assert len(schema.entities[0].attributes) == 0
        assert any("no contiene campos" in w for w in schema.figma_metadata.warnings)


# ─── Tests: No form found ───────────────────────────────────


class TestFigmaNoForm:
    """Tests para casos donde no hay form_* en el árbol."""

    def test_no_form_frame_raises(self, extractor: FigmaExtractor):
        node = {
            "name": "SomeRandomFrame",
            "type": "FRAME",
            "children": [
                {"name": "input_Campo_text", "type": "INSTANCE", "children": []},
            ],
        }
        with pytest.raises(FigmaStructureError, match="form_"):
            extractor.extract_from_node_data(node)

    def test_form_in_nested_level(self, extractor: FigmaExtractor):
        """form_* found inside a wrapper frame should still be extracted."""
        node = {
            "name": "Wrapper",
            "type": "FRAME",
            "children": [
                {
                    "name": "form_Found",
                    "type": "FRAME",
                    "children": [
                        {"name": "input_Campo_text", "type": "INSTANCE", "children": []},
                    ],
                },
            ],
        }
        schema = extractor.extract_from_node_data(node)
        assert len(schema.entities) == 1
        assert schema.entities[0].name == "Found"


# ─── Tests: Page/Microflow generation control ────────────────


class TestFigmaGenerationFlags:
    """Tests para flags generate_pages y generate_microflows."""

    def test_no_pages_when_disabled(self):
        ext = FigmaExtractor(access_token="test", generate_pages=False)
        node = _make_simple_form(fields=[{"name": "C", "type": "text"}])
        schema = ext.extract_from_node_data(node)
        assert len(schema.pages) == 0

    def test_no_microflows_when_disabled(self):
        ext = FigmaExtractor(access_token="test", generate_microflows=False)
        node = _make_simple_form(fields=[{"name": "C", "type": "text"}])
        schema = ext.extract_from_node_data(node)
        assert len(schema.microflows) == 0


# ─── Tests: URL Parsing ─────────────────────────────────────


class TestFigmaURLParsing:
    """Tests para parseo de URLs de Figma."""

    def test_file_url_with_node_id(self):
        url = "https://www.figma.com/file/abc123/MyProject?node-id=456:789"
        file_key, node_id = FigmaExtractor.parse_figma_url(url)
        assert file_key == "abc123"
        assert node_id == "456:789"

    def test_design_url_with_node_id(self):
        url = "https://www.figma.com/design/xyz789/DesignFile?node-id=1-2"
        file_key, node_id = FigmaExtractor.parse_figma_url(url)
        assert file_key == "xyz789"
        assert node_id == "1-2"

    def test_url_with_extra_params(self):
        url = "https://www.figma.com/file/abc/Name?node-id=1:2&t=abc123"
        file_key, node_id = FigmaExtractor.parse_figma_url(url)
        assert file_key == "abc"
        assert node_id == "1:2"

    def test_url_without_node_id_raises(self):
        url = "https://www.figma.com/file/abc123/MyProject"
        with pytest.raises(FigmaExtractorError, match="node-id"):
            FigmaExtractor.parse_figma_url(url)

    def test_non_figma_url_raises(self):
        url = "https://www.google.com/something"
        with pytest.raises(FigmaExtractorError, match="Figma"):
            FigmaExtractor.parse_figma_url(url)

    def test_invalid_path_raises(self):
        url = "https://www.figma.com/unknown/abc?node-id=1:2"
        with pytest.raises(FigmaExtractorError, match="tipo no reconocido"):
            FigmaExtractor.parse_figma_url(url)


# ─── Tests: Type mappings ───────────────────────────────────


class TestFigmaTypeMappings:
    """Tests para mapeos de tipos Figma → Mendix."""

    @pytest.mark.parametrize("figma_type,expected_mendix,expected_widget", [
        ("text", MendixDataType.STRING, WidgetType.TEXT_INPUT),
        ("string", MendixDataType.STRING, WidgetType.TEXT_INPUT),
        ("number", MendixDataType.INTEGER, WidgetType.NUMBER_INPUT),
        ("integer", MendixDataType.INTEGER, WidgetType.NUMBER_INPUT),
        ("int", MendixDataType.INTEGER, WidgetType.NUMBER_INPUT),
        ("decimal", MendixDataType.DECIMAL, WidgetType.NUMBER_INPUT),
        ("float", MendixDataType.DECIMAL, WidgetType.NUMBER_INPUT),
        ("date", MendixDataType.DATETIME, WidgetType.DATE_PICKER),
        ("datetime", MendixDataType.DATETIME, WidgetType.DATE_PICKER),
        ("bool", MendixDataType.BOOLEAN, WidgetType.CHECK_BOX),
        ("boolean", MendixDataType.BOOLEAN, WidgetType.CHECK_BOX),
        ("enum", MendixDataType.ENUMERATION, WidgetType.DROP_DOWN),
        ("textarea", MendixDataType.STRING, WidgetType.TEXT_AREA),
    ])
    def test_type_mapping(
        self,
        extractor: FigmaExtractor,
        figma_type: str,
        expected_mendix: MendixDataType,
        expected_widget: WidgetType,
    ):
        node = _make_simple_form(
            fields=[{"name": "Campo", "type": figma_type}],
        )
        schema = extractor.extract_from_node_data(node)
        attr = schema.entities[0].attributes[0]
        assert attr.mendix_type == expected_mendix
        assert attr.widget_type == expected_widget


# ─── Tests: Schema serialization ────────────────────────────


class TestFigmaSchemaOutput:
    """Tests para la estructura del IntermediateSchema generado."""

    def test_schema_serializable(self, extractor: FigmaExtractor, mock_figma_data: dict):
        schema = extractor.extract_from_node_data(mock_figma_data)
        json_str = schema.model_dump_json()
        assert "OrdenCompra" in json_str
        assert "figma" in json_str

    def test_schema_has_generated_at(self, extractor: FigmaExtractor, mock_figma_data: dict):
        schema = extractor.extract_from_node_data(mock_figma_data)
        assert schema.generated_at is not None
