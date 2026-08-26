"""Операции доходов/расходов: HTML-CRUD и JSON API."""
import re
from collections import defaultdict
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session, joinedload
from starlette.templating import Jinja2Templates

from app.deps import get_db, require_auth
from app.models import Category, ChangeLog, Employee, Operation, OperationItem, Supplier
from app.schemas import OperationCreate, OperationRead


PAYMENT_METHOD_LABELS = {
    "cash": "Нал",
    "card": "Б/нал",
    "transfer": "Перевод",
}


ITEM_FIELD_RE = re.compile(r"items\[(\d+)\]\[(\w+)\]")

router = APIRouter(tags=["operations"], dependencies=[Depends(require_auth)])
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


def _parse_items_from_form(form) -> list[OperationItem]:
    """Разбирает динамические поля items[i][field] из form-data."""
    raw: dict[int, dict[str, str]] = defaultdict(dict)
    for key, value in form.multi_items():
        match = ITEM_FIELD_RE.match(key)
        if match:
            idx = int(match.group(1))
            field = match.group(2)
            raw[idx][field] = value

    items: list[OperationItem] = []
    for idx in sorted(raw.keys()):
        data = raw[idx]
        name = (data.get("name") or "").strip()
        if not name:
            continue
        product_id = data.get("product_id")
        items.append(
            OperationItem(
                product_id=int(product_id) if product_id else None,
                name=name,
                price=Decimal(data.get("price") or "0"),
                quantity=Decimal(data.get("quantity") or "1"),
                unit=data.get("unit") or "шт",
            )
        )
    return items


def _validate_operation_form(
    category: Category,
    kind: str,
    guests_count: int | None,
    payment_method: str | None,
    supplier_id: int | None,
    employee_id: int | None,
    responsible: str | None,
    items: list[OperationItem],
) -> None:
    if kind not in ("income", "expense"):
        raise HTTPException(status_code=400, detail="Неверный тип операции")

    if category.requires_guests and (not guests_count or guests_count <= 0):
        raise HTTPException(status_code=400, detail="Количество гостей обязательно и должно быть больше 0")

    if category.requires_payment_method and kind == "income" and not payment_method:
        raise HTTPException(status_code=400, detail="Способ оплаты обязателен")

    if category.requires_supplier and not supplier_id:
        raise HTTPException(status_code=400, detail="Поставщик обязателен")

    if category.requires_employee and not employee_id:
        raise HTTPException(status_code=400, detail="Сотрудник обязателен")

    if category.requires_responsible and not responsible:
        raise HTTPException(status_code=400, detail="Ответственный обязателен")

    if category.requires_products and not items:
        raise HTTPException(status_code=400, detail="Добавьте хотя бы одну строку продукта")


@router.get("/operations")
async def operations_list(
    request: Request,
    db: Session = Depends(get_db),
    kind: str | None = Query(None),
    category_id: int | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
):
    query = db.query(Operation).options(
        joinedload(Operation.category).joinedload(Category.parent)
    )
    if kind:
        query = query.filter(Operation.kind == kind)
    if category_id:
        query = query.filter(Operation.category_id == category_id)
    if date_from:
        query = query.filter(Operation.date >= date_from)
    if date_to:
        query = query.filter(Operation.date <= date_to)

    operations = query.order_by(Operation.date.desc(), Operation.id.desc()).all()
    categories = db.query(Category).order_by(Category.kind, Category.name).all()
    return templates.TemplateResponse(
        request,
        "operations/list.html",
        {
            "operations": operations,
            "categories": categories,
            "kind": kind,
            "category_id": category_id,
            "date_from": date_from,
            "date_to": date_to,
            "payment_labels": PAYMENT_METHOD_LABELS,
        },
    )


@router.get("/operations/new")
async def operation_new(request: Request, db: Session = Depends(get_db)):
    categories = (
        db.query(Category)
        .filter(Category.is_active == True)
        .order_by(Category.kind, Category.name)
        .all()
    )
    employees = (
        db.query(Employee)
        .filter(Employee.is_active == True)
        .order_by(Employee.name)
        .all()
    )
    suppliers = (
        db.query(Supplier)
        .filter(Supplier.is_active == True)
        .order_by(Supplier.name)
        .all()
    )
    return templates.TemplateResponse(
        request,
        "operations/form.html",
        {
            "operation": None,
            "categories": categories,
            "employees": employees,
            "suppliers": suppliers,
            "payment_labels": PAYMENT_METHOD_LABELS,
            "today": date.today().isoformat(),
        },
    )


@router.get("/operations/{operation_id}/edit")
async def operation_edit(
    request: Request,
    operation_id: int,
    db: Session = Depends(get_db),
):
    operation = (
        db.query(Operation)
        .options(joinedload(Operation.items).joinedload(OperationItem.product))
        .filter(Operation.id == operation_id)
        .first()
    )
    if not operation:
        raise HTTPException(status_code=404, detail="Операция не найдена")
    categories = (
        db.query(Category)
        .filter(Category.is_active == True)
        .order_by(Category.kind, Category.name)
        .all()
    )
    employees = (
        db.query(Employee)
        .filter(Employee.is_active == True)
        .order_by(Employee.name)
        .all()
    )
    suppliers = (
        db.query(Supplier)
        .filter(Supplier.is_active == True)
        .order_by(Supplier.name)
        .all()
    )
    return templates.TemplateResponse(
        request,
        "operations/form.html",
        {
            "operation": operation,
            "categories": categories,
            "employees": employees,
            "suppliers": suppliers,
            "payment_labels": PAYMENT_METHOD_LABELS,
            "today": date.today().isoformat(),
        },
    )


@router.post("/operations")
async def operation_create(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    data = {k: v for k, v in form.multi_items()}

    kind = data.get("kind")
    category_id = int(data.get("category_id") or 0)
    category = db.query(Category).filter(Category.id == category_id).first()
    if not category:
        raise HTTPException(status_code=400, detail="Категория не найдена")

    guests_count = int(data["guests_count"]) if data.get("guests_count") else None
    payment_method = data.get("payment_method") or None
    supplier_id = int(data["supplier_id"]) if data.get("supplier_id") else None
    employee_id = int(data["employee_id"]) if data.get("employee_id") else None
    responsible = data.get("responsible") or None

    items = _parse_items_from_form(form)
    _validate_operation_form(
        category=category,
        kind=kind,
        guests_count=guests_count,
        payment_method=payment_method,
        supplier_id=supplier_id,
        employee_id=employee_id,
        responsible=responsible,
        items=items,
    )

    amount = Decimal(data.get("amount") or "0")
    if kind == "expense" and category.requires_products and items:
        calculated = sum(item.price * item.quantity for item in items)
        if amount == 0:
            amount = calculated

    operation = Operation(
        date=date.fromisoformat(data["date"]),
        kind=kind,
        category_id=category_id,
        amount=amount,
        comment=data.get("comment") or None,
        guests_count=guests_count,
        payment_method=payment_method,
        supplier_id=supplier_id,
        employee_id=employee_id,
        responsible=responsible,
    )
    db.add(operation)
    db.flush()

    for item in items:
        item.operation_id = operation.id
        db.add(item)

    _log_change(db, "operation", operation.id, "create")
    db.commit()
    return RedirectResponse(url="/operations", status_code=302)


@router.post("/operations/{operation_id}")
async def operation_update(
    request: Request,
    operation_id: int,
    db: Session = Depends(get_db),
):
    operation = (
        db.query(Operation)
        .options(joinedload(Operation.items))
        .filter(Operation.id == operation_id)
        .first()
    )
    if not operation:
        raise HTTPException(status_code=404, detail="Операция не найдена")

    form = await request.form()
    data = {k: v for k, v in form.multi_items()}

    kind = data.get("kind")
    category_id = int(data.get("category_id") or 0)
    category = db.query(Category).filter(Category.id == category_id).first()
    if not category:
        raise HTTPException(status_code=400, detail="Категория не найдена")

    guests_count = int(data["guests_count"]) if data.get("guests_count") else None
    payment_method = data.get("payment_method") or None
    supplier_id = int(data["supplier_id"]) if data.get("supplier_id") else None
    employee_id = int(data["employee_id"]) if data.get("employee_id") else None
    responsible = data.get("responsible") or None

    items = _parse_items_from_form(form)
    _validate_operation_form(
        category=category,
        kind=kind,
        guests_count=guests_count,
        payment_method=payment_method,
        supplier_id=supplier_id,
        employee_id=employee_id,
        responsible=responsible,
        items=items,
    )

    columns = [c.name for c in Operation.__table__.columns]
    old_values = {c: getattr(operation, c) for c in columns}

    operation.date = date.fromisoformat(data["date"])
    operation.kind = kind
    operation.category_id = category_id
    operation.comment = data.get("comment") or None
    operation.guests_count = guests_count
    operation.payment_method = payment_method
    operation.supplier_id = supplier_id
    operation.employee_id = employee_id
    operation.responsible = responsible

    amount = Decimal(data.get("amount") or "0")
    if kind == "expense" and category.requires_products and items:
        calculated = sum(item.price * item.quantity for item in items)
        if amount == 0:
            amount = calculated
    operation.amount = amount

    # Пересоздаём строки продуктов
    for old_item in operation.items:
        db.delete(old_item)
    db.flush()
    for item in items:
        item.operation_id = operation.id
        db.add(item)

    db.flush()
    new_values = {c: getattr(operation, c) for c in columns}

    def _json_value(value):
        from datetime import date, datetime

        if isinstance(value, Decimal):
            return float(value)
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        return value

    changes = {
        k: {"old": _json_value(old_values[k]), "new": _json_value(new_values[k])}
        for k in old_values
        if old_values[k] != new_values[k]
    }
    _log_change(db, "operation", operation.id, "update", changes)
    db.commit()
    return RedirectResponse(url="/operations", status_code=302)


@router.post("/operations/{operation_id}/delete")
async def operation_delete(operation_id: int, db: Session = Depends(get_db)):
    operation = db.query(Operation).filter(Operation.id == operation_id).first()
    if not operation:
        raise HTTPException(status_code=404, detail="Операция не найдена")
    db.delete(operation)
    _log_change(db, "operation", operation.id, "delete")
    db.commit()
    return RedirectResponse(url="/operations", status_code=302)


@router.get("/api/operations", response_model=list[OperationRead])
async def api_operations_list(
    db: Session = Depends(get_db),
    kind: str | None = Query(None),
    category_id: int | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
):
    query = db.query(Operation).options(
        joinedload(Operation.category),
        joinedload(Operation.supplier),
        joinedload(Operation.employee),
        joinedload(Operation.items).joinedload(OperationItem.product),
    )
    if kind:
        query = query.filter(Operation.kind == kind)
    if category_id:
        query = query.filter(Operation.category_id == category_id)
    if date_from:
        query = query.filter(Operation.date >= date_from)
    if date_to:
        query = query.filter(Operation.date <= date_to)
    return query.order_by(Operation.date.desc(), Operation.id.desc()).all()


@router.get("/api/operations/{operation_id}", response_model=OperationRead)
async def api_operations_get(operation_id: int, db: Session = Depends(get_db)):
    operation = (
        db.query(Operation)
        .options(
            joinedload(Operation.category),
            joinedload(Operation.supplier),
            joinedload(Operation.employee),
            joinedload(Operation.items).joinedload(OperationItem.product),
        )
        .filter(Operation.id == operation_id)
        .first()
    )
    if not operation:
        raise HTTPException(status_code=404, detail="Операция не найдена")
    return operation


@router.post(
    "/api/operations",
    response_model=OperationRead,
    status_code=status.HTTP_201_CREATED,
)
async def api_operations_create(data: OperationCreate, db: Session = Depends(get_db)):
    operation = Operation(
        date=data.date,
        kind=data.kind,
        category_id=data.category_id,
        amount=data.amount,
        comment=data.comment,
        guests_count=data.guests_count,
        payment_method=data.payment_method,
        supplier_id=data.supplier_id,
        employee_id=data.employee_id,
        responsible=data.responsible,
    )
    db.add(operation)
    db.flush()
    for item in data.items:
        db.add(
            OperationItem(
                operation_id=operation.id,
                product_id=item.product_id,
                name=item.name,
                price=item.price,
                quantity=item.quantity,
                unit=item.unit,
            )
        )
    _log_change(db, "operation", operation.id, "create")
    db.commit()
    db.refresh(operation)
    return operation
