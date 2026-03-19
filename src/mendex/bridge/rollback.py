"""Sistema de rollback y backup atómico del .mpr.

Garantiza que el .mpr nunca quede en estado inconsistente.
Antes de cualquier modificación, se crea un backup versionado.
Si la operación falla, se restaura automáticamente.

Fase 1: Implementación completa.
"""

from __future__ import annotations

import hashlib
import shutil
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

import structlog

logger = structlog.get_logger(__name__)


class RollbackError(Exception):
    """Error durante operación de rollback."""


class BackupInfo:
    """Metadata de un backup creado."""

    def __init__(self, original_path: Path, backup_path: Path, timestamp: str) -> None:
        self.original_path = original_path
        self.backup_path = backup_path
        self.timestamp = timestamp

    def __repr__(self) -> str:
        return f"BackupInfo(backup={self.backup_path.name}, ts={self.timestamp})"


class RollbackManager:
    """Gestiona backups y restauración atómica del .mpr.

    Uso básico:
        rm = RollbackManager(max_backups=5)
        backup = rm.create_backup(Path("proyecto.mpr"))
        # ... operaciones peligrosas ...
        # Si falla:
        rm.restore_backup(backup)

    Uso con context manager:
        with atomic_mpr_operation(Path("proyecto.mpr")) as backup:
            # ... operaciones peligrosas ...
            # Si lanza excepción, se restaura automáticamente
    """

    BACKUP_SUFFIX_FORMAT = ".backup.{timestamp}"
    TIMESTAMP_FORMAT = "%Y%m%dT%H%M%S"

    def __init__(self, max_backups: int = 5) -> None:
        self.max_backups = max_backups

    def create_backup(self, mpr_path: Path) -> BackupInfo:
        """Crea un backup versionado del .mpr.

        El backup se coloca en el mismo directorio que el .mpr original,
        con formato: {nombre}.mpr.backup.{YYYYMMDDTHHmmss}

        Args:
            mpr_path: Path al archivo .mpr a respaldar.

        Returns:
            BackupInfo con metadata del backup creado.

        Raises:
            RollbackError: Si el .mpr no existe o no se puede copiar.
        """
        mpr_path = mpr_path.resolve()

        if not mpr_path.exists():
            raise RollbackError(f"El archivo .mpr no existe: {mpr_path}")

        if not mpr_path.is_file():
            raise RollbackError(f"La ruta no es un archivo: {mpr_path}")

        timestamp = datetime.now(timezone.utc).strftime(self.TIMESTAMP_FORMAT)
        backup_name = f"{mpr_path.name}.backup.{timestamp}"
        backup_path = mpr_path.parent / backup_name

        # Evitar colisión en el raro caso de dos backups en el mismo segundo
        if backup_path.exists():
            # Agregar sufijo con milisegundos
            ms = int(time.time() * 1000) % 1000
            backup_name = f"{mpr_path.name}.backup.{timestamp}_{ms:03d}"
            backup_path = mpr_path.parent / backup_name

        try:
            shutil.copy2(mpr_path, backup_path)
        except OSError as e:
            raise RollbackError(f"No se pudo crear backup: {e}") from e

        info = BackupInfo(
            original_path=mpr_path,
            backup_path=backup_path,
            timestamp=timestamp,
        )

        logger.info(
            "backup_created",
            original=str(mpr_path),
            backup=str(backup_path),
            size_bytes=backup_path.stat().st_size,
        )

        # Limpiar backups antiguos después de crear uno nuevo
        self._cleanup_old_backups(mpr_path)

        return info

    def restore_backup(self, backup_info: BackupInfo) -> None:
        """Restaura el .mpr desde un backup.

        La restauración es atómica: primero copia a un archivo temporal,
        luego reemplaza el original. Si falla el reemplazo, el temporal
        se limpia.

        Args:
            backup_info: Info del backup a restaurar.

        Raises:
            RollbackError: Si el backup no existe o la restauración falla.
        """
        if not backup_info.backup_path.exists():
            raise RollbackError(
                f"El archivo de backup no existe: {backup_info.backup_path}"
            )

        original = backup_info.original_path
        temp_path = original.parent / f"{original.name}.restoring"

        try:
            # Paso 1: Copiar backup a archivo temporal
            shutil.copy2(backup_info.backup_path, temp_path)

            # Paso 2: Reemplazar el original con el temporal (atómico en la mayoría de OS)
            temp_path.replace(original)

            logger.info(
                "backup_restored",
                original=str(original),
                from_backup=str(backup_info.backup_path),
            )

        except OSError as e:
            # Limpiar archivo temporal si existe
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
            raise RollbackError(f"No se pudo restaurar el backup: {e}") from e

    def restore_from_path(self, backup_path: Path, original_path: Path) -> None:
        """Restaura el .mpr desde un path de backup directo.

        Convenience method cuando no se tiene el BackupInfo.

        Args:
            backup_path: Path al archivo de backup.
            original_path: Path donde restaurar.
        """
        info = BackupInfo(
            original_path=original_path.resolve(),
            backup_path=backup_path.resolve(),
            timestamp="",
        )
        self.restore_backup(info)

    def list_backups(self, mpr_path: Path) -> list[BackupInfo]:
        """Lista todos los backups existentes para un .mpr.

        Args:
            mpr_path: Path al archivo .mpr original.

        Returns:
            Lista de BackupInfo ordenada por timestamp (más reciente primero).
        """
        mpr_path = mpr_path.resolve()
        backup_dir = mpr_path.parent
        pattern = f"{mpr_path.name}.backup.*"

        backups: list[BackupInfo] = []
        for path in backup_dir.glob(pattern):
            # Extraer timestamp del nombre
            # Formato: nombre.mpr.backup.YYYYMMDDTHHmmss[_ms]
            suffix = path.name.removeprefix(f"{mpr_path.name}.backup.")
            timestamp = suffix.split("_")[0] if "_" in suffix else suffix
            backups.append(
                BackupInfo(
                    original_path=mpr_path,
                    backup_path=path,
                    timestamp=timestamp,
                )
            )

        # Ordenar por timestamp descendente (más reciente primero)
        backups.sort(key=lambda b: b.timestamp, reverse=True)
        return backups

    def _cleanup_old_backups(self, mpr_path: Path) -> int:
        """Elimina backups antiguos, manteniendo solo los N más recientes.

        Args:
            mpr_path: Path al .mpr original.

        Returns:
            Número de backups eliminados.
        """
        backups = self.list_backups(mpr_path)
        removed = 0

        if len(backups) > self.max_backups:
            for old_backup in backups[self.max_backups :]:
                try:
                    old_backup.backup_path.unlink()
                    removed += 1
                    logger.debug(
                        "old_backup_removed",
                        path=str(old_backup.backup_path),
                    )
                except OSError as e:
                    logger.warning(
                        "old_backup_remove_failed",
                        path=str(old_backup.backup_path),
                        error=str(e),
                    )

        return removed

    @staticmethod
    def compute_mpr_hash(mpr_path: Path) -> str:
        """Calcula hash SHA-256 del .mpr.

        Útil para detectar si el proyecto cambió desde la última extracción
        de convenciones.

        Args:
            mpr_path: Path al archivo .mpr.

        Returns:
            Hash SHA-256 como string hexadecimal.
        """
        sha256 = hashlib.sha256()
        with open(mpr_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()


@contextmanager
def atomic_mpr_operation(
    mpr_path: Path,
    max_backups: int = 5,
) -> Generator[BackupInfo, None, None]:
    """Context manager para operaciones atómicas sobre el .mpr.

    Crea un backup antes de la operación. Si la operación lanza cualquier
    excepción, restaura automáticamente el backup. Si la operación completa
    sin errores, el backup se mantiene (para rollback manual si es necesario).

    Uso:
        with atomic_mpr_operation(Path("proyecto.mpr")) as backup:
            # ... modificar el .mpr via Model SDK ...
            # Si lanza excepción → se restaura automáticamente

    Args:
        mpr_path: Path al archivo .mpr.
        max_backups: Número máximo de backups a mantener.

    Yields:
        BackupInfo del backup creado.

    Raises:
        RollbackError: Si no se puede crear o restaurar el backup.
        Exception: Re-lanza la excepción original después de restaurar.
    """
    manager = RollbackManager(max_backups=max_backups)
    backup_info = manager.create_backup(mpr_path)

    try:
        yield backup_info
    except Exception as exc:
        logger.error(
            "operation_failed_restoring_backup",
            error=str(exc),
            error_type=type(exc).__name__,
            backup=str(backup_info.backup_path),
        )

        try:
            manager.restore_backup(backup_info)
            logger.info(
                "auto_restore_success",
                original=str(mpr_path),
            )
        except RollbackError as restore_err:
            logger.critical(
                "auto_restore_failed",
                original_error=str(exc),
                restore_error=str(restore_err),
                backup_path=str(backup_info.backup_path),
                manual_restore_hint=(
                    f"Restaurar manualmente: copy {backup_info.backup_path} → {mpr_path}"
                ),
            )
            raise RollbackError(
                f"CRITICAL: La operación falló Y la restauración también falló. "
                f"Error original: {exc}. Error de restauración: {restore_err}. "
                f"Backup disponible en: {backup_info.backup_path}"
            ) from exc

        # Re-lanzar la excepción original después de restaurar exitosamente
        raise
