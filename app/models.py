"""Модели данных SQLAlchemy 2.0 (typed mapped)."""
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ReportGroup(Base):
    """Группа отчёта P&L (например, «Прямой расход», «Накладный расход»).

    Порядок вывода в отчёте задаётся полем sort_order.
    """

    __tablename__ = "report_groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    section: Mapped[str] = mapped_column(String(20), default="direct")  # revenue/direct/overhead/taxes/other
    sort_order: Mapped[int] = mapped_column(Integer, default=100)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    categories: Mapped[list["Category"]] = relationship(back_populates="report_group_ref")


class Category(Base):
    """Категория дохода/расхода, многоуровневая (self FK)."""

    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(10))  # "income" / "expense"
    name: Mapped[str] = mapped_column(String(200))
    parent_id: Mapped[Optional[int]] = mapped_column(ForeignKey("categories.id"), nullable=True)

    # Флаги дополнительных полей формы операции
    requires_payment_method: Mapped[bool] = mapped_column(Boolean, default=False)
    requires_guests: Mapped[bool] = mapped_column(Boolean, default=False)
    requires_supplier: Mapped[bool] = mapped_column(Boolean, default=False)
    requires_products: Mapped[bool] = mapped_column(Boolean, default=False)
    requires_employee: Mapped[bool] = mapped_column(Boolean, default=False)
    requires_responsible: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Группа для отчёта P&L (ссылка на report_groups.id)
    report_group_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("report_groups.id"), nullable=True
    )

    parent: Mapped[Optional["Category"]] = relationship(remote_side=[id], back_populates="children")
    children: Mapped[list["Category"]] = relationship(back_populates="parent", order_by="Category.id")
    operations: Mapped[list["Operation"]] = relationship(back_populates="category")
    report_group_ref: Mapped[Optional["ReportGroup"]] = relationship(back_populates="categories")


class Supplier(Base):
    __tablename__ = "suppliers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    contact: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    product_prices: Mapped[list["ProductPrice"]] = relationship(back_populates="supplier", cascade="all, delete-orphan")
    operations: Mapped[list["Operation"]] = relationship(back_populates="supplier")


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    unit: Mapped[str] = mapped_column(String(20), default="шт")  # шт/кг/л
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    prices: Mapped[list["ProductPrice"]] = relationship(back_populates="product", cascade="all, delete-orphan")
    items: Mapped[list["OperationItem"]] = relationship(back_populates="product")


class ProductPrice(Base):
    """Закупочная цена продукта у конкретного поставщика."""

    __tablename__ = "product_prices"
    __table_args__ = (UniqueConstraint("product_id", "supplier_id", name="uq_product_supplier"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"))
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))

    product: Mapped[Product] = relationship(back_populates="prices")
    supplier: Mapped[Supplier] = relationship(back_populates="product_prices")


class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    role: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    operations: Mapped[list["Operation"]] = relationship(back_populates="employee")


class Operation(Base):
    """Операция дохода/расхода."""

    __tablename__ = "operations"

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(String(10))  # "income" / "expense"
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    guests_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    payment_method: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # cash/card/transfer
    supplier_id: Mapped[Optional[int]] = mapped_column(ForeignKey("suppliers.id"), nullable=True)
    employee_id: Mapped[Optional[int]] = mapped_column(ForeignKey("employees.id"), nullable=True)
    responsible: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)  # для «Съели сами»: Ира/Илья
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    category: Mapped[Category] = relationship(back_populates="operations")
    supplier: Mapped[Optional[Supplier]] = relationship(back_populates="operations")
    employee: Mapped[Optional[Employee]] = relationship(back_populates="operations")
    items: Mapped[list["OperationItem"]] = relationship(
        back_populates="operation", cascade="all, delete-orphan", order_by="OperationItem.id"
    )


class OperationItem(Base):
    """Строка продуктов внутри операции (мульти-ввод)."""

    __tablename__ = "operation_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    operation_id: Mapped[int] = mapped_column(ForeignKey("operations.id", ondelete="CASCADE"))
    product_id: Mapped[Optional[int]] = mapped_column(ForeignKey("products.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(200))  # снимок наименования
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 3))
    unit: Mapped[str] = mapped_column(String(20), default="шт")

    operation: Mapped[Operation] = relationship(back_populates="items")
    product: Mapped[Optional[Product]] = relationship(back_populates="items")


class ChangeLog(Base):
    """История изменений сущностей (пишется в CRUD-роутерах)."""

    __tablename__ = "change_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    entity: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(10))  # create/update/delete
    changes: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class SyncLog(Base):
    """Лог попыток синхронизации с Google Sheets."""

    __tablename__ = "sync_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    success: Mapped[bool]
    message: Mapped[str] = mapped_column(Text)
    details: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    records_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
