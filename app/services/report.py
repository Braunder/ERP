"""Генерация отчёта P&L по месяцам для Google Sheets."""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import Category, Employee, Operation, ReportGroup

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


def _months_range(operations: list[Operation]) -> list[tuple[int, int, str]]:
    """Возвращает список (year, month, label), отсортированный по хронологии."""
    if not operations:
        today = date.today()
        return [(today.year, today.month, _month_label(today.year, today.month, {today.year}))]

    months_set: set[tuple[int, int]] = set()
    years: set[int] = set()
    for op in operations:
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


def build_report(db: Session) -> ReportData:
    """Строит отчёт P&L по месяцам на основе групп отчёта из БД."""
    operations = _collect_operations(db)
    months = _months_range(operations)
    revenue, by_group, by_employee, by_group_category = _aggregate(operations, months)
    n = len(months)

    groups = (
        db.query(ReportGroup)
        .order_by(ReportGroup.sort_order, ReportGroup.id)
        .all()
    )

    rows: list[ReportRow] = []

    # Выручка всего
    rows.append(
        ReportRow(
            label="Выручка всего",
            section="revenue_total",
            level=0,
            bold=True,
            background="yellow",
            values=_calc_row(months, revenue, revenue),
        )
    )

    # Итоги по секциям (для строк «... всего» и прибыли)
    section_totals: dict[str, list[Decimal]] = defaultdict(
        lambda: [Decimal("0") for _ in range(n)]
    )

    # Строки групп отчёта с категориями внутри; нулевые группы пропускаются
    for group in groups:
        row = _group_row(group, months, revenue, by_group, by_group_category, by_employee)
        if row is None:
            continue
        rows.append(row)
        totals = section_totals[group.section]
        vals = by_group.get(group.id, [Decimal("0") for _ in range(n)])
        for i in range(n):
            totals[i] += vals[i]

    # Итоговые строки по секциям расходов и налогов
    direct_totals = section_totals.get("direct", [Decimal("0") for _ in range(n)])
    overhead_totals = section_totals.get("overhead", [Decimal("0") for _ in range(n)])
    taxes_totals = section_totals.get("taxes", [Decimal("0") for _ in range(n)])

    if not _is_zero(direct_totals):
        rows.append(
            ReportRow(
                label="Прямые расходы всего",
                section="direct_total",
                level=0,
                bold=True,
                background="blue",
                values=_calc_row(months, revenue, direct_totals),
            )
        )

    if not _is_zero(overhead_totals):
        rows.append(
            ReportRow(
                label="Накладные расходы всего",
                section="overhead_total",
                level=0,
                bold=True,
                background="blue",
                values=_calc_row(months, revenue, overhead_totals),
            )
        )

    if not _is_zero(taxes_totals):
        rows.append(
            ReportRow(
                label="Налоги и сборы всего",
                section="taxes_total",
                level=0,
                bold=True,
                background="blue",
                values=_calc_row(months, revenue, taxes_totals),
            )
        )

    # Прибыль
    profit_amounts = [
        revenue[i] - direct_totals[i] - overhead_totals[i] - taxes_totals[i]
        for i in range(n)
    ]
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
    rows.append(
        ReportRow(
            label="прибыль итого",
            section="cumulative_profit",
            level=1,
            bold=True,
            skip_percent=True,
            values=_calc_row(months, revenue, cumulative, skip_percent=True),
        )
    )

    # Инвестиции (пустая строка для ручного заполнения)
    rows.append(
        ReportRow(
            label="инвестиции",
            section="manual",
            level=1,
            bold=True,
            skip_percent=True,
            values=[RowValue(amount=Decimal("0"), percent=Decimal("0"), raw=False) for _ in range(n)],
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
    header1 = [""]
    for label in months:
        header1.extend([label, ""])

    header2 = [""]
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
        line = [row.label]
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
