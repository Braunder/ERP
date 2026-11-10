"""Генерация отчёта P&L по месяцам для Google Sheets."""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import Category, Employee, Investment, Operation, ReportGroup
from app.timezone import local_today

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
    "touroperator": "Доходы туроператора",
    "direct": "Прямые расходы",
    "overhead": "Накладные расходы",
    "taxes": "Налоги и сборы",
    "outside": "Вне финансового результата",
    "other": "Прочее",
}

# Секции, которые не являются расходами и не участвуют в операционной
# прибыли: доходы (учтены в выручке) и статьи вне финансового результата
# (Арт-парк) — эталон держит их отдельным блоком ниже прибыли.
NON_EXPENSE_SECTIONS = {"revenue", "touroperator", "outside"}

# --- Параметры выгрузки, воспроизводящие эталонный файл ---
# docs/report_reference_spec.md: лист «Отчет» A1:I61, один столбец на месяц
# плюс «ИТОГО», живые формулы SUMIFS по листам данных.

REPORT_SHEET_TITLE = "Отчет"
OPERATIONS_SHEET_TITLE = "Операции"
INVESTMENTS_SHEET_TITLE = "Инвестиции"
WRITEOFFS_SHEET_TITLE = "Списания"

# Диапазон строк листов данных в формулах (=SUMIFS(...$F$2:$F$1000...)).
DATA_RANGE_FIRST_ROW = 2
DATA_RANGE_LAST_ROW = 1000

# Запас строк формата дат в листах данных: новые строки, добавленные
# вручную или при следующей выгрузке, уже получают dd.mm.yyyy.
DATE_FORMAT_TAIL_ROWS = 200

REFERENCE_TITLE = "ЗИМАРИ · ПОМЕСЯЧНЫЙ ФИНАНСОВЫЙ ОТЧЕТ | ERP MVP (3)"
REFERENCE_SUBTITLE = "Два разреза операционной прибыли · предварительные списания"
ARTICLE_COLUMN_LABEL = "Статья"
TOTAL_COLUMN_LABEL = "ИТОГО"

REFERENCE_NOTES = (
    "Методика: «Съели сами» из ERP исключены из расходов; "
    "оценка списаний уменьшает убыток после корректировки.",
    "Подарки показаны отдельной справочной строкой маркетинга без повторного "
    "начисления себестоимости.",
    "Инвестиции и Арт-парк не участвуют в прибыли; в графе ИТОГО показаны "
    "суммы за весь период учета.",
)

MONEY_NUMBER_FORMAT = '#,##0.00 "₽";[Red](#,##0.00 "₽");"–"'
MONTH_NUMBER_FORMAT = "mmmm yyyy"
DATE_NUMBER_FORMAT = "dd.mm.yyyy"

# Разделитель аргументов формул: в Google Sheets с русской локалью — «;».
FORMULA_SEPARATOR = ";"

# Палитра эталона (RGB без alpha) и высоты/ширины в единицах Excel.
STYLE_PALETTE: dict[str, dict] = {
    "title": {"bold": True, "font_size": 16, "font_color": "FFFFFF", "background": "173528"},
    "subtitle": {"font_size": 10, "font_color": "627469"},
    "header": {"bold": True, "font_size": 11, "font_color": "FFFFFF", "background": "21734B"},
    "section": {"bold": True, "font_size": 11, "font_color": "143C2A", "background": "DCEEE1"},
    "detail": {"font_size": 11},
    "profit": {"bold": True, "font_size": 11, "font_color": "123C28", "background": "B4DAC1"},
    "outside": {"bold": True, "font_size": 11, "font_color": "143C2A", "background": "E4EEE8"},
    "blank": {"font_size": 11},
    "note": {"font_size": 10, "font_color": "667A70"},
}

ROW_HEIGHTS: dict[int, float] = {
    1: 35.0,
    2: 24.0,
    3: 27.0,
    4: 24.0,
    10: 24.0,
    12: 24.0,
    14: 24.0,
    27: 24.0,
    38: 24.0,
    41: 29.0,
    42: 29.0,
    44: 24.0,
    48: 29.0,
    49: 29.0,
    51: 24.0,
    55: 24.0,
    56: 13.9,
    57: 13.9,
    59: 20.0,
    60: 20.0,
    61: 20.0,
}

COLUMN_WIDTHS: dict[str, float] = {"A": 58.0, "B": 21.0}

# Freeze B10: закреплены 9 верхних строк и один левый столбец.
FREEZE_ROWS = 9
FREEZE_COLUMNS = 1

# Строки, для которых применяется денежный формат (включая пустые разделители).
MONEY_FORMAT_FIRST_ROW = 4
MONEY_FORMAT_LAST_ROW = 57

# Заголовки создаваемого листа «Списания» — как в эталоне.
WRITEOFFS_HEADERS = [
    "Дата",
    "Группа",
    "Товар / продукт",
    "Количество",
    "Ед.",
    "Закуп. цена / ед., ₽",
    "Предв. себестоимость, ₽",
    "Комментарий / статус",
    "Источник",
    "Месяц (для отчета)",
]


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
    # Первый день каждого месяца столбца отчёта: нужен для живых формул
    # (=EDATE(B$3;1), =TEXT(B$3;"yyyy-mm")), где строка 3 хранит даты.
    month_starts: list[date] = field(default_factory=list)


def _month_label(year: int, month: int, years: set[int]) -> str:
    label = MONTH_NAMES[month - 1]
    if len(years) > 1:
        label = f"{label} {year}"
    return label


def _months_range(records: list[Operation | Investment]) -> list[tuple[int, int, str]]:
    """Возвращает список (year, month, label), отсортированный по хронологии."""
    if not records:
        today = local_today()
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
) -> tuple[
    list[Decimal],
    dict[int, list[Decimal]],
    dict[int, dict[str, list[Decimal]]],
    list[Decimal],
]:
    """Агрегирует суммы по месяцам, группам и категориям.

    Возвращает также расходы без группы отчёта, чтобы они не терялись
    при расчёте прибыли.
    """
    month_index = {(y, m): i for i, (y, m, _) in enumerate(months)}
    n = len(months)

    # revenue[month_idx] = Decimal
    revenue: list[Decimal] = [Decimal("0") for _ in range(n)]
    # by_group[group_id][month_idx] = Decimal
    by_group: dict[int, list[Decimal]] = defaultdict(lambda: [Decimal("0") for _ in range(n)])
    # Расходы без группы отчёта не отображаются отдельной строкой,
    # но обязательно учитываются в прибыли.
    ungrouped_expenses: list[Decimal] = [Decimal("0") for _ in range(n)]
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
        elif op.kind == "expense":
            ungrouped_expenses[idx] += amount

    return revenue, by_group, by_group_category, ungrouped_expenses


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
    revenue, by_group, by_group_category, ungrouped_expenses = _aggregate(operations, months)
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
        row = _group_row(group, months, revenue, by_group, by_group_category)
        if row is None:
            continue
        rows_by_section[group.section].append(row)
        totals = section_totals[group.section]
        vals = by_group.get(group.id, [Decimal("0") for _ in range(n)])
        for i in range(n):
            totals[i] += vals[i]

    # Выручка: строка всегда должна быть первой строкой данных.
    # Это позволяет формулам процентов стабильно ссылаться на строку 3.
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

    # Налоги и сборы - отдельная секция, а не часть «Других групп».
    taxes_totals = section_totals.get("taxes", [Decimal("0") for _ in range(n)])
    _append_section(
        rows,
        "taxes",
        "Налоги и сборы",
        rows_by_section.get("taxes", []),
        taxes_totals,
        months,
        revenue,
        "blue",
        n,
    )

    # Только неизвестные/прочие секции попадают в «Другие группы».
    other_section_rows: list[ReportRow] = []
    known_sections = NON_EXPENSE_SECTIONS | {"direct", "overhead", "taxes"}
    for section in sorted(rows_by_section):
        if section in known_sections:
            continue
        other_section_rows.extend(rows_by_section.get(section, []))

    if other_section_rows:
        other_totals = [Decimal("0") for _ in range(n)]
        for section in rows_by_section:
            if section in known_sections:
                continue
            section_amounts = section_totals.get(section, [Decimal("0") for _ in range(n)])
            for i in range(n):
                other_totals[i] += section_amounts[i]
        _append_section(
            rows,
            "other",
            "Другие группы",
            other_section_rows,
            other_totals,
            months,
            revenue,
            "blue",
            n,
        )

    # Прибыль считается по всем расходам, включая налоги и прочее.
    # Доходы и статьи вне финансового результата из выручки не вычитаются.
    other_total_all = [Decimal("0") for _ in range(n)]
    for section, totals in section_totals.items():
        if section in NON_EXPENSE_SECTIONS:
            continue
        for i in range(n):
            other_total_all[i] += totals[i]

    # Расходы без группы отчёта не видны в P&L, но не должны исчезать
    # из расчёта прибыли.
    for i in range(n):
        other_total_all[i] += ungrouped_expenses[i]

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

    # Прибыль итого = фактическая сумма прибыли за весь период.
    # В каждой строке отчёта должно быть ровно столько значений,
    # сколько месяцев в заголовке; итог показываем только в первом месяце.
    cumulative_first = [sum(profit_amounts, start=Decimal("0"))] + [Decimal("0")] * max(0, n - 1)
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
    investment_first = [sum(investment_amounts, start=Decimal("0"))] + [Decimal("0")] * max(0, n - 1)
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
        month_starts=[date(year, month, 1) for year, month, _ in months],
    )


def _col_letter(col: int) -> str:
    """Числовой индекс столбца (1-based) в буквенный (A, B, ..., Z, AA)."""
    result = ""
    while col > 0:
        col, rem = divmod(col - 1, 26)
        result = chr(65 + rem) + result
    return result


def _func(name: str, *args: str, sep: str = FORMULA_SEPARATOR) -> str:
    """Собирает вызов функции с разделителем аргументов целевой локали."""
    return f"{name}({sep.join(args)})"


def _data_range(sheet: str, column: str) -> str:
    return (
        f"{sheet}!${column}${DATA_RANGE_FIRST_ROW}"
        f":${column}${DATA_RANGE_LAST_ROW}"
    )


def _operations_sumifs(
    col: str, op_type: str, category: str, *, by_month: bool = True, sep: str = FORMULA_SEPARATOR
) -> str:
    """SUMIFS по листу «Операции»: тип операции, категория и (опционально) месяц."""
    args: list[str] = [_data_range(OPERATIONS_SHEET_TITLE, "F")]
    if by_month:
        args += [
            _data_range(OPERATIONS_SHEET_TITLE, "B"),
            f'">="&{col}$3',
            _data_range(OPERATIONS_SHEET_TITLE, "B"),
            f'"<"&{_func("EDATE", col + "$3", "1", sep=sep)}',
        ]
    args += [
        _data_range(OPERATIONS_SHEET_TITLE, "C"),
        f'"{op_type}"',
        _data_range(OPERATIONS_SHEET_TITLE, "D"),
        f'"{category}"',
    ]
    return "=" + _func("SUMIFS", *args, sep=sep)


def _writeoffs_sumifs(col: str, group: str, *, sep: str = FORMULA_SEPARATOR) -> str:
    """SUMIFS по листу «Списания» за месяц из заголовка столбца."""
    month_text = _func("TEXT", col + "$3", chr(34) + "yyyy-mm" + chr(34), sep=sep)
    return "=" + _func(
        "SUMIFS",
        _data_range(WRITEOFFS_SHEET_TITLE, "G"),
        _data_range(WRITEOFFS_SHEET_TITLE, "J"),
        month_text,
        _data_range(WRITEOFFS_SHEET_TITLE, "B"),
        f'"{group}"',
        sep=sep,
    )


def _investments_sumifs(col: str, *, sep: str = FORMULA_SEPARATOR) -> str:
    """SUMIFS по листу «Инвестиции» за месяц из заголовка столбца."""
    return "=" + _func(
        "SUMIFS",
        _data_range(INVESTMENTS_SHEET_TITLE, "B"),
        _data_range(INVESTMENTS_SHEET_TITLE, "A"),
        f'">="&{col}$3',
        _data_range(INVESTMENTS_SHEET_TITLE, "A"),
        f'"<"&{_func("EDATE", col + "$3", "1", sep=sep)}',
        sep=sep,
    )


@dataclass(frozen=True)
class ReportLine:
    """Описание одной строки листа «Отчет» в эталонном формате."""

    label: str = ""
    style: str = "blank"
    # blank — пустая строка/разделитель, title/subtitle/header/note — текстовые,
    # ops — SUMIFS по операциям, writeoffs — SUMIFS по списаниям,
    # investments — SUMIFS по инвестициям, expr — формула-ссылка, sum — сумма диапазонов.
    kind: str = "blank"
    op_type: str = ""
    category: str = ""
    group: str = ""
    # str — шаблон формулы с {c} (буква текущего столбца) или tuple шаблонов для sum.
    ref: str | tuple[str, ...] = ""
    # Итог в последнем столбце: months — сумма по месячным столбцам,
    # none — пусто, ops_all/investments_all — сумма за весь период учета.
    total: str = "months"
    # Ожидаемый номер строки: защита от рассинхронизации ссылок в формулах.
    row: int | None = None


# П&Л эталона: строки 1–61, один столбец на месяц + «ИТОГО».
# Порядок элементов списка = порядок строк на листе.
REPORT_TEMPLATE: tuple[ReportLine, ...] = (
    ReportLine(REFERENCE_TITLE, "title", "title", total="none", row=1),
    ReportLine(REFERENCE_SUBTITLE, "subtitle", "subtitle", total="none", row=2),
    ReportLine(ARTICLE_COLUMN_LABEL, "header", "header", total="none", row=3),

    ReportLine("ВЫРУЧКА ГАСТРОФЕРМЫ", "section", "sum", ref=("{c}5:{c}9",), row=4),
    ReportLine("Кейтеринг", "detail", "ops", op_type="Доход", category="Кейтеринг"),
    ReportLine("Лавка", "detail", "ops", op_type="Доход", category="Лавка"),
    ReportLine("Открытые события", "detail", "ops", op_type="Доход", category="Открытые события"),
    ReportLine("Мероприятия (обеды и ужины)", "detail", "ops", op_type="Доход", category="Мероприятия (обеды и ужины)"),
    ReportLine("Аренда", "detail", "ops", op_type="Доход", category="Аренда"),

    ReportLine("ДОХОДЫ ТУРОПЕРАТОРА", "section", "expr", ref="={c}11", row=10),
    ReportLine("Доход туроператор", "detail", "ops", op_type="Доход", category="Доход туроператор"),
    ReportLine("ОБЩАЯ ВЫРУЧКА", "section", "expr", ref="={c}4+{c}10", row=12),
    ReportLine(style="blank", total="none"),

    # Из прямых расходов исключены «Съели сами» — они учитываются отдельной
    # строкой корректировки (45) по оценке списаний (46).
    ReportLine("ПРЯМЫЕ РАСХОДЫ", "section", "expr", ref="=SUM({c}15:{c}25)-{c}45", row=14),
    ReportLine("Бензин", "detail", "ops", op_type="Расход", category="Бензин"),
    ReportLine("Зарплата сотрудникам", "detail", "ops", op_type="Расход", category="Зарплата сотрудникам"),
    ReportLine("Корм для животных", "detail", "ops", op_type="Расход", category="Корм для животных"),
    ReportLine("Молочные продукты", "detail", "ops", op_type="Расход", category="Молочные продукты"),
    ReportLine("Операционные расходы", "detail", "ops", op_type="Расход", category="Операционные расходы"),
    ReportLine("Продукты", "detail", "ops", op_type="Расход", category="Продукты"),
    ReportLine("Продукты для производства колбасы", "detail", "ops", op_type="Расход", category="Продукты для производства колбасы"),
    ReportLine("Прочие прямые расходы", "detail", "ops", op_type="Расход", category="Прочие прямые расходы"),
    ReportLine("Себестоимость кейтеринга", "detail", "ops", op_type="Расход", category="Себестоимость кейтеринга"),
    ReportLine("Служебное питание", "detail", "ops", op_type="Расход", category="Служебное питание"),
    ReportLine("Хозтовары", "detail", "ops", op_type="Расход", category="Хозтовары"),
    ReportLine(style="blank", total="none"),

    ReportLine("НАКЛАДНЫЕ РАСХОДЫ", "section", "sum", ref=("{c}28:{c}31", "{c}33:{c}36"), row=27),
    ReportLine("WiFi", "detail", "ops", op_type="Расход", category="WiFi"),
    ReportLine("ИТ", "detail", "ops", op_type="Расход", category="ИТ"),
    ReportLine("Комиссия банка", "detail", "ops", op_type="Расход", category="Комиссия банка"),
    ReportLine("Маркетинг (ERP)", "detail", "ops", op_type="Расход", category="Маркетинг"),
    ReportLine("Списание маркетинг — подарки", "detail", "ops", op_type="Расход", category="Списание маркетинг — подарки"),
    ReportLine("Прочие накладные расходы", "detail", "ops", op_type="Расход", category="Прочие накладные расходы"),
    ReportLine("Финансовые услуги", "detail", "ops", op_type="Расход", category="Финансовые услуги"),
    ReportLine("Хостинг", "detail", "ops", op_type="Расход", category="Хостинг"),
    ReportLine("Эквайринг", "detail", "ops", op_type="Расход", category="Эквайринг"),
    ReportLine(style="blank", total="none"),

    ReportLine("НАЛОГИ И СБОРЫ", "section", "expr", ref="={c}39", row=38),
    ReportLine("Налоги и сборы", "detail", "ops", op_type="Расход", category="Налоги и сборы"),
    ReportLine(style="blank", total="none"),

    ReportLine(
        "ОПЕРАЦИОННАЯ ПРИБЫЛЬ — ТОЛЬКО ГАСТРОФЕРМА",
        "profit",
        "expr",
        ref="={c}4-{c}14-{c}27-{c}38",
        row=41,
    ),
    ReportLine(
        "ОПЕРАЦИОННАЯ ПРИБЫЛЬ — ГАСТРОФЕРМА + ТУРОПЕРАТОР",
        "profit",
        "expr",
        ref="={c}41+{c}10",
        row=42,
    ),
    ReportLine(style="blank", total="none"),

    ReportLine("КОРРЕКТИРОВКА ЛИЧНОГО ПОТРЕБЛЕНИЯ", "section", "blank", total="none", row=44),
    ReportLine("Съели сами — отражено расходом в ERP", "detail", "ops", op_type="Расход", category="Съели сами"),
    ReportLine("Съели сами — оценка списаний", "detail", "writeoffs", group="Съели сами/взяли себе", row=46),
    ReportLine(style="blank", total="none"),

    ReportLine(
        "ПРИБЫЛЬ ПОСЛЕ КОРРЕКТИРОВКИ — ТОЛЬКО ГАСТРОФЕРМА",
        "profit",
        "expr",
        ref="={c}41+{c}46",
        row=48,
    ),
    ReportLine(
        "ПРИБЫЛЬ ПОСЛЕ КОРРЕКТИРОВКИ — ГАСТРОФЕРМА + ТУРОПЕРАТОР",
        "profit",
        "expr",
        ref="={c}42+{c}46",
        row=49,
    ),
    ReportLine(style="blank", total="none"),

    ReportLine("СПИСАНИЯ (СПРАВОЧНО)", "section", "blank", total="none", row=51),
    ReportLine("Подарки — оцененная себестоимость", "detail", "expr", ref="={c}32", row=52),
    ReportLine("Неуточненные списания", "detail", "writeoffs", group="Уточнить", row=53),
    ReportLine(style="blank", total="none"),

    ReportLine("ВНЕ ФИНАНСОВОГО РЕЗУЛЬТАТА", "section", "blank", total="none", row=55),
    ReportLine(
        "Арт-парк",
        "outside",
        "ops",
        op_type="Расход",
        category="Арт-парк",
        total="ops_all",
        row=56,
    ),
    ReportLine("Инвестиции", "outside", "investments", total="investments_all", row=57),
    ReportLine(style="blank", total="none"),

    ReportLine(REFERENCE_NOTES[0], "note", "note", total="none", row=59),
    ReportLine(REFERENCE_NOTES[1], "note", "note", total="none", row=60),
    ReportLine(REFERENCE_NOTES[2], "note", "note", total="none", row=61),
)


def _line_formula(line: ReportLine, col: str, *, sep: str = FORMULA_SEPARATOR) -> str:
    """Формула строки для месячного столбца с буквой ``col``."""
    if line.kind == "ops":
        return _operations_sumifs(col, line.op_type, line.category, sep=sep)
    if line.kind == "writeoffs":
        return _writeoffs_sumifs(col, line.group, sep=sep)
    if line.kind == "investments":
        return _investments_sumifs(col, sep=sep)
    if line.kind == "expr":
        return str(line.ref).format(c=col)
    if line.kind == "sum":
        return "=" + _func("SUM", *[str(ref).format(c=col) for ref in line.ref], sep=sep)
    return ""


def _total_formula(
    line: ReportLine, first_col: str, last_col: str, row_number: int, *, sep: str = FORMULA_SEPARATOR
) -> str:
    """Формула столбца «ИТОГО»: сумма месяцев либо сумма за весь период."""
    if line.total == "months":
        return "=" + _func("SUM", f"{first_col}{row_number}:{last_col}{row_number}", sep=sep)
    if line.total == "ops_all":
        return _operations_sumifs(first_col, line.op_type, line.category, by_month=False, sep=sep)
    if line.total == "investments_all":
        return "=" + _func("SUM", _data_range(INVESTMENTS_SHEET_TITLE, "B"), sep=sep)
    return ""


def report_layout() -> list[dict]:
    """Стили и форматы строк листа «Отчет» по номерам строк эталона."""
    layout: list[dict] = []
    for index, line in enumerate(REPORT_TEMPLATE):
        row_number = index + 1
        layout.append(
            {
                "row": row_number,
                "style": line.style,
                "height": ROW_HEIGHTS.get(row_number),
                "money": MONEY_FORMAT_FIRST_ROW <= row_number <= MONEY_FORMAT_LAST_ROW,
            }
        )
    return layout


def report_to_matrix(report: ReportData, *, separator: str = FORMULA_SEPARATOR) -> list[list]:
    """Строит лист «Отчет» в эталонном формате: строки 1–61, один столбец
    на месяц плюс «ИТОГО», живые SUMIFS/EDATE/TEXT по листам данных.

    Значения считаются не Python'ом, а самим Google Sheets, поэтому после
    правки операций или списаний в таблице отчёт пересчитывается сам.

    ``separator`` — разделитель аргументов функций: «;» для русской локали
    таблицы и «,» для английской.
    """
    labels = report.months
    month_starts = report.month_starts
    n = len(labels)
    if n == 0:
        return []

    first_col = _col_letter(2)
    last_col = _col_letter(1 + n)

    matrix: list[list] = []
    for index, line in enumerate(REPORT_TEMPLATE):
        row_number = index + 1
        if line.row is not None and line.row != row_number:
            raise ValueError(
                f"Строка шаблона {line.label!r} стоит на {row_number}, "
                f"а формулы ссылаются на {line.row}"
            )

        cells: list[object] = [line.label]
        if line.kind == "header":
            # Даты в строке заголовков — источник условий всех SUMIFS.
            for i in range(n):
                cells.append(
                    month_starts[i].isoformat()
                    if i < len(month_starts)
                    else labels[i]
                )
            cells.append(TOTAL_COLUMN_LABEL)
        elif line.kind in {"title", "subtitle", "note", "blank"}:
            cells.extend([""] * (n + 1))
        else:
            for i in range(n):
                cells.append(_line_formula(line, _col_letter(2 + i), sep=separator))
            cells.append(
                _total_formula(line, first_col, last_col, row_number, sep=separator)
            )

        matrix.append(cells)

    return matrix