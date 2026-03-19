"""Tests unitarios para LLMProvider y MockLLMProvider.

Fase 2: Tests del sistema de abstracción LLM.
Nota: ClaudeProvider no se testea en unit tests (requiere API key real).
      Se testea via MockLLMProvider y tests de integración.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mendex.llm.cache import LLMCache
from mendex.llm.provider import (
    ClaudeProvider,
    LLMProvider,
    LLMResponse,
    MockLLMProvider,
)
from mendex.logging.decision_logger import DecisionLogger


# ─── Tests de LLMResponse ───────────────────────────────────────────


class TestLLMResponse:
    def test_basic_response(self) -> None:
        r = LLMResponse(content="hello", model="test-model")
        assert r.content == "hello"
        assert r.model == "test-model"
        assert r.total_tokens == 0
        assert r.cache_hit is False

    def test_parsed_json_valid(self) -> None:
        r = LLMResponse(
            content='{"verdict": "CONFORME", "score": 0.95}',
            model="test",
        )
        parsed = r.parsed_json
        assert parsed["verdict"] == "CONFORME"
        assert parsed["score"] == 0.95

    def test_parsed_json_invalid(self) -> None:
        r = LLMResponse(content="not json at all", model="test")
        assert r.parsed_json is None

    def test_parsed_json_empty(self) -> None:
        r = LLMResponse(content="", model="test")
        assert r.parsed_json is None


# ─── Tests de MockLLMProvider ────────────────────────────────────────


class TestMockLLMProvider:
    def test_is_llm_provider(self) -> None:
        """MockLLMProvider implementa LLMProvider."""
        mock = MockLLMProvider()
        assert isinstance(mock, LLMProvider)

    def test_default_response(self) -> None:
        mock = MockLLMProvider()
        r = mock.send("any prompt")
        assert r.content == '{"result": "mock"}'
        assert r.model == "mock-model"
        assert r.cache_hit is False

    def test_custom_responses(self) -> None:
        mock = MockLLMProvider(
            responses={
                "what type?": '{"type": "String"}',
                "is valid?": '{"valid": true}',
            }
        )
        r1 = mock.send("what type?")
        assert json.loads(r1.content)["type"] == "String"

        r2 = mock.send("is valid?")
        assert json.loads(r2.content)["valid"] is True

    def test_custom_default_response(self) -> None:
        mock = MockLLMProvider(default_response="custom default")
        r = mock.send("unknown prompt")
        assert r.content == "custom default"

    def test_call_count(self) -> None:
        mock = MockLLMProvider()
        assert mock.call_count == 0
        mock.send("a")
        mock.send("b")
        assert mock.call_count == 2

    def test_last_prompt(self) -> None:
        mock = MockLLMProvider()
        mock.send("first prompt")
        mock.send("second prompt")
        assert mock.last_prompt == "second prompt"

    def test_model_name(self) -> None:
        mock = MockLLMProvider()
        assert mock.model_name() == "mock-model"

    def test_returns_token_estimates(self) -> None:
        mock = MockLLMProvider()
        r = mock.send("hello world test")
        # Token count = word count (mock estimation)
        assert r.input_tokens == 3  # "hello", "world", "test"
        assert r.total_tokens > 0


# ─── Tests de ClaudeProvider (sin API) ───────────────────────────────


class TestClaudeProviderInit:
    def test_model_name(self) -> None:
        provider = ClaudeProvider(api_key="fake", model="claude-test")
        assert provider.model_name() == "claude-test"

    def test_default_model(self) -> None:
        provider = ClaudeProvider(api_key="fake")
        assert "claude" in provider.model_name()

    def test_is_llm_provider(self) -> None:
        provider = ClaudeProvider(api_key="fake")
        assert isinstance(provider, LLMProvider)


# ─── Tests de integración con cache ─────────────────────────────────


class TestProviderCacheIntegration:
    """Tests que verifican la integración MockProvider + Cache + Logger."""

    def test_mock_with_logger(self, tmp_path: Path) -> None:
        """MockLLMProvider se puede usar sin problemas (no llama a cache/logger)."""
        mock = MockLLMProvider()
        r = mock.send("test", system_prompt="system")
        assert r.content == '{"result": "mock"}'

    def test_claude_provider_update_conventions_hash(self, tmp_path: Path) -> None:
        """update_conventions_hash invalida cache cuando el hash cambia."""
        cache = LLMCache(tmp_path / "cache.db", ttl_days=7)

        # Pre-popular el cache con convenciones viejas
        cache.put("prompt_hash", "old_conv_hash", {"old": True}, "model")
        assert cache.get("prompt_hash", "old_conv_hash") is not None

        provider = ClaudeProvider(
            api_key="fake",
            cache=cache,
            conventions_hash="old_conv_hash",
        )

        # Actualizar conventions → invalida entradas con hash viejo
        provider.update_conventions_hash("new_conv_hash")

        # La entrada vieja ya no está
        assert cache.get("prompt_hash", "old_conv_hash") is None

    def test_claude_provider_no_cache_no_crash(self) -> None:
        """ClaudeProvider sin cache ni logger no crashea en init."""
        provider = ClaudeProvider(api_key="fake")
        assert provider.model_name() is not None
