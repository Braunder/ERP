"""Тесты синхронизации с Google Sheets."""
from unittest.mock import MagicMock

from app.config import settings
from app.models import SyncLog


def _make_mock_gspread():
    worksheet = MagicMock()
    worksheet.title = "Операции"
    worksheet.clear = MagicMock()
    worksheet.update = MagicMock()
    worksheet.format = MagicMock()

    spreadsheet = MagicMock()
    spreadsheet.worksheet = MagicMock(return_value=worksheet)

    client = MagicMock()
    client.open_by_key = MagicMock(return_value=spreadsheet)

    gspread_module = MagicMock()
    gspread_module.service_account = MagicMock(return_value=client)
    gspread_module.exceptions.WorksheetNotFound = Exception
    return gspread_module


def test_sync_page_requires_auth(client):
    response = client.get("/sync", follow_redirects=False)
    assert response.status_code == 302


def test_sync_page(client):
    client.post("/login", data={"password": "admin"})
    response = client.get("/sync")
    assert response.status_code == 200
    assert "Синхронизация" in response.text


def test_sync_now_without_spreadsheet_id(client, monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_SPREADSHEET_ID", "")
    client.post("/login", data={"password": "admin"})

    response = client.post("/sync/now")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False
    assert "GOOGLE_SPREADSHEET_ID" in data["error"]


def test_sync_now_success(client, monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_SPREADSHEET_ID", "test_spreadsheet_id")
    monkeypatch.setattr("app.services.sheets.gspread", _make_mock_gspread())

    client.post("/login", data={"password": "admin"})

    category_response = client.post(
        "/api/categories", json={"name": "Тест синхронизации", "kind": "income"}
    )
    category_id = category_response.json()["id"]

    client.post(
        "/api/operations",
        json={
            "date": "2024-02-01",
            "kind": "income",
            "category_id": category_id,
            "amount": "500.00",
            "payment_method": "card",
        },
    )

    response = client.post("/sync/now")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["synced"] > 0

    logs_response = client.get("/api/sync/logs")
    assert logs_response.status_code == 200
    logs = logs_response.json()
    assert len(logs) >= 1
    assert logs[0]["success"] is True
    assert logs[0]["records_count"] > 0
