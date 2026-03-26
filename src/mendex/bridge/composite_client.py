"""CompositeSDKClient: delega lecturas a MprDirectReader y escrituras a SubprocessSDKClient.

Permite usar el lector nativo de Python para operaciones de lectura (rápido,
offline) y el bridge Node.js solo para operaciones de escritura que requieren
el Mendix Model SDK.

Uso:
    reader = MprDirectReader()
    writer = SubprocessSDKClient(node_script=Path("mendix_sdk/dist/index.js"))
    client = CompositeSDKClient(reader=reader, writer=writer)

    # Lectura: usa MprDirectReader (~360ms, offline)
    structure = client.read_project_structure(Path("proyecto.mpr"))

    # Escritura: usa SubprocessSDKClient (Node.js)
    client.create_entity(Path("proyecto.mpr"), entity_data)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import structlog

from mendex.bridge.mpr_reader import MprDirectReader
from mendex.bridge.sdk_client import (
    ProjectStructure,
    SDKClient,
    SDKClientError,
    SubprocessSDKClient,
)

logger = structlog.get_logger(__name__)


class CompositeSDKClient(SDKClient):
    """Cliente SDK compuesto: lecturas via Python, escrituras via Node.js.

    Args:
        reader: MprDirectReader para operaciones de lectura.
        writer: SubprocessSDKClient para operaciones de escritura.
                Si es None, las operaciones de escritura lanzan SDKClientError.
    """

    def __init__(
        self,
        reader: MprDirectReader,
        writer: SubprocessSDKClient | None = None,
    ) -> None:
        self._reader = reader
        self._writer = writer

    def ping(self) -> bool:
        """Verifica que el reader esté operativo (siempre True)."""
        return self._reader.ping()

    def read_project_structure(self, mpr_path: Path) -> ProjectStructure:
        """Lee la estructura del proyecto via MprDirectReader (Python puro)."""
        return self._reader.read_project_structure(mpr_path)

    def check_artifact_exists(
        self, mpr_path: Path, artifact_type: str, module: str, name: str
    ) -> bool:
        """Verifica existencia via MprDirectReader (caché O(1))."""
        return self._reader.check_artifact_exists(
            mpr_path, artifact_type, module, name
        )

    def create_entity(
        self, mpr_path: Path, entity_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Crea una entidad via SubprocessSDKClient (Node.js)."""
        self._ensure_writer("create_entity")
        assert self._writer is not None
        return self._writer.create_entity(mpr_path, entity_data)

    def create_page(
        self, mpr_path: Path, page_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Crea una página via SubprocessSDKClient (Node.js)."""
        self._ensure_writer("create_page")
        assert self._writer is not None
        return self._writer.create_page(mpr_path, page_data)

    def create_microflow(
        self, mpr_path: Path, microflow_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Crea un microflow via SubprocessSDKClient (Node.js)."""
        self._ensure_writer("create_microflow")
        assert self._writer is not None
        return self._writer.create_microflow(mpr_path, microflow_data)

    def create_association(
        self, mpr_path: Path, association_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Crea una asociación via SubprocessSDKClient (Node.js)."""
        self._ensure_writer("create_association")
        assert self._writer is not None
        return self._writer.create_association(mpr_path, association_data)

    def _ensure_writer(self, operation: str) -> None:
        """Verifica que el writer esté disponible para operaciones de escritura."""
        if self._writer is None:
            raise SDKClientError(
                f"No se puede ejecutar '{operation}': "
                "SubprocessSDKClient no configurado. "
                "CompositeSDKClient necesita un writer para operaciones de escritura. "
                "Ejecuta: cd mendix_sdk && npm run build"
            )

    def close(self) -> None:
        """Cierra el writer si existe."""
        if self._writer is not None and hasattr(self._writer, "close"):
            self._writer.close()
