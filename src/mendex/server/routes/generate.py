"""Rutas de generación: preview (dry-run) y generate (ejecución).

POST /api/v1/preview  — Dry-run sin modificar el .mpr
POST /api/v1/generate — Genera artefactos en el .mpr (con dry-run previo)

Fase 11: Implementación completa.
"""

from __future__ import annotations

from pathlib import Path

import structlog
from fastapi import APIRouter, HTTPException, Request

from mendex.bridge.sdk_client import MockSDKClient, SDKClient, SDKClientError, SubprocessSDKClient
from mendex.generators.domain_model import DomainModelGenerator
from mendex.generators.microflows import MicroflowGenerator
from mendex.generators.pages import PageGenerator
from mendex.logging.decision_logger import DecisionLogger
from mendex.orchestrator.dry_run import ConflictPolicy, DryRunEngine
from mendex.server.schemas.requests import (
    GenerateRequest,
    GenerateResponse,
    PreviewRequest,
    PreviewResponse,
)

logger = structlog.get_logger(__name__)
router = APIRouter()


def _get_sdk_client(request: Request) -> SDKClient:
    """Obtiene el SDKClient desde la configuración."""
    settings = request.app.state.settings
    node_script = Path("mendix_sdk/dist/index.js")
    if node_script.exists():
        return SubprocessSDKClient(node_script=node_script)
    return MockSDKClient()


def _map_conflict_policy(policy: str) -> ConflictPolicy:
    return ConflictPolicy(policy)


@router.post(
    "/preview",
    response_model=PreviewResponse,
    summary="Preview (dry-run) de generación",
    description=(
        "Ejecuta un dry-run que muestra qué se va a generar, evalúa BP "
        "y detecta colisiones, sin modificar el .mpr."
    ),
)
async def preview(body: PreviewRequest, request: Request) -> PreviewResponse:
    """Ejecuta dry-run sin modificar el .mpr."""
    settings = request.app.state.settings
    decision_logger = DecisionLogger(settings.decisions_log_path)

    sdk = _get_sdk_client(request)
    try:
        engine = DryRunEngine(
            sdk_client=sdk,
            decision_logger=decision_logger,
        )
        report = engine.run(
            schema=body.schema_data,
            mpr_path=Path(body.mpr_path),
            conflict_policy=_map_conflict_policy(body.conflict_policy.value),
            strict=body.strict,
        )
    except SDKClientError as e:
        raise HTTPException(status_code=502, detail=f"SDK Bridge error: {e}")
    finally:
        if hasattr(sdk, "close"):
            sdk.close()

    report_dict = report.to_dict()
    return PreviewResponse(
        status=report_dict["status"],
        abort_reason=report_dict.get("abort_reason"),
        conflict_policy=report_dict["conflict_policy"],
        strict_mode=report_dict["strict_mode"],
        artifacts=report_dict["artifacts"],
        summary=report_dict["summary"],
        generated_at=report_dict["generated_at"],
        text_report=report.as_text_report(),
    )


@router.post(
    "/generate",
    response_model=GenerateResponse,
    summary="Genera artefactos en el .mpr",
    description=(
        "Genera entidades, páginas y microflows en el .mpr. "
        "Ejecuta un dry-run previo salvo que skip_preview=True."
    ),
)
async def generate(body: GenerateRequest, request: Request) -> GenerateResponse:
    """Genera artefactos completos en el .mpr."""
    settings = request.app.state.settings
    decision_logger = DecisionLogger(settings.decisions_log_path)
    mpr_path = Path(body.mpr_path)

    sdk = _get_sdk_client(request)
    errors: list[str] = []

    try:
        # 1. Preview (dry-run) si no se omite
        preview_response: PreviewResponse | None = None
        if not body.skip_preview:
            engine = DryRunEngine(
                sdk_client=sdk,
                decision_logger=decision_logger,
            )
            report = engine.run(
                schema=body.schema_data,
                mpr_path=mpr_path,
                conflict_policy=_map_conflict_policy(body.conflict_policy.value),
                strict=body.strict,
            )
            report_dict = report.to_dict()
            preview_response = PreviewResponse(
                status=report_dict["status"],
                abort_reason=report_dict.get("abort_reason"),
                conflict_policy=report_dict["conflict_policy"],
                strict_mode=report_dict["strict_mode"],
                artifacts=report_dict["artifacts"],
                summary=report_dict["summary"],
                generated_at=report_dict["generated_at"],
            )

            if report.aborted:
                return GenerateResponse(
                    status="aborted",
                    preview=preview_response,
                    errors=[report.abort_reason],
                )

        # 2. Generate domain model
        dm_result = None
        if body.schema_data.entities:
            dm_gen = DomainModelGenerator(
                sdk_client=sdk,
                decision_logger=decision_logger,
            )
            dm = dm_gen.generate(body.schema_data, mpr_path)
            dm_result = {
                "total_created": dm.total_created,
                "total_skipped": dm.total_skipped,
                "total_failed": dm.total_failed,
                "success": dm.success,
            }
            errors.extend(dm.errors)

        # 3. Generate pages
        pages_result = None
        if body.schema_data.pages:
            page_gen = PageGenerator(
                sdk_client=sdk,
                decision_logger=decision_logger,
            )
            pg = page_gen.generate(body.schema_data, mpr_path)
            pages_result = {
                "total_created": pg.total_created,
                "total_skipped": pg.total_skipped,
                "total_failed": pg.total_failed,
                "success": pg.success,
            }
            errors.extend(pg.errors)

        # 4. Generate microflows
        mf_result = None
        if body.schema_data.microflows:
            mf_gen = MicroflowGenerator(
                sdk_client=sdk,
                decision_logger=decision_logger,
            )
            mf = mf_gen.generate(body.schema_data, mpr_path)
            mf_result = {
                "total_created": mf.total_created,
                "total_skipped": mf.total_skipped,
                "total_failed": mf.total_failed,
                "success": mf.success,
            }
            errors.extend(mf.errors)

        status = "completed" if not errors else "completed_with_errors"

        return GenerateResponse(
            status=status,
            preview=preview_response,
            domain_model=dm_result,
            pages=pages_result,
            microflows=mf_result,
            errors=errors,
        )

    except SDKClientError as e:
        raise HTTPException(status_code=502, detail=f"SDK Bridge error: {e}")
    finally:
        if hasattr(sdk, "close"):
            sdk.close()
