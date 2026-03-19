"""Tests unitarios para el caché LLM (SQLite).

Fase 2: Cobertura completa de LLMCache.
"""

from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from mendex.llm.cache import CacheStats, LLMCache


@pytest.fixture
def cache_path(tmp_path: Path) -> Path:
    return tmp_path / "cache" / "llm_responses.db"


@pytest.fixture
def cache(cache_path: Path) -> LLMCache:
    return LLMCache(cache_path, ttl_days=7)


# ─── Tests de inicialización ────────────────────────────────────────


class TestInit:
    def test_creates_directory(self, cache_path: Path) -> None:
        """Crea el directorio padre si no existe."""
        assert not cache_path.parent.exists()
        LLMCache(cache_path)
        assert cache_path.parent.exists()

    def test_creates_db_file(self, cache: LLMCache, cache_path: Path) -> None:
        """El archivo SQLite se crea al inicializar."""
        assert cache_path.exists()

    def test_creates_table(self, cache: LLMCache, cache_path: Path) -> None:
        """La tabla llm_cache existe con las columnas correctas."""
        conn = sqlite3.connect(str(cache_path))
        cursor = conn.execute("PRAGMA table_info(llm_cache)")
        columns = {row[1] for row in cursor.fetchall()}
        conn.close()

        assert "input_hash" in columns
        assert "conventions_hash" in columns
        assert "response" in columns
        assert "model" in columns
        assert "created_at" in columns

    def test_idempotent_init(self, cache_path: Path) -> None:
        """Múltiples inicializaciones no corrompen la DB."""
        LLMCache(cache_path)
        LLMCache(cache_path)
        cache = LLMCache(cache_path)
        # Debe funcionar normalmente
        cache.put("hash1", "conv1", {"test": True}, "model")
        assert cache.get("hash1", "conv1") is not None


# ─── Tests de put/get ────────────────────────────────────────────


class TestPutGet:
    def test_put_and_get(self, cache: LLMCache) -> None:
        """Almacena y recupera una respuesta."""
        cache.put("hash_a", "conv_1", {"result": "hello"}, "claude-sonnet")

        result = cache.get("hash_a", "conv_1")
        assert result is not None
        assert result["response"]["result"] == "hello"
        assert result["model"] == "claude-sonnet"
        assert result["cache_hit"] is True

    def test_get_miss(self, cache: LLMCache) -> None:
        """Retorna None si no hay entrada para el hash."""
        result = cache.get("nonexistent", "conv_1")
        assert result is None

    def test_different_conventions_hash_is_miss(self, cache: LLMCache) -> None:
        """Un hash de convenciones diferente produce cache miss."""
        cache.put("hash_a", "conv_old", {"result": "old"}, "model")

        # Mismo input_hash pero diferente conventions_hash
        result = cache.get("hash_a", "conv_new")
        assert result is None

    def test_same_input_different_conventions_stored_separately(
        self, cache: LLMCache
    ) -> None:
        """Mismo input con diferentes convenciones son entradas distintas."""
        cache.put("hash_a", "conv_1", {"v": 1}, "model")
        cache.put("hash_a", "conv_2", {"v": 2}, "model")

        r1 = cache.get("hash_a", "conv_1")
        r2 = cache.get("hash_a", "conv_2")
        assert r1["response"]["v"] == 1
        assert r2["response"]["v"] == 2

    def test_put_overwrites_existing(self, cache: LLMCache) -> None:
        """Una segunda put con la misma clave sobreescribe."""
        cache.put("hash_a", "conv_1", {"v": "old"}, "model")
        cache.put("hash_a", "conv_1", {"v": "new"}, "model")

        result = cache.get("hash_a", "conv_1")
        assert result["response"]["v"] == "new"

    def test_stores_complex_response(self, cache: LLMCache) -> None:
        """Almacena y recupera respuestas JSON complejas."""
        complex_data = {
            "entities": [
                {"name": "OrdenCompra", "attributes": ["Fecha", "Monto"]},
                {"name": "LineaDetalle", "attributes": ["Cantidad"]},
            ],
            "verdict": "CONFORME",
            "score": 0.95,
            "nested": {"deep": {"value": True}},
        }
        cache.put("hash_complex", "conv_1", complex_data, "model")

        result = cache.get("hash_complex", "conv_1")
        assert result["response"]["entities"][0]["name"] == "OrdenCompra"
        assert result["response"]["nested"]["deep"]["value"] is True

    def test_stores_unicode(self, cache: LLMCache) -> None:
        """Almacena y recupera correctamente texto con unicode/español."""
        cache.put("hash_u", "conv_1", {"msg": "Validación de año"}, "model")

        result = cache.get("hash_u", "conv_1")
        assert result["response"]["msg"] == "Validación de año"


# ─── Tests de TTL ────────────────────────────────────────────────


class TestTTL:
    def test_expired_entry_returns_none(self, cache_path: Path) -> None:
        """Entradas expiradas por TTL retornan None."""
        cache = LLMCache(cache_path, ttl_days=0)  # TTL = 0 días → expira inmediatamente

        cache.put("hash_ttl", "conv_1", {"old": True}, "model")

        # Forzar timestamp antiguo directamente en DB
        conn = sqlite3.connect(str(cache_path))
        old_time = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        conn.execute(
            "UPDATE llm_cache SET created_at = ? WHERE input_hash = ?",
            (old_time, "hash_ttl"),
        )
        conn.commit()
        conn.close()

        result = cache.get("hash_ttl", "conv_1")
        assert result is None

    def test_non_expired_entry_returns_hit(self, cache: LLMCache) -> None:
        """Entradas dentro del TTL retornan cache hit."""
        cache.put("hash_fresh", "conv_1", {"fresh": True}, "model")

        result = cache.get("hash_fresh", "conv_1")
        assert result is not None
        assert result["response"]["fresh"] is True

    def test_cleanup_expired_removes_old_entries(self, cache_path: Path) -> None:
        """cleanup_expired() elimina entradas vencidas."""
        cache = LLMCache(cache_path, ttl_days=1)

        cache.put("hash_old", "conv_1", {"v": "old"}, "model")
        cache.put("hash_new", "conv_1", {"v": "new"}, "model")

        # Envejecer la primera entrada
        conn = sqlite3.connect(str(cache_path))
        old_time = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
        conn.execute(
            "UPDATE llm_cache SET created_at = ? WHERE input_hash = ?",
            (old_time, "hash_old"),
        )
        conn.commit()
        conn.close()

        removed = cache.cleanup_expired()
        assert removed == 1

        # hash_old eliminado, hash_new sigue
        assert cache.get("hash_old", "conv_1") is None
        assert cache.get("hash_new", "conv_1") is not None


# ─── Tests de invalidate_by_conventions ──────────────────────────


class TestInvalidateByConventions:
    def test_invalidates_matching_conventions(self, cache: LLMCache) -> None:
        """Elimina entradas con el hash de convenciones especificado."""
        cache.put("h1", "old_conv", {"v": 1}, "model")
        cache.put("h2", "old_conv", {"v": 2}, "model")
        cache.put("h3", "new_conv", {"v": 3}, "model")

        removed = cache.invalidate_by_conventions("old_conv")
        assert removed == 2

        assert cache.get("h1", "old_conv") is None
        assert cache.get("h2", "old_conv") is None
        assert cache.get("h3", "new_conv") is not None

    def test_invalidate_nonexistent_returns_zero(self, cache: LLMCache) -> None:
        removed = cache.invalidate_by_conventions("nonexistent")
        assert removed == 0


# ─── Tests de stats ──────────────────────────────────────────────


class TestStats:
    def test_empty_cache_stats(self, cache: LLMCache) -> None:
        stats = cache.stats()
        assert stats.total_entries == 0
        assert stats.hits == 0
        assert stats.misses == 0
        assert stats.oldest_entry is None

    def test_stats_after_operations(self, cache: LLMCache) -> None:
        cache.put("h1", "c1", {"v": 1}, "model")
        cache.put("h2", "c1", {"v": 2}, "model")

        cache.get("h1", "c1")  # hit
        cache.get("h1", "c1")  # hit
        cache.get("nonexistent", "c1")  # miss

        stats = cache.stats()
        assert stats.total_entries == 2
        assert stats.hits == 2
        assert stats.misses == 1
        assert stats.size_bytes > 0
        assert stats.oldest_entry is not None

    def test_stats_to_dict(self, cache: LLMCache) -> None:
        stats = cache.stats()
        d = stats.to_dict()
        assert "total_entries" in d
        assert "hits" in d
        assert "misses" in d
        assert "size_bytes" in d


# ─── Tests de clear ──────────────────────────────────────────────


class TestClear:
    def test_clear_removes_all_entries(self, cache: LLMCache) -> None:
        cache.put("h1", "c1", {"v": 1}, "model")
        cache.put("h2", "c1", {"v": 2}, "model")

        removed = cache.clear()
        assert removed == 2

        assert cache.get("h1", "c1") is None
        assert cache.get("h2", "c1") is None

    def test_clear_resets_counters(self, cache: LLMCache) -> None:
        cache.put("h1", "c1", {"v": 1}, "model")
        cache.get("h1", "c1")  # hit

        cache.clear()
        stats = cache.stats()
        assert stats.hits == 0
        assert stats.misses == 0


# ─── Tests de hash helpers ───────────────────────────────────────


class TestHashHelpers:
    def test_compute_input_hash_deterministic(self) -> None:
        h1 = LLMCache.compute_input_hash("prompt1", "context1")
        h2 = LLMCache.compute_input_hash("prompt1", "context1")
        assert h1 == h2

    def test_compute_input_hash_different_inputs(self) -> None:
        h1 = LLMCache.compute_input_hash("prompt1")
        h2 = LLMCache.compute_input_hash("prompt2")
        assert h1 != h2

    def test_compute_input_hash_order_matters(self) -> None:
        h1 = LLMCache.compute_input_hash("a", "b")
        h2 = LLMCache.compute_input_hash("b", "a")
        assert h1 != h2

    def test_compute_input_hash_is_sha256(self) -> None:
        h = LLMCache.compute_input_hash("test")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_compute_file_hash(self, tmp_path: Path) -> None:
        f = tmp_path / "test.yaml"
        f.write_text("content: hello")
        h1 = LLMCache.compute_file_hash(f)
        assert len(h1) == 64

        f.write_text("content: changed")
        h2 = LLMCache.compute_file_hash(f)
        assert h1 != h2
