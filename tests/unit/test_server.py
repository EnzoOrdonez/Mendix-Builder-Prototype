"""Tests para el servidor REST FastAPI.

Fase 11: Tests unitarios completos.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from mendex.bridge.sdk_client import (
    EntityInfo,
    MockSDKClient,
    ModuleInfo,
    ProjectStructure,
    SecurityInfo,
)
from mendex.config.settings import Settings
from mendex.server.app import create_app


# ─── Fixtures ────────────────────────────────────────────────


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        decisions_log_path=tmp_path / "decisions.jsonl",
        cache_db_path=tmp_path / "cache.db",
        chroma_db_path=tmp_path / "chroma",
        anthropic_api_key="test-key",
    )


@pytest.fixture
def app(settings: Settings):
    return create_app(settings)


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app)


# ─── Shared data ─────────────────────────────────────────────


MINIMAL_SCHEMA = {
    "source": "excel",
    "source_file": "test.xlsx",
    "entities": [
        {
            "name": "Customer",
            "module": "CRM",
            "attributes": [
                {
                    "name": "Name",
                    "mendix_type": "String",
                    "label": "Name",
                    "required": True,
                },
            ],
        },
    ],
    "pages": [
        {
            "name": "Customer_Create",
            "page_type": "Create",
            "entity": "Customer",
            "module": "CRM",
        },
    ],
    "microflows": [
        {
            "name": "VAL_Customer_Validate",
            "microflow_type": "Validation",
            "entity": "Customer",
            "module": "CRM",
            "logic_description": "Validate customer",
        },
    ],
}


# ═══════════════════════════════════════════════════════════════
# HEALTH
# ═══════════════════════════════════════════════════════════════


class TestHealthEndpoint:
    def test_health_returns_ok(self, client: TestClient):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "version" in data

    def test_health_sdk_status(self, client: TestClient):
        response = client.get("/health")
        data = response.json()
        assert "sdk_bridge" in data


# ═══════════════════════════════════════════════════════════════
# PREVIEW
# ═══════════════════════════════════════════════════════════════


class TestPreviewEndpoint:
    @patch("mendex.server.routes.generate._get_sdk_client")
    def test_preview_success(self, mock_get_sdk, client: TestClient):
        mock_get_sdk.return_value = MockSDKClient()
        response = client.post(
            "/api/v1/preview",
            json={
                "schema_data": MINIMAL_SCHEMA,
                "mpr_path": "/tmp/test.mpr",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "dry_run_complete"
        assert "artifacts" in data
        assert "summary" in data

    @patch("mendex.server.routes.generate._get_sdk_client")
    def test_preview_with_strict(self, mock_get_sdk, client: TestClient):
        mock_get_sdk.return_value = MockSDKClient()
        response = client.post(
            "/api/v1/preview",
            json={
                "schema_data": MINIMAL_SCHEMA,
                "mpr_path": "/tmp/test.mpr",
                "strict": True,
            },
        )
        assert response.status_code == 200

    @patch("mendex.server.routes.generate._get_sdk_client")
    def test_preview_has_text_report(self, mock_get_sdk, client: TestClient):
        mock_get_sdk.return_value = MockSDKClient()
        response = client.post(
            "/api/v1/preview",
            json={
                "schema_data": MINIMAL_SCHEMA,
                "mpr_path": "/tmp/test.mpr",
            },
        )
        data = response.json()
        assert data["text_report"] is not None
        assert "Dry-Run Report" in data["text_report"]

    def test_preview_missing_body(self, client: TestClient):
        response = client.post("/api/v1/preview")
        assert response.status_code == 422


# ═══════════════════════════════════════════════════════════════
# GENERATE
# ═══════════════════════════════════════════════════════════════


class TestGenerateEndpoint:
    @patch("mendex.server.routes.generate._get_sdk_client")
    def test_generate_success(self, mock_get_sdk, client: TestClient):
        mock_get_sdk.return_value = MockSDKClient()
        response = client.post(
            "/api/v1/generate",
            json={
                "schema_data": MINIMAL_SCHEMA,
                "mpr_path": "/tmp/test.mpr",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("completed", "completed_with_errors")
        assert data["domain_model"] is not None
        assert data["pages"] is not None
        assert data["microflows"] is not None

    @patch("mendex.server.routes.generate._get_sdk_client")
    def test_generate_skip_preview(self, mock_get_sdk, client: TestClient):
        mock_get_sdk.return_value = MockSDKClient()
        response = client.post(
            "/api/v1/generate",
            json={
                "schema_data": MINIMAL_SCHEMA,
                "mpr_path": "/tmp/test.mpr",
                "skip_preview": True,
            },
        )
        data = response.json()
        assert data["preview"] is None
        assert data["status"] in ("completed", "completed_with_errors")

    @patch("mendex.server.routes.generate._get_sdk_client")
    def test_generate_with_preview(self, mock_get_sdk, client: TestClient):
        mock_get_sdk.return_value = MockSDKClient()
        response = client.post(
            "/api/v1/generate",
            json={
                "schema_data": MINIMAL_SCHEMA,
                "mpr_path": "/tmp/test.mpr",
                "skip_preview": False,
            },
        )
        data = response.json()
        assert data["preview"] is not None

    @patch("mendex.server.routes.generate._get_sdk_client")
    def test_generate_empty_schema(self, mock_get_sdk, client: TestClient):
        mock_get_sdk.return_value = MockSDKClient()
        response = client.post(
            "/api/v1/generate",
            json={
                "schema_data": {
                    "source": "excel",
                    "entities": [],
                },
                "mpr_path": "/tmp/test.mpr",
                "skip_preview": True,
            },
        )
        data = response.json()
        assert data["status"] == "completed"
        assert data["domain_model"] is None

    def test_generate_missing_body(self, client: TestClient):
        response = client.post("/api/v1/generate")
        assert response.status_code == 422


# ═══════════════════════════════════════════════════════════════
# AUDIT
# ═══════════════════════════════════════════════════════════════


class TestAuditEndpoint:
    @patch("mendex.server.routes.audit._get_sdk_client")
    def test_audit_success(self, mock_get_sdk, client: TestClient):
        structure = ProjectStructure(
            modules=[
                ModuleInfo(
                    name="CRM",
                    entities=[
                        EntityInfo(name="Customer", attributes=["Name", "Email"]),
                    ],
                    pages=["Customer_Create"],
                    microflows=["ACT_Customer_Save"],
                ),
            ],
        )
        mock_get_sdk.return_value = MockSDKClient(project_structure=structure)
        response = client.post(
            "/api/v1/audit",
            json={
                "mpr_path": "/tmp/test.mpr",
                "include_bp": False,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("pass", "warn", "fail")
        assert "artifacts" in data
        assert "summary" in data

    @patch("mendex.server.routes.audit._get_sdk_client")
    def test_audit_with_text_format(self, mock_get_sdk, client: TestClient):
        mock_get_sdk.return_value = MockSDKClient(
            project_structure=ProjectStructure(modules=[])
        )
        response = client.post(
            "/api/v1/audit",
            json={
                "mpr_path": "/tmp/test.mpr",
                "include_bp": False,
                "output_format": "text",
            },
        )
        data = response.json()
        assert data["text_report"] is not None
        assert "Audit Report" in data["text_report"]

    @patch("mendex.server.routes.audit._get_sdk_client")
    def test_audit_detects_violations(self, mock_get_sdk, client: TestClient):
        structure = ProjectStructure(
            modules=[
                ModuleInfo(
                    name="My Module",
                    entities=[
                        EntityInfo(name="bad_entity", attributes=["snake_attr"]),
                    ],
                    pages=["randomPage"],
                    microflows=["noPrefix"],
                ),
            ],
        )
        mock_get_sdk.return_value = MockSDKClient(project_structure=structure)
        response = client.post(
            "/api/v1/audit",
            json={
                "mpr_path": "/tmp/test.mpr",
                "include_bp": False,
            },
        )
        data = response.json()
        assert data["summary"]["total_findings"] > 0

    def test_audit_missing_body(self, client: TestClient):
        response = client.post("/api/v1/audit")
        assert response.status_code == 422


# ═══════════════════════════════════════════════════════════════
# APP FACTORY
# ═══════════════════════════════════════════════════════════════


class TestAppFactory:
    def test_create_app(self, settings: Settings):
        app = create_app(settings)
        assert app is not None
        assert app.title == "MendixFormAgent API"

    def test_openapi_schema(self, client: TestClient):
        response = client.get("/openapi.json")
        assert response.status_code == 200
        schema = response.json()
        paths = schema["paths"]
        assert "/health" in paths
        assert "/api/v1/preview" in paths
        assert "/api/v1/generate" in paths
        assert "/api/v1/audit" in paths


# ═══════════════════════════════════════════════════════════════
# SCHEMA MODELS
# ═══════════════════════════════════════════════════════════════


class TestSchemaModels:
    def test_preview_request_validation(self):
        from mendex.server.schemas.requests import PreviewRequest

        req = PreviewRequest(
            schema_data=MINIMAL_SCHEMA,
            mpr_path="/tmp/test.mpr",
        )
        assert req.conflict_policy.value == "skip"
        assert req.strict is False

    def test_health_response_defaults(self):
        from mendex.server.schemas.requests import HealthResponse

        resp = HealthResponse()
        assert resp.status == "ok"
        assert resp.version == "0.10.0"

    def test_error_response(self):
        from mendex.server.schemas.requests import ErrorResponse

        err = ErrorResponse(error="Test", detail="Detail")
        assert err.error == "Test"
