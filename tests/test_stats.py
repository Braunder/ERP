"""Тесты API статистики и графиков."""


def _find_category(client, kind, name):
    response = client.get(f"/api/categories?kind={kind}")
    assert response.status_code == 200
    for category in response.json():
        if category["name"] == name:
            return category["id"]
    raise AssertionError(f"Категория {name!r} не найдена")


def test_stats_page_requires_auth(client):
    response = client.get("/stats", follow_redirects=False)
    assert response.status_code == 302


def test_stats_page(client):
    client.post("/login", data={"password": "admin"})
    response = client.get("/stats")
    assert response.status_code == 200
    assert "Графики" in response.text


def test_api_stats_data_structure(client):
    client.post("/login", data={"password": "admin"})

    category_response = client.post(
        "/api/categories", json={"name": "Тест доход", "kind": "income"}
    )
    category_id = category_response.json()["id"]

    client.post(
        "/api/operations",
        json={
            "date": "2024-01-15",
            "kind": "income",
            "category_id": category_id,
            "amount": "250.00",
            "payment_method": "cash",
        },
    )

    response = client.get("/api/stats/data?kind=all")
    assert response.status_code == 200
    data = response.json()

    assert "totals" in data
    assert "by_period" in data
    assert "by_category" in data
    assert "by_payment" in data

    assert data["totals"]["income"] == "250.00"
    assert data["totals"]["expense"] == "0.00"
    assert data["totals"]["balance"] == "250.00"

    assert len(data["by_category"]) == 1
    assert data["by_category"][0]["category"] == "Тест доход"
    assert data["by_category"][0]["kind"] == "income"
    assert data["by_category"][0]["amount"] == "250.00"

    assert len(data["by_payment"]) == 1
    assert data["by_payment"][0]["payment_method"] == "cash"
    assert data["by_payment"][0]["label"] == "Нал"
    assert data["by_payment"][0]["amount"] == "250.00"


def test_api_stats_filters(client):
    client.post("/login", data={"password": "admin"})
    response = client.get("/api/stats/filters")
    assert response.status_code == 200
    data = response.json()
    assert "categories" in data
    assert "payment_methods" in data
    assert any(pm["value"] == "cash" and pm["label"] == "Нал" for pm in data["payment_methods"])
