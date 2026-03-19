"""CLI principal del agente MendixFormAgent.

Usa Typer para definir comandos y flags.
Fase 0: Solo stub con --help funcional. Se completa en Fase 12.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Annotated, Optional

import typer

app = typer.Typer(
    name="mendex",
    help="MendixFormAgent — Agente de IA para automatizar generación de formularios en Mendix.",
    no_args_is_help=True,
)


class ConflictPolicy(str, Enum):
    SKIP = "skip"
    OVERWRITE = "overwrite"
    ABORT = "abort"


class OutputFormat(str, Enum):
    JSON = "json"
    TEXT = "text"


@app.command()
def generate(
    input: Annotated[str, typer.Option("--input", "-i", help="Path al .xlsx o URL de frame Figma")],
    mpr: Annotated[Path, typer.Option("--mpr", "-m", help="Path al archivo .mpr destino")],
    on_conflict: Annotated[
        ConflictPolicy, typer.Option("--on-conflict", help="Política de colisión")
    ] = ConflictPolicy.SKIP,
    strict: Annotated[bool, typer.Option("--strict", help="Abortar si hay NO_CONFORME")] = False,
    no_confirm: Annotated[
        bool, typer.Option("--no-confirm", help="Omitir confirmación de dry-run")
    ] = False,
    no_cache: Annotated[bool, typer.Option("--no-cache", help="No usar caché LLM")] = False,
) -> None:
    """Genera formularios Mendix desde Excel o Figma."""
    typer.echo(f"[mendex] generate: input={input}, mpr={mpr}")
    typer.echo("[mendex] TODO: Implementar en fases 6-9")
    raise typer.Exit(0)


@app.command()
def audit(
    mpr: Annotated[Path, typer.Option("--mpr", "-m", help="Path al archivo .mpr a auditar")],
    strict: Annotated[bool, typer.Option("--strict", help="Abortar si hay NO_CONFORME")] = False,
    output: Annotated[
        OutputFormat, typer.Option("--output", "-o", help="Formato de salida")
    ] = OutputFormat.TEXT,
) -> None:
    """Audita un proyecto Mendix contra buenas prácticas oficiales."""
    typer.echo(f"[mendex] audit: mpr={mpr}")
    typer.echo("[mendex] TODO: Implementar en fase 10")
    raise typer.Exit(0)


@app.command(name="refresh-conventions")
def refresh_conventions(
    mpr: Annotated[
        Path, typer.Option("--mpr", "-m", help="Path al .mpr del proyecto de referencia")
    ],
    project_name: Annotated[
        str, typer.Option("--project-name", help="Nombre del proyecto de referencia")
    ] = "COPEINCA",
    mendix_version: Annotated[
        str, typer.Option("--mendix-version", help="Versión de Mendix del proyecto")
    ] = "10.24.16",
) -> None:
    """Re-extrae convenciones del proyecto de referencia."""
    from mendex.bridge.sdk_client import SubprocessSDKClient
    from mendex.config.settings import get_settings
    from mendex.knowledge.conventions_extractor import ConventionsExtractor
    from mendex.logging.decision_logger import DecisionLogger

    settings = get_settings()

    if not mpr.exists():
        typer.echo(f"[mendex] ERROR: El archivo .mpr no existe: {mpr}", err=True)
        raise typer.Exit(1)

    # Inicializar componentes
    decision_logger = DecisionLogger(settings.decisions_log_path)
    sdk_client = SubprocessSDKClient(
        node_script=Path("mendix_sdk/dist/index.js")
    )

    extractor = ConventionsExtractor(
        sdk_client=sdk_client,
        output_path=settings.conventions_path,
        hash_path=settings.conventions_path.parent / ".mpr_hash",
        decision_logger=decision_logger,
        project_name=project_name,
    )

    try:
        result = extractor.extract(mpr, mendix_version=mendix_version)
        typer.echo(result.summary())
    except Exception as e:
        typer.echo(f"[mendex] ERROR: {e}", err=True)
        raise typer.Exit(1)
    finally:
        sdk_client.close()


@app.command()
def serve(
    port: Annotated[int, typer.Option("--port", "-p", help="Puerto del servidor")] = 8000,
    host: Annotated[str, typer.Option("--host", help="Host del servidor")] = "127.0.0.1",
) -> None:
    """Inicia el servidor REST FastAPI (MCP-compatible)."""
    import uvicorn

    from mendex.config.settings import get_settings
    from mendex.server.app import create_app

    settings = get_settings()
    settings.host = host
    settings.port = port

    fastapi_app = create_app(settings)
    typer.echo(f"[mendex] Servidor iniciando en http://{host}:{port}")
    typer.echo("[mendex] Docs: http://{host}:{port}/docs")
    uvicorn.run(fastapi_app, host=host, port=port, log_level="info")


# --- Sub-comandos de cache ---
cache_app = typer.Typer(help="Gestión del caché LLM.")
app.add_typer(cache_app, name="cache")


@cache_app.command()
def stats() -> None:
    """Muestra estadísticas del caché LLM."""
    typer.echo("[mendex] cache stats")
    typer.echo("[mendex] TODO: Implementar en fase 2")
    raise typer.Exit(0)


@cache_app.command()
def clear() -> None:
    """Invalida todo el caché LLM."""
    typer.echo("[mendex] cache clear")
    typer.echo("[mendex] TODO: Implementar en fase 2")
    raise typer.Exit(0)
