"""Сервис резервного копирования баз данных (SQLite и PostgreSQL)."""
import logging
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from app.config import BASE_DIR, settings

logger = logging.getLogger(__name__)


def _is_postgres_url(database_url: str) -> bool:
    return database_url.startswith(("postgresql://", "postgresql+psycopg2://", "postgres://"))


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


def _build_pg_env(database_url: str) -> dict[str, str]:
    env = os.environ.copy()
    parsed = urlsplit(database_url)
    if parsed.password:
        env["PGPASSWORD"] = parsed.password
    return env


def _backup_postgres_database(database_url: str) -> Path | None:
    """Создаёт SQL-дамп PostgreSQL через pg_dump."""
    backup_dir = _backup_dir()
    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.error("Не удалось создать каталог бэкапов %s: %s", backup_dir, exc)
        return None

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    backup_path = backup_dir / f"app_{timestamp}.sql"

    try:
        result = subprocess.run(
            ["pg_dump", "--clean", "--if-exists", "--file", str(backup_path), database_url],
            capture_output=True,
            text=True,
            env=_build_pg_env(database_url),
            check=False,
        )
    except FileNotFoundError as exc:
        logger.error("Команда pg_dump недоступна: %s", exc)
        return None

    if result.returncode != 0:
        logger.error("Не удалось создать резервную копию PostgreSQL: %s", result.stderr.strip() or result.stdout.strip())
        if backup_path.exists():
            backup_path.unlink(missing_ok=True)
        return None

    logger.info("Создана резервная копия PostgreSQL: %s", backup_path)
    _rotate_backups(backup_dir)
    return backup_path


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
    """Создаёт резервную копию БД и ротирует старые копии.

    Returns:
        Путь к созданной копии или None, если БД недоступна.
    """
    if _is_postgres_url(settings.DATABASE_URL):
        return _backup_postgres_database(settings.DATABASE_URL)

    db_path = _resolve_db_path(settings.DATABASE_URL)
    if db_path is None:
        logger.warning(
            "Резервное копирование не поддерживается для текущего DATABASE_URL=%s",
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


def _restore_postgres_database(backup_path: Path) -> Path:
    """Восстанавливает PostgreSQL из SQL-дампа через psql."""
    if not backup_path.exists():
        raise FileNotFoundError(f"Резервная копия не найдена: {backup_path}")

    env = _build_pg_env(settings.DATABASE_URL)
    try:
        result = subprocess.run(
            ["psql", "-d", settings.DATABASE_URL, "-f", str(backup_path)],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("Команда psql недоступна") from exc

    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Не удалось восстановить PostgreSQL")

    logger.info("База данных PostgreSQL восстановлена из %s", backup_path)
    return backup_path


def restore_database(backup_path: Path) -> Path:
    """Восстанавливает БД из указанной резервной копии.

    Args:
        backup_path: Путь к файлу резервной копии.

    Returns:
        Путь к восстановленному файлу БД.

    Raises:
        FileNotFoundError: если файл копии не существует.
        ValueError: если текущая БД не поддерживается.
    """
    if not backup_path.exists():
        raise FileNotFoundError(f"Резервная копия не найдена: {backup_path}")

    if _is_postgres_url(settings.DATABASE_URL):
        return _restore_postgres_database(backup_path)

    db_path = _resolve_db_path(settings.DATABASE_URL)
    if db_path is None:
        raise ValueError(
            f"Восстановление поддерживается только для SQLite/PostgreSQL; текущий DATABASE_URL={settings.DATABASE_URL}"
        )

    db_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(backup_path, db_path)
    logger.info("База данных восстановлена из %s в %s", backup_path, db_path)
    return db_path
