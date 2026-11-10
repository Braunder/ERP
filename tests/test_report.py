"""Тесты генерации отчёта P&L."""
import app.database as database_module
from app.services.report import build_report, report_to_matrix
from app.services.report import (
    ARTICLE_COLUMN_LABEL,
    REFERENCE_TITLE,
    TOTAL_COLUMN_LABEL,
)


def _find_category_id(client, kind, name):
    response = client.get(f"/api/categories?kind={kind}")
    assert response.status_code == 200
    for category in response.json():
        if category["name"] == name:
            return category["id"]
    raise AssertionError(f"Категория {name!r} не найдена")


def test_build_report_totals(client):
    client.post("/login", data={"password": "admin"})

    lavka_id = _find_category_id(client, "income", "Лавка")
    fuel_id = _find_category_id(client, "expense", "Бензин")
    wifi_id = _find_category_id(client, "expense", "WiFi")
    taxes_id = _find_category_id(client, "expense", "Налоги и сборы")

    # Доход
    client.post(
        "/api/operations",
        json={
            "date": "2024-06-15",
            "kind": "income",
            "category_id": lavka_id,
            "amount": "1000.00",
            "payment_method": "cash",
            "guests_count": 4,
        },
    )

    # Расходы
    client.post(
        "/api/operations",
        json={
            "date": "2024-06-20",
            "kind": "expense",
            "category_id": fuel_id,
            "amount": "300.00",
            "comment": "топливо",
        },
    )
    client.post(
        "/api/operations",
        json={
            "date": "2024-06-21",
            "kind": "expense",
            "category_id": wifi_id,
            "amount": "100.00",
        },
    )
    client.post(
        "/api/operations",
        json={
            "date": "2024-06-22",
            "kind": "expense",
            "category_id": taxes_id,
            "amount": "50.00",
        },
    )

    db = database_module.SessionLocal()
    try:
        report = build_report(db)
    finally:
        db.close()

    assert report.months == ["июнь"]

    rows_by_label = {row.label: row for row in report.rows}

    revenue_total = rows_by_label["Выручка всего"]
    assert revenue_total.values[0].amount == 1000
    assert revenue_total.values[0].percent == 100

    lavka_row = rows_by_label["Доход"]
    assert lavka_row.values[0].amount == 1000
    assert lavka_row.values[0].percent == 100
    # Категория «Лавка» внутри группы «Доход»
    assert any(sub.label == "· Лавка" for sub in lavka_row.subrows)
    assert any(sub.label == "· Бензин" for sub in rows_by_label["Прямой расход"].subrows)

    direct_section = rows_by_label["Прямые расходы"]
    assert direct_section.values[0].amount == 300
    assert direct_section.values[0].percent == 30

    overhead_section = rows_by_label["Накладные расходы"]
    assert overhead_section.values[0].amount == 100
    assert overhead_section.values[0].percent == 10
    assert any(sub.label == "· WiFi" for sub in overhead_section.subrows)

    assert "Другие группы" not in rows_by_label

    taxes_row = rows_by_label["Налоги и сборы"]
    assert taxes_row.values[0].amount == 50
    assert taxes_row.values[0].percent == 5

    profit_row = rows_by_label["Прибыль"]
    assert profit_row.values[0].amount == 550

    cumulative_row = rows_by_label["Прибыль итого"]
    assert cumulative_row.values[0].amount == 550


def test_report_matrix_shape(client):
    client.post("/login", data={"password": "admin"})

    lavka_id = _find_category_id(client, "income", "Лавка")
    client.post(
        "/api/operations",
        json={
            "date": "2024-07-01",
            "kind": "income",
            "category_id": lavka_id,
            "amount": "500.00",
            "payment_method": "cash",
            "guests_count": 2,
        },
    )

    db = database_module.SessionLocal()
    try:
        report = build_report(db)
        matrix = report_to_matrix(report)
    finally:
        db.close()

    n_months = len(report.months)
    # Эталонный лист: 61 строка, столбец статьи + один столбец на месяц + ИТОГО.
    assert len(matrix) == 61
    assert all(len(row) == 1 + n_months + 1 for row in matrix)

    # Строки 1–3: заголовок документа, подзаголовок, шапка столбцов.
    assert matrix[0][0] == REFERENCE_TITLE
    assert matrix[2][0] == ARTICLE_COLUMN_LABEL
    assert matrix[2][-1] == TOTAL_COLUMN_LABEL
    # Заголовки месяцев — даты первого числа: источник условий SUMIFS.
    assert matrix[2][1] == "2024-07-01"

    # Строки данных: одна строка на статью, имя категории без префикса.
    assert any(row[0] == "Лавка" for row in matrix)

    lavka_row = next(row for row in matrix if row[0] == "Лавка")
    assert lavka_row[1].startswith("=SUMIFS(Операции!")
    assert '"Доход"' in lavka_row[1]
    assert '"Лавка"' in lavka_row[1]
    assert "EDATE(" in lavka_row[1]


def test_report_matrix_revenue_total(client):
    client.post("/login", data={"password": "admin"})

    lavka_id = _find_category_id(client, "income", "Лавка")
    client.post(
        "/api/operations",
        json={
            "date": "2024-08-01",
            "kind": "income",
            "category_id": lavka_id,
            "amount": "250.00",
            "payment_method": "cash",
            "guests_count": 3,
        },
    )

    db = database_module.SessionLocal()
    try:
        report = build_report(db)
        matrix = report_to_matrix(report)
    finally:
        db.close()

    revenue_row = next(row for row in matrix if row[0] == "ВЫРУЧКА ГАСТРОФЕРМЫ")
    # Итог — формула, суммирующая месячные столбцы.
    assert revenue_row[-1].startswith("=SUM(")
    assert revenue_row[-1].endswith(")")
    # Секция суммирует детальные строки выручки (5–9), а не числа Python.
    assert revenue_row[1] == "=SUM(B5:B9)"


def test_investment_tab_and_report_row(client):
    client.post("/login", data={"password": "admin"})

    response = client.post(
        "/investments",
        data={
            "investment_date": "2026-08-15",
            "amount": "12500,50",
            "comment": "Оборудование",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302

    page = client.get("/investments")
    assert page.status_code == 200
    assert "Оборудование" in page.text
    assert "12500.50" in page.text

    db = database_module.SessionLocal()
    try:
        report = build_report(db)
    finally:
        db.close()

    investment_row = next(row for row in report.rows if row.label == "Инвестиции")
    assert report.months == ["август"]
    assert investment_row.values[0].amount == 12500.50

    matrix = report_to_matrix(report)
    investment_matrix_row = next(row for row in matrix if row[0] == "Инвестиции")
    # Итого — сумма всех инвестиций за весь период.
    assert investment_matrix_row[-1] == "=SUM(Инвестиции!$B$2:$B$1000)"
