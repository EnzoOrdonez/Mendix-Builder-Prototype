"""Tests para el generador de Domain Model via Model SDK.

Fase 8: Tests unitarios completos.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mendex.bridge.sdk_client import MockSDKClient, SDKClientError
from mendex.generators.domain_model import (
    DomainModelGenerator,
    EntityResult,
    GenerationResult,
)
from mendex.logging.decision_logger import DecisionLogger
from mendex.schema.intermediate import (
    AccessRuleSchema,
    AttributeSchema,
    EntitySchema,
    InputSource,
    IntermediateSchema,
    MendixDataType,
    ValidationRuleSchema,
    ValidationType,
)


# ─── Fixtures ────────────────────────────────────────────────


@pytest.fixture
def mpr_path(tmp_path: Path) -> Path:
    mpr = tmp_path / "test_project.mpr"
    mpr.write_bytes(b"fake mpr content")
    return mpr


@pytest.fixture
def mock_sdk() -> MockSDKClient:
    return MockSDKClient()


@pytest.fixture
def mock_sdk_with_existing() -> MockSDKClient:
    return MockSDKClient(
        existing_artifacts={"entity:Operaciones.OrdenCompra"}
    )


@pytest.fixture
def decision_logger(tmp_path: Path) -> DecisionLogger:
    return DecisionLogger(tmp_path / "decisions.jsonl")


def _make_entity(
    name: str = "OrdenCompra",
    module: str = "Operaciones",
    n_attrs: int = 3,
    with_access_rules: bool = False,
) -> EntitySchema:
    attrs = [
        AttributeSchema(
            name=f"Campo{i}",
            mendix_type=MendixDataType.STRING,
            label=f"Campo {i}",
        )
        for i in range(1, n_attrs + 1)
    ]
    rules = []
    if with_access_rules:
        rules = [
            AccessRuleSchema(role="Admin", can_create=True, can_read=True, can_write=True),
            AccessRuleSchema(role="User", can_read=True),
        ]
    return EntitySchema(name=name, module=module, attributes=attrs, access_rules=rules)


def _make_schema(
    entities: list[EntitySchema] | None = None,
) -> IntermediateSchema:
    return IntermediateSchema(
        source=InputSource.EXCEL,
        source_file="test.xlsx",
        entities=entities or [],
    )


# ─── Tests: GenerationResult ────────────────────────────────


class TestGenerationResult:
    def test_empty_result(self):
        result = GenerationResult()
        assert result.success
        assert result.total_created == 0
        assert result.total_failed == 0

    def test_success_with_entities(self):
        result = GenerationResult(
            total_created=3,
            entities=[
                EntityResult(name="E1", module="M", success=True, attributes_created=5),
                EntityResult(name="E2", module="M", success=True, attributes_created=3),
                EntityResult(name="E3", module="M", success=True, attributes_created=2),
            ],
        )
        assert result.success
        assert result.total_created == 3

    def test_failure_marks_not_success(self):
        result = GenerationResult(total_failed=1)
        assert not result.success

    def test_rollback_marks_not_success(self):
        result = GenerationResult(rollback_triggered=True)
        assert not result.success

    def test_summary_text(self):
        result = GenerationResult(total_created=2, total_skipped=1)
        text = result.summary()
        assert "2 created" in text
        assert "1 skipped" in text


class TestEntityResult:
    def test_repr_success(self):
        r = EntityResult(name="E", module="M", success=True, attributes_created=5)
        assert "✓" in repr(r)
        assert "M.E" in repr(r)

    def test_repr_failure(self):
        r = EntityResult(name="E", module="M", success=False)
        assert "✗" in repr(r)


# ─── Tests: Generate basic ───────────────────────────────────


class TestDomainModelGeneratorBasic:
    def test_empty_schema(self, mock_sdk: MockSDKClient, mpr_path: Path):
        gen = DomainModelGenerator(sdk_client=mock_sdk)
        result = gen.generate(_make_schema(), mpr_path)
        assert result.success
        assert result.total_created == 0
        assert len(mock_sdk.created_entities) == 0

    def test_single_entity(self, mock_sdk: MockSDKClient, mpr_path: Path):
        gen = DomainModelGenerator(sdk_client=mock_sdk)
        schema = _make_schema([_make_entity()])
        result = gen.generate(schema, mpr_path)
        assert result.success
        assert result.total_created == 1
        assert len(mock_sdk.created_entities) == 1
        assert mock_sdk.created_entities[0]["name"] == "OrdenCompra"
        assert mock_sdk.created_entities[0]["module"] == "Operaciones"

    def test_multiple_entities(self, mock_sdk: MockSDKClient, mpr_path: Path):
        gen = DomainModelGenerator(sdk_client=mock_sdk)
        schema = _make_schema([
            _make_entity(name="E1"),
            _make_entity(name="E2"),
            _make_entity(name="E3"),
        ])
        result = gen.generate(schema, mpr_path)
        assert result.success
        assert result.total_created == 3
        assert len(mock_sdk.created_entities) == 3

    def test_entity_with_attributes(self, mock_sdk: MockSDKClient, mpr_path: Path):
        gen = DomainModelGenerator(sdk_client=mock_sdk)
        entity = _make_entity(n_attrs=5)
        schema = _make_schema([entity])
        result = gen.generate(schema, mpr_path)
        assert result.entities[0].attributes_created == 5
        # Verify SDK received correct attribute data
        sdk_data = mock_sdk.created_entities[0]
        assert len(sdk_data["attributes"]) == 5
        assert sdk_data["attributes"][0]["name"] == "Campo1"
        assert sdk_data["attributes"][0]["mendix_type"] == "String"

    def test_entity_with_access_rules(self, mock_sdk: MockSDKClient, mpr_path: Path):
        gen = DomainModelGenerator(sdk_client=mock_sdk)
        entity = _make_entity(with_access_rules=True)
        schema = _make_schema([entity])
        result = gen.generate(schema, mpr_path)
        assert result.entities[0].access_rules_created == 2
        sdk_data = mock_sdk.created_entities[0]
        assert len(sdk_data["access_rules"]) == 2
        assert sdk_data["access_rules"][0]["role"] == "Admin"
        assert sdk_data["access_rules"][0]["can_write"] is True
        assert sdk_data["access_rules"][1]["role"] == "User"
        assert sdk_data["access_rules"][1]["can_write"] is False

    def test_entity_persistable_flag(self, mock_sdk: MockSDKClient, mpr_path: Path):
        gen = DomainModelGenerator(sdk_client=mock_sdk)
        entity = _make_entity()
        entity.is_persistable = False
        schema = _make_schema([entity])
        gen.generate(schema, mpr_path)
        assert mock_sdk.created_entities[0]["is_persistable"] is False


# ─── Tests: Skip existing ───────────────────────────────────


class TestDomainModelSkipExisting:
    def test_skip_existing_entity(
        self, mock_sdk_with_existing: MockSDKClient, mpr_path: Path
    ):
        gen = DomainModelGenerator(
            sdk_client=mock_sdk_with_existing, skip_existing=True
        )
        schema = _make_schema([_make_entity(name="OrdenCompra")])
        result = gen.generate(schema, mpr_path)
        assert result.total_created == 0
        assert result.total_skipped == 1
        assert len(mock_sdk_with_existing.created_entities) == 0

    def test_dont_skip_when_disabled(
        self, mock_sdk_with_existing: MockSDKClient, mpr_path: Path
    ):
        gen = DomainModelGenerator(
            sdk_client=mock_sdk_with_existing, skip_existing=False
        )
        schema = _make_schema([_make_entity(name="OrdenCompra")])
        result = gen.generate(schema, mpr_path)
        assert result.total_created == 1
        assert len(mock_sdk_with_existing.created_entities) == 1

    def test_mix_existing_and_new(
        self, mock_sdk_with_existing: MockSDKClient, mpr_path: Path
    ):
        gen = DomainModelGenerator(
            sdk_client=mock_sdk_with_existing, skip_existing=True
        )
        schema = _make_schema([
            _make_entity(name="OrdenCompra"),  # exists
            _make_entity(name="NuevaEntidad"),  # new
        ])
        result = gen.generate(schema, mpr_path)
        assert result.total_created == 1
        assert result.total_skipped == 1
        assert len(mock_sdk_with_existing.created_entities) == 1
        assert mock_sdk_with_existing.created_entities[0]["name"] == "NuevaEntidad"


# ─── Tests: SDK errors ──────────────────────────────────────


class TestDomainModelSDKErrors:
    def test_sdk_create_error(self, mpr_path: Path):
        sdk = MagicMock()
        sdk.check_artifact_exists.return_value = False
        sdk.create_entity.side_effect = SDKClientError("Connection failed")
        gen = DomainModelGenerator(sdk_client=sdk, skip_existing=True)
        schema = _make_schema([_make_entity()])
        result = gen.generate(schema, mpr_path)
        assert result.total_failed == 1
        assert not result.success
        assert result.entities[0].success is False
        assert "Connection failed" in result.entities[0].error

    def test_sdk_check_exists_error_proceeds(self, mpr_path: Path):
        """If check_artifact_exists fails, proceed with creation."""
        sdk = MagicMock()
        sdk.check_artifact_exists.side_effect = SDKClientError("Check failed")
        sdk.create_entity.return_value = {"status": "created", "name": "E"}
        gen = DomainModelGenerator(sdk_client=sdk, skip_existing=True)
        schema = _make_schema([_make_entity()])
        result = gen.generate(schema, mpr_path)
        # Should still try to create
        assert sdk.create_entity.called
        assert result.total_created == 1

    def test_partial_failure(self, mpr_path: Path):
        """One entity fails, another succeeds."""
        sdk = MagicMock()
        sdk.check_artifact_exists.return_value = False
        sdk.create_entity.side_effect = [
            {"status": "created", "name": "E1"},
            SDKClientError("Failed for E2"),
        ]
        gen = DomainModelGenerator(sdk_client=sdk, skip_existing=True)
        schema = _make_schema([
            _make_entity(name="E1"),
            _make_entity(name="E2"),
        ])
        result = gen.generate(schema, mpr_path)
        assert result.total_created == 1
        assert result.total_failed == 1
        assert result.entities[0].success
        assert not result.entities[1].success


# ─── Tests: Generate approved ────────────────────────────────


class TestDomainModelGenerateApproved:
    def test_only_approved_created(self, mock_sdk: MockSDKClient, mpr_path: Path):
        gen = DomainModelGenerator(sdk_client=mock_sdk)
        schema = _make_schema([
            _make_entity(name="Aprobada1"),
            _make_entity(name="NoAprobada"),
            _make_entity(name="Aprobada2"),
        ])
        result = gen.generate_approved(
            schema, mpr_path, approved_entities=["Aprobada1", "Aprobada2"]
        )
        assert result.total_created == 2
        names = [e["name"] for e in mock_sdk.created_entities]
        assert "Aprobada1" in names
        assert "Aprobada2" in names
        assert "NoAprobada" not in names

    def test_empty_approved_list(self, mock_sdk: MockSDKClient, mpr_path: Path):
        gen = DomainModelGenerator(sdk_client=mock_sdk)
        schema = _make_schema([_make_entity()])
        result = gen.generate_approved(schema, mpr_path, approved_entities=[])
        assert result.total_created == 0


# ─── Tests: Generate single ─────────────────────────────────


class TestDomainModelGenerateSingle:
    def test_single_success(self, mock_sdk: MockSDKClient, mpr_path: Path):
        gen = DomainModelGenerator(sdk_client=mock_sdk)
        entity = _make_entity(n_attrs=4)
        result = gen.generate_single(entity, mpr_path)
        assert result.success
        assert result.name == "OrdenCompra"
        assert result.attributes_created == 4

    def test_single_failure(self, mpr_path: Path):
        sdk = MagicMock()
        sdk.check_artifact_exists.return_value = False
        sdk.create_entity.side_effect = SDKClientError("Fail")
        gen = DomainModelGenerator(sdk_client=sdk)
        result = gen.generate_single(_make_entity(), mpr_path)
        assert not result.success


# ─── Tests: Attribute data serialization ─────────────────────


class TestAttributeSerialization:
    def test_attribute_types_serialized(self, mock_sdk: MockSDKClient, mpr_path: Path):
        entity = EntitySchema(
            name="Test",
            module="Mod",
            attributes=[
                AttributeSchema(name="A1", mendix_type=MendixDataType.STRING, label="A1"),
                AttributeSchema(name="A2", mendix_type=MendixDataType.INTEGER, label="A2"),
                AttributeSchema(name="A3", mendix_type=MendixDataType.DECIMAL, label="A3"),
                AttributeSchema(name="A4", mendix_type=MendixDataType.BOOLEAN, label="A4"),
                AttributeSchema(name="A5", mendix_type=MendixDataType.DATETIME, label="A5"),
                AttributeSchema(
                    name="A6",
                    mendix_type=MendixDataType.ENUMERATION,
                    label="A6",
                    enum_values=["X", "Y", "Z"],
                ),
            ],
        )
        gen = DomainModelGenerator(sdk_client=mock_sdk)
        gen.generate_single(entity, mpr_path)
        attrs = mock_sdk.created_entities[0]["attributes"]
        assert attrs[0]["mendix_type"] == "String"
        assert attrs[1]["mendix_type"] == "Integer"
        assert attrs[2]["mendix_type"] == "Decimal"
        assert attrs[3]["mendix_type"] == "Boolean"
        assert attrs[4]["mendix_type"] == "DateTime"
        assert attrs[5]["mendix_type"] == "Enumeration"
        assert attrs[5]["enum_values"] == ["X", "Y", "Z"]

    def test_validations_serialized(self, mock_sdk: MockSDKClient, mpr_path: Path):
        entity = EntitySchema(
            name="Test",
            module="Mod",
            attributes=[
                AttributeSchema(
                    name="Nombre",
                    mendix_type=MendixDataType.STRING,
                    label="Nombre",
                    required=True,
                    validations=[
                        ValidationRuleSchema(
                            type=ValidationType.MAX_LENGTH,
                            params={"max": 100},
                            error_message="Max 100 chars",
                        ),
                    ],
                ),
            ],
        )
        gen = DomainModelGenerator(sdk_client=mock_sdk)
        gen.generate_single(entity, mpr_path)
        attr = mock_sdk.created_entities[0]["attributes"][0]
        assert attr["required"] is True
        assert len(attr["validations"]) == 1
        assert attr["validations"][0]["type"] == "max_length"
        assert attr["validations"][0]["params"]["max"] == 100

    def test_default_value_serialized(self, mock_sdk: MockSDKClient, mpr_path: Path):
        entity = EntitySchema(
            name="Test",
            module="Mod",
            attributes=[
                AttributeSchema(
                    name="Status",
                    mendix_type=MendixDataType.STRING,
                    label="Status",
                    default_value="active",
                ),
            ],
        )
        gen = DomainModelGenerator(sdk_client=mock_sdk)
        gen.generate_single(entity, mpr_path)
        attr = mock_sdk.created_entities[0]["attributes"][0]
        assert attr["default_value"] == "active"

    def test_no_default_value_omitted(self, mock_sdk: MockSDKClient, mpr_path: Path):
        entity = EntitySchema(
            name="Test",
            module="Mod",
            attributes=[
                AttributeSchema(
                    name="Campo",
                    mendix_type=MendixDataType.STRING,
                    label="Campo",
                ),
            ],
        )
        gen = DomainModelGenerator(sdk_client=mock_sdk)
        gen.generate_single(entity, mpr_path)
        attr = mock_sdk.created_entities[0]["attributes"][0]
        assert "default_value" not in attr


# ─── Tests: Decision logger ─────────────────────────────────


class TestDomainModelDecisionLogger:
    def test_logger_on_success(
        self, mock_sdk: MockSDKClient, mpr_path: Path, decision_logger: DecisionLogger
    ):
        gen = DomainModelGenerator(
            sdk_client=mock_sdk, decision_logger=decision_logger
        )
        gen.generate(_make_schema([_make_entity()]), mpr_path, input_hash="abc")
        entries = decision_logger.read_entries()
        assert len(entries) == 1
        assert entries[0].operation == "domain_model_generation"
        assert entries[0].action_taken == "generated"
        assert entries[0].input_hash == "abc"
        assert entries[0].extra["total_created"] == 1

    def test_logger_on_failure(
        self, mpr_path: Path, decision_logger: DecisionLogger
    ):
        sdk = MagicMock()
        sdk.check_artifact_exists.return_value = False
        sdk.create_entity.side_effect = SDKClientError("Fail")
        gen = DomainModelGenerator(
            sdk_client=sdk, decision_logger=decision_logger
        )
        gen.generate(_make_schema([_make_entity()]), mpr_path)
        entries = decision_logger.read_entries()
        assert entries[0].action_taken == "failed"

    def test_no_logger_no_error(self, mock_sdk: MockSDKClient, mpr_path: Path):
        gen = DomainModelGenerator(sdk_client=mock_sdk)
        result = gen.generate(_make_schema([_make_entity()]), mpr_path)
        assert result.success


# ─── Tests: MockSDKClient enhancements ──────────────────────


class TestMockSDKClientCreate:
    """Tests for the enhanced MockSDKClient with creation tracking."""

    def test_create_entity_registers_as_existing(self):
        sdk = MockSDKClient()
        mpr = Path("test.mpr")
        sdk.create_entity(mpr, {"name": "E1", "module": "M"})
        assert sdk.check_artifact_exists(mpr, "entity", "M", "E1")

    def test_create_entity_tracked(self):
        sdk = MockSDKClient()
        sdk.create_entity(Path("t.mpr"), {"name": "E", "module": "M", "attributes": [1, 2]})
        assert len(sdk.created_entities) == 1
        assert sdk.created_entities[0]["name"] == "E"

    def test_create_page_tracked(self):
        sdk = MockSDKClient()
        sdk.create_page(Path("t.mpr"), {"name": "P", "module": "M"})
        assert len(sdk.created_pages) == 1

    def test_create_microflow_tracked(self):
        sdk = MockSDKClient()
        sdk.create_microflow(Path("t.mpr"), {"name": "MF", "module": "M"})
        assert len(sdk.created_microflows) == 1
