"""Роутер ручной синхронизации с Google Sheets."""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from starlette.templating import Jinja2Templates

from app.config import settings
from app.deps import get_db, require_auth
from app.models import SyncLog
from app.schemas import SyncLogRead
from app.services.sheets import log_sync_attempt, sync_operations_to_sheets

router = APIRouter(tags=["sync"], dependencies=[Depends(require_auth)])
templates = Jinja2Templates(directory="app/templates")


def _last_logs(db: Session, limit: int = 20):
    return (
        db.query(SyncLog)
        .order_by(SyncLog.created_at.desc())
        .limit(limit)
        .all()
    )


@router.get("/sync")
async def sync_page(request: Request, db: Session = Depends(get_db)):
    logs = _last_logs(db)
    return templates.TemplateResponse(
        request,
        "sync/sync.html",
        {
            "logs": logs,
            "spreadsheet_configured": bool(settings.GOOGLE_SPREADSHEET_ID),
            "schedule": settings.SYNC_SCHEDULE,
        },
    )


@router.post("/sync/now")
async def sync_now(db: Session = Depends(get_db)):
    try:
        result = sync_operations_to_sheets(db)
        log_sync_attempt(
            db,
            success=True,
            message="Синхронизация отчёта P&L с Google Таблицей завершена успешно",
            details=result,
            records_count=result.get("synced"),
        )
        return {
            "success": True,
            "synced": result["synced"],
            "message": f"Синхронизировано {result['synced']} операций",
        }
    except ValueError as exc:
        message = str(exc)
        log_sync_attempt(
            db,
            success=False,
            message=message,
            details={"error": message},
        )
        return {"success": False, "error": message}
    except Exception as exc:  # noqa: BLE001
        message = str(exc)
        log_sync_attempt(
            db,
            success=False,
            message=message,
            details={"error": message},
        )
        return {"success": False, "error": message}


@router.get("/api/sync/logs", response_model=list[SyncLogRead])
async def api_sync_logs(db: Session = Depends(get_db)):
    return _last_logs(db)
