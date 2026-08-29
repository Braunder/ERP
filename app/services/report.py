# app\services\report.py
"""Генерация отчёта P&L по месяцам для Google Sheets."""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import Category, Employee, Investment, Operation, ReportGroup

MONTH_NAMES = [
    "январь",
    "февраль",
    "март",
    "апрель",
    "май",
    "июнь",
    "июль",
    "август",
    "сентябрь",
    "октябрь",
    "ноябрь",
    "декабрь",
]

# Подписи секций отчёта (для итоговых строк)
SECTION_LABELS = {
    "revenue": "Выручка",
    "direct": "Прямые расходы",
    "overhead": "Накладные расходы",
    "taxes": "Налоги и сборы",
    "other": "Прочее",
}


def report_group_label(group: ReportGroup | None) -> str:
    return group.name if group else "— не в отчёте —"


def report_group_option_label(group: ReportGroup | None) -> str:
    if not group:
        return "— не в отчёте —"
    section = SECTION_LABELS.get(group.section, group.section)
    return f"{group.name} ({section})"


@dataclass
class RowValue:
    amount: Decimal = Decimal("0")
    percent: Decimal = Decimal("0")
    raw: bool = True  # True для числовых ячеек, False для пустых/текстовых


@dataclass
class ReportRow:
    label: str
    section: str
    level: int = 0
    bold: bool = False
    skip_percent: bool = False
    background: str | None = None
    values: list[RowValue] = field(default_factory=list)
    subrows: list["ReportRow"] = field(default_factory=list)


@dataclass
class ReportData:
    months: list[str]
    rows: list[ReportRow]


def _month_label(year: int, month: int, years: set[int]) -> str:
    label = MONTH_NAMES[month - 1]
    if len(years) > 1:
        label = f"{label} {year}"
    return label


def _months_range(records: list[Operation | Investment]) -> list[tuple[int, int, str]]:
    """Возвращает список (year, month, label), отсортированный по хронологии."""
    if not records:
        today = date.today()
        return [(today.year, today.month, _month_label(today.year, today.month, {today.year}))]

    months_set: set[tuple[int, int]] = set()
    years: set[int] = set()
    for op in records:
        months_set.add((op.date.year, op.date.month))
        years.add(op.date.year)

    sorted_months = sorted(months_set)
    return [(y, m, _month_label(y, m, years)) for y, m in sorted_months]


def _collect_operations(db: Session) -> list[Operation]:
    return (
        db.query(Operation)
        .join(Category)
        .outerjoin(Employee)
        .order_by(Operation.date)
        .all()
    )


def _collect_investments(db: Session) -> list[Investment]:
    return db.query(Investment).order_by(Investment.date).all()


def _aggregate_investments(
    investments: list[Investment],
    months: list[tuple[int, int, str]],
) -> list[Decimal]:
    month_index = {(year, month): index for index, (year, month, _) in enumerate(months)}
    amounts = [Decimal("0") for _ in months]
    for investment in investments:
        index = month_index.get((investment.date.year, investment.date.month))
        if index is not None:
            amounts[index] += investment.amount
    return amounts


def _aggregate(
    operations: list[Operation],
    months: list[tuple[int, int, str]],
) -> tuple[list[Decimal], dict, dict, dict]:
    """Агрегирует суммы по месяцам, группам отчёта и сотрудникам."""
    month_index = {(y, m): i for i, (y, m, _) in enumerate(months)}
    n = len(months)

    # revenue[month_idx] = Decimal
    revenue: list[Decimal] = [Decimal("0") for _ in range(n)]
    # by_group[group_id][month_idx] = Decimal
    by_group: dict[int, list[Decimal]] = defaultdict(lambda: [Decimal("0") for _ in range(n)])
    # by_employee[group_id][employee_name][month_idx] = Decimal
    by_employee: dict[int, dict[str, list[Decimal]]] = defaultdict(
        lambda: defaultdict(lambda: [Decimal("0") for _ in range(n)])
    )
    # by_group_category[group_id][category_name][month_idx] = Decimal
    by_group_category: dict[int, dict[str, list[Decimal]]] = defaultdict(
        lambda: defaultdict(lambda: [Decimal("0") for _ in range(n)])
    )

    for op in operations:
        idx = month_index.get((op.date.year, op.date.month))
        if idx is None:
            continue

        group_id = op.category.report_group_id
        amount = op.amount

        if op.kind == "income":
            revenue[idx] += amount

        if group_id:
            by_group[group_id][idx] += amount
            by_group_category[group_id][op.category.name][idx] += amount
            if op.employee_id and op.employee:
                by_employee[group_id][op.employee.name][idx] += amount

    return revenue, by_group, by_employee, by_group_category


def _calc_row(
    months: list[tuple[int, int, str]],
    revenue: list[Decimal],
    amounts: list[Decimal],
    skip_percent: bool = False,
) -> list[RowValue]:
    values = []
    for i, _ in enumerate(months):
        amt = amounts[i]
        if skip_percent:
            values.append(RowValue(amount=amt, percent=Decimal("0"), raw=True))
        else:
            pct = Decimal("0")
            if revenue[i]:
                pct = (amt / revenue[i]) * Decimal("100")
            values.append(RowValue(amount=amt, percent=pct, raw=True))
    return values


def _is_zero(amounts: list[Decimal]) -> bool:
    return all(a == 0 for a in amounts)


def _group_row(
    group: ReportGroup,
    months: list[tuple[int, int, str]],
    revenue: list[Decimal],
    by_group: dict[int, list[Decimal]],
    by_group_category: dict[int, dict[str, list[Decimal]]],
    by_employee: dict[int, dict[str, list[Decimal]]],
) -> ReportRow | None:
    """Строка группы отчёта с категориями внутри.

    Возвращает None, если по группе нет ни одной операции за период
    (нулевые строки не попадают в Excel/Google Sheets).
    """
    n = len(months)
    amounts = by_group.get(group.id, [Decimal("0") for _ in range(n)])
    if _is_zero(amounts):
        return None

    row = ReportRow(
        label=group.name,
        section=group.section,
        level=1,
        values=_calc_row(months, revenue, amounts),
    )

    # Категории внутри группы отчёта — процент от суммы группы (не от выручки)
    group_amounts = by_group.get(group.id, [Decimal("0") for _ in range(n)])
    for cat_name in sorted(by_group_category.get(group.id, {}).keys()):
        cat_amounts = by_group_category[group.id][cat_name]
        if _is_zero(cat_amounts):
            continue
        # Процент подкатегории = сумма подкатегории / сумма группы
        sub_pct = [
            (cat_amounts[i] / group_amounts[i] * Decimal("100")) if group_amounts[i] else Decimal("0")
            for i in range(n)
        ]
        sub_values = []
        for i in range(n):
            sub_values.append(RowValue(amount=cat_amounts[i], percent=sub_pct[i], raw=True))
        row.subrows.append(
            ReportRow(
                label=f"· {cat_name}",
                section=group.section,
                level=2,
                values=sub_values,
            )
        )

    # Разбивка по сотрудникам (например, «Съели сами»)
    for employee_name in sorted(by_employee.get(group.id, {}).keys()):
        emp_amounts = by_employee[group.id][employee_name]
        if _is_zero(emp_amounts):
            continue
        row.subrows.append(
            ReportRow(
                label=f"👤 {employee_name}",
                section=group.section,
                level=2,
                values=_calc_row(months, revenue, emp_amounts),
            )
        )

    return row


def _blank_separator(section: str, n: int) -> ReportRow:
    return ReportRow(
        label="",
        section=f"{section}_separator",
        level=0,
        values=[RowValue(amount=Decimal("0"), percent=Decimal("0"), raw=False) for _ in range(n)],
    )


def _section_total_row(
    section: str,
    label: str,
    totals: list[Decimal],
    months: list[tuple[int, int, str]],
    revenue: list[Decimal],
    background: str | None,
) -> ReportRow:
    return ReportRow(
        label=label,
        section=section,
        level=0,
        bold=True,
        background=background,
        values=_calc_row(months, revenue, totals),
    )


def _append_section(
    rows: list[ReportRow],
    section: str,
    label: str,
    section_rows: list[ReportRow],
    totals: list[Decimal],
    months: list[tuple[int, int, str]],
    revenue: list[Decimal],
    background: str | None,
    n: int,
) -> None:
    if not _is_zero(totals):
        header = _section_total_row(section, label, totals, months, revenue, background)
        duplicate_rows = [row for row in section_rows if row.label == label]
        for duplicate in duplicate_rows:
            header.subrows.extend(duplicate.subrows)
        rows.append(header)
        rows.extend(row for row in section_rows if row.label != label)
    rows.append(_blank_separator(section, n))


def build_report(db: Session) -> ReportData:
    """Строит отчёт P&L по месяцам на основе групп отчёта из БД."""
    operations = _collect_operations(db)
    investments = _collect_investments(db)
    months = _months_range([*operations, *investments])
    revenue, by_group, by_employee, by_group_category = _aggregate(operations, months)
    investment_amounts = _aggregate_investments(investments, months)
    n = len(months)

    groups = (
        db.query(ReportGroup)
        .order_by(ReportGroup.sort_order, ReportGroup.id)
        .all()
    )

    rows: list[ReportRow] = []

    # Итоги по секциям (для строк «... всего» и прибыли)
    section_totals: dict[str, list[Decimal]] = defaultdict(
        lambda: [Decimal("0") for _ in range(n)]
    )
    rows_by_section: dict[str, list[ReportRow]] = defaultdict(list)

    # Строки групп отчёта с категориями внутри; нулевые группы пропускаются
    for group in groups:
        row = _group_row(group, months, revenue, by_group, by_group_category, by_employee)
        if row is None:
            continue
        rows_by_section[group.section].append(row)
        totals = section_totals[group.section]
        vals = by_group.get(group.id, [Decimal("0") for _ in range(n)])
        for i in range(n):
            totals[i] += vals[i]

    # Выручка: заголовок секции + все группы дохода
    if not _is_zero(revenue):
        rows.append(
            _section_total_row("revenue", "Выручка всего", revenue, months, revenue, "yellow")
        )
        rows.extend(rows_by_section.get("revenue", []))
        rows.append(_blank_separator("revenue", n))

    # Прямые расходы: заголовок секции + все группы прямых расходов
    direct_totals = section_totals.get("direct", [Decimal("0") for _ in range(n)])
    _append_section(
        rows,
        "direct",
        "Прямые расходы",
        rows_by_section.get("direct", []),
        direct_totals,
        months,
        revenue,
        "blue",
        n,
    )

    # Накладные расходы: заголовок секции + все группы накладных расходов
    overhead_totals = section_totals.get("overhead", [Decimal("0") for _ in range(n)])
    _append_section(
        rows,
        "overhead",
        "Накладные расходы",
        rows_by_section.get("overhead", []),
        overhead_totals,
        months,
        revenue,
        "blue",
        n,
    )

    # Остальные группы отчёта (например, налоги и прочее)
    other_section_rows = []
    other_sections = {"revenue", "direct", "overhead"}
    for section in sorted(rows_by_section, key=lambda s: (s not in {"other", "taxes"}, s)):
        if section in other_sections:
            continue
        other_section_rows.extend(rows_by_section.get(section, []))

    if other_section_rows:
        other_totals = [Decimal("0") for _ in range(n)]
        for section in rows_by_section:
            if section in other_sections:
                continue
            for i in range(n):
                other_totals[i] += section_totals.get(section, [Decimal("0") for _ in range(n)])[i]
        rows.append(
            _section_total_row("other", "Другие группы", other_totals, months, revenue, "blue")
        )
        rows.extend(other_section_rows)
        rows.append(_blank_separator("other", n))

    # Прибыль уже считается по всем расходам, включая налоги и прочее.
    # Для этого вычитаем все секции, не относящиеся к доходам, из выручки.
    other_total_all = [Decimal("0") for _ in range(n)]
    for section, totals in section_totals.items():
        if section == "revenue":
            continue
        for i in range(n):
            other_total_all[i] += totals[i]

    profit_amounts = [revenue[i] - other_total_all[i] for i in range(n)]

    rows.append(
        ReportRow(
            label="Прибыль",
            section="profit",
            level=0,
            bold=True,
            skip_percent=True,
            background="green",
            values=_calc_row(months, revenue, profit_amounts, skip_percent=True),
        )
    )

    # Прибыль итого (накопительно)
    cumulative = [Decimal("0") for _ in range(n)]
    running = Decimal("0")
    for i in range(n):
        running += profit_amounts[i]
        cumulative[i] = running
    # Общая сумма за всё время — в колонке B (первый столбец данных)
    cumulative_first = [sum(cumulative, start=Decimal("0"))]
    rows.append(
        ReportRow(
            label="Прибыль итого",
            section="cumulative_profit",
            level=1,
            bold=True,
            skip_percent=True,
            values=[RowValue(amount=amt, percent=Decimal("0"), raw=True) for amt in cumulative_first],
        )
    )

    # Инвестиции вводятся на отдельной вкладке и попадают в отчёт по месяцам.
    # Общая сумма — в колонке B.
    investment_first = [sum(investment_amounts, start=Decimal("0"))]
    rows.append(
        ReportRow(
            label="Инвестиции",
            section="manual",
            level=1,
            bold=True,
            skip_percent=True,
            values=[RowValue(amount=amt, percent=Decimal("0"), raw=True) for amt in investment_first],
        )
    )

    return ReportData(
        months=[label for _, _, label in months],
        rows=rows,
    )


def report_to_matrix(report: ReportData) -> list[list]:
    """Преобразует ReportData в матрицу для записи в Google Sheets."""
    months = report.months

    # Заголовок месяцев: первая ячейка пустая, затем для каждого месяца название (объединяется в два столбца)
    header1: list[object] = [""]
    for label in months:
        header1.extend([label, ""])

    header2: list[object] = [""]
    for _ in months:
        header2.extend(["сумма", "%"])

    matrix = [header1, header2]

    # Строка «Выручка всего» в таблице (данные начинаются с 3-й строки).
    # Используется как знаменатель в формулах процентов.
    REVENUE_ROW = 3

    def _col_letter(col: int) -> str:
        """Числовой индекс столбца (1-based) в буквенный (A, B, ..., Z, AA)."""
        result = ""
        while col > 0:
            col, rem = divmod(col - 1, 26)
            result = chr(65 + rem) + result
        return result

    def append_row(row: ReportRow):
        line: list[object] = [row.label]
        row_number = len(matrix) + 1
        for i, val in enumerate(row.values):
            # Столбец суммы месяца i (1-based): B, D, F, ...
            sum_col_letter = _col_letter(2 + i * 2)
            if val.raw:
                line.append(float(val.amount))
                if row.skip_percent:
                    line.append("")
                else:
                    # Живая формула: доля от выручки этого месяца.
                    # Пересчитывается автоматически при изменении сумм в таблице.
                    line.append(str(f'={sum_col_letter}{row_number}/{sum_col_letter}${REVENUE_ROW}'))
            else:
                line.append("")
                line.append("")
        matrix.append(line)
        for sub in row.subrows:
            append_row(sub)

    for row in report.rows:
        append_row(row)

    return matrix
