"""Tests unitarios para el extractor de convenciones.

Fase 3: Cobertura de ConventionsExtractor, ConventionsReader y MockSDKClient.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from mendex.bridge.sdk_client import (
    EntityInfo,
    MockSDKClient,
    ModuleInfo,
    ProjectStructure,
    SecurityInfo,
)
from mendex.knowledge.conventions_extractor import (
    ConventionsExtractor,
    ConventionsExtractorError,
    ExtractionResult,
)
from mendex.knowledge.conventions_reader import ConventionsReader, ConventionsReaderError
from mendex.logging.decision_logger import DecisionLogger


# ─── Fixtures ────────────────────────────────────────────────────


@pytest.fixture
def sample_structure() -> ProjectStructure:
    """Estructura de proyecto Mendix realista para tests."""
    return ProjectStructure(
        modules=[
            ModuleInfo(
                name="Administracion",
                entities=[
                    EntityInfo(name="Usuario", attributes=["Nombre", "Email", "FechaRegistro"]),
                    EntityInfo(name="Rol", attributes=["Nombre", "Descripcion"]),
                ],
                pages=["Usuario_Overview", "Usuario_NewEdit", "Rol_Overview"],
                microflows=["ACT_Usuario_Guardar", "VAL_Usuario_Validar", "ACT_Rol_Crear"],
            ),
            ModuleInfo(
                name="Operaciones",
                entities=[
                    EntityInfo(name="OrdenCompra", attributes=["Fecha", "MontoTotal", "Estado"]),
                    EntityInfo(name="LineaDetalle", attributes=["Cantidad", "PrecioUnitario"]),
                    EntityInfo(name="Proveedor", attributes=["RazonSocial", "RUC"]),
                ],
                pages=["OrdenCompra_Overview", "OrdenCompra_NewEdit", "Proveedor_Overview"],
                microflows=[
                    "ACT_OrdenCompra_Guardar",
                    "VAL_OrdenCompra_Validar",
                    "ACT_Proveedor_Crear",
                    "SUB_LineaDetalle_Calcular",
                ],
            ),
        ],
        security=SecurityInfo(roles=["Administrator", "User", "ReadOnly"]),
    )


@pytest.fixture
def mock_client(sample_structure: ProjectStructure) -> MockSDKClient:
    return MockSDKClient(project_structure=sample_structure)


@pytest.fixture
def tmp_mpr(tmp_path: Path) -> Path:
    """Crea un archivo .mpr de prueba."""
    mpr = tmp_path / "test.mpr"
    mpr.write_bytes(b"FAKE_MPR_CONTENT_FOR_TESTING")
    return mpr


@pytest.fixture
def output_path(tmp_path: Path) -> Path:
    return tmp_path / "conventions" / "project_conventions.yaml"


@pytest.fixture
def hash_path(tmp_path: Path) -> Path:
    return tmp_path / "conventions" / ".mpr_hash"


@pytest.fixture
def extractor(
    mock_client: MockSDKClient,
    output_path: Path,
    hash_path: Path,
) -> ConventionsExtractor:
    return ConventionsExtractor(
        sdk_client=mock_client,
        output_path=output_path,
        hash_path=hash_path,
        project_name="TestProject",
    )


# ─── Tests de ConventionsExtractor ──────────────────────────────


class TestConventionsExtractor:
    def test_extract_creates_yaml(
        self, extractor: ConventionsExtractor, tmp_mpr: Path, output_path: Path
    ) -> None:
        """La extracción crea el archivo YAML."""
        extractor.extract(tmp_mpr)
        assert output_path.exists()

    def test_extract_creates_hash_file(
        self, extractor: ConventionsExtractor, tmp_mpr: Path, hash_path: Path
    ) -> None:
        """La extracción persiste el hash del .mpr."""
        extractor.extract(tmp_mpr)
        assert hash_path.exists()
        hash_content = hash_path.read_text(encoding="utf-8").strip()
        assert len(hash_content) == 64  # SHA-256

    def test_extract_returns_result(
        self, extractor: ConventionsExtractor, tmp_mpr: Path
    ) -> None:
        """La extracción retorna ExtractionResult con metadata correcta."""
        result = extractor.extract(tmp_mpr)

        assert isinstance(result, ExtractionResult)
        assert result.modules_count == 2
        assert result.entities_count == 5
        assert result.pages_count == 6
        assert result.microflows_count == 7
        assert result.previous_hash is None  # Primera extracción
        assert result.changed is False

    def test_yaml_has_required_sections(
        self, extractor: ConventionsExtractor, tmp_mpr: Path, output_path: Path
    ) -> None:
        """El YAML generado tiene todas las secciones requeridas."""
        extractor.extract(tmp_mpr)

        with open(output_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        assert "project" in data
        assert "naming" in data
        assert "modules" in data
        assert "common_patterns" in data
        assert "data_types" in data

    def test_yaml_project_section(
        self, extractor: ConventionsExtractor, tmp_mpr: Path, output_path: Path
    ) -> None:
        """La sección project tiene los campos correctos."""
        extractor.extract(tmp_mpr, mendix_version="10.24.16")

        with open(output_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        assert data["project"]["name"] == "TestProject"
        assert data["project"]["mendix_version"] == "10.24.16"
        assert data["project"]["mpr_hash"]  # No vacío
        assert data["project"]["extracted_at"]  # No vacío

    def test_yaml_naming_contains_examples(
        self, extractor: ConventionsExtractor, tmp_mpr: Path, output_path: Path
    ) -> None:
        """La sección naming incluye ejemplos del proyecto."""
        extractor.extract(tmp_mpr)

        with open(output_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        assert len(data["naming"]["entities"]["examples"]) > 0
        assert "Usuario" in data["naming"]["entities"]["examples"]
        assert "OrdenCompra" in data["naming"]["entities"]["examples"]

    def test_yaml_modules_populated(
        self, extractor: ConventionsExtractor, tmp_mpr: Path, output_path: Path
    ) -> None:
        """La sección modules lista los módulos del proyecto."""
        extractor.extract(tmp_mpr)

        with open(output_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        module_names = [m["name"] for m in data["modules"]]
        assert "Administracion" in module_names
        assert "Operaciones" in module_names

    def test_yaml_security_roles(
        self, extractor: ConventionsExtractor, tmp_mpr: Path, output_path: Path
    ) -> None:
        """Los roles de seguridad se extraen correctamente."""
        extractor.extract(tmp_mpr)

        with open(output_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        roles = data["common_patterns"]["access_rules"]["roles"]
        assert "Administrator" in roles
        assert "User" in roles

    def test_raises_on_nonexistent_mpr(
        self, extractor: ConventionsExtractor, tmp_path: Path
    ) -> None:
        """Lanza error si el .mpr no existe."""
        fake = tmp_path / "no_existe.mpr"
        with pytest.raises(ConventionsExtractorError, match="no existe"):
            extractor.extract(fake)

    def test_idempotent_extraction(
        self, extractor: ConventionsExtractor, tmp_mpr: Path, output_path: Path
    ) -> None:
        """Dos extracciones con el mismo .mpr producen YAML idéntico (excepto timestamp)."""
        extractor.extract(tmp_mpr)
        with open(output_path, encoding="utf-8") as f:
            data1 = yaml.safe_load(f)

        extractor.extract(tmp_mpr)
        with open(output_path, encoding="utf-8") as f:
            data2 = yaml.safe_load(f)

        # Todo igual excepto extracted_at
        assert data1["naming"] == data2["naming"]
        assert data1["modules"] == data2["modules"]
        assert data1["common_patterns"] == data2["common_patterns"]

    def test_detects_mpr_change(
        self, extractor: ConventionsExtractor, tmp_mpr: Path
    ) -> None:
        """Detecta cuando el .mpr cambia entre extracciones."""
        result1 = extractor.extract(tmp_mpr)
        assert result1.previous_hash is None

        # Cambiar el .mpr
        tmp_mpr.write_bytes(b"CHANGED_MPR_CONTENT")

        result2 = extractor.extract(tmp_mpr)
        assert result2.previous_hash is not None
        assert result2.changed is True
        assert result2.mpr_hash != result1.mpr_hash

    def test_check_outdated_no_previous(
        self, extractor: ConventionsExtractor, tmp_mpr: Path
    ) -> None:
        """check_outdated retorna True si nunca se extrajo."""
        assert extractor.check_outdated(tmp_mpr) is True

    def test_check_outdated_unchanged(
        self, extractor: ConventionsExtractor, tmp_mpr: Path
    ) -> None:
        """check_outdated retorna False si el .mpr no cambió."""
        extractor.extract(tmp_mpr)
        assert extractor.check_outdated(tmp_mpr) is False

    def test_check_outdated_changed(
        self, extractor: ConventionsExtractor, tmp_mpr: Path
    ) -> None:
        """check_outdated retorna True si el .mpr cambió."""
        extractor.extract(tmp_mpr)
        tmp_mpr.write_bytes(b"NEW_CONTENT")
        assert extractor.check_outdated(tmp_mpr) is True

    def test_with_decision_logger(
        self, mock_client: MockSDKClient, tmp_mpr: Path, tmp_path: Path
    ) -> None:
        """La extracción registra decisiones si se provee logger."""
        log_path = tmp_path / "logs" / "decisions.jsonl"
        decision_logger = DecisionLogger(log_path)

        extractor = ConventionsExtractor(
            sdk_client=mock_client,
            output_path=tmp_path / "conv.yaml",
            hash_path=tmp_path / ".mpr_hash",
            decision_logger=decision_logger,
        )
        extractor.extract(tmp_mpr)

        entries = decision_logger.read_entries()
        assert len(entries) == 1
        assert entries[0].operation == "extract_conventions"

    def test_extraction_result_summary(
        self, extractor: ConventionsExtractor, tmp_mpr: Path
    ) -> None:
        """ExtractionResult.summary() genera texto legible."""
        result = extractor.extract(tmp_mpr)
        summary = result.summary()

        assert "Módulos: 2" in summary
        assert "Entidades: 5" in summary
        assert "PRIMERA EXTRACCIÓN" in summary


# ─── Tests de naming pattern detection ──────────────────────────


class TestNamingDetection:
    def test_detect_pascal_case(self) -> None:
        names = ["OrdenCompra", "LineaDetalle", "Proveedor", "Usuario"]
        result = ConventionsExtractor._detect_naming_pattern(names)
        assert result["pattern"] == "PascalCase"

    def test_detect_camel_case(self) -> None:
        names = ["ordenCompra", "lineaDetalle", "proveedor"]
        result = ConventionsExtractor._detect_naming_pattern(names)
        assert result["pattern"] == "camelCase"

    def test_detect_snake_case(self) -> None:
        names = ["orden_compra", "linea_detalle", "proveedor"]
        result = ConventionsExtractor._detect_naming_pattern(names)
        assert result["pattern"] == "snake_case"

    def test_detect_empty_list(self) -> None:
        result = ConventionsExtractor._detect_naming_pattern([])
        assert result["pattern"] == "PascalCase"  # Default

    def test_detect_microflow_prefix_pattern(self) -> None:
        names = ["ACT_User_Save", "VAL_Order_Validate", "SUB_Line_Calculate"]
        result = ConventionsExtractor._detect_microflow_pattern(names)
        assert "Prefix" in result["pattern"] or "Action" in result["pattern"]

    def test_detect_page_pattern(self) -> None:
        names = ["User_Overview", "Order_NewEdit", "Provider_Detail"]
        result = ConventionsExtractor._detect_page_pattern(names)
        assert "Entity" in result["pattern"] or "Action" in result["pattern"]


# ─── Tests de ConventionsReader ─────────────────────────────────


class TestConventionsReader:
    @pytest.fixture
    def populated_yaml(self, tmp_path: Path) -> Path:
        """Crea un YAML de convenciones completo para tests."""
        yaml_path = tmp_path / "conventions.yaml"
        data = {
            "project": {
                "name": "MiProyecto",
                "mendix_version": "10.24.16",
                "extracted_at": "2026-01-15T10:00:00Z",
                "mpr_hash": "abc123",
            },
            "naming": {
                "entities": {
                    "pattern": "PascalCase",
                    "prefix": "",
                    "examples": ["OrdenCompra", "Proveedor"],
                },
                "attributes": {
                    "pattern": "PascalCase",
                    "examples": ["FechaCreacion", "MontoTotal"],
                },
                "microflows": {
                    "pattern": "{Prefix}_{Entity}_{Action}",
                    "examples": ["ACT_OrdenCompra_Guardar"],
                },
                "pages": {
                    "pattern": "{Entity}_{Action}",
                    "examples": ["OrdenCompra_NewEdit"],
                },
            },
            "modules": [
                {"name": "Administracion", "entity_count": 5, "description": "Admin"},
                {"name": "Operaciones", "entity_count": 10, "description": "Ops"},
            ],
            "common_patterns": {
                "access_rules": {
                    "roles": ["Administrator", "User"],
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
                "most_used": ["String", "DateTime", "Decimal"],
                "enumerations": [],
            },
        }
        yaml_path.write_text(yaml.dump(data), encoding="utf-8")
        return yaml_path

    def test_load_succeeds(self, populated_yaml: Path) -> None:
        reader = ConventionsReader(populated_yaml)
        reader.load()
        assert reader.is_loaded

    def test_raises_before_load(self, populated_yaml: Path) -> None:
        reader = ConventionsReader(populated_yaml)
        with pytest.raises(ConventionsReaderError, match="no cargadas"):
            _ = reader.project_name

    def test_raises_on_missing_file(self, tmp_path: Path) -> None:
        reader = ConventionsReader(tmp_path / "missing.yaml")
        with pytest.raises(ConventionsReaderError, match="no encontrado"):
            reader.load()

    def test_project_name(self, populated_yaml: Path) -> None:
        reader = ConventionsReader(populated_yaml)
        reader.load()
        assert reader.project_name == "MiProyecto"

    def test_mendix_version(self, populated_yaml: Path) -> None:
        reader = ConventionsReader(populated_yaml)
        reader.load()
        assert reader.mendix_version == "10.24.16"

    def test_entity_naming(self, populated_yaml: Path) -> None:
        reader = ConventionsReader(populated_yaml)
        reader.load()
        assert reader.entity_naming_pattern == "PascalCase"
        assert "OrdenCompra" in reader.entity_naming_examples

    def test_security_roles(self, populated_yaml: Path) -> None:
        reader = ConventionsReader(populated_yaml)
        reader.load()
        assert "Administrator" in reader.security_roles
        assert reader.default_access_policy == "deny_all_then_grant"

    def test_module_names(self, populated_yaml: Path) -> None:
        reader = ConventionsReader(populated_yaml)
        reader.load()
        assert "Administracion" in reader.module_names
        assert "Operaciones" in reader.module_names

    def test_most_used_types(self, populated_yaml: Path) -> None:
        reader = ConventionsReader(populated_yaml)
        reader.load()
        assert "String" in reader.most_used_types

    def test_content_hash(self, populated_yaml: Path) -> None:
        reader = ConventionsReader(populated_yaml)
        reader.load()
        assert len(reader.content_hash) == 64

    def test_reload_detects_changes(self, populated_yaml: Path) -> None:
        reader = ConventionsReader(populated_yaml)
        reader.load()
        old_hash = reader.content_hash

        # Modificar el archivo
        data = yaml.safe_load(populated_yaml.read_text(encoding="utf-8"))
        data["project"]["name"] = "MODIFIED"
        populated_yaml.write_text(yaml.dump(data), encoding="utf-8")

        changed = reader.reload()
        assert changed is True
        assert reader.content_hash != old_hash
        assert reader.project_name == "MODIFIED"

    def test_reload_no_changes(self, populated_yaml: Path) -> None:
        reader = ConventionsReader(populated_yaml)
        reader.load()
        changed = reader.reload()
        assert changed is False

    def test_as_context_string(self, populated_yaml: Path) -> None:
        reader = ConventionsReader(populated_yaml)
        reader.load()
        ctx = reader.as_context_string()

        assert "MiProyecto" in ctx
        assert "PascalCase" in ctx
        assert "Administrator" in ctx
        assert "Administracion" in ctx

    def test_default_page_layout(self, populated_yaml: Path) -> None:
        reader = ConventionsReader(populated_yaml)
        reader.load()
        assert reader.default_page_layout == "Atlas_Default"


# ─── Tests de MockSDKClient ─────────────────────────────────────


class TestMockSDKClient:
    def test_ping(self) -> None:
        client = MockSDKClient()
        assert client.ping() is True

    def test_read_empty_structure(self, tmp_path: Path) -> None:
        client = MockSDKClient()
        structure = client.read_project_structure(tmp_path / "test.mpr")
        assert structure.modules == []

    def test_read_custom_structure(
        self, sample_structure: ProjectStructure, tmp_path: Path
    ) -> None:
        client = MockSDKClient(project_structure=sample_structure)
        structure = client.read_project_structure(tmp_path / "test.mpr")
        assert len(structure.modules) == 2
        assert structure.all_entity_names == [
            "Usuario", "Rol", "OrdenCompra", "LineaDetalle", "Proveedor"
        ]

    def test_check_artifact_exists(self, tmp_path: Path) -> None:
        client = MockSDKClient(
            existing_artifacts={"entity:Ops.OrdenCompra", "page:Ops.OrdenCompra_NewEdit"}
        )
        assert client.check_artifact_exists(
            tmp_path / "t.mpr", "entity", "Ops", "OrdenCompra"
        ) is True
        assert client.check_artifact_exists(
            tmp_path / "t.mpr", "entity", "Ops", "NoExiste"
        ) is False


# ─── Tests de ProjectStructure helpers ───────────────────────────


class TestProjectStructure:
    def test_all_entity_names(self, sample_structure: ProjectStructure) -> None:
        names = sample_structure.all_entity_names
        assert "Usuario" in names
        assert "OrdenCompra" in names
        assert len(names) == 5

    def test_all_page_names(self, sample_structure: ProjectStructure) -> None:
        names = sample_structure.all_page_names
        assert "Usuario_Overview" in names
        assert len(names) == 6

    def test_all_microflow_names(self, sample_structure: ProjectStructure) -> None:
        names = sample_structure.all_microflow_names
        assert "ACT_Usuario_Guardar" in names
        assert len(names) == 7

    def test_all_attribute_names(self, sample_structure: ProjectStructure) -> None:
        names = sample_structure.all_attribute_names
        assert "Nombre" in names
        assert "MontoTotal" in names
