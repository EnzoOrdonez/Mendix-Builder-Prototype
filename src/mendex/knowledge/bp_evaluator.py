"""Pipeline de evaluación de buenas prácticas.

Evalúa un patrón contra las BP oficiales de Mendix (via RAG) y las
convenciones del proyecto de referencia. Genera veredictos estructurados:
CONFORME, NO_CONFORME, SIN_DATOS.

Jerarquía de fuentes:
1. BP oficial de Mendix (ChromaDB RAG) — siempre gana
2. copeinca_conventions.yaml — se aplica solo si no contradice BPs
3. Si hay conflicto: se aplica BP oficial y se notifica al usuario

Fase 4: Implementación completa.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import structlog

from mendex.knowledge.bp_loader import BPChunk, BPLoader
from mendex.knowledge.conventions_reader import ConventionsReader
from mendex.llm.provider import LLMProvider, LLMResponse
from mendex.logging.decision_logger import (
    BPVerdict,
    DecisionLogger,
    PatternSource,
)

logger = structlog.get_logger(__name__)


EVALUATION_SYSTEM_PROMPT = """Eres un evaluador experto de buenas prácticas de Mendix.

Tu tarea es evaluar si un patrón de desarrollo cumple con las buenas prácticas oficiales de Mendix.

Recibirás:
1. El patrón a evaluar (descripción del artefacto)
2. Chunks relevantes de las buenas prácticas oficiales de Mendix
3. Convenciones del proyecto de referencia (contexto secundario)

Debes responder EXACTAMENTE en formato JSON con esta estructura:
{
  "verdict": "CONFORME" | "NO_CONFORME" | "SIN_DATOS",
  "confidence": 0.0 a 1.0,
  "reason": "Explicación breve de por qué",
  "recommendation": "Qué cambiar si es NO_CONFORME (o null si es CONFORME)",
  "bp_source": "Qué regla oficial aplica (o null si SIN_DATOS)",
  "convention_match": true | false,
  "convention_conflict": "Descripción del conflicto si lo hay (o null)"
}

Reglas:
- CONFORME: El patrón cumple las BP oficiales
- NO_CONFORME: El patrón viola una BP oficial específica
- SIN_DATOS: No hay BP oficial que cubra este patrón
- Si las convenciones del proyecto contradicen una BP oficial, el veredicto
  sigue la BP oficial (NO_CONFORME) y reportas el conflicto en convention_conflict
- confidence debe reflejar cuán seguro estás del veredicto
"""


@dataclass
class BPEvaluation:
    """Resultado de una evaluación de buenas prácticas."""

    verdict: BPVerdict
    confidence: float = 0.0
    reason: str = ""
    recommendation: str | None = None
    bp_source: str | None = None
    convention_match: bool = False
    convention_conflict: str | None = None
    relevant_chunks: list[BPChunk] = field(default_factory=list)
    pattern_description: str = ""

    def __repr__(self) -> str:
        return f"BPEvaluation(verdict={self.verdict.value}, conf={self.confidence:.2f})"

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "confidence": self.confidence,
            "reason": self.reason,
            "recommendation": self.recommendation,
            "bp_source": self.bp_source,
            "convention_match": self.convention_match,
            "convention_conflict": self.convention_conflict,
        }

    def as_report_line(self) -> str:
        """Genera una línea de reporte legible para dry-run."""
        icon = {"CONFORME": "✓", "NO_CONFORME": "✗", "SIN_DATOS": "?"}
        v = self.verdict.value
        line = f"  BP: {v} {icon.get(v, '')} ({self.reason})"
        if self.recommendation:
            line += f"\n    → Recomendación: {self.recommendation}"
        if self.convention_conflict:
            line += f"\n    ⚠ Conflicto con convenciones: {self.convention_conflict}"
        return line


class BPEvaluator:
    """Evalúa patrones contra BP oficiales y convenciones.

    Pipeline:
    1. Query ChromaDB con la descripción del patrón → top-k chunks
    2. Construir prompt con chunks + convenciones + patrón
    3. Claude API (o caché) → respuesta estructurada JSON
    4. Parse → BPEvaluation

    Uso:
        evaluator = BPEvaluator(
            bp_loader=bp_loader,
            llm_provider=claude_provider,
            conventions_reader=conventions_reader,
        )
        result = evaluator.evaluate("Entity 'OrdenCompra' with PascalCase naming")
    """

    def __init__(
        self,
        bp_loader: BPLoader,
        llm_provider: LLMProvider,
        conventions_reader: ConventionsReader | None = None,
        decision_logger: DecisionLogger | None = None,
        top_k: int = 5,
    ) -> None:
        self._bp_loader = bp_loader
        self._llm = llm_provider
        self._conventions = conventions_reader
        self._decision_logger = decision_logger
        self._top_k = top_k

    def evaluate(
        self,
        pattern_description: str,
        *,
        category_filter: str | None = None,
        input_hash: str = "",
    ) -> BPEvaluation:
        """Evalúa un patrón contra las BP oficiales.

        Args:
            pattern_description: Descripción del patrón a evaluar
                (ej: "Entity 'OrdenCompra' uses PascalCase naming")
            category_filter: Filtrar chunks por categoría (opcional)
            input_hash: Hash del input original (para logging)

        Returns:
            BPEvaluation con veredicto, razón y recomendación.
        """
        # 1. Query ChromaDB → top-k chunks relevantes
        relevant_chunks = self._bp_loader.query(
            pattern_description,
            n_results=self._top_k,
            category_filter=category_filter,
        )

        # 2. Construir prompt
        user_prompt = self._build_evaluation_prompt(
            pattern_description, relevant_chunks
        )

        # 3. Llamar a LLM
        llm_response: LLMResponse | None = None
        try:
            llm_response = self._llm.send(
                user_prompt,
                system_prompt=EVALUATION_SYSTEM_PROMPT,
                temperature=0.0,
                response_format="json",
            )
            evaluation = self._parse_llm_response(
                llm_response, relevant_chunks, pattern_description
            )
        except Exception as e:
            logger.error("bp_evaluation_llm_error", error=str(e))
            evaluation = BPEvaluation(
                verdict=BPVerdict.SIN_DATOS,
                reason=f"Error en evaluación LLM: {e}",
                pattern_description=pattern_description,
                relevant_chunks=relevant_chunks,
            )

        # 4. Loguear decisión
        if self._decision_logger:
            self._decision_logger.log(
                operation="bp_evaluation",
                input_hash=input_hash,
                bp_verdict=evaluation.verdict,
                pattern_source=(
                    PatternSource.OFFICIAL_BP
                    if evaluation.bp_source
                    else PatternSource.NONE
                ),
                action_taken=self._verdict_to_action(evaluation.verdict),
                warnings=[evaluation.recommendation] if evaluation.recommendation else [],
                llm_model=self._llm.model_name(),
                llm_tokens_used=(
                    llm_response.total_tokens if llm_response is not None else 0
                ),
                cache_hit=llm_response.cache_hit if llm_response is not None else False,
            )

        return evaluation

    def evaluate_batch(
        self,
        patterns: list[str],
        *,
        category_filter: str | None = None,
        input_hash: str = "",
    ) -> list[BPEvaluation]:
        """Evalúa múltiples patrones.

        Args:
            patterns: Lista de descripciones de patrones.
            category_filter: Filtrar chunks por categoría.
            input_hash: Hash del input original.

        Returns:
            Lista de BPEvaluation, una por patrón.
        """
        return [
            self.evaluate(
                pattern,
                category_filter=category_filter,
                input_hash=input_hash,
            )
            for pattern in patterns
        ]

    def _build_evaluation_prompt(
        self,
        pattern_description: str,
        chunks: list[BPChunk],
    ) -> str:
        """Construye el prompt de evaluación con chunks y convenciones."""
        parts: list[str] = []

        # Patrón a evaluar
        parts.append(f"## Patrón a evaluar\n{pattern_description}")

        # Chunks de BP oficiales
        if chunks:
            parts.append("\n## Buenas prácticas oficiales de Mendix (relevantes)")
            for i, chunk in enumerate(chunks, 1):
                parts.append(
                    f"\n### BP {i}: {chunk.section_title} "
                    f"[{chunk.category}/{chunk.severity}]\n{chunk.content}"
                )
        else:
            parts.append(
                "\n## Buenas prácticas oficiales\n"
                "No se encontraron BPs relevantes para este patrón."
            )

        # Convenciones del proyecto
        if self._conventions and self._conventions.is_loaded:
            parts.append(
                "\n## Convenciones del proyecto de referencia (contexto secundario)\n"
                + self._conventions.as_context_string()
            )

        return "\n".join(parts)

    def _parse_llm_response(
        self,
        response: LLMResponse,
        chunks: list[BPChunk],
        pattern_description: str,
    ) -> BPEvaluation:
        """Parsea la respuesta JSON del LLM a BPEvaluation."""
        parsed = response.parsed_json

        if parsed is None:
            logger.warning(
                "llm_response_not_json",
                content=response.content[:200],
            )
            return BPEvaluation(
                verdict=BPVerdict.SIN_DATOS,
                reason="La respuesta del LLM no es JSON válido",
                relevant_chunks=chunks,
                pattern_description=pattern_description,
            )

        # Mapear verdict string a enum
        verdict_str = parsed.get("verdict", "SIN_DATOS").upper()
        try:
            verdict = BPVerdict(verdict_str)
        except ValueError:
            verdict = BPVerdict.SIN_DATOS

        return BPEvaluation(
            verdict=verdict,
            confidence=float(parsed.get("confidence", 0.0)),
            reason=parsed.get("reason", ""),
            recommendation=parsed.get("recommendation"),
            bp_source=parsed.get("bp_source"),
            convention_match=bool(parsed.get("convention_match", False)),
            convention_conflict=parsed.get("convention_conflict"),
            relevant_chunks=chunks,
            pattern_description=pattern_description,
        )

    @staticmethod
    def _verdict_to_action(verdict: BPVerdict) -> str:
        """Mapea veredicto a acción tomada."""
        return {
            BPVerdict.CONFORME: "proceed",
            BPVerdict.NO_CONFORME: "warning_emitted",
            BPVerdict.SIN_DATOS: "proceed_with_warning",
        }[verdict]
