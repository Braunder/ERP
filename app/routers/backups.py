"""Роутер управления резервными копиями БД."""
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from starlette.templating import Jinja2Templates

from app.config import settings
from app.deps import get_db, require_auth
from app.services.backup import backup_database, list_backups, restore_database

router = APIRouter(tags=["backups"], dependencies=[Depends(require_auth)])
templates = Jinja2Templates(directory="app/templates")


def _backup_dir() -> Path:
    backup_dir = Path(settings.BACKUP_DIR)
    if not backup_dir.is_absolute():
        from app.config import BASE_DIR

        backup_dir = BASE_DIR / backup_dir
    return backup_dir


def _backup_to_dict(backup: Path) -> dict:
    stat = backup.stat()
    return {
        "filename": backup.name,
        "created_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        "size_bytes": stat.st_size,
    }


@router.get("/backups")
async def backups_page(request: Request, restored: int | None = None):
    backups = [_backup_to_dict(b) for b in list_backups()]
    return templates.TemplateResponse(
        request,
        "backups/backups.html",
        {
            "backups": backups,
            "restored": bool(restored),
        },
    )


@router.post("/backups/create")
async def backups_create():
    backup_database()
    return RedirectResponse(url="/backups", status_code=302)


@router.post("/backups/restore/{filename}")
async def backups_restore(filename: str):
    backup_path = _backup_dir() / filename
    try:
        restore_database(backup_path)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(url="/backups?restored=1", status_code=302)


@router.get("/api/backups")
async def api_backups_list():
    return [_backup_to_dict(b) for b in list_backups()]
