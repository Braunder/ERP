"""Категории доходов/расходов: HTML-CRUD и JSON API."""
from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from starlette.templating import Jinja2Templates

from app.deps import get_db, require_auth
from app.models import Category, ChangeLog, ReportGroup
from app.schemas import CategoryCreate, CategoryRead
from app.services.report import report_group_label, report_group_option_label

router = APIRouter(tags=["categories"], dependencies=[Depends(require_auth)])
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["report_group_label"] = report_group_label
templates.env.globals["report_group_option_label"] = report_group_option_label


def _report_groups(db: Session) -> list[ReportGroup]:
    groups = db.query(ReportGroup).order_by(ReportGroup.sort_order, ReportGroup.id).all()
    seen: set[tuple[str, str]] = set()
    unique: list[ReportGroup] = []
    for group in groups:
        key = (group.name.strip().lower(), group.section.strip().lower())
        if key in seen:
            continue
        seen.add(key)
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


def _build_category_tree(categories: list[Category]) -> list[Category]:
    by_id = {c.id: c for c in categories}
    roots: list[Category] = []
    for category in categories:
        if category.parent_id and category.parent_id in by_id:
            by_id[category.parent_id].children.append(category)
        else:
            roots.append(category)
    return roots


def _category_to_dict(category: Category) -> dict:
    group_name = category.report_group_ref.name if category.report_group_ref else None
    return {
        "id": category.id,
        "name": category.name,
        "kind": category.kind,
        "parent_id": category.parent_id,
        "requires_payment_method": category.requires_payment_method,
        "requires_guests": category.requires_guests,
        "requires_supplier": category.requires_supplier,
        "requires_products": category.requires_products,
        "requires_employee": category.requires_employee,
        "requires_responsible": category.requires_responsible,
        "is_active": category.is_active,
        "report_group_id": category.report_group_id,
        "report_group_name": group_name,
        "children": [],
    }


def _build_category_tree_dict(categories: list[Category]) -> list[dict]:
    by_id = {c.id: _category_to_dict(c) for c in categories}
    roots: list[dict] = []
    for category in categories:
        node = by_id[category.id]
        if category.parent_id and category.parent_id in by_id:
            by_id[category.parent_id]["children"].append(node)
        else:
            roots.append(node)
    return roots


@router.get("/categories")
async def categories_list(request: Request, db: Session = Depends(get_db)):
    all_categories = (
        db.query(Category).order_by(Category.kind, Category.name).all()
    )
    tree = _build_category_tree(all_categories)
    return templates.TemplateResponse(
        request,
        "categories/list.html",
        {
            "categories": tree,
            "all_categories": all_categories,
            "report_groups": _report_groups(db),
        },
    )


@router.post("/categories")
async def category_create(
    request: Request,
    db: Session = Depends(get_db),
    name: str = Form(...),
    kind: str = Form(...),
    parent_id: int | None = Form(None),
    requires_payment_method: bool = Form(False),
    requires_guests: bool = Form(False),
    requires_supplier: bool = Form(False),
    requires_products: bool = Form(False),
    requires_employee: bool = Form(False),
    requires_responsible: bool = Form(False),
    report_group_id: int | None = Form(None),
):
    category = Category(
        name=name,
        kind=kind,
        parent_id=parent_id,
        requires_payment_method=requires_payment_method,
        requires_guests=requires_guests,
        requires_supplier=requires_supplier,
        requires_products=requires_products,
        requires_employee=requires_employee,
        requires_responsible=requires_responsible,
        report_group_id=report_group_id or None,
    )
    db.add(category)
    db.flush()
    _log_change(db, "category", category.id, "create")
    db.commit()
    return RedirectResponse(url="/categories", status_code=302)


@router.post("/categories/{category_id}")
async def category_update(
    request: Request,
    category_id: int,
    db: Session = Depends(get_db),
    name: str = Form(...),
    kind: str = Form(...),
    parent_id: int | None = Form(None),
    requires_payment_method: bool = Form(False),
    requires_guests: bool = Form(False),
    requires_supplier: bool = Form(False),
    requires_products: bool = Form(False),
    requires_employee: bool = Form(False),
    requires_responsible: bool = Form(False),
    is_active: bool = Form(True),
    report_group_id: int | None = Form(None),
):
    category = db.query(Category).filter(Category.id == category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Категория не найдена")

    columns = [c.name for c in Category.__table__.columns]
    old_values = {c: getattr(category, c) for c in columns}

    category.name = name
    category.kind = kind
    category.parent_id = parent_id
    category.requires_payment_method = requires_payment_method
    category.requires_guests = requires_guests
    category.requires_supplier = requires_supplier
    category.requires_products = requires_products
    category.requires_employee = requires_employee
    category.requires_responsible = requires_responsible
    category.is_active = is_active
    category.report_group_id = report_group_id or None

    db.flush()
    new_values = {c: getattr(category, c) for c in columns}
    changes = {
        k: {"old": old_values[k], "new": new_values[k]}
        for k in old_values
        if old_values[k] != new_values[k]
    }
    _log_change(db, "category", category.id, "update", changes)
    db.commit()
    return RedirectResponse(url="/categories", status_code=302)


@router.post("/categories/{category_id}/delete")
async def category_delete(category_id: int, db: Session = Depends(get_db)):
    category = db.query(Category).filter(Category.id == category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Категория не найдена")
    db.delete(category)
    _log_change(db, "category", category.id, "delete")
    db.commit()
    return RedirectResponse(url="/categories", status_code=302)


@router.get("/api/categories", response_model=list[CategoryRead])
async def api_categories_list(
    db: Session = Depends(get_db),
    kind: str | None = Query(None),
    tree: int | None = Query(None),
):
    query = db.query(Category).order_by(Category.kind, Category.name)
    if kind:
        query = query.filter(Category.kind == kind)
    categories = query.all()
    if tree:
        return _build_category_tree_dict(categories)
    return categories


@router.post("/api/categories", response_model=CategoryRead)
async def api_categories_create(data: CategoryCreate, db: Session = Depends(get_db)):
    category = Category(**data.model_dump())
    db.add(category)
    db.flush()
    _log_change(db, "category", category.id, "create")
    db.commit()
    db.refresh(category)
    return category


@router.get("/api/categories/by-group/{group_id}")
async def api_categories_by_group(group_id: int, db: Session = Depends(get_db)):
    categories = (
        db.query(Category)
        .filter(Category.report_group_id == group_id)
        .order_by(Category.kind, Category.name)
        .all()
    )
    return _build_category_tree_dict(categories)
