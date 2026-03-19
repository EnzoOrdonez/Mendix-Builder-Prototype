"""Extractor de convenciones desde un proyecto Mendix de referencia.

Lee la estructura del .mpr via SDK Bridge, analiza patrones de naming,
módulos, tipos de datos, roles, y genera copeinca_conventions.yaml.

La extracción ocurre UNA VEZ (o bajo demanda con --refresh-conventions).
El hash del .mpr se persiste para detectar si el proyecto evolucionó.

Fase 3: Implementación completa.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog
import yaml

from mendex.bridge.rollback import RollbackManager
from mendex.bridge.sdk_client import (
    EntityInfo,
    ModuleInfo,
    ProjectStructure,
    SDKClient,
)
from mendex.logging.decision_logger import DecisionLogger, PatternSource

logger = structlog.get_logger(__name__)


class ConventionsExtractorError(Exception):
    """Error durante la extracción de convenciones."""


class ConventionsExtractor:
    """Extrae patrones y convenciones de un proyecto Mendix de referencia.

    Genera un archivo YAML con las convenciones detectadas y persiste
    el hash del .mpr para detectar cambios futuros.

    Uso:
        extractor = ConventionsExtractor(
            sdk_client=sdk_client,
            output_path=Path("conventions/copeinca_conventions.yaml"),
            hash_path=Path("conventions/.mpr_hash"),
        )
        result = extractor.extract(mpr_path=Path("reference_project/COPEINCA.mpr"))
    """

    # Mendix data types reconocibles en atributos
    MENDIX_DATA_TYPES = {
        "String", "Integer", "Long", "Decimal", "Boolean",
        "DateTime", "Enumeration", "HashedString", "AutoNumber",
    }

    def __init__(
        self,
        sdk_client: SDKClient,
        output_path: Path,
        hash_path: Path,
        decision_logger: DecisionLogger | None = None,
        project_name: str = "COPEINCA",
    ) -> None:
        self._sdk_client = sdk_client
        self._output_path = output_path
        self._hash_path = hash_path
        self._decision_logger = decision_logger
        self._project_name = project_name

    def extract(
        self, mpr_path: Path, mendix_version: str = "10.24.16"
    ) -> ExtractionResult:
        """Extrae convenciones del proyecto y genera el YAML.

        Args:
            mpr_path: Path al .mpr del proyecto de referencia.
            mendix_version: Versión de Mendix del proyecto.

        Returns:
            ExtractionResult con metadata de la extracción.

        Raises:
            ConventionsExtractorError: Si el .mpr no existe o la lectura falla.
        """
        mpr_path = mpr_path.resolve()

        if not mpr_path.exists():
            raise ConventionsExtractorError(f"El archivo .mpr no existe: {mpr_path}")

        # Calcular hash del .mpr
        current_hash = RollbackManager.compute_mpr_hash(mpr_path)
        previous_hash = self._read_previous_hash()
        changed = previous_hash is not None and current_hash != previous_hash

        if previous_hash and not changed:
            logger.info(
                "mpr_unchanged",
                mpr_hash=current_hash[:16],
                message="El .mpr no ha cambiado desde la última extracción.",
            )

        # Leer estructura del proyecto via SDK Bridge
        logger.info("reading_project_structure", mpr=str(mpr_path))
        structure = self._sdk_client.read_project_structure(mpr_path)

        # Analizar patrones
        conventions = self._analyze_patterns(structure, current_hash, mendix_version)

        # Escribir YAML
        self._write_yaml(conventions)

        # Persistir hash
        self._write_hash(current_hash)

        # Loguear decisión
        if self._decision_logger:
            self._decision_logger.log(
                operation="extract_conventions",
                input_hash=current_hash,
                pattern_source=PatternSource.COPEINCA_CONVENTIONS,
                action_taken="conventions_extracted",
                extra={
                    "project_name": self._project_name,
                    "modules_count": len(structure.modules),
                    "entities_count": len(structure.all_entity_names),
                    "pages_count": len(structure.all_page_names),
                    "microflows_count": len(structure.all_microflow_names),
                    "changed_from_previous": changed,
                },
            )

        result = ExtractionResult(
            output_path=self._output_path,
            mpr_hash=current_hash,
            previous_hash=previous_hash,
            changed=changed,
            modules_count=len(structure.modules),
            entities_count=len(structure.all_entity_names),
            pages_count=len(structure.all_page_names),
            microflows_count=len(structure.all_microflow_names),
        )

        logger.info(
            "conventions_extracted",
            output=str(self._output_path),
            modules=result.modules_count,
            entities=result.entities_count,
            changed=result.changed,
        )

        return result

    def check_outdated(self, mpr_path: Path) -> bool:
        """Verifica si las convenciones están desactualizadas.

        Compara el hash actual del .mpr con el hash persistido.

        Args:
            mpr_path: Path al .mpr.

        Returns:
            True si el .mpr cambió desde la última extracción.
        """
        previous_hash = self._read_previous_hash()
        if previous_hash is None:
            return True  # Nunca se ha extraído

        current_hash = RollbackManager.compute_mpr_hash(mpr_path)
        return current_hash != previous_hash

    def _analyze_patterns(
        self,
        structure: ProjectStructure,
        mpr_hash: str,
        mendix_version: str,
    ) -> dict[str, Any]:
        """Analiza la estructura del proyecto y detecta patrones."""

        # --- Naming patterns ---
        entity_names = structure.all_entity_names
        attribute_names = structure.all_attribute_names
        microflow_names = structure.all_microflow_names
        page_names = structure.all_page_names

        entity_naming = self._detect_naming_pattern(entity_names)
        attribute_naming = self._detect_naming_pattern(attribute_names)
        microflow_naming = self._detect_microflow_pattern(microflow_names)
        page_naming = self._detect_page_pattern(page_names)

        # --- Modules ---
        modules_info = []
        for mod in structure.modules:
            modules_info.append({
                "name": mod.name,
                "entity_count": mod.entity_count,
                "description": "",
            })

        # --- Data types ---
        all_attrs = [
            attr
            for mod in structure.modules
            for entity in mod.entities
            for attr in entity.attributes
        ]
        type_counts = Counter(all_attrs)
        most_used = [t for t, _ in type_counts.most_common(5)] if type_counts else []

        # --- Security roles ---
        roles = structure.security.roles

        # --- Enumerations (detectar por nombre de atributo) ---
        enum_candidates = [
            attr for attr in all_attrs
            if any(kw in attr.lower() for kw in ["estado", "tipo", "status", "type", "categoria"])
        ]

        return {
            "project": {
                "name": self._project_name,
                "mendix_version": mendix_version,
                "extracted_at": datetime.now(timezone.utc).isoformat(),
                "mpr_hash": mpr_hash,
            },
            "naming": {
                "entities": {
                    "pattern": entity_naming["pattern"],
                    "prefix": entity_naming.get("prefix", ""),
                    "examples": entity_names[:10],
                },
                "attributes": {
                    "pattern": attribute_naming["pattern"],
                    "examples": list(set(attribute_names))[:10],
                },
                "microflows": {
                    "pattern": microflow_naming["pattern"],
                    "examples": microflow_names[:10],
                },
                "pages": {
                    "pattern": page_naming["pattern"],
                    "examples": page_names[:10],
                },
            },
            "modules": modules_info,
            "common_patterns": {
                "access_rules": {
                    "roles": roles,
                    "default_policy": "deny_all_then_grant",
                },
                "validation": {
                    "common_types": ["required", "max_length"],
                    "error_message_language": "es",
                },
                "page_layouts": {
                    "default": "Atlas_Default",
                    "popup": "PopupLayout",
                },
            },
            "data_types": {
                "most_used": most_used if most_used else [
                    "String", "DateTime", "Decimal", "Integer", "Boolean"
                ],
                "enumerations": [],
            },
        }

    @staticmethod
    def _detect_naming_pattern(names: list[str]) -> dict[str, str]:
        """Detecta el patrón de naming (PascalCase, camelCase, snake_case, etc.)."""
        if not names:
            return {"pattern": "PascalCase"}

        pascal_count = sum(1 for n in names if re.match(r"^[A-Z][a-zA-Z0-9]*$", n))
        camel_count = sum(1 for n in names if re.match(r"^[a-z][a-zA-Z0-9]*$", n))
        snake_count = sum(1 for n in names if re.match(r"^[a-z][a-z0-9_]*$", n))

        total = len(names)
        if total == 0:
            return {"pattern": "PascalCase"}

        # Detectar prefijo común
        prefix = ""
        if len(names) >= 3:
            prefix_candidate = _common_prefix(names)
            if len(prefix_candidate) >= 2 and prefix_candidate.endswith("_"):
                prefix = prefix_candidate

        if pascal_count / total >= 0.6:
            return {"pattern": "PascalCase", "prefix": prefix}
        elif camel_count / total >= 0.6:
            return {"pattern": "camelCase", "prefix": prefix}
        elif snake_count / total >= 0.6:
            return {"pattern": "snake_case", "prefix": prefix}
        else:
            return {"pattern": "Mixed", "prefix": prefix}

    @staticmethod
    def _detect_microflow_pattern(names: list[str]) -> dict[str, str]:
        """Detecta patrón de naming de microflows (ej: ACT_Entity_Action)."""
        if not names:
            return {"pattern": "{Action}_{Entity}_{Qualifier}"}

        # Buscar patrón PREFIX_Entity_Action
        prefixed = sum(1 for n in names if re.match(r"^[A-Z]{2,5}_", n))
        if prefixed / max(len(names), 1) >= 0.4:
            return {"pattern": "{Prefix}_{Entity}_{Action}"}

        # Buscar patrón Entity_Action
        underscored = sum(1 for n in names if "_" in n)
        if underscored / max(len(names), 1) >= 0.5:
            return {"pattern": "{Entity}_{Action}"}

        return {"pattern": "PascalCase"}

    @staticmethod
    def _detect_page_pattern(names: list[str]) -> dict[str, str]:
        """Detecta patrón de naming de páginas."""
        if not names:
            return {"pattern": "{Entity}_{Action}"}

        underscored = sum(1 for n in names if "_" in n)
        if underscored / max(len(names), 1) >= 0.5:
            return {"pattern": "{Entity}_{Action}"}

        return {"pattern": "PascalCase"}

    def _write_yaml(self, conventions: dict[str, Any]) -> None:
        """Escribe el YAML de convenciones."""
        self._output_path.parent.mkdir(parents=True, exist_ok=True)

        header = (
            "# ============================================\n"
            "# COPEINCA Conventions — Patrones extraídos del proyecto de referencia\n"
            "# ============================================\n"
            "# Este archivo se genera automáticamente con: mendex refresh-conventions --mpr <path>\n"
            "# SÍ se commitea al repositorio (no contiene datos sensibles, solo patrones).\n"
            "# Editable manualmente si se necesita ajustar patrones.\n"
            "#\n"
            f"# Generado: {conventions['project']['extracted_at']}\n"
            f"# Hash .mpr: {conventions['project']['mpr_hash'][:16]}...\n"
            "#\n"
            "# Para regenerar: mendex refresh-conventions --mpr reference_project/COPEINCA.mpr\n\n"
        )

        yaml_content = yaml.dump(
            conventions,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
            width=100,
        )

        with open(self._output_path, "w", encoding="utf-8") as f:
            f.write(header)
            f.write(yaml_content)

    def _write_hash(self, mpr_hash: str) -> None:
        """Persiste el hash del .mpr."""
        self._hash_path.parent.mkdir(parents=True, exist_ok=True)
        self._hash_path.write_text(mpr_hash, encoding="utf-8")

    def _read_previous_hash(self) -> str | None:
        """Lee el hash persistido de la última extracción."""
        if not self._hash_path.exists():
            return None
        content = self._hash_path.read_text(encoding="utf-8").strip()
        return content if content else None


class ExtractionResult:
    """Resultado de una extracción de convenciones."""

    def __init__(
        self,
        output_path: Path,
        mpr_hash: str,
        previous_hash: str | None,
        changed: bool,
        modules_count: int,
        entities_count: int,
        pages_count: int,
        microflows_count: int,
    ) -> None:
        self.output_path = output_path
        self.mpr_hash = mpr_hash
        self.previous_hash = previous_hash
        self.changed = changed
        self.modules_count = modules_count
        self.entities_count = entities_count
        self.pages_count = pages_count
        self.microflows_count = microflows_count

    def summary(self) -> str:
        """Genera un resumen legible de la extracción."""
        status = "ACTUALIZADO" if self.changed else "SIN CAMBIOS"
        if self.previous_hash is None:
            status = "PRIMERA EXTRACCIÓN"

        return (
            f"=== Extracción de Convenciones ===\n"
            f"Estado: {status}\n"
            f"Módulos: {self.modules_count}\n"
            f"Entidades: {self.entities_count}\n"
            f"Páginas: {self.pages_count}\n"
            f"Microflows: {self.microflows_count}\n"
            f"Hash .mpr: {self.mpr_hash[:16]}...\n"
            f"Output: {self.output_path}\n"
        )


def _common_prefix(strings: list[str]) -> str:
    """Encuentra el prefijo común más largo de una lista de strings."""
    if not strings:
        return ""
    shortest = min(strings, key=len)
    for i, char in enumerate(shortest):
        if any(s[i] != char for s in strings):
            return shortest[:i]
    return shortest
