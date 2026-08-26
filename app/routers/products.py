"""Продукты: HTML-CRUD и JSON API."""
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from starlette.templating import Jinja2Templates

from app.deps import get_db, require_auth
from app.models import ChangeLog, Product, ProductPrice
from app.schemas import ProductCreate, ProductPriceRead, ProductRead, ProductWithPricesRead

router = APIRouter(tags=["products"], dependencies=[Depends(require_auth)])
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


@router.get("/products")
async def products_list(request: Request, db: Session = Depends(get_db)):
    products = db.query(Product).order_by(Product.name).all()
    return templates.TemplateResponse(
        request,
        "products/list.html",
        {"products": products},
    )


@router.post("/products")
async def product_create(
    request: Request,
    db: Session = Depends(get_db),
    name: str = Form(...),
    unit: str = Form("шт"),
):
    product = Product(name=name, unit=unit)
    db.add(product)
    db.flush()
    _log_change(db, "product", product.id, "create")
    db.commit()
    return RedirectResponse(url="/products", status_code=302)


@router.post("/products/{product_id}")
async def product_update(
    request: Request,
    product_id: int,
    db: Session = Depends(get_db),
    name: str = Form(...),
    unit: str = Form("шт"),
    is_active: bool = Form(True),
):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Продукт не найден")

    columns = [c.name for c in Product.__table__.columns]
    old_values = {c: getattr(product, c) for c in columns}

    product.name = name
    product.unit = unit
    product.is_active = is_active

    db.flush()
    new_values = {c: getattr(product, c) for c in columns}
    changes = {
        k: {"old": old_values[k], "new": new_values[k]}
        for k in old_values
        if old_values[k] != new_values[k]
    }
    _log_change(db, "product", product.id, "update", changes)
    db.commit()
    return RedirectResponse(url="/products", status_code=302)


@router.post("/products/{product_id}/delete")
async def product_delete(product_id: int, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Продукт не найден")
    db.delete(product)
    _log_change(db, "product", product.id, "delete")
    db.commit()
    return RedirectResponse(url="/products", status_code=302)


@router.get("/api/products", response_model=list[ProductWithPricesRead])
async def api_products_list(
    db: Session = Depends(get_db),
    supplier_id: int | None = None,
    active: bool | None = None,
):
    query = db.query(Product)
    if active is not None:
        query = query.filter(Product.is_active == active)
    if supplier_id is not None:
        query = query.join(ProductPrice).filter(ProductPrice.supplier_id == supplier_id)
    return query.order_by(Product.name).all()


@router.post("/api/products", response_model=ProductRead)
async def api_products_create(data: ProductCreate, db: Session = Depends(get_db)):
    product = Product(**data.model_dump())
    db.add(product)
    db.flush()
    _log_change(db, "product", product.id, "create")
    db.commit()
    db.refresh(product)
    return product


@router.get("/api/product-prices", response_model=list[ProductPriceRead])
async def api_product_prices(
    db: Session = Depends(get_db),
    supplier_id: int | None = None,
    product_id: int | None = None,
):
    query = db.query(ProductPrice)
    if supplier_id is not None:
        query = query.filter(ProductPrice.supplier_id == supplier_id)
    if product_id is not None:
        query = query.filter(ProductPrice.product_id == product_id)
    return query.all()
