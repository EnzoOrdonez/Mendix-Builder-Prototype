"""Ruta de auditoría de buenas prácticas.

POST /api/v1/audit — Audita un proyecto Mendix existente

Fase 11: Implementación completa.
"""

from __future__ import annotations

from pathlib import Path

import structlog
from fastapi import APIRouter, HTTPException, Request

from mendex.auditor.engine import AuditEngine
from mendex.bridge.sdk_client import MockSDKClient, SDKClient, SDKClientError, SubprocessSDKClient
from mendex.logging.decision_logger import DecisionLogger
from mendex.server.schemas.requests import AuditRequest, AuditResponse

logger = structlog.get_logger(__name__)
router = APIRouter()


def _get_sdk_client(request: Request) -> SDKClient:
    """Obtiene el SDKClient desde la configuración."""
    node_script = Path("mendix_sdk/dist/index.js")
    if node_script.exists():
        return SubprocessSDKClient(node_script=node_script)
    return MockSDKClient()


@router.post(
    "/audit",
    response_model=AuditResponse,
    summary="Audita un proyecto Mendix contra buenas prácticas",
    description=(
        "Lee un .mpr existente y evalúa cada artefacto (entidad, página, microflow) "
        "contra reglas deterministas y BP oficiales de Mendix."
    ),
)
async def audit(body: AuditRequest, request: Request) -> AuditResponse:
    """Audita un proyecto .mpr existente."""
    settings = request.app.state.settings
    decision_logger = DecisionLogger(settings.decisions_log_path)

    sdk = _get_sdk_client(request)
    try:
        engine = AuditEngine(
            sdk_client=sdk,
            decision_logger=decision_logger,
        )
        report = engine.audit(
            mpr_path=Path(body.mpr_path),
            include_bp=body.include_bp,
        )
    except SDKClientError as e:
        raise HTTPException(status_code=502, detail=f"SDK Bridge error: {e}")
    finally:
        if hasattr(sdk, "close"):
            sdk.close()

    report_dict = report.to_dict()

    text_report = None
    if body.output_format.value == "text":
        text_report = report.as_text_report()

    return AuditResponse(
        status=report_dict["status"],
        mpr_path=report_dict["mpr_path"],
        scan_error=report_dict.get("scan_error"),
        artifacts=report_dict["artifacts"],
        summary=report_dict["summary"],
        generated_at=report_dict["generated_at"],
        text_report=text_report,
    )
