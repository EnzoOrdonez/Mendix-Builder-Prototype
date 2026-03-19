"""Tests para la CLI completa de MendixFormAgent.

Fase 12: Tests unitarios completos.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from mendex.cli.app import app


runner = CliRunner()


# ═══════════════════════════════════════════════════════════════
# HELP & BASICS
# ═══════════════════════════════════════════════════════════════


class TestCLIHelp:
    def test_no_args_shows_help(self):
        result = runner.invoke(app, [])
        assert result.exit_code in (0, 2)
        assert "Usage" in result.output

    def test_help_flag(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "generate" in result.output
        assert "audit" in result.output
        assert "serve" in result.output

    def test_generate_help(self):
        result = runner.invoke(app, ["generate", "--help"])
        assert result.exit_code == 0
        assert "--input" in result.output
        assert "--mpr" in result.output
        assert "--on-conflict" in result.output
        assert "--strict" in result.output
        assert "--no-confirm" in result.output
        assert "--no-cache" in result.output
        assert "--module" in result.output

    def test_audit_help(self):
        result = runner.invoke(app, ["audit", "--help"])
        assert result.exit_code == 0
        assert "--mpr" in result.output
        assert "--strict" in result.output
        assert "--no-bp" in result.output
        assert "--output" in result.output

    def test_serve_help(self):
        result = runner.invoke(app, ["serve", "--help"])
        assert result.exit_code == 0
        assert "--port" in result.output
        assert "--host" in result.output

    def test_cache_help(self):
        result = runner.invoke(app, ["cache", "--help"])
        assert result.exit_code == 0
        assert "stats" in result.output
        assert "clear" in result.output

    def test_log_help(self):
        result = runner.invoke(app, ["log", "--help"])
        assert result.exit_code == 0
        assert "show" in result.output
        assert "tokens" in result.output
        assert "clear" in result.output


# ═══════════════════════════════════════════════════════════════
# GENERATE
# ═══════════════════════════════════════════════════════════════


class TestGenerateCommand:
    def test_missing_mpr_exits(self, tmp_path: Path):
        result = runner.invoke(app, [
            "generate",
            "--input", "test.xlsx",
            "--mpr", str(tmp_path / "nonexistent.mpr"),
        ])
        assert result.exit_code == 1

    def test_missing_input_exits(self, tmp_path: Path):
        mpr = tmp_path / "test.mpr"
        mpr.write_bytes(b"fake")
        result = runner.invoke(app, [
            "generate",
            "--input", str(tmp_path / "nonexistent.xlsx"),
            "--mpr", str(mpr),
        ])
        assert result.exit_code == 1


# ═══════════════════════════════════════════════════════════════
# AUDIT
# ═══════════════════════════════════════════════════════════════


class TestAuditCommand:
    def test_missing_mpr_exits(self, tmp_path: Path):
        result = runner.invoke(app, [
            "audit",
            "--mpr", str(tmp_path / "nonexistent.mpr"),
        ])
        assert result.exit_code == 1


# ═══════════════════════════════════════════════════════════════
# CACHE
# ═══════════════════════════════════════════════════════════════


class TestCacheCommands:
    @patch("mendex.config.settings.get_settings")
    def test_cache_stats(self, mock_settings, tmp_path: Path):
        mock_settings.return_value = MagicMock(
            cache_db_path=tmp_path / "cache.db",
            cache_ttl_days=7,
        )
        result = runner.invoke(app, ["cache", "stats"])
        assert result.exit_code == 0
        assert "Caché LLM" in result.output

    @patch("mendex.config.settings.get_settings")
    def test_cache_clear_cancel(self, mock_settings, tmp_path: Path):
        mock_settings.return_value = MagicMock(
            cache_db_path=tmp_path / "cache.db",
            cache_ttl_days=7,
        )
        result = runner.invoke(app, ["cache", "clear"], input="n\n")
        assert result.exit_code == 0
        assert "Cancelado" in result.output

    @patch("mendex.config.settings.get_settings")
    def test_cache_clear_confirm(self, mock_settings, tmp_path: Path):
        mock_settings.return_value = MagicMock(
            cache_db_path=tmp_path / "cache.db",
            cache_ttl_days=7,
        )
        result = runner.invoke(app, ["cache", "clear", "--yes"])
        assert result.exit_code == 0
        assert "eliminado" in result.output


# ═══════════════════════════════════════════════════════════════
# LOG
# ═══════════════════════════════════════════════════════════════


class TestLogCommands:
    @patch("mendex.config.settings.get_settings")
    def test_log_show_empty(self, mock_settings, tmp_path: Path):
        mock_settings.return_value = MagicMock(
            decisions_log_path=tmp_path / "decisions.jsonl",
        )
        result = runner.invoke(app, ["log", "show"])
        assert result.exit_code == 0
        assert "Sin entradas" in result.output

    @patch("mendex.config.settings.get_settings")
    def test_log_show_with_entries(self, mock_settings, tmp_path: Path):
        log_path = tmp_path / "decisions.jsonl"
        mock_settings.return_value = MagicMock(decisions_log_path=log_path)

        # Write a test entry
        from mendex.logging.decision_logger import DecisionLogger
        dl = DecisionLogger(log_path)
        dl.log(operation="test_op", action_taken="proceed")

        result = runner.invoke(app, ["log", "show"])
        assert result.exit_code == 0
        assert "test_op" in result.output

    @patch("mendex.config.settings.get_settings")
    def test_log_show_json(self, mock_settings, tmp_path: Path):
        log_path = tmp_path / "decisions.jsonl"
        mock_settings.return_value = MagicMock(decisions_log_path=log_path)

        from mendex.logging.decision_logger import DecisionLogger
        dl = DecisionLogger(log_path)
        dl.log(operation="test_op", action_taken="proceed")

        result = runner.invoke(app, ["log", "show", "--output", "json"])
        assert result.exit_code == 0
        assert "test_op" in result.output

    @patch("mendex.config.settings.get_settings")
    def test_log_tokens(self, mock_settings, tmp_path: Path):
        mock_settings.return_value = MagicMock(
            decisions_log_path=tmp_path / "decisions.jsonl",
        )
        result = runner.invoke(app, ["log", "tokens"])
        assert result.exit_code == 0
        assert "Tokens" in result.output

    @patch("mendex.config.settings.get_settings")
    def test_log_clear_cancel(self, mock_settings, tmp_path: Path):
        mock_settings.return_value = MagicMock(
            decisions_log_path=tmp_path / "decisions.jsonl",
        )
        result = runner.invoke(app, ["log", "clear"], input="n\n")
        assert result.exit_code == 0
        assert "Cancelado" in result.output

    @patch("mendex.config.settings.get_settings")
    def test_log_clear_confirm(self, mock_settings, tmp_path: Path):
        mock_settings.return_value = MagicMock(
            decisions_log_path=tmp_path / "decisions.jsonl",
        )
        result = runner.invoke(app, ["log", "clear", "--yes"])
        assert result.exit_code == 0
        assert "eliminado" in result.output
