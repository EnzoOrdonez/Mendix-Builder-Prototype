"""Caché de respuestas LLM por hash de input.

Antes de llamar a Claude API, se calcula un hash SHA-256 del input.
Si existe una respuesta cacheada para ese hash, se usa directamente
sin llamar a la API. El caché tiene TTL configurable y se invalida
automáticamente cuando cambia el hash de convenciones.

Storage: SQLite local en cache/llm_responses.db.

Fase 2: Implementación completa.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any


class CacheStats:
    """Estadísticas del caché LLM."""

    def __init__(
        self,
        total_entries: int,
        hits: int,
        misses: int,
        size_bytes: int,
        oldest_entry: datetime | None,
    ) -> None:
        self.total_entries = total_entries
        self.hits = hits
        self.misses = misses
        self.size_bytes = size_bytes
        self.oldest_entry = oldest_entry

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_entries": self.total_entries,
            "hits": self.hits,
            "misses": self.misses,
            "size_bytes": self.size_bytes,
            "oldest_entry": self.oldest_entry.isoformat() if self.oldest_entry else None,
        }


class LLMCache:
    """Caché SQLite para respuestas LLM con TTL y invalidación por convenciones.

    La clave de caché es el hash SHA-256 del input. El hash de convenciones
    se almacena junto a la respuesta: si las convenciones cambian, las
    entradas anteriores se consideran inválidas.

    Thread-safe via lock interno.

    Uso:
        cache = LLMCache(Path("cache/llm_responses.db"), ttl_days=7)

        # Buscar en caché
        result = cache.get("input_hash_abc", "conventions_hash_xyz")
        if result is None:
            # Llamar a Claude API
            response = call_claude(...)
            cache.put("input_hash_abc", "conventions_hash_xyz", response, "claude-sonnet-4-5")
    """

    def __init__(self, db_path: Path, ttl_days: int = 7) -> None:
        self._db_path = db_path
        self._ttl_days = ttl_days
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

        # Crear directorio padre si no existe
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        self._init_db()

    def _init_db(self) -> None:
        """Inicializa la base de datos SQLite con el schema requerido."""
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS llm_cache (
                        input_hash TEXT NOT NULL,
                        conventions_hash TEXT NOT NULL,
                        response TEXT NOT NULL,
                        model TEXT NOT NULL DEFAULT '',
                        created_at TEXT NOT NULL,
                        PRIMARY KEY (input_hash, conventions_hash)
                    )
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_created_at
                    ON llm_cache(created_at)
                """)
                conn.commit()
            finally:
                conn.close()

    def _get_connection(self) -> sqlite3.Connection:
        """Crea una nueva conexión SQLite."""
        return sqlite3.connect(str(self._db_path))

    def get(self, input_hash: str, conventions_hash: str) -> dict[str, Any] | None:
        """Busca una respuesta en el caché.

        Retorna None si:
        - No existe entrada para este input_hash + conventions_hash
        - La entrada expiró (TTL superado)

        Args:
            input_hash: Hash SHA-256 del input.
            conventions_hash: Hash SHA-256 del project_conventions.yaml activo.

        Returns:
            Dict con la respuesta cacheada, o None si no hay cache hit.
        """
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(
                    """
                    SELECT response, model, created_at
                    FROM llm_cache
                    WHERE input_hash = ? AND conventions_hash = ?
                    """,
                    (input_hash, conventions_hash),
                )
                row = cursor.fetchone()
            finally:
                conn.close()

        if row is None:
            self._misses += 1
            return None

        response_str, model, created_at_str = row
        created_at = datetime.fromisoformat(created_at_str)

        # Verificar TTL
        cutoff = datetime.now(timezone.utc) - timedelta(days=self._ttl_days)
        if created_at < cutoff:
            # Entrada expirada — limpiarla y retornar miss
            self._delete_entry(input_hash, conventions_hash)
            self._misses += 1
            return None

        self._hits += 1
        return {
            "response": json.loads(response_str),
            "model": model,
            "created_at": created_at_str,
            "cache_hit": True,
        }

    def put(
        self,
        input_hash: str,
        conventions_hash: str,
        response: Any,
        model: str = "",
    ) -> None:
        """Almacena una respuesta en el caché.

        Si ya existe una entrada con la misma clave, se sobrescribe.

        Args:
            input_hash: Hash SHA-256 del input.
            conventions_hash: Hash SHA-256 del project_conventions.yaml.
            response: Respuesta a cachear (debe ser JSON-serializable).
            model: Modelo de LLM que generó la respuesta.
        """
        now = datetime.now(timezone.utc).isoformat()
        response_str = json.dumps(response, ensure_ascii=False)

        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO llm_cache
                        (input_hash, conventions_hash, response, model, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (input_hash, conventions_hash, response_str, model, now),
                )
                conn.commit()
            finally:
                conn.close()

    def _delete_entry(self, input_hash: str, conventions_hash: str) -> None:
        """Elimina una entrada específica del caché."""
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    "DELETE FROM llm_cache WHERE input_hash = ? AND conventions_hash = ?",
                    (input_hash, conventions_hash),
                )
                conn.commit()
            finally:
                conn.close()

    def invalidate_by_conventions(self, old_conventions_hash: str) -> int:
        """Invalida todas las entradas que usaron un hash de convenciones específico.

        Útil cuando se detecta que project_conventions.yaml cambió.

        Args:
            old_conventions_hash: Hash de las convenciones anteriores.

        Returns:
            Número de entradas eliminadas.
        """
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(
                    "DELETE FROM llm_cache WHERE conventions_hash = ?",
                    (old_conventions_hash,),
                )
                conn.commit()
                return cursor.rowcount
            finally:
                conn.close()

    def cleanup_expired(self) -> int:
        """Elimina todas las entradas expiradas.

        Returns:
            Número de entradas eliminadas.
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(days=self._ttl_days)).isoformat()

        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(
                    "DELETE FROM llm_cache WHERE created_at < ?",
                    (cutoff,),
                )
                conn.commit()
                return cursor.rowcount
            finally:
                conn.close()

    def stats(self) -> CacheStats:
        """Retorna estadísticas del caché.

        Returns:
            CacheStats con total_entries, hits, misses, size_bytes, oldest_entry.
        """
        with self._lock:
            conn = self._get_connection()
            try:
                # Contar entradas
                count = conn.execute("SELECT COUNT(*) FROM llm_cache").fetchone()[0]

                # Entrada más antigua
                oldest_row = conn.execute(
                    "SELECT MIN(created_at) FROM llm_cache"
                ).fetchone()
                oldest = None
                if oldest_row and oldest_row[0]:
                    oldest = datetime.fromisoformat(oldest_row[0])
            finally:
                conn.close()

        # Tamaño del archivo
        size = self._db_path.stat().st_size if self._db_path.exists() else 0

        return CacheStats(
            total_entries=count,
            hits=self._hits,
            misses=self._misses,
            size_bytes=size,
            oldest_entry=oldest,
        )

    def clear(self) -> int:
        """Elimina todas las entradas del caché.

        Returns:
            Número de entradas eliminadas.
        """
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute("DELETE FROM llm_cache")
                conn.commit()
                count = cursor.rowcount
            finally:
                conn.close()

        self._hits = 0
        self._misses = 0
        return count

    @staticmethod
    def compute_input_hash(*parts: str) -> str:
        """Calcula un hash SHA-256 de múltiples partes de input.

        Útil para combinar el contenido del Excel/Figma con otros parámetros
        en un solo hash determinista.

        Args:
            parts: Strings a combinar en el hash.

        Returns:
            Hash SHA-256 como string hexadecimal.
        """
        sha256 = hashlib.sha256()
        for part in parts:
            sha256.update(part.encode("utf-8"))
        return sha256.hexdigest()

    @staticmethod
    def compute_file_hash(file_path: Path) -> str:
        """Calcula hash SHA-256 de un archivo.

        Args:
            file_path: Path al archivo.

        Returns:
            Hash SHA-256 como string hexadecimal.
        """
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()
