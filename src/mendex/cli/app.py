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
) -> None:
    """Re-extrae convenciones del proyecto de referencia."""
    typer.echo(f"[mendex] refresh-conventions: mpr={mpr}")
    typer.echo("[mendex] TODO: Implementar en fase 3")
    raise typer.Exit(0)


@app.command()
def serve(
    port: Annotated[int, typer.Option("--port", "-p", help="Puerto del servidor")] = 8000,
) -> None:
    """Inicia el servidor REST FastAPI (MCP-compatible)."""
    typer.echo(f"[mendex] serve: port={port}")
    typer.echo("[mendex] TODO: Implementar en fase 11")
    raise typer.Exit(0)


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
