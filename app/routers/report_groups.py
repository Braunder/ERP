"""Группы отчёта P&L: HTML-CRUD и JSON API."""
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from starlette.templating import Jinja2Templates

from app.services.report import SECTION_LABELS

from app.deps import get_db, require_auth
from app.models import Category, ChangeLog, ReportGroup
from app.schemas import ReportGroupCreate, ReportGroupRead

router = APIRouter(tags=["report-groups"], dependencies=[Depends(require_auth)])
templates = Jinja2Templates(directory="app/templates")



def _group_identity(name: str, section: str) -> tuple[str, str]:
    return (name.strip(), section.strip())


def _unique_report_groups(groups: list[ReportGroup]) -> list[ReportGroup]:
    seen: set[tuple[str, str]] = set()
    unique: list[ReportGroup] = []
    for group in groups:
        identity = _group_identity(group.name, group.section)
        if identity in seen:
            continue
        seen.add(identity)
        unique.append(group)
    return unique


def _log_change(
    db: Session,
    entity: str,
    entity_id: int,
    action: str,
    changes: dict | None = None,
) -> None:
    db.add(
        ChangeLog(
            entity=entity,
            entity_id=entity_id,
            action=action,
            changes=changes,
        )
    )


@router.get("/report-groups")
async def report_groups_page(request: Request, db: Session = Depends(get_db)):
    groups = db.query(ReportGroup).order_by(ReportGroup.sort_order, ReportGroup.id).all()
    counts: dict[int, int] = {}
    for group in groups:
        counts[group.id] = (
            db.query(Category).filter(Category.report_group_id == group.id).count()
        )
    return templates.TemplateResponse(
        request,
        "report_groups/list.html",
        {
            "groups": groups,
            "category_counts": counts,
            "section_labels": SECTION_LABELS,
        },
    )


@router.post("/report-groups")
async def report_group_create(
    request: Request,
    db: Session = Depends(get_db),
    name: str = Form(...),
    section: str = Form("direct"),
    sort_order: int = Form(100),
):
    normalized_name = name.strip()
    normalized_section = section.strip()
    existing = (
        db.query(ReportGroup)
        .filter(ReportGroup.name == normalized_name, ReportGroup.section == normalized_section)
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Группа «{normalized_name}» для секции «{SECTION_LABELS.get(normalized_section, normalized_section)}» уже существует.",
        )

    group = ReportGroup(name=normalized_name, section=normalized_section, sort_order=sort_order)
    db.add(group)
    db.flush()
    _log_change(db, "report_group", group.id, "create")
    db.commit()
    return RedirectResponse(url="/report-groups", status_code=302)


@router.post("/report-groups/{group_id}")
async def report_group_update(
    request: Request,
    group_id: int,
    db: Session = Depends(get_db),
    name: str = Form(...),
    section: str = Form("direct"),
    sort_order: int = Form(100),
    is_active: bool = Form(True),
):
    group = db.query(ReportGroup).filter(ReportGroup.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Группа не найдена")

    normalized_name = name.strip()
    normalized_section = section.strip()
    duplicate = (
        db.query(ReportGroup)
        .filter(
            ReportGroup.id != group_id,
            ReportGroup.name == normalized_name,
            ReportGroup.section == normalized_section,
        )
        .first()
    )
    if duplicate:
        raise HTTPException(
            status_code=400,
            detail=f"Группа «{normalized_name}» для секции «{SECTION_LABELS.get(normalized_section, normalized_section)}» уже существует.",
        )

    columns = [c.name for c in ReportGroup.__table__.columns]
    old_values = {c: getattr(group, c) for c in columns}

    group.name = normalized_name
    group.section = normalized_section
    group.sort_order = sort_order
    group.is_active = is_active

    db.flush()
    new_values = {c: getattr(group, c) for c in columns}
    changes = {
        k: {"old": old_values[k], "new": new_values[k]}
        for k in old_values
        if old_values[k] != new_values[k]
    }
    _log_change(db, "report_group", group.id, "update", changes)
    db.commit()
    return RedirectResponse(url="/report-groups", status_code=302)


@router.post("/report-groups/{group_id}/delete")
async def report_group_delete(group_id: int, db: Session = Depends(get_db)):
    group = db.query(ReportGroup).filter(ReportGroup.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Группа не найдена")

    linked = db.query(Category).filter(Category.report_group_id == group_id).count()
    if linked:
        raise HTTPException(
            status_code=400,
            detail=f"Нельзя удалить группу «{group.name}»: к ней привязано {linked} категорий. Сначала отвяжите категории.",
        )

    db.delete(group)
    _log_change(db, "report_group", group_id, "delete")
    db.commit()
    return RedirectResponse(url="/report-groups", status_code=302)


@router.get("/api/report-groups", response_model=list[ReportGroupRead])
async def api_report_groups_list(db: Session = Depends(get_db)):
    groups = db.query(ReportGroup).order_by(ReportGroup.sort_order, ReportGroup.id).all()
    return _unique_report_groups(groups)


@router.post("/api/report-groups", response_model=ReportGroupRead)
async def api_report_groups_create(data: ReportGroupCreate, db: Session = Depends(get_db)):
    group = ReportGroup(**data.model_dump())
    db.add(group)
    db.flush()
    _log_change(db, "report_group", group.id, "create")
    db.commit()
    db.refresh(group)
    return group


@router.post("/api/report-groups/{group_id}", response_model=ReportGroupRead)
async def api_report_groups_update(
    group_id: int,
    data: ReportGroupCreate,
    db: Session = Depends(get_db),
):
    group = db.query(ReportGroup).filter(ReportGroup.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Группа не найдена")

    columns = [c.name for c in ReportGroup.__table__.columns]
    old_values = {c: getattr(group, c) for c in columns}

    for key, value in data.model_dump().items():
        setattr(group, key, value)

    db.flush()
    new_values = {c: getattr(group, c) for c in columns}
    changes = {
        k: {"old": old_values[k], "new": new_values[k]}
        for k in old_values
        if old_values[k] != new_values[k]
    }
    _log_change(db, "report_group", group.id, "update", changes)
    db.commit()
    db.refresh(group)
    return group
