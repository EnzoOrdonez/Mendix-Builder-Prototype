"""Lector de project_conventions.yaml.

Carga, valida y provee acceso a las convenciones del proyecto de
referencia. Fuente de contexto secundario para el agente.

Fase 3: Implementación completa.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import structlog
import yaml

logger = structlog.get_logger(__name__)


class ConventionsReaderError(Exception):
    """Error al leer o parsear las convenciones."""


class ConventionsReader:
    """Lee y provee acceso al project_conventions.yaml.

    Carga el archivo una vez y ofrece métodos para consultar
    patrones específicos. Calcula hash del contenido para
    invalidación de caché LLM.

    Uso:
        reader = ConventionsReader(Path("conventions/project_conventions.yaml"))
        reader.load()

        pattern = reader.entity_naming_pattern  # "PascalCase"
        roles = reader.security_roles  # ["Administrator", "User"]
        hash = reader.content_hash  # SHA-256 del archivo
    """

    def __init__(self, conventions_path: Path) -> None:
        self._path = conventions_path
        self._data: dict[str, Any] = {}
        self._content_hash: str = ""
        self._loaded: bool = False

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    @property
    def content_hash(self) -> str:
        """Hash SHA-256 del contenido del archivo.

        Útil para invalidar el caché LLM cuando las convenciones cambian.
        """
        if not self._loaded:
            raise ConventionsReaderError("Convenciones no cargadas. Ejecuta load() primero.")
        return self._content_hash

    @property
    def raw_data(self) -> dict[str, Any]:
        """Datos crudos del YAML."""
        self._ensure_loaded()
        return self._data

    def load(self) -> None:
        """Carga y parsea el archivo YAML.

        Raises:
            ConventionsReaderError: Si el archivo no existe o es inválido.
        """
        if not self._path.exists():
            raise ConventionsReaderError(
                f"Archivo de convenciones no encontrado: {self._path}. "
                "Ejecuta: mendex refresh-conventions --mpr <path>"
            )

        try:
            raw_content = self._path.read_bytes()
            self._content_hash = hashlib.sha256(raw_content).hexdigest()
            self._data = yaml.safe_load(raw_content.decode("utf-8")) or {}
        except yaml.YAMLError as e:
            raise ConventionsReaderError(
                f"Error parseando {self._path}: {e}"
            ) from e

        self._loaded = True
        logger.info(
            "conventions_loaded",
            path=str(self._path),
            hash=self._content_hash[:16],
            project=self.project_name,
        )

    def reload(self) -> bool:
        """Recarga el archivo y retorna True si el contenido cambió.

        Returns:
            True si el hash cambió (contenido modificado), False si no.
        """
        old_hash = self._content_hash
        self.load()
        return self._content_hash != old_hash

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            raise ConventionsReaderError("Convenciones no cargadas. Ejecuta load() primero.")

    # ─── Accessors de proyecto ───────────────────────────────────

    @property
    def project_name(self) -> str:
        self._ensure_loaded()
        return self._data.get("project", {}).get("name", "")

    @property
    def mendix_version(self) -> str:
        self._ensure_loaded()
        return self._data.get("project", {}).get("mendix_version", "")

    @property
    def mpr_hash(self) -> str:
        self._ensure_loaded()
        return self._data.get("project", {}).get("mpr_hash", "")

    # ─── Accessors de naming ─────────────────────────────────────

    @property
    def entity_naming_pattern(self) -> str:
        self._ensure_loaded()
        return self._data.get("naming", {}).get("entities", {}).get("pattern", "PascalCase")

    @property
    def entity_naming_prefix(self) -> str:
        self._ensure_loaded()
        return self._data.get("naming", {}).get("entities", {}).get("prefix", "")

    @property
    def entity_naming_examples(self) -> list[str]:
        self._ensure_loaded()
        return self._data.get("naming", {}).get("entities", {}).get("examples", [])

    @property
    def attribute_naming_pattern(self) -> str:
        self._ensure_loaded()
        return self._data.get("naming", {}).get("attributes", {}).get("pattern", "PascalCase")

    @property
    def microflow_naming_pattern(self) -> str:
        self._ensure_loaded()
        return self._data.get("naming", {}).get("microflows", {}).get("pattern", "")

    @property
    def page_naming_pattern(self) -> str:
        self._ensure_loaded()
        return self._data.get("naming", {}).get("pages", {}).get("pattern", "")

    # ─── Accessors de módulos ────────────────────────────────────

    @property
    def modules(self) -> list[dict[str, Any]]:
        self._ensure_loaded()
        return self._data.get("modules", [])

    @property
    def module_names(self) -> list[str]:
        return [m.get("name", "") for m in self.modules]

    # ─── Accessors de seguridad ──────────────────────────────────

    @property
    def security_roles(self) -> list[str]:
        self._ensure_loaded()
        return (
            self._data
            .get("common_patterns", {})
            .get("access_rules", {})
            .get("roles", [])
        )

    @property
    def default_access_policy(self) -> str:
        self._ensure_loaded()
        return (
            self._data
            .get("common_patterns", {})
            .get("access_rules", {})
            .get("default_policy", "deny_all_then_grant")
        )

    # ─── Accessors de data types ─────────────────────────────────

    @property
    def most_used_types(self) -> list[str]:
        self._ensure_loaded()
        return self._data.get("data_types", {}).get("most_used", [])

    @property
    def enumerations(self) -> list[dict[str, Any]]:
        self._ensure_loaded()
        return self._data.get("data_types", {}).get("enumerations", [])

    # ─── Accessors de layouts ────────────────────────────────────

    @property
    def default_page_layout(self) -> str:
        self._ensure_loaded()
        return (
            self._data
            .get("common_patterns", {})
            .get("page_layouts", {})
            .get("default", "Atlas_Default")
        )

    # ─── Contexto para prompts LLM ──────────────────────────────

    def as_context_string(self) -> str:
        """Genera un string de contexto para incluir en prompts LLM.

        Resume las convenciones del proyecto en texto legible.
        """
        self._ensure_loaded()

        lines = [
            f"## Convenciones del proyecto {self.project_name} (Mendix {self.mendix_version})",
            "",
            "### Naming",
            f"- Entidades: {self.entity_naming_pattern}",
            f"  Ejemplos: {', '.join(self.entity_naming_examples[:5])}",
            f"- Atributos: {self.attribute_naming_pattern}",
            f"- Microflows: {self.microflow_naming_pattern}",
            f"- Páginas: {self.page_naming_pattern}",
            "",
            "### Módulos",
        ]
        for mod in self.modules[:10]:
            lines.append(f"- {mod.get('name', '?')} ({mod.get('entity_count', 0)} entidades)")

        lines.extend([
            "",
            "### Seguridad",
            f"- Roles: {', '.join(self.security_roles)}",
            f"- Política por defecto: {self.default_access_policy}",
            "",
            "### Tipos más usados",
            f"- {', '.join(self.most_used_types)}",
        ])

        return "\n".join(lines)
