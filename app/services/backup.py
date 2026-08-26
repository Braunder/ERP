"""Сервис резервного копирования SQLite-базы данных."""
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

from app.config import BASE_DIR, settings

logger = logging.getLogger(__name__)


def _resolve_db_path(database_url: str) -> Path | None:
    """Возвращает путь к файлу SQLite из DATABASE_URL или None, если не sqlite."""
    if not database_url.startswith("sqlite"):
        return None
    prefix = "sqlite:///"
    if database_url.startswith(prefix):
        db_path = database_url[len(prefix) :]
    else:
        return None

    if db_path in (":memory:", ""):
        return None

    db_path_obj = Path(db_path)
    if not db_path_obj.is_absolute():
        db_path_obj = BASE_DIR / db_path_obj
    return db_path_obj


def _backup_dir() -> Path:
    """Возвращает абсолютный путь к каталогу резервных копий."""
    backup_dir = Path(settings.BACKUP_DIR)
    if not backup_dir.is_absolute():
        backup_dir = BASE_DIR / backup_dir
    return backup_dir


def _parse_existing_backups(backup_dir: Path) -> list[Path]:
    """Возвращает существующие файлы бэкапов, отсортированные по имени (свежее — раньше).

    Имя файла содержит UTC-метку вида app_YYYYMMDD_HHMMSS_ffffff.db, поэтому
    лексикографический порядок совпадает с хронологическим.
    """
    if not backup_dir.exists():
        return []
    backups = [p for p in backup_dir.iterdir() if p.is_file() and p.suffix == ".db"]
    backups.sort(key=lambda p: p.name, reverse=True)
    return backups


def backup_database() -> Path | None:
    """Создаёт резервную копию SQLite-БД и ротирует старые копии.

    Returns:
        Путь к созданной копии или None, если БД не SQLite / недоступна.
    """
    db_path = _resolve_db_path(settings.DATABASE_URL)
    if db_path is None:
        logger.warning(
            "Резервное копирование поддерживается только для SQLite; текущий DATABASE_URL=%s",
            settings.DATABASE_URL,
        )
        return None

    if not db_path.exists():
        logger.error("Файл базы данных не найден: %s", db_path)
        return None

    backup_dir = _backup_dir()
    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.error("Не удалось создать каталог бэкапов %s: %s", backup_dir, exc)
        return None

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    backup_name = f"app_{timestamp}.db"
    backup_path = backup_dir / backup_name

    try:
        shutil.copy2(db_path, backup_path)
    except OSError as exc:
        logger.error("Не удалось создать резервную копию %s: %s", backup_path, exc)
        return None

    logger.info("Создана резервная копия БД: %s", backup_path)

    _rotate_backups(backup_dir)

    return backup_path


def _rotate_backups(backup_dir: Path) -> None:
    """Удаляет старые резервные копии, оставляя не более BACKUP_KEEP последних."""
    keep = max(1, settings.BACKUP_KEEP)
    backups = _parse_existing_backups(backup_dir)
    for old_backup in backups[keep:]:
        try:
            old_backup.unlink()
            logger.info("Удалена старая резервная копия: %s", old_backup)
        except OSError as exc:
            logger.warning("Не удалось удалить старую копию %s: %s", old_backup, exc)


def list_backups() -> list[Path]:
    """Возвращает список резервных копий, отсортированный по времени изменения (свежее — раньше)."""
    return _parse_existing_backups(_backup_dir())


def restore_database(backup_path: Path) -> Path:
    """Восстанавливает БД из указанной резервной копии.

    Args:
        backup_path: Путь к файлу резервной копии.

    Returns:
        Путь к восстановленному файлу БД.

    Raises:
        FileNotFoundError: если файл копии не существует.
        ValueError: если текущая БД не SQLite.
    """
    if not backup_path.exists():
        raise FileNotFoundError(f"Резервная копия не найдена: {backup_path}")

    db_path = _resolve_db_path(settings.DATABASE_URL)
    if db_path is None:
        raise ValueError(
            f"Восстановление поддерживается только для SQLite; текущий DATABASE_URL={settings.DATABASE_URL}"
        )

    db_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(backup_path, db_path)
    logger.info("База данных восстановлена из %s в %s", backup_path, db_path)
    return db_path
