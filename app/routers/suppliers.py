"""Поставщики: HTML-CRUD и JSON API."""
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from starlette.templating import Jinja2Templates

from app.deps import get_db, require_auth
from app.models import ChangeLog, Supplier
from app.schemas import SupplierCreate, SupplierRead

router = APIRouter(tags=["suppliers"], dependencies=[Depends(require_auth)])
templates = Jinja2Templates(directory="app/templates")


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


@router.get("/suppliers")
async def suppliers_list(request: Request, db: Session = Depends(get_db)):
    suppliers = db.query(Supplier).order_by(Supplier.name).all()
    return templates.TemplateResponse(
        request,
        "suppliers/list.html",
        {"suppliers": suppliers},
    )


@router.post("/suppliers")
async def supplier_create(
    request: Request,
    db: Session = Depends(get_db),
    name: str = Form(...),
    contact: str | None = Form(None),
):
    supplier = Supplier(name=name, contact=contact)
    db.add(supplier)
    db.flush()
    _log_change(db, "supplier", supplier.id, "create")
    db.commit()
    return RedirectResponse(url="/suppliers", status_code=302)


@router.post("/suppliers/{supplier_id}")
async def supplier_update(
    request: Request,
    supplier_id: int,
    db: Session = Depends(get_db),
    name: str = Form(...),
    contact: str | None = Form(None),
    is_active: bool = Form(True),
):
    supplier = db.query(Supplier).filter(Supplier.id == supplier_id).first()
    if not supplier:
        raise HTTPException(status_code=404, detail="Поставщик не найден")

    columns = [c.name for c in Supplier.__table__.columns]
    old_values = {c: getattr(supplier, c) for c in columns}

    supplier.name = name
    supplier.contact = contact
    supplier.is_active = is_active

    db.flush()
    new_values = {c: getattr(supplier, c) for c in columns}
    changes = {
        k: {"old": old_values[k], "new": new_values[k]}
        for k in old_values
        if old_values[k] != new_values[k]
    }
    _log_change(db, "supplier", supplier.id, "update", changes)
    db.commit()
    return RedirectResponse(url="/suppliers", status_code=302)


@router.post("/suppliers/{supplier_id}/delete")
async def supplier_delete(supplier_id: int, db: Session = Depends(get_db)):
    supplier = db.query(Supplier).filter(Supplier.id == supplier_id).first()
    if not supplier:
        raise HTTPException(status_code=404, detail="Поставщик не найден")
    db.delete(supplier)
    _log_change(db, "supplier", supplier.id, "delete")
    db.commit()
    return RedirectResponse(url="/suppliers", status_code=302)


@router.get("/api/suppliers", response_model=list[SupplierRead])
async def api_suppliers_list(db: Session = Depends(get_db)):
    return db.query(Supplier).order_by(Supplier.name).all()


@router.post("/api/suppliers", response_model=SupplierRead)
async def api_suppliers_create(data: SupplierCreate, db: Session = Depends(get_db)):
    supplier = Supplier(**data.model_dump())
    db.add(supplier)
    db.flush()
    _log_change(db, "supplier", supplier.id, "create")
    db.commit()
    db.refresh(supplier)
    return supplier
