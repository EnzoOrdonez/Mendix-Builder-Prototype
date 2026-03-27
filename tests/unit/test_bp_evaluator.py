"""Tests unitarios para BPLoader y BPEvaluator.

Fase 4: Cobertura del pipeline RAG de buenas prácticas.

Nota: Tests de BPLoader que involucran ChromaDB requieren chromadb instalado.
Tests de BPEvaluator usan MockLLMProvider para evitar llamadas API reales.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from mendex.knowledge.bp_loader import BPChunk, BPLoader
from mendex.knowledge.bp_evaluator import (
    BPEvaluation,
    BPEvaluator,
    EVALUATION_SYSTEM_PROMPT,
)
from mendex.knowledge.conventions_reader import ConventionsReader
from mendex.llm.provider import LLMResponse, MockLLMProvider
from mendex.logging.decision_logger import BPVerdict, DecisionLogger


# ─── Fixtures ────────────────────────────────────────────────────


@pytest.fixture
def bp_docs_path(tmp_path: Path) -> Path:
    """Crea documentos BP de prueba."""
    docs = tmp_path / "bp_docs"
    docs.mkdir()

    # Naming conventions doc
    (docs / "naming_conventions.md").write_text(
        "# Naming Conventions\n\n"
        "## Entity Naming\n\n"
        "Entities should use PascalCase. Each entity name should be a "
        "singular noun. Do not use abbreviations. This is a critical "
        "requirement that must always be followed.\n\n"
        "### Examples\n\n"
        "- Good: SalesOrder, CustomerContact\n"
        "- Bad: tbl_sales_order, SO\n\n"
        "## Attribute Naming\n\n"
        "Attributes should also use PascalCase. Boolean attributes should "
        "start with Is, Has, or Can.\n\n"
        "## Microflow Naming\n\n"
        "Microflows should use prefix pattern: ACT_, VAL_, SUB_, DS_. "
        "Pattern: {Prefix}_{EntityName}_{Action}\n",
        encoding="utf-8",
    )

    # Security doc
    (docs / "security.md").write_text(
        "# Security Best Practices\n\n"
        "## Access Rules\n\n"
        "Every persistable entity MUST have explicit access rules. "
        "This is critical. Never leave entities without access rules. "
        "Follow deny-by-default principle.\n\n"
        "## Password Security\n\n"
        "Always use HashedString for password fields. Never store "
        "passwords in plain text.\n",
        encoding="utf-8",
    )

    # README (should be excluded from chunking)
    (docs / "README.md").write_text("# This is a readme\n", encoding="utf-8")

    return docs


@pytest.fixture
def chroma_path(tmp_path: Path) -> Path:
    return tmp_path / "chroma_db"


@pytest.fixture
def bp_loader(bp_docs_path: Path, chroma_path: Path) -> BPLoader:
    return BPLoader(docs_path=bp_docs_path, chroma_path=chroma_path)


@pytest.fixture
def conventions_yaml(tmp_path: Path) -> Path:
    """Crea un YAML de convenciones para tests."""
    yaml_path = tmp_path / "conventions.yaml"
    data = {
        "project": {
            "name": "MiProyecto",
            "mendix_version": "10.24.16",
            "extracted_at": "2026-01-15T10:00:00Z",
            "mpr_hash": "abc123",
        },
        "naming": {
            "entities": {"pattern": "PascalCase", "prefix": "", "examples": ["OrdenCompra"]},
            "attributes": {"pattern": "PascalCase", "examples": ["MontoTotal"]},
            "microflows": {"pattern": "{Prefix}_{Entity}_{Action}", "examples": ["ACT_Orden_Guardar"]},
            "pages": {"pattern": "{Entity}_{Action}", "examples": ["Orden_NewEdit"]},
        },
        "modules": [{"name": "Operaciones", "entity_count": 10, "description": ""}],
        "common_patterns": {
            "access_rules": {"roles": ["Admin", "User"], "default_policy": "deny_all_then_grant"},
            "validation": {"common_types": ["required"], "error_message_language": "es"},
            "page_layouts": {"default": "Atlas_Default", "popup": "PopupLayout"},
        },
        "data_types": {"most_used": ["String", "DateTime"], "enumerations": []},
    }
    yaml_path.write_text(yaml.dump(data), encoding="utf-8")
    return yaml_path


@pytest.fixture
def conventions_reader(conventions_yaml: Path) -> ConventionsReader:
    reader = ConventionsReader(conventions_yaml)
    reader.load()
    return reader


def _mock_conforme_provider() -> MockLLMProvider:
    return MockLLMProvider(
        default_response=json.dumps({
            "verdict": "CONFORME",
            "confidence": 0.95,
            "reason": "Entity uses PascalCase naming as recommended",
            "recommendation": None,
            "bp_source": "Naming Conventions - Entity Naming",
            "convention_match": True,
            "convention_conflict": None,
        })
    )


def _mock_no_conforme_provider() -> MockLLMProvider:
    return MockLLMProvider(
        default_response=json.dumps({
            "verdict": "NO_CONFORME",
            "confidence": 0.90,
            "reason": "Entity uses snake_case instead of PascalCase",
            "recommendation": "Rename entity to PascalCase (e.g., 'OrdenCompra' instead of 'orden_compra')",
            "bp_source": "Naming Conventions - Entity Naming",
            "convention_match": False,
            "convention_conflict": None,
        })
    )


def _mock_sin_datos_provider() -> MockLLMProvider:
    return MockLLMProvider(
        default_response=json.dumps({
            "verdict": "SIN_DATOS",
            "confidence": 0.3,
            "reason": "No official BP found for this specific pattern",
            "recommendation": None,
            "bp_source": None,
            "convention_match": True,
            "convention_conflict": None,
        })
    )


# ─── Tests de BPChunk ───────────────────────────────────────────


class TestBPChunk:
    def test_creates_with_metadata(self) -> None:
        chunk = BPChunk(
            content="Entities must use PascalCase",
            source_file="naming",
            section_title="Entity Naming",
            category="naming",
            severity="critical",
        )
        assert chunk.category == "naming"
        assert chunk.severity == "critical"
        assert chunk.metadata["source_file"] == "naming"

    def test_deterministic_id(self) -> None:
        c1 = BPChunk(content="same", source_file="f", section_title="s")
        c2 = BPChunk(content="same", source_file="f", section_title="s")
        assert c1.chunk_id == c2.chunk_id

    def test_different_content_different_id(self) -> None:
        c1 = BPChunk(content="content1", source_file="f", section_title="s")
        c2 = BPChunk(content="content2", source_file="f", section_title="s")
        assert c1.chunk_id != c2.chunk_id


# ─── Tests de BPLoader (sin ChromaDB) ───────────────────────────


class TestBPLoaderChunking:
    def test_load_and_chunk_reads_files(self, bp_loader: BPLoader) -> None:
        """Carga documentos MD y produce chunks."""
        chunks = bp_loader.load_and_chunk()
        assert len(chunks) > 0

    def test_excludes_readme(self, bp_loader: BPLoader) -> None:
        """README.md se excluye del chunking."""
        chunks = bp_loader.load_and_chunk()
        sources = {c.source_file for c in chunks}
        assert "README" not in sources

    def test_chunks_have_metadata(self, bp_loader: BPLoader) -> None:
        """Cada chunk tiene metadata de categoría y severidad."""
        chunks = bp_loader.load_and_chunk()
        for chunk in chunks:
            assert chunk.category in {"naming", "security", "performance", "architecture", "general"}
            assert chunk.severity in {"critical", "warning", "info"}
            assert chunk.source_file
            assert chunk.section_title

    def test_chunks_from_naming_doc(self, bp_loader: BPLoader) -> None:
        """El doc de naming genera chunks con categoría naming."""
        chunks = bp_loader.load_and_chunk()
        naming_chunks = [c for c in chunks if c.source_file == "naming_conventions"]
        assert len(naming_chunks) >= 2  # Al menos entity y attribute naming

    def test_chunks_from_security_doc(self, bp_loader: BPLoader) -> None:
        """El doc de security genera chunks con categoría security."""
        chunks = bp_loader.load_and_chunk()
        sec_chunks = [c for c in chunks if c.source_file == "security"]
        assert len(sec_chunks) >= 1

    def test_empty_directory(self, tmp_path: Path) -> None:
        """Directorio vacío retorna lista vacía sin error."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        loader = BPLoader(docs_path=empty_dir, chroma_path=tmp_path / "chroma")
        chunks = loader.load_and_chunk()
        assert chunks == []

    def test_split_by_headers(self) -> None:
        """Divide correctamente por headers H2/H3."""
        content = (
            "# Title\n\nIntro\n\n"
            "## Section 1\n\nContent 1\n\n"
            "### Subsection 1.1\n\nContent 1.1\n\n"
            "## Section 2\n\nContent 2\n"
        )
        sections = BPLoader._split_by_headers(content)
        titles = [t for t, _ in sections]
        assert "Section 1" in titles
        assert "Section 2" in titles

    def test_detect_category_naming(self) -> None:
        assert BPLoader._detect_category("naming conventions for entities") == "naming"

    def test_detect_category_security(self) -> None:
        assert BPLoader._detect_category("access rules and security roles") == "security"

    def test_detect_severity_critical(self) -> None:
        assert BPLoader._detect_severity("you MUST always define access rules") == "critical"

    def test_detect_severity_warning(self) -> None:
        assert BPLoader._detect_severity("you should avoid long microflows") == "warning"


# ─── Tests de BPLoader con ChromaDB ─────────────────────────────


class TestBPLoaderWithChroma:
    """Tests que requieren chromadb instalado."""

    @pytest.fixture(autouse=True)
    def _check_chromadb(self) -> None:
        try:
            import chromadb  # noqa: F401
        except ImportError:
            pytest.skip("chromadb not installed")

    def test_index_and_query(self, bp_loader: BPLoader) -> None:
        """Indexa chunks y los recupera via query."""
        chunks = bp_loader.load_and_chunk()
        indexed = bp_loader.index_chunks(chunks)
        assert indexed > 0

        results = bp_loader.query("entity naming PascalCase")
        assert len(results) > 0
        # Al menos un resultado debe ser de naming
        categories = {r.category for r in results}
        assert "naming" in categories

    def test_query_security(self, bp_loader: BPLoader) -> None:
        """Busca chunks de seguridad."""
        chunks = bp_loader.load_and_chunk()
        bp_loader.index_chunks(chunks)

        results = bp_loader.query("access rules security")
        assert len(results) > 0

    def test_query_with_category_filter(self, bp_loader: BPLoader) -> None:
        """Filtra resultados por categoría."""
        chunks = bp_loader.load_and_chunk()
        bp_loader.index_chunks(chunks)

        results = bp_loader.query(
            "naming conventions",
            category_filter="security",
        )
        for r in results:
            assert r.category == "security"

    def test_collection_stats(self, bp_loader: BPLoader) -> None:
        chunks = bp_loader.load_and_chunk()
        bp_loader.index_chunks(chunks)

        stats = bp_loader.get_collection_stats()
        assert stats["total_chunks"] > 0

    def test_clear_collection(self, bp_loader: BPLoader) -> None:
        chunks = bp_loader.load_and_chunk()
        bp_loader.index_chunks(chunks)
        bp_loader.clear()

        stats = bp_loader.get_collection_stats()
        assert stats["total_chunks"] == 0

    def test_idempotent_index(self, bp_loader: BPLoader) -> None:
        """Indexar dos veces no duplica chunks (upsert)."""
        chunks = bp_loader.load_and_chunk()
        bp_loader.index_chunks(chunks)
        count1 = bp_loader.get_collection_stats()["total_chunks"]

        bp_loader.index_chunks(chunks)
        count2 = bp_loader.get_collection_stats()["total_chunks"]

        assert count1 == count2


# ─── Tests de BPEvaluator ───────────────────────────────────────


class TestBPEvaluator:
    """Tests del evaluador de BP usando MockLLMProvider."""

    @pytest.fixture(autouse=True)
    def _check_chromadb(self) -> None:
        try:
            import chromadb  # noqa: F401
        except ImportError:
            pytest.skip("chromadb not installed")

    @pytest.fixture
    def indexed_loader(self, bp_loader: BPLoader) -> BPLoader:
        chunks = bp_loader.load_and_chunk()
        bp_loader.index_chunks(chunks)
        return bp_loader

    def test_evaluate_conforme(
        self, indexed_loader: BPLoader, conventions_reader: ConventionsReader
    ) -> None:
        """Patrón conforme retorna CONFORME."""
        evaluator = BPEvaluator(
            bp_loader=indexed_loader,
            llm_provider=_mock_conforme_provider(),
            conventions_reader=conventions_reader,
        )
        result = evaluator.evaluate(
            "Entity 'OrdenCompra' uses PascalCase naming"
        )
        assert result.verdict == BPVerdict.CONFORME
        assert result.confidence > 0.5
        assert result.recommendation is None

    def test_evaluate_no_conforme(
        self, indexed_loader: BPLoader, conventions_reader: ConventionsReader
    ) -> None:
        """Patrón no conforme retorna NO_CONFORME con recomendación."""
        evaluator = BPEvaluator(
            bp_loader=indexed_loader,
            llm_provider=_mock_no_conforme_provider(),
            conventions_reader=conventions_reader,
        )
        result = evaluator.evaluate(
            "Entity 'orden_compra' uses snake_case naming"
        )
        assert result.verdict == BPVerdict.NO_CONFORME
        assert result.recommendation is not None
        assert "PascalCase" in result.recommendation

    def test_evaluate_sin_datos(
        self, indexed_loader: BPLoader
    ) -> None:
        """Patrón sin BP relevante retorna SIN_DATOS."""
        evaluator = BPEvaluator(
            bp_loader=indexed_loader,
            llm_provider=_mock_sin_datos_provider(),
        )
        result = evaluator.evaluate(
            "Custom widget 'XyzChart' uses proprietary config format"
        )
        assert result.verdict == BPVerdict.SIN_DATOS

    def test_evaluate_includes_relevant_chunks(
        self, indexed_loader: BPLoader
    ) -> None:
        """La evaluación incluye los chunks relevantes consultados."""
        evaluator = BPEvaluator(
            bp_loader=indexed_loader,
            llm_provider=_mock_conforme_provider(),
        )
        result = evaluator.evaluate("Entity naming in PascalCase")
        assert len(result.relevant_chunks) > 0

    def test_evaluate_with_decision_logger(
        self, indexed_loader: BPLoader, tmp_path: Path
    ) -> None:
        """La evaluación se registra en el decision logger."""
        decision_logger = DecisionLogger(tmp_path / "decisions.jsonl")
        evaluator = BPEvaluator(
            bp_loader=indexed_loader,
            llm_provider=_mock_conforme_provider(),
            decision_logger=decision_logger,
        )
        evaluator.evaluate("Test pattern", input_hash="test123")

        entries = decision_logger.read_entries()
        assert len(entries) == 1
        assert entries[0].operation == "bp_evaluation"
        assert entries[0].bp_verdict == BPVerdict.CONFORME

    def test_evaluate_batch(
        self, indexed_loader: BPLoader
    ) -> None:
        """evaluate_batch evalúa múltiples patrones."""
        evaluator = BPEvaluator(
            bp_loader=indexed_loader,
            llm_provider=_mock_conforme_provider(),
        )
        results = evaluator.evaluate_batch([
            "Entity 'A' PascalCase",
            "Entity 'B' PascalCase",
            "Entity 'C' PascalCase",
        ])
        assert len(results) == 3
        assert all(r.verdict == BPVerdict.CONFORME for r in results)

    def test_evaluation_to_dict(self) -> None:
        """BPEvaluation se serializa a dict."""
        ev = BPEvaluation(
            verdict=BPVerdict.NO_CONFORME,
            confidence=0.85,
            reason="Wrong naming",
            recommendation="Use PascalCase",
        )
        d = ev.to_dict()
        assert d["verdict"] == "NO_CONFORME"
        assert d["confidence"] == 0.85

    def test_evaluation_report_line(self) -> None:
        """as_report_line genera texto legible."""
        ev = BPEvaluation(
            verdict=BPVerdict.NO_CONFORME,
            reason="snake_case detected",
            recommendation="Use PascalCase",
        )
        line = ev.as_report_line()
        assert "NO_CONFORME" in line
        assert "PascalCase" in line
        assert "✗" in line

    def test_llm_error_returns_sin_datos(
        self, indexed_loader: BPLoader
    ) -> None:
        """Si el LLM falla, retorna SIN_DATOS con error."""
        # Mock que retorna JSON inválido
        bad_provider = MockLLMProvider(default_response="not json at all")
        evaluator = BPEvaluator(
            bp_loader=indexed_loader,
            llm_provider=bad_provider,
        )
        result = evaluator.evaluate("Test pattern")
        assert result.verdict == BPVerdict.SIN_DATOS
