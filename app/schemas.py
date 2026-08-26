"""Pydantic-схемы для API и валидации форм."""
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict


class CategoryBase(BaseModel):
    name: str
    kind: str
    parent_id: int | None = None
    requires_payment_method: bool = False
    requires_guests: bool = False
    requires_supplier: bool = False
    requires_products: bool = False
    requires_employee: bool = False
    requires_responsible: bool = False
    is_active: bool = True
    report_group_id: int | None = None


class CategoryCreate(CategoryBase):
    pass


class CategoryRead(CategoryBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    children: list["CategoryRead"] = []


class ReportGroupBase(BaseModel):
    name: str
    section: str = "direct"
    sort_order: int = 100
    is_active: bool = True


class ReportGroupCreate(ReportGroupBase):
    pass


class ReportGroupRead(ReportGroupBase):
    model_config = ConfigDict(from_attributes=True)

    id: int


class SupplierBase(BaseModel):
    name: str
    contact: str | None = None
    is_active: bool = True


class SupplierCreate(SupplierBase):
    pass


class SupplierRead(SupplierBase):
    model_config = ConfigDict(from_attributes=True)

    id: int


class ProductBase(BaseModel):
    name: str
    unit: str = "шт"
    is_active: bool = True


class ProductCreate(ProductBase):
    pass


class ProductRead(ProductBase):
    model_config = ConfigDict(from_attributes=True)

    id: int


class ProductPriceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    supplier_id: int
    price: Decimal


class ProductWithPricesRead(ProductRead):
    prices: list[ProductPriceRead] = []


class EmployeeBase(BaseModel):
    name: str
    role: str | None = None
    is_active: bool = True


class EmployeeCreate(EmployeeBase):
    pass


class EmployeeRead(EmployeeBase):
    model_config = ConfigDict(from_attributes=True)

    id: int


class OperationItemBase(BaseModel):
    product_id: int | None = None
    name: str
    price: Decimal
    quantity: Decimal
    unit: str = "шт"


class OperationItemCreate(OperationItemBase):
    pass


class OperationItemRead(OperationItemBase):
    model_config = ConfigDict(from_attributes=True)

    id: int


class OperationBase(BaseModel):
    date: date
    kind: str
    category_id: int
    amount: Decimal
    comment: str | None = None
    guests_count: int | None = None
    payment_method: str | None = None
    supplier_id: int | None = None
    employee_id: int | None = None
    responsible: str | None = None


class OperationCreate(OperationBase):
    items: list[OperationItemCreate] = []


class OperationRead(OperationBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
    category: CategoryRead | None = None
    supplier: SupplierRead | None = None
    employee: EmployeeRead | None = None
    items: list[OperationItemRead] = []


class CategorySummary(BaseModel):
    category_id: int
    category_name: str
    kind: str
    total: Decimal


class StatsSummary(BaseModel):
    income: Decimal
    expense: Decimal
    balance: Decimal
    by_category: list[CategorySummary]


class PeriodStat(BaseModel):
    period: str
    income: Decimal
    expense: Decimal


class CategoryStat(BaseModel):
    category: str
    kind: str
    amount: Decimal


class PaymentStat(BaseModel):
    payment_method: str
    label: str
    amount: Decimal


class StatsData(BaseModel):
    totals: dict[str, str]
    by_period: list[PeriodStat]
    by_category: list[CategoryStat]
    by_payment: list[PaymentStat]


class SyncLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    success: bool
    message: str
    details: dict | None = None
    records_count: int | None = None
