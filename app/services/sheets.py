"""Сервис синхронизации операций с Google Sheets в формате отчёта P&L."""
import json
import logging
from pathlib import Path

import gspread
from sqlalchemy.orm import Session, joinedload

from app.config import BASE_DIR, settings
from app.models import Category, Operation, SyncLog
from app.services.report import ReportRow, build_report, report_to_matrix

logger = logging.getLogger(__name__)

PAYMENT_METHOD_LABELS = {
    "cash": "Нал",
    "card": "Б/нал",
    "transfer": "Перевод",
}

REPORT_SHEET_TITLE = "Отчет"
OPERATIONS_SHEET_TITLE = "Операции"


def _safe_iso(value, timespec: str | None = None) -> str:
    """Безопасно сериализует date/datetime, не ломая выгрузку из-за NULL."""
    if value is None:
        return ""
    if timespec is not None and hasattr(value, "isoformat"):
        return value.isoformat(timespec=timespec)
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def get_gsheets_client() -> gspread.Client:
    """Авторизация в Google Sheets через сервисный аккаунт.

    Поддерживает два способа передать ключ сервисного аккаунта:

    1. ``GOOGLE_SA_JSON`` — содержимое JSON-ключа целиком в переменной
       окружения. Так делают на Railway и других PaaS, где нельзя
       закоммитить секретный файл в репозиторий: значение переменной
       вставляется прямо в дашборде из скачанного JSON-файла сервисного
       аккаунта. Имеет приоритет над ``GOOGLE_SA_FILE``, если задано.
    2. ``GOOGLE_SA_FILE`` — путь к JSON-файлу на диске. Используется для
       локальной разработки, где файл ключа лежит рядом с проектом.
    """
    if settings.GOOGLE_SA_JSON:
        try:
            info = json.loads(settings.GOOGLE_SA_JSON)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "Переменная окружения GOOGLE_SA_JSON содержит невалидный JSON. "
                "Скопируйте содержимое скачанного файла сервисного аккаунта "
                "целиком, без изменений и лишних кавычек."
            ) from exc
        return gspread.service_account_from_dict(info)

    sa_path = Path(settings.GOOGLE_SA_FILE)
    if not sa_path.is_absolute():
        sa_path = BASE_DIR / sa_path
    if not sa_path.exists():
        raise RuntimeError(
            f"Файл сервисного аккаунта Google не найден: {sa_path}. "
            "На хостингах вроде Railway файл ключа недоступен на диске — "
            "задайте переменную окружения GOOGLE_SA_JSON с содержимым "
            "JSON-ключа сервисного аккаунта. Для локальной разработки "
            "убедитесь, что GOOGLE_SA_FILE указывает на существующий файл."
        )
    return gspread.service_account(filename=str(sa_path))


def log_sync_attempt(
    db: Session,
    success: bool,
    message: str,
    details: dict | None = None,
    records_count: int | None = None,
) -> None:
    """Сохраняет запись о попытке синхронизации."""
    db.add(
        SyncLog(
            success=success,
            message=message,
            details=details,
            records_count=records_count,
        )
    )
    db.commit()


def _get_or_create_worksheet(spreadsheet, title: str, rows: int = 1000, cols: int = 30):
    try:
        return spreadsheet.worksheet(title)
    except gspread.exceptions.WorksheetNotFound:
        return spreadsheet.add_worksheet(title=title, rows=str(rows), cols=str(cols))


def _col_letter(col: int) -> str:
    """Числовой индекс столбца (1-based) в буквенный (A, B, ..., Z, AA)."""
    result = ""
    while col > 0:
        col, rem = divmod(col - 1, 26)
        result = chr(65 + rem) + result
    return result


def _format_report_sheet(worksheet, report, matrix: list[list]) -> None:
    """Применяет форматирование к листу отчёта."""
    months = report.months
    num_months = len(months)
    num_data_rows = len(matrix)

    # 1. Объединить ячейки заголовков месяцев (первая строка)
    # Структура: A1 пустая, B1=месяц1, C1 пустая, D1=месяц2, E1 пустая, ...
    for i, _ in enumerate(months):
        start_col = 2 + i * 2
        end_col = start_col + 1
        try:
            worksheet.merge_cells(1, start_col, 1, end_col)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Не удалось объединить ячейки заголовка: %s", exc)

    # 2. Форматирование заголовков (первая и вторая строки)
    last_col = 1 + num_months * 2
    header_range = f"A1:{_col_letter(last_col)}2"
    try:
        worksheet.format(
            header_range,
            {
                "textFormat": {"bold": True},
                "backgroundColor": {"red": 0.85, "green": 0.85, "blue": 0.85},
                "horizontalAlignment": "CENTER",
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Не удалось применить форматирование заголовков: %s", exc)

    # 3. Числовые форматы для столбцов сумм и процентов
    sum_cols = [2 + i * 2 for i in range(num_months)]
    pct_cols = [3 + i * 2 for i in range(num_months)]

    for col in sum_cols:
        col_letter = _col_letter(col)
        try:
            worksheet.format(
                f"{col_letter}3:{col_letter}{num_data_rows}",
                {"numberFormat": {"type": "NUMBER", "pattern": "#,##0.00 ₽"}},
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Не удалось задать формат валюты: %s", exc)

    for col in pct_cols:
        col_letter = _col_letter(col)
        try:
            worksheet.format(
                f"{col_letter}3:{col_letter}{num_data_rows}",
                {"numberFormat": {"type": "PERCENT", "pattern": "0.00%"}},
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Не удалось задать формат процента: %s", exc)

    # 4. Форматирование строк отчёта (жирный, фон)
    flat_rows: list[tuple[int, ReportRow]] = []

    def _collect_rows(row: ReportRow, current_idx: int) -> int:
        flat_rows.append((current_idx, row))
        current_idx += 1
        for sub in row.subrows:
            flat_rows.append((current_idx, sub))
            current_idx += 1
        return current_idx

    current = 3
    for row in report.rows:
        current = _collect_rows(row, current)

    for row_idx, row in flat_rows:
        # Форматируем всю строку до конца месяцев (колонка B + пары сумма/%)
        row_end_col = _col_letter(last_col)
        range_full = f"A{row_idx}:{row_end_col}{row_idx}"
        try:
            fmt: dict = {"textFormat": {"bold": row.bold}}
            if row.background == "yellow":
                fmt["backgroundColor"] = {"red": 1.0, "green": 0.95, "blue": 0.8}
            elif row.background == "blue":
                fmt["backgroundColor"] = {"red": 0.85, "green": 0.92, "blue": 1.0}
            elif row.background == "green":
                fmt["backgroundColor"] = {"red": 0.85, "green": 1.0, "blue": 0.85}

            worksheet.format(range_full, fmt)

            if row.section in {"direct", "overhead"} and row.level >= 2:
                worksheet.format(f"A{row_idx}:{row_end_col}{row_idx}", {"textFormat": {"italic": True}})
        except Exception as exc:  # noqa: BLE001
            logger.warning("Не удалось применить форматирование строки %s: %s", row_idx, exc)

    # 5. Ширина столбцов
    try:
        worksheet.columns_auto_resize(1, last_col)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Не удалось автоматически изменить ширину столбцов: %s", exc)


def _build_operations_matrix(db: Session) -> list[list[object]]:
    """Возвращает матрицу для листа с полным перечнем операций."""
    operations = (
        db.query(Operation)
        .options(
            joinedload(Operation.category).joinedload(Category.parent),
            joinedload(Operation.supplier),
            joinedload(Operation.employee),
        )
        .order_by(Operation.date.desc(), Operation.id.desc())
        .all()
    )

    headers = [
        "ID",
        "Дата",
        "Тип",
        "Категория",
        "Родительская категория",
        "Сумма",
        "Комментарий",
        "Гостей",
        "Способ оплаты",
        "Поставщик",
        "Сотрудник",
        "Ответственный",
        "Создана",
        "Обновлена",
    ]
    rows: list[list[object]] = [headers]

    for operation in operations:
        category_name = operation.category.name if operation.category else ""
        parent_name = operation.category.parent.name if operation.category and operation.category.parent else ""
        rows.append(
            [
                str(operation.id),
                _safe_iso(operation.date),
                "Доход" if operation.kind == "income" else "Расход",
                category_name,
                parent_name,
                float(operation.amount or 0),
                operation.comment or "",
                str(operation.guests_count) if operation.guests_count is not None else "",
                PAYMENT_METHOD_LABELS.get(operation.payment_method, operation.payment_method or ""),
                operation.supplier.name if operation.supplier else "",
                operation.employee.name if operation.employee else "",
                operation.responsible or "",
                _safe_iso(operation.created_at, timespec="seconds"),
                _safe_iso(operation.updated_at, timespec="seconds"),
            ]
        )

    # Добавляем строку фильтра в первую строку: Google Sheets покажет
    # фильтр для данных, начиная со второй строки заголовка.
    filter_row = ["" for _ in range(len(headers))]
    if rows:
        rows.insert(1, filter_row)

    return rows


def sync_operations_to_sheets(db: Session, spreadsheet_id: str | None = None) -> dict:
    """Выгружает P&L и полный список операций в Google Sheets.

    Две выгрузки независимы: ошибка P&L не блокирует лист «Операции»
    и наоборот. Если одна из них завершилась ошибкой, исключение
    поднимается после попытки второй выгрузки, чтобы вызывающий код
    корректно показал неуспешную синхронизацию.
    """
    spreadsheet_id = spreadsheet_id or settings.GOOGLE_SPREADSHEET_ID
    if not spreadsheet_id:
        raise ValueError("GOOGLE_SPREADSHEET_ID не настроен")

    client = get_gsheets_client()
    spreadsheet = client.open_by_key(spreadsheet_id)

    # Сначала полностью строим обе матрицы в памяти. Если проблема в БД
    # или данных одной выгрузки, вторая всё равно сможет быть отправлена.
    report = None
    report_matrix = None
    operations_matrix = None
    errors: list[str] = []

    try:
        report = build_report(db)
        report_matrix = report_to_matrix(report)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Не удалось построить отчёт P&L")
        errors.append(f"Отчёт P&L: {exc}")

    try:
        operations_matrix = _build_operations_matrix(db)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Не удалось построить выгрузку операций")
        errors.append(f"Операции: {exc}")

    report_synced = False
    operations_synced = False

    # Записываем отчёт независимо от результата подготовки операций.
    if report is not None and report_matrix is not None:
        try:
            report_worksheet = _get_or_create_worksheet(
                spreadsheet, REPORT_SHEET_TITLE
            )
            report_worksheet.clear()
            report_worksheet.update(report_matrix, value_input_option="USER_ENTERED")
            _format_report_sheet(report_worksheet, report, report_matrix)
            report_synced = True
        except gspread.exceptions.APIError as exc:
            logger.exception("Ошибка Google Sheets API при записи отчёта")
            errors.append(f"Отчёт P&L: ошибка Google Sheets API: {exc}")
        except Exception as exc:  # noqa: BLE001
            logger.exception("Ошибка при записи отчёта P&L")
            errors.append(f"Отчёт P&L: {exc}")

    # Операции записываем независимо от результата отчёта.
    if operations_matrix is not None:
        try:
            operations_worksheet = _get_or_create_worksheet(
                spreadsheet, OPERATIONS_SHEET_TITLE
            )

            # Старый фильтр может мешать повторному set_basic_filter.
            try:
                operations_worksheet.clear_basic_filter()
            except Exception:  # noqa: BLE001
                pass

            operations_worksheet.clear()
            operations_worksheet.update(
                operations_matrix,
                value_input_option="USER_ENTERED",
            )
            operations_worksheet.freeze(rows=2)
            operations_worksheet.set_basic_filter()
            operations_synced = True
        except gspread.exceptions.APIError as exc:
            logger.exception("Ошибка Google Sheets API при записи операций")
            errors.append(f"Операции: ошибка Google Sheets API: {exc}")
        except Exception as exc:  # noqa: BLE001
            logger.exception("Ошибка при записи операций")
            errors.append(f"Операции: {exc}")

    operations_count = 0
    if operations_matrix is not None:
        # Заголовок + пустая строка фильтра не являются операциями.
        operations_count = max(0, len(operations_matrix) - 2)

    result = {
        "synced": operations_count if operations_synced else 0,
        "report_rows": max(0, len(report_matrix) - 2) if report_matrix is not None else 0,
        "operations_rows": operations_count if operations_synced else 0,
        "spreadsheet_id": spreadsheet_id,
        "sheet_title": REPORT_SHEET_TITLE,
        "operations_sheet_title": OPERATIONS_SHEET_TITLE,
        "months": report.months if report is not None else [],
        "report_synced": report_synced,
        "operations_synced": operations_synced,
        "errors": errors,
    }

    if errors:
        raise RuntimeError("Синхронизация завершена с ошибками: " + " | ".join(errors))

    return result