"""Tests para el IntermediateSchema — contrato de datos central."""

from __future__ import annotations

from mendex.schema.intermediate import (
    AccessRuleSchema,
    AttributeSchema,
    EntitySchema,
    InputSource,
    IntermediateSchema,
    MendixDataType,
    PageSchema,
    PageType,
    ValidationRuleSchema,
    ValidationType,
)


class TestAttributeSchema:
    def test_basic_attribute(self) -> None:
        attr = AttributeSchema(
            name="Nombre",
            mendix_type=MendixDataType.STRING,
            label="Nombre Completo",
        )
        assert attr.name == "Nombre"
        assert attr.mendix_type == MendixDataType.STRING
        assert attr.required is False
        assert attr.validations == []

    def test_required_attribute_with_validation(self) -> None:
        attr = AttributeSchema(
            name="Email",
            mendix_type=MendixDataType.STRING,
            label="Correo Electrónico",
            required=True,
            validations=[
                ValidationRuleSchema(
                    type=ValidationType.REGEX,
                    params={"pattern": r"^[\w.]+@[\w.]+\.\w+$"},
                    error_message="Email inválido",
                ),
            ],
        )
        assert attr.required is True
        assert len(attr.validations) == 1
        assert attr.validations[0].type == ValidationType.REGEX


class TestEntitySchema:
    def test_entity_with_access_rules(self) -> None:
        entity = EntitySchema(
            name="OrdenCompra",
            module="Operaciones",
            attributes=[
                AttributeSchema(
                    name="Numero",
                    mendix_type=MendixDataType.INTEGER,
                    label="Número",
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
                AccessRuleSchema(
                    role="User",
                    can_read=True,
                ),
            ],
        )
        assert entity.name == "OrdenCompra"
        assert len(entity.access_rules) == 2
        assert entity.access_rules[1].can_write is False


class TestIntermediateSchema:
    def test_minimal_schema(self, sample_schema: IntermediateSchema) -> None:
        assert sample_schema.source == InputSource.EXCEL
        assert len(sample_schema.entities) == 1
        assert sample_schema.entities[0].name == "OrdenCompra"
        assert sample_schema.figma_metadata is None

    def test_schema_with_pages(self, sample_entity: EntitySchema) -> None:
        schema = IntermediateSchema(
            source=InputSource.EXCEL,
            entities=[sample_entity],
            pages=[
                PageSchema(
                    name="OrdenCompra_NewEdit",
                    page_type=PageType.CREATE,
                    entity="OrdenCompra",
                    module="Operaciones",
                ),
            ],
        )
        assert len(schema.pages) == 1
        assert schema.pages[0].page_type == PageType.CREATE

    def test_schema_serialization(self, sample_schema: IntermediateSchema) -> None:
        json_str = sample_schema.model_dump_json()
        restored = IntermediateSchema.model_validate_json(json_str)
        assert restored.entities[0].name == sample_schema.entities[0].name
        assert len(restored.entities[0].attributes) == len(
            sample_schema.entities[0].attributes
        )
