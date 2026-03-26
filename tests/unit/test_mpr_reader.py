"""Tests unitarios para MprDirectReader y MxunitParser.

Construye datos binarios .mxunit sintéticos para probar el parser
sin depender de archivos reales.
"""

from __future__ import annotations

import sqlite3
import struct
import tempfile
import uuid
from pathlib import Path

import pytest

from mendex.bridge.mpr_reader import MprDirectReader, MxunitParser
from mendex.bridge.sdk_client import SDKClientError


# ============================================================
# Helpers para construir datos binarios .mxunit de prueba
# ============================================================


def _build_string_prop(name: str, value: str) -> bytes:
    """Construye una propiedad string: tag(0x02) + name\\0 + uint32_le(len) + value + \\0."""
    name_bytes = name.encode("utf-8") + b"\x00"
    value_bytes = value.encode("utf-8") + b"\x00"
    length = len(value_bytes)
    return b"\x02" + name_bytes + struct.pack("<I", length) + value_bytes


def _build_bool_prop(name: str, value: bool) -> bytes:
    """Construye una propiedad boolean: tag(0x08) + name\\0 + byte."""
    name_bytes = name.encode("utf-8") + b"\x00"
    return b"\x08" + name_bytes + (b"\x01" if value else b"\x00")


def _build_guid_prop(name: str, guid_bytes: bytes = b"\x00" * 16) -> bytes:
    """Construye una propiedad GUID: tag(0x05) + name\\0 + uint32_le(16) + \\0 + 16 bytes."""
    name_bytes = name.encode("utf-8") + b"\x00"
    return b"\x05" + name_bytes + struct.pack("<I", 16) + b"\x00" + guid_bytes


def _build_long_prop(name: str, value: int) -> bytes:
    """Construye una propiedad long: tag(0x12) + name\\0 + int64_le."""
    name_bytes = name.encode("utf-8") + b"\x00"
    return b"\x12" + name_bytes + struct.pack("<q", value)


def _build_int32_prop(name: str, value: int) -> bytes:
    """Construye una propiedad int32: tag(0x10) + name\\0 + uint32_le."""
    name_bytes = name.encode("utf-8") + b"\x00"
    return b"\x10" + name_bytes + struct.pack("<I", value)


def _build_null_prop(name: str) -> bytes:
    """Construye una propiedad null: tag(0x0a) + name\\0."""
    name_bytes = name.encode("utf-8") + b"\x00"
    return b"\x0a" + name_bytes


def _build_child(name: str, content: bytes) -> bytes:
    """Construye un hijo: tag(0x03) + name\\0 + uint32_le(size) + content.
    Size es auto-inclusivo (incluye los 4 bytes del campo size)."""
    name_bytes = name.encode("utf-8") + b"\x00"
    size = 4 + len(content)
    return b"\x03" + name_bytes + struct.pack("<I", size) + content


def _build_list(name: str, content: bytes) -> bytes:
    """Construye una lista: tag(0x04) + name\\0 + uint32_le(size) + content."""
    name_bytes = name.encode("utf-8") + b"\x00"
    size = 4 + len(content)
    return b"\x04" + name_bytes + struct.pack("<I", size) + content


def _wrap_object(props_bytes: bytes) -> bytes:
    """Envuelve propiedades en un objeto raíz con tamaño y END marker."""
    total = 4 + len(props_bytes) + 1  # size + content + END
    return struct.pack("<I", total) + props_bytes + b"\x00"


def _build_simple_module(name: str, guid_bytes: bytes | None = None) -> bytes:
    """Construye un .mxunit de módulo simple con Name y $Type."""
    if guid_bytes is None:
        guid_bytes = uuid.uuid4().bytes
    props = (
        _build_guid_prop("$ID", guid_bytes)
        + _build_string_prop("$Type", "Projects$ModuleImpl")
        + _build_string_prop("Name", name)
    )
    return _wrap_object(props)


def _build_entity_child(name: str, attributes: list[str]) -> bytes:
    """Construye un hijo EntityImpl con atributos."""
    # Build attribute children
    attr_children = b""
    for i, attr_name in enumerate(attributes):
        attr_props = (
            _build_guid_prop("$ID")
            + _build_string_prop("$Type", "DomainModels$Attribute")
            + _build_string_prop("Name", attr_name)
        )
        attr_obj = _wrap_object(attr_props)
        attr_children += _build_child(str(i + 1), attr_obj[4:])  # skip outer size

    # Build Attributes list with header
    attr_list_content = _build_int32_prop("0", len(attributes)) + attr_children

    # Build entity props
    entity_props = (
        _build_guid_prop("$ID")
        + _build_string_prop("$Type", "DomainModels$EntityImpl")
        + _build_list("Attributes", attr_list_content)
        + _build_string_prop("Name", name)
    )
    return _wrap_object(entity_props)


def _build_domain_model(entities: list[tuple[str, list[str]]]) -> bytes:
    """Construye un DomainModels$DomainModel con entidades."""
    # Build entity children
    entity_children = b""
    for i, (ename, attrs) in enumerate(entities):
        entity_obj = _build_entity_child(ename, attrs)
        entity_children += _build_child(str(i + 1), entity_obj[4:])

    # Entities list with header
    entities_list_content = _build_int32_prop("0", len(entities)) + entity_children

    props = (
        _build_guid_prop("$ID")
        + _build_string_prop("$Type", "DomainModels$DomainModel")
        + _build_list("Entities", entities_list_content)
    )
    return _wrap_object(props)


def _build_page(name: str) -> bytes:
    """Construye un Forms$Page simple."""
    props = (
        _build_guid_prop("$ID")
        + _build_string_prop("$Type", "Forms$Page")
        + _build_bool_prop("Excluded", False)
        + _build_string_prop("Name", name)
    )
    return _wrap_object(props)


def _build_microflow(name: str) -> bytes:
    """Construye un Microflows$Microflow simple."""
    props = (
        _build_guid_prop("$ID")
        + _build_string_prop("$Type", "Microflows$Microflow")
        + _build_bool_prop("Excluded", False)
        + _build_string_prop("Name", name)
    )
    return _wrap_object(props)


def _build_project_security(roles: list[str]) -> bytes:
    """Construye un Security$ProjectSecurity con roles."""
    role_children = b""
    for i, role_name in enumerate(roles):
        role_props = (
            _build_guid_prop("$ID")
            + _build_string_prop("$Type", "Security$UserRole")
            + _build_string_prop("Name", role_name)
        )
        role_obj = _wrap_object(role_props)
        role_children += _build_child(str(i + 1), role_obj[4:])

    roles_list_content = _build_int32_prop("0", len(roles)) + role_children

    props = (
        _build_guid_prop("$ID")
        + _build_string_prop("$Type", "Security$ProjectSecurity")
        + _build_list("UserRoles", roles_list_content)
    )
    return _wrap_object(props)


# ============================================================
# Test fixtures
# ============================================================


def _create_test_mpr(
    tmp_path: Path,
    modules: dict[str, dict],
    roles: list[str] | None = None,
) -> Path:
    """Crea un proyecto .mpr de prueba completo en tmp_path.

    Args:
        tmp_path: Directorio temporal.
        modules: Dict de {nombre_módulo: {entities: [...], pages: [...], microflows: [...]}}.
        roles: Lista de roles de seguridad.

    Returns:
        Path al archivo .mpr creado.
    """
    mpr_path = tmp_path / "test.mpr"
    mprcontents = tmp_path / "mprcontents"

    # Create SQLite database
    conn = sqlite3.connect(str(mpr_path))
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE Unit (
            UnitID BLOB,
            ContainerID BLOB,
            ContainmentName TEXT,
            TreeConflict LONG,
            ContentsHash TEXT,
            ContentsConflicts TEXT
        )
    """)

    # Root unit
    root_uid = uuid.uuid4().bytes_le

    def _write_mxunit(uid_bytes: bytes, data: bytes) -> None:
        u = uuid.UUID(bytes_le=uid_bytes)
        uid_str = str(u)
        hex_str = uid_str.replace("-", "")
        path = mprcontents / hex_str[:2] / hex_str[2:4] / f"{uid_str}.mxunit"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    for mod_name, mod_config in modules.items():
        # Create module unit
        mod_uid = uuid.uuid4().bytes_le
        cur.execute(
            "INSERT INTO Unit VALUES (?, ?, 'Modules', 0, '', '')",
            (mod_uid, root_uid),
        )
        _write_mxunit(mod_uid, _build_simple_module(mod_name))

        # Create DomainModel unit
        entities = mod_config.get("entities", [])
        if entities:
            dm_uid = uuid.uuid4().bytes_le
            cur.execute(
                "INSERT INTO Unit VALUES (?, ?, 'DomainModel', 0, '', '')",
                (dm_uid, mod_uid),
            )
            _write_mxunit(dm_uid, _build_domain_model(entities))

        # Create Document units for pages
        for page_name in mod_config.get("pages", []):
            page_uid = uuid.uuid4().bytes_le
            cur.execute(
                "INSERT INTO Unit VALUES (?, ?, 'Documents', 0, '', '')",
                (page_uid, mod_uid),
            )
            _write_mxunit(page_uid, _build_page(page_name))

        # Create Document units for microflows
        for mf_name in mod_config.get("microflows", []):
            mf_uid = uuid.uuid4().bytes_le
            cur.execute(
                "INSERT INTO Unit VALUES (?, ?, 'Documents', 0, '', '')",
                (mf_uid, mod_uid),
            )
            _write_mxunit(mf_uid, _build_microflow(mf_name))

    # Create ProjectSecurity
    if roles:
        sec_uid = uuid.uuid4().bytes_le
        cur.execute(
            "INSERT INTO Unit VALUES (?, ?, 'ProjectDocuments', 0, '', '')",
            (sec_uid, root_uid),
        )
        _write_mxunit(sec_uid, _build_project_security(roles))

    conn.commit()
    conn.close()
    return mpr_path


# ============================================================
# Tests: MxunitParser
# ============================================================


class TestMxunitParserProps:
    """Tests para parse_top_level_props."""

    def test_parse_string_props(self):
        data = _wrap_object(
            _build_string_prop("$Type", "Test$Type")
            + _build_string_prop("Name", "TestName")
        )
        props = MxunitParser.parse_top_level_props(data)
        assert props["$Type"] == "Test$Type"
        assert props["Name"] == "TestName"

    def test_parse_bool_prop(self):
        data = _wrap_object(
            _build_string_prop("$Type", "Test$Type")
            + _build_bool_prop("Excluded", True)
        )
        props = MxunitParser.parse_top_level_props(data)
        assert props["Excluded"] is True

    def test_parse_long_prop(self):
        data = _wrap_object(
            _build_string_prop("$Type", "Test$Type")
            + _build_long_prop("Height", 600)
        )
        props = MxunitParser.parse_top_level_props(data)
        assert props["Height"] == 600

    def test_parse_int32_prop(self):
        data = _wrap_object(
            _build_string_prop("$Type", "Test$Type")
            + _build_int32_prop("Count", 42)
        )
        props = MxunitParser.parse_top_level_props(data)
        assert props["Count"] == 42

    def test_parse_null_prop(self):
        data = _wrap_object(
            _build_string_prop("$Type", "Test$Type")
            + _build_null_prop("Empty")
        )
        props = MxunitParser.parse_top_level_props(data)
        assert props["Empty"] is None

    def test_parse_guid_prop(self):
        guid = b"\x01\x02\x03\x04" * 4
        data = _wrap_object(
            _build_guid_prop("$ID", guid)
            + _build_string_prop("$Type", "Test$Type")
        )
        props = MxunitParser.parse_top_level_props(data)
        assert props["$ID"] == guid

    def test_skip_child_objects(self):
        """Top-level props should skip child objects/lists."""
        child_content = _build_string_prop("InnerName", "ShouldNotAppear")
        data = _wrap_object(
            _build_string_prop("$Type", "Forms$Page")
            + _build_child("ChildObj", child_content)
            + _build_string_prop("Name", "PageName")
        )
        props = MxunitParser.parse_top_level_props(data)
        assert props["$Type"] == "Forms$Page"
        assert props["Name"] == "PageName"
        assert "InnerName" not in props

    def test_skip_list_objects(self):
        """Top-level props should skip lists."""
        list_content = _build_int32_prop("0", 0)
        data = _wrap_object(
            _build_string_prop("$Type", "Test$Type")
            + _build_list("Items", list_content)
            + _build_string_prop("Name", "AfterList")
        )
        props = MxunitParser.parse_top_level_props(data)
        assert props["Name"] == "AfterList"

    def test_empty_string(self):
        data = _wrap_object(
            _build_string_prop("$Type", "Test$Type")
            + _build_string_prop("Name", "")
        )
        props = MxunitParser.parse_top_level_props(data)
        assert props["Name"] == ""

    def test_corrupt_data_returns_partial(self):
        """Truncated data should return what was parsed so far."""
        data = _wrap_object(
            _build_string_prop("$Type", "Test$Type")
            + _build_string_prop("Name", "TestName")
        )
        # Truncate
        truncated = data[:20]
        props = MxunitParser.parse_top_level_props(truncated)
        # Should have at least $Type
        assert "$Type" in props


class TestMxunitParserExtract:
    """Tests para extract_type, extract_name, extract_type_and_name."""

    def test_extract_type(self):
        data = _wrap_object(
            _build_guid_prop("$ID")
            + _build_string_prop("$Type", "Forms$Page")
            + _build_string_prop("Name", "MyPage")
        )
        assert MxunitParser.extract_type(data) == "Forms$Page"

    def test_extract_name(self):
        data = _wrap_object(
            _build_guid_prop("$ID")
            + _build_string_prop("$Type", "Forms$Page")
            + _build_string_prop("Name", "MyPage")
        )
        assert MxunitParser.extract_name(data) == "MyPage"

    def test_extract_type_and_name(self):
        data = _wrap_object(
            _build_guid_prop("$ID")
            + _build_string_prop("$Type", "Microflows$Microflow")
            + _build_string_prop("Name", "ACT_Save")
        )
        t, n = MxunitParser.extract_type_and_name(data)
        assert t == "Microflows$Microflow"
        assert n == "ACT_Save"

    def test_extract_type_none_for_missing(self):
        data = _wrap_object(_build_string_prop("Name", "NoType"))
        assert MxunitParser.extract_type(data) is None


class TestMxunitParserEntities:
    """Tests para extract_entities_from_domain_model."""

    def test_extract_entities_basic(self):
        data = _build_domain_model([
            ("Customer", ["Name", "Email", "Phone"]),
            ("Order", ["OrderDate", "Total"]),
        ])
        entities = MxunitParser.extract_entities_from_domain_model(data)
        assert len(entities) == 2
        assert entities[0] == ("Customer", ["Name", "Email", "Phone"])
        assert entities[1] == ("Order", ["OrderDate", "Total"])

    def test_extract_entities_empty(self):
        data = _build_domain_model([])
        entities = MxunitParser.extract_entities_from_domain_model(data)
        assert entities == []

    def test_extract_entity_no_attributes(self):
        data = _build_domain_model([("EmptyEntity", [])])
        entities = MxunitParser.extract_entities_from_domain_model(data)
        assert len(entities) == 1
        assert entities[0] == ("EmptyEntity", [])

    def test_extract_many_entities(self):
        entity_list = [(f"Entity{i}", [f"Attr{j}" for j in range(3)])
                       for i in range(10)]
        data = _build_domain_model(entity_list)
        entities = MxunitParser.extract_entities_from_domain_model(data)
        assert len(entities) == 10
        for i, (name, attrs) in enumerate(entities):
            assert name == f"Entity{i}"
            assert len(attrs) == 3


class TestMxunitParserRoles:
    """Tests para extract_user_roles."""

    def test_extract_roles(self):
        data = _build_project_security(["Administrator", "User", "ReadOnly"])
        roles = MxunitParser.extract_user_roles(data)
        assert roles == ["Administrator", "User", "ReadOnly"]

    def test_extract_roles_empty(self):
        data = _build_project_security([])
        roles = MxunitParser.extract_user_roles(data)
        assert roles == []


class TestMxunitParserUidPath:
    """Tests para uid_to_mxunit_path."""

    def test_uid_to_path(self):
        # Create a known UUID and check path
        u = uuid.UUID("2a662a05-9996-48d4-b5d0-e0cc7a54573c")
        uid_bytes = u.bytes_le
        path = MxunitParser.uid_to_mxunit_path(uid_bytes, Path("/project"))
        assert "2a" in str(path)
        assert "66" in str(path)
        assert "2a662a05-9996-48d4-b5d0-e0cc7a54573c.mxunit" in str(path)


# ============================================================
# Tests: MprDirectReader
# ============================================================


class TestMprDirectReader:
    """Tests para MprDirectReader con proyecto sintético."""

    @pytest.fixture
    def test_project(self, tmp_path: Path) -> Path:
        """Crea un proyecto de prueba con estructura conocida."""
        return _create_test_mpr(
            tmp_path,
            modules={
                "MyModule": {
                    "entities": [
                        ("Customer", ["Name", "Email"]),
                        ("Order", ["Total", "Date"]),
                    ],
                    "pages": ["Customer_NewEdit", "Order_Overview"],
                    "microflows": ["ACT_Customer_Save", "VAL_Order_Validate"],
                },
                "Admin": {
                    "entities": [("Account", ["Username"])],
                    "pages": ["Account_List"],
                    "microflows": [],
                },
            },
            roles=["Administrator", "User"],
        )

    def test_ping(self):
        reader = MprDirectReader()
        assert reader.ping() is True

    def test_read_modules(self, test_project: Path):
        reader = MprDirectReader()
        structure = reader.read_project_structure(test_project)
        module_names = {m.name for m in structure.modules}
        assert "MyModule" in module_names
        assert "Admin" in module_names
        assert len(structure.modules) == 2

    def test_read_entities(self, test_project: Path):
        reader = MprDirectReader()
        structure = reader.read_project_structure(test_project)
        entities = structure.all_entity_names
        assert "Customer" in entities
        assert "Order" in entities
        assert "Account" in entities
        assert len(entities) == 3

    def test_read_entity_attributes(self, test_project: Path):
        reader = MprDirectReader()
        structure = reader.read_project_structure(test_project)
        my_module = next(m for m in structure.modules if m.name == "MyModule")
        customer = next(e for e in my_module.entities if e.name == "Customer")
        assert customer.attributes == ["Name", "Email"]

    def test_read_pages(self, test_project: Path):
        reader = MprDirectReader()
        structure = reader.read_project_structure(test_project)
        pages = structure.all_page_names
        assert "Customer_NewEdit" in pages
        assert "Order_Overview" in pages
        assert "Account_List" in pages
        assert len(pages) == 3

    def test_read_microflows(self, test_project: Path):
        reader = MprDirectReader()
        structure = reader.read_project_structure(test_project)
        mfs = structure.all_microflow_names
        assert "ACT_Customer_Save" in mfs
        assert "VAL_Order_Validate" in mfs
        assert len(mfs) == 2

    def test_read_roles(self, test_project: Path):
        reader = MprDirectReader()
        structure = reader.read_project_structure(test_project)
        assert structure.security.roles == ["Administrator", "User"]

    def test_check_artifact_exists_entity(self, test_project: Path):
        reader = MprDirectReader()
        reader.read_project_structure(test_project)
        assert reader.check_artifact_exists(
            test_project, "entity", "MyModule", "Customer"
        )
        assert not reader.check_artifact_exists(
            test_project, "entity", "MyModule", "NonExistent"
        )

    def test_check_artifact_exists_page(self, test_project: Path):
        reader = MprDirectReader()
        reader.read_project_structure(test_project)
        assert reader.check_artifact_exists(
            test_project, "page", "MyModule", "Customer_NewEdit"
        )
        assert not reader.check_artifact_exists(
            test_project, "page", "Admin", "NonExistent"
        )

    def test_check_artifact_exists_microflow(self, test_project: Path):
        reader = MprDirectReader()
        reader.read_project_structure(test_project)
        assert reader.check_artifact_exists(
            test_project, "microflow", "MyModule", "ACT_Customer_Save"
        )

    def test_cache_works(self, test_project: Path):
        reader = MprDirectReader()
        s1 = reader.read_project_structure(test_project)
        s2 = reader.read_project_structure(test_project)
        assert s1 is s2  # Same object (cached)

    def test_mpr_not_found_raises(self, tmp_path: Path):
        reader = MprDirectReader()
        with pytest.raises(SDKClientError, match="no encontrado"):
            reader.read_project_structure(tmp_path / "nonexistent.mpr")

    def test_write_methods_raise(self, test_project: Path):
        reader = MprDirectReader()
        with pytest.raises(NotImplementedError):
            reader.create_entity(test_project, {})
        with pytest.raises(NotImplementedError):
            reader.create_page(test_project, {})
        with pytest.raises(NotImplementedError):
            reader.create_microflow(test_project, {})


class TestMprDirectReaderEmptyProject:
    """Tests con proyecto vacío (sin módulos)."""

    @pytest.fixture
    def empty_project(self, tmp_path: Path) -> Path:
        return _create_test_mpr(tmp_path, modules={}, roles=None)

    def test_empty_project(self, empty_project: Path):
        reader = MprDirectReader()
        structure = reader.read_project_structure(empty_project)
        assert len(structure.modules) == 0
        assert len(structure.all_entity_names) == 0
        assert len(structure.security.roles) == 0
