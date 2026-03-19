"""CLI principal del agente MendixFormAgent.

Usa Typer para definir comandos y flags.
Fase 0: Stub con --help funcional.
Fase 12: Implementación completa de todos los comandos.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    name="mendex",
    help="MendixFormAgent — Agente de IA para automatizar generación de formularios en Mendix.",
    no_args_is_help=True,
)

console = Console()
err_console = Console(stderr=True)


class ConflictPolicy(str, Enum):
    SKIP = "skip"
    OVERWRITE = "overwrite"
    ABORT = "abort"


class OutputFormat(str, Enum):
    JSON = "json"
    TEXT = "text"


# ═══════════════════════════════════════════════════════════════
# generate
# ═══════════════════════════════════════════════════════════════


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
    output: Annotated[
        OutputFormat, typer.Option("--output", "-o", help="Formato de salida")
    ] = OutputFormat.TEXT,
    module: Annotated[str, typer.Option("--module", help="Módulo destino en Mendix")] = "Operaciones",
) -> None:
    """Genera formularios Mendix desde Excel o Figma."""
    from mendex.bridge.rollback import RollbackManager, atomic_mpr_operation
    from mendex.bridge.sdk_client import SubprocessSDKClient
    from mendex.config.settings import get_settings
    from mendex.generators.domain_model import DomainModelGenerator
    from mendex.generators.microflows import MicroflowGenerator
    from mendex.generators.pages import PageGenerator
    from mendex.logging.decision_logger import DecisionLogger
    from mendex.orchestrator.dry_run import ConflictPolicy as DRConflict
    from mendex.orchestrator.dry_run import DryRunEngine

    settings = get_settings()

    # Validate inputs
    if not mpr.exists():
        err_console.print(f"[red]ERROR:[/red] El archivo .mpr no existe: {mpr}")
        raise typer.Exit(1)

    # Parse input
    schema = _parse_input(input, module, settings)

    # Init components
    decision_logger = DecisionLogger(settings.decisions_log_path)
    sdk_client = SubprocessSDKClient(node_script=Path("mendix_sdk/dist/index.js"))

    try:
        # 1. Dry-run
        conflict_map = {
            ConflictPolicy.SKIP: DRConflict.SKIP,
            ConflictPolicy.OVERWRITE: DRConflict.OVERWRITE,
            ConflictPolicy.ABORT: DRConflict.ABORT,
        }
        engine = DryRunEngine(
            sdk_client=sdk_client,
            decision_logger=decision_logger,
        )
        report = engine.run(
            schema=schema,
            mpr_path=mpr,
            conflict_policy=conflict_map[on_conflict],
            strict=strict,
        )

        # Show dry-run report
        if output == OutputFormat.JSON:
            console.print_json(report.to_json())
        else:
            console.print(report.as_text_report())

        if report.aborted:
            err_console.print(f"[red]Abortado:[/red] {report.abort_reason}")
            raise typer.Exit(1)

        # Confirm
        if not no_confirm:
            confirm = typer.confirm(
                f"\n¿Ejecutar generación de {len(report.artifacts)} artefactos?"
            )
            if not confirm:
                console.print("[yellow]Cancelado por el usuario.[/yellow]")
                raise typer.Exit(0)

        # 2. Generate with rollback
        console.print("\n[bold]Generando artefactos...[/bold]")

        with atomic_mpr_operation(mpr, max_backups=settings.max_backups) as backup:
            # Domain model
            if schema.entities:
                dm_gen = DomainModelGenerator(
                    sdk_client=sdk_client,
                    decision_logger=decision_logger,
                )
                dm_result = dm_gen.generate(schema, mpr)
                console.print(
                    f"  Entidades: {dm_result.total_created} creadas, "
                    f"{dm_result.total_skipped} omitidas, "
                    f"{dm_result.total_failed} fallidas"
                )

            # Pages
            if schema.pages:
                pg_gen = PageGenerator(
                    sdk_client=sdk_client,
                    decision_logger=decision_logger,
                )
                pg_result = pg_gen.generate(schema, mpr)
                console.print(
                    f"  Páginas: {pg_result.total_created} creadas, "
                    f"{pg_result.total_skipped} omitidas, "
                    f"{pg_result.total_failed} fallidas"
                )

            # Microflows
            if schema.microflows:
                mf_gen = MicroflowGenerator(
                    sdk_client=sdk_client,
                    decision_logger=decision_logger,
                )
                mf_result = mf_gen.generate(schema, mpr)
                console.print(
                    f"  Microflows: {mf_result.total_created} creados, "
                    f"{mf_result.total_skipped} omitidos, "
                    f"{mf_result.total_failed} fallidos"
                )

        console.print("\n[green]Generación completada.[/green]")

    except Exception as e:
        if not isinstance(e, (typer.Exit, SystemExit)):
            err_console.print(f"[red]ERROR:[/red] {e}")
            raise typer.Exit(1)
        raise
    finally:
        sdk_client.close()


def _parse_input(input_path: str, module: str, settings: "Any") -> "Any":
    """Parsea el input (Excel o Figma URL) a IntermediateSchema."""
    from mendex.schema.intermediate import IntermediateSchema

    # Detect Figma URL
    if input_path.startswith("https://www.figma.com/") or input_path.startswith("figma://"):
        from mendex.parsers.figma_extractor import FigmaExtractor

        if not settings.figma_access_token:
            err_console.print(
                "[red]ERROR:[/red] FIGMA_ACCESS_TOKEN no configurado. "
                "Agrégalo al archivo .env"
            )
            raise typer.Exit(1)

        extractor = FigmaExtractor(access_token=settings.figma_access_token)
        return extractor.extract_from_url(url=input_path, module=module)

    # Excel file
    excel_path = Path(input_path)
    if not excel_path.exists():
        err_console.print(f"[red]ERROR:[/red] Archivo no encontrado: {input_path}")
        raise typer.Exit(1)

    from mendex.parsers.excel_parser import ExcelParser

    parser = ExcelParser(default_module=module)
    return parser.parse(excel_path)


# ═══════════════════════════════════════════════════════════════
# audit
# ═══════════════════════════════════════════════════════════════


@app.command()
def audit(
    mpr: Annotated[Path, typer.Option("--mpr", "-m", help="Path al archivo .mpr a auditar")],
    strict: Annotated[bool, typer.Option("--strict", help="Fallar con exit code 1 si hay critical")] = False,
    output: Annotated[
        OutputFormat, typer.Option("--output", "-o", help="Formato de salida")
    ] = OutputFormat.TEXT,
    no_bp: Annotated[
        bool, typer.Option("--no-bp", help="Solo reglas deterministas, sin LLM")
    ] = False,
) -> None:
    """Audita un proyecto Mendix contra buenas prácticas oficiales."""
    from mendex.auditor.engine import AuditEngine, AuditStatus
    from mendex.bridge.sdk_client import SubprocessSDKClient
    from mendex.config.settings import get_settings
    from mendex.logging.decision_logger import DecisionLogger

    settings = get_settings()

    if not mpr.exists():
        err_console.print(f"[red]ERROR:[/red] El archivo .mpr no existe: {mpr}")
        raise typer.Exit(1)

    decision_logger = DecisionLogger(settings.decisions_log_path)
    sdk_client = SubprocessSDKClient(node_script=Path("mendix_sdk/dist/index.js"))

    try:
        engine = AuditEngine(
            sdk_client=sdk_client,
            decision_logger=decision_logger,
        )
        report = engine.audit(mpr_path=mpr, include_bp=not no_bp)

        if output == OutputFormat.JSON:
            console.print_json(report.to_json())
        else:
            console.print(report.as_text_report())

        if strict and report.status == AuditStatus.FAIL:
            raise typer.Exit(1)

    except typer.Exit:
        raise
    except Exception as e:
        err_console.print(f"[red]ERROR:[/red] {e}")
        raise typer.Exit(1)
    finally:
        sdk_client.close()


# ═══════════════════════════════════════════════════════════════
# refresh-conventions
# ═══════════════════════════════════════════════════════════════


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
        err_console.print(f"[red]ERROR:[/red] El archivo .mpr no existe: {mpr}")
        raise typer.Exit(1)

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
        console.print(result.summary())
    except Exception as e:
        err_console.print(f"[red]ERROR:[/red] {e}")
        raise typer.Exit(1)
    finally:
        sdk_client.close()


# ═══════════════════════════════════════════════════════════════
# serve
# ═══════════════════════════════════════════════════════════════


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
    console.print(f"[bold]Servidor iniciando en http://{host}:{port}[/bold]")
    console.print(f"Docs: http://{host}:{port}/docs")
    console.print(f"MCP: http://{host}:{port}/mcp")
    uvicorn.run(fastapi_app, host=host, port=port, log_level="info")


# ═══════════════════════════════════════════════════════════════
# cache subcommands
# ═══════════════════════════════════════════════════════════════

cache_app = typer.Typer(help="Gestión del caché LLM.")
app.add_typer(cache_app, name="cache")


@cache_app.command()
def stats() -> None:
    """Muestra estadísticas del caché LLM."""
    from mendex.config.settings import get_settings
    from mendex.llm.cache import LLMCache

    settings = get_settings()
    cache = LLMCache(settings.cache_db_path, ttl_days=settings.cache_ttl_days)
    cache_stats = cache.stats()

    table = Table(title="Caché LLM — Estadísticas")
    table.add_column("Métrica", style="cyan")
    table.add_column("Valor", style="green")
    table.add_row("Entradas totales", str(cache_stats.total_entries))
    table.add_row("Cache hits", str(cache_stats.hits))
    table.add_row("Cache misses", str(cache_stats.misses))
    table.add_row("Tamaño", f"{cache_stats.size_bytes / 1024:.1f} KB")
    if cache_stats.oldest_entry:
        table.add_row("Entrada más antigua", cache_stats.oldest_entry.isoformat())
    console.print(table)


@cache_app.command()
def clear(
    confirm: Annotated[
        bool, typer.Option("--yes", "-y", help="Confirmar sin preguntar")
    ] = False,
) -> None:
    """Invalida todo el caché LLM."""
    from mendex.config.settings import get_settings
    from mendex.llm.cache import LLMCache

    settings = get_settings()

    if not confirm:
        confirm = typer.confirm("¿Eliminar todo el caché LLM?")
        if not confirm:
            console.print("[yellow]Cancelado.[/yellow]")
            raise typer.Exit(0)

    cache = LLMCache(settings.cache_db_path, ttl_days=settings.cache_ttl_days)
    count = cache.clear()
    console.print(f"[green]Caché eliminado:[/green] {count} entradas borradas")


# ═══════════════════════════════════════════════════════════════
# log subcommands
# ═══════════════════════════════════════════════════════════════

log_app = typer.Typer(help="Gestión del log de decisiones.")
app.add_typer(log_app, name="log")


@log_app.command(name="show")
def log_show(
    last: Annotated[int, typer.Option("--last", "-n", help="Últimas N entradas")] = 10,
    output: Annotated[
        OutputFormat, typer.Option("--output", "-o", help="Formato de salida")
    ] = OutputFormat.TEXT,
) -> None:
    """Muestra las últimas entradas del log de decisiones."""
    import json

    from mendex.config.settings import get_settings
    from mendex.logging.decision_logger import DecisionLogger

    settings = get_settings()
    dl = DecisionLogger(settings.decisions_log_path)
    entries = dl.read_entries(last_n=last)

    if not entries:
        console.print("[dim]Sin entradas en el log.[/dim]")
        return

    if output == OutputFormat.JSON:
        data = [e.model_dump() for e in entries]
        console.print_json(json.dumps(data, indent=2, default=str))
    else:
        table = Table(title=f"Últimas {len(entries)} decisiones")
        table.add_column("Timestamp", style="dim", max_width=20)
        table.add_column("Operación", style="cyan")
        table.add_column("Acción", style="green")
        table.add_column("BP", style="yellow")
        table.add_column("Warnings")
        for e in entries:
            bp = e.bp_verdict.value if e.bp_verdict else "-"
            warns = str(len(e.warnings)) if e.warnings else "-"
            table.add_row(
                e.timestamp[:19],
                e.operation,
                e.action_taken or "-",
                bp,
                warns,
            )
        console.print(table)


@log_app.command(name="tokens")
def log_tokens() -> None:
    """Muestra resumen de consumo de tokens LLM."""
    from mendex.config.settings import get_settings
    from mendex.logging.decision_logger import DecisionLogger

    settings = get_settings()
    dl = DecisionLogger(settings.decisions_log_path)
    summary = dl.compute_token_summary()

    table = Table(title="Consumo de Tokens LLM")
    table.add_column("Métrica", style="cyan")
    table.add_column("Valor", style="green")
    table.add_row("Total tokens", f"{summary['total_tokens']:,}")
    table.add_row("Total llamadas", str(summary['total_calls']))
    table.add_row("Cache hits", str(summary['cache_hits']))
    table.add_row("Cache misses", str(summary['cache_misses']))
    table.add_row("Tokens ahorrados (cache)", f"{summary['tokens_saved_by_cache']:,}")

    if summary['tokens_by_model']:
        table.add_section()
        for model, tokens in summary['tokens_by_model'].items():
            table.add_row(f"  {model}", f"{tokens:,}")

    console.print(table)


@log_app.command(name="clear")
def log_clear(
    confirm: Annotated[
        bool, typer.Option("--yes", "-y", help="Confirmar sin preguntar")
    ] = False,
) -> None:
    """Elimina el log de decisiones."""
    from mendex.config.settings import get_settings
    from mendex.logging.decision_logger import DecisionLogger

    settings = get_settings()

    if not confirm:
        confirm = typer.confirm("¿Eliminar el log de decisiones?")
        if not confirm:
            console.print("[yellow]Cancelado.[/yellow]")
            raise typer.Exit(0)

    dl = DecisionLogger(settings.decisions_log_path)
    count = dl.clear()
    console.print(f"[green]Log eliminado:[/green] {count} entradas borradas")
