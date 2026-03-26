"""Bridge Python → Node.js para operaciones del Mendix Model SDK.

Define SDKClient como ABC para desacoplar el agente del mecanismo
de comunicación con el Model SDK. La implementación actual usa
subprocess con JSON-RPC via stdio.

Implementaciones:
- SubprocessSDKClient: Node.js subprocess con JSON-RPC stdio
- MockSDKClient: Para tests, retorna datos predefinidos
- (Futuro) AgentsKitClient: Para Mendix 11 via Agents Kit API

Fase 3: Implementación del bridge con read_project_structure.
Fase 8: Agregar create_entity.
Fase 9: Agregar create_page, create_microflow.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class ModuleInfo:
    """Información de un módulo Mendix extraída del .mpr."""

    name: str
    entities: list[EntityInfo] = field(default_factory=list)
    pages: list[str] = field(default_factory=list)
    microflows: list[str] = field(default_factory=list)

    @property
    def entity_count(self) -> int:
        return len(self.entities)


@dataclass
class EntityInfo:
    """Información de una entidad extraída del .mpr."""

    name: str
    attributes: list[str] = field(default_factory=list)


@dataclass
class SecurityInfo:
    """Información de seguridad extraída del .mpr."""

    roles: list[str] = field(default_factory=list)


@dataclass
class ProjectStructure:
    """Estructura completa de un proyecto Mendix extraída del .mpr."""

    modules: list[ModuleInfo] = field(default_factory=list)
    security: SecurityInfo = field(default_factory=SecurityInfo)

    @property
    def all_entity_names(self) -> list[str]:
        return [e.name for m in self.modules for e in m.entities]

    @property
    def all_page_names(self) -> list[str]:
        return [p for m in self.modules for p in m.pages]

    @property
    def all_microflow_names(self) -> list[str]:
        return [mf for m in self.modules for mf in m.microflows]

    @property
    def all_attribute_names(self) -> list[str]:
        return [a for m in self.modules for e in m.entities for a in e.attributes]


class SDKClientError(Exception):
    """Error en la comunicación con el Mendix Model SDK."""


class SDKClient(ABC):
    """Interfaz abstracta para operaciones del Mendix Model SDK.

    Fase 3: read_project_structure, check_artifact_exists, ping.
    Fase 8: create_entity.
    Fase 9: create_page, create_microflow.
    """

    @abstractmethod
    def read_project_structure(self, mpr_path: Path) -> ProjectStructure:
        """Lee la estructura completa de un proyecto .mpr."""
        ...

    @abstractmethod
    def check_artifact_exists(
        self, mpr_path: Path, artifact_type: str, module: str, name: str
    ) -> bool:
        """Verifica si un artefacto ya existe en el .mpr."""
        ...

    @abstractmethod
    def ping(self) -> bool:
        """Verifica que el bridge esté operativo."""
        ...

    @abstractmethod
    def create_entity(
        self,
        mpr_path: Path,
        entity_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Crea una entidad con atributos y reglas de acceso en el .mpr.

        Args:
            mpr_path: Path al .mpr.
            entity_data: Dict con name, module, attributes, access_rules, is_persistable.

        Returns:
            Dict con status y detalles de la entidad creada.
        """
        ...

    @abstractmethod
    def create_page(
        self,
        mpr_path: Path,
        page_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Crea una página en el .mpr.

        Args:
            mpr_path: Path al .mpr.
            page_data: Dict con name, page_type, entity, module, title, layout.

        Returns:
            Dict con status y detalles de la página creada.
        """
        ...

    @abstractmethod
    def create_microflow(
        self,
        mpr_path: Path,
        microflow_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Crea un microflow en el .mpr.

        Args:
            mpr_path: Path al .mpr.
            microflow_data: Dict con name, microflow_type, entity, module, logic_description.

        Returns:
            Dict con status y detalles del microflow creado.
        """
        ...

    @abstractmethod
    def create_association(
        self,
        mpr_path: Path,
        association_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Crea una asociación entre dos entidades en el .mpr.

        Args:
            mpr_path: Path al .mpr.
            association_data: Dict con name, parent_entity, child_entity,
                association_type, owner, cascade_delete, is_lookup.

        Returns:
            Dict con status y detalles de la asociación creada.
        """
        ...


class SubprocessSDKClient(SDKClient):
    """Implementación de SDKClient via subprocess Node.js con JSON-RPC stdio.

    Mantiene un proceso Node.js vivo durante toda la sesión para evitar
    el costo de spawn por operación.

    Uso:
        client = SubprocessSDKClient(node_script=Path("mendix_sdk/dist/index.js"))
        structure = client.read_project_structure(Path("proyecto.mpr"))
    """

    def __init__(self, node_script: Path, app_id: str = "") -> None:
        self._node_script = node_script
        self._app_id = app_id or os.environ.get("MENDIX_APP_ID", "")
        self._process: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._request_id = 0

    def _ensure_process(self) -> subprocess.Popen:
        """Inicia el proceso Node.js si no está corriendo."""
        if self._process is not None and self._process.poll() is None:
            return self._process

        if not self._node_script.exists():
            raise SDKClientError(
                f"Script Node.js no encontrado: {self._node_script}. "
                "Ejecuta: cd mendix_sdk && npm run build"
            )

        try:
            self._process = subprocess.Popen(
                ["node", str(self._node_script)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            logger.info("sdk_bridge_started", script=str(self._node_script))
        except FileNotFoundError:
            raise SDKClientError(
                "Node.js no encontrado. Asegúrate de que 'node' está en el PATH."
            )

        return self._process

    def _send_request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        """Envía un request JSON-RPC y espera la respuesta."""
        with self._lock:
            process = self._ensure_process()
            assert process.stdin is not None
            assert process.stdout is not None

            self._request_id += 1
            request = {
                "jsonrpc": "2.0",
                "id": self._request_id,
                "method": method,
                "params": params or {},
            }

            try:
                process.stdin.write(json.dumps(request) + "\n")
                process.stdin.flush()

                response_line = process.stdout.readline()
                if not response_line:
                    raise SDKClientError("El proceso Node.js cerró la conexión.")

                response = json.loads(response_line)

                if "error" in response and response["error"]:
                    err = response["error"]
                    raise SDKClientError(
                        f"SDK error [{err.get('code', '?')}]: {err.get('message', 'Unknown')}"
                    )

                return response.get("result")

            except json.JSONDecodeError as e:
                raise SDKClientError(f"Respuesta JSON inválida del SDK: {e}") from e

    def ping(self) -> bool:
        try:
            result = self._send_request("ping")
            return result.get("status") == "ok"
        except SDKClientError:
            return False

    def read_project_structure(self, mpr_path: Path) -> ProjectStructure:
        result = self._send_request(
            "readProjectStructure",
            {"appId": self._app_id, "mprPath": str(mpr_path.resolve())},
        )
        return self._parse_project_structure(result)

    def check_artifact_exists(
        self, mpr_path: Path, artifact_type: str, module: str, name: str
    ) -> bool:
        result = self._send_request(
            "checkArtifactExists",
            {
                "appId": self._app_id,
                "artifactType": artifact_type,
                "module": module,
                "name": name,
            },
        )
        return bool(result.get("exists", False))

    def create_entity(
        self, mpr_path: Path, entity_data: dict[str, Any]
    ) -> dict[str, Any]:
        result = self._send_request(
            "createEntity",
            {"appId": self._app_id, "entity": entity_data},
        )
        return result or {}

    def create_page(
        self, mpr_path: Path, page_data: dict[str, Any]
    ) -> dict[str, Any]:
        result = self._send_request(
            "createPage",
            {"appId": self._app_id, "page": page_data},
        )
        return result or {}

    def create_microflow(
        self, mpr_path: Path, microflow_data: dict[str, Any]
    ) -> dict[str, Any]:
        result = self._send_request(
            "createMicroflow",
            {"appId": self._app_id, "microflow": microflow_data},
        )
        return result or {}

    def create_association(
        self, mpr_path: Path, association_data: dict[str, Any]
    ) -> dict[str, Any]:
        result = self._send_request(
            "createAssociation",
            {"appId": self._app_id, "association": association_data},
        )
        return result or {}

    def commit_session(self, branch_name: str = "main") -> dict[str, Any]:
        """Commits all pending changes to the Mendix repository."""
        result = self._send_request(
            "commitSession",
            {"branchName": branch_name},
        )
        return result or {}

    def open_session(self, branch_name: str = "main") -> dict[str, Any]:
        """Opens a working copy session for the configured app."""
        result = self._send_request(
            "openSession",
            {"appId": self._app_id, "branchName": branch_name},
        )
        return result or {}

    def close(self) -> None:
        """Cierra el proceso Node.js."""
        if self._process is not None and self._process.poll() is None:
            self._process.terminate()
            self._process.wait(timeout=5)
            logger.info("sdk_bridge_closed")
        self._process = None

    def __del__(self) -> None:
        self.close()

    @staticmethod
    def _parse_project_structure(data: dict[str, Any]) -> ProjectStructure:
        """Parsea la respuesta JSON del SDK a ProjectStructure."""
        modules: list[ModuleInfo] = []
        for mod_data in data.get("modules", []):
            entities = [
                EntityInfo(
                    name=e.get("name", ""),
                    attributes=e.get("attributes", []),
                )
                for e in mod_data.get("entities", [])
            ]
            modules.append(
                ModuleInfo(
                    name=mod_data.get("name", ""),
                    entities=entities,
                    pages=mod_data.get("pages", []),
                    microflows=mod_data.get("microflows", []),
                )
            )

        security = SecurityInfo(
            roles=data.get("security", {}).get("roles", [])
        )

        return ProjectStructure(modules=modules, security=security)


class MockSDKClient(SDKClient):
    """Cliente SDK mock para tests. Retorna estructuras predefinidas.

    Registra todas las operaciones de creación para verificación en tests.
    """

    def __init__(
        self,
        project_structure: ProjectStructure | None = None,
        existing_artifacts: set[str] | None = None,
    ) -> None:
        self._structure = project_structure or ProjectStructure()
        self._existing = existing_artifacts or set()
        self.created_entities: list[dict[str, Any]] = []
        self.created_pages: list[dict[str, Any]] = []
        self.created_microflows: list[dict[str, Any]] = []
        self.created_associations: list[dict[str, Any]] = []

    def ping(self) -> bool:
        return True

    def read_project_structure(self, mpr_path: Path) -> ProjectStructure:
        return self._structure

    def check_artifact_exists(
        self, mpr_path: Path, artifact_type: str, module: str, name: str
    ) -> bool:
        key = f"{artifact_type}:{module}.{name}"
        return key in self._existing

    def create_entity(
        self, mpr_path: Path, entity_data: dict[str, Any]
    ) -> dict[str, Any]:
        self.created_entities.append(entity_data)
        name = entity_data.get("name", "unknown")
        module = entity_data.get("module", "unknown")
        # Register as existing after creation
        self._existing.add(f"entity:{module}.{name}")
        return {
            "status": "created",
            "name": name,
            "module": module,
            "attributes_count": len(entity_data.get("attributes", [])),
        }

    def create_page(
        self, mpr_path: Path, page_data: dict[str, Any]
    ) -> dict[str, Any]:
        self.created_pages.append(page_data)
        name = page_data.get("name", "unknown")
        module = page_data.get("module", "unknown")
        self._existing.add(f"page:{module}.{name}")
        return {"status": "created", "name": name, "module": module}

    def create_microflow(
        self, mpr_path: Path, microflow_data: dict[str, Any]
    ) -> dict[str, Any]:
        self.created_microflows.append(microflow_data)
        name = microflow_data.get("name", "unknown")
        module = microflow_data.get("module", "unknown")
        self._existing.add(f"microflow:{module}.{name}")
        return {"status": "created", "name": name, "module": module}

    def create_association(
        self, mpr_path: Path, association_data: dict[str, Any]
    ) -> dict[str, Any]:
        self.created_associations.append(association_data)
        name = association_data.get("name", "unknown")
        return {"status": "created", "name": name}
