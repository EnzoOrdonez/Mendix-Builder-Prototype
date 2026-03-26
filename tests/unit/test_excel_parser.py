"""Tests para el parser de Excel (.xlsx) a IntermediateSchema.

Fase 6: Tests unitarios completos.

Nota: Los tests crean archivos .xlsx en memoria usando openpyxl
para no depender de fixtures binarios externos.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

try:
    import openpyxl

    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False

pytestmark = pytest.mark.skipif(
    not HAS_OPENPYXL,
    reason="openpyxl no instalado — pip install openpyxl",
)

from mendex.parsers.excel_parser import (
    DATA_TYPE_MAP,
    ExcelParser,
    ExcelParserError,
    ExcelValidationError,
)
from mendex.schema.intermediate import (
    InputSource,
    MendixDataType,
    MicroflowType,
    PageType,
    ValidationType,
    WidgetType,
)


# ─── Helpers ─────────────────────────────────────────────────


def _create_xlsx(
    tmp_path: Path,
    sheets: dict[str, list[list[Any]]],
    filename: str = "test.xlsx",
) -> Path:
    """Crea un archivo .xlsx con las hojas y filas especificadas."""
    wb = openpyxl.Workbook()
    first = True
    for sheet_name, rows in sheets.items():
        if first:
            ws = wb.active
            ws.title = sheet_name
            first = False
        else:
            ws = wb.create_sheet(sheet_name)
        for row in rows:
            ws.append(row)

    path = tmp_path / filename
    wb.save(path)
    return path


def _simple_sheet(
    extra_rows: list[list[Any]] | None = None,
    headers: list[str] | None = None,
    module: str = "Operaciones",
) -> list[list[Any]]:
    """Crea filas para una hoja simple con headers + datos básicos."""
    h = headers or [
        "NombreCampo", "TipoDato", "Requerido", "Validacion",
        "Etiqueta", "Pagina", "ModuloDestino", "ValoresEnum", "ValorDefault",
    ]
    rows = [h]
    if extra_rows:
        rows.extend(extra_rows)
    else:
        rows.extend([
            ["Nombre", "Texto", "Sí", "max_length:100", "Nombre", "Create", module, "", ""],
            ["Edad", "Entero", "No", "", "Edad", "", module, "", ""],
            ["Activo", "Booleano", "No", "", "Activo", "", module, "", "true"],
        ])
    return rows


# ─── Tests: Parseo básico ───────────────────────────────────


class TestExcelParserBasic:
    """Tests básicos del parser."""

    def test_parse_simple_sheet(self, tmp_path: Path):
        xlsx = _create_xlsx(tmp_path, {"Persona": _simple_sheet()})
        parser = ExcelParser()
        schema = parser.parse(xlsx)

        assert schema.source == InputSource.EXCEL
        assert str(xlsx) in schema.source_file
        assert len(schema.entities) == 1
        assert schema.entities[0].name == "Persona"
        assert schema.entities[0].module == "Operaciones"
        assert len(schema.entities[0].attributes) == 3

    def test_parse_attributes_types(self, tmp_path: Path):
        xlsx = _create_xlsx(tmp_path, {"TestEntity": _simple_sheet()})
        parser = ExcelParser()
        schema = parser.parse(xlsx)

        attrs = {a.name: a for a in schema.entities[0].attributes}
        assert attrs["Nombre"].mendix_type == MendixDataType.STRING
        assert attrs["Edad"].mendix_type == MendixDataType.INTEGER
        assert attrs["Activo"].mendix_type == MendixDataType.BOOLEAN

    def test_parse_required_field(self, tmp_path: Path):
        xlsx = _create_xlsx(tmp_path, {"Test": _simple_sheet()})
        parser = ExcelParser()
        schema = parser.parse(xlsx)
        attrs = {a.name: a for a in schema.entities[0].attributes}
        assert attrs["Nombre"].required is True
        assert attrs["Edad"].required is False

    def test_parse_labels(self, tmp_path: Path):
        xlsx = _create_xlsx(tmp_path, {"Test": _simple_sheet()})
        parser = ExcelParser()
        schema = parser.parse(xlsx)
        attrs = {a.name: a for a in schema.entities[0].attributes}
        assert attrs["Nombre"].label == "Nombre"
        assert attrs["Activo"].label == "Activo"

    def test_label_defaults_to_name(self, tmp_path: Path):
        rows = [
            ["NombreCampo", "TipoDato"],
            ["MiCampo", "Texto"],
        ]
        xlsx = _create_xlsx(tmp_path, {"Test": rows})
        parser = ExcelParser()
        schema = parser.parse(xlsx)
        assert schema.entities[0].attributes[0].label == "MiCampo"

    def test_default_value_parsed(self, tmp_path: Path):
        xlsx = _create_xlsx(tmp_path, {"Test": _simple_sheet()})
        parser = ExcelParser()
        schema = parser.parse(xlsx)
        attrs = {a.name: a for a in schema.entities[0].attributes}
        assert attrs["Activo"].default_value == "true"

    def test_widget_type_inferred(self, tmp_path: Path):
        xlsx = _create_xlsx(tmp_path, {"Test": _simple_sheet()})
        parser = ExcelParser()
        schema = parser.parse(xlsx)
        attrs = {a.name: a for a in schema.entities[0].attributes}
        assert attrs["Nombre"].widget_type == WidgetType.TEXT_INPUT
        assert attrs["Edad"].widget_type == WidgetType.NUMBER_INPUT
        assert attrs["Activo"].widget_type == WidgetType.CHECK_BOX


# ─── Tests: Múltiples hojas ─────────────────────────────────


class TestExcelMultipleSheets:
    """Tests para Excel con múltiples hojas."""

    def test_two_sheets_two_entities(self, tmp_path: Path):
        xlsx = _create_xlsx(tmp_path, {
            "OrdenCompra": _simple_sheet(),
            "LineaDetalle": _simple_sheet(),
        })
        parser = ExcelParser()
        schema = parser.parse(xlsx)
        assert len(schema.entities) == 2
        names = [e.name for e in schema.entities]
        assert "OrdenCompra" in names
        assert "LineaDetalle" in names

    def test_metadata_sheet_ignored(self, tmp_path: Path):
        xlsx = _create_xlsx(tmp_path, {
            "Producto": _simple_sheet(),
            "_Metadata": [["Clave", "Valor"], ["Autor", "Test"]],
        })
        parser = ExcelParser()
        schema = parser.parse(xlsx)
        assert len(schema.entities) == 1
        assert schema.entities[0].name == "Producto"

    def test_hash_prefixed_sheet_ignored(self, tmp_path: Path):
        xlsx = _create_xlsx(tmp_path, {
            "Producto": _simple_sheet(),
            "#Notes": [["Nota"], ["Esto es una nota"]],
        })
        parser = ExcelParser()
        schema = parser.parse(xlsx)
        assert len(schema.entities) == 1


# ─── Tests: Tipos de datos ──────────────────────────────────


class TestExcelDataTypes:
    """Tests para mapeo de tipos de datos."""

    @pytest.mark.parametrize("raw_type,expected", [
        ("Texto", MendixDataType.STRING),
        ("texto", MendixDataType.STRING),
        ("String", MendixDataType.STRING),
        ("Cadena", MendixDataType.STRING),
        ("Entero", MendixDataType.INTEGER),
        ("Integer", MendixDataType.INTEGER),
        ("int", MendixDataType.INTEGER),
        ("Decimal", MendixDataType.DECIMAL),
        ("Float", MendixDataType.DECIMAL),
        ("Numero", MendixDataType.DECIMAL),
        ("Booleano", MendixDataType.BOOLEAN),
        ("Boolean", MendixDataType.BOOLEAN),
        ("bool", MendixDataType.BOOLEAN),
        ("Fecha", MendixDataType.DATETIME),
        ("DateTime", MendixDataType.DATETIME),
        ("FechaHora", MendixDataType.DATETIME),
        ("Enum", MendixDataType.ENUMERATION),
        ("Enumeracion", MendixDataType.ENUMERATION),
        ("AutoNumero", MendixDataType.AUTONUMBER),
        ("AutoNumber", MendixDataType.AUTONUMBER),
        ("Password", MendixDataType.HASHED_STRING),
        ("Hash", MendixDataType.HASHED_STRING),
        ("Long", MendixDataType.LONG),
        ("Largo", MendixDataType.LONG),
    ])
    def test_data_type_mapping(self, tmp_path: Path, raw_type: str, expected: MendixDataType):
        if expected == MendixDataType.ENUMERATION:
            rows = [
                ["NombreCampo", "TipoDato", "ValoresEnum"],
                ["Campo1", raw_type, "A,B,C"],
            ]
        else:
            rows = [
                ["NombreCampo", "TipoDato"],
                ["Campo1", raw_type],
            ]
        xlsx = _create_xlsx(tmp_path, {"Test": rows})
        parser = ExcelParser()
        schema = parser.parse(xlsx)
        if expected == MendixDataType.ENUMERATION:
            # Enum fields become lookup entities, not attributes on the parent
            lookup = next(e for e in schema.entities if e.is_lookup)
            assert lookup.name == "Campo1"
            assert lookup.seed_values == ["A", "B", "C"]
        else:
            assert schema.entities[0].attributes[0].mendix_type == expected

    def test_invalid_data_type_raises(self, tmp_path: Path):
        rows = [
            ["NombreCampo", "TipoDato"],
            ["Campo1", "TipoInvalido"],
        ]
        xlsx = _create_xlsx(tmp_path, {"Test": rows})
        parser = ExcelParser()
        with pytest.raises(ExcelValidationError) as exc_info:
            parser.parse(xlsx)
        assert "TipoInvalido" in str(exc_info.value)


# ─── Tests: Validaciones ────────────────────────────────────


class TestExcelValidations:
    """Tests para parseo de reglas de validación."""

    def test_max_length_validation(self, tmp_path: Path):
        rows = [
            ["NombreCampo", "TipoDato", "Validacion"],
            ["Campo", "Texto", "max_length:100"],
        ]
        xlsx = _create_xlsx(tmp_path, {"Test": rows})
        schema = ExcelParser().parse(xlsx)
        validations = schema.entities[0].attributes[0].validations
        assert any(v.type == ValidationType.MAX_LENGTH for v in validations)
        ml = next(v for v in validations if v.type == ValidationType.MAX_LENGTH)
        assert ml.params["max"] == 100

    def test_min_length_validation(self, tmp_path: Path):
        rows = [
            ["NombreCampo", "TipoDato", "Validacion"],
            ["Campo", "Texto", "min_length:3"],
        ]
        xlsx = _create_xlsx(tmp_path, {"Test": rows})
        schema = ExcelParser().parse(xlsx)
        validations = schema.entities[0].attributes[0].validations
        assert any(v.type == ValidationType.MIN_LENGTH for v in validations)

    def test_range_validation(self, tmp_path: Path):
        rows = [
            ["NombreCampo", "TipoDato", "Validacion"],
            ["Monto", "Decimal", "range:0-9999"],
        ]
        xlsx = _create_xlsx(tmp_path, {"Test": rows})
        schema = ExcelParser().parse(xlsx)
        validations = schema.entities[0].attributes[0].validations
        rv = next(v for v in validations if v.type == ValidationType.RANGE)
        assert rv.params["min"] == 0.0
        assert rv.params["max"] == 9999.0

    def test_regex_validation(self, tmp_path: Path):
        rows = [
            ["NombreCampo", "TipoDato", "Validacion"],
            ["Codigo", "Texto", "regex:^[A-Z]{2}-\\d{4}$"],
        ]
        xlsx = _create_xlsx(tmp_path, {"Test": rows})
        schema = ExcelParser().parse(xlsx)
        validations = schema.entities[0].attributes[0].validations
        rv = next(v for v in validations if v.type == ValidationType.REGEX)
        assert rv.params["pattern"] == "^[A-Z]{2}-\\d{4}$"

    def test_unique_validation(self, tmp_path: Path):
        rows = [
            ["NombreCampo", "TipoDato", "Validacion"],
            ["Email", "Texto", "unique"],
        ]
        xlsx = _create_xlsx(tmp_path, {"Test": rows})
        schema = ExcelParser().parse(xlsx)
        validations = schema.entities[0].attributes[0].validations
        assert any(v.type == ValidationType.UNIQUE for v in validations)

    def test_multiple_validations_semicolon(self, tmp_path: Path):
        rows = [
            ["NombreCampo", "TipoDato", "Validacion"],
            ["Campo", "Texto", "min_length:3;max_length:100;unique"],
        ]
        xlsx = _create_xlsx(tmp_path, {"Test": rows})
        schema = ExcelParser().parse(xlsx)
        validations = schema.entities[0].attributes[0].validations
        types = {v.type for v in validations}
        assert ValidationType.MIN_LENGTH in types
        assert ValidationType.MAX_LENGTH in types
        assert ValidationType.UNIQUE in types

    def test_required_adds_validation(self, tmp_path: Path):
        rows = [
            ["NombreCampo", "TipoDato", "Requerido"],
            ["Campo", "Texto", "Sí"],
        ]
        xlsx = _create_xlsx(tmp_path, {"Test": rows})
        schema = ExcelParser().parse(xlsx)
        validations = schema.entities[0].attributes[0].validations
        assert any(v.type == ValidationType.REQUIRED for v in validations)

    def test_no_validation_column_ok(self, tmp_path: Path):
        rows = [
            ["NombreCampo", "TipoDato"],
            ["Campo", "Texto"],
        ]
        xlsx = _create_xlsx(tmp_path, {"Test": rows})
        schema = ExcelParser().parse(xlsx)
        assert schema.entities[0].attributes[0].validations == []


# ─── Tests: Enumeraciones ───────────────────────────────────


class TestExcelEnumerations:
    """Tests para enumeraciones."""

    def test_enum_with_values(self, tmp_path: Path):
        """Enum fields become lookup entities with seed_values."""
        rows = [
            ["NombreCampo", "TipoDato", "ValoresEnum"],
            ["Estado", "Enum", "Pendiente,Aprobado,Rechazado"],
        ]
        xlsx = _create_xlsx(tmp_path, {"Test": rows})
        schema = ExcelParser().parse(xlsx)
        # Parent entity has no enum attribute (it was extracted)
        parent = next(e for e in schema.entities if not e.is_lookup)
        assert all(a.name != "Estado" for a in parent.attributes)
        # Lookup entity created
        lookup = next(e for e in schema.entities if e.is_lookup)
        assert lookup.name == "Estado"
        assert lookup.seed_values == ["Pendiente", "Aprobado", "Rechazado"]
        assert lookup.attributes[0].name == "Name"
        # Lookup association created
        assoc = next(a for a in schema.associations if a.is_lookup)
        assert assoc.parent_entity == "Estado"
        assert assoc.child_entity == "Test"

    def test_enum_without_values_raises(self, tmp_path: Path):
        rows = [
            ["NombreCampo", "TipoDato", "ValoresEnum"],
            ["Estado", "Enum", ""],
        ]
        xlsx = _create_xlsx(tmp_path, {"Test": rows})
        with pytest.raises(ExcelValidationError) as exc_info:
            ExcelParser().parse(xlsx)
        assert "Enumeration" in str(exc_info.value) or "ValoresEnum" in str(exc_info.value)

    def test_enum_values_trimmed(self, tmp_path: Path):
        rows = [
            ["NombreCampo", "TipoDato", "ValoresEnum"],
            ["Tipo", "Enum", " A , B , C "],
        ]
        xlsx = _create_xlsx(tmp_path, {"Test": rows})
        schema = ExcelParser().parse(xlsx)
        lookup = next(e for e in schema.entities if e.is_lookup)
        assert lookup.seed_values == ["A", "B", "C"]


# ─── Tests: Requerido (truthy values) ───────────────────────


class TestExcelRequired:
    """Tests para parseo de campo requerido."""

    @pytest.mark.parametrize("value,expected", [
        ("Sí", True),
        ("si", True),
        ("SI", True),
        ("Yes", True),
        ("yes", True),
        ("True", True),
        ("true", True),
        ("1", True),
        ("x", True),
        ("X", True),
        ("No", False),
        ("no", False),
        ("False", False),
        ("false", False),
        ("0", False),
        ("", False),
        (None, False),
    ])
    def test_required_parsing(self, tmp_path: Path, value: Any, expected: bool):
        rows = [
            ["NombreCampo", "TipoDato", "Requerido"],
            ["Campo", "Texto", value],
        ]
        xlsx = _create_xlsx(tmp_path, {"Test": rows})
        schema = ExcelParser().parse(xlsx)
        assert schema.entities[0].attributes[0].required is expected

    def test_boolean_true_value(self, tmp_path: Path):
        """openpyxl puede retornar bool nativo."""
        rows = [
            ["NombreCampo", "TipoDato", "Requerido"],
            ["Campo", "Texto", True],
        ]
        xlsx = _create_xlsx(tmp_path, {"Test": rows})
        schema = ExcelParser().parse(xlsx)
        assert schema.entities[0].attributes[0].required is True


# ─── Tests: Páginas generadas ────────────────────────────────


class TestExcelPageGeneration:
    """Tests para generación automática de páginas."""

    def test_default_pages_create_and_overview(self, tmp_path: Path):
        rows = [
            ["NombreCampo", "TipoDato"],
            ["Campo", "Texto"],
        ]
        xlsx = _create_xlsx(tmp_path, {"Producto": rows})
        schema = ExcelParser().parse(xlsx)
        assert len(schema.pages) == 2
        types = {p.page_type for p in schema.pages}
        assert PageType.CREATE in types
        assert PageType.OVERVIEW in types

    def test_explicit_page_types(self, tmp_path: Path):
        rows = [
            ["NombreCampo", "TipoDato", "Pagina"],
            ["Campo1", "Texto", "Create"],
            ["Campo2", "Entero", "Edit"],
        ]
        xlsx = _create_xlsx(tmp_path, {"Producto": rows})
        schema = ExcelParser().parse(xlsx)
        types = {p.page_type for p in schema.pages}
        assert PageType.CREATE in types
        assert PageType.EDIT in types

    def test_page_naming_convention(self, tmp_path: Path):
        rows = [
            ["NombreCampo", "TipoDato"],
            ["Campo", "Texto"],
        ]
        xlsx = _create_xlsx(tmp_path, {"Producto": rows})
        schema = ExcelParser().parse(xlsx)
        names = {p.name for p in schema.pages}
        assert "Producto_Create" in names
        assert "Producto_Overview" in names

    def test_pages_link_to_entity(self, tmp_path: Path):
        rows = [
            ["NombreCampo", "TipoDato"],
            ["Campo", "Texto"],
        ]
        xlsx = _create_xlsx(tmp_path, {"MiEntidad": rows})
        schema = ExcelParser().parse(xlsx)
        for page in schema.pages:
            assert page.entity == "MiEntidad"
            assert page.module == "MyFirstModule"

    def test_page_spanish_types(self, tmp_path: Path):
        rows = [
            ["NombreCampo", "TipoDato", "Pagina"],
            ["Campo1", "Texto", "Crear"],
            ["Campo2", "Entero", "Editar"],
            ["Campo3", "Texto", "Lista"],
        ]
        xlsx = _create_xlsx(tmp_path, {"Test": rows})
        schema = ExcelParser().parse(xlsx)
        types = {p.page_type for p in schema.pages}
        assert PageType.CREATE in types
        assert PageType.EDIT in types
        assert PageType.OVERVIEW in types

    def test_no_pages_when_disabled(self, tmp_path: Path):
        rows = [
            ["NombreCampo", "TipoDato"],
            ["Campo", "Texto"],
        ]
        xlsx = _create_xlsx(tmp_path, {"Test": rows})
        schema = ExcelParser(generate_pages=False).parse(xlsx)
        assert len(schema.pages) == 0


# ─── Tests: Microflows generados ─────────────────────────────


class TestExcelMicroflowGeneration:
    """Tests para generación automática de microflows."""

    def test_default_microflows(self, tmp_path: Path):
        rows = [
            ["NombreCampo", "TipoDato"],
            ["Campo", "Texto"],
        ]
        xlsx = _create_xlsx(tmp_path, {"Producto": rows})
        schema = ExcelParser().parse(xlsx)
        assert len(schema.microflows) == 3
        names = {mf.name for mf in schema.microflows}
        assert "VAL_Producto_Validate" in names
        assert "ACT_Producto_Save" in names
        assert "ACT_Producto_Delete" in names

    def test_microflow_types(self, tmp_path: Path):
        rows = [
            ["NombreCampo", "TipoDato"],
            ["Campo", "Texto"],
        ]
        xlsx = _create_xlsx(tmp_path, {"Test": rows})
        schema = ExcelParser().parse(xlsx)
        types = {mf.microflow_type for mf in schema.microflows}
        assert MicroflowType.VALIDATION in types
        assert MicroflowType.SAVE in types

    def test_microflows_link_to_entity(self, tmp_path: Path):
        rows = [
            ["NombreCampo", "TipoDato"],
            ["Campo", "Texto"],
        ]
        xlsx = _create_xlsx(tmp_path, {"OrdenCompra": rows})
        schema = ExcelParser().parse(xlsx)
        for mf in schema.microflows:
            assert mf.entity == "OrdenCompra"
            assert mf.module == "MyFirstModule"

    def test_no_microflows_when_disabled(self, tmp_path: Path):
        rows = [
            ["NombreCampo", "TipoDato"],
            ["Campo", "Texto"],
        ]
        xlsx = _create_xlsx(tmp_path, {"Test": rows})
        schema = ExcelParser(generate_microflows=False).parse(xlsx)
        assert len(schema.microflows) == 0


# ─── Tests: Módulo destino ──────────────────────────────────


class TestExcelModule:
    """Tests para determinación del módulo destino."""

    def test_module_from_column(self, tmp_path: Path):
        rows = [
            ["NombreCampo", "TipoDato", "ModuloDestino"],
            ["Campo", "Texto", "Operaciones"],
        ]
        xlsx = _create_xlsx(tmp_path, {"Test": rows})
        schema = ExcelParser().parse(xlsx)
        assert schema.entities[0].module == "Operaciones"

    def test_module_default(self, tmp_path: Path):
        rows = [
            ["NombreCampo", "TipoDato"],
            ["Campo", "Texto"],
        ]
        xlsx = _create_xlsx(tmp_path, {"Test": rows})
        schema = ExcelParser().parse(xlsx)
        assert schema.entities[0].module == "MyFirstModule"

    def test_module_custom_default(self, tmp_path: Path):
        rows = [
            ["NombreCampo", "TipoDato"],
            ["Campo", "Texto"],
        ]
        xlsx = _create_xlsx(tmp_path, {"Test": rows})
        schema = ExcelParser(default_module="MiModulo").parse(xlsx)
        assert schema.entities[0].module == "MiModulo"

    def test_module_first_row_wins(self, tmp_path: Path):
        rows = [
            ["NombreCampo", "TipoDato", "ModuloDestino"],
            ["Campo1", "Texto", "Modulo1"],
            ["Campo2", "Texto", "Modulo2"],
        ]
        xlsx = _create_xlsx(tmp_path, {"Test": rows})
        schema = ExcelParser().parse(xlsx)
        assert schema.entities[0].module == "Modulo1"


# ─── Tests: Normalización de nombres ────────────────────────


class TestExcelEntityNaming:
    """Tests para normalización de nombres de entidad."""

    def test_pascal_case_preserved(self, tmp_path: Path):
        rows = [["NombreCampo", "TipoDato"], ["Campo", "Texto"]]
        xlsx = _create_xlsx(tmp_path, {"OrdenCompra": rows})
        schema = ExcelParser().parse(xlsx)
        assert schema.entities[0].name == "OrdenCompra"

    def test_snake_case_converted(self, tmp_path: Path):
        rows = [["NombreCampo", "TipoDato"], ["Campo", "Texto"]]
        xlsx = _create_xlsx(tmp_path, {"orden_compra": rows})
        schema = ExcelParser().parse(xlsx)
        assert schema.entities[0].name == "OrdenCompra"

    def test_spaces_converted(self, tmp_path: Path):
        rows = [["NombreCampo", "TipoDato"], ["Campo", "Texto"]]
        xlsx = _create_xlsx(tmp_path, {"orden compra": rows})
        schema = ExcelParser().parse(xlsx)
        assert schema.entities[0].name == "OrdenCompra"

    def test_single_word_capitalized(self, tmp_path: Path):
        rows = [["NombreCampo", "TipoDato"], ["Campo", "Texto"]]
        xlsx = _create_xlsx(tmp_path, {"producto": rows})
        schema = ExcelParser().parse(xlsx)
        assert schema.entities[0].name == "Producto"


# ─── Tests: Columnas flexibles ──────────────────────────────


class TestExcelFlexibleColumns:
    """Tests para flexibilidad en nombres de columnas."""

    def test_columns_case_insensitive(self, tmp_path: Path):
        rows = [
            ["nombrecampo", "tipodato"],
            ["Campo", "Texto"],
        ]
        xlsx = _create_xlsx(tmp_path, {"Test": rows})
        schema = ExcelParser().parse(xlsx)
        assert len(schema.entities[0].attributes) == 1

    def test_columns_with_spaces(self, tmp_path: Path):
        rows = [
            ["Nombre Campo", "Tipo Dato"],
            ["Campo", "Texto"],
        ]
        xlsx = _create_xlsx(tmp_path, {"Test": rows})
        schema = ExcelParser().parse(xlsx)
        assert len(schema.entities[0].attributes) == 1

    def test_columns_with_underscores(self, tmp_path: Path):
        rows = [
            ["Nombre_Campo", "Tipo_Dato"],
            ["Campo", "Texto"],
        ]
        xlsx = _create_xlsx(tmp_path, {"Test": rows})
        schema = ExcelParser().parse(xlsx)
        assert len(schema.entities[0].attributes) == 1


# ─── Tests: Errores y validación ─────────────────────────────


class TestExcelErrors:
    """Tests para manejo de errores."""

    def test_file_not_found(self, tmp_path: Path):
        parser = ExcelParser()
        with pytest.raises(ExcelParserError, match="no encontrado"):
            parser.parse(tmp_path / "nonexistent.xlsx")

    def test_wrong_extension(self, tmp_path: Path):
        csv_file = tmp_path / "data.csv"
        csv_file.write_text("a,b\n1,2")
        parser = ExcelParser()
        with pytest.raises(ExcelParserError, match="Formato no soportado"):
            parser.parse(csv_file)

    def test_missing_required_columns(self, tmp_path: Path):
        rows = [
            ["Columna1", "Columna2"],
            ["Dato1", "Dato2"],
        ]
        xlsx = _create_xlsx(tmp_path, {"Test": rows})
        parser = ExcelParser()
        with pytest.raises(ExcelValidationError) as exc_info:
            parser.parse(xlsx)
        assert "NombreCampo" in str(exc_info.value) or "TipoDato" in str(exc_info.value)

    def test_empty_sheet_no_data_rows(self, tmp_path: Path):
        rows = [
            ["NombreCampo", "TipoDato"],
            # No data rows
        ]
        xlsx = _create_xlsx(tmp_path, {"Test": rows})
        parser = ExcelParser()
        with pytest.raises(ExcelParserError, match="Sin filas"):
            parser.parse(xlsx)

    def test_duplicate_field_names(self, tmp_path: Path):
        rows = [
            ["NombreCampo", "TipoDato"],
            ["Campo1", "Texto"],
            ["Campo1", "Entero"],
        ]
        xlsx = _create_xlsx(tmp_path, {"Test": rows})
        parser = ExcelParser()
        with pytest.raises(ExcelValidationError, match="duplicado"):
            parser.parse(xlsx)

    def test_invalid_field_name_characters(self, tmp_path: Path):
        rows = [
            ["NombreCampo", "TipoDato"],
            ["Campo Con Espacios", "Texto"],
        ]
        xlsx = _create_xlsx(tmp_path, {"Test": rows})
        parser = ExcelParser()
        with pytest.raises(ExcelValidationError, match="caracteres no válidos"):
            parser.parse(xlsx)

    def test_empty_tipo_dato(self, tmp_path: Path):
        rows = [
            ["NombreCampo", "TipoDato"],
            ["Campo1", ""],
        ]
        xlsx = _create_xlsx(tmp_path, {"Test": rows})
        parser = ExcelParser()
        with pytest.raises(ExcelValidationError, match="TipoDato vacío"):
            parser.parse(xlsx)

    def test_all_sheets_invalid(self, tmp_path: Path):
        """Si todas las hojas dan error, se acumulan."""
        xlsx = _create_xlsx(tmp_path, {
            "Hoja1": [["NombreCampo", "TipoDato"], ["Campo1", "InvalidType"]],
            "Hoja2": [["NombreCampo", "TipoDato"], ["Campo1", "OtroInvalido"]],
        })
        parser = ExcelParser()
        with pytest.raises(ExcelValidationError) as exc_info:
            parser.parse(xlsx)
        # Errors from both sheets
        assert "[Hoja1]" in str(exc_info.value)
        assert "[Hoja2]" in str(exc_info.value)

    def test_empty_rows_skipped(self, tmp_path: Path):
        rows = [
            ["NombreCampo", "TipoDato"],
            ["Campo1", "Texto"],
            [None, None],  # Empty row
            ["Campo2", "Entero"],
        ]
        xlsx = _create_xlsx(tmp_path, {"Test": rows})
        schema = ExcelParser().parse(xlsx)
        assert len(schema.entities[0].attributes) == 2

    def test_only_metadata_sheets_raises(self, tmp_path: Path):
        xlsx = _create_xlsx(tmp_path, {
            "_Config": [["Key", "Value"]],
        })
        parser = ExcelParser()
        with pytest.raises(ExcelParserError, match="No se encontraron entidades"):
            parser.parse(xlsx)


# ─── Tests: Schema output completo ──────────────────────────


class TestExcelFullSchema:
    """Tests para la estructura completa del IntermediateSchema."""

    def test_full_schema_structure(self, tmp_path: Path):
        xlsx = _create_xlsx(tmp_path, {
            "OrdenCompra": _simple_sheet(module="Operaciones"),
        })
        parser = ExcelParser()
        schema = parser.parse(xlsx)

        # Root
        assert schema.source == InputSource.EXCEL
        assert schema.generated_at is not None

        # Entity
        entity = schema.entities[0]
        assert entity.name == "OrdenCompra"
        assert entity.module == "Operaciones"
        assert entity.is_persistable is True
        assert len(entity.attributes) == 3

        # Pages
        assert len(schema.pages) >= 1
        for page in schema.pages:
            assert page.entity == "OrdenCompra"
            assert page.module == "Operaciones"

        # Microflows (VAL_Validate + ACT_Save + ACT_Delete)
        assert len(schema.microflows) == 3
        for mf in schema.microflows:
            assert mf.entity == "OrdenCompra"
            assert mf.module == "Operaciones"

    def test_schema_serializable(self, tmp_path: Path):
        """El schema debe ser serializable a JSON."""
        xlsx = _create_xlsx(tmp_path, {"Test": _simple_sheet()})
        schema = ExcelParser().parse(xlsx)
        json_str = schema.model_dump_json()
        assert "Test" in json_str
        assert "Nombre" in json_str
