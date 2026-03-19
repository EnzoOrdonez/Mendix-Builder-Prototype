"""Carga y chunking de Best Practices oficiales de Mendix.

Lee documentos Markdown de la carpeta knowledge_base/mendix_bp_official/,
los chunkeiza por secciones (H2/H3), y los indexa en ChromaDB con
metadata de categoría y severidad.

Fase 4: Implementación completa.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


# Categorías de BP basadas en el contenido
CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "naming": ["naming", "convention", "name", "prefix", "pascalcase", "camelcase"],
    "security": ["security", "access", "role", "permission", "password", "authentication"],
    "performance": ["performance", "index", "xpath", "retrieve", "cache", "optimize"],
    "architecture": ["architecture", "domain model", "microflow design", "module", "entity design"],
}

# Severidad basada en keywords
SEVERITY_KEYWORDS: dict[str, list[str]] = {
    "critical": ["must", "critical", "never", "always", "required", "mandatory"],
    "warning": ["should", "warning", "recommended", "avoid", "consider"],
    "info": ["can", "may", "optional", "suggestion", "tip"],
}


class BPChunk:
    """Un fragmento de documentación de BP con metadata."""

    def __init__(
        self,
        content: str,
        source_file: str,
        section_title: str,
        category: str = "general",
        severity: str = "info",
        chunk_id: str = "",
    ) -> None:
        self.content = content
        self.source_file = source_file
        self.section_title = section_title
        self.category = category
        self.severity = severity
        self.chunk_id = chunk_id or self._compute_id()

    def _compute_id(self) -> str:
        """Genera un ID determinista basado en el contenido."""
        h = hashlib.sha256(self.content.encode("utf-8")).hexdigest()[:12]
        return f"{self.source_file}::{self.section_title}::{h}"

    @property
    def metadata(self) -> dict[str, str]:
        return {
            "source_file": self.source_file,
            "section_title": self.section_title,
            "category": self.category,
            "severity": self.severity,
        }

    def __repr__(self) -> str:
        return (
            f"BPChunk(section='{self.section_title}', "
            f"cat={self.category}, sev={self.severity}, "
            f"len={len(self.content)})"
        )


class BPLoader:
    """Carga, chunkeiza e indexa documentos de BP en ChromaDB.

    Uso:
        loader = BPLoader(
            docs_path=Path("knowledge_base/mendix_bp_official"),
            chroma_path=Path("knowledge_base/chroma_db"),
        )
        chunks = loader.load_and_chunk()  # Lee Markdown → chunks
        loader.index_chunks(chunks)        # Indexa en ChromaDB
    """

    COLLECTION_NAME = "mendix_best_practices"

    def __init__(
        self,
        docs_path: Path,
        chroma_path: Path,
    ) -> None:
        self._docs_path = docs_path
        self._chroma_path = chroma_path
        self._collection: Any = None

    def load_and_chunk(self) -> list[BPChunk]:
        """Lee todos los archivos Markdown y los chunkeiza por sección.

        Returns:
            Lista de BPChunk listos para indexar.
        """
        chunks: list[BPChunk] = []

        md_files = sorted(self._docs_path.glob("*.md"))
        # Excluir README.md
        md_files = [f for f in md_files if f.name.lower() != "readme.md"]

        if not md_files:
            logger.warning(
                "no_bp_documents_found",
                path=str(self._docs_path),
                hint="Ejecuta: python scripts/download_bp_docs.py",
            )
            return chunks

        for md_file in md_files:
            file_chunks = self._chunk_markdown(md_file)
            chunks.extend(file_chunks)
            logger.debug(
                "file_chunked",
                file=md_file.name,
                chunks=len(file_chunks),
            )

        logger.info(
            "bp_documents_loaded",
            files=len(md_files),
            total_chunks=len(chunks),
        )
        return chunks

    def index_chunks(self, chunks: list[BPChunk]) -> int:
        """Indexa chunks en ChromaDB.

        Crea o reemplaza la colección completa.

        Args:
            chunks: Lista de BPChunk a indexar.

        Returns:
            Número de chunks indexados.
        """
        if not chunks:
            return 0

        collection = self._get_or_create_collection()

        # Preparar datos para ChromaDB
        ids = [c.chunk_id for c in chunks]
        documents = [c.content for c in chunks]
        metadatas = [c.metadata for c in chunks]

        # Upsert (insert or update) en batch
        collection.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
        )

        logger.info("bp_chunks_indexed", count=len(chunks))
        return len(chunks)

    def query(
        self,
        query_text: str,
        n_results: int = 5,
        category_filter: str | None = None,
    ) -> list[BPChunk]:
        """Busca chunks relevantes en ChromaDB.

        Args:
            query_text: Texto de búsqueda.
            n_results: Número máximo de resultados.
            category_filter: Filtrar por categoría (opcional).

        Returns:
            Lista de BPChunk más relevantes.
        """
        collection = self._get_or_create_collection()

        where_filter = None
        if category_filter:
            where_filter = {"category": category_filter}

        try:
            results = collection.query(
                query_texts=[query_text],
                n_results=n_results,
                where=where_filter,
            )
        except Exception as e:
            logger.error("chroma_query_error", error=str(e))
            return []

        chunks: list[BPChunk] = []
        if results and results["documents"]:
            for i, doc in enumerate(results["documents"][0]):
                meta = results["metadatas"][0][i] if results["metadatas"] else {}
                chunk_id = results["ids"][0][i] if results["ids"] else ""
                chunks.append(
                    BPChunk(
                        content=doc,
                        source_file=meta.get("source_file", ""),
                        section_title=meta.get("section_title", ""),
                        category=meta.get("category", "general"),
                        severity=meta.get("severity", "info"),
                        chunk_id=chunk_id,
                    )
                )

        return chunks

    def get_collection_stats(self) -> dict[str, Any]:
        """Retorna estadísticas de la colección ChromaDB.

        Returns:
            Dict con count, categories, severities.
        """
        collection = self._get_or_create_collection()
        count = collection.count()

        return {
            "total_chunks": count,
            "collection_name": self.COLLECTION_NAME,
            "chroma_path": str(self._chroma_path),
        }

    def clear(self) -> None:
        """Elimina la colección ChromaDB."""
        client = self._get_chroma_client()
        try:
            client.delete_collection(self.COLLECTION_NAME)
            self._collection = None
            logger.info("bp_collection_cleared")
        except Exception:
            pass

    def _get_chroma_client(self) -> Any:
        """Obtiene el cliente ChromaDB con persistencia en disco."""
        try:
            import chromadb
        except ImportError:
            raise RuntimeError(
                "ChromaDB no instalado. Ejecuta: pip install chromadb"
            )

        self._chroma_path.mkdir(parents=True, exist_ok=True)
        return chromadb.PersistentClient(path=str(self._chroma_path))

    def _get_or_create_collection(self) -> Any:
        """Obtiene o crea la colección ChromaDB."""
        if self._collection is not None:
            return self._collection

        client = self._get_chroma_client()
        self._collection = client.get_or_create_collection(
            name=self.COLLECTION_NAME,
            metadata={"description": "Mendix Best Practices for RAG evaluation"},
        )
        return self._collection

    def _chunk_markdown(self, md_file: Path) -> list[BPChunk]:
        """Chunkeiza un archivo Markdown por secciones H2/H3.

        Cada sección se convierte en un chunk independiente con metadata.
        """
        content = md_file.read_text(encoding="utf-8")
        file_name = md_file.stem

        sections = self._split_by_headers(content)
        chunks: list[BPChunk] = []

        for section_title, section_content in sections:
            # Ignorar secciones vacías o muy cortas
            clean = section_content.strip()
            if len(clean) < 20:
                continue

            category = self._detect_category(section_title + " " + clean)
            severity = self._detect_severity(clean)

            chunks.append(
                BPChunk(
                    content=clean,
                    source_file=file_name,
                    section_title=section_title,
                    category=category,
                    severity=severity,
                )
            )

        return chunks

    @staticmethod
    def _split_by_headers(content: str) -> list[tuple[str, str]]:
        """Divide el contenido Markdown por headers H2 y H3.

        Returns:
            Lista de (título_sección, contenido_sección).
        """
        # Regex para H1, H2, H3
        header_pattern = re.compile(r"^(#{1,3})\s+(.+)$", re.MULTILINE)

        sections: list[tuple[str, str]] = []
        matches = list(header_pattern.finditer(content))

        if not matches:
            # Sin headers → todo es un chunk
            return [("Document", content)]

        for i, match in enumerate(matches):
            title = match.group(2).strip()
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
            section_content = content[start:end].strip()

            if section_content:
                sections.append((title, section_content))

        return sections

    @staticmethod
    def _detect_category(text: str) -> str:
        """Detecta la categoría de BP basada en keywords."""
        text_lower = text.lower()
        scores: dict[str, int] = {}

        for category, keywords in CATEGORY_KEYWORDS.items():
            scores[category] = sum(1 for kw in keywords if kw in text_lower)

        if not scores or max(scores.values()) == 0:
            return "general"

        return max(scores, key=lambda k: scores[k])

    @staticmethod
    def _detect_severity(text: str) -> str:
        """Detecta la severidad de la BP basada en keywords."""
        text_lower = text.lower()
        scores: dict[str, int] = {}

        for severity, keywords in SEVERITY_KEYWORDS.items():
            scores[severity] = sum(1 for kw in keywords if kw in text_lower)

        if not scores or max(scores.values()) == 0:
            return "info"

        return max(scores, key=lambda k: scores[k])
