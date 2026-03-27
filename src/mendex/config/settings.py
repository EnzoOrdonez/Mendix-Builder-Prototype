"""Configuración global del agente MendixFormAgent.

Carga variables desde .env y aplica defaults sensatos.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuración centralizada — se lee de .env y variables de entorno."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Anthropic ---
    anthropic_api_key: str = ""
    llm_model: str = "claude-sonnet-4-5-20250514"

    # --- Mendix Platform SDK ---
    mendix_token: str = ""
    mendix_app_id: str = ""

    # --- Figma (opcional) ---
    figma_access_token: str = ""

    # --- Servidor REST ---
    host: str = "127.0.0.1"
    port: int = 8000

    # --- Cache LLM ---
    cache_ttl_days: int = 7
    cache_db_path: Path = Field(default=Path("cache/llm_responses.db"))

    # --- Logging ---
    log_level: str = "INFO"
    decisions_log_path: Path = Field(default=Path("logs/decisions.jsonl"))

    # --- Knowledge Base ---
    chroma_db_path: Path = Field(default=Path("knowledge_base/chroma_db"))
    bp_docs_path: Path = Field(default=Path("knowledge_base/mendix_bp_official"))

    # --- Convenciones ---
    conventions_path: Path = Field(default=Path("conventions/project_conventions.yaml"))

    # --- Rollback ---
    max_backups: int = 5

    @property
    def figma_enabled(self) -> bool:
        """Figma está habilitado solo si se provee el token."""
        return bool(self.figma_access_token)


def get_settings() -> Settings:
    """Factory para obtener la configuración (cacheable con lru_cache si se desea)."""
    return Settings()
