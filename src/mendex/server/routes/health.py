"""Ruta de health check.

GET /health — Estado del servidor y SDK Bridge

Fase 11: Implementación completa.
"""

from __future__ import annotations

from pathlib import Path

import structlog
from fastapi import APIRouter, Request

from mendex.bridge.sdk_client import SubprocessSDKClient
from mendex.server.schemas.requests import HealthResponse

logger = structlog.get_logger(__name__)
router = APIRouter()


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check del servidor",
)
async def health(request: Request) -> HealthResponse:
    """Verifica el estado del servidor y el SDK Bridge."""
    sdk_status = "not_configured"
    node_script = Path("mendix_sdk/dist/index.js")
    if node_script.exists():
        sdk = SubprocessSDKClient(node_script=node_script)
        try:
            if sdk.ping():
                sdk_status = "ok"
            else:
                sdk_status = "unreachable"
        except Exception:
            sdk_status = "error"
        finally:
            sdk.close()
    return HealthResponse(sdk_bridge=sdk_status)
