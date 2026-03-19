"""Schemas de request/response para la API REST.

Reusan los modelos Pydantic del IntermediateSchema donde sea posible
y definen wrappers específicos para los endpoints.

Fase 11: Implementación completa.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from mendex.schema.intermediate import IntermediateSchema


# ─── Enums ────────────────────────────────────────────────────


class ConflictPolicyAPI(str, Enum):
    SKIP = "skip"
    OVERWRITE = "overwrite"
    ABORT = "abort"


class OutputFormatAPI(str, Enum):
    JSON = "json"
    TEXT = "text"


# ─── Generate ────────────────────────────────────────────────


class PreviewRequest(BaseModel):
    """Request para preview (dry-run) de generación."""

    schema_data: IntermediateSchema = Field(
        ..., description="IntermediateSchema con entidades, páginas y microflows a generar"
    )
    mpr_path: str = Field(
        ..., description="Path al archivo .mpr destino"
    )
    conflict_policy: ConflictPolicyAPI = Field(
        default=ConflictPolicyAPI.SKIP,
        description="Política ante colisión con artefactos existentes",
    )
    strict: bool = Field(
        default=False,
        description="Si True, aborta si hay algún NO_CONFORME",
    )


class PreviewResponse(BaseModel):
    """Response del preview (dry-run)."""

    status: str
    abort_reason: str | None = None
    conflict_policy: str
    strict_mode: bool
    artifacts: list[dict[str, Any]]
    summary: dict[str, Any]
    generated_at: str
    text_report: str | None = None


class GenerateRequest(BaseModel):
    """Request para ejecutar la generación completa."""

    schema_data: IntermediateSchema = Field(
        ..., description="IntermediateSchema con artefactos a generar"
    )
    mpr_path: str = Field(
        ..., description="Path al archivo .mpr destino"
    )
    conflict_policy: ConflictPolicyAPI = Field(
        default=ConflictPolicyAPI.SKIP,
    )
    strict: bool = False
    skip_preview: bool = Field(
        default=False,
        description="Si True, omite el dry-run previo",
    )


class GenerateResponse(BaseModel):
    """Response de la generación."""

    status: str
    preview: PreviewResponse | None = None
    domain_model: dict[str, Any] | None = None
    pages: dict[str, Any] | None = None
    microflows: dict[str, Any] | None = None
    errors: list[str] = Field(default_factory=list)


# ─── Audit ───────────────────────────────────────────────────


class AuditRequest(BaseModel):
    """Request para auditar un proyecto existente."""

    mpr_path: str = Field(
        ..., description="Path al archivo .mpr a auditar"
    )
    include_bp: bool = Field(
        default=True,
        description="Incluir evaluación contra BP oficiales via LLM",
    )
    output_format: OutputFormatAPI = Field(
        default=OutputFormatAPI.JSON,
    )


class AuditResponse(BaseModel):
    """Response de la auditoría."""

    status: str
    mpr_path: str
    scan_error: str | None = None
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)
    generated_at: str = ""
    text_report: str | None = None


# ─── Health ──────────────────────────────────────────────────


class HealthResponse(BaseModel):
    """Response del health check."""

    status: str = "ok"
    version: str = "0.10.0"
    sdk_bridge: str = "unknown"
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# ─── Errors ──────────────────────────────────────────────────


class ErrorResponse(BaseModel):
    """Response de error estándar."""

    error: str
    detail: str | None = None
