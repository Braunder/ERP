"""Идемпотентное заполнение справочников: группы отчёта, категории, сотрудники."""
from sqlalchemy.orm import Session

from app.models import Category, Employee, ReportGroup


# Простые группы отчёта P&L. Порядок = порядок в выгрузке.
REPORT_GROUPS_SEED: list[tuple[str, str, int]] = [
    ("Доход", "revenue", 10),
    ("Прямой расход", "direct", 20),
    ("Накладные расходы", "overhead", 30),
    ("Налоги и сборы", "taxes", 40),
]


def _get_or_create_report_group(session: Session, name: str, section: str, sort_order: int) -> ReportGroup:
    group = session.query(ReportGroup).filter_by(name=name).first()
    if group:
        return group
    group = ReportGroup(name=name, section=section, sort_order=sort_order)
    session.add(group)
    session.flush()
    return group

def _get_or_create_category(
    session: Session,
    name: str,
    kind: str,
    parent: Category | None = None,
    report_group: ReportGroup | None = None,
    requires_payment_method: bool = False,
    requires_guests: bool = False,
    requires_supplier: bool = False,
    requires_products: bool = False,
    requires_employee: bool = False,
    requires_responsible: bool = False,
) -> Category:
    query = session.query(Category).filter_by(name=name, kind=kind)
    if parent is None:
        query = query.filter(Category.parent_id.is_(None))
    else:
        query = query.filter_by(parent_id=parent.id)

    category = query.first()
    if category:
        # Обновляем маппинг отчёта при изменении справочника
        if report_group is not None and category.report_group_id != report_group.id:
            category.report_group_id = report_group.id
        return category

    category = Category(
        name=name,
        kind=kind,
        parent_id=parent.id if parent else None,
        report_group_id=report_group.id if report_group else None,
        requires_payment_method=requires_payment_method,
        requires_guests=requires_guests,
        requires_supplier=requires_supplier,
        requires_products=requires_products,
        requires_employee=requires_employee,
        requires_responsible=requires_responsible,
    )
    session.add(category)
    session.flush()
    return category


def _get_or_create_employee(session: Session, name: str) -> Employee:
    employee = session.query(Employee).filter_by(name=name).first()
    if employee:
        return employee
    employee = Employee(name=name)
    session.add(employee)
    session.flush()
    return employee


def seed_db(session: Session) -> None:
    """Создаёт группы отчёта, категории и сотрудников, если их ещё нет."""
    groups = {
        name: _get_or_create_report_group(session, name, section, sort_order)
        for name, section, sort_order in REPORT_GROUPS_SEED
    }
    income = groups["Доход"]
    direct = groups["Прямой расход"]
    overhead = groups["Накладные расходы"]
    taxes = groups["Налоги и сборы"]

    # Доходы
    income_categories = [
        ("Лавка", {"requires_guests": True}),
        ("Кейтеринг", {"requires_guests": True}),
        ("Открытые события", {"requires_guests": True}),
    ]

    for name, flags in income_categories:
        _get_or_create_category(
            session,
            name=name,
            kind="income",
            report_group=income,
            requires_payment_method=True,
            **flags,
        )

    # Расходы
    expense_categories = [
        ("Аренда", {"requires_guests": False}),
        ("Оборудование", {"requires_guests": False}),
        ("Площадка", {"requires_guests": False}),
        ("Посуда", {"requires_guests": False}),
        ("Выездные мероприятия", {"requires_guests": True}),
        ("Доставка продуктов", {"requires_guests": True}),
        ("Комиссия", {"requires_guests": True}),
        ("Открытые события", {"requires_guests": True}),
        ("Ужины/Обеды", {"requires_guests": True}),
    ]
    for name, flags in expense_categories:
        _get_or_create_category(
            session,
            name=name,
            kind="expense",
            report_group=overhead,
            requires_payment_method=True,
            **flags,
        )

    # Дочерние категории расходов (аренда)
    arenda = _get_or_create_category(
        session,
        name="Аренда",
        kind="expense",
        report_group=overhead,
        requires_payment_method=True,
        requires_guests=False,
    )
    for child_name in ("Оборудование", "Посуда", "Площадка"):
        _get_or_create_category(
            session,
            name=child_name,
            kind="expense",
            parent=arenda,
            report_group=overhead,
            requires_payment_method=True,
            requires_guests=False,
        )

    # Расходы — закупка продуктов
    zakupka = _get_or_create_category(
        session,
        name="Закупка продуктов",
        kind="expense",
        report_group=direct,
        requires_supplier=True,
        requires_products=True,
    )
    for child_name in (
        "Мясо и рыба",
        "Овощи и фрукты",
        "Бакалея",
        "Молочные продукты",
        "Напитки",
        "Хозтовары",
    ):
        _get_or_create_category(
            session,
            name=child_name,
            kind="expense",
            parent=zakupka,
            report_group=direct,
            requires_supplier=True,
            requires_products=True,
        )

    # Остальные прямые расходы
    direct_expenses = [
        ("Себестоимость кейтеринга", {}),
        ("Корм для животных", {}),
        ("Бензин", {}),
        ("Служебное питание", {}),
        ("Зарплата сотрудникам", {"requires_employee": True}),
        ("Опреционные расходы", {}),
        ("Прочие прямые расходы", {}),
    ]
    for name, flags in direct_expenses:
        _get_or_create_category(
            session,
            name=name,
            kind="expense",
            report_group=direct,
            **flags,
        )

    # Накладные расходы
    overhead_expenses = [
        "Эквайринг",
        "Доставка и логистика",
        "WiFi",
        "Комиссия банка",
        "ИТ",
        "Коммунальные платежи",
        "Финансы",
        "Маркетинг",
        "Оборудование и инвентарь",
        "Аренда помещения",
        "Прочие накладные расходы",
    ]
    for name in overhead_expenses:
        _get_or_create_category(
            session,
            name=name,
            kind="expense",
            report_group=overhead,
        )

    # Списания
    spisaniya = _get_or_create_category(
        session,
        name="Списания",
        kind="expense",
        report_group=direct,
    )
    _get_or_create_category(
        session,
        name="Съели сами",
        kind="expense",
        parent=spisaniya,
        report_group=direct,
        requires_responsible=True,
    )
    _get_or_create_category(
        session,
        name="Порча/просрочка",
        kind="expense",
        parent=spisaniya,
        report_group=direct,
    )

    # Налоги
    _get_or_create_category(
        session,
        name="Налоги и сборы",
        kind="expense",
        report_group=taxes,
    )

    # Сотрудники
    for name in ("Ира", "Илья", "Каштанова"):
        _get_or_create_employee(session, name)

    session.commit()
