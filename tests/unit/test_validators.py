"""Tests para los validadores post-generación y convenciones."""

from __future__ import annotations

import pytest

from mendex.schema.intermediate import (
    AssociationSchema,
    AssociationType,
    AttributeSchema,
    ButtonSchema,
    ButtonType,
    EntitySchema,
    IntermediateSchema,
    MendixDataType,
    MicroflowSchema,
    MicroflowType,
    PageSchema,
    PageType,
)
from mendex.validators.conventions import ConventionsValidator, is_pascal_case
from mendex.validators.post_generation import (
    PostGenerationValidator,
    Severity,
    ValidationReport,
)


# ─── Helpers ────────────────────────────────────────────────


def _make_entity(
    name: str = "Documento",
    module: str = "Operaciones",
    attrs: list[str] | None = None,
) -> EntitySchema:
    attributes = []
    for attr_name in attrs or ["Nombre"]:
        attributes.append(
            AttributeSchema(
                name=attr_name,
                mendix_type=MendixDataType.STRING,
                label=attr_name,
            )
        )
    return EntitySchema(name=name, module=module, attributes=attributes)


def _make_page(
    name: str = "Documento_Overview",
    entity: str = "Documento",
    module: str = "Operaciones",
    page_type: PageType = PageType.OVERVIEW,
    buttons: list[ButtonSchema] | None = None,
    filter_entity: str | None = None,
) -> PageSchema:
    return PageSchema(
        name=name,
        page_type=page_type,
        entity=entity,
        module=module,
        title=name,
        layout="Atlas_Default",
        buttons=buttons or [],
        filter_entity=filter_entity,
    )


def _make_microflow(
    name: str = "ACT_Documento_Save",
    entity: str = "Documento",
    module: str = "Operaciones",
    mf_type: MicroflowType = MicroflowType.SAVE,
    return_entity: str | None = None,
) -> MicroflowSchema:
    return MicroflowSchema(
        name=name,
        microflow_type=mf_type,
        entity=entity,
        module=module,
        logic_description="test",
        return_entity=return_entity,
    )


def _make_schema(
    entities: list[EntitySchema] | None = None,
    pages: list[PageSchema] | None = None,
    microflows: list[MicroflowSchema] | None = None,
    associations: list[AssociationSchema] | None = None,
) -> IntermediateSchema:
    return IntermediateSchema(
        source="excel",
        entities=entities or [],
        pages=pages or [],
        microflows=microflows or [],
        associations=associations or [],
    )


# ═══════════════════════════════════════════════════════════════
# PostGenerationValidator
# ═══════════════════════════════════════════════════════════════


class TestPostGenerationValidator:
    """Tests para PostGenerationValidator."""

    def test_valid_schema_passes(self):
        entity = _make_entity()
        page = _make_page()
        mf = _make_microflow(
            name="VAL_Documento_Validate",
            mf_type=MicroflowType.VALIDATION,
        )
        save_mf = _make_microflow()
        schema = _make_schema(
            entities=[entity],
            pages=[page],
            microflows=[mf, save_mf],
        )
        report = PostGenerationValidator().validate(schema)
        assert report.is_valid

    def test_page_references_missing_entity(self):
        page = _make_page(entity="NoExiste")
        schema = _make_schema(pages=[page])
        report = PostGenerationValidator().validate(schema)
        assert not report.is_valid
        assert any("NoExiste" in i.message for i in report.errors)

    def test_page_references_missing_filter_entity(self):
        entity = _make_entity()
        page = _make_page(filter_entity="NoExisteFiltro")
        schema = _make_schema(entities=[entity], pages=[page])
        report = PostGenerationValidator().validate(schema)
        assert not report.is_valid
        assert any("NoExisteFiltro" in i.message for i in report.errors)

    def test_microflow_references_missing_entity(self):
        mf = _make_microflow(entity="NoExiste")
        schema = _make_schema(microflows=[mf])
        report = PostGenerationValidator().validate(schema)
        assert not report.is_valid

    def test_association_parent_missing(self):
        entity = _make_entity(name="Detalle")
        assoc = AssociationSchema(
            name="Documento_Detalle",
            parent_entity="Documento",
            child_entity="Detalle",
        )
        schema = _make_schema(entities=[entity], associations=[assoc])
        report = PostGenerationValidator().validate(schema)
        assert not report.is_valid
        assert any("parent" in i.message.lower() for i in report.errors)

    def test_association_child_missing(self):
        entity = _make_entity(name="Documento")
        assoc = AssociationSchema(
            name="Documento_Detalle",
            parent_entity="Documento",
            child_entity="Detalle",
        )
        schema = _make_schema(entities=[entity], associations=[assoc])
        report = PostGenerationValidator().validate(schema)
        assert not report.is_valid
        assert any("child" in i.message.lower() for i in report.errors)

    def test_valid_association_passes(self):
        e1 = _make_entity(name="Documento")
        e2 = _make_entity(name="Detalle")
        assoc = AssociationSchema(
            name="Documento_Detalle",
            parent_entity="Documento",
            child_entity="Detalle",
        )
        schema = _make_schema(entities=[e1, e2], associations=[assoc])
        report = PostGenerationValidator().validate(schema)
        # No association entity errors
        assoc_errors = [
            i for i in report.errors if i.artifact_type == "association"
        ]
        assert len(assoc_errors) == 0

    def test_button_references_missing_microflow(self):
        entity = _make_entity()
        button = ButtonSchema(
            label="Guardar",
            button_type=ButtonType.SAVE,
            microflow="ACT_Documento_Save",
        )
        page = _make_page(buttons=[button])
        schema = _make_schema(entities=[entity], pages=[page])
        report = PostGenerationValidator().validate(schema)
        assert any(
            i.category == "button_ref" and "ACT_Documento_Save" in i.message
            for i in report.warnings
        )

    def test_button_references_existing_microflow(self):
        entity = _make_entity()
        mf = _make_microflow(name="ACT_Documento_Save")
        button = ButtonSchema(
            label="Guardar",
            button_type=ButtonType.SAVE,
            microflow="ACT_Documento_Save",
        )
        page = _make_page(buttons=[button])
        schema = _make_schema(entities=[entity], pages=[page], microflows=[mf])
        report = PostGenerationValidator().validate(schema)
        button_ref_issues = [
            i for i in report.issues
            if i.category == "button_ref" and "ACT_Documento_Save" in i.message
        ]
        assert len(button_ref_issues) == 0

    def test_button_references_missing_page(self):
        entity = _make_entity()
        button = ButtonSchema(
            label="Nuevo",
            button_type=ButtonType.NEW,
            target_page="Documento_New",
        )
        page = _make_page(buttons=[button])
        schema = _make_schema(entities=[entity], pages=[page])
        report = PostGenerationValidator().validate(schema)
        assert any(
            i.category == "button_ref" and "Documento_New" in i.message
            for i in report.warnings
        )

    def test_save_microflow_warns_missing_validation(self):
        entity = _make_entity()
        save_mf = _make_microflow()
        schema = _make_schema(entities=[entity], microflows=[save_mf])
        report = PostGenerationValidator().validate(schema)
        assert any(
            i.category == "microflow_call" and "VAL_Documento_Validate" in i.message
            for i in report.warnings
        )

    def test_save_microflow_no_warn_when_validation_exists(self):
        entity = _make_entity()
        val_mf = _make_microflow(
            name="VAL_Documento_Validate",
            mf_type=MicroflowType.VALIDATION,
        )
        save_mf = _make_microflow()
        schema = _make_schema(entities=[entity], microflows=[val_mf, save_mf])
        report = PostGenerationValidator().validate(schema)
        assert not any(
            i.category == "microflow_call"
            for i in report.warnings
        )

    def test_datasource_return_entity_invalid(self):
        entity = _make_entity()
        ds_mf = _make_microflow(
            name="DS_OS_TipoDoc",
            mf_type=MicroflowType.DATA_SOURCE,
            return_entity="NoExiste",
        )
        schema = _make_schema(entities=[entity], microflows=[ds_mf])
        report = PostGenerationValidator().validate(schema)
        assert not report.is_valid
        assert any("return_type" in i.category for i in report.errors)

    def test_datasource_return_entity_valid(self):
        entity = _make_entity(name="TipoDoc")
        ds_mf = _make_microflow(
            name="DS_OS_TipoDoc",
            mf_type=MicroflowType.DATA_SOURCE,
            return_entity="TipoDoc",
        )
        schema = _make_schema(entities=[entity], microflows=[ds_mf])
        report = PostGenerationValidator().validate(schema)
        return_errors = [i for i in report.errors if i.category == "return_type"]
        assert len(return_errors) == 0

    def test_orphan_page_without_entity(self):
        page = _make_page(entity="")
        schema = _make_schema(pages=[page])
        report = PostGenerationValidator().validate(schema)
        assert any(
            i.category == "orphan" and i.artifact_type == "page"
            for i in report.warnings
        )

    def test_config_page_no_orphan_warning(self):
        page = _make_page(
            name="Configuracion",
            entity="",
            page_type=PageType.CONFIG,
        )
        schema = _make_schema(pages=[page])
        report = PostGenerationValidator().validate(schema)
        orphan_page_warnings = [
            i for i in report.warnings
            if i.category == "orphan" and i.artifact_type == "page"
        ]
        assert len(orphan_page_warnings) == 0

    def test_empty_schema_is_valid(self):
        schema = _make_schema()
        report = PostGenerationValidator().validate(schema)
        assert report.is_valid


class TestValidationReport:
    """Tests para ValidationReport."""

    def test_summary_format(self):
        report = ValidationReport()
        assert "0 errors" in report.summary()
        assert "0 warnings" in report.summary()

    def test_is_valid_with_warnings_only(self):
        from mendex.validators.post_generation import ValidationIssue

        report = ValidationReport(
            issues=[
                ValidationIssue(
                    severity=Severity.WARNING,
                    category="test",
                    message="just a warning",
                )
            ]
        )
        assert report.is_valid  # warnings don't block


# ═══════════════════════════════════════════════════════════════
# ConventionsValidator
# ═══════════════════════════════════════════════════════════════


class TestIsPascalCase:
    """Tests para is_pascal_case helper."""

    def test_valid_pascal(self):
        assert is_pascal_case("Documento")
        assert is_pascal_case("OrdenCompra")
        assert is_pascal_case("Ab")

    def test_invalid_pascal(self):
        assert not is_pascal_case("documento")
        assert not is_pascal_case("orden_compra")
        assert not is_pascal_case("ALLCAPS")
        assert not is_pascal_case("")


class TestConventionsValidator:
    """Tests para ConventionsValidator."""

    def test_entity_names_pascal_case(self):
        entity = _make_entity(name="Documento")
        schema = _make_schema(entities=[entity])
        report = ConventionsValidator().validate(schema)
        naming_issues = [
            i for i in report.issues
            if i.category == "naming" and i.artifact_type == "entity"
        ]
        assert len(naming_issues) == 0

    def test_entity_names_not_pascal_warns(self):
        entity = _make_entity(name="documento_bajo")
        schema = _make_schema(entities=[entity])
        report = ConventionsValidator().validate(schema)
        naming_issues = [
            i for i in report.issues
            if i.category == "naming" and i.artifact_type == "entity"
        ]
        assert len(naming_issues) > 0

    def test_microflow_known_prefix(self):
        mf = _make_microflow(name="ACT_Documento_Save")
        schema = _make_schema(microflows=[mf])
        report = ConventionsValidator().validate(schema)
        mf_naming = [
            i for i in report.issues
            if i.category == "naming" and i.artifact_type == "microflow"
        ]
        assert len(mf_naming) == 0

    def test_microflow_unknown_prefix_warns(self):
        mf = _make_microflow(name="XYZ_Documento_Save")
        schema = _make_schema(microflows=[mf])
        report = ConventionsValidator().validate(schema)
        mf_naming = [
            i for i in report.issues
            if i.category == "naming" and i.artifact_type == "microflow"
        ]
        assert len(mf_naming) > 0
        assert "XYZ" in mf_naming[0].message

    def test_page_known_suffix(self):
        page = _make_page(name="Documento_Overview")
        schema = _make_schema(pages=[page])
        report = ConventionsValidator().validate(schema)
        page_naming = [
            i for i in report.issues
            if i.category == "naming" and i.artifact_type == "page"
        ]
        assert len(page_naming) == 0

    def test_page_no_underscore_warns(self):
        page = _make_page(name="DocumentoListado")
        schema = _make_schema(pages=[page])
        report = ConventionsValidator().validate(schema)
        page_naming = [
            i for i in report.issues
            if i.category == "naming" and i.artifact_type == "page"
        ]
        assert len(page_naming) > 0

    def test_page_configuracion_no_warn(self):
        page = _make_page(name="Configuracion", page_type=PageType.CONFIG, entity="")
        schema = _make_schema(pages=[page])
        report = ConventionsValidator().validate(schema)
        page_naming = [
            i for i in report.issues
            if i.category == "naming" and i.artifact_type == "page"
        ]
        assert len(page_naming) == 0

    def test_attribute_module_prefix_allowed(self):
        """SGP_NombreCampo is valid (module prefix + PascalCase)."""
        entity = _make_entity(attrs=["SGP_NombreCampo"])
        schema = _make_schema(entities=[entity])
        report = ConventionsValidator().validate(schema)
        attr_naming = [
            i for i in report.issues
            if i.category == "naming" and i.artifact_type == "attribute"
        ]
        assert len(attr_naming) == 0
