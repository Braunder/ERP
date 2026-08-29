"""Роутер ручной синхронизации с Google Sheets."""
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from starlette.templating import Jinja2Templates

from app.config import settings
from app import database
from app.deps import get_db, require_auth
from app.models import SyncLog
from app.schemas import SyncLogRead
from app.services.sheets import log_sync_attempt, sync_operations_to_sheets

router = APIRouter(tags=["sync"], dependencies=[Depends(require_auth)])
templates = Jinja2Templates(directory="app/templates")
sync_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sheets-sync")
sync_state_lock = Lock()
sync_state: dict[str, dict] = {}


def _run_manual_sync(job_id: str) -> None:
    db = database.SessionLocal()
    try:
        with sync_state_lock:
            sync_state[job_id] = {"status": "running"}

        result = sync_operations_to_sheets(db)
        log_sync_attempt(
            db,
            success=True,
            message="Синхронизация отчёта P&L с Google Таблицей завершена успешно",
            details=result,
            records_count=result.get("synced"),
        )
        state = {
            "status": "success",
            "synced": result["synced"],
            "message": f"Синхронизировано {result['synced']} операций",
        }
    except Exception as exc:  # noqa: BLE001
        message = str(exc)
        try:
            log_sync_attempt(db, success=False, message=message, details={"error": message})
        except Exception:  # noqa: BLE001
            pass
        state = {"status": "error", "error": message}
    finally:
        db.close()
        with sync_state_lock:
            sync_state[job_id] = state


def _active_job_id() -> str | None:
    with sync_state_lock:
        for job_id, state in reversed(list(sync_state.items())):
            if state["status"] in {"queued", "running"}:
                return job_id
    return None


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
    if not settings.GOOGLE_SPREADSHEET_ID:
        message = "GOOGLE_SPREADSHEET_ID не настроен"
        log_sync_attempt(db, success=False, message=message, details={"error": message})
        return {"success": False, "error": message}

    active_job_id = _active_job_id()
    if active_job_id:
        return JSONResponse(
            status_code=409,
            content={"success": False, "error": "Синхронизация уже выполняется", "job_id": active_job_id},
        )

    job_id = uuid4().hex
    with sync_state_lock:
        sync_state[job_id] = {"status": "queued"}
    sync_executor.submit(_run_manual_sync, job_id)
    return JSONResponse(
        status_code=202,
        content={"success": True, "status": "queued", "job_id": job_id},
    )


@router.get("/api/sync/status/{job_id}")
async def api_sync_status(job_id: str):
    with sync_state_lock:
        state = sync_state.get(job_id)
    if state is None:
        return JSONResponse(status_code=404, content={"error": "Задача синхронизации не найдена"})
    return {"success": state["status"] == "success", **state, "job_id": job_id}


@router.get("/api/sync/logs", response_model=list[SyncLogRead])
async def api_sync_logs(db: Session = Depends(get_db)):
    return _last_logs(db)
