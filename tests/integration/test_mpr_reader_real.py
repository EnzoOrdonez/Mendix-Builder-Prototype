"""Tests de integración para MprDirectReader contra proyecto GestionProcesal real.

Estos tests requieren el proyecto de referencia en:
  reference_project/GestionProcesal-Enzo_3_from_QA/GestionProcesal.mpr

Se saltan automáticamente si el proyecto no está disponible.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from mendex.bridge.mpr_reader import MprDirectReader

# Path al proyecto de referencia
_REFERENCE_PROJECT = Path(
    "reference_project/GestionProcesal-Enzo_3_from_QA/GestionProcesal.mpr"
)

# Si ejecutamos desde la raíz del repo
if not _REFERENCE_PROJECT.exists():
    _REFERENCE_PROJECT = (
        Path(__file__).parent.parent.parent / _REFERENCE_PROJECT
    )

_HAS_PROJECT = _REFERENCE_PROJECT.exists()

pytestmark = pytest.mark.skipif(
    not _HAS_PROJECT,
    reason="Proyecto de referencia GestionProcesal no disponible",
)


@pytest.fixture(scope="module")
def reader() -> MprDirectReader:
    return MprDirectReader()


@pytest.fixture(scope="module")
def mpr_path() -> Path:
    return _REFERENCE_PROJECT


@pytest.fixture(scope="module")
def structure(reader: MprDirectReader, mpr_path: Path):
    return reader.read_project_structure(mpr_path)


class TestMprDirectReaderReal:
    """Tests contra proyecto GestionProcesal real."""

    def test_reads_all_modules(self, structure):
        """Debe encontrar 25 módulos."""
        assert len(structure.modules) == 25

    def test_known_module_names(self, structure):
        """Módulos conocidos deben existir."""
        module_names = {m.name for m in structure.modules}
        expected = {
            "GestionProcesal",
            "Administration",
            "ExcelImporter",
            "Email_Connector",
            "AuditTrail",
            "Atlas_Core",
        }
        assert expected.issubset(module_names)

    def test_reads_entities(self, structure):
        """Debe encontrar al menos 140 entidades (157 esperadas)."""
        total = len(structure.all_entity_names)
        assert total >= 140, f"Solo {total} entidades encontradas, esperadas >= 140"

    def test_gestion_procesal_entities(self, structure):
        """Módulo GestionProcesal debe tener al menos 50 entidades."""
        gp = next(m for m in structure.modules if m.name == "GestionProcesal")
        assert len(gp.entities) >= 50

    def test_known_entity_names(self, structure):
        """Entidades conocidas deben existir."""
        entity_names = set(structure.all_entity_names)
        expected = {
            "SGP_DocumentosRecepcion",
            "SGP_Expedientes",
            "Account",
        }
        assert expected.issubset(entity_names)

    def test_entity_attributes(self, structure):
        """Entidades deben tener atributos extraídos."""
        gp = next(m for m in structure.modules if m.name == "GestionProcesal")
        doc = next(
            e for e in gp.entities if e.name == "SGP_DocumentosRecepcion"
        )
        assert len(doc.attributes) >= 10
        assert "SGP_TipoDocumento" in doc.attributes

    def test_reads_pages(self, structure):
        """Debe encontrar al menos 400 páginas (442 esperadas)."""
        total = len(structure.all_page_names)
        assert total >= 400, f"Solo {total} páginas encontradas, esperadas >= 400"

    def test_reads_microflows(self, structure):
        """Debe encontrar al menos 450 microflows (495 esperados)."""
        total = len(structure.all_microflow_names)
        assert total >= 450, f"Solo {total} microflows encontrados, esperados >= 450"

    def test_reads_security_roles(self, structure):
        """Debe encontrar 11 roles de seguridad."""
        assert len(structure.security.roles) == 11

    def test_known_roles(self, structure):
        """Roles conocidos deben existir."""
        assert "Administrator" in structure.security.roles
        assert "User" in structure.security.roles

    def test_modules_have_pages(self, structure):
        """GestionProcesal debe tener al menos 100 páginas."""
        gp = next(m for m in structure.modules if m.name == "GestionProcesal")
        assert len(gp.pages) >= 100

    def test_modules_have_microflows(self, structure):
        """GestionProcesal debe tener al menos 80 microflows."""
        gp = next(m for m in structure.modules if m.name == "GestionProcesal")
        assert len(gp.microflows) >= 80

    def test_performance_under_1_second(self, mpr_path: Path):
        """Lectura completa debe tomar menos de 1 segundo."""
        reader = MprDirectReader()  # Fresh reader, no cache
        start = time.perf_counter()
        reader.read_project_structure(mpr_path)
        elapsed = time.perf_counter() - start
        assert elapsed < 1.0, f"Lectura tomó {elapsed:.2f}s, máximo esperado 1.0s"

    def test_cached_read_fast(self, reader: MprDirectReader, mpr_path: Path):
        """Lectura cacheada debe tomar menos de 1ms."""
        # Ensure cache is populated
        reader.read_project_structure(mpr_path)
        start = time.perf_counter()
        reader.read_project_structure(mpr_path)
        elapsed = time.perf_counter() - start
        assert elapsed < 0.001, f"Lectura cacheada tomó {elapsed*1000:.2f}ms"

    def test_check_artifact_exists_entity(
        self, reader: MprDirectReader, mpr_path: Path
    ):
        assert reader.check_artifact_exists(
            mpr_path, "entity", "GestionProcesal", "SGP_Expedientes"
        )
        assert not reader.check_artifact_exists(
            mpr_path, "entity", "GestionProcesal", "NonExistentEntity"
        )

    def test_check_artifact_exists_page(
        self, reader: MprDirectReader, mpr_path: Path
    ):
        assert reader.check_artifact_exists(
            mpr_path, "page", "ExcelImporter", "ExcelImportOverview"
        )

    def test_check_artifact_exists_microflow(
        self, reader: MprDirectReader, mpr_path: Path
    ):
        # ExcelImporter should have microflows
        structure = reader.read_project_structure(mpr_path)
        ei = next(m for m in structure.modules if m.name == "ExcelImporter")
        if ei.microflows:
            assert reader.check_artifact_exists(
                mpr_path, "microflow", "ExcelImporter", ei.microflows[0]
            )
