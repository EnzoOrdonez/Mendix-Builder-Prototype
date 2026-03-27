"""Abstracción de proveedor LLM.

Define LLMProvider como ABC para desacoplar la lógica del agente del
proveedor de LLM concreto. Permite swappear Claude por otro modelo o
proveedor sin cambiar la lógica de negocio.

Implementaciones:
- ClaudeProvider: Claude API via SDK oficial de Anthropic
- (Futuro) MendixAIGatewayProvider: para Mendix 11

Fase 2: Implementación completa.
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

from mendex.llm.cache import LLMCache
from mendex.logging.decision_logger import DecisionLogger

logger = structlog.get_logger(__name__)


@dataclass
class LLMResponse:
    """Respuesta estructurada de un LLM."""

    content: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cache_hit: bool = False
    raw_response: dict[str, Any] = field(default_factory=dict)

    @property
    def parsed_json(self) -> Any:
        """Intenta parsear el contenido como JSON."""
        try:
            return json.loads(self.content)
        except json.JSONDecodeError:
            return None


class LLMProvider(ABC):
    """Interfaz abstracta para proveedores de LLM.

    Todas las implementaciones deben:
    - Aceptar un prompt de sistema y un prompt de usuario
    - Retornar LLMResponse con tokens consumidos
    - Soportar respuestas JSON estructuradas (opcional)
    """

    @abstractmethod
    def send(
        self,
        user_prompt: str,
        *,
        system_prompt: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.0,
        response_format: str | None = None,
    ) -> LLMResponse:
        """Envía un prompt al LLM y retorna la respuesta.

        Args:
            user_prompt: Prompt del usuario.
            system_prompt: Prompt de sistema (contexto/instrucciones).
            max_tokens: Máximo de tokens en la respuesta.
            temperature: Temperatura de sampling (0.0 = determinista).
            response_format: Si es "json", solicita respuesta JSON.

        Returns:
            LLMResponse con contenido y metadata.
        """
        ...

    @abstractmethod
    def model_name(self) -> str:
        """Retorna el nombre del modelo en uso."""
        ...


class ClaudeProvider(LLMProvider):
    """Implementación de LLMProvider usando Claude API via SDK de Anthropic.

    Integra automáticamente con LLMCache y DecisionLogger si se proporcionan.

    Uso:
        provider = ClaudeProvider(
            api_key="sk-ant-...",
            model="claude-sonnet-4-5-20250514",
            cache=LLMCache(...),
            decision_logger=DecisionLogger(...),
        )
        response = provider.send("¿Qué tipo Mendix corresponde a un campo de fecha?")
    """

    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-5-20250514",
        cache: LLMCache | None = None,
        decision_logger: DecisionLogger | None = None,
        conventions_hash: str = "",
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._cache = cache
        self._decision_logger = decision_logger
        self._conventions_hash = conventions_hash
        self._client: Any = None

    def _get_client(self) -> Any:
        """Lazy-init del cliente Anthropic."""
        if self._client is None:
            try:
                import anthropic

                self._client = anthropic.Anthropic(api_key=self._api_key)
            except ImportError:
                raise RuntimeError(
                    "El paquete 'anthropic' no está instalado. "
                    "Ejecuta: pip install anthropic"
                )
        return self._client

    def model_name(self) -> str:
        return self._model

    def update_conventions_hash(self, new_hash: str) -> None:
        """Actualiza el hash de convenciones usado para el caché.

        Llamar cuando project_conventions.yaml cambie.
        """
        if self._cache and self._conventions_hash and new_hash != self._conventions_hash:
            invalidated = self._cache.invalidate_by_conventions(self._conventions_hash)
            logger.info(
                "conventions_changed_cache_invalidated",
                old_hash=self._conventions_hash[:16],
                new_hash=new_hash[:16],
                entries_invalidated=invalidated,
            )
        self._conventions_hash = new_hash

    def send(
        self,
        user_prompt: str,
        *,
        system_prompt: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.0,
        response_format: str | None = None,
    ) -> LLMResponse:
        """Envía prompt a Claude API con caché integrado.

        Si el caché tiene una respuesta válida para este input + conventions,
        la retorna sin llamar a la API.
        """
        # Calcular hash del input para caché
        input_hash = self._compute_prompt_hash(user_prompt, system_prompt)

        # Intentar caché
        if self._cache is not None:
            cached = self._cache.get(input_hash, self._conventions_hash)
            if cached is not None:
                response = LLMResponse(
                    content=cached["response"].get("content", ""),
                    model=cached.get("model", self._model),
                    input_tokens=cached["response"].get("input_tokens", 0),
                    output_tokens=cached["response"].get("output_tokens", 0),
                    total_tokens=cached["response"].get("total_tokens", 0),
                    cache_hit=True,
                )

                self._log_decision(
                    operation="llm_call",
                    input_hash=input_hash,
                    response=response,
                )

                logger.debug(
                    "cache_hit",
                    input_hash=input_hash[:16],
                    model=response.model,
                )
                return response

        # Llamar a Claude API
        client = self._get_client()

        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": user_prompt}],
        }

        if system_prompt:
            kwargs["system"] = system_prompt

        try:
            api_response = client.messages.create(**kwargs)
        except Exception as e:
            logger.error("claude_api_error", error=str(e), model=self._model)
            raise

        # Extraer contenido
        content = ""
        if api_response.content:
            content = api_response.content[0].text

        response = LLMResponse(
            content=content,
            model=api_response.model,
            input_tokens=api_response.usage.input_tokens,
            output_tokens=api_response.usage.output_tokens,
            total_tokens=(
                api_response.usage.input_tokens + api_response.usage.output_tokens
            ),
            cache_hit=False,
            raw_response={
                "id": api_response.id,
                "stop_reason": api_response.stop_reason,
            },
        )

        # Guardar en caché
        if self._cache is not None:
            cache_data = {
                "content": content,
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "total_tokens": response.total_tokens,
            }
            self._cache.put(
                input_hash, self._conventions_hash, cache_data, self._model
            )

        # Loguear decisión
        self._log_decision(
            operation="llm_call",
            input_hash=input_hash,
            response=response,
        )

        logger.info(
            "claude_api_call",
            model=self._model,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
        )

        return response

    def _compute_prompt_hash(self, user_prompt: str, system_prompt: str) -> str:
        """Calcula hash SHA-256 del prompt completo."""
        sha256 = hashlib.sha256()
        sha256.update(self._model.encode("utf-8"))
        sha256.update(system_prompt.encode("utf-8"))
        sha256.update(user_prompt.encode("utf-8"))
        return sha256.hexdigest()

    def _log_decision(
        self,
        operation: str,
        input_hash: str,
        response: LLMResponse,
    ) -> None:
        """Registra la llamada en el decision logger si está disponible."""
        if self._decision_logger is not None:
            self._decision_logger.log(
                operation=operation,
                input_hash=input_hash,
                llm_model=response.model,
                llm_tokens_used=response.total_tokens,
                cache_hit=response.cache_hit,
                action_taken="cache_hit" if response.cache_hit else "api_call",
            )


class MockLLMProvider(LLMProvider):
    """Proveedor mock para tests. Retorna respuestas predefinidas."""

    def __init__(
        self,
        responses: dict[str, str] | None = None,
        default_response: str = '{"result": "mock"}',
    ) -> None:
        self._responses = responses or {}
        self._default_response = default_response
        self._call_count = 0
        self._last_prompt: str = ""

    def model_name(self) -> str:
        return "mock-model"

    @property
    def call_count(self) -> int:
        return self._call_count

    @property
    def last_prompt(self) -> str:
        return self._last_prompt

    def send(
        self,
        user_prompt: str,
        *,
        system_prompt: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.0,
        response_format: str | None = None,
    ) -> LLMResponse:
        self._call_count += 1
        self._last_prompt = user_prompt

        content = self._responses.get(user_prompt, self._default_response)

        return LLMResponse(
            content=content,
            model="mock-model",
            input_tokens=len(user_prompt.split()),
            output_tokens=len(content.split()),
            total_tokens=len(user_prompt.split()) + len(content.split()),
            cache_hit=False,
        )
