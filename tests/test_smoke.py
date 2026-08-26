"""Дымовые тесты основных сценариев."""

import re


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["database"] == "ok"


def test_operations_redirects_when_unauthorized(client):
    response = client.get("/operations", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/login"


def test_login_and_operations(client):
    response = client.post("/login", data={"password": "admin"}, follow_redirects=False)
    assert response.status_code == 302
    assert "session" in response.cookies

    response = client.get("/operations")
    assert response.status_code == 200
    assert "Операции" in response.text


def test_api_create_category(client):
    client.post("/login", data={"password": "admin"})

    response = client.post("/api/categories", json={"name": "Тест", "kind": "expense"})
    assert response.status_code in (200, 201)

    data = response.json()
    assert data["name"] == "Тест"
    assert data["kind"] == "expense"


def test_api_create_operation(client):
    client.post("/login", data={"password": "admin"})

    category_response = client.post(
        "/api/categories", json={"name": "Тест операции", "kind": "income"}
    )
    category_id = category_response.json()["id"]

    response = client.post(
        "/api/operations",
        json={
            "date": "2024-01-01",
            "kind": "income",
            "category_id": category_id,
            "amount": "100.00",
            "comment": "тестовая операция",
        },
    )
    assert response.status_code == 201

    data = response.json()
    assert data["amount"] == "100.00"
    assert data["comment"] == "тестовая операция"
    assert data["category_id"] == category_id


def _find_category(client, kind, name):
    response = client.get(f"/api/categories?kind={kind}")
    assert response.status_code == 200
    for category in response.json():
        if category["name"] == name:
            return category["id"]
    raise AssertionError(f"Категория {name!r} не найдена")


def test_create_income_operation_lavka(client):
    client.post("/login", data={"password": "admin"})

    category_id = _find_category(client, "income", "Лавка")

    response = client.post(
        "/operations",
        data={
            "date": "2024-06-15",
            "kind": "income",
            "category_id": category_id,
            "amount": "1500.00",
            "comment": "Лавка вечер",
            "guests_count": "5",
            "payment_method": "cash",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["location"] == "/operations"

    list_response = client.get("/operations")
    assert list_response.status_code == 200
    assert "Лавка" in list_response.text
    assert "1500,00" in list_response.text or "1500.00" in list_response.text


def test_create_expense_operation_with_products(client):
    client.post("/login", data={"password": "admin"})

    parent_id = _find_category(client, "expense", "Закупка продуктов")
    child_id = _find_category(client, "expense", "Мясо и рыба")

    supplier_response = client.post("/api/suppliers", json={"name": "Поставщик тест"})
    supplier_id = supplier_response.json()["id"]

    product_1 = client.post("/api/products", json={"name": "Сёмга", "unit": "кг"}).json()["id"]
    product_2 = client.post("/api/products", json={"name": "Говядина", "unit": "кг"}).json()["id"]

    response = client.post(
        "/operations",
        data={
            "date": "2024-06-15",
            "kind": "expense",
            "category_id": child_id,
            "amount": "0",
            "comment": "Закупка мяса и рыбы",
            "supplier_id": supplier_id,
            "items[0][product_id]": product_1,
            "items[0][name]": "Сёмга",
            "items[0][price]": "800.00",
            "items[0][quantity]": "2",
            "items[0][unit]": "кг",
            "items[1][product_id]": product_2,
            "items[1][name]": "Говядина",
            "items[1][price]": "1200.00",
            "items[1][quantity]": "1.5",
            "items[1][unit]": "кг",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["location"] == "/operations"

    detail = client.get("/api/operations").json()
    op = next((o for o in detail if o["category_id"] == child_id), None)
    assert op is not None
    assert op["amount"] == "3400.00"
    assert len(op["items"]) == 2


def test_report_group_dropdown_is_deduplicated_and_clear(client):
    client.post("/login", data={"password": "admin"})

    client.post("/report-groups", data={"name": "Дублирующаяся группа", "section": "direct", "sort_order": "10"})
    duplicate_response = client.post(
        "/report-groups",
        data={"name": "Дублирующаяся группа", "section": "direct", "sort_order": "11"},
        follow_redirects=False,
    )
    assert duplicate_response.status_code == 400

    groups_response = client.get("/api/report-groups")
    assert groups_response.status_code == 200
    matching_groups = [group for group in groups_response.json() if group["name"] == "Дублирующаяся группа"]
    assert len(matching_groups) == 1
    assert matching_groups[0]["section"] == "direct"

    page_response = client.get("/categories")
    assert page_response.status_code == 200
    assert "Дублирующаяся группа (Прямые расходы)" in page_response.text
    assert "Прямые расходы" in page_response.text


def test_edit_and_delete_operation(client):
    client.post("/login", data={"password": "admin"})

    category_id = _find_category(client, "income", "Открытые события")

    create_response = client.post(
        "/operations",
        data={
            "date": "2024-06-15",
            "kind": "income",
            "category_id": category_id,
            "amount": "500.00",
            "comment": "Старый коммент",
            "guests_count": "10",
            "payment_method": "card",
        },
        follow_redirects=False,
    )
    assert create_response.status_code == 302

    operations = client.get("/api/operations").json()
    op = next((o for o in operations if o["comment"] == "Старый коммент"), None)
    assert op is not None

    edit_response = client.post(
        f"/operations/{op['id']}",
        data={
            "date": "2024-06-15",
            "kind": "income",
            "category_id": category_id,
            "amount": "750.00",
            "comment": "Новый коммент",
            "guests_count": "10",
            "payment_method": "card",
        },
        follow_redirects=False,
    )
    assert edit_response.status_code == 302

    updated = client.get(f"/api/operations").json()
    updated_op = next((o for o in updated if o["id"] == op["id"]), None)
    assert updated_op["amount"] == "750.00"
    assert updated_op["comment"] == "Новый коммент"

    delete_response = client.post(
        f"/operations/{op['id']}/delete", follow_redirects=False
    )
    assert delete_response.status_code == 302

    final = client.get("/api/operations").json()
    assert not any(o["id"] == op["id"] for o in final)
