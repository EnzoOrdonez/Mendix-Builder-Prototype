"""Logger estructurado para decisiones del agente.

Cada decisión genera una entrada JSON en logs/decisions.jsonl (append-only).
Es la fuente de verdad para auditar por qué el agente tomó cada decisión,
depurar comportamientos inesperados y calcular costos de API acumulados.

Fase 2: Implementación completa.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class BPVerdict(str, Enum):
    """Veredicto de evaluación de buenas prácticas."""

    CONFORME = "CONFORME"
    NO_CONFORME = "NO_CONFORME"
    SIN_DATOS = "SIN_DATOS"


class PatternSource(str, Enum):
    """Fuente del patrón aplicado."""

    OFFICIAL_BP = "official_bp"
    PROJECT_CONVENTIONS = "project_conventions"
    FIGMA = "figma"
    EXCEL = "excel"
    NONE = "none"


class DecisionEntry(BaseModel):
    """Una entrada en el log de decisiones."""

    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    operation: str
    input_hash: str = ""
    bp_verdict: BPVerdict | None = None
    pattern_source: PatternSource = PatternSource.NONE
    action_taken: str = ""
    warnings: list[str] = Field(default_factory=list)
    llm_model: str = ""
    llm_tokens_used: int = 0
    cache_hit: bool = False
    extra: dict[str, Any] = Field(default_factory=dict)

    def to_jsonl(self) -> str:
        """Serializa a una línea JSON (sin newline al final)."""
        return self.model_dump_json()


class DecisionLogger:
    """Logger append-only que escribe decisiones a un archivo JSONL.

    Thread-safe via lock interno. Cada llamada a log() escribe
    inmediatamente al archivo (flush incluido).

    Uso:
        logger = DecisionLogger(Path("logs/decisions.jsonl"))
        logger.log(
            operation="bp_evaluation",
            input_hash="abc123",
            bp_verdict=BPVerdict.CONFORME,
            pattern_source=PatternSource.OFFICIAL_BP,
            action_taken="proceed",
        )
    """

    def __init__(self, log_path: Path) -> None:
        self._log_path = log_path
        self._lock = threading.Lock()
        self._entry_count = 0

        # Crear directorio padre si no existe
        self._log_path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def log_path(self) -> Path:
        return self._log_path

    @property
    def entry_count(self) -> int:
        """Número de entradas escritas en esta sesión."""
        return self._entry_count

    def log(
        self,
        operation: str,
        *,
        input_hash: str = "",
        bp_verdict: BPVerdict | None = None,
        pattern_source: PatternSource = PatternSource.NONE,
        action_taken: str = "",
        warnings: list[str] | None = None,
        llm_model: str = "",
        llm_tokens_used: int = 0,
        cache_hit: bool = False,
        extra: dict[str, Any] | None = None,
    ) -> DecisionEntry:
        """Registra una decisión en el log.

        Args:
            operation: Nombre de la operación (ej: "bp_evaluation", "generate_entity").
            input_hash: Hash SHA-256 del input procesado.
            bp_verdict: Veredicto de buenas prácticas (si aplica).
            pattern_source: Fuente del patrón aplicado.
            action_taken: Acción ejecutada (ej: "proceed", "warning_emitted", "aborted").
            warnings: Lista de warnings generados.
            llm_model: Modelo de LLM utilizado.
            llm_tokens_used: Tokens consumidos en la llamada.
            cache_hit: Si la respuesta vino del caché.
            extra: Campos adicionales libres.

        Returns:
            DecisionEntry creado y persistido.
        """
        entry = DecisionEntry(
            operation=operation,
            input_hash=input_hash,
            bp_verdict=bp_verdict,
            pattern_source=pattern_source,
            action_taken=action_taken,
            warnings=warnings or [],
            llm_model=llm_model,
            llm_tokens_used=llm_tokens_used,
            cache_hit=cache_hit,
            extra=extra or {},
        )

        self._write_entry(entry)
        return entry

    def log_entry(self, entry: DecisionEntry) -> None:
        """Escribe un DecisionEntry ya construido."""
        self._write_entry(entry)

    def _write_entry(self, entry: DecisionEntry) -> None:
        """Escribe una entrada al archivo JSONL (thread-safe)."""
        line = entry.to_jsonl() + "\n"

        with self._lock:
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(line)
            self._entry_count += 1

    def read_entries(self, last_n: int | None = None) -> list[DecisionEntry]:
        """Lee entradas del log.

        Args:
            last_n: Si se especifica, retorna solo las N últimas entradas.

        Returns:
            Lista de DecisionEntry.
        """
        if not self._log_path.exists():
            return []

        entries: list[DecisionEntry] = []
        with open(self._log_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(DecisionEntry.model_validate_json(line))

        if last_n is not None:
            return entries[-last_n:]
        return entries

    def compute_token_summary(self) -> dict[str, Any]:
        """Calcula un resumen de consumo de tokens.

        Returns:
            Dict con total_tokens, total_calls, cache_hits, cache_misses,
            tokens_by_model, y tokens_saved_by_cache.
        """
        entries = self.read_entries()

        total_tokens = 0
        total_calls = 0
        cache_hits = 0
        cache_misses = 0
        tokens_by_model: dict[str, int] = {}
        tokens_saved_by_cache = 0

        for entry in entries:
            if entry.llm_tokens_used > 0 or entry.cache_hit:
                total_calls += 1
                if entry.cache_hit:
                    cache_hits += 1
                    # Estimamos que el caché ahorra los mismos tokens que la respuesta original
                    tokens_saved_by_cache += entry.llm_tokens_used
                else:
                    cache_misses += 1
                    total_tokens += entry.llm_tokens_used
                    model = entry.llm_model or "unknown"
                    tokens_by_model[model] = (
                        tokens_by_model.get(model, 0) + entry.llm_tokens_used
                    )

        return {
            "total_tokens": total_tokens,
            "total_calls": total_calls,
            "cache_hits": cache_hits,
            "cache_misses": cache_misses,
            "tokens_by_model": tokens_by_model,
            "tokens_saved_by_cache": tokens_saved_by_cache,
        }

    def clear(self) -> int:
        """Elimina el archivo de log y retorna el número de entradas eliminadas.

        Returns:
            Número de entradas que había en el log.
        """
        count = len(self.read_entries())
        if self._log_path.exists():
            self._log_path.unlink()
        self._entry_count = 0
        return count
