"""Фоновый планировщик синхронизации с Google Sheets."""
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import settings
from app.database import SessionLocal
from app.services.backup import backup_database
from app.services.sheets import log_sync_attempt, sync_operations_to_sheets

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


def sync_job() -> None:
    """Задача планировщика: синхронизация операций с Google Sheets."""
    db = SessionLocal()
    try:
        result = sync_operations_to_sheets(db)
        log_sync_attempt(
            db,
            success=True,
            message="Автоматическая синхронизация завершена успешно",
            details=result,
            records_count=result.get("synced"),
        )
        logger.info("Автосинхронизация завершена: %s записей", result.get("synced"))
    except Exception as exc:  # noqa: BLE001
        message = str(exc)
        logger.exception("Автосинхронизация не удалась: %s", message)
        try:
            log_sync_attempt(
                db,
                success=False,
                message=message,
                details={"error": message},
            )
        except Exception as log_exc:  # noqa: BLE001
            logger.error("Не удалось записать лог синхронизации: %s", log_exc)
    finally:
        db.close()


def backup_job() -> None:
    """Задача планировщика: резервное копирование БД."""
    try:
        backup_path = backup_database()
        if backup_path:
            logger.info("Автобэкап завершён: %s", backup_path)
        else:
            logger.warning("Автобэкап не создан (см. логи выше)")
    except Exception as exc:  # noqa: BLE001
        logger.exception("Автобэкап завершился ошибкой: %s", exc)


def setup_scheduler() -> None:
    """Настраивает периодические задачи синхронизации и резервного копирования."""
    jobs_added = []

    if settings.SYNC_ENABLED and settings.GOOGLE_SPREADSHEET_ID:
        scheduler.add_job(
            sync_job,
            CronTrigger.from_crontab(settings.SYNC_SCHEDULE),
            id="sheets_sync",
            replace_existing=True,
        )
        jobs_added.append(f"синхронизация ({settings.SYNC_SCHEDULE})")
    else:
        logger.info(
            "Автосинхронизация отключена (SYNC_ENABLED=%s, GOOGLE_SPREADSHEET_ID=%s)",
            settings.SYNC_ENABLED,
            "настроен" if settings.GOOGLE_SPREADSHEET_ID else "не настроен",
        )

    scheduler.add_job(
        backup_job,
        CronTrigger.from_crontab(settings.BACKUP_SCHEDULE),
        id="database_backup",
        replace_existing=True,
    )
    jobs_added.append(f"бэкап ({settings.BACKUP_SCHEDULE})")

    scheduler.start()
    logger.info("Планировщик запущен: %s", ", ".join(jobs_added))


def shutdown_scheduler() -> None:
    """Останавливает планировщик."""
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Планировщик остановлен")
