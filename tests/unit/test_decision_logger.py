"""Tests unitarios para el logger estructurado (decisions.jsonl).

Fase 2: Cobertura completa de DecisionLogger.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from mendex.logging.decision_logger import (
    BPVerdict,
    DecisionEntry,
    DecisionLogger,
    PatternSource,
)


@pytest.fixture
def log_path(tmp_path: Path) -> Path:
    return tmp_path / "logs" / "decisions.jsonl"


@pytest.fixture
def logger(log_path: Path) -> DecisionLogger:
    return DecisionLogger(log_path)


# ─── Tests de DecisionEntry ────────────────────────────────────────


class TestDecisionEntry:
    def test_creates_with_defaults(self) -> None:
        entry = DecisionEntry(operation="test_op")
        assert entry.operation == "test_op"
        assert entry.input_hash == ""
        assert entry.bp_verdict is None
        assert entry.warnings == []
        assert entry.cache_hit is False

    def test_to_jsonl_produces_valid_json(self) -> None:
        entry = DecisionEntry(
            operation="bp_evaluation",
            bp_verdict=BPVerdict.CONFORME,
            pattern_source=PatternSource.OFFICIAL_BP,
        )
        line = entry.to_jsonl()
        parsed = json.loads(line)
        assert parsed["operation"] == "bp_evaluation"
        assert parsed["bp_verdict"] == "CONFORME"
        assert parsed["pattern_source"] == "official_bp"

    def test_timestamp_is_iso_format(self) -> None:
        entry = DecisionEntry(operation="test")
        # Debe ser parseable como ISO datetime
        from datetime import datetime

        datetime.fromisoformat(entry.timestamp)

    def test_extra_fields_preserved(self) -> None:
        entry = DecisionEntry(
            operation="test",
            extra={"figma_frame_id": "1:2", "entity_name": "OrdenCompra"},
        )
        parsed = json.loads(entry.to_jsonl())
        assert parsed["extra"]["figma_frame_id"] == "1:2"


# ─── Tests de DecisionLogger ───────────────────────────────────────


class TestDecisionLogger:
    def test_creates_log_directory(self, log_path: Path) -> None:
        """Crea el directorio padre si no existe."""
        assert not log_path.parent.exists()
        DecisionLogger(log_path)
        assert log_path.parent.exists()

    def test_log_creates_file(self, logger: DecisionLogger, log_path: Path) -> None:
        """Primera escritura crea el archivo."""
        assert not log_path.exists()
        logger.log(operation="test")
        assert log_path.exists()

    def test_log_writes_valid_jsonl(self, logger: DecisionLogger, log_path: Path) -> None:
        """Cada línea del archivo es JSON válido."""
        logger.log(operation="op1", input_hash="hash1")
        logger.log(operation="op2", input_hash="hash2")

        lines = log_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2

        for line in lines:
            parsed = json.loads(line)
            assert "operation" in parsed
            assert "timestamp" in parsed

    def test_log_returns_entry(self, logger: DecisionLogger) -> None:
        """log() retorna el DecisionEntry creado."""
        entry = logger.log(
            operation="bp_evaluation",
            bp_verdict=BPVerdict.NO_CONFORME,
            warnings=["Missing access rules"],
        )
        assert isinstance(entry, DecisionEntry)
        assert entry.operation == "bp_evaluation"
        assert entry.bp_verdict == BPVerdict.NO_CONFORME
        assert "Missing access rules" in entry.warnings

    def test_log_all_fields(self, logger: DecisionLogger, log_path: Path) -> None:
        """Todos los campos se persisten correctamente."""
        logger.log(
            operation="generate_entity",
            input_hash="abc123",
            bp_verdict=BPVerdict.CONFORME,
            pattern_source=PatternSource.PROJECT_CONVENTIONS,
            action_taken="proceed",
            warnings=["warn1", "warn2"],
            llm_model="claude-sonnet-4-5-20250514",
            llm_tokens_used=1500,
            cache_hit=True,
            extra={"entity": "OrdenCompra"},
        )

        parsed = json.loads(log_path.read_text(encoding="utf-8").strip())
        assert parsed["operation"] == "generate_entity"
        assert parsed["input_hash"] == "abc123"
        assert parsed["bp_verdict"] == "CONFORME"
        assert parsed["pattern_source"] == "project_conventions"
        assert parsed["action_taken"] == "proceed"
        assert parsed["warnings"] == ["warn1", "warn2"]
        assert parsed["llm_model"] == "claude-sonnet-4-5-20250514"
        assert parsed["llm_tokens_used"] == 1500
        assert parsed["cache_hit"] is True
        assert parsed["extra"]["entity"] == "OrdenCompra"

    def test_append_only(self, logger: DecisionLogger, log_path: Path) -> None:
        """Escrituras sucesivas agregan líneas sin sobreescribir."""
        logger.log(operation="op1")
        logger.log(operation="op2")
        logger.log(operation="op3")

        lines = log_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 3
        ops = [json.loads(line)["operation"] for line in lines]
        assert ops == ["op1", "op2", "op3"]

    def test_entry_count_tracks_session(self, logger: DecisionLogger) -> None:
        """entry_count refleja las escrituras de esta sesión."""
        assert logger.entry_count == 0
        logger.log(operation="op1")
        assert logger.entry_count == 1
        logger.log(operation="op2")
        assert logger.entry_count == 2

    def test_log_entry_writes_prebuilt_entry(
        self, logger: DecisionLogger, log_path: Path
    ) -> None:
        """log_entry() escribe un DecisionEntry ya construido."""
        entry = DecisionEntry(operation="prebuilt", input_hash="xyz")
        logger.log_entry(entry)

        parsed = json.loads(log_path.read_text(encoding="utf-8").strip())
        assert parsed["operation"] == "prebuilt"
        assert parsed["input_hash"] == "xyz"


# ─── Tests de read_entries ──────────────────────────────────────────


class TestReadEntries:
    def test_read_empty_log(self, logger: DecisionLogger) -> None:
        """Log inexistente retorna lista vacía."""
        assert logger.read_entries() == []

    def test_read_all_entries(self, logger: DecisionLogger) -> None:
        """Lee todas las entradas escritas."""
        logger.log(operation="op1")
        logger.log(operation="op2")
        logger.log(operation="op3")

        entries = logger.read_entries()
        assert len(entries) == 3
        assert [e.operation for e in entries] == ["op1", "op2", "op3"]

    def test_read_last_n(self, logger: DecisionLogger) -> None:
        """Lee solo las últimas N entradas."""
        for i in range(10):
            logger.log(operation=f"op{i}")

        entries = logger.read_entries(last_n=3)
        assert len(entries) == 3
        assert [e.operation for e in entries] == ["op7", "op8", "op9"]

    def test_entries_are_deserialized_correctly(self, logger: DecisionLogger) -> None:
        """Las entradas leídas tienen tipos correctos."""
        logger.log(
            operation="eval",
            bp_verdict=BPVerdict.SIN_DATOS,
            llm_tokens_used=500,
            cache_hit=True,
        )

        entries = logger.read_entries()
        assert entries[0].bp_verdict == BPVerdict.SIN_DATOS
        assert entries[0].llm_tokens_used == 500
        assert entries[0].cache_hit is True


# ─── Tests de compute_token_summary ─────────────────────────────────


class TestTokenSummary:
    def test_empty_log_summary(self, logger: DecisionLogger) -> None:
        summary = logger.compute_token_summary()
        assert summary["total_tokens"] == 0
        assert summary["total_calls"] == 0

    def test_summary_counts_tokens(self, logger: DecisionLogger) -> None:
        logger.log(operation="call1", llm_tokens_used=1000, llm_model="claude-sonnet-4-5")
        logger.log(operation="call2", llm_tokens_used=500, llm_model="claude-sonnet-4-5")

        summary = logger.compute_token_summary()
        assert summary["total_tokens"] == 1500
        assert summary["total_calls"] == 2
        assert summary["cache_misses"] == 2

    def test_summary_separates_cache_hits(self, logger: DecisionLogger) -> None:
        logger.log(operation="miss", llm_tokens_used=1000, cache_hit=False)
        logger.log(operation="hit", llm_tokens_used=800, cache_hit=True)

        summary = logger.compute_token_summary()
        assert summary["cache_hits"] == 1
        assert summary["cache_misses"] == 1
        assert summary["total_tokens"] == 1000  # Solo misses
        assert summary["tokens_saved_by_cache"] == 800

    def test_summary_groups_by_model(self, logger: DecisionLogger) -> None:
        logger.log(operation="c1", llm_tokens_used=1000, llm_model="claude-sonnet")
        logger.log(operation="c2", llm_tokens_used=500, llm_model="claude-haiku")
        logger.log(operation="c3", llm_tokens_used=200, llm_model="claude-sonnet")

        summary = logger.compute_token_summary()
        assert summary["tokens_by_model"]["claude-sonnet"] == 1200
        assert summary["tokens_by_model"]["claude-haiku"] == 500


# ─── Tests de clear ─────────────────────────────────────────────────


class TestClear:
    def test_clear_removes_file(self, logger: DecisionLogger, log_path: Path) -> None:
        logger.log(operation="op1")
        logger.log(operation="op2")

        count = logger.clear()
        assert count == 2
        assert not log_path.exists()

    def test_clear_resets_entry_count(self, logger: DecisionLogger) -> None:
        logger.log(operation="op1")
        assert logger.entry_count == 1
        logger.clear()
        assert logger.entry_count == 0

    def test_clear_empty_log(self, logger: DecisionLogger) -> None:
        count = logger.clear()
        assert count == 0


# ─── Tests de thread safety ─────────────────────────────────────────


class TestThreadSafety:
    def test_concurrent_writes(self, logger: DecisionLogger, log_path: Path) -> None:
        """Escrituras concurrentes no corrompen el archivo."""
        num_threads = 10
        entries_per_thread = 20

        def write_entries(thread_id: int) -> None:
            for i in range(entries_per_thread):
                logger.log(operation=f"thread{thread_id}_op{i}")

        threads = [
            threading.Thread(target=write_entries, args=(t,))
            for t in range(num_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Todas las entradas deben estar presentes
        entries = logger.read_entries()
        assert len(entries) == num_threads * entries_per_thread

        # Cada línea debe ser JSON válido
        lines = log_path.read_text(encoding="utf-8").strip().split("\n")
        for line in lines:
            json.loads(line)  # No debe lanzar error
