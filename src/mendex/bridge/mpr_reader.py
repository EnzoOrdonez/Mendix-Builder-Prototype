"""Lector nativo de proyectos Mendix .mpr en Python puro.

Lee la estructura de un proyecto Mendix directamente desde los archivos
.mpr (SQLite) y .mxunit (binario), sin necesidad de Node.js ni conexión
al Mendix Platform SDK.

Rendimiento: ~200ms para un proyecto de 1,780 archivos .mxunit.

Clases principales:
- MxunitParser: Motor de parsing del formato binario .mxunit
- MprDirectReader: Implementación de SDKClient para operaciones de lectura
"""

from __future__ import annotations

import sqlite3
import struct
import uuid
from pathlib import Path
from typing import Any

import structlog

from mendex.bridge.sdk_client import (
    EntityInfo,
    ModuleInfo,
    ProjectStructure,
    SDKClient,
    SDKClientError,
    SecurityInfo,
)

logger = structlog.get_logger(__name__)


class MxunitParser:
    """Parser del formato binario .mxunit de Mendix 10.x.

    Formato descubierto por reverse engineering:
    - Primeros 4 bytes: uint32_le tamaño total del objeto raíz
    - Propiedades en orden alfabético: tag(1) + nombre\\0 + valor
    - Tags: 0x02=string, 0x05=GUID, 0x08=bool, 0x01=double,
             0x10=int32, 0x12=long, 0x0a=null, 0x03=child, 0x04=list
    - 0x00 = fin del objeto
    - Listas (0x04) internamente usan: elemento "0" (tag 0x10, header)
      seguido de hijos numerados "1", "2", ... (tag 0x03)
    """

    # Tag type constants
    TAG_DOUBLE = 0x01
    TAG_STRING = 0x02
    TAG_CHILD = 0x03
    TAG_LIST = 0x04
    TAG_GUID = 0x05
    TAG_BOOL = 0x08
    TAG_NULL = 0x0A
    TAG_INT32 = 0x10
    TAG_LONG = 0x12
    TAG_END = 0x00

    @staticmethod
    def uid_to_mxunit_path(uid_bytes: bytes, mpr_dir: Path) -> Path:
        """Convierte UnitID (16 bytes de SQLite) a la ruta del .mxunit.

        El UnitID se almacena como bytes_le en SQLite. La ruta usa el UUID
        formateado: mprcontents/{hex[0:2]}/{hex[2:4]}/{uuid-string}.mxunit
        """
        u = uuid.UUID(bytes_le=uid_bytes)
        uid_str = str(u)
        hex_str = uid_str.replace("-", "")
        return mpr_dir / "mprcontents" / hex_str[:2] / hex_str[2:4] / f"{uid_str}.mxunit"

    @staticmethod
    def _read_property_name(data: bytes, idx: int) -> tuple[str, int]:
        """Lee el nombre de una propiedad (null-terminated string).

        Returns:
            (nombre, índice después del null terminator)
        """
        end = data.index(b"\x00", idx)
        name = data[idx:end].decode("utf-8", errors="replace")
        return name, end + 1

    @staticmethod
    def _skip_value(data: bytes, idx: int, tag: int) -> int:
        """Salta el valor de una propiedad según su tag.

        Returns:
            Índice después del valor.
        """
        if tag == MxunitParser.TAG_STRING:
            str_len = struct.unpack_from("<I", data, idx)[0]
            return idx + 4 + str_len
        elif tag == MxunitParser.TAG_GUID:
            guid_len = struct.unpack_from("<I", data, idx)[0]
            return idx + 4 + 1 + guid_len  # 4(len) + 1(null prefix) + data
        elif tag == MxunitParser.TAG_BOOL:
            return idx + 1
        elif tag == MxunitParser.TAG_DOUBLE:
            return idx + 8
        elif tag == MxunitParser.TAG_INT32:
            return idx + 4
        elif tag == MxunitParser.TAG_LONG:
            return idx + 8
        elif tag == MxunitParser.TAG_NULL:
            return idx
        elif tag in (MxunitParser.TAG_CHILD, MxunitParser.TAG_LIST):
            csize = struct.unpack_from("<I", data, idx)[0]
            return idx + csize  # size is self-inclusive
        else:
            raise ValueError(f"Unknown tag 0x{tag:02x} at offset {idx}")

    @staticmethod
    def _read_string_value(data: bytes, idx: int) -> tuple[str, int]:
        """Lee un valor string: uint32_le length + bytes + null.

        Returns:
            (valor_string, índice después del valor)
        """
        str_len = struct.unpack_from("<I", data, idx)[0]
        if str_len > 0:
            value = data[idx + 4 : idx + 4 + str_len - 1].decode(
                "utf-8", errors="replace"
            )
        else:
            value = ""
        return value, idx + 4 + str_len

    @classmethod
    def parse_top_level_props(cls, data: bytes) -> dict[str, Any]:
        """Extrae propiedades del objeto raíz, saltando hijos por tamaño.

        Solo lee propiedades escalares (string, bool, long, double, GUID).
        Los hijos (0x03/0x04) se saltan completamente usando su campo size.

        Returns:
            Dict con {nombre_propiedad: valor} incluyendo $Type.
        """
        props: dict[str, Any] = {}
        idx = 4  # Skip total size (uint32_le)

        try:
            while idx < len(data):
                tag = data[idx]
                if tag == cls.TAG_END:
                    break

                prop_name, idx = cls._read_property_name(data, idx + 1)

                if tag == cls.TAG_STRING:
                    value, idx = cls._read_string_value(data, idx)
                    props[prop_name] = value
                elif tag == cls.TAG_GUID:
                    guid_len = struct.unpack_from("<I", data, idx)[0]
                    if guid_len == 16:
                        guid_bytes = data[idx + 5 : idx + 5 + 16]
                        props[prop_name] = guid_bytes
                    idx += 4 + 1 + guid_len
                elif tag == cls.TAG_BOOL:
                    props[prop_name] = bool(data[idx])
                    idx += 1
                elif tag == cls.TAG_DOUBLE:
                    props[prop_name] = struct.unpack_from("<d", data, idx)[0]
                    idx += 8
                elif tag == cls.TAG_INT32:
                    props[prop_name] = struct.unpack_from("<I", data, idx)[0]
                    idx += 4
                elif tag == cls.TAG_LONG:
                    props[prop_name] = struct.unpack_from("<q", data, idx)[0]
                    idx += 8
                elif tag == cls.TAG_NULL:
                    props[prop_name] = None
                elif tag in (cls.TAG_CHILD, cls.TAG_LIST):
                    csize = struct.unpack_from("<I", data, idx)[0]
                    idx += csize
                else:
                    # Unknown tag — skip rest to avoid infinite loop
                    logger.warning(
                        "mxunit_unknown_tag",
                        tag=f"0x{tag:02x}",
                        offset=idx,
                        prop_name=prop_name,
                    )
                    break
        except (struct.error, IndexError, ValueError):
            # Truncated or corrupt file — return what we have
            pass

        return props

    @classmethod
    def extract_type(cls, data: bytes) -> str | None:
        """Extrae el $Type del objeto raíz (rápido, solo lee hasta encontrarlo)."""
        props = cls.parse_top_level_props(data)
        return props.get("$Type")

    @classmethod
    def extract_name(cls, data: bytes) -> str | None:
        """Extrae el Name del objeto raíz."""
        props = cls.parse_top_level_props(data)
        return props.get("Name")

    @classmethod
    def extract_type_and_name(cls, data: bytes) -> tuple[str | None, str | None]:
        """Extrae $Type y Name en una sola pasada."""
        props = cls.parse_top_level_props(data)
        return props.get("$Type"), props.get("Name")

    @classmethod
    def extract_entities_from_domain_model(
        cls, data: bytes
    ) -> list[tuple[str, list[str]]]:
        """Extrae entidades y sus atributos de un archivo DomainModels$DomainModel.

        Busca la propiedad lista "Entities" en el top-level, luego parsea
        cada DomainModels$EntityImpl hijo para obtener Name, y dentro de
        cada entidad parsea la lista "Attributes" para obtener nombres.

        Returns:
            Lista de (entity_name, [attribute_names])
        """
        entities: list[tuple[str, list[str]]] = []
        idx = 4  # Skip total size

        try:
            while idx < len(data):
                tag = data[idx]
                if tag == cls.TAG_END:
                    break

                prop_name, name_end = cls._read_property_name(data, idx + 1)

                if tag == cls.TAG_LIST and prop_name == "Entities":
                    # Found the Entities list — parse entity children
                    list_size = struct.unpack_from("<I", data, name_end)[0]
                    list_end = name_end + list_size
                    entities = cls._parse_entities_list(data, name_end, list_end)
                    break
                else:
                    # Skip this property
                    idx = cls._skip_value(data, name_end, tag)

        except (struct.error, IndexError, ValueError) as e:
            logger.warning("mxunit_parse_error", error=str(e), context="entities")

        return entities

    @classmethod
    def _parse_list_children(
        cls, data: bytes, list_start: int, list_end: int
    ) -> list[bytes]:
        """Parsea los hijos dentro de una lista (tag 0x04).

        Las listas en .mxunit tienen formato:
        - Elemento "0" (tag 0x10): header/version (se salta)
        - Elementos "1", "2", ... (tag 0x03): objetos hijos

        Returns:
            Lista de bytes de cada objeto hijo (datos desde su size field).
        """
        children: list[bytes] = []
        idx = list_start + 4  # Skip list size field

        while idx < list_end:
            tag = data[idx]
            if tag == cls.TAG_END:
                break

            prop_name, name_end = cls._read_property_name(data, idx + 1)

            if tag == cls.TAG_INT32:
                # Header element (typically named "0") — skip
                idx = name_end + 4
            elif tag in (cls.TAG_CHILD, cls.TAG_LIST):
                csize = struct.unpack_from("<I", data, name_end)[0]
                child_end = name_end + csize
                children.append(data[name_end:child_end])
                idx = child_end
            else:
                # Unknown tag inside list — try to skip
                try:
                    idx = cls._skip_value(data, name_end, tag)
                except ValueError:
                    break

        return children

    @classmethod
    def _parse_entities_list(
        cls, data: bytes, list_start: int, list_end: int
    ) -> list[tuple[str, list[str]]]:
        """Parsea la lista de entidades dentro de un DomainModel."""
        entities: list[tuple[str, list[str]]] = []

        for child_data in cls._parse_list_children(data, list_start, list_end):
            entity_type = cls.extract_type(child_data)

            if entity_type and "EntityImpl" in entity_type:
                entity_name = cls.extract_name(child_data)
                if entity_name:
                    attrs = cls._extract_attributes_from_entity(child_data)
                    entities.append((entity_name, attrs))

        return entities

    @classmethod
    def _extract_attributes_from_entity(cls, entity_data: bytes) -> list[str]:
        """Extrae nombres de atributos de un EntityImpl."""
        attributes: list[str] = []
        idx = 4  # Skip total size

        try:
            while idx < len(entity_data):
                tag = entity_data[idx]
                if tag == cls.TAG_END:
                    break

                prop_name, name_end = cls._read_property_name(
                    entity_data, idx + 1
                )

                if tag == cls.TAG_LIST and prop_name == "Attributes":
                    list_size = struct.unpack_from("<I", entity_data, name_end)[0]
                    list_end = name_end + list_size
                    for child_data in cls._parse_list_children(
                        entity_data, name_end, list_end
                    ):
                        attr_name = cls.extract_name(child_data)
                        if attr_name:
                            attributes.append(attr_name)
                    break
                else:
                    idx = cls._skip_value(entity_data, name_end, tag)

        except (struct.error, IndexError, ValueError):
            pass

        return attributes

    @classmethod
    def extract_user_roles(cls, data: bytes) -> list[str]:
        """Extrae nombres de roles de un archivo Security$ProjectSecurity.

        Busca la lista "UserRoles" y dentro cada Security$UserRole hijo.

        Returns:
            Lista de nombres de roles.
        """
        roles: list[str] = []
        idx = 4  # Skip total size

        try:
            while idx < len(data):
                tag = data[idx]
                if tag == cls.TAG_END:
                    break

                prop_name, name_end = cls._read_property_name(data, idx + 1)

                if tag == cls.TAG_LIST and prop_name == "UserRoles":
                    list_size = struct.unpack_from("<I", data, name_end)[0]
                    list_end = name_end + list_size
                    for child_data in cls._parse_list_children(
                        data, name_end, list_end
                    ):
                        role_name = cls.extract_name(child_data)
                        if role_name:
                            roles.append(role_name)
                    break
                else:
                    idx = cls._skip_value(data, name_end, tag)

        except (struct.error, IndexError, ValueError):
            pass

        return roles


class MprDirectReader(SDKClient):
    """Lector nativo de proyectos Mendix .mpr en Python puro.

    Implementa SDKClient para operaciones de lectura. Las operaciones
    de escritura (create_entity, create_page, create_microflow) lanzan
    NotImplementedError — usar CompositeSDKClient para operaciones mixtas.

    El ProjectStructure se cachea en memoria tras la primera lectura.
    Se invalida automáticamente si cambia el mtime del .mpr.

    Uso:
        reader = MprDirectReader()
        structure = reader.read_project_structure(Path("proyecto.mpr"))
        exists = reader.check_artifact_exists(path, "entity", "MyModule", "MyEntity")
    """

    def __init__(self) -> None:
        self._cache: ProjectStructure | None = None
        self._cache_key: tuple[str, float] | None = None  # (path, mtime)
        # Prebuilt lookup sets for fast check_artifact_exists
        self._entity_set: set[str] | None = None
        self._page_set: set[str] | None = None
        self._microflow_set: set[str] | None = None

    def ping(self) -> bool:
        """Siempre retorna True — no depende de proceso externo."""
        return True

    def read_project_structure(self, mpr_path: Path) -> ProjectStructure:
        """Lee la estructura completa de un proyecto .mpr.

        Args:
            mpr_path: Ruta al archivo .mpr (SQLite).

        Returns:
            ProjectStructure con módulos, entidades, páginas, microflows y roles.

        Raises:
            SDKClientError: Si el .mpr no existe, no es SQLite, o hay error de parsing.
        """
        mpr_path = mpr_path.resolve()

        if not mpr_path.exists():
            raise SDKClientError(f"Archivo .mpr no encontrado: {mpr_path}")

        # Check cache
        try:
            mtime = mpr_path.stat().st_mtime
        except OSError as e:
            raise SDKClientError(f"No se puede acceder a {mpr_path}: {e}") from e

        cache_key = (str(mpr_path), mtime)
        if self._cache is not None and self._cache_key == cache_key:
            return self._cache

        logger.info("mpr_reader_start", mpr_path=str(mpr_path))

        try:
            structure = self._read_structure(mpr_path)
        except sqlite3.Error as e:
            raise SDKClientError(
                f"Error al leer SQLite {mpr_path}: {e}. "
                "Verifica que el archivo es un .mpr válido de Mendix."
            ) from e

        # Cache the result
        self._cache = structure
        self._cache_key = cache_key
        self._build_lookup_sets(structure)

        logger.info(
            "mpr_reader_done",
            modules=len(structure.modules),
            entities=len(structure.all_entity_names),
            pages=len(structure.all_page_names),
            microflows=len(structure.all_microflow_names),
            roles=len(structure.security.roles),
        )

        return structure

    def check_artifact_exists(
        self, mpr_path: Path, artifact_type: str, module: str, name: str
    ) -> bool:
        """Verifica si un artefacto existe usando el caché de ProjectStructure.

        Si no hay caché, lee la estructura primero.
        Lookup es O(1) usando sets precalculados.
        """
        # Ensure structure is loaded
        if self._cache is None or self._cache_key != (
            str(mpr_path.resolve()),
            mpr_path.resolve().stat().st_mtime,
        ):
            self.read_project_structure(mpr_path)

        key = f"{module}.{name}"

        if artifact_type == "entity":
            return key in (self._entity_set or set())
        elif artifact_type == "page":
            return key in (self._page_set or set())
        elif artifact_type == "microflow":
            return key in (self._microflow_set or set())
        else:
            logger.warning(
                "mpr_reader_unknown_artifact_type", artifact_type=artifact_type
            )
            return False

    def create_entity(
        self, mpr_path: Path, entity_data: dict[str, Any]
    ) -> dict[str, Any]:
        """No soportado — MprDirectReader es solo lectura."""
        raise NotImplementedError(
            "MprDirectReader es solo lectura. "
            "Usar CompositeSDKClient para operaciones de escritura."
        )

    def create_page(
        self, mpr_path: Path, page_data: dict[str, Any]
    ) -> dict[str, Any]:
        """No soportado — MprDirectReader es solo lectura."""
        raise NotImplementedError(
            "MprDirectReader es solo lectura. "
            "Usar CompositeSDKClient para operaciones de escritura."
        )

    def create_microflow(
        self, mpr_path: Path, microflow_data: dict[str, Any]
    ) -> dict[str, Any]:
        """No soportado — MprDirectReader es solo lectura."""
        raise NotImplementedError(
            "MprDirectReader es solo lectura. "
            "Usar CompositeSDKClient para operaciones de escritura."
        )

    def create_association(
        self, mpr_path: Path, association_data: dict[str, Any]
    ) -> dict[str, Any]:
        """No soportado — MprDirectReader es solo lectura."""
        raise NotImplementedError(
            "MprDirectReader es solo lectura. "
            "Usar CompositeSDKClient para operaciones de escritura."
        )

    def _build_lookup_sets(self, structure: ProjectStructure) -> None:
        """Construye sets de lookup para check_artifact_exists O(1)."""
        self._entity_set = set()
        self._page_set = set()
        self._microflow_set = set()

        for mod in structure.modules:
            for entity in mod.entities:
                self._entity_set.add(f"{mod.name}.{entity.name}")
            for page in mod.pages:
                self._page_set.add(f"{mod.name}.{page}")
            for mf in mod.microflows:
                self._microflow_set.add(f"{mod.name}.{mf}")

    def _read_structure(self, mpr_path: Path) -> ProjectStructure:
        """Lee la estructura completa del proyecto desde SQLite + .mxunit."""
        mpr_dir = mpr_path.parent

        conn = sqlite3.connect(str(mpr_path))
        try:
            return self._parse_project(conn, mpr_dir)
        finally:
            conn.close()

    def _parse_project(
        self, conn: sqlite3.Connection, mpr_dir: Path
    ) -> ProjectStructure:
        """Parsea la estructura del proyecto desde la base de datos SQLite."""
        cur = conn.cursor()

        # 1. Read all units and build parent map
        cur.execute(
            "SELECT UnitID, ContainerID, ContainmentName FROM Unit"
        )
        rows = cur.fetchall()

        parent_map: dict[bytes, bytes] = {}
        containment_map: dict[bytes, str] = {}
        for uid, cid, cname in rows:
            parent_map[uid] = cid
            containment_map[uid] = cname or ""

        # 2. Identify module units
        module_uids = {
            uid for uid, cname in containment_map.items() if cname == "Modules"
        }

        # 3. Build module-lookup function (trace parent chain to find module)
        def find_module_uid(uid: bytes) -> bytes | None:
            visited: set[bytes] = set()
            current: bytes | None = uid
            while current is not None and current not in visited:
                if current in module_uids:
                    return current
                visited.add(current)
                current = parent_map.get(current)
            return None

        # 4. Read module names
        module_names: dict[bytes, str] = {}
        for mod_uid in module_uids:
            mxunit_path = MxunitParser.uid_to_mxunit_path(mod_uid, mpr_dir)
            if mxunit_path.exists():
                data = mxunit_path.read_bytes()
                name = MxunitParser.extract_name(data)
                if name:
                    module_names[mod_uid] = name

        # 5. Read DomainModel files → entities + attributes per module
        module_entities: dict[bytes, list[EntityInfo]] = {
            uid: [] for uid in module_uids
        }
        dm_uids = {
            uid: parent_map[uid]
            for uid, cname in containment_map.items()
            if cname == "DomainModel"
        }
        for dm_uid, container_uid in dm_uids.items():
            if container_uid not in module_uids:
                continue
            mxunit_path = MxunitParser.uid_to_mxunit_path(dm_uid, mpr_dir)
            if not mxunit_path.exists():
                continue
            data = mxunit_path.read_bytes()
            entities = MxunitParser.extract_entities_from_domain_model(data)
            for entity_name, attr_names in entities:
                module_entities[container_uid].append(
                    EntityInfo(name=entity_name, attributes=attr_names)
                )

        # 6. Read Document files → pages and microflows per module
        module_pages: dict[bytes, list[str]] = {uid: [] for uid in module_uids}
        module_microflows: dict[bytes, list[str]] = {
            uid: [] for uid in module_uids
        }

        doc_uids = [
            uid
            for uid, cname in containment_map.items()
            if cname == "Documents"
        ]
        for doc_uid in doc_uids:
            mxunit_path = MxunitParser.uid_to_mxunit_path(doc_uid, mpr_dir)
            if not mxunit_path.exists():
                continue

            data = mxunit_path.read_bytes()
            type_name, doc_name = MxunitParser.extract_type_and_name(data)

            if not type_name or not doc_name:
                continue

            mod_uid = find_module_uid(doc_uid)
            if mod_uid is None:
                continue

            # Forms$Page → pages, Microflows$Microflow → microflows
            if type_name.startswith("Forms$"):
                module_pages[mod_uid].append(doc_name)
            elif type_name.startswith("Microflows$Microflow"):
                module_microflows[mod_uid].append(doc_name)

        # 7. Read ProjectSecurity → roles
        roles: list[str] = []
        project_doc_uids = [
            uid
            for uid, cname in containment_map.items()
            if cname == "ProjectDocuments"
        ]
        for pd_uid in project_doc_uids:
            mxunit_path = MxunitParser.uid_to_mxunit_path(pd_uid, mpr_dir)
            if not mxunit_path.exists():
                continue
            data = mxunit_path.read_bytes()
            type_name = MxunitParser.extract_type(data)
            if type_name == "Security$ProjectSecurity":
                roles = MxunitParser.extract_user_roles(data)
                break

        # 8. Assemble ProjectStructure
        modules: list[ModuleInfo] = []
        for mod_uid in module_uids:
            name = module_names.get(mod_uid)
            if not name:
                continue
            modules.append(
                ModuleInfo(
                    name=name,
                    entities=module_entities.get(mod_uid, []),
                    pages=module_pages.get(mod_uid, []),
                    microflows=module_microflows.get(mod_uid, []),
                )
            )

        # Sort modules alphabetically for deterministic output
        modules.sort(key=lambda m: m.name)

        return ProjectStructure(
            modules=modules,
            security=SecurityInfo(roles=roles),
        )
