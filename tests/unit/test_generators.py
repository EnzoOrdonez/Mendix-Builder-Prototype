"""Tests para los generadores de páginas y microflows.

Fase 9: Tests unitarios completos.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mendex.bridge.sdk_client import MockSDKClient, SDKClientError
from mendex.generators.microflows import (
    MicroflowGenerationResult,
    MicroflowGenerator,
    MicroflowResult,
)
from mendex.generators.pages import (
    PageGenerationResult,
    PageGenerator,
    PageResult,
)
from mendex.logging.decision_logger import DecisionLogger
from mendex.schema.intermediate import (
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


# ─── Fixtures ────────────────────────────────────────────────


@pytest.fixture
def mpr_path(tmp_path: Path) -> Path:
    mpr = tmp_path / "test.mpr"
    mpr.write_bytes(b"fake")
    return mpr


@pytest.fixture
def mock_sdk() -> MockSDKClient:
    return MockSDKClient()


@pytest.fixture
def mock_sdk_with_existing() -> MockSDKClient:
    return MockSDKClient(existing_artifacts={
        "page:Mod.TestEntity_Create",
        "microflow:Mod.VAL_TestEntity_Validate",
    })


@pytest.fixture
def decision_logger(tmp_path: Path) -> DecisionLogger:
    return DecisionLogger(tmp_path / "decisions.jsonl")


def _entity(
    name: str = "TestEntity",
    module: str = "Mod",
    n_attrs: int = 3,
) -> EntitySchema:
    attrs = [
        AttributeSchema(
            name=f"Field{i}",
            mendix_type=[
                MendixDataType.STRING,
                MendixDataType.INTEGER,
                MendixDataType.BOOLEAN,
                MendixDataType.DATETIME,
                MendixDataType.DECIMAL,
            ][i % 5],
            label=f"Field {i}",
            required=(i == 1),
        )
        for i in range(1, n_attrs + 1)
    ]
    return EntitySchema(name=name, module=module, attributes=attrs)


def _page(
    name: str = "TestEntity_Create",
    module: str = "Mod",
    entity: str = "TestEntity",
    page_type: PageType = PageType.CREATE,
) -> PageSchema:
    return PageSchema(
        name=name, page_type=page_type, entity=entity, module=module
    )


def _microflow(
    name: str = "VAL_TestEntity_Validate",
    module: str = "Mod",
    entity: str = "TestEntity",
    mf_type: MicroflowType = MicroflowType.VALIDATION,
) -> MicroflowSchema:
    return MicroflowSchema(
        name=name,
        microflow_type=mf_type,
        entity=entity,
        module=module,
        logic_description="Test microflow",
    )


def _schema(
    entities: list[EntitySchema] | None = None,
    pages: list[PageSchema] | None = None,
    microflows: list[MicroflowSchema] | None = None,
) -> IntermediateSchema:
    return IntermediateSchema(
        source=InputSource.EXCEL,
        source_file="test.xlsx",
        entities=entities or [],
        pages=pages or [],
        microflows=microflows or [],
    )


# ═══════════════════════════════════════════════════════════════
# PAGE GENERATOR TESTS
# ═══════════════════════════════════════════════════════════════


class TestPageGeneratorBasic:
    def test_empty_schema(self, mock_sdk: MockSDKClient, mpr_path: Path):
        gen = PageGenerator(sdk_client=mock_sdk)
        result = gen.generate(_schema(), mpr_path)
        assert result.success
        assert result.total_created == 0

    def test_single_create_page(self, mock_sdk: MockSDKClient, mpr_path: Path):
        gen = PageGenerator(sdk_client=mock_sdk)
        schema = _schema(
            entities=[_entity()],
            pages=[_page()],
        )
        result = gen.generate(schema, mpr_path)
        assert result.success
        assert result.total_created == 1
        assert len(mock_sdk.created_pages) == 1

    def test_page_data_sent_to_sdk(self, mock_sdk: MockSDKClient, mpr_path: Path):
        gen = PageGenerator(sdk_client=mock_sdk)
        schema = _schema(
            entities=[_entity()],
            pages=[_page(name="MyPage_Create", page_type=PageType.CREATE)],
        )
        gen.generate(schema, mpr_path)
        data = mock_sdk.created_pages[0]
        assert data["name"] == "MyPage_Create"
        assert data["page_type"] == "Create"
        assert data["entity"] == "TestEntity"
        assert data["module"] == "Mod"

    def test_multiple_pages(self, mock_sdk: MockSDKClient, mpr_path: Path):
        gen = PageGenerator(sdk_client=mock_sdk)
        schema = _schema(
            entities=[_entity()],
            pages=[
                _page(name="E_Create", page_type=PageType.CREATE),
                _page(name="E_Edit", page_type=PageType.EDIT),
                _page(name="E_Overview", page_type=PageType.OVERVIEW),
            ],
        )
        result = gen.generate(schema, mpr_path)
        assert result.total_created == 3


class TestPageWidgets:
    def test_create_page_has_widgets(self, mock_sdk: MockSDKClient, mpr_path: Path):
        gen = PageGenerator(sdk_client=mock_sdk)
        entity = _entity(n_attrs=4)
        schema = _schema(entities=[entity], pages=[_page()])
        gen.generate(schema, mpr_path)
        widgets = mock_sdk.created_pages[0]["widgets"]
        assert len(widgets) >= 3  # at least some widgets

    def test_create_page_widget_types(self, mock_sdk: MockSDKClient, mpr_path: Path):
        entity = EntitySchema(
            name="E", module="M",
            attributes=[
                AttributeSchema(name="S", mendix_type=MendixDataType.STRING, label="S"),
                AttributeSchema(name="B", mendix_type=MendixDataType.BOOLEAN, label="B"),
                AttributeSchema(name="D", mendix_type=MendixDataType.DATETIME, label="D"),
                AttributeSchema(name="En", mendix_type=MendixDataType.ENUMERATION, label="En"),
            ],
        )
        gen = PageGenerator(sdk_client=mock_sdk)
        schema = _schema(
            entities=[entity],
            pages=[_page(name="E_Create", entity="E", module="M")],
        )
        gen.generate(schema, mpr_path)
        widgets = {w["attribute"]: w["widget_type"] for w in mock_sdk.created_pages[0]["widgets"]}
        assert widgets["S"] == "TextBox"
        assert widgets["B"] == "CheckBox"
        assert widgets["D"] == "DatePicker"
        assert widgets["En"] == "DropDown"

    def test_overview_page_has_grid_columns(self, mock_sdk: MockSDKClient, mpr_path: Path):
        gen = PageGenerator(sdk_client=mock_sdk)
        entity = _entity(n_attrs=3)
        schema = _schema(
            entities=[entity],
            pages=[_page(name="E_Overview", page_type=PageType.OVERVIEW)],
        )
        gen.generate(schema, mpr_path)
        widgets = mock_sdk.created_pages[0]["widgets"]
        grid_cols = [w for w in widgets if w["widget_type"] == "DataGridColumn"]
        search_fields = [w for w in widgets if w["widget_type"] == "SearchField"]
        assert len(grid_cols) >= 1
        assert all(w["editable"] is False for w in grid_cols)
        # Overview pages now also include SearchField widgets for searchable columns
        assert all(w["widget_type"] in ("DataGridColumn", "SearchField") for w in widgets)

    def test_create_page_widgets_editable(self, mock_sdk: MockSDKClient, mpr_path: Path):
        gen = PageGenerator(sdk_client=mock_sdk)
        entity = _entity(n_attrs=2)
        schema = _schema(entities=[entity], pages=[_page()])
        gen.generate(schema, mpr_path)
        widgets = mock_sdk.created_pages[0]["widgets"]
        assert all(w["editable"] is True for w in widgets)

    def test_autonumber_skipped_on_create(self, mock_sdk: MockSDKClient, mpr_path: Path):
        entity = EntitySchema(
            name="E", module="M",
            attributes=[
                AttributeSchema(name="Id", mendix_type=MendixDataType.AUTONUMBER, label="Id"),
                AttributeSchema(name="Name", mendix_type=MendixDataType.STRING, label="Name"),
            ],
        )
        gen = PageGenerator(sdk_client=mock_sdk)
        schema = _schema(
            entities=[entity],
            pages=[_page(name="E_Create", entity="E", module="M", page_type=PageType.CREATE)],
        )
        gen.generate(schema, mpr_path)
        widgets = mock_sdk.created_pages[0]["widgets"]
        attr_names = [w["attribute"] for w in widgets]
        assert "Id" not in attr_names
        assert "Name" in attr_names

    def test_explicit_widget_type_override(self, mock_sdk: MockSDKClient, mpr_path: Path):
        entity = EntitySchema(
            name="E", module="M",
            attributes=[
                AttributeSchema(
                    name="Desc",
                    mendix_type=MendixDataType.STRING,
                    label="Desc",
                    widget_type=WidgetType.TEXT_AREA,
                ),
            ],
        )
        gen = PageGenerator(sdk_client=mock_sdk)
        schema = _schema(
            entities=[entity],
            pages=[_page(name="E_Create", entity="E", module="M")],
        )
        gen.generate(schema, mpr_path)
        widgets = mock_sdk.created_pages[0]["widgets"]
        assert widgets[0]["widget_type"] == "TextArea"


class TestPageSkipExisting:
    def test_skip_existing_page(
        self, mock_sdk_with_existing: MockSDKClient, mpr_path: Path
    ):
        gen = PageGenerator(sdk_client=mock_sdk_with_existing)
        schema = _schema(
            entities=[_entity()],
            pages=[_page(name="TestEntity_Create")],
        )
        result = gen.generate(schema, mpr_path)
        assert result.total_skipped == 1
        assert result.total_created == 0
        assert len(mock_sdk_with_existing.created_pages) == 0

    def test_dont_skip_when_disabled(
        self, mock_sdk_with_existing: MockSDKClient, mpr_path: Path
    ):
        gen = PageGenerator(sdk_client=mock_sdk_with_existing, skip_existing=False)
        schema = _schema(
            entities=[_entity()],
            pages=[_page(name="TestEntity_Create")],
        )
        result = gen.generate(schema, mpr_path)
        assert result.total_created == 1


class TestPageErrors:
    def test_sdk_error(self, mpr_path: Path):
        sdk = MagicMock()
        sdk.check_artifact_exists.return_value = False
        sdk.create_page.side_effect = SDKClientError("Fail")
        gen = PageGenerator(sdk_client=sdk)
        schema = _schema(entities=[_entity()], pages=[_page()])
        result = gen.generate(schema, mpr_path)
        assert result.total_failed == 1
        assert not result.success

    def test_page_without_entity_no_widgets(self, mock_sdk: MockSDKClient, mpr_path: Path):
        gen = PageGenerator(sdk_client=mock_sdk)
        schema = _schema(
            entities=[],  # No entity
            pages=[_page()],
        )
        gen.generate(schema, mpr_path)
        assert mock_sdk.created_pages[0]["widgets"] == []


class TestPageDecisionLogger:
    def test_logger_called(
        self, mock_sdk: MockSDKClient, mpr_path: Path, decision_logger: DecisionLogger
    ):
        gen = PageGenerator(sdk_client=mock_sdk, decision_logger=decision_logger)
        schema = _schema(entities=[_entity()], pages=[_page()])
        gen.generate(schema, mpr_path, input_hash="h1")
        entries = decision_logger.read_entries()
        assert len(entries) == 1
        assert entries[0].operation == "page_generation"


class TestPageResult:
    def test_repr(self):
        r = PageResult(name="P", module="M", page_type="Create", success=True)
        assert "✓" in repr(r)
        assert "M.P" in repr(r)

    def test_summary(self):
        r = PageGenerationResult(total_created=2, total_skipped=1)
        assert "2 created" in r.summary()


# ═══════════════════════════════════════════════════════════════
# MICROFLOW GENERATOR TESTS
# ═══════════════════════════════════════════════════════════════


class TestMicroflowGeneratorBasic:
    def test_empty_schema(self, mock_sdk: MockSDKClient, mpr_path: Path):
        gen = MicroflowGenerator(sdk_client=mock_sdk)
        result = gen.generate(_schema(), mpr_path)
        assert result.success
        assert result.total_created == 0

    def test_single_validation_microflow(self, mock_sdk: MockSDKClient, mpr_path: Path):
        gen = MicroflowGenerator(sdk_client=mock_sdk)
        schema = _schema(
            entities=[_entity()],
            microflows=[_microflow()],
        )
        result = gen.generate(schema, mpr_path)
        assert result.success
        assert result.total_created == 1
        assert len(mock_sdk.created_microflows) == 1

    def test_microflow_data_sent_to_sdk(self, mock_sdk: MockSDKClient, mpr_path: Path):
        gen = MicroflowGenerator(sdk_client=mock_sdk)
        schema = _schema(
            entities=[_entity()],
            microflows=[_microflow()],
        )
        gen.generate(schema, mpr_path)
        data = mock_sdk.created_microflows[0]
        assert data["name"] == "VAL_TestEntity_Validate"
        assert data["microflow_type"] == "Validation"
        assert data["entity"] == "TestEntity"
        assert data["module"] == "Mod"
        assert "input_parameter" in data
        assert "activities" in data

    def test_multiple_microflows(self, mock_sdk: MockSDKClient, mpr_path: Path):
        gen = MicroflowGenerator(sdk_client=mock_sdk)
        schema = _schema(
            entities=[_entity()],
            microflows=[
                _microflow(name="VAL_E_Validate", mf_type=MicroflowType.VALIDATION),
                _microflow(name="ACT_E_Save", mf_type=MicroflowType.SAVE),
                _microflow(name="ACT_E_Delete", mf_type=MicroflowType.DELETE),
            ],
        )
        result = gen.generate(schema, mpr_path)
        assert result.total_created == 3


class TestMicroflowActivities:
    def test_validation_activities_for_required_fields(
        self, mock_sdk: MockSDKClient, mpr_path: Path
    ):
        entity = EntitySchema(
            name="E", module="M",
            attributes=[
                AttributeSchema(name="Req", mendix_type=MendixDataType.STRING, label="Req", required=True),
                AttributeSchema(name="Opt", mendix_type=MendixDataType.STRING, label="Opt", required=False),
            ],
        )
        gen = MicroflowGenerator(sdk_client=mock_sdk)
        schema = _schema(
            entities=[entity],
            microflows=[_microflow(name="VAL", entity="E", module="M")],
        )
        gen.generate(schema, mpr_path)
        activities = mock_sdk.created_microflows[0]["activities"]
        req_activities = [a for a in activities if a.get("attribute") == "Req"]
        assert len(req_activities) >= 1
        assert any(a["action"] == "validate_required" for a in req_activities)

    def test_validation_includes_custom_validations(
        self, mock_sdk: MockSDKClient, mpr_path: Path
    ):
        entity = EntitySchema(
            name="E", module="M",
            attributes=[
                AttributeSchema(
                    name="F",
                    mendix_type=MendixDataType.STRING,
                    label="F",
                    validations=[
                        ValidationRuleSchema(
                            type=ValidationType.MAX_LENGTH,
                            params={"max": 100},
                            error_message="Too long",
                        ),
                    ],
                ),
            ],
        )
        gen = MicroflowGenerator(sdk_client=mock_sdk)
        schema = _schema(
            entities=[entity],
            microflows=[_microflow(name="VAL", entity="E", module="M")],
        )
        gen.generate(schema, mpr_path)
        activities = mock_sdk.created_microflows[0]["activities"]
        assert any(a["action"] == "validate_max_length" for a in activities)

    def test_save_activities_structure(self, mock_sdk: MockSDKClient, mpr_path: Path):
        gen = MicroflowGenerator(sdk_client=mock_sdk)
        schema = _schema(
            entities=[_entity()],
            microflows=[_microflow(name="ACT_Save", mf_type=MicroflowType.SAVE)],
        )
        gen.generate(schema, mpr_path)
        activities = mock_sdk.created_microflows[0]["activities"]
        types = [a["type"] for a in activities]
        assert "MicroflowCallActivity" in types
        assert "CommitActivity" in types
        assert "ClosePageActivity" in types

    def test_delete_activities_structure(self, mock_sdk: MockSDKClient, mpr_path: Path):
        gen = MicroflowGenerator(sdk_client=mock_sdk)
        schema = _schema(
            entities=[_entity()],
            microflows=[_microflow(name="ACT_Del", mf_type=MicroflowType.DELETE)],
        )
        gen.generate(schema, mpr_path)
        activities = mock_sdk.created_microflows[0]["activities"]
        types = [a["type"] for a in activities]
        assert "ShowMessageActivity" in types
        assert "DeleteActivity" in types
        assert "ClosePageActivity" in types

    def test_custom_microflow_empty_activities(self, mock_sdk: MockSDKClient, mpr_path: Path):
        gen = MicroflowGenerator(sdk_client=mock_sdk)
        schema = _schema(
            entities=[_entity()],
            microflows=[_microflow(name="CUSTOM", mf_type=MicroflowType.CUSTOM)],
        )
        gen.generate(schema, mpr_path)
        assert mock_sdk.created_microflows[0]["activities"] == []

    def test_return_type_validation_is_boolean(self, mock_sdk: MockSDKClient, mpr_path: Path):
        gen = MicroflowGenerator(sdk_client=mock_sdk)
        schema = _schema(
            entities=[_entity()],
            microflows=[_microflow(mf_type=MicroflowType.VALIDATION)],
        )
        gen.generate(schema, mpr_path)
        assert mock_sdk.created_microflows[0]["return_type"] == "Boolean"

    def test_return_type_save_is_void(self, mock_sdk: MockSDKClient, mpr_path: Path):
        gen = MicroflowGenerator(sdk_client=mock_sdk)
        schema = _schema(
            entities=[_entity()],
            microflows=[_microflow(name="ACT", mf_type=MicroflowType.SAVE)],
        )
        gen.generate(schema, mpr_path)
        assert mock_sdk.created_microflows[0]["return_type"] == "Void"

    def test_input_parameter(self, mock_sdk: MockSDKClient, mpr_path: Path):
        gen = MicroflowGenerator(sdk_client=mock_sdk)
        schema = _schema(
            entities=[_entity()],
            microflows=[_microflow()],
        )
        gen.generate(schema, mpr_path)
        param = mock_sdk.created_microflows[0]["input_parameter"]
        assert param["name"] == "TestEntity"
        assert param["entity"] == "Mod.TestEntity"


class TestMicroflowSkipExisting:
    def test_skip_existing(
        self, mock_sdk_with_existing: MockSDKClient, mpr_path: Path
    ):
        gen = MicroflowGenerator(sdk_client=mock_sdk_with_existing)
        schema = _schema(
            entities=[_entity()],
            microflows=[_microflow(name="VAL_TestEntity_Validate")],
        )
        result = gen.generate(schema, mpr_path)
        assert result.total_skipped == 1
        assert len(mock_sdk_with_existing.created_microflows) == 0

    def test_dont_skip_when_disabled(
        self, mock_sdk_with_existing: MockSDKClient, mpr_path: Path
    ):
        gen = MicroflowGenerator(sdk_client=mock_sdk_with_existing, skip_existing=False)
        schema = _schema(
            entities=[_entity()],
            microflows=[_microflow(name="VAL_TestEntity_Validate")],
        )
        result = gen.generate(schema, mpr_path)
        assert result.total_created == 1


class TestMicroflowErrors:
    def test_sdk_error(self, mpr_path: Path):
        sdk = MagicMock()
        sdk.check_artifact_exists.return_value = False
        sdk.create_microflow.side_effect = SDKClientError("Fail")
        gen = MicroflowGenerator(sdk_client=sdk)
        schema = _schema(entities=[_entity()], microflows=[_microflow()])
        result = gen.generate(schema, mpr_path)
        assert result.total_failed == 1
        assert not result.success


class TestMicroflowDecisionLogger:
    def test_logger_called(
        self, mock_sdk: MockSDKClient, mpr_path: Path, decision_logger: DecisionLogger
    ):
        gen = MicroflowGenerator(sdk_client=mock_sdk, decision_logger=decision_logger)
        schema = _schema(entities=[_entity()], microflows=[_microflow()])
        gen.generate(schema, mpr_path, input_hash="h1")
        entries = decision_logger.read_entries()
        assert len(entries) == 1
        assert entries[0].operation == "microflow_generation"


class TestMicroflowResult:
    def test_repr(self):
        r = MicroflowResult(name="MF", module="M", microflow_type="Save", success=True)
        assert "✓" in repr(r)

    def test_summary(self):
        r = MicroflowGenerationResult(total_created=3)
        assert "3 created" in r.summary()
