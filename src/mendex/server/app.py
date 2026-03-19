"""FastAPI application factory para MendixFormAgent.

Crea la app FastAPI con:
- Rutas REST para generate, preview, audit y health
- Integración MCP via fastapi-mcp (compatible con Mendix 11 Agents Kit)
- Middleware de logging estructurado

Fase 11: Implementación completa.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

import structlog
from fastapi import FastAPI
from fastapi_mcp import FastApiMCP

from mendex.config.settings import Settings, get_settings
from mendex.server.routes.audit import router as audit_router
from mendex.server.routes.generate import router as generate_router
from mendex.server.routes.health import router as health_router

logger = structlog.get_logger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Crea y configura la aplicación FastAPI.

    Args:
        settings: Configuración. Si None, usa get_settings().

    Returns:
        FastAPI app lista para servir.
    """
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        logger.info(
            "server_starting",
            host=settings.host,
            port=settings.port,
        )
        yield
        logger.info("server_stopping")

    app = FastAPI(
        title="MendixFormAgent API",
        description=(
            "API REST para automatizar generación de formularios en Mendix 10.24. "
            "Compatible con Model Context Protocol (MCP)."
        ),
        version="0.10.0",
        lifespan=lifespan,
    )

    # Store settings in app state for dependency injection
    app.state.settings = settings

    # Register routes
    app.include_router(health_router, tags=["Health"])
    app.include_router(generate_router, prefix="/api/v1", tags=["Generation"])
    app.include_router(audit_router, prefix="/api/v1", tags=["Audit"])

    # MCP integration — exposes API operations as MCP tools
    mcp = FastApiMCP(
        app,
        name="mendex-agent",
        description="MendixFormAgent — AI agent for Mendix form generation",
    )
    # mount_http() is the new API (fastapi-mcp >= 0.4)
    if hasattr(mcp, "mount_http"):
        mcp.mount_http()
    else:
        mcp.mount()  # fallback for older versions

    return app
