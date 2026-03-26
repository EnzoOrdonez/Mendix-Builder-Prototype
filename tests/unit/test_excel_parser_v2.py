"""Tests para las nuevas funcionalidades del parser Excel v2.

Fase G: Tests para columnas nuevas, hojas especiales, validaciones naturales,
tipos de dato nuevos y retrocompatibilidad.
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

from mendex.parsers.excel_parser import ExcelParser, ExcelValidationError
from mendex.schema.intermediate import (
    AssociationType,
    FieldVisibility,
    InputSource,
    IntermediateSchema,
    MendixDataType,
    MicroflowType,
    PageSchema,
    PageType,
    ValidationType,
    WidgetType,
)


# ─── Helpers ─────────────────────────────────────────────────


def _create_xlsx(
    tmp_path: Path,
    sheets: dict[str, list[list[Any]]],
    filename: str = "test_v2.xlsx",
) -> Path:
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


HEADERS_V2 = [
    "NombreCampo", "TipoDato", "Requerido", "Validacion",
    "Etiqueta", "Pagina", "ModuloDestino", "ValoresEnum", "ValorDefault",
    "Seccion", "Widget", "VisibleEn", "Calculado", "OrdenSeccion", "VisibleSi",
]


# ─── Tests: Nuevas columnas ─────────────────────────────────


class TestSeccionColumn:
    def test_section_parsed(self, tmp_path: Path):
        rows = [
            HEADERS_V2,
            ["Nombre", "Texto", "Si", "", "Nombre", "Create", "Mod", "", "", "Generalidades", "", "", "", "1"],
            ["Edad", "Entero", "", "", "Edad", "Create", "Mod", "", "", "Generalidades", "", "", "", "1"],
            ["Email", "Texto", "", "", "Email", "Create", "Mod", "", "", "Contacto", "", "", "", "2"],
        ]
        xlsx = _create_xlsx(tmp_path, {"Persona": rows})
        schema = ExcelParser().parse(xlsx)

        attrs = {a.name: a for a in schema.entities[0].attributes}
        assert attrs["Nombre"].section == "Generalidades"
        assert attrs["Edad"].section == "Generalidades"
        assert attrs["Email"].section == "Contacto"

    def test_sections_in_pages(self, tmp_path: Path):
        rows = [
            HEADERS_V2,
            ["Nombre", "Texto", "Si", "", "Nombre", "Create", "Mod", "", "", "General", "", "", "", ""],
            ["Edad", "Entero", "", "", "Edad", "Create", "Mod", "", "", "General", "", "", "", ""],
            ["Email", "Texto", "", "", "Email", "Create", "Mod", "", "", "Contacto", "", "", "", ""],
        ]
        xlsx = _create_xlsx(tmp_path, {"Persona": rows})
        schema = ExcelParser().parse(xlsx)

        create_page = next(p for p in schema.pages if p.page_type == PageType.CREATE)
        assert len(create_page.sections) == 2
        sec_names = [s.name for s in create_page.sections]
        assert "General" in sec_names
        assert "Contacto" in sec_names

    def test_no_section_means_empty_sections(self, tmp_path: Path):
        rows = [
            ["NombreCampo", "TipoDato"],
            ["Nombre", "Texto"],
        ]
        xlsx = _create_xlsx(tmp_path, {"Test": rows})
        schema = ExcelParser().parse(xlsx)
        for page in schema.pages:
            assert page.sections == []


class TestWidgetColumn:
    def test_explicit_widget_override(self, tmp_path: Path):
        rows = [
            HEADERS_V2,
            ["Descripcion", "Texto", "", "", "Descripcion", "Create", "Mod", "", "", "", "TextArea", "", "", ""],
        ]
        xlsx = _create_xlsx(tmp_path, {"Test": rows})
        schema = ExcelParser().parse(xlsx)
        assert schema.entities[0].attributes[0].widget_type == WidgetType.TEXT_AREA

    def test_radio_buttons_widget(self, tmp_path: Path):
        rows = [
            HEADERS_V2,
            ["Prioridad", "Texto", "", "", "Prioridad", "", "Mod", "", "", "", "RadioButtons", "", "", ""],
        ]
        xlsx = _create_xlsx(tmp_path, {"Test": rows})
        schema = ExcelParser().parse(xlsx)
        assert schema.entities[0].attributes[0].widget_type == WidgetType.RADIO_BUTTONS


class TestVisibleEnColumn:
    def test_visibility_parsed(self, tmp_path: Path):
        rows = [
            HEADERS_V2,
            ["Codigo", "AutoNumero", "", "", "Codigo", "Create", "Mod", "", "", "", "", "SoloOverview", "", ""],
            ["Nombre", "Texto", "Si", "", "Nombre", "Create", "Mod", "", "", "", "", "Todos", "", ""],
            ["Criterio1", "Entero", "", "", "Criterio1", "Create", "Mod", "", "", "", "", "SoloEditar", "", ""],
        ]
        xlsx = _create_xlsx(tmp_path, {"Test": rows})
        schema = ExcelParser().parse(xlsx)
        attrs = {a.name: a for a in schema.entities[0].attributes}
        assert attrs["Codigo"].visibility == FieldVisibility.OVERVIEW_ONLY
        assert attrs["Nombre"].visibility == FieldVisibility.ALL
        assert attrs["Criterio1"].visibility == FieldVisibility.EDIT_ONLY

    def test_section_filtering_by_visibility(self, tmp_path: Path):
        rows = [
            HEADERS_V2,
            ["Nombre", "Texto", "Si", "", "Nombre", "Create", "Mod", "", "", "Gen", "", "Todos", "", ""],
            ["Criterio1", "Entero", "", "", "C1", "Edit", "Mod", "", "", "Eval", "", "SoloEditar", "", ""],
        ]
        xlsx = _create_xlsx(tmp_path, {"Test": rows})
        schema = ExcelParser().parse(xlsx)

        create_page = next(
            (p for p in schema.pages if p.page_type == PageType.CREATE), None
        )
        if create_page and create_page.sections:
            sec_names = [s.name for s in create_page.sections]
            # "Eval" section's Criterio1 is SoloEditar, so not visible in Create
            assert "Eval" not in sec_names


class TestCalculadoColumn:
    def test_calculated_field_parsed(self, tmp_path: Path):
        rows = [
            ["NombreCampo", "TipoDato", "Calculado"],
            ["Total", "Entero", "Criterio1+Criterio2+Criterio3"],
        ]
        xlsx = _create_xlsx(tmp_path, {"Test": rows})
        schema = ExcelParser().parse(xlsx)
        attr = schema.entities[0].attributes[0]
        assert attr.is_calculated is True
        assert attr.calculation_expression == "Criterio1+Criterio2+Criterio3"

    def test_non_calculated_field(self, tmp_path: Path):
        rows = [
            ["NombreCampo", "TipoDato"],
            ["Nombre", "Texto"],
        ]
        xlsx = _create_xlsx(tmp_path, {"Test": rows})
        schema = ExcelParser().parse(xlsx)
        attr = schema.entities[0].attributes[0]
        assert attr.is_calculated is False
        assert attr.calculation_expression is None


# ─── Tests: Nuevos tipos de dato ────────────────────────────


class TestNewDataTypes:
    def test_archivo_type(self, tmp_path: Path):
        rows = [
            ["NombreCampo", "TipoDato"],
            ["Adjunto", "Archivo"],
        ]
        xlsx = _create_xlsx(tmp_path, {"Test": rows})
        schema = ExcelParser().parse(xlsx)
        attr = schema.entities[0].attributes[0]
        assert attr.mendix_type == MendixDataType.BINARY
        assert attr.widget_type == WidgetType.FILE_UPLOAD

    def test_imagen_type(self, tmp_path: Path):
        rows = [
            ["NombreCampo", "TipoDato"],
            ["Foto", "Imagen"],
        ]
        xlsx = _create_xlsx(tmp_path, {"Test": rows})
        schema = ExcelParser().parse(xlsx)
        attr = schema.entities[0].attributes[0]
        assert attr.mendix_type == MendixDataType.BINARY
        assert attr.widget_type == WidgetType.IMAGE_UPLOAD

    def test_textogrande_type(self, tmp_path: Path):
        rows = [
            ["NombreCampo", "TipoDato"],
            ["Observaciones", "TextoGrande"],
        ]
        xlsx = _create_xlsx(tmp_path, {"Test": rows})
        schema = ExcelParser().parse(xlsx)
        attr = schema.entities[0].attributes[0]
        assert attr.mendix_type == MendixDataType.STRING
        assert attr.widget_type == WidgetType.TEXT_AREA

    def test_richtext_type(self, tmp_path: Path):
        rows = [
            ["NombreCampo", "TipoDato"],
            ["Contenido", "RichText"],
        ]
        xlsx = _create_xlsx(tmp_path, {"Test": rows})
        schema = ExcelParser().parse(xlsx)
        attr = schema.entities[0].attributes[0]
        assert attr.mendix_type == MendixDataType.STRING
        assert attr.widget_type == WidgetType.RICH_TEXT

    def test_generalization_detected_for_file(self, tmp_path: Path):
        rows = [
            ["NombreCampo", "TipoDato"],
            ["Nombre", "Texto"],
            ["Adjunto", "Archivo"],
        ]
        xlsx = _create_xlsx(tmp_path, {"DocEntity": rows})
        schema = ExcelParser().parse(xlsx)
        assert schema.entities[0].generalization == "System.FileDocument"

    def test_generalization_detected_for_image(self, tmp_path: Path):
        rows = [
            ["NombreCampo", "TipoDato"],
            ["Foto", "Imagen"],
        ]
        xlsx = _create_xlsx(tmp_path, {"FotoEntity": rows})
        schema = ExcelParser().parse(xlsx)
        assert schema.entities[0].generalization == "System.Image"

    def test_no_generalization_for_normal_entity(self, tmp_path: Path):
        rows = [
            ["NombreCampo", "TipoDato"],
            ["Nombre", "Texto"],
        ]
        xlsx = _create_xlsx(tmp_path, {"Test": rows})
        schema = ExcelParser().parse(xlsx)
        assert schema.entities[0].generalization is None


# ─── Tests: Validaciones en lenguaje natural ─────────────────


class TestNaturalValidations:
    def test_maximo_caracteres(self, tmp_path: Path):
        rows = [
            ["NombreCampo", "TipoDato", "Validacion"],
            ["Lugar", "Texto", "maximo 200 caracteres"],
        ]
        xlsx = _create_xlsx(tmp_path, {"Test": rows})
        schema = ExcelParser().parse(xlsx)
        vals = schema.entities[0].attributes[0].validations
        max_val = next(v for v in vals if v.type == ValidationType.MAX_LENGTH)
        assert max_val.params["max"] == 200

    def test_minimo_caracteres(self, tmp_path: Path):
        rows = [
            ["NombreCampo", "TipoDato", "Validacion"],
            ["Codigo", "Texto", "minimo 3 caracteres"],
        ]
        xlsx = _create_xlsx(tmp_path, {"Test": rows})
        schema = ExcelParser().parse(xlsx)
        vals = schema.entities[0].attributes[0].validations
        min_val = next(v for v in vals if v.type == ValidationType.MIN_LENGTH)
        assert min_val.params["min"] == 3

    def test_entre_n_y_m(self, tmp_path: Path):
        rows = [
            ["NombreCampo", "TipoDato", "Validacion"],
            ["Puntaje", "Entero", "entre 0 y 100"],
        ]
        xlsx = _create_xlsx(tmp_path, {"Test": rows})
        schema = ExcelParser().parse(xlsx)
        vals = schema.entities[0].attributes[0].validations
        range_val = next(v for v in vals if v.type == ValidationType.RANGE)
        assert range_val.params["min"] == 0.0
        assert range_val.params["max"] == 100.0

    def test_unico(self, tmp_path: Path):
        rows = [
            ["NombreCampo", "TipoDato", "Validacion"],
            ["DNI", "Texto", "unico"],
        ]
        xlsx = _create_xlsx(tmp_path, {"Test": rows})
        schema = ExcelParser().parse(xlsx)
        vals = schema.entities[0].attributes[0].validations
        assert any(v.type == ValidationType.UNIQUE for v in vals)

    def test_email_validation(self, tmp_path: Path):
        rows = [
            ["NombreCampo", "TipoDato", "Validacion"],
            ["Correo", "Texto", "email"],
        ]
        xlsx = _create_xlsx(tmp_path, {"Test": rows})
        schema = ExcelParser().parse(xlsx)
        vals = schema.entities[0].attributes[0].validations
        regex_val = next(v for v in vals if v.type == ValidationType.REGEX)
        assert "@" in regex_val.params["pattern"]

    def test_telefono_validation(self, tmp_path: Path):
        rows = [
            ["NombreCampo", "TipoDato", "Validacion"],
            ["Tel", "Texto", "telefono"],
        ]
        xlsx = _create_xlsx(tmp_path, {"Test": rows})
        schema = ExcelParser().parse(xlsx)
        vals = schema.entities[0].attributes[0].validations
        regex_val = next(v for v in vals if v.type == ValidationType.REGEX)
        assert "pattern" in regex_val.params

    def test_technical_syntax_still_works(self, tmp_path: Path):
        rows = [
            ["NombreCampo", "TipoDato", "Validacion"],
            ["Codigo", "Texto", "max_length:50"],
        ]
        xlsx = _create_xlsx(tmp_path, {"Test": rows})
        schema = ExcelParser().parse(xlsx)
        vals = schema.entities[0].attributes[0].validations
        max_val = next(v for v in vals if v.type == ValidationType.MAX_LENGTH)
        assert max_val.params["max"] == 50


# ─── Tests: Hoja _Config ────────────────────────────────────


class TestConfigSheet:
    def test_config_parsed(self, tmp_path: Path):
        sheets = {
            "_Config": [
                ["ModuloDestino", "SSO_Seguridad"],
                ["PrefijoEntidad", "SSO_"],
                ["Layout", "Atlas_Default"],
            ],
            "Simulacro": [
                ["NombreCampo", "TipoDato"],
                ["Codigo", "Texto"],
            ],
        }
        xlsx = _create_xlsx(tmp_path, sheets)
        schema = ExcelParser().parse(xlsx)
        assert schema.config.get("modulodestino") == "SSO_Seguridad"
        assert schema.config.get("prefijoentidad") == "SSO_"

    def test_config_applies_module(self, tmp_path: Path):
        sheets = {
            "_Config": [
                ["ModuloDestino", "MiModulo"],
            ],
            "Test": [
                ["NombreCampo", "TipoDato"],
                ["Nombre", "Texto"],
            ],
        }
        xlsx = _create_xlsx(tmp_path, sheets)
        schema = ExcelParser().parse(xlsx)
        assert schema.entities[0].module == "MiModulo"

    def test_config_applies_entity_prefix(self, tmp_path: Path):
        sheets = {
            "_Config": [
                ["PrefijoEntidad", "SSO_"],
            ],
            "Simulacro": [
                ["NombreCampo", "TipoDato"],
                ["Nombre", "Texto"],
            ],
        }
        xlsx = _create_xlsx(tmp_path, sheets)
        schema = ExcelParser().parse(xlsx)
        assert schema.entities[0].name == "SSO_Simulacro"

    def test_config_applies_attribute_prefix(self, tmp_path: Path):
        sheets = {
            "_Config": [
                ["PrefijoAtributo", "SSO_"],
            ],
            "Test": [
                ["NombreCampo", "TipoDato"],
                ["Nombre", "Texto"],
            ],
        }
        xlsx = _create_xlsx(tmp_path, sheets)
        schema = ExcelParser().parse(xlsx)
        assert schema.entities[0].attributes[0].name == "SSO_Nombre"


# ─── Tests: Hoja _Relaciones ────────────────────────────────


class TestRelacionesSheet:
    def test_associations_parsed(self, tmp_path: Path):
        sheets = {
            "Simulacro": [
                ["NombreCampo", "TipoDato"],
                ["Codigo", "Texto"],
            ],
            "Participante": [
                ["NombreCampo", "TipoDato"],
                ["Nombre", "Texto"],
            ],
            "_Relaciones": [
                ["EntidadOrigen", "EntidadDestino", "Tipo", "NombreAsociacion", "CascadeDelete"],
                ["Simulacro", "Participante", "1-*", "Simulacro_Participantes", "Si"],
            ],
        }
        xlsx = _create_xlsx(tmp_path, sheets)
        schema = ExcelParser().parse(xlsx)

        assert len(schema.associations) == 1
        assoc = schema.associations[0]
        assert assoc.parent_entity == "Simulacro"
        assert assoc.child_entity == "Participante"
        assert assoc.association_type == AssociationType.ONE_TO_MANY
        assert assoc.name == "Simulacro_Participantes"
        assert assoc.cascade_delete is True

    def test_default_association_name(self, tmp_path: Path):
        sheets = {
            "Padre": [
                ["NombreCampo", "TipoDato"],
                ["Nombre", "Texto"],
            ],
            "Hijo": [
                ["NombreCampo", "TipoDato"],
                ["Nombre", "Texto"],
            ],
            "_Relaciones": [
                ["EntidadOrigen", "EntidadDestino", "Tipo"],
                ["Padre", "Hijo", "1-*"],
            ],
        }
        xlsx = _create_xlsx(tmp_path, sheets)
        schema = ExcelParser().parse(xlsx)
        assert schema.associations[0].name == "Padre_Hijo"

    def test_many_to_many_association(self, tmp_path: Path):
        sheets = {
            "Student": [
                ["NombreCampo", "TipoDato"],
                ["Name", "Texto"],
            ],
            "Course": [
                ["NombreCampo", "TipoDato"],
                ["Title", "Texto"],
            ],
            "_Relaciones": [
                ["EntidadOrigen", "EntidadDestino", "Tipo"],
                ["Student", "Course", "*-*"],
            ],
        }
        xlsx = _create_xlsx(tmp_path, sheets)
        schema = ExcelParser().parse(xlsx)
        assert schema.associations[0].association_type == AssociationType.MANY_TO_MANY

    def test_invalid_entity_reference_raises(self, tmp_path: Path):
        sheets = {
            "Simulacro": [
                ["NombreCampo", "TipoDato"],
                ["Codigo", "Texto"],
            ],
            "_Relaciones": [
                ["EntidadOrigen", "EntidadDestino", "Tipo"],
                ["Simulacro", "NoExiste", "1-*"],
            ],
        }
        xlsx = _create_xlsx(tmp_path, sheets)
        with pytest.raises(ExcelValidationError, match="NoExiste"):
            ExcelParser().parse(xlsx)

    def test_invalid_association_type_raises(self, tmp_path: Path):
        sheets = {
            "A": [
                ["NombreCampo", "TipoDato"],
                ["X", "Texto"],
            ],
            "B": [
                ["NombreCampo", "TipoDato"],
                ["Y", "Texto"],
            ],
            "_Relaciones": [
                ["EntidadOrigen", "EntidadDestino", "Tipo"],
                ["A", "B", "invalid"],
            ],
        }
        xlsx = _create_xlsx(tmp_path, sheets)
        with pytest.raises(ExcelValidationError, match="no reconocido"):
            ExcelParser().parse(xlsx)


# ─── Tests: Hoja _Seguridad ─────────────────────────────────


class TestSeguridadSheet:
    def test_security_rules_applied(self, tmp_path: Path):
        sheets = {
            "Documento": [
                ["NombreCampo", "TipoDato"],
                ["Titulo", "Texto"],
            ],
            "_Seguridad": [
                ["Entidad", "Rol", "Crear", "Leer", "Escribir", "Eliminar"],
                ["Documento", "Administrator", "Si", "Si", "Si", "Si"],
                ["Documento", "User", "Si", "Si", "No", "No"],
            ],
        }
        xlsx = _create_xlsx(tmp_path, sheets)
        schema = ExcelParser().parse(xlsx)

        rules = schema.entities[0].access_rules
        assert len(rules) == 2
        admin_rule = next(r for r in rules if r.role == "Administrator")
        assert admin_rule.can_create is True
        assert admin_rule.can_delete is True
        user_rule = next(r for r in rules if r.role == "User")
        assert user_rule.can_create is True
        assert user_rule.can_delete is False

    def test_wildcard_security(self, tmp_path: Path):
        sheets = {
            "EntityA": [
                ["NombreCampo", "TipoDato"],
                ["Name", "Texto"],
            ],
            "EntityB": [
                ["NombreCampo", "TipoDato"],
                ["Code", "Texto"],
            ],
            "_Seguridad": [
                ["Entidad", "Rol", "Crear", "Leer", "Escribir", "Eliminar"],
                ["*", "Admin", "Si", "Si", "Si", "Si"],
            ],
        }
        xlsx = _create_xlsx(tmp_path, sheets)
        schema = ExcelParser().parse(xlsx)
        # Both entities should have the wildcard rule
        for entity in schema.entities:
            assert len(entity.access_rules) >= 1
            assert any(r.role == "Admin" for r in entity.access_rules)


# ─── Tests: Retrocompatibilidad ──────────────────────────────


class TestRetrocompatibility:
    def test_old_format_still_works(self, tmp_path: Path):
        """Excel sin columnas nuevas sigue parseando correctamente."""
        rows = [
            ["NombreCampo", "TipoDato", "Requerido", "Validacion",
             "Etiqueta", "Pagina", "ModuloDestino", "ValoresEnum", "ValorDefault"],
            ["Nombre", "Texto", "Sí", "max_length:100", "Nombre", "Create", "Ops", "", ""],
            ["Edad", "Entero", "No", "", "Edad", "", "Ops", "", ""],
            ["Estado", "Enum", "Si", "", "Estado", "", "Ops", "Activo,Inactivo", ""],
        ]
        xlsx = _create_xlsx(tmp_path, {"Persona": rows})
        schema = ExcelParser().parse(xlsx)

        # 3 entities: Persona (main) + Estado (lookup) + Filtros (filter)
        assert len(schema.entities) == 3
        persona = next(e for e in schema.entities if e.name == "Persona")
        assert len(persona.attributes) == 2  # Nombre, Edad (Estado extracted)
        assert schema.config == {}

        # Verify attributes are correct (Estado is now a lookup, not an attribute)
        attrs = {a.name: a for a in persona.attributes}
        assert attrs["Nombre"].mendix_type == MendixDataType.STRING
        assert attrs["Nombre"].required is True
        assert attrs["Edad"].mendix_type == MendixDataType.INTEGER

        # Estado became a lookup entity
        lookup = next(e for e in schema.entities if e.is_lookup)
        assert lookup.name == "Estado"
        assert lookup.seed_values == ["Activo", "Inactivo"]

        # Lookup association created
        lookup_assocs = [a for a in schema.associations if a.is_lookup]
        assert len(lookup_assocs) == 1
        assert lookup_assocs[0].parent_entity == "Estado"
        assert lookup_assocs[0].child_entity == "Persona"

        # Verify pages are still generated
        assert len(schema.pages) >= 1

        # Verify no sections (none defined)
        for page in schema.pages:
            assert page.sections == []

    def test_old_format_default_visibility(self, tmp_path: Path):
        rows = [
            ["NombreCampo", "TipoDato"],
            ["Nombre", "Texto"],
        ]
        xlsx = _create_xlsx(tmp_path, {"Test": rows})
        schema = ExcelParser().parse(xlsx)
        assert schema.entities[0].attributes[0].visibility == FieldVisibility.ALL

    def test_old_format_no_generalization(self, tmp_path: Path):
        rows = [
            ["NombreCampo", "TipoDato"],
            ["Nombre", "Texto"],
        ]
        xlsx = _create_xlsx(tmp_path, {"Test": rows})
        schema = ExcelParser().parse(xlsx)
        assert schema.entities[0].generalization is None


# ─── Tests: Generadores con nuevas features ──────────────────


class TestPageGeneratorVisibility:
    def test_visibility_filtering_in_widgets(self):
        from mendex.bridge.sdk_client import MockSDKClient
        from mendex.generators.pages import PageGenerator
        from mendex.schema.intermediate import (
            AttributeSchema,
            EntitySchema,
            IntermediateSchema,
            PageSchema,
        )

        entity = EntitySchema(
            name="Test",
            module="Mod",
            attributes=[
                AttributeSchema(
                    name="Nombre", mendix_type=MendixDataType.STRING,
                    label="Nombre", visibility=FieldVisibility.ALL,
                ),
                AttributeSchema(
                    name="Score", mendix_type=MendixDataType.INTEGER,
                    label="Score", visibility=FieldVisibility.EDIT_ONLY,
                ),
                AttributeSchema(
                    name="Codigo", mendix_type=MendixDataType.AUTONUMBER,
                    label="Codigo", visibility=FieldVisibility.OVERVIEW_ONLY,
                ),
            ],
        )
        schema = IntermediateSchema(
            source=InputSource.EXCEL,
            entities=[entity],
            pages=[
                PageSchema(
                    name="Test_Create", page_type=PageType.CREATE,
                    entity="Test", module="Mod",
                ),
            ],
        )

        sdk = MockSDKClient()
        gen = PageGenerator(sdk_client=sdk)
        result = gen.generate(schema, Path("test.mpr"))

        assert result.total_created == 1
        # Check the actual page data sent to SDK
        page_data = sdk.created_pages[0]
        widget_attrs = [w["attribute"] for w in page_data["widgets"]]
        assert "Nombre" in widget_attrs
        # Score is EDIT_ONLY, should NOT appear in Create page
        assert "Score" not in widget_attrs
        # Codigo is OVERVIEW_ONLY, should NOT appear in Create page
        assert "Codigo" not in widget_attrs

    def test_new_widget_types_mapped(self):
        from mendex.generators.pages import PageGenerator

        assert PageGenerator._map_schema_widget(WidgetType.FILE_UPLOAD) == "FileManager"
        assert PageGenerator._map_schema_widget(WidgetType.IMAGE_UPLOAD) == "ImageUploader"
        assert PageGenerator._map_schema_widget(WidgetType.RICH_TEXT) == "RichTextEditor"


class TestDomainModelGeneratorAssociations:
    def test_generalization_included_in_entity_data(self):
        from mendex.bridge.sdk_client import MockSDKClient
        from mendex.generators.domain_model import DomainModelGenerator
        from mendex.schema.intermediate import EntitySchema, IntermediateSchema

        entity = EntitySchema(
            name="Foto",
            module="Mod",
            attributes=[],
            generalization="System.Image",
        )
        schema = IntermediateSchema(
            source=InputSource.EXCEL,
            entities=[entity],
        )

        sdk = MockSDKClient()
        gen = DomainModelGenerator(sdk_client=sdk)
        result = gen.generate(schema, Path("test.mpr"))

        assert result.total_created == 1
        data = sdk.created_entities[0]
        assert data["generalization"] == "System.Image"

    def test_associations_created(self):
        from mendex.bridge.sdk_client import MockSDKClient
        from mendex.generators.domain_model import DomainModelGenerator
        from mendex.schema.intermediate import (
            AssociationSchema,
            EntitySchema,
            IntermediateSchema,
        )

        schema = IntermediateSchema(
            source=InputSource.EXCEL,
            entities=[
                EntitySchema(name="Parent", module="Mod", attributes=[]),
                EntitySchema(name="Child", module="Mod", attributes=[]),
            ],
            associations=[
                AssociationSchema(
                    name="Parent_Child",
                    parent_entity="Parent",
                    child_entity="Child",
                    association_type=AssociationType.ONE_TO_MANY,
                    cascade_delete=True,
                ),
            ],
        )

        sdk = MockSDKClient()
        gen = DomainModelGenerator(sdk_client=sdk)
        result = gen.generate(schema, Path("test.mpr"))

        assert result.total_created == 2
        assert result.associations_created == 1
        assert len(result.associations) == 1
        assert result.associations[0].name == "Parent_Child"
        assert result.associations[0].success is True


class TestMicroflowGeneratorEnhanced:
    def test_calculated_field_microflow_generated(self):
        from mendex.bridge.sdk_client import MockSDKClient
        from mendex.generators.microflows import MicroflowGenerator
        from mendex.schema.intermediate import (
            AttributeSchema,
            EntitySchema,
            IntermediateSchema,
        )

        entity = EntitySchema(
            name="Simulacro",
            module="Mod",
            attributes=[
                AttributeSchema(
                    name="Criterio1", mendix_type=MendixDataType.INTEGER,
                    label="C1",
                ),
                AttributeSchema(
                    name="Total", mendix_type=MendixDataType.INTEGER,
                    label="Total", is_calculated=True,
                    calculation_expression="=Criterio1+Criterio2",
                ),
            ],
        )
        schema = IntermediateSchema(
            source=InputSource.EXCEL,
            entities=[entity],
            microflows=[],  # No explicit microflows
        )

        sdk = MockSDKClient()
        gen = MicroflowGenerator(sdk_client=sdk)
        result = gen.generate(schema, Path("test.mpr"))

        # Should auto-generate ACT_Simulacro_Calculate
        assert result.total_created >= 1
        mf_names = [mf["name"] for mf in sdk.created_microflows]
        assert "ACT_Simulacro_Calculate" in mf_names

    def test_cascade_delete_microflow_generated(self):
        from mendex.bridge.sdk_client import MockSDKClient
        from mendex.generators.microflows import MicroflowGenerator
        from mendex.schema.intermediate import (
            AssociationSchema,
            AttributeSchema,
            EntitySchema,
            IntermediateSchema,
        )

        schema = IntermediateSchema(
            source=InputSource.EXCEL,
            entities=[
                EntitySchema(
                    name="Parent", module="Mod",
                    attributes=[AttributeSchema(
                        name="N", mendix_type=MendixDataType.STRING, label="N",
                    )],
                ),
                EntitySchema(
                    name="Child", module="Mod",
                    attributes=[AttributeSchema(
                        name="N", mendix_type=MendixDataType.STRING, label="N",
                    )],
                ),
            ],
            associations=[
                AssociationSchema(
                    name="Parent_Child",
                    parent_entity="Parent",
                    child_entity="Child",
                    association_type=AssociationType.ONE_TO_MANY,
                    cascade_delete=True,
                ),
            ],
            microflows=[],
        )

        sdk = MockSDKClient()
        gen = MicroflowGenerator(sdk_client=sdk)
        result = gen.generate(schema, Path("test.mpr"))

        mf_names = [mf["name"] for mf in sdk.created_microflows]
        assert "ACT_Parent_CascadeDelete" in mf_names


# ─── Tests: Lookup Entity (Enum → Tabla Maestra) ────────────


class TestLookupEntityParser:
    """Tests para la transformación Enum → Lookup Entity."""

    def test_enum_creates_lookup_entity(self, tmp_path: Path):
        """Enum field creates a lookup entity with Name attribute."""
        rows = [
            HEADERS_V2,
            ["Sede", "Enum", "Si", "", "Sede", "Create", "Mod", "Lima,Chimbote,Chicama", "", "", "", "", "", ""],
        ]
        xlsx = _create_xlsx(tmp_path, {"Simulacro": rows})
        schema = ExcelParser().parse(xlsx)

        lookups = [e for e in schema.entities if e.is_lookup]
        assert len(lookups) == 1
        assert lookups[0].name == "Sede"
        assert lookups[0].attributes[0].name == "Name"
        assert lookups[0].attributes[0].mendix_type == MendixDataType.STRING
        assert lookups[0].attributes[0].required is True

    def test_enum_creates_association(self, tmp_path: Path):
        """Enum field creates a lookup association."""
        rows = [
            HEADERS_V2,
            ["Sede", "Enum", "Si", "", "Sede", "Create", "Mod", "Lima,Chimbote", "", "", "", "", "", ""],
        ]
        xlsx = _create_xlsx(tmp_path, {"Simulacro": rows})
        schema = ExcelParser().parse(xlsx)

        lookup_assocs = [a for a in schema.associations if a.is_lookup]
        assert len(lookup_assocs) == 1
        assert lookup_assocs[0].parent_entity == "Sede"
        assert lookup_assocs[0].child_entity == "Simulacro"
        assert lookup_assocs[0].association_type == AssociationType.ONE_TO_MANY

    def test_enum_removes_attribute_from_parent(self, tmp_path: Path):
        """Enum attribute is removed from parent entity."""
        rows = [
            HEADERS_V2,
            ["Nombre", "Texto", "Si", "", "Nombre", "Create", "Mod", "", "", "", "", "", "", ""],
            ["Sede", "Enum", "Si", "", "Sede", "Create", "Mod", "Lima,Arequipa", "", "", "", "", "", ""],
        ]
        xlsx = _create_xlsx(tmp_path, {"Simulacro": rows})
        schema = ExcelParser().parse(xlsx)

        parent = next(e for e in schema.entities if not e.is_lookup)
        attr_names = [a.name for a in parent.attributes]
        assert "Nombre" in attr_names
        assert "Sede" not in attr_names

    def test_lookup_seed_values(self, tmp_path: Path):
        """Lookup entity has correct seed_values."""
        rows = [
            HEADERS_V2,
            ["Estado", "Enum", "", "", "Estado", "", "Mod", "Activo,Inactivo,Suspendido", "", "", "", "", "", ""],
        ]
        xlsx = _create_xlsx(tmp_path, {"Test": rows})
        schema = ExcelParser().parse(xlsx)

        lookup = next(e for e in schema.entities if e.is_lookup)
        assert lookup.seed_values == ["Activo", "Inactivo", "Suspendido"]

    def test_lookup_preserves_ui_metadata(self, tmp_path: Path):
        """Lookup association preserves label, section, visibility, required from original attribute."""
        rows = [
            HEADERS_V2,
            ["Sede", "Enum", "Si", "", "Ubicación", "Create", "Mod", "Lima,Chicama", "", "General", "", "SoloCrear", "", "1"],
        ]
        xlsx = _create_xlsx(tmp_path, {"Formulario": rows})
        schema = ExcelParser().parse(xlsx)

        assoc = next(a for a in schema.associations if a.is_lookup)
        assert assoc.label == "Ubicación"
        assert assoc.section == "General"
        assert assoc.visibility == FieldVisibility.CREATE_ONLY
        assert assoc.required is True

    def test_lookup_deduplication(self, tmp_path: Path):
        """Two sheets with same Enum name produce one lookup entity."""
        sheets = {
            "Pedido": [
                HEADERS_V2,
                ["Nombre", "Texto", "Si", "", "Nombre", "", "Mod", "", "", "", "", "", "", ""],
                ["Estado", "Enum", "", "", "Estado", "", "Mod", "Activo,Inactivo", "", "", "", "", "", ""],
            ],
            "Factura": [
                HEADERS_V2,
                ["Codigo", "Texto", "Si", "", "Codigo", "", "Mod", "", "", "", "", "", "", ""],
                ["Estado", "Enum", "", "", "Estado", "", "Mod", "Activo,Inactivo,Cerrado", "", "", "", "", "", ""],
            ],
        }
        xlsx = _create_xlsx(tmp_path, sheets)
        schema = ExcelParser().parse(xlsx)

        lookups = [e for e in schema.entities if e.is_lookup]
        assert len(lookups) == 1
        assert lookups[0].name == "Estado"
        # Merged seed values: Activo, Inactivo from Pedido + Cerrado from Factura
        assert "Activo" in lookups[0].seed_values
        assert "Inactivo" in lookups[0].seed_values
        assert "Cerrado" in lookups[0].seed_values

    def test_lookup_with_prefix(self, tmp_path: Path):
        """Lookup entity gets prefix from _Config."""
        sheets = {
            "_Config": [
                ["PrefijoEntidad", "SSO_"],
            ],
            "Simulacro": [
                HEADERS_V2,
                ["Sede", "Enum", "Si", "", "Sede", "Create", "Mod", "Lima,Chicama", "", "", "", "", "", ""],
            ],
        }
        xlsx = _create_xlsx(tmp_path, sheets)
        schema = ExcelParser().parse(xlsx)

        lookup = next(e for e in schema.entities if e.is_lookup)
        assert lookup.name == "SSO_Sede"
        assoc = next(a for a in schema.associations if a.is_lookup)
        assert assoc.parent_entity == "SSO_Sede"
        assert assoc.child_entity == "SSO_Simulacro"

    def test_multiple_enums_in_one_entity(self, tmp_path: Path):
        """Multiple enum fields in one entity create multiple lookup entities."""
        rows = [
            HEADERS_V2,
            ["Nombre", "Texto", "Si", "", "Nombre", "", "Mod", "", "", "", "", "", "", ""],
            ["Sede", "Enum", "", "", "Sede", "", "Mod", "Lima,Chicama", "", "", "", "", "", ""],
            ["Estado", "Enum", "", "", "Estado", "", "Mod", "Activo,Inactivo", "", "", "", "", "", ""],
        ]
        xlsx = _create_xlsx(tmp_path, {"Proyecto": rows})
        schema = ExcelParser().parse(xlsx)

        lookups = [e for e in schema.entities if e.is_lookup]
        assert len(lookups) == 2
        lookup_names = {e.name for e in lookups}
        assert lookup_names == {"Sede", "Estado"}

        parent = next(e for e in schema.entities if not e.is_lookup)
        assert len(parent.attributes) == 1  # Only Nombre remains
        assert parent.attributes[0].name == "Nombre"


class TestLookupPageGenerator:
    """Tests for ReferenceSelector widget generation for lookups."""

    def test_reference_selector_for_lookup(self, tmp_path: Path):
        """Page generator creates ReferenceSelector widget for lookup association."""
        from mendex.bridge.sdk_client import MockSDKClient
        from mendex.generators.pages import PageGenerator

        rows = [
            HEADERS_V2,
            ["Nombre", "Texto", "Si", "", "Nombre", "Create", "Mod", "", "", "", "", "", "", ""],
            ["Sede", "Enum", "Si", "", "Sede", "Create", "Mod", "Lima,Chicama", "", "", "", "", "", ""],
        ]
        xlsx = _create_xlsx(tmp_path, {"Proyecto": rows})
        schema = ExcelParser().parse(xlsx)

        sdk = MockSDKClient()
        gen = PageGenerator(sdk_client=sdk)
        gen.generate(schema, tmp_path / "test.mpr")

        # Find Create page
        create_pages = [p for p in sdk.created_pages if p.get("page_type") == "Create"]
        assert len(create_pages) >= 1
        widgets = create_pages[0].get("widgets", [])
        ref_widgets = [w for w in widgets if w.get("widget_type") == "ReferenceSelector"]
        assert len(ref_widgets) == 1
        assert ref_widgets[0]["label"] == "Sede"
        assert ref_widgets[0]["display_attribute"] == "Name"
        assert ref_widgets[0]["required"] is True

    def test_lookup_visibility_filter(self, tmp_path: Path):
        """Lookup with CREATE_ONLY visibility is not shown in Edit page."""
        from mendex.bridge.sdk_client import MockSDKClient
        from mendex.generators.pages import PageGenerator

        rows = [
            HEADERS_V2,
            ["Nombre", "Texto", "Si", "", "Nombre", "Create", "Mod", "", "", "", "", "", "", ""],
            ["Sede", "Enum", "Si", "", "Sede", "Edit", "Mod", "Lima,Chicama", "", "", "", "SoloCrear", "", ""],
        ]
        xlsx = _create_xlsx(tmp_path, {"Proyecto": rows})
        schema = ExcelParser().parse(xlsx)

        sdk = MockSDKClient()
        gen = PageGenerator(sdk_client=sdk)
        gen.generate(schema, tmp_path / "test.mpr")

        # Edit page should NOT have the ReferenceSelector (visibility=CREATE_ONLY)
        edit_pages = [p for p in sdk.created_pages if p.get("page_type") == "Edit"]
        if edit_pages:
            widgets = edit_pages[0].get("widgets", [])
            ref_widgets = [w for w in widgets if w.get("widget_type") == "ReferenceSelector"]
            assert len(ref_widgets) == 0


class TestLookupMicroflowGenerator:
    """Tests for ASe_ seed data microflow generation."""

    def test_seed_microflow_generated(self, tmp_path: Path):
        """Lookup entity with seed_values generates ASe_ microflow."""
        from mendex.bridge.sdk_client import MockSDKClient
        from mendex.generators.microflows import MicroflowGenerator

        rows = [
            HEADERS_V2,
            ["Nombre", "Texto", "Si", "", "Nombre", "Create", "Mod", "", "", "", "", "", "", ""],
            ["Sede", "Enum", "", "", "Sede", "", "Mod", "Lima,Chicama", "", "", "", "", "", ""],
        ]
        xlsx = _create_xlsx(tmp_path, {"Test": rows})
        schema = ExcelParser().parse(xlsx)

        sdk = MockSDKClient()
        gen = MicroflowGenerator(sdk_client=sdk)
        result = gen.generate(schema, tmp_path / "test.mpr")

        mf_names = [mf["name"] for mf in sdk.created_microflows]
        assert "ASe_InitializeSede" in mf_names

        # Check the description mentions seed values
        seed_mf = next(m for m in sdk.created_microflows if m["name"] == "ASe_InitializeSede")
        assert "Lima" in seed_mf["logic_description"]
        assert "Chicama" in seed_mf["logic_description"]

    def test_seed_microflow_per_lookup(self, tmp_path: Path):
        """Each lookup entity gets its own ASe_ microflow."""
        from mendex.bridge.sdk_client import MockSDKClient
        from mendex.generators.microflows import MicroflowGenerator

        rows = [
            HEADERS_V2,
            ["Nombre", "Texto", "Si", "", "Nombre", "", "Mod", "", "", "", "", "", "", ""],
            ["Sede", "Enum", "", "", "Sede", "", "Mod", "Lima,Chicama", "", "", "", "", "", ""],
            ["Estado", "Enum", "", "", "Estado", "", "Mod", "Activo,Inactivo", "", "", "", "", "", ""],
        ]
        xlsx = _create_xlsx(tmp_path, {"Test": rows})
        schema = ExcelParser().parse(xlsx)

        sdk = MockSDKClient()
        gen = MicroflowGenerator(sdk_client=sdk)
        gen.generate(schema, tmp_path / "test.mpr")

        mf_names = [mf["name"] for mf in sdk.created_microflows]
        assert "ASe_InitializeSede" in mf_names
        assert "ASe_InitializeEstado" in mf_names


class TestLookupDomainModelGenerator:
    """Tests for lookup entity creation via domain model generator."""

    def test_lookup_entity_data_has_flags(self, tmp_path: Path):
        """Lookup entity passes is_lookup and seed_values to SDK."""
        from mendex.bridge.sdk_client import MockSDKClient
        from mendex.generators.domain_model import DomainModelGenerator

        rows = [
            HEADERS_V2,
            ["Nombre", "Texto", "Si", "", "Nombre", "Create", "Mod", "", "", "", "", "", "", ""],
            ["Sede", "Enum", "", "", "Sede", "", "Mod", "Lima,Chicama", "", "", "", "", "", ""],
        ]
        xlsx = _create_xlsx(tmp_path, {"Test": rows})
        schema = ExcelParser().parse(xlsx)

        sdk = MockSDKClient()
        gen = DomainModelGenerator(sdk_client=sdk)
        gen.generate(schema, tmp_path / "test.mpr")

        # Find the lookup entity in created entities
        lookup_data = next(
            (e for e in sdk.created_entities if e.get("is_lookup")), None
        )
        assert lookup_data is not None
        assert lookup_data["name"] == "Sede"
        assert lookup_data["seed_values"] == ["Lima", "Chicama"]

    def test_lookup_association_created(self, tmp_path: Path):
        """Lookup association is created via create_association."""
        from mendex.bridge.sdk_client import MockSDKClient
        from mendex.generators.domain_model import DomainModelGenerator

        rows = [
            HEADERS_V2,
            ["Nombre", "Texto", "Si", "", "Nombre", "Create", "Mod", "", "", "", "", "", "", ""],
            ["Sede", "Enum", "", "", "Sede", "", "Mod", "Lima,Chicama", "", "", "", "", "", ""],
        ]
        xlsx = _create_xlsx(tmp_path, {"Test": rows})
        schema = ExcelParser().parse(xlsx)

        sdk = MockSDKClient()
        gen = DomainModelGenerator(sdk_client=sdk)
        gen.generate(schema, tmp_path / "test.mpr")

        assert len(sdk.created_associations) == 1
        assoc = sdk.created_associations[0]
        assert assoc["parent_entity"] == "Sede"
        assert assoc["child_entity"] == "Test"
        assert assoc["is_lookup"] is True


# ─── Tests: Simulacros SSO (integration-style) ──────────────


class TestSimulacrosIntegration:
    """Test completo del formato Simulacros SSO como caso de uso real."""

    def test_full_simulacros_parse(self, tmp_path: Path):
        sheets = {
            "_Config": [
                ["ModuloDestino", "SSO_Seguridad"],
                ["PrefijoEntidad", "SSO_"],
                ["Layout", "Atlas_Default"],
            ],
            "Simulacro": [
                HEADERS_V2,
                ["Codigo", "AutoNumero", "", "", "Código", "Overview", "SSO_Seguridad", "", "", "Generalidades", "", "SoloOverview", "", "1"],
                ["Sede", "Enum", "Si", "", "Sede", "Create", "SSO_Seguridad", "Lima,Chimbote,Chicama", "", "Generalidades", "", "Todos", "", "1"],
                ["FechaSimulacro", "Fecha", "Si", "", "Fecha", "Create", "SSO_Seguridad", "", "", "Generalidades", "", "Todos", "", "1"],
                ["Lugar", "Texto", "Si", "maximo 200 caracteres", "Lugar", "Create", "SSO_Seguridad", "", "", "Generalidades", "", "Todos", "", "1"],
                ["Criterio1", "Entero", "", "entre 0 y 4", "Alarma", "Edit", "SSO_Seguridad", "", "", "Evaluacion", "", "SoloEditar", "", "2"],
                ["PuntajeTotal", "Entero", "", "", "Puntaje Total", "", "SSO_Seguridad", "", "", "Evaluacion", "", "Todos", "Criterio1+Criterio2", "2"],
                ["Observaciones", "TextoGrande", "", "", "Observaciones", "", "SSO_Seguridad", "", "", "Observaciones", "", "Todos", "", "3"],
            ],
            "Participante": [
                ["NombreCampo", "TipoDato", "Requerido", "Etiqueta"],
                ["NombreCompleto", "Texto", "Si", "Nombre Completo"],
                ["DNI", "Texto", "Si", "DNI"],
                ["Area", "Texto", "Si", "Área"],
                ["Asistio", "Booleano", "", "Asistió"],
            ],
            "_Relaciones": [
                ["EntidadOrigen", "EntidadDestino", "Tipo", "CascadeDelete"],
                ["Simulacro", "Participante", "1-*", "Si"],
            ],
            "_Seguridad": [
                ["Entidad", "Rol", "Crear", "Leer", "Escribir", "Eliminar"],
                ["*", "Administrator", "Si", "Si", "Si", "Si"],
                ["Simulacro", "User", "Si", "Si", "Si", "No"],
                ["Participante", "User", "Si", "Si", "Si", "No"],
            ],
        }
        xlsx = _create_xlsx(tmp_path, sheets)
        schema = ExcelParser().parse(xlsx)

        # Entities with prefix (main + lookup)
        entity_names = [e.name for e in schema.entities]
        assert "SSO_Simulacro" in entity_names
        assert "SSO_Participante" in entity_names
        # Sede enum → lookup entity SSO_Sede
        assert "SSO_Sede" in entity_names
        lookup_sede = next(e for e in schema.entities if e.name == "SSO_Sede")
        assert lookup_sede.is_lookup is True
        assert lookup_sede.seed_values == ["Lima", "Chimbote", "Chicama"]

        # Module from config
        for entity in schema.entities:
            assert entity.module == "SSO_Seguridad"

        # Associations: 1 from _Relaciones + 1 lookup (SSO_Sede)
        assert len(schema.associations) == 2
        structural = [a for a in schema.associations if not a.is_lookup]
        assert len(structural) == 1
        assert structural[0].association_type == AssociationType.ONE_TO_MANY
        assert structural[0].cascade_delete is True
        lookup_assocs = [a for a in schema.associations if a.is_lookup]
        assert len(lookup_assocs) == 1
        assert lookup_assocs[0].parent_entity == "SSO_Sede"
        assert lookup_assocs[0].child_entity == "SSO_Simulacro"

        # Simulacro attributes (Sede extracted as lookup, not in attributes)
        sim = next(e for e in schema.entities if e.name == "SSO_Simulacro")
        attrs = {a.name: a for a in sim.attributes}
        assert "Sede" not in attrs and "SSO_Sede" not in attrs  # extracted
        assert "SSO_Codigo" in attrs or "Codigo" in attrs  # prefix may apply
        assert sim.generalization is None  # no file/image types

        # Check visibility
        codigo_attr = next(
            (a for a in sim.attributes if "Codigo" in a.name), None
        )
        if codigo_attr:
            assert codigo_attr.visibility == FieldVisibility.OVERVIEW_ONLY

        # Check sections in pages
        sim_pages = [p for p in schema.pages if "Simulacro" in p.entity]
        create_pages = [p for p in sim_pages if p.page_type == PageType.CREATE]
        if create_pages:
            create_page = create_pages[0]
            if create_page.sections:
                sec_names = [s.name for s in create_page.sections]
                assert "Generalidades" in sec_names

        # Check calculated field
        total_attr = next(
            (a for a in sim.attributes if "PuntajeTotal" in a.name or "Total" in a.name),
            None,
        )
        if total_attr:
            assert total_attr.is_calculated is True

        # Security rules (main entities have rules, lookup/filter entities may not)
        for entity in schema.entities:
            if not entity.is_lookup and not entity.is_filter_entity:
                assert len(entity.access_rules) >= 1  # At least * wildcard
                admin_rules = [r for r in entity.access_rules if r.role == "Administrator"]
                assert len(admin_rules) >= 1

        # Config stored
        assert schema.config.get("modulodestino") == "SSO_Seguridad"
        assert schema.config.get("prefijoentidad") == "SSO_"

        # Validations
        lugar_attr = next(
            (a for a in sim.attributes if "Lugar" in a.name), None
        )
        if lugar_attr:
            max_vals = [v for v in lugar_attr.validations if v.type == ValidationType.MAX_LENGTH]
            assert len(max_vals) == 1
            assert max_vals[0].params["max"] == 200

        criterio_attr = next(
            (a for a in sim.attributes if "Criterio1" in a.name), None
        )
        if criterio_attr:
            range_vals = [v for v in criterio_attr.validations if v.type == ValidationType.RANGE]
            assert len(range_vals) == 1


# ─── Tests: DS_OS_ Selectable Objects (Fase 2) ─────────────


class TestDsOsSelectableObjects:
    """Tests for DS_OS_ microflow generation per lookup entity."""

    def _make_enum_xlsx(self, tmp_path: Path) -> Path:
        rows = [
            HEADERS_V2,
            ["Nombre", "Texto", "Si", "", "Nombre", "Create", "Mod", "", "",
             "", "", "", "", ""],
            ["Sede", "Enum", "Si", "", "Sede", "", "Mod", "Lima,Chimbote", "",
             "", "", "", "", ""],
        ]
        return _create_xlsx(tmp_path, {"Orden": rows})

    def test_ds_os_generated_per_lookup(self, tmp_path: Path):
        """Each lookup entity produces a DS_OS_ microflow in the generator."""
        from mendex.generators.microflows import MicroflowGenerator
        from mendex.bridge.sdk_client import MockSDKClient

        xlsx = self._make_enum_xlsx(tmp_path)
        schema = ExcelParser().parse(xlsx)

        mock = MockSDKClient()
        gen = MicroflowGenerator(sdk_client=mock)
        result = gen.generate(schema, tmp_path / "fake.mpr")

        ds_os = [m for m in result.microflows if m.name.startswith("DS_OS_")]
        assert len(ds_os) >= 1
        assert any("Sede" in m.name for m in ds_os)

    def test_reference_selector_has_selectable_objects(self, tmp_path: Path):
        """ReferenceSelector widgets include selectable_objects_source."""
        from mendex.generators.pages import PageGenerator
        from mendex.bridge.sdk_client import MockSDKClient

        xlsx = self._make_enum_xlsx(tmp_path)
        schema = ExcelParser().parse(xlsx)

        mock = MockSDKClient()
        gen = PageGenerator(sdk_client=mock)
        gen.generate(schema, tmp_path / "fake.mpr")

        # Find Create pages in created pages
        for page_data in mock.created_pages:
            widgets = page_data.get("widgets", [])
            ref_selectors = [w for w in widgets if w.get("widget_type") == "ReferenceSelector"]
            for rs in ref_selectors:
                assert "selectable_objects_source" in rs
                assert rs["selectable_objects_source"].startswith("DS_OS_")


# ─── Tests: Sequential Numbering (Fase 3) ───────────────────


class TestSequentialNumbering:
    """Tests for sequential field detection and SUB_ microflow generation."""

    def test_secuencia_field_detected(self, tmp_path: Path):
        """Campo 'Secuencia' sets has_sequential=True."""
        rows = [
            HEADERS_V2,
            ["Nombre", "Texto", "Si", "", "Nombre", "Create", "Mod", "", "",
             "", "", "", "", ""],
            ["Secuencia", "Entero", "", "", "Secuencia", "", "Mod", "", "",
             "", "", "", "", ""],
        ]
        xlsx = _create_xlsx(tmp_path, {"Detalle": rows})
        schema = ExcelParser().parse(xlsx)
        entity = next(e for e in schema.entities if e.name == "Detalle")
        assert entity.has_sequential is True

    def test_orden_field_detected(self, tmp_path: Path):
        """Campo 'OrdenDetalle' sets has_sequential=True."""
        rows = [
            HEADERS_V2,
            ["Descripcion", "Texto", "", "", "Desc", "Create", "Mod", "", "",
             "", "", "", "", ""],
            ["OrdenDetalle", "Entero", "", "", "Orden", "", "Mod", "", "",
             "", "", "", "", ""],
        ]
        xlsx = _create_xlsx(tmp_path, {"Linea": rows})
        schema = ExcelParser().parse(xlsx)
        entity = next(e for e in schema.entities if e.name == "Linea")
        assert entity.has_sequential is True

    def test_no_sequential_by_default(self, tmp_path: Path):
        """Entity without sequential field has has_sequential=False."""
        rows = [
            HEADERS_V2,
            ["Nombre", "Texto", "Si", "", "Nombre", "Create", "Mod", "", "",
             "", "", "", "", ""],
        ]
        xlsx = _create_xlsx(tmp_path, {"Persona": rows})
        schema = ExcelParser().parse(xlsx)
        entity = next(e for e in schema.entities if e.name == "Persona")
        assert entity.has_sequential is False

    def test_sub_set_secuencia_generated(self, tmp_path: Path):
        """Entity with has_sequential generates SUB_ microflow."""
        from mendex.generators.microflows import MicroflowGenerator
        from mendex.bridge.sdk_client import MockSDKClient

        rows = [
            HEADERS_V2,
            ["Nombre", "Texto", "Si", "", "Nombre", "Create", "Mod", "", "",
             "", "", "", "", ""],
            ["Secuencia", "Entero", "", "", "Secuencia", "", "Mod", "", "",
             "", "", "", "", ""],
        ]
        xlsx = _create_xlsx(tmp_path, {"Detalle": rows})
        schema = ExcelParser().parse(xlsx)

        mock = MockSDKClient()
        gen = MicroflowGenerator(sdk_client=mock)
        result = gen.generate(schema, tmp_path / "fake.mpr")

        sub_mfs = [m for m in result.microflows if m.name.startswith("SUB_")]
        assert len(sub_mfs) >= 1
        assert any("SetSecuencia" in m.name for m in sub_mfs)


# ─── Tests: Dynamic Filters (Fase 4) ────────────────────────


class TestDynamicFilters:
    """Tests for global filter entity and DS_Filtros microflow generation."""

    def _make_enum_xlsx(self, tmp_path: Path, prefix: str = "") -> Path:
        config_rows = [
            ["ModuloDestino", "TestMod"],
        ]
        if prefix:
            config_rows.append(["PrefijoEntidad", prefix])
        sheets: dict[str, list] = {
            "_Config": config_rows,
            "Orden": [
                HEADERS_V2,
                ["Nombre", "Texto", "Si", "", "Nombre", "Create,Overview", "TestMod",
                 "", "", "", "", "", "", ""],
                ["Sede", "Enum", "Si", "", "Sede", "", "TestMod",
                 "Lima,Chimbote", "", "", "", "", "", ""],
                ["Tipo", "Enum", "", "", "Tipo", "", "TestMod",
                 "Urgente,Normal", "", "", "", "", "", ""],
            ],
        }
        return _create_xlsx(tmp_path, sheets)

    def test_filter_entity_created(self, tmp_path: Path):
        """Global filter entity is created (non-persistable)."""
        xlsx = self._make_enum_xlsx(tmp_path)
        schema = ExcelParser().parse(xlsx)
        filter_entities = [e for e in schema.entities if e.is_filter_entity]
        assert len(filter_entities) == 1
        assert filter_entities[0].is_persistable is False

    def test_filter_entity_attributes(self, tmp_path: Path):
        """Filter entity has one attribute per lookup."""
        xlsx = self._make_enum_xlsx(tmp_path)
        schema = ExcelParser().parse(xlsx)
        filt = next(e for e in schema.entities if e.is_filter_entity)
        attr_names = {a.name for a in filt.attributes}
        assert "Filtro_Sede" in attr_names
        assert "Filtro_Tipo" in attr_names

    def test_ds_filtros_microflow_generated(self, tmp_path: Path):
        """DS_{Entity}_Filtros microflow generated for overview pages."""
        from mendex.generators.microflows import MicroflowGenerator
        from mendex.bridge.sdk_client import MockSDKClient

        xlsx = self._make_enum_xlsx(tmp_path)
        schema = ExcelParser().parse(xlsx)

        mock = MockSDKClient()
        gen = MicroflowGenerator(sdk_client=mock)
        result = gen.generate(schema, tmp_path / "fake.mpr")

        ds_filtros = [m for m in result.microflows if "Filtros" in m.name and m.name.startswith("DS_")]
        assert len(ds_filtros) >= 1

    def test_overview_has_filter_widgets(self, tmp_path: Path):
        """Overview page with filter_entity gets DropDown filter widgets."""
        from mendex.generators.pages import PageGenerator
        from mendex.bridge.sdk_client import MockSDKClient

        xlsx = self._make_enum_xlsx(tmp_path)
        schema = ExcelParser().parse(xlsx)

        mock = MockSDKClient()
        gen = PageGenerator(sdk_client=mock)
        gen.generate(schema, tmp_path / "fake.mpr")

        # Find overview page data
        overview_pages = [p for p in mock.created_pages if p.get("page_type") == "Overview"]
        assert len(overview_pages) >= 1

        overview = overview_pages[0]
        filter_widgets = [w for w in overview["widgets"] if w.get("is_filter")]
        assert len(filter_widgets) >= 1
        assert all(w["widget_type"] == "DropDown" for w in filter_widgets)

    def test_filter_entity_global(self, tmp_path: Path):
        """Multiple entities with lookups share ONE filter entity."""
        sheets: dict[str, list] = {
            "Orden": [
                HEADERS_V2,
                ["Nombre", "Texto", "Si", "", "Nombre", "Create", "Mod", "",
                 "", "", "", "", "", ""],
                ["Estado", "Enum", "", "", "Estado", "", "Mod",
                 "Activo,Inactivo", "", "", "", "", "", ""],
            ],
            "Factura": [
                HEADERS_V2,
                ["Monto", "Decimal", "", "", "Monto", "Create", "Mod", "",
                 "", "", "", "", "", ""],
                ["Tipo", "Enum", "", "", "Tipo", "", "Mod",
                 "Compra,Venta", "", "", "", "", "", ""],
            ],
        }
        xlsx = _create_xlsx(tmp_path, sheets)
        schema = ExcelParser().parse(xlsx)
        filter_entities = [e for e in schema.entities if e.is_filter_entity]
        assert len(filter_entities) == 1
        # Should have attributes for both Estado and Tipo
        attr_names = {a.name for a in filter_entities[0].attributes}
        assert "Filtro_Estado" in attr_names
        assert "Filtro_Tipo" in attr_names


# ─── Tests: Config Page + Lookup CRUD (Fase 5) ──────────────


class TestConfigPageAndLookupCrud:
    """Tests for lookup CRUD pages, Configuracion page, and default access rules."""

    def _make_enum_xlsx(self, tmp_path: Path) -> Path:
        rows = [
            HEADERS_V2,
            ["Nombre", "Texto", "Si", "", "Nombre", "Create", "Mod", "", "",
             "", "", "", "", ""],
            ["Sede", "Enum", "Si", "", "Sede", "", "Mod", "Lima,Chimbote", "",
             "", "", "", "", ""],
        ]
        return _create_xlsx(tmp_path, {"Orden": rows})

    def test_lookup_overview_pages_generated(self, tmp_path: Path):
        """Each lookup entity produces an Overview page."""
        xlsx = self._make_enum_xlsx(tmp_path)
        schema = ExcelParser().parse(xlsx)
        overview_pages = [p for p in schema.pages if p.name.endswith("_Overview") and "Sede" in p.name]
        assert len(overview_pages) == 1
        assert overview_pages[0].page_type == PageType.OVERVIEW

    def test_lookup_newedit_pages_generated(self, tmp_path: Path):
        """Each lookup entity produces a NewEdit page."""
        xlsx = self._make_enum_xlsx(tmp_path)
        schema = ExcelParser().parse(xlsx)
        newedit_pages = [p for p in schema.pages if p.name.endswith("_NewEdit") and "Sede" in p.name]
        assert len(newedit_pages) == 1

    def test_configuracion_page_generated(self, tmp_path: Path):
        """Configuracion page generated with navigation_items."""
        xlsx = self._make_enum_xlsx(tmp_path)
        schema = ExcelParser().parse(xlsx)
        config_pages = [p for p in schema.pages if p.page_type == PageType.CONFIG]
        assert len(config_pages) == 1
        assert config_pages[0].name == "Configuracion"
        assert len(config_pages[0].navigation_items) >= 1

    def test_lookup_default_access_rules(self, tmp_path: Path):
        """Lookup entities get default access rules: Admin CRUD, User read-only."""
        xlsx = self._make_enum_xlsx(tmp_path)
        schema = ExcelParser().parse(xlsx)
        lookup = next(e for e in schema.entities if e.is_lookup)
        assert len(lookup.access_rules) == 2

        admin = next(r for r in lookup.access_rules if r.role == "Administrator")
        assert admin.can_create is True
        assert admin.can_delete is True

        user = next(r for r in lookup.access_rules if r.role == "User")
        assert user.can_read is True
        assert user.can_write is False

    def test_lookup_crud_microflows(self, tmp_path: Path):
        """Lookup entities produce ACT_Save and ACT_Delete microflows."""
        xlsx = self._make_enum_xlsx(tmp_path)
        schema = ExcelParser().parse(xlsx)
        lookup_mfs = [m for m in schema.microflows if "Sede" in m.name]
        mf_names = {m.name for m in lookup_mfs}
        assert "ACT_Sede_Save" in mf_names
        assert "ACT_Sede_Delete" in mf_names


# ─── Tests: Action Buttons (Fase 7) ─────────────────────────


class TestActionButtons:
    """Tests for auto-generated action buttons on pages."""

    def _make_simple_xlsx(self, tmp_path: Path) -> Path:
        rows = [
            HEADERS_V2,
            ["Nombre", "Texto", "Si", "", "Nombre", "Create,Overview", "Mod",
             "", "", "", "", "", "", "", ""],
        ]
        return _create_xlsx(tmp_path, {"Orden": rows})

    def test_create_page_has_save_cancel_buttons(self, tmp_path: Path):
        """Create page auto-generates Guardar + Cancelar buttons."""
        from mendex.generators.pages import PageGenerator
        from mendex.bridge.sdk_client import MockSDKClient

        xlsx = self._make_simple_xlsx(tmp_path)
        schema = ExcelParser().parse(xlsx)

        mock = MockSDKClient()
        gen = PageGenerator(sdk_client=mock)
        gen.generate(schema, tmp_path / "fake.mpr")

        create_pages = [p for p in mock.created_pages if p["page_type"] == "Create"]
        assert len(create_pages) >= 1
        buttons = create_pages[0].get("buttons", [])
        labels = {b["label"] for b in buttons}
        assert "Guardar" in labels
        assert "Cancelar" in labels

    def test_overview_page_has_new_edit_delete_buttons(self, tmp_path: Path):
        """Overview page auto-generates Nuevo, Editar, Eliminar buttons."""
        from mendex.generators.pages import PageGenerator
        from mendex.bridge.sdk_client import MockSDKClient

        xlsx = self._make_simple_xlsx(tmp_path)
        schema = ExcelParser().parse(xlsx)

        mock = MockSDKClient()
        gen = PageGenerator(sdk_client=mock)
        gen.generate(schema, tmp_path / "fake.mpr")

        overview_pages = [p for p in mock.created_pages if p["page_type"] == "Overview"]
        assert len(overview_pages) >= 1
        buttons = overview_pages[0].get("buttons", [])
        labels = {b["label"] for b in buttons}
        assert "Nuevo" in labels
        assert "Editar" in labels
        assert "Eliminar" in labels

    def test_buttons_reference_correct_microflows(self, tmp_path: Path):
        """Save button references ACT_{Entity}_Save microflow."""
        from mendex.generators.pages import PageGenerator
        from mendex.bridge.sdk_client import MockSDKClient

        xlsx = self._make_simple_xlsx(tmp_path)
        schema = ExcelParser().parse(xlsx)

        mock = MockSDKClient()
        gen = PageGenerator(sdk_client=mock)
        gen.generate(schema, tmp_path / "fake.mpr")

        create_pages = [p for p in mock.created_pages if p["page_type"] == "Create"]
        buttons = create_pages[0].get("buttons", [])
        save_btn = next(b for b in buttons if b["label"] == "Guardar")
        assert save_btn["microflow"] == "ACT_Orden_Save"

    def test_default_microflows_include_delete(self, tmp_path: Path):
        """Parser now generates DELETE microflow by default."""
        xlsx = self._make_simple_xlsx(tmp_path)
        schema = ExcelParser().parse(xlsx)
        mf_names = {m.name for m in schema.microflows}
        assert "ACT_Orden_Delete" in mf_names


# ─── Tests: Search Bar (Fase 8) ─────────────────────────────


class TestSearchBar:
    """Tests for SearchField widgets on DataGrid Overview pages."""

    def test_overview_generates_search_fields(self, tmp_path: Path):
        """Overview with string/date attrs generates SearchField widgets."""
        from mendex.generators.pages import PageGenerator
        from mendex.bridge.sdk_client import MockSDKClient

        rows = [
            HEADERS_V2,
            ["Nombre", "Texto", "", "", "Nombre", "Overview", "Mod",
             "", "", "", "", "", "", "", ""],
            ["Fecha", "Fecha", "", "", "Fecha", "Overview", "Mod",
             "", "", "", "", "", "", "", ""],
            ["Cantidad", "Entero", "", "", "Cantidad", "Overview", "Mod",
             "", "", "", "", "", "", "", ""],
        ]
        xlsx = _create_xlsx(tmp_path, {"Producto": rows})
        schema = ExcelParser().parse(xlsx)

        mock = MockSDKClient()
        gen = PageGenerator(sdk_client=mock)
        gen.generate(schema, tmp_path / "fake.mpr")

        overview = [p for p in mock.created_pages if p["page_type"] == "Overview"][0]
        search_fields = [w for w in overview["widgets"] if w["widget_type"] == "SearchField"]
        # String (Nombre) and DateTime (Fecha) are searchable, Integer is not
        assert len(search_fields) == 2
        search_attrs = {sf["attribute"] for sf in search_fields}
        assert "Nombre" in search_attrs
        assert "Fecha" in search_attrs

    def test_search_field_types(self, tmp_path: Path):
        """String columns get 'contains', date/enum get 'equals'."""
        from mendex.generators.pages import PageGenerator
        from mendex.bridge.sdk_client import MockSDKClient

        rows = [
            HEADERS_V2,
            ["Nombre", "Texto", "", "", "Nombre", "Overview", "Mod",
             "", "", "", "", "", "", "", ""],
            ["Fecha", "Fecha", "", "", "Fecha", "Overview", "Mod",
             "", "", "", "", "", "", "", ""],
        ]
        xlsx = _create_xlsx(tmp_path, {"Item": rows})
        schema = ExcelParser().parse(xlsx)

        mock = MockSDKClient()
        gen = PageGenerator(sdk_client=mock)
        gen.generate(schema, tmp_path / "fake.mpr")

        overview = [p for p in mock.created_pages if p["page_type"] == "Overview"][0]
        search_fields = {
            sf["attribute"]: sf["search_type"]
            for sf in overview["widgets"] if sf["widget_type"] == "SearchField"
        }
        assert search_fields["Nombre"] == "contains"
        assert search_fields["Fecha"] == "equals"

    def test_search_bar_disabled(self, tmp_path: Path):
        """enable_search_bar=False suppresses SearchField widgets."""
        from mendex.generators.pages import PageGenerator
        from mendex.bridge.sdk_client import MockSDKClient
        from mendex.schema.intermediate import IntermediateSchema, InputSource

        entity = next(iter([
            e for e in ExcelParser().parse(
                _create_xlsx(tmp_path, {"Test": [
                    HEADERS_V2,
                    ["Nombre", "Texto", "", "", "Nombre", "Overview", "Mod",
                     "", "", "", "", "", "", "", ""],
                ]})
            ).entities if not e.is_filter_entity
        ]))
        schema = IntermediateSchema(
            source=InputSource.EXCEL,
            entities=[entity],
            pages=[PageSchema(
                name="Test_Overview",
                page_type=PageType.OVERVIEW,
                entity=entity.name,
                module=entity.module,
                enable_search_bar=False,
            )],
        )

        mock = MockSDKClient()
        gen = PageGenerator(sdk_client=mock)
        gen.generate(schema, tmp_path / "fake.mpr")

        overview = mock.created_pages[0]
        search_fields = [w for w in overview["widgets"] if w["widget_type"] == "SearchField"]
        assert len(search_fields) == 0


# ─── Tests: Conditional Visibility (Fase 9) ─────────────────


class TestConditionalVisibility:
    """Tests for VisibleSi column and conditional visibility on widgets."""

    def test_conditional_visibility_parsed(self, tmp_path: Path):
        """VisibleSi=TipoDoc=Otro parses correctly."""
        rows = [
            HEADERS_V2,
            ["TipoDoc", "Texto", "", "", "Tipo Doc", "Create", "Mod",
             "", "", "", "", "", "", "", ""],
            ["DescOtro", "Texto", "", "", "Descripción Otro", "Create", "Mod",
             "", "", "", "", "", "", "", "TipoDoc=Otro"],
        ]
        xlsx = _create_xlsx(tmp_path, {"Documento": rows})
        schema = ExcelParser().parse(xlsx)
        entity = next(e for e in schema.entities if e.name == "Documento")
        desc_attr = next(a for a in entity.attributes if a.name == "DescOtro")
        assert desc_attr.conditional_visibility is not None
        assert desc_attr.conditional_visibility.depends_on == "TipoDoc"
        assert desc_attr.conditional_visibility.operator == "equals"
        assert desc_attr.conditional_visibility.value == "Otro"

    def test_conditional_visibility_in_widget(self, tmp_path: Path):
        """Generator includes conditional_visibility in widget dict."""
        from mendex.generators.pages import PageGenerator
        from mendex.bridge.sdk_client import MockSDKClient

        rows = [
            HEADERS_V2,
            ["TipoDoc", "Texto", "", "", "Tipo", "Create", "Mod",
             "", "", "", "", "", "", "", ""],
            ["DescOtro", "Texto", "", "", "Desc", "Create", "Mod",
             "", "", "", "", "", "", "", "TipoDoc=Otro"],
        ]
        xlsx = _create_xlsx(tmp_path, {"Doc": rows})
        schema = ExcelParser().parse(xlsx)

        mock = MockSDKClient()
        gen = PageGenerator(sdk_client=mock)
        gen.generate(schema, tmp_path / "fake.mpr")

        create = [p for p in mock.created_pages if p["page_type"] == "Create"][0]
        cond_widgets = [w for w in create["widgets"] if "conditional_visibility" in w]
        assert len(cond_widgets) == 1
        cv = cond_widgets[0]["conditional_visibility"]
        assert cv["depends_on"] == "TipoDoc"
        assert cv["value"] == "Otro"

    def test_conditional_not_empty(self, tmp_path: Path):
        """VisibleSi=Campo (no =value) uses not_empty operator."""
        rows = [
            HEADERS_V2,
            ["Email", "Texto", "", "", "Email", "Create", "Mod",
             "", "", "", "", "", "", "", ""],
            ["ConfEmail", "Texto", "", "", "Confirmar", "Create", "Mod",
             "", "", "", "", "", "", "", "Email"],
        ]
        xlsx = _create_xlsx(tmp_path, {"Usuario": rows})
        schema = ExcelParser().parse(xlsx)
        entity = next(e for e in schema.entities if e.name == "Usuario")
        conf_attr = next(a for a in entity.attributes if a.name == "ConfEmail")
        assert conf_attr.conditional_visibility is not None
        assert conf_attr.conditional_visibility.operator == "not_empty"
        assert conf_attr.conditional_visibility.depends_on == "Email"


# ─── Tests: Master-Detail / Nested ListView (Fase 10) ───────


class TestMasterDetail:
    """Tests for nested list detection and generation."""

    def _make_master_detail_xlsx(self, tmp_path: Path) -> Path:
        sheets = {
            "_Relaciones": [
                ["EntidadOrigen", "EntidadDestino", "Tipo", "NombreAsociacion", "CascadeDelete"],
                ["Recepcion", "Documento", "1-*", "Recepcion_Documento", "No"],
            ],
            "Recepcion": [
                HEADERS_V2,
                ["Fecha", "Fecha", "Si", "", "Fecha", "Create", "Mod",
                 "", "", "", "", "", "", "", ""],
            ],
            "Documento": [
                HEADERS_V2,
                ["Titulo", "Texto", "", "", "Título", "Create", "Mod",
                 "", "", "", "", "", "", "", ""],
                ["Tipo", "Texto", "", "", "Tipo", "", "Mod",
                 "", "", "", "", "", "", "", ""],
            ],
        }
        return _create_xlsx(tmp_path, sheets)

    def test_nested_list_from_association(self, tmp_path: Path):
        """Non-lookup 1-* association generates nested list on parent page."""
        xlsx = self._make_master_detail_xlsx(tmp_path)
        schema = ExcelParser().parse(xlsx)

        create_pages = [p for p in schema.pages if p.entity == "Recepcion" and p.page_type == PageType.CREATE]
        assert len(create_pages) >= 1
        assert len(create_pages[0].nested_lists) == 1
        nested = create_pages[0].nested_lists[0]
        assert nested.child_entity == "Documento"
        assert nested.association == "Recepcion_Documento"

    def test_nested_list_has_buttons(self, tmp_path: Path):
        """Nested list has Agregar and Eliminar buttons in widget output."""
        from mendex.generators.pages import PageGenerator
        from mendex.bridge.sdk_client import MockSDKClient

        xlsx = self._make_master_detail_xlsx(tmp_path)
        schema = ExcelParser().parse(xlsx)

        mock = MockSDKClient()
        gen = PageGenerator(sdk_client=mock)
        gen.generate(schema, tmp_path / "fake.mpr")

        # Find Recepcion Create page
        rec_create = [p for p in mock.created_pages
                      if p["page_type"] == "Create" and p["entity"] == "Recepcion"]
        assert len(rec_create) >= 1
        nested_widgets = [w for w in rec_create[0]["widgets"] if w["widget_type"] == "NestedListView"]
        assert len(nested_widgets) == 1
        btn_labels = {b["label"] for b in nested_widgets[0]["buttons"]}
        assert "Agregar" in btn_labels
        assert "Eliminar" in btn_labels

    def test_nested_list_columns(self, tmp_path: Path):
        """Nested list contains child entity attributes as columns."""
        xlsx = self._make_master_detail_xlsx(tmp_path)
        schema = ExcelParser().parse(xlsx)
        create_page = [p for p in schema.pages if p.entity == "Recepcion" and p.page_type == PageType.CREATE][0]
        nested = create_page.nested_lists[0]
        assert len(nested.display_attributes) >= 1
        assert "Titulo" in nested.display_attributes

    def test_lookup_not_nested(self, tmp_path: Path):
        """Lookup 1-* associations do NOT become nested lists."""
        rows = [
            HEADERS_V2,
            ["Nombre", "Texto", "Si", "", "Nombre", "Create", "Mod",
             "", "", "", "", "", "", "", ""],
            ["Estado", "Enum", "", "", "Estado", "", "Mod",
             "Activo,Inactivo", "", "", "", "", "", "", ""],
        ]
        xlsx = _create_xlsx(tmp_path, {"Orden": rows})
        schema = ExcelParser().parse(xlsx)
        create_pages = [p for p in schema.pages if p.entity == "Orden" and p.page_type == PageType.CREATE]
        assert len(create_pages) >= 1
        assert len(create_pages[0].nested_lists) == 0


# ─── Tests: Popups / Modals (Fase 11) ───────────────────────


class TestPopups:
    """Tests for popup page generation for child entities."""

    def _make_master_detail_xlsx(self, tmp_path: Path) -> Path:
        sheets = {
            "_Relaciones": [
                ["EntidadOrigen", "EntidadDestino", "Tipo", "NombreAsociacion", "CascadeDelete"],
                ["Pedido", "Linea", "1-*", "Pedido_Linea", "No"],
            ],
            "Pedido": [
                HEADERS_V2,
                ["Fecha", "Fecha", "Si", "", "Fecha", "Create", "Mod",
                 "", "", "", "", "", "", "", ""],
            ],
            "Linea": [
                HEADERS_V2,
                ["Producto", "Texto", "", "", "Producto", "Create", "Mod",
                 "", "", "", "", "", "", "", ""],
            ],
        }
        return _create_xlsx(tmp_path, sheets)

    def test_child_page_is_popup(self, tmp_path: Path):
        """Auto-generated child NewEdit page has is_popup=True and PopupLayout."""
        xlsx = self._make_master_detail_xlsx(tmp_path)
        schema = ExcelParser().parse(xlsx)
        child_pages = [p for p in schema.pages if p.name == "Linea_NewEdit"]
        assert len(child_pages) == 1
        assert child_pages[0].is_popup is True
        assert child_pages[0].layout == "PopupLayout"

    def test_popup_button_open_as(self, tmp_path: Path):
        """Agregar button in nested list uses open_as='popup'."""
        from mendex.generators.pages import PageGenerator
        from mendex.bridge.sdk_client import MockSDKClient

        xlsx = self._make_master_detail_xlsx(tmp_path)
        schema = ExcelParser().parse(xlsx)

        mock = MockSDKClient()
        gen = PageGenerator(sdk_client=mock)
        gen.generate(schema, tmp_path / "fake.mpr")

        pedido_create = [p for p in mock.created_pages
                         if p["page_type"] == "Create" and p["entity"] == "Pedido"]
        assert len(pedido_create) >= 1
        nested = [w for w in pedido_create[0]["widgets"] if w["widget_type"] == "NestedListView"]
        assert len(nested) >= 1
        add_btn = next(b for b in nested[0]["buttons"] if b["label"] == "Agregar")
        assert add_btn["open_as"] == "popup"

    def test_regular_pages_not_popup(self, tmp_path: Path):
        """Regular Create/Edit/Overview pages are NOT popups."""
        xlsx = self._make_master_detail_xlsx(tmp_path)
        schema = ExcelParser().parse(xlsx)
        regular_pages = [p for p in schema.pages if p.entity == "Pedido"]
        for page in regular_pages:
            assert page.is_popup is False
