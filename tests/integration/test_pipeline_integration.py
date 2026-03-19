"""Tests de integración: pipeline completo de generación.

Verifica que el flujo end-to-end funciona correctamente usando
MockSDKClient: parse → dry-run → generate (domain model + pages + microflows).

Fase 13: Implementación completa.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mendex.auditor.engine import AuditEngine, AuditStatus
from mendex.bridge.sdk_client import (
    EntityInfo,
    MockSDKClient,
    ModuleInfo,
    ProjectStructure,
    SecurityInfo,
)
from mendex.generators.domain_model import DomainModelGenerator
from mendex.generators.microflows import MicroflowGenerator
from mendex.generators.pages import PageGenerator
from mendex.logging.decision_logger import BPVerdict, DecisionLogger
from mendex.orchestrator.dry_run import ConflictPolicy, DryRunEngine
from mendex.schema.intermediate import (
    AccessRuleSchema,
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
    mpr = tmp_path / "integration_test.mpr"
    mpr.write_bytes(b"fake-mpr")
    return mpr


@pytest.fixture
def decision_logger(tmp_path: Path) -> DecisionLogger:
    return DecisionLogger(tmp_path / "decisions.jsonl")


@pytest.fixture
def demo_schema() -> IntermediateSchema:
    """Schema completo tipo demo: CRM con Customer y Order."""
    customer = EntitySchema(
        name="Customer",
        module="CRM",
        attributes=[
            AttributeSchema(
                name="FullName",
                mendix_type=MendixDataType.STRING,
                label="Nombre Completo",
                required=True,
                validations=[
                    ValidationRuleSchema(
                        type=ValidationType.MAX_LENGTH,
                        params={"max": 200},
                        error_message="Máximo 200 caracteres",
                    ),
                ],
            ),
            AttributeSchema(
                name="Email",
                mendix_type=MendixDataType.STRING,
                label="Correo Electrónico",
                required=True,
                validations=[
                    ValidationRuleSchema(
                        type=ValidationType.REGEX,
                        params={"pattern": r".+@.+\..+"},
                        error_message="Formato de email inválido",
                    ),
                ],
            ),
            AttributeSchema(
                name="Phone",
                mendix_type=MendixDataType.STRING,
                label="Teléfono",
            ),
            AttributeSchema(
                name="IsActive",
                mendix_type=MendixDataType.BOOLEAN,
                label="Activo",
            ),
            AttributeSchema(
                name="BirthDate",
                mendix_type=MendixDataType.DATETIME,
                label="Fecha de Nacimiento",
            ),
        ],
        access_rules=[
            AccessRuleSchema(role="Admin", can_create=True, can_read=True, can_write=True, can_delete=True),
            AccessRuleSchema(role="User", can_create=True, can_read=True, can_write=True, can_delete=False),
        ],
    )

    order = EntitySchema(
        name="Order",
        module="CRM",
        attributes=[
            AttributeSchema(
                name="OrderNumber",
                mendix_type=MendixDataType.AUTONUMBER,
                label="Número de Orden",
            ),
            AttributeSchema(
                name="OrderDate",
                mendix_type=MendixDataType.DATETIME,
                label="Fecha",
                required=True,
            ),
            AttributeSchema(
                name="TotalAmount",
                mendix_type=MendixDataType.DECIMAL,
                label="Monto Total",
                required=True,
            ),
            AttributeSchema(
                name="Description",
                mendix_type=MendixDataType.STRING,
                label="Descripción",
                widget_type=WidgetType.TEXT_AREA,
            ),
            AttributeSchema(
                name="Status",
                mendix_type=MendixDataType.ENUMERATION,
                label="Estado",
                enum_values=["Draft", "Confirmed", "Shipped", "Delivered"],
            ),
        ],
        access_rules=[
            AccessRuleSchema(role="Admin", can_create=True, can_read=True, can_write=True, can_delete=True),
        ],
    )

    pages = [
        PageSchema(name="Customer_Create", page_type=PageType.CREATE, entity="Customer", module="CRM"),
        PageSchema(name="Customer_Edit", page_type=PageType.EDIT, entity="Customer", module="CRM"),
        PageSchema(name="Customer_Overview", page_type=PageType.OVERVIEW, entity="Customer", module="CRM"),
        PageSchema(name="Order_Create", page_type=PageType.CREATE, entity="Order", module="CRM"),
        PageSchema(name="Order_Overview", page_type=PageType.OVERVIEW, entity="Order", module="CRM"),
    ]

    microflows = [
        MicroflowSchema(
            name="VAL_Customer_Validate",
            microflow_type=MicroflowType.VALIDATION,
            entity="Customer",
            module="CRM",
            logic_description="Valida campos requeridos de Customer",
        ),
        MicroflowSchema(
            name="ACT_Customer_Save",
            microflow_type=MicroflowType.SAVE,
            entity="Customer",
            module="CRM",
            logic_description="Valida y guarda Customer",
        ),
        MicroflowSchema(
            name="ACT_Customer_Delete",
            microflow_type=MicroflowType.DELETE,
            entity="Customer",
            module="CRM",
            logic_description="Confirma y elimina Customer",
        ),
        MicroflowSchema(
            name="VAL_Order_Validate",
            microflow_type=MicroflowType.VALIDATION,
            entity="Order",
            module="CRM",
            logic_description="Valida campos requeridos de Order",
        ),
        MicroflowSchema(
            name="ACT_Order_Save",
            microflow_type=MicroflowType.SAVE,
            entity="Order",
            module="CRM",
            logic_description="Valida y guarda Order",
        ),
    ]

    return IntermediateSchema(
        source=InputSource.EXCEL,
        source_file="fixtures/demo_crm.xlsx",
        entities=[customer, order],
        pages=pages,
        microflows=microflows,
    )


# ═══════════════════════════════════════════════════════════════
# PIPELINE: DRY-RUN → GENERATE
# ═══════════════════════════════════════════════════════════════


class TestFullPipeline:
    """Test del pipeline completo: dry-run → domain model → pages → microflows."""

    def test_full_pipeline_clean_project(
        self, demo_schema: IntermediateSchema, mpr_path: Path, decision_logger: DecisionLogger
    ):
        sdk = MockSDKClient()

        # 1. Dry-run
        engine = DryRunEngine(sdk_client=sdk, decision_logger=decision_logger)
        report = engine.run(schema=demo_schema, mpr_path=mpr_path)

        assert not report.aborted
        assert len(report.artifacts) == 12  # 2 entities + 5 pages + 5 microflows

        # 2. Generate domain model
        dm_gen = DomainModelGenerator(sdk_client=sdk, decision_logger=decision_logger)
        dm_result = dm_gen.generate(demo_schema, mpr_path)
        assert dm_result.success
        assert dm_result.total_created == 2
        assert len(sdk.created_entities) == 2

        # 3. Generate pages
        pg_gen = PageGenerator(sdk_client=sdk, decision_logger=decision_logger)
        pg_result = pg_gen.generate(demo_schema, mpr_path)
        assert pg_result.success
        assert pg_result.total_created == 5
        assert len(sdk.created_pages) == 5

        # 4. Generate microflows
        mf_gen = MicroflowGenerator(sdk_client=sdk, decision_logger=decision_logger)
        mf_result = mf_gen.generate(demo_schema, mpr_path)
        assert mf_result.success
        assert mf_result.total_created == 5
        assert len(sdk.created_microflows) == 5

    def test_pipeline_with_existing_artifacts(
        self, demo_schema: IntermediateSchema, mpr_path: Path, decision_logger: DecisionLogger
    ):
        """Simula proyecto donde algunos artefactos ya existen."""
        sdk = MockSDKClient(
            existing_artifacts={
                "entity:CRM.Customer",
                "page:CRM.Customer_Create",
                "microflow:CRM.VAL_Customer_Validate",
            }
        )

        # Dry-run con skip
        engine = DryRunEngine(sdk_client=sdk, decision_logger=decision_logger)
        report = engine.run(
            schema=demo_schema, mpr_path=mpr_path,
            conflict_policy=ConflictPolicy.SKIP,
        )
        assert not report.aborted
        assert report.total_conflicts == 3

        # Generate — should skip existing
        dm_gen = DomainModelGenerator(sdk_client=sdk, decision_logger=decision_logger)
        dm_result = dm_gen.generate(demo_schema, mpr_path)
        assert dm_result.total_created == 1  # Only Order
        assert dm_result.total_skipped == 1  # Customer skipped

        pg_gen = PageGenerator(sdk_client=sdk, decision_logger=decision_logger)
        pg_result = pg_gen.generate(demo_schema, mpr_path)
        assert pg_result.total_created == 4  # Customer_Create skipped
        assert pg_result.total_skipped == 1

    def test_pipeline_abort_on_conflict(
        self, demo_schema: IntermediateSchema, mpr_path: Path, decision_logger: DecisionLogger
    ):
        """Verifica que --on-conflict=abort detiene el pipeline."""
        sdk = MockSDKClient(
            existing_artifacts={"entity:CRM.Customer"}
        )

        engine = DryRunEngine(sdk_client=sdk, decision_logger=decision_logger)
        report = engine.run(
            schema=demo_schema, mpr_path=mpr_path,
            conflict_policy=ConflictPolicy.ABORT,
        )
        assert report.aborted
        assert "Customer" in report.abort_reason

    def test_pipeline_decision_log_trail(
        self, demo_schema: IntermediateSchema, mpr_path: Path, decision_logger: DecisionLogger
    ):
        """Verifica que toda la cadena genera entradas en el decision log."""
        sdk = MockSDKClient()

        # Run full pipeline
        engine = DryRunEngine(sdk_client=sdk, decision_logger=decision_logger)
        engine.run(schema=demo_schema, mpr_path=mpr_path)

        dm_gen = DomainModelGenerator(sdk_client=sdk, decision_logger=decision_logger)
        dm_gen.generate(demo_schema, mpr_path)

        pg_gen = PageGenerator(sdk_client=sdk, decision_logger=decision_logger)
        pg_gen.generate(demo_schema, mpr_path)

        mf_gen = MicroflowGenerator(sdk_client=sdk, decision_logger=decision_logger)
        mf_gen.generate(demo_schema, mpr_path)

        entries = decision_logger.read_entries()
        operations = [e.operation for e in entries]
        assert "dry_run" in operations
        assert "domain_model_generation" in operations
        assert "page_generation" in operations
        assert "microflow_generation" in operations


# ═══════════════════════════════════════════════════════════════
# PIPELINE: GENERATE → AUDIT
# ═══════════════════════════════════════════════════════════════


class TestGenerateThenAudit:
    """Verifica que después de generar, la auditoría detecta los artefactos."""

    def test_audit_after_generate(
        self, demo_schema: IntermediateSchema, mpr_path: Path, decision_logger: DecisionLogger
    ):
        # Simula un proyecto con lo que acabamos de generar
        structure = ProjectStructure(
            modules=[
                ModuleInfo(
                    name="CRM",
                    entities=[
                        EntityInfo(name="Customer", attributes=["FullName", "Email", "Phone", "IsActive", "BirthDate"]),
                        EntityInfo(name="Order", attributes=["OrderNumber", "OrderDate", "TotalAmount", "Description", "Status"]),
                    ],
                    pages=[
                        "Customer_Create", "Customer_Edit", "Customer_Overview",
                        "Order_Create", "Order_Overview",
                    ],
                    microflows=[
                        "VAL_Customer_Validate", "ACT_Customer_Save", "ACT_Customer_Delete",
                        "VAL_Order_Validate", "ACT_Order_Save",
                    ],
                ),
            ],
            security=SecurityInfo(roles=["Admin", "User"]),
        )

        sdk = MockSDKClient(project_structure=structure)
        engine = AuditEngine(sdk_client=sdk, decision_logger=decision_logger)
        report = engine.audit(mpr_path, include_bp=False)

        # Well-formed artifacts should pass
        assert report.status == AuditStatus.PASS
        assert report.total_critical == 0
        assert len(report.artifacts) == 12

    def test_audit_detects_bad_naming_after_manual_edits(
        self, mpr_path: Path, decision_logger: DecisionLogger
    ):
        """Simula que un developer agregó artefactos con naming incorrecto."""
        structure = ProjectStructure(
            modules=[
                ModuleInfo(
                    name="CRM",
                    entities=[
                        EntityInfo(name="Customer", attributes=["FullName"]),
                        EntityInfo(name="order_item", attributes=["quantity", "price_total"]),
                    ],
                    pages=["Customer_Create", "RandomPage"],
                    microflows=["ACT_Customer_Save", "doSomethingWeird"],
                ),
            ],
        )

        sdk = MockSDKClient(project_structure=structure)
        engine = AuditEngine(sdk_client=sdk, decision_logger=decision_logger)
        report = engine.audit(mpr_path, include_bp=False)

        assert report.total_findings > 0
        # Should detect: snake_case entity, snake_case attrs, bad page naming, bad microflow naming
        rule_ids = {f.rule_id for a in report.artifacts for f in a.findings}
        assert "NM-001" in rule_ids  # entity naming
        assert "NM-002" in rule_ids  # page naming
        assert "NM-003" in rule_ids  # microflow naming


# ═══════════════════════════════════════════════════════════════
# SCHEMA VALIDATION
# ═══════════════════════════════════════════════════════════════


class TestSchemaIntegration:
    """Verifica que IntermediateSchema se serializa/deserializa correctamente."""

    def test_schema_round_trip(self, demo_schema: IntermediateSchema):
        json_str = demo_schema.model_dump_json()
        restored = IntermediateSchema.model_validate_json(json_str)
        assert len(restored.entities) == len(demo_schema.entities)
        assert len(restored.pages) == len(demo_schema.pages)
        assert len(restored.microflows) == len(demo_schema.microflows)

    def test_schema_dict_round_trip(self, demo_schema: IntermediateSchema):
        d = demo_schema.model_dump()
        restored = IntermediateSchema.model_validate(d)
        assert restored.source == demo_schema.source

    def test_entity_attributes_preserved(self, demo_schema: IntermediateSchema):
        json_str = demo_schema.model_dump_json()
        restored = IntermediateSchema.model_validate_json(json_str)
        customer = next(e for e in restored.entities if e.name == "Customer")
        assert len(customer.attributes) == 5
        assert customer.attributes[0].required is True
        assert len(customer.access_rules) == 2

    def test_widget_data_preserved(self, demo_schema: IntermediateSchema):
        d = demo_schema.model_dump()
        restored = IntermediateSchema.model_validate(d)
        order = next(e for e in restored.entities if e.name == "Order")
        desc_attr = next(a for a in order.attributes if a.name == "Description")
        assert desc_attr.widget_type == WidgetType.TEXT_AREA


# ═══════════════════════════════════════════════════════════════
# API INTEGRATION
# ═══════════════════════════════════════════════════════════════


class TestAPIIntegration:
    """Test de integración del servidor FastAPI con pipeline completo."""

    def test_api_preview_then_generate(self, tmp_path: Path):
        from unittest.mock import patch

        from fastapi.testclient import TestClient

        from mendex.config.settings import Settings
        from mendex.server.app import create_app

        settings = Settings(
            decisions_log_path=tmp_path / "decisions.jsonl",
            cache_db_path=tmp_path / "cache.db",
            chroma_db_path=tmp_path / "chroma",
            anthropic_api_key="test",
        )
        app = create_app(settings)
        client = TestClient(app)

        schema_data = {
            "source": "excel",
            "source_file": "demo.xlsx",
            "entities": [
                {
                    "name": "Product",
                    "module": "Inventory",
                    "attributes": [
                        {"name": "Name", "mendix_type": "String", "label": "Name", "required": True},
                        {"name": "Price", "mendix_type": "Decimal", "label": "Price"},
                    ],
                },
            ],
            "pages": [
                {"name": "Product_Create", "page_type": "Create", "entity": "Product", "module": "Inventory"},
            ],
            "microflows": [
                {
                    "name": "VAL_Product_Validate",
                    "microflow_type": "Validation",
                    "entity": "Product",
                    "module": "Inventory",
                    "logic_description": "Validate product",
                },
            ],
        }

        sdk = MockSDKClient()

        # 1. Preview
        with patch("mendex.server.routes.generate._get_sdk_client", return_value=sdk):
            resp = client.post("/api/v1/preview", json={
                "schema_data": schema_data,
                "mpr_path": "/tmp/test.mpr",
            })
        assert resp.status_code == 200
        preview = resp.json()
        assert preview["status"] == "dry_run_complete"
        assert preview["summary"]["total"] == 3

        # 2. Generate
        with patch("mendex.server.routes.generate._get_sdk_client", return_value=sdk):
            resp = client.post("/api/v1/generate", json={
                "schema_data": schema_data,
                "mpr_path": "/tmp/test.mpr",
                "skip_preview": True,
            })
        assert resp.status_code == 200
        gen = resp.json()
        assert gen["status"] in ("completed", "completed_with_errors")
        assert gen["domain_model"]["total_created"] == 1
        assert gen["pages"]["total_created"] == 1
        assert gen["microflows"]["total_created"] == 1

    def test_api_audit_integration(self, tmp_path: Path):
        from unittest.mock import patch

        from fastapi.testclient import TestClient

        from mendex.config.settings import Settings
        from mendex.server.app import create_app

        settings = Settings(
            decisions_log_path=tmp_path / "decisions.jsonl",
            cache_db_path=tmp_path / "cache.db",
            chroma_db_path=tmp_path / "chroma",
            anthropic_api_key="test",
        )
        app = create_app(settings)
        client = TestClient(app)

        structure = ProjectStructure(
            modules=[
                ModuleInfo(
                    name="CRM",
                    entities=[EntityInfo(name="Customer", attributes=["Name"])],
                    pages=["Customer_Create"],
                    microflows=["ACT_Customer_Save"],
                ),
            ],
        )
        sdk = MockSDKClient(project_structure=structure)

        with patch("mendex.server.routes.audit._get_sdk_client", return_value=sdk):
            resp = client.post("/api/v1/audit", json={
                "mpr_path": "/tmp/test.mpr",
                "include_bp": False,
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "pass"
        assert data["summary"]["total_artifacts"] == 3
