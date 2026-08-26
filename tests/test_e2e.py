"""Функциональное E2E-тестирование основного сценария."""
from datetime import date


def _find_category(client, kind, name):
    response = client.get(f"/api/categories?kind={kind}")
    assert response.status_code == 200
    for category in response.json():
        if category["name"] == name:
            return category["id"]
    raise AssertionError(f"Категория {name!r} не найдена")


def test_full_workflow(client):
    # 1. Логин
    login_response = client.post("/login", data={"password": "admin"}, follow_redirects=False)
    assert login_response.status_code == 302
    assert "session" in login_response.cookies

    # 2. Создание категории
    category_response = client.post(
        "/api/categories",
        json={"name": "E2E категория", "kind": "expense", "requires_products": True},
    )
    assert category_response.status_code in (200, 201)
    category_id = category_response.json()["id"]

    # 3. Создание поставщика
    supplier_response = client.post("/api/suppliers", json={"name": "E2E поставщик"})
    assert supplier_response.status_code in (200, 201)
    supplier_id = supplier_response.json()["id"]

    # 4. Создание продукта
    product_response = client.post("/api/products", json={"name": "E2E продукт", "unit": "кг"})
    assert product_response.status_code in (200, 201)
    product_id = product_response.json()["id"]

    # 5. Создание доходной операции (Лавка)
    lavka_id = _find_category(client, "income", "Лавка")
    income_response = client.post(
        "/api/operations",
        json={
            "date": "2024-07-01",
            "kind": "income",
            "category_id": lavka_id,
            "amount": "5000.00",
            "comment": "E2E лавка",
            "payment_method": "cash",
        },
    )
    assert income_response.status_code == 201
    income_id = income_response.json()["id"]

    # 6. Создание расходной операции с продуктами
    expense_response = client.post(
        "/operations",
        data={
            "date": "2024-07-02",
            "kind": "expense",
            "category_id": category_id,
            "amount": "0",
            "comment": "E2E закупка",
            "supplier_id": supplier_id,
            "items[0][product_id]": product_id,
            "items[0][name]": "E2E продукт",
            "items[0][price]": "250.00",
            "items[0][quantity]": "3",
            "items[0][unit]": "кг",
        },
        follow_redirects=False,
    )
    assert expense_response.status_code == 302
    assert expense_response.headers["location"] == "/operations"

    operations = client.get("/api/operations").json()
    expense_op = next((o for o in operations if o["comment"] == "E2E закупка"), None)
    assert expense_op is not None
    assert expense_op["amount"] == "750.00"
    assert len(expense_op["items"]) == 1
    assert expense_op["items"][0]["name"] == "E2E продукт"

    # 7. Редактирование операции
    edit_response = client.post(
        f"/operations/{expense_op['id']}",
        data={
            "date": "2024-07-02",
            "kind": "expense",
            "category_id": category_id,
            "amount": "0",
            "comment": "E2E закупка обновлена",
            "supplier_id": supplier_id,
            "items[0][product_id]": product_id,
            "items[0][name]": "E2E продукт",
            "items[0][price]": "300.00",
            "items[0][quantity]": "2",
            "items[0][unit]": "кг",
        },
        follow_redirects=False,
    )
    assert edit_response.status_code == 302

    updated = client.get(f"/api/operations/{expense_op['id']}").json()
    assert updated["amount"] == "600.00"
    assert updated["comment"] == "E2E закупка обновлена"

    # 8. Проверка /api/stats/data
    stats_response = client.get("/api/stats/data?kind=all")
    assert stats_response.status_code == 200
    stats = stats_response.json()
    assert stats["totals"]["income"] == "5000.00"
    assert stats["totals"]["expense"] == "600.00"
    assert stats["totals"]["balance"] == "4400.00"
    assert any(c["category"] == "E2E категория" for c in stats["by_category"])

    # 9. Удаление операции
    delete_response = client.post(
        f"/operations/{income_id}/delete", follow_redirects=False
    )
    assert delete_response.status_code == 302

    final_operations = client.get("/api/operations").json()
    assert not any(o["id"] == income_id for o in final_operations)
