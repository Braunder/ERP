"""Тесты синхронизации с Google Sheets."""
import time
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

from app.config import settings
from app.models import Investment, SyncLog
from app.services.report import WRITEOFFS_HEADERS
from app.services.sheets import (
    INVESTMENTS_COLUMN_WIDTHS_PX,
    OPERATIONS_COLUMN_WIDTHS_PX,
    REPORT_ROW_HEIGHTS_PX,
    WRITEOFFS_COLUMN_WIDTHS_PX,
    _ensure_writeoffs_sheet,
    _format_data_sheet,
    _format_report_sheet,
)


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


def test_sync_default_schedule_is_hourly():
    assert settings.SYNC_SCHEDULE == "0 * * * *"


def test_scheduler_cron_triggers_use_moscow_timezone():
    from app.services.scheduler import _cron_trigger

    assert _cron_trigger(settings.SYNC_SCHEDULE).timezone.key == "Europe/Moscow"
    assert _cron_trigger(settings.BACKUP_SCHEDULE).timezone.key == "Europe/Moscow"


def test_sync_exports_operations_sheet(client, monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_SPREADSHEET_ID", "test_spreadsheet_id")
    mock_gspread = _make_mock_gspread()
    monkeypatch.setattr("app.services.sheets.gspread", mock_gspread)

    client.post("/login", data={"password": "admin"})
    category_response = client.post(
        "/api/categories",
        json={"name": "Операции синхронизация", "kind": "expense"},
    )
    category_id = category_response.json()["id"]
    client.post(
        "/api/operations",
        json={
            "date": "2024-04-01",
            "kind": "expense",
            "category_id": category_id,
            "amount": "123.45",
            "comment": "Синхро",
        },
    )

    from app.services.sheets import sync_operations_to_sheets
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        db.add(
            Investment(
                date=date(2024, 4, 2),
                amount=Decimal("50.00"),
                comment="Инвестиция для синхронизации",
            )
        )
        db.commit()
        result = sync_operations_to_sheets(db)
    finally:
        db.close()

    assert result["operations_rows"] >= 1
    assert result["synced"] >= 1
    assert result["investments_rows"] == 1
    assert result["investments_synced"] is True
    updates = mock_gspread.service_account.return_value.open_by_key.return_value.worksheet.return_value.update.call_args_list
    assert any(
        len(call.args[0]) >= 2 and call.args[0][0] == ["Дата", "Сумма", "Комментарий"]
        and call.args[0][1][2] == "Инвестиция для синхронизации"
        for call in updates
    )
    batch_updates = (
        mock_gspread.service_account.return_value.open_by_key.return_value
        .worksheet.return_value.spreadsheet.batch_update.call_args_list
    )
    dark_green_headers = {
        request["repeatCell"]["range"]["endColumnIndex"]
        for call in batch_updates
        for request in call.args[0]["requests"]
        if "repeatCell" in request
        and request["repeatCell"]["range"]["startRowIndex"] == 0
        and request["repeatCell"]["range"]["endRowIndex"] == 1
        and request["repeatCell"]["cell"]["userEnteredFormat"].get(
            "backgroundColor"
        )
        == {"red": 27 / 255, "green": 57 / 255, "blue": 44 / 255}
    }
    assert {3, 14} <= dark_green_headers


def test_sync_creates_writeoffs_sheet(client, monkeypatch):
    """Лист «Списания» создаётся при отсутствии и заполняется заголовками."""
    monkeypatch.setattr(settings, "GOOGLE_SPREADSHEET_ID", "test_spreadsheet_id")
    mock_gspread = _make_mock_gspread()
    monkeypatch.setattr("app.services.sheets.gspread", mock_gspread)

    spreadsheet = mock_gspread.service_account.return_value.open_by_key.return_value
    data_worksheet = spreadsheet.worksheet.return_value

    def _worksheet(title):
        if title == "Списания":
            raise mock_gspread.exceptions.WorksheetNotFound(title)
        return data_worksheet

    spreadsheet.worksheet = MagicMock(side_effect=_worksheet)
    writeoffs_worksheet = MagicMock()
    spreadsheet.add_worksheet = MagicMock(return_value=writeoffs_worksheet)

    client.post("/login", data={"password": "admin"})

    from app.services.sheets import sync_operations_to_sheets
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        result = sync_operations_to_sheets(db)
    finally:
        db.close()

    assert result["writeoffs_sheet_title"] == "Списания"
    assert result["writeoffs_status"] == "created"
    spreadsheet.add_worksheet.assert_any_call(
        title="Списания", rows="1000", cols=str(len(WRITEOFFS_HEADERS))
    )
    written_headers = writeoffs_worksheet.update.call_args.args[0][0]
    assert written_headers == WRITEOFFS_HEADERS


def test_sync_keeps_existing_writeoffs_sheet(client, monkeypatch):
    """Данные списаний ведёт заказчик: существующий лист не перетирается."""
    monkeypatch.setattr(settings, "GOOGLE_SPREADSHEET_ID", "test_spreadsheet_id")
    mock_gspread = _make_mock_gspread()
    monkeypatch.setattr("app.services.sheets.gspread", mock_gspread)

    spreadsheet = mock_gspread.service_account.return_value.open_by_key.return_value
    data_worksheet = spreadsheet.worksheet.return_value
    data_worksheet.get_values = MagicMock(
        return_value=[
            WRITEOFFS_HEADERS,
            ["19.07.2026", "Съели сами/взяли себе", "Сидр Top Hat", 4, "бут.",
             "", "", "", "", "2026-07"],
        ]
    )

    client.post("/login", data={"password": "admin"})

    from app.services.sheets import sync_operations_to_sheets
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        result = sync_operations_to_sheets(db)
    finally:
        db.close()

    assert result["writeoffs_status"] == "kept"
    spreadsheet.add_worksheet.assert_not_called()
    # Ни один update не пытался перезаписать строку заголовков «Списаний».
    written_first_rows = [
        call.args[0][0]
        for call in data_worksheet.update.call_args_list
        if call.args and isinstance(call.args[0][0], list)
    ]
    assert WRITEOFFS_HEADERS not in written_first_rows


def test_data_sheet_formatting_matches_sample_and_covers_dynamic_rows():
    worksheet = MagicMock()
    worksheet.id = 42
    worksheet.row_count = 1000
    worksheet.col_count = 14

    _format_data_sheet(
        worksheet,
        column_count=14,
        populated_rows=1200,
        column_widths=OPERATIONS_COLUMN_WIDTHS_PX,
    )

    worksheet.resize.assert_called_once_with(rows=1400, cols=14)
    requests = worksheet.spreadsheet.batch_update.call_args.args[0]["requests"]
    assert len(requests) == 9

    header = requests[0]["repeatCell"]
    assert header["range"] == {
        "sheetId": 42,
        "startRowIndex": 0,
        "endRowIndex": 1,
        "startColumnIndex": 0,
        "endColumnIndex": 14,
    }
    header_format = header["cell"]["userEnteredFormat"]
    assert header_format["backgroundColor"] == {
        "red": 27 / 255,
        "green": 57 / 255,
        "blue": 44 / 255,
    }
    assert header_format["textFormat"] == {
        "fontFamily": "Carlito",
        "fontSize": 11,
        "bold": True,
        "foregroundColor": {"red": 1, "green": 1, "blue": 1},
    }

    body = requests[1]["repeatCell"]
    assert body["range"]["startRowIndex"] == 1
    assert body["range"]["endRowIndex"] == 1400
    assert body["range"]["endColumnIndex"] == 14
    assert body["cell"]["userEnteredFormat"] == {
        "backgroundColor": {"red": 1, "green": 1, "blue": 1},
        "textFormat": {"fontFamily": "Carlito", "fontSize": 11},
    }
    assert requests[2]["updateDimensionProperties"]["properties"] == {
        "pixelSize": 33
    }
    assert requests[3]["updateDimensionProperties"]["properties"] == {
        "pixelSize": 17
    }
    column_width_requests = [
        request["updateDimensionProperties"]
        for request in requests[4:]
    ]
    assert [
        (
            request["range"]["startIndex"],
            request["range"]["endIndex"],
            request["properties"]["pixelSize"],
        )
        for request in column_width_requests
    ] == [(0, 1, 71), (1, 2, 119), (2, 6, 159), (6, 7, 383), (7, 14, 68)]


def test_report_column_widths_match_sample():
    worksheet = MagicMock()
    worksheet.id = 42

    _format_report_sheet(
        worksheet,
        MagicMock(),
        [["Отчет", "ИТОГО"] for _ in range(61)],
    )

    requests = worksheet.spreadsheet.batch_update.call_args.args[0]["requests"]
    title_style = requests[0]["repeatCell"]["cell"]["userEnteredFormat"]
    assert title_style["backgroundColor"] == {
        "red": 23 / 255,
        "green": 53 / 255,
        "blue": 40 / 255,
    }
    assert title_style["textFormat"] == {
        "fontFamily": "Carlito",
        "bold": True,
        "fontSize": 16,
        "foregroundColor": {"red": 1, "green": 1, "blue": 1},
    }
    header_style = requests[2]["repeatCell"]["cell"]["userEnteredFormat"]
    assert header_style["backgroundColor"] == {
        "red": 33 / 255,
        "green": 115 / 255,
        "blue": 75 / 255,
    }
    assert header_style["textFormat"]["bold"] is True
    profit_style = next(
        request["repeatCell"]["cell"]["userEnteredFormat"]
        for request in requests
        if request.get("repeatCell", {}).get("range", {}).get("startRowIndex") == 40
    )
    assert profit_style["backgroundColor"] == {
        "red": 180 / 255,
        "green": 218 / 255,
        "blue": 193 / 255,
    }

    widths = [
        request["updateDimensionProperties"]
        for request in requests
        if request.get("updateDimensionProperties", {}).get("range", {}).get(
            "dimension"
        ) == "COLUMNS"
    ]
    assert [
        (
            request["range"]["startIndex"],
            request["range"]["endIndex"],
            request["properties"]["pixelSize"],
        )
        for request in widths
    ] == [(0, 1, 463), (1, 2, 167)]

    heights = [
        request["updateDimensionProperties"]
        for request in requests
        if request.get("updateDimensionProperties", {}).get("range", {}).get(
            "dimension"
        ) == "ROWS"
    ]
    assert [
        (
            request["range"]["startIndex"],
            request["range"]["endIndex"],
            request["properties"]["pixelSize"],
        )
        for request in heights[:3]
    ] == [(0, 1, 45), (1, 2, 31), (2, 3, 35)]
    assert {
        request["properties"]["pixelSize"] for request in heights
    } == set(REPORT_ROW_HEIGHTS_PX.values())
    assert set(REPORT_ROW_HEIGHTS_PX.values()) == {17, 25, 31, 35, 37, 45}
    assert any(
        request["range"]["startIndex"] == 55
        and request["range"]["endIndex"] == 57
        and request["properties"]["pixelSize"] == 17
        for request in heights
    )


def test_investments_and_writeoffs_column_widths_match_samples():
    for column_widths in (
        INVESTMENTS_COLUMN_WIDTHS_PX,
        WRITEOFFS_COLUMN_WIDTHS_PX,
    ):
        worksheet = MagicMock()
        worksheet.id = 42
        worksheet.row_count = 1000
        worksheet.col_count = len(column_widths)

        _format_data_sheet(
            worksheet,
            column_count=len(column_widths),
            populated_rows=1,
            column_widths=column_widths,
            tail_rows=0,
        )

        requests = worksheet.spreadsheet.batch_update.call_args.args[0]["requests"]
        widths = [
            request["updateDimensionProperties"]
            for request in requests
            if request.get("updateDimensionProperties", {}).get("range", {}).get(
                "dimension"
            ) == "COLUMNS"
        ]
        assert [
            (
                request["range"]["startIndex"],
                request["range"]["endIndex"],
                request["properties"]["pixelSize"],
            )
            for request in widths
        ] == (
            [(0, 1, 119), (1, 2, 159), (2, 3, 543)]
            if column_widths == INVESTMENTS_COLUMN_WIDTHS_PX
            else [(0, 1, 135), (1, 10, 167)]
        )


def test_existing_writeoffs_are_formatted_without_writing_user_values(monkeypatch):
    worksheet = MagicMock()
    worksheet.id = 77
    worksheet.row_count = 1500
    worksheet.col_count = len(WRITEOFFS_HEADERS)
    worksheet.get_values.return_value = [
        WRITEOFFS_HEADERS,
        ["19.07.2026", "Съели сами", "Сидр", 4],
    ]
    spreadsheet = MagicMock()
    spreadsheet.worksheet.return_value = worksheet
    worksheet.spreadsheet = spreadsheet
    gspread_module = MagicMock()
    gspread_module.exceptions.WorksheetNotFound = Exception
    monkeypatch.setattr("app.services.sheets.gspread", gspread_module)

    status = _ensure_writeoffs_sheet(spreadsheet)

    assert status == "kept"
    worksheet.update.assert_not_called()
    worksheet.freeze.assert_not_called()
    requests = spreadsheet.batch_update.call_args.args[0]["requests"]
    assert len(requests) == 6
    assert requests[0]["repeatCell"]["range"]["endColumnIndex"] == len(
        WRITEOFFS_HEADERS
    )
    assert requests[1]["repeatCell"]["range"]["endRowIndex"] == 1500


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
    assert response.status_code == 202
    data = response.json()
    assert data["success"] is True

    status_data = None
    for _ in range(20):
        status_response = client.get(f"/api/sync/status/{data['job_id']}")
        status_data = status_response.json()
        if status_data["status"] in {"success", "error"}:
            break
        time.sleep(0.01)

    assert status_data["status"] == "success"
    assert status_data["synced"] > 0

    logs_response = client.get("/api/sync/logs")
    assert logs_response.status_code == 200
    logs = logs_response.json()
    assert len(logs) >= 1
    assert logs[0]["success"] is True
    assert logs[0]["records_count"] > 0
