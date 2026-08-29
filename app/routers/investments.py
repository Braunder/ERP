"""HTML-CRUD инвестиций."""
from datetime import date
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from starlette.templating import Jinja2Templates

from app.deps import get_db, require_auth
from app.models import Investment

router = APIRouter(tags=["investments"], dependencies=[Depends(require_auth)])
templates = Jinja2Templates(directory="app/templates")


@router.get("/investments")
async def investments_list(request: Request, db: Session = Depends(get_db)):
    investments = db.query(Investment).order_by(Investment.date.desc(), Investment.id.desc()).all()
    total = sum((investment.amount for investment in investments), start=0)
    return templates.TemplateResponse(
        request,
        "investments/list.html",
        {"investments": investments, "total": total},
    )


@router.post("/investments")
async def investment_create(
    investment_date: date = Form(...),
    amount: str = Form(...),
    comment: str | None = Form(None),
    db: Session = Depends(get_db),
):
    try:
        investment_amount = Decimal(amount.replace(",", ".").replace(" ", ""))
    except InvalidOperation as exc:
        raise HTTPException(status_code=400, detail="Сумма должна быть числом") from exc
    if investment_amount <= 0:
        raise HTTPException(status_code=400, detail="Сумма должна быть больше нуля")

    db.add(Investment(date=investment_date, amount=investment_amount, comment=comment or None))
    db.commit()
    return RedirectResponse(url="/investments", status_code=302)


@router.post("/investments/{investment_id}/delete")
async def investment_delete(investment_id: int, db: Session = Depends(get_db)):
    investment = db.query(Investment).filter(Investment.id == investment_id).first()
    if not investment:
        raise HTTPException(status_code=404, detail="Инвестиция не найдена")
    db.delete(investment)
    db.commit()
    return RedirectResponse(url="/investments", status_code=302)
