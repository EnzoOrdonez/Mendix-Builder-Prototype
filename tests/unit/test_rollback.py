"""Tests unitarios para el sistema de rollback / backup del .mpr.

Fase 1: Cobertura completa de RollbackManager y atomic_mpr_operation.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from mendex.bridge.rollback import (
    BackupInfo,
    RollbackError,
    RollbackManager,
    atomic_mpr_operation,
)


@pytest.fixture
def tmp_mpr(tmp_path: Path) -> Path:
    """Crea un archivo .mpr de prueba con contenido conocido."""
    mpr = tmp_path / "test_project.mpr"
    mpr.write_bytes(b"MENDIX_MPR_ORIGINAL_CONTENT_12345")
    return mpr


@pytest.fixture
def manager() -> RollbackManager:
    """RollbackManager con max_backups=3 para tests."""
    return RollbackManager(max_backups=3)


# ─── Tests de create_backup ─────────────────────────────────────────


class TestCreateBackup:
    def test_creates_backup_file(self, manager: RollbackManager, tmp_mpr: Path) -> None:
        """El backup se crea en el mismo directorio que el .mpr."""
        info = manager.create_backup(tmp_mpr)

        assert info.backup_path.exists()
        assert info.backup_path.parent == tmp_mpr.parent

    def test_backup_has_correct_naming_format(
        self, manager: RollbackManager, tmp_mpr: Path
    ) -> None:
        """El nombre sigue el formato: nombre.mpr.backup.YYYYMMDDTHHmmss."""
        info = manager.create_backup(tmp_mpr)

        name = info.backup_path.name
        assert name.startswith("test_project.mpr.backup.")
        # El timestamp tiene formato YYYYMMDDTHHMMSS (15 caracteres)
        timestamp_part = name.removeprefix("test_project.mpr.backup.")
        assert len(timestamp_part) >= 15  # Puede tener sufijo _ms

    def test_backup_preserves_content(
        self, manager: RollbackManager, tmp_mpr: Path
    ) -> None:
        """El contenido del backup es idéntico al original."""
        original_content = tmp_mpr.read_bytes()
        info = manager.create_backup(tmp_mpr)

        assert info.backup_path.read_bytes() == original_content

    def test_backup_info_has_correct_fields(
        self, manager: RollbackManager, tmp_mpr: Path
    ) -> None:
        """BackupInfo contiene la metadata correcta."""
        info = manager.create_backup(tmp_mpr)

        assert info.original_path == tmp_mpr.resolve()
        assert info.backup_path.exists()
        assert len(info.timestamp) >= 15

    def test_raises_on_nonexistent_file(self, manager: RollbackManager, tmp_path: Path) -> None:
        """Lanza RollbackError si el .mpr no existe."""
        fake_mpr = tmp_path / "no_existe.mpr"

        with pytest.raises(RollbackError, match="no existe"):
            manager.create_backup(fake_mpr)

    def test_raises_on_directory(self, manager: RollbackManager, tmp_path: Path) -> None:
        """Lanza RollbackError si la ruta es un directorio."""
        with pytest.raises(RollbackError, match="no es un archivo"):
            manager.create_backup(tmp_path)

    def test_multiple_backups_have_unique_names(
        self, manager: RollbackManager, tmp_mpr: Path
    ) -> None:
        """Backups sucesivos tienen nombres distintos."""
        info1 = manager.create_backup(tmp_mpr)
        time.sleep(1.1)  # Asegurar timestamps distintos
        info2 = manager.create_backup(tmp_mpr)

        assert info1.backup_path != info2.backup_path
        assert info1.backup_path.exists()
        assert info2.backup_path.exists()


# ─── Tests de restore_backup ────────────────────────────────────────


class TestRestoreBackup:
    def test_restore_recovers_original_content(
        self, manager: RollbackManager, tmp_mpr: Path
    ) -> None:
        """Después de modificar el .mpr y restaurar, el contenido es el original."""
        original_content = tmp_mpr.read_bytes()
        info = manager.create_backup(tmp_mpr)

        # Simular que el .mpr fue modificado
        tmp_mpr.write_bytes(b"CORRUPTED_DATA_AFTER_FAILED_OPERATION")

        manager.restore_backup(info)

        assert tmp_mpr.read_bytes() == original_content

    def test_restore_when_original_deleted(
        self, manager: RollbackManager, tmp_mpr: Path
    ) -> None:
        """Restaura aunque el .mpr original haya sido eliminado."""
        original_content = tmp_mpr.read_bytes()
        info = manager.create_backup(tmp_mpr)

        # Simular que el .mpr fue eliminado
        tmp_mpr.unlink()
        assert not tmp_mpr.exists()

        manager.restore_backup(info)

        assert tmp_mpr.exists()
        assert tmp_mpr.read_bytes() == original_content

    def test_raises_on_missing_backup(self, manager: RollbackManager, tmp_mpr: Path) -> None:
        """Lanza RollbackError si el archivo de backup no existe."""
        info = BackupInfo(
            original_path=tmp_mpr,
            backup_path=tmp_mpr.parent / "no_existe.mpr.backup.20250101T000000",
            timestamp="20250101T000000",
        )

        with pytest.raises(RollbackError, match="no existe"):
            manager.restore_backup(info)

    def test_restore_from_path(
        self, manager: RollbackManager, tmp_mpr: Path
    ) -> None:
        """restore_from_path funciona sin BackupInfo previo."""
        original_content = tmp_mpr.read_bytes()
        info = manager.create_backup(tmp_mpr)

        tmp_mpr.write_bytes(b"CORRUPTED")

        manager.restore_from_path(info.backup_path, tmp_mpr)

        assert tmp_mpr.read_bytes() == original_content


# ─── Tests de list_backups ──────────────────────────────────────────


class TestListBackups:
    def test_list_empty_when_no_backups(
        self, manager: RollbackManager, tmp_mpr: Path
    ) -> None:
        """Sin backups, retorna lista vacía."""
        assert manager.list_backups(tmp_mpr) == []

    def test_list_returns_all_backups(
        self, manager: RollbackManager, tmp_mpr: Path
    ) -> None:
        """Lista todos los backups creados."""
        manager.create_backup(tmp_mpr)
        time.sleep(1.1)
        manager.create_backup(tmp_mpr)

        backups = manager.list_backups(tmp_mpr)
        assert len(backups) == 2

    def test_list_ordered_most_recent_first(
        self, manager: RollbackManager, tmp_mpr: Path
    ) -> None:
        """Los backups están ordenados con el más reciente primero."""
        info1 = manager.create_backup(tmp_mpr)
        time.sleep(1.1)
        info2 = manager.create_backup(tmp_mpr)

        backups = manager.list_backups(tmp_mpr)
        assert backups[0].timestamp >= backups[1].timestamp


# ─── Tests de cleanup_old_backups ───────────────────────────────────


class TestCleanupOldBackups:
    def test_cleanup_keeps_max_backups(self, tmp_mpr: Path) -> None:
        """Solo se mantienen los N backups más recientes."""
        manager = RollbackManager(max_backups=2)

        # Crear 4 backups (con separación de tiempo para timestamps únicos)
        for _ in range(4):
            manager.create_backup(tmp_mpr)
            time.sleep(1.1)

        backups = manager.list_backups(tmp_mpr)
        assert len(backups) == 2  # Solo los 2 más recientes

    def test_cleanup_removes_oldest(self, tmp_mpr: Path) -> None:
        """Los backups eliminados son los más antiguos."""
        manager = RollbackManager(max_backups=1)

        info_old = manager.create_backup(tmp_mpr)
        time.sleep(1.1)
        _info_new = manager.create_backup(tmp_mpr)

        # El viejo debe haber sido eliminado
        assert not info_old.backup_path.exists()


# ─── Tests de compute_mpr_hash ──────────────────────────────────────


class TestComputeMprHash:
    def test_hash_is_deterministic(self, tmp_mpr: Path) -> None:
        """El mismo archivo produce el mismo hash."""
        h1 = RollbackManager.compute_mpr_hash(tmp_mpr)
        h2 = RollbackManager.compute_mpr_hash(tmp_mpr)
        assert h1 == h2

    def test_hash_changes_with_content(self, tmp_mpr: Path) -> None:
        """Contenido diferente produce hash diferente."""
        h1 = RollbackManager.compute_mpr_hash(tmp_mpr)
        tmp_mpr.write_bytes(b"DIFFERENT_CONTENT")
        h2 = RollbackManager.compute_mpr_hash(tmp_mpr)
        assert h1 != h2

    def test_hash_is_sha256_hex(self, tmp_mpr: Path) -> None:
        """El hash tiene formato SHA-256 hexadecimal (64 caracteres)."""
        h = RollbackManager.compute_mpr_hash(tmp_mpr)
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)


# ─── Tests de atomic_mpr_operation ──────────────────────────────────


class TestAtomicMprOperation:
    def test_successful_operation_keeps_changes(self, tmp_mpr: Path) -> None:
        """Si la operación completa sin error, los cambios se mantienen."""
        with atomic_mpr_operation(tmp_mpr) as backup:
            tmp_mpr.write_bytes(b"NEW_VALID_CONTENT")
            assert backup.backup_path.exists()

        # Los cambios se mantienen
        assert tmp_mpr.read_bytes() == b"NEW_VALID_CONTENT"
        # El backup sigue existiendo (para rollback manual)
        assert backup.backup_path.exists()

    def test_failed_operation_restores_original(self, tmp_mpr: Path) -> None:
        """Si la operación lanza excepción, se restaura el .mpr original."""
        original_content = tmp_mpr.read_bytes()

        with pytest.raises(RuntimeError, match="Simulated SDK failure"):
            with atomic_mpr_operation(tmp_mpr):
                tmp_mpr.write_bytes(b"PARTIAL_CORRUPT_DATA")
                raise RuntimeError("Simulated SDK failure")

        # El contenido original se restauró
        assert tmp_mpr.read_bytes() == original_content

    def test_failed_operation_preserves_backup(self, tmp_mpr: Path) -> None:
        """Después de restaurar, el backup sigue existiendo."""
        with pytest.raises(RuntimeError):
            with atomic_mpr_operation(tmp_mpr) as backup:
                tmp_mpr.write_bytes(b"CORRUPT")
                raise RuntimeError("failure")

        assert backup.backup_path.exists()

    def test_context_yields_backup_info(self, tmp_mpr: Path) -> None:
        """El context manager yield BackupInfo correcto."""
        with atomic_mpr_operation(tmp_mpr) as backup:
            assert isinstance(backup, BackupInfo)
            assert backup.original_path == tmp_mpr.resolve()
            assert backup.backup_path.exists()

    def test_respects_max_backups(self, tmp_mpr: Path) -> None:
        """El parámetro max_backups se respeta."""
        for _ in range(4):
            with atomic_mpr_operation(tmp_mpr, max_backups=2):
                pass
            time.sleep(1.1)

        manager = RollbackManager()
        backups = manager.list_backups(tmp_mpr)
        assert len(backups) == 2

    def test_midway_crash_simulation(self, tmp_mpr: Path) -> None:
        """Simula un crash a mitad de operación multi-paso.

        Escenario: Se modifican 3 cosas. La 2da falla.
        El .mpr debe quedar en su estado original, no parcialmente modificado.
        """
        original_content = tmp_mpr.read_bytes()

        with pytest.raises(ValueError, match="SDK timeout"):
            with atomic_mpr_operation(tmp_mpr):
                # Paso 1: éxito
                tmp_mpr.write_bytes(b"STEP_1_DONE")
                # Paso 2: falla
                raise ValueError("SDK timeout on entity creation")
                # Paso 3: nunca se ejecuta

        # El .mpr tiene el contenido ORIGINAL, no "STEP_1_DONE"
        assert tmp_mpr.read_bytes() == original_content

    def test_raises_on_nonexistent_mpr(self, tmp_path: Path) -> None:
        """Lanza RollbackError si el .mpr no existe antes de iniciar."""
        fake_mpr = tmp_path / "no_existe.mpr"

        with pytest.raises(RollbackError, match="no existe"):
            with atomic_mpr_operation(fake_mpr):
                pass
