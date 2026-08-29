# app\routers\employees.py
"""Сотрудники: HTML-CRUD и JSON API."""
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from starlette.templating import Jinja2Templates

from app.deps import get_db, require_auth
from app.models import ChangeLog, Employee, Operation
from app.schemas import EmployeeCreate, EmployeeRead

router = APIRouter(tags=["employees"], dependencies=[Depends(require_auth)])
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


@router.get("/employees")
async def employees_list(request: Request, db: Session = Depends(get_db)):
    employees = db.query(Employee).order_by(Employee.name).all()
    return templates.TemplateResponse(
        request,
        "employees/list.html",
        {"employees": employees},
    )


@router.post("/employees")
async def employee_create(
    request: Request,
    db: Session = Depends(get_db),
    name: str = Form(...),
    role: str | None = Form(None),
):
    employee = Employee(name=name, role=role)
    db.add(employee)
    db.flush()
    _log_change(db, "employee", employee.id, "create")
    db.commit()
    return RedirectResponse(url="/employees", status_code=302)


@router.post("/employees/{employee_id}")
async def employee_update(
    request: Request,
    employee_id: int,
    db: Session = Depends(get_db),
    name: str = Form(...),
    role: str | None = Form(None),
    is_active: bool = Form(True),
):
    employee = db.query(Employee).filter(Employee.id == employee_id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="Сотрудник не найден")

    columns = [c.name for c in Employee.__table__.columns]
    old_values = {c: getattr(employee, c) for c in columns}

    employee.name = name
    employee.role = role
    employee.is_active = is_active

    db.flush()
    new_values = {c: getattr(employee, c) for c in columns}
    changes = {
        k: {"old": old_values[k], "new": new_values[k]}
        for k in old_values
        if old_values[k] != new_values[k]
    }
    _log_change(db, "employee", employee.id, "update", changes)
    db.commit()
    return RedirectResponse(url="/employees", status_code=302)


@router.post("/employees/{employee_id}/delete")
async def employee_delete(employee_id: int, db: Session = Depends(get_db)):
    employee = db.query(Employee).filter(Employee.id == employee_id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="Сотрудник не найден")

    # Без этой проверки удаление сотрудника, использованного в операциях,
    # оставило бы Operation.employee_id указывающим на несуществующую строку
    # (SQLite не проверяет внешние ключи по умолчанию).
    operations_count = db.query(Operation).filter(Operation.employee_id == employee_id).count()
    if operations_count:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Нельзя удалить сотрудника «{employee.name}»: к нему привязано "
                f"{operations_count} операций."
            ),
        )

    db.delete(employee)
    _log_change(db, "employee", employee.id, "delete")
    db.commit()
    return RedirectResponse(url="/employees", status_code=302)


@router.get("/api/employees", response_model=list[EmployeeRead])
async def api_employees_list(db: Session = Depends(get_db)):
    return db.query(Employee).order_by(Employee.name).all()


@router.post("/api/employees", response_model=EmployeeRead)
async def api_employees_create(data: EmployeeCreate, db: Session = Depends(get_db)):
    employee = Employee(**data.model_dump())
    db.add(employee)
    db.flush()
    _log_change(db, "employee", employee.id, "create")
    db.commit()
    db.refresh(employee)
    return employee
