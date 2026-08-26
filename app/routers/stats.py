"""Статистика: страница графиков и JSON API для Chart.js."""
from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func
from sqlalchemy.orm import Session
from starlette.templating import Jinja2Templates

from app.deps import get_db, require_auth
from app.models import Category, Operation
from app.schemas import CategorySummary, StatsData, StatsSummary

router = APIRouter(tags=["stats"], dependencies=[Depends(require_auth)])
templates = Jinja2Templates(directory="app/templates")

PAYMENT_METHOD_LABELS = {
    "cash": "Нал",
    "card": "Б/нал",
    "transfer": "Перевод",
}


def _period_mode(date_from: date | None, date_to: date | None) -> str:
    """Выбирает режим группировки по датам: day / week / month."""
    if date_from and date_to:
        days = (date_to - date_from).days + 1
        if days > 365:
            return "month"
        if days > 60:
            return "week"
    return "day"


def _period_expr(mode: str):
    """SQLAlchemy-выражение для строки периода в зависимости от режима."""
    if mode == "month":
        return func.strftime("%Y-%m", Operation.date)
    if mode == "week":
        return func.strftime("%Y-%W", Operation.date)
    return func.strftime("%Y-%m-%d", Operation.date)


def _apply_filters(
    query,
    *,
    kind: str | None = None,
    category_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    payment_method: str | None = None,
):
    if kind and kind != "all":
        query = query.filter(Operation.kind == kind)
    if category_id:
        query = query.filter(Operation.category_id == category_id)
    if date_from:
        query = query.filter(Operation.date >= date_from)
    if date_to:
        query = query.filter(Operation.date <= date_to)
    if payment_method:
        query = query.filter(Operation.payment_method == payment_method)
    return query


@router.get("/stats")
async def stats_page(request: Request):
    return templates.TemplateResponse(
        request,
        "stats/charts.html",
        {},
    )


@router.get("/api/stats/summary", response_model=StatsSummary)
async def api_stats_summary(
    db: Session = Depends(get_db),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
):
    query = db.query(Operation)
    if date_from:
        query = query.filter(Operation.date >= date_from)
    if date_to:
        query = query.filter(Operation.date <= date_to)

    income = (
        query.filter(Operation.kind == "income")
        .with_entities(func.coalesce(func.sum(Operation.amount), 0))
        .scalar()
    )
    expense = (
        query.filter(Operation.kind == "expense")
        .with_entities(func.coalesce(func.sum(Operation.amount), 0))
        .scalar()
    )

    category_totals = (
        query.join(Category)
        .group_by(Category.id, Category.name, Category.kind)
        .with_entities(
            Category.id.label("category_id"),
            Category.name.label("category_name"),
            Category.kind.label("kind"),
            func.sum(Operation.amount).label("total"),
        )
        .order_by(Category.kind, Category.name)
        .all()
    )

    return StatsSummary(
        income=income,
        expense=expense,
        balance=income - expense,
        by_category=[
            CategorySummary(
                category_id=row.category_id,
                category_name=row.category_name,
                kind=row.kind,
                total=row.total,
            )
            for row in category_totals
        ],
    )


@router.get("/api/stats/data", response_model=StatsData)
async def api_stats_data(
    db: Session = Depends(get_db),
    kind: str = Query("all", pattern="^(all|income|expense)$"),
    category_id: int | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    payment_method: str | None = Query(None),
):
    base_query = _apply_filters(
        db.query(Operation),
        kind=kind,
        category_id=category_id,
        date_from=date_from,
        date_to=date_to,
        payment_method=payment_method,
    )

    # Итоги: доход/расход/баланс с учётом фильтров
    income = (
        base_query.filter(Operation.kind == "income")
        .with_entities(func.coalesce(func.sum(Operation.amount), Decimal("0")))
        .scalar()
    )
    expense = (
        base_query.filter(Operation.kind == "expense")
        .with_entities(func.coalesce(func.sum(Operation.amount), Decimal("0")))
        .scalar()
    )

    totals = {
        "income": str(income.quantize(Decimal("0.01"))),
        "expense": str(expense.quantize(Decimal("0.01"))),
        "balance": str((income - expense).quantize(Decimal("0.01"))),
    }

    # Группировка по периодам
    mode = _period_mode(date_from, date_to)
    period_expr = _period_expr(mode)

    period_rows = (
        base_query.group_by(period_expr, Operation.kind)
        .with_entities(
            period_expr.label("period"),
            Operation.kind,
            func.coalesce(func.sum(Operation.amount), Decimal("0")).label("amount"),
        )
        .order_by(period_expr)
        .all()
    )

    period_map: dict[str, dict[str, Decimal]] = {}
    for row in period_rows:
        period_map.setdefault(row.period, {"income": Decimal("0"), "expense": Decimal("0")})
        period_map[row.period][row.kind] = row.amount

    by_period = [
        {
            "period": period,
            "income": str(values["income"].quantize(Decimal("0.01"))),
            "expense": str(values["expense"].quantize(Decimal("0.01"))),
        }
        for period, values in sorted(period_map.items())
    ]

    # По категориям
    category_query = _apply_filters(
        db.query(Operation).join(Category),
        kind=kind,
        category_id=category_id,
        date_from=date_from,
        date_to=date_to,
        payment_method=payment_method,
    )
    category_rows = (
        category_query.group_by(Category.id, Category.name, Category.kind)
        .with_entities(
            Category.name.label("category"),
            Category.kind,
            func.coalesce(func.sum(Operation.amount), Decimal("0")).label("amount"),
        )
        .order_by(func.sum(Operation.amount).desc())
        .all()
    )
    by_category = [
        {
            "category": row.category,
            "kind": row.kind,
            "amount": str(row.amount.quantize(Decimal("0.01"))),
        }
        for row in category_rows
    ]

    # По способам оплаты (только доход)
    payment_query = _apply_filters(
        db.query(Operation),
        kind="income",
        category_id=category_id,
        date_from=date_from,
        date_to=date_to,
        payment_method=payment_method,
    )
    payment_rows = (
        payment_query.filter(Operation.payment_method.isnot(None))
        .group_by(Operation.payment_method)
        .with_entities(
            Operation.payment_method,
            func.coalesce(func.sum(Operation.amount), Decimal("0")).label("amount"),
        )
        .order_by(func.sum(Operation.amount).desc())
        .all()
    )
    by_payment = [
        {
            "payment_method": row.payment_method,
            "label": PAYMENT_METHOD_LABELS.get(row.payment_method, row.payment_method),
            "amount": str(row.amount.quantize(Decimal("0.01"))),
        }
        for row in payment_rows
    ]

    return StatsData(
        totals=totals,
        by_period=by_period,
        by_category=by_category,
        by_payment=by_payment,
    )


@router.get("/api/stats/filters")
async def api_stats_filters(db: Session = Depends(get_db)):
    categories = (
        db.query(Category)
        .filter(Category.is_active == True)
        .order_by(Category.kind, Category.name)
        .all()
    )
    return {
        "categories": [
            {
                "id": c.id,
                "name": c.name,
                "kind": c.kind,
                "parent_id": c.parent_id,
            }
            for c in categories
        ],
        "payment_methods": [
            {"value": key, "label": label}
            for key, label in PAYMENT_METHOD_LABELS.items()
        ],
    }
