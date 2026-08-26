"""Тесты генерации отчёта P&L."""
import app.database as database_module
from app.services.report import build_report, report_to_matrix


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
    products_id = _find_category_id(client, "expense", "Закупка продуктов")
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
        },
    )

    # Расходы
    client.post(
        "/api/operations",
        json={
            "date": "2024-06-20",
            "kind": "expense",
            "category_id": products_id,
            "amount": "300.00",
            "comment": "продукты",
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

    direct_total = rows_by_label["Прямые расходы всего"]
    assert direct_total.values[0].amount == 300
    assert direct_total.values[0].percent == 30

    overhead_total = rows_by_label["Накладные расходы всего"]
    assert overhead_total.values[0].amount == 100
    assert overhead_total.values[0].percent == 10

    taxes_row = rows_by_label["Налоги и сборы"]
    assert taxes_row.values[0].amount == 50
    assert taxes_row.values[0].percent == 5

    taxes_total = rows_by_label["Налоги и сборы всего"]
    assert taxes_total.values[0].amount == 50

    profit_row = rows_by_label["Прибыль"]
    assert profit_row.values[0].amount == 550

    cumulative_row = rows_by_label["прибыль итого"]
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
        },
    )

    db = database_module.SessionLocal()
    try:
        report = build_report(db)
        matrix = report_to_matrix(report)
    finally:
        db.close()

    # Первая строка: пустая + по 2 ячейки на месяц
    assert len(matrix[0]) == 1 + len(report.months) * 2
    # Вторая строка: пустая + сумма/%
    assert matrix[1][1] == "сумма"
    assert matrix[1][2] == "%"
    # Хотя бы одна строка данных
    assert len(matrix) > 2
