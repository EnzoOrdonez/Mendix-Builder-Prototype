"""Tests de contrato: verifica que los payloads Python→TypeScript tienen la estructura correcta.

Dado un IntermediateSchema conocido, corre todos los generadores con MockSDKClient,
captura los payloads JSON de cada create_* call, y verifica la estructura contra
lo que los handlers TypeScript esperan.

Sprint 3A del plan v2.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mendex.bridge.sdk_client import MockSDKClient
from mendex.generators.domain_model import DomainModelGenerator
from mendex.generators.microflows import MicroflowGenerator
from mendex.generators.pages import PageGenerator
from mendex.schema.intermediate import (
    AccessRuleSchema,
    AssociationSchema,
    AssociationType,
    AttributeSchema,
    EntitySchema,
    IntermediateSchema,
    MendixDataType,
    MicroflowSchema,
    MicroflowType,
    PageSchema,
    PageType,
)

MPR_PATH = Path("fake.mpr")


@pytest.fixture()
def sample_schema() -> IntermediateSchema:
    """Schema de prueba con entidades, páginas y microflows típicos."""
    entity = EntitySchema(
        name="OrdenCompra",
        module="Operaciones",
        attributes=[
            AttributeSchema(
                name="Numero",
                mendix_type=MendixDataType.INTEGER,
                label="Número",
                required=True,
            ),
            AttributeSchema(
                name="Fecha",
                mendix_type=MendixDataType.DATETIME,
                label="Fecha",
                required=True,
            ),
            AttributeSchema(
                name="Estado",
                mendix_type=MendixDataType.STRING,
                label="Estado",
            ),
            AttributeSchema(
                name="Activo",
                mendix_type=MendixDataType.BOOLEAN,
                label="Activo",
            ),
            AttributeSchema(
                name="Monto",
                mendix_type=MendixDataType.DECIMAL,
                label="Monto Total",
            ),
        ],
        access_rules=[
            AccessRuleSchema(
                role="Administrator",
                can_create=True,
                can_read=True,
                can_write=True,
                can_delete=True,
            ),
        ],
    )

    lookup = EntitySchema(
        name="TipoOrden",
        module="Operaciones",
        attributes=[
            AttributeSchema(
                name="Name",
                mendix_type=MendixDataType.STRING,
                label="Nombre",
            ),
        ],
        is_lookup=True,
        seed_values=["Compra", "Venta"],
    )

    return IntermediateSchema(
        source="excel",
        entities=[entity, lookup],
        pages=[
            PageSchema(
                name="OrdenCompra_Overview",
                page_type=PageType.OVERVIEW,
                entity="OrdenCompra",
                module="Operaciones",
                title="Órdenes de Compra",
                layout="Atlas_Default",
            ),
            PageSchema(
                name="OrdenCompra_NewEdit",
                page_type=PageType.CREATE,
                entity="OrdenCompra",
                module="Operaciones",
                title="Nueva Orden",
                layout="Atlas_Default",
            ),
        ],
        microflows=[
            MicroflowSchema(
                name="VAL_OrdenCompra_Validate",
                microflow_type=MicroflowType.VALIDATION,
                entity="OrdenCompra",
                module="Operaciones",
                logic_description="Validar campos requeridos",
            ),
            MicroflowSchema(
                name="ACT_OrdenCompra_Save",
                microflow_type=MicroflowType.SAVE,
                entity="OrdenCompra",
                module="Operaciones",
                logic_description="Validar y guardar orden",
            ),
            MicroflowSchema(
                name="ACT_OrdenCompra_Delete",
                microflow_type=MicroflowType.DELETE,
                entity="OrdenCompra",
                module="Operaciones",
                logic_description="Eliminar orden",
            ),
        ],
        associations=[
            AssociationSchema(
                name="OrdenCompra_TipoOrden",
                parent_entity="OrdenCompra",
                child_entity="TipoOrden",
                association_type=AssociationType.ONE_TO_MANY,
                is_lookup=True,
            ),
        ],
    )


# ═══════════════════════════════════════════════════════════════
# Entity Payload Structure
# ═══════════════════════════════════════════════════════════════


class TestEntityPayloadStructure:
    """Verifica que los payloads de entidad tienen los campos que entity.ts espera."""

    def test_entity_has_required_fields(self, sample_schema: IntermediateSchema):
        mock = MockSDKClient()
        gen = DomainModelGenerator(sdk_client=mock)
        gen.generate(sample_schema, MPR_PATH)

        assert len(mock.created_entities) >= 1
        entity_payload = mock.created_entities[0]

        # Fields expected by entity.ts handler
        assert "name" in entity_payload
        assert "module" in entity_payload
        assert "attributes" in entity_payload
        assert "access_rules" in entity_payload
        assert "is_persistable" in entity_payload

    def test_attribute_has_required_fields(self, sample_schema: IntermediateSchema):
        mock = MockSDKClient()
        gen = DomainModelGenerator(sdk_client=mock)
        gen.generate(sample_schema, MPR_PATH)

        attrs = mock.created_entities[0]["attributes"]
        assert len(attrs) >= 1

        for attr in attrs:
            assert "name" in attr
            assert "mendix_type" in attr
            assert "label" in attr

    def test_attribute_types_are_valid(self, sample_schema: IntermediateSchema):
        mock = MockSDKClient()
        gen = DomainModelGenerator(sdk_client=mock)
        gen.generate(sample_schema, MPR_PATH)

        valid_types = {
            "String", "Integer", "Long", "Decimal", "Boolean",
            "DateTime", "Enumeration", "HashedString", "AutoNumber", "Binary",
        }
        for entity_data in mock.created_entities:
            for attr in entity_data["attributes"]:
                assert attr["mendix_type"] in valid_types, (
                    f"Invalid type '{attr['mendix_type']}' for {attr['name']}"
                )

    def test_access_rule_has_required_fields(self, sample_schema: IntermediateSchema):
        mock = MockSDKClient()
        gen = DomainModelGenerator(sdk_client=mock)
        gen.generate(sample_schema, MPR_PATH)

        rules = mock.created_entities[0]["access_rules"]
        assert len(rules) >= 1

        for rule in rules:
            assert "role" in rule
            assert "can_create" in rule
            assert "can_read" in rule
            assert "can_write" in rule
            assert "can_delete" in rule


# ═══════════════════════════════════════════════════════════════
# Page Payload Structure
# ═══════════════════════════════════════════════════════════════


class TestPagePayloadStructure:
    """Verifica que los payloads de página tienen los campos que page.ts espera."""

    def test_page_has_required_fields(self, sample_schema: IntermediateSchema):
        mock = MockSDKClient()
        gen = PageGenerator(sdk_client=mock)
        gen.generate(sample_schema, MPR_PATH)

        assert len(mock.created_pages) >= 1
        page_payload = mock.created_pages[0]

        # Fields expected by page.ts handler
        assert "name" in page_payload
        assert "page_type" in page_payload
        assert "entity" in page_payload
        assert "module" in page_payload
        assert "title" in page_payload
        assert "layout" in page_payload

    def test_page_has_widgets(self, sample_schema: IntermediateSchema):
        mock = MockSDKClient()
        gen = PageGenerator(sdk_client=mock)
        gen.generate(sample_schema, MPR_PATH)

        for page_data in mock.created_pages:
            assert "widgets" in page_data
            assert isinstance(page_data["widgets"], list)

    def test_widget_has_type(self, sample_schema: IntermediateSchema):
        mock = MockSDKClient()
        gen = PageGenerator(sdk_client=mock)
        gen.generate(sample_schema, MPR_PATH)

        for page_data in mock.created_pages:
            for widget in page_data["widgets"]:
                assert "widget_type" in widget, (
                    f"Widget in page '{page_data['name']}' missing widget_type"
                )

    def test_page_types_are_valid(self, sample_schema: IntermediateSchema):
        mock = MockSDKClient()
        gen = PageGenerator(sdk_client=mock)
        gen.generate(sample_schema, MPR_PATH)

        valid_types = {"Create", "Edit", "Overview", "Config"}
        for page_data in mock.created_pages:
            assert page_data["page_type"] in valid_types, (
                f"Invalid page_type '{page_data['page_type']}'"
            )

    def test_overview_page_has_buttons(self, sample_schema: IntermediateSchema):
        mock = MockSDKClient()
        gen = PageGenerator(sdk_client=mock)
        gen.generate(sample_schema, MPR_PATH)

        overview_pages = [
            p for p in mock.created_pages if p["page_type"] == "Overview"
        ]
        assert len(overview_pages) >= 1

        for page_data in overview_pages:
            assert "buttons" in page_data
            assert len(page_data["buttons"]) > 0

    def test_button_has_label(self, sample_schema: IntermediateSchema):
        mock = MockSDKClient()
        gen = PageGenerator(sdk_client=mock)
        gen.generate(sample_schema, MPR_PATH)

        for page_data in mock.created_pages:
            for btn in page_data.get("buttons", []):
                assert "label" in btn


# ═══════════════════════════════════════════════════════════════
# Microflow Payload Structure
# ═══════════════════════════════════════════════════════════════


class TestMicroflowPayloadStructure:
    """Verifica que los payloads de microflow tienen los campos que microflow.ts espera."""

    def test_microflow_has_required_fields(self, sample_schema: IntermediateSchema):
        mock = MockSDKClient()
        gen = MicroflowGenerator(sdk_client=mock)
        gen.generate(sample_schema, MPR_PATH)

        assert len(mock.created_microflows) >= 1
        mf_payload = mock.created_microflows[0]

        # Fields expected by microflow.ts handler
        assert "name" in mf_payload
        assert "microflow_type" in mf_payload
        assert "entity" in mf_payload
        assert "module" in mf_payload
        assert "logic_description" in mf_payload
        assert "activities" in mf_payload
        assert "return_type" in mf_payload

    def test_microflow_has_input_parameter(self, sample_schema: IntermediateSchema):
        mock = MockSDKClient()
        gen = MicroflowGenerator(sdk_client=mock)
        gen.generate(sample_schema, MPR_PATH)

        for mf_data in mock.created_microflows:
            assert "input_parameter" in mf_data
            param = mf_data["input_parameter"]
            assert "name" in param
            assert "entity" in param
            # entity should be qualified: Module.Entity
            assert "." in param["entity"]

    def test_activities_are_list(self, sample_schema: IntermediateSchema):
        mock = MockSDKClient()
        gen = MicroflowGenerator(sdk_client=mock)
        gen.generate(sample_schema, MPR_PATH)

        for mf_data in mock.created_microflows:
            assert isinstance(mf_data["activities"], list)

    def test_activity_has_type(self, sample_schema: IntermediateSchema):
        mock = MockSDKClient()
        gen = MicroflowGenerator(sdk_client=mock)
        gen.generate(sample_schema, MPR_PATH)

        valid_activity_types = {
            "CommitActivity",
            "DeleteActivity",
            "RetrieveActivity",
            "ChangeActivity",
            "MicroflowCallActivity",
            "ClosePageActivity",
            "ShowMessageActivity",
            "ValidationActivity",
            "CreateActivity",
        }
        for mf_data in mock.created_microflows:
            for act in mf_data["activities"]:
                assert "type" in act, (
                    f"Activity in '{mf_data['name']}' missing 'type'"
                )
                assert act["type"] in valid_activity_types, (
                    f"Unknown activity type '{act['type']}' in '{mf_data['name']}'"
                )

    def test_validation_microflow_returns_boolean(self, sample_schema: IntermediateSchema):
        mock = MockSDKClient()
        gen = MicroflowGenerator(sdk_client=mock)
        gen.generate(sample_schema, MPR_PATH)

        val_mfs = [
            m for m in mock.created_microflows
            if m["microflow_type"] == "Validation"
        ]
        assert len(val_mfs) >= 1
        for mf in val_mfs:
            assert mf["return_type"] == "Boolean"

    def test_save_microflow_has_commit_and_close(self, sample_schema: IntermediateSchema):
        mock = MockSDKClient()
        gen = MicroflowGenerator(sdk_client=mock)
        gen.generate(sample_schema, MPR_PATH)

        save_mfs = [
            m for m in mock.created_microflows
            if m["microflow_type"] == "Save"
        ]
        assert len(save_mfs) >= 1
        for mf in save_mfs:
            types = [a["type"] for a in mf["activities"]]
            assert "CommitActivity" in types
            assert "ClosePageActivity" in types

    def test_delete_microflow_has_delete_and_close(self, sample_schema: IntermediateSchema):
        mock = MockSDKClient()
        gen = MicroflowGenerator(sdk_client=mock)
        gen.generate(sample_schema, MPR_PATH)

        del_mfs = [
            m for m in mock.created_microflows
            if m["microflow_type"] == "Delete"
        ]
        assert len(del_mfs) >= 1
        for mf in del_mfs:
            types = [a["type"] for a in mf["activities"]]
            assert "DeleteActivity" in types
            assert "ClosePageActivity" in types

    def test_microflow_types_are_valid(self, sample_schema: IntermediateSchema):
        mock = MockSDKClient()
        gen = MicroflowGenerator(sdk_client=mock)
        gen.generate(sample_schema, MPR_PATH)

        valid_types = {"Validation", "Save", "Delete", "Custom", "DataSource", "Sequence"}
        for mf_data in mock.created_microflows:
            assert mf_data["microflow_type"] in valid_types


# ═══════════════════════════════════════════════════════════════
# Association Payload Structure
# ═══════════════════════════════════════════════════════════════


class TestAssociationPayloadStructure:
    """Verifica que los payloads de asociación tienen los campos que association.ts espera."""

    def test_association_has_required_fields(self, sample_schema: IntermediateSchema):
        mock = MockSDKClient()
        gen = DomainModelGenerator(sdk_client=mock)
        gen.generate(sample_schema, MPR_PATH)

        assert len(mock.created_associations) >= 1
        assoc_payload = mock.created_associations[0]

        # Fields expected by association.ts handler
        assert "name" in assoc_payload
        assert "parent_entity" in assoc_payload
        assert "child_entity" in assoc_payload
        assert "association_type" in assoc_payload
        assert "module" in assoc_payload

    def test_association_type_is_valid(self, sample_schema: IntermediateSchema):
        mock = MockSDKClient()
        gen = DomainModelGenerator(sdk_client=mock)
        gen.generate(sample_schema, MPR_PATH)

        valid_types = {"1-*", "*-*", "1-1"}
        for assoc_data in mock.created_associations:
            assert assoc_data["association_type"] in valid_types

    def test_association_module_resolved(self, sample_schema: IntermediateSchema):
        mock = MockSDKClient()
        gen = DomainModelGenerator(sdk_client=mock)
        gen.generate(sample_schema, MPR_PATH)

        for assoc_data in mock.created_associations:
            assert assoc_data["module"] != "", (
                f"Association '{assoc_data['name']}' has empty module"
            )
