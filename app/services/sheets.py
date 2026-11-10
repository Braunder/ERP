"""Сервис синхронизации операций с Google Sheets в формате отчёта P&L."""
import json
import logging
import time
from pathlib import Path

import gspread
from sqlalchemy.orm import Session, joinedload

from app.config import BASE_DIR, settings
from app.models import Category, Investment, Operation, SyncLog
from app.services.report import (
    COLUMN_WIDTHS,
    DATA_RANGE_LAST_ROW,
    DATE_NUMBER_FORMAT,
    DATE_FORMAT_TAIL_ROWS,
    FREEZE_COLUMNS,
    FREEZE_ROWS,
    INVESTMENTS_SHEET_TITLE,
    MONEY_NUMBER_FORMAT,
    MONTH_NUMBER_FORMAT,
    OPERATIONS_SHEET_TITLE,
    REPORT_SHEET_TITLE,
    STYLE_PALETTE,
    WRITEOFFS_HEADERS,
    WRITEOFFS_SHEET_TITLE,
    ReportData,
    build_report,
    report_layout,
    report_to_matrix,
)

logger = logging.getLogger(__name__)

PAYMENT_METHOD_LABELS = {
    "cash": "Нал",
    "card": "Б/нал",
    "transfer": "Перевод",
}



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



def _retry_google_request(action, *, attempts: int = 5):
    """Повторяет временные ошибки квоты/сервера Google с экспоненциальной паузой."""
    for attempt in range(attempts):
        try:
            return action()
        except gspread.exceptions.APIError as exc:
            response = getattr(exc, "response", None)
            status = getattr(response, "status_code", None)
            if status not in {429, 500, 502, 503, 504} or attempt == attempts - 1:
                raise
            delay = min(2 ** attempt, 16)
            logger.warning("Google Sheets API вернул %s; повтор через %s сек. (%s/%s)", status, delay, attempt + 1, attempts)
            time.sleep(delay)


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


def _rgb(hex_color: str) -> dict:
    """Шестнадцатеричный RGB (без alpha) в цвет Google Sheets API."""
    return {
        "red": int(hex_color[0:2], 16) / 255,
        "green": int(hex_color[2:4], 16) / 255,
        "blue": int(hex_color[4:6], 16) / 255,
    }


# Стили эталонного листа «Отчет»: палитра report.py в запросы Google Sheets API.
def _style_requests(sheet_id: int, style: str, start: int, end: int, last_col: int) -> list[dict]:
    """Запросы оформления строк [start, end) в стиле эталона."""
    spec = STYLE_PALETTE.get(style, {})
    text_format: dict = {"fontFamily": "Carlito"}
    fields = ["userEnteredFormat.textFormat.fontFamily"]

    if "bold" in spec:
        text_format["bold"] = spec["bold"]
        fields.append("userEnteredFormat.textFormat.bold")
    if "font_size" in spec:
        text_format["fontSize"] = spec["font_size"]
        fields.append("userEnteredFormat.textFormat.fontSize")
    if "font_color" in spec:
        text_format["foregroundColor"] = _rgb(spec["font_color"])
        fields.append("userEnteredFormat.textFormat.foregroundColor")

    user_format: dict = {"textFormat": text_format}
    if "background" in spec:
        user_format["backgroundColor"] = _rgb(spec["background"])
        fields.append("userEnteredFormat.backgroundColor")

    return [{
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": start,
                "endRowIndex": end,
                "startColumnIndex": 0,
                "endColumnIndex": last_col,
            },
            "cell": {"userEnteredFormat": user_format},
            "fields": ",".join(fields),
        }
    }]


def _format_report_sheet(worksheet, report: ReportData, matrix: list[list]) -> None:
    """Оформляет лист «Отчет» по эталону: палитра, высоты, ширины, freeze B10.

    Объединения ячеек и автофильтр не ставятся — в эталоне их нет, а
    один столбец на месяц в них не нуждается.
    """
    if not matrix:
        return

    last_col = max(len(row) for row in matrix)
    num_rows = min(len(matrix), len(report_layout()))
    sheet_id = worksheet.id
    requests: list[dict] = []
    layout = report_layout()

    # 1. Оформление строк: подряд идущие строки одного стиля — одним запросом.
    idx = 0
    while idx < num_rows:
        style = layout[idx]["style"]
        end = idx + 1
        while end < num_rows and layout[end]["style"] == style:
            end += 1
        requests.extend(_style_requests(sheet_id, style, idx, end, last_col))
        idx = end

    # 2. Денежный формат месяцев и итога; заголовки месяцев — формат даты.
    money_start = None
    for i in range(num_rows + 1):
        money = i < num_rows and layout[i]["money"]
        if money and money_start is None:
            money_start = i
        elif not money and money_start is not None:
            requests.append({
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": money_start,
                        "endRowIndex": i,
                        "startColumnIndex": 1,
                        "endColumnIndex": last_col,
                    },
                    "cell": {"userEnteredFormat": {"numberFormat": {
                        "type": "NUMBER",
                        "pattern": MONEY_NUMBER_FORMAT,
                    }}},
                    "fields": "userEnteredFormat.numberFormat",
                }
            })
            money_start = None

    if num_rows >= 3:
        requests.append({
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 2,
                    "endRowIndex": 3,
                    "startColumnIndex": 1,
                    "endColumnIndex": max(last_col - 1, 1),
                },
                "cell": {"userEnteredFormat": {"numberFormat": {
                    "type": "DATE",
                    "pattern": MONTH_NUMBER_FORMAT,
                }}},
                "fields": "userEnteredFormat.numberFormat",
            }
        })

    # 3. Высоты строк: Excel оперирует пунктами, Sheets — пикселями (1pt = 4/3 px).
    height_start = None
    for i in range(num_rows + 1):
        height = layout[i]["height"] if i < num_rows else None
        previous = layout[height_start]["height"] if height_start is not None else None
        if height_start is not None and height != previous:
            requests.append({
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": "ROWS",
                        "startIndex": height_start,
                        "endIndex": i,
                    },
                    "properties": {"pixelSize": round(previous * 4 / 3)},
                    "fields": "pixelSize",
                }
            })
            height_start = i if height is not None else None
        elif height_start is None and height is not None:
            height_start = i
        elif height is None and height_start is not None:
            height_start = None

    # 4. Закрепление области B10 и ширины столбцов A и B.
    requests.append({
        "updateSheetProperties": {
            "properties": {
                "sheetId": sheet_id,
                "gridProperties": {
                    "frozenRowCount": FREEZE_ROWS,
                    "frozenColumnCount": FREEZE_COLUMNS,
                },
            },
            "fields": "gridProperties.frozenRowCount,gridProperties.frozenColumnCount",
        }
    })

    for letter, width in COLUMN_WIDTHS.items():
        index = ord(letter) - 65
        requests.append({
            "updateDimensionProperties": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "COLUMNS",
                    "startIndex": index,
                    "endIndex": index + 1,
                },
                # Символьная ширина Excel ≈ 7 px на символ плюс поля ячейки.
                "properties": {"pixelSize": round(width * 7) + 5},
                "fields": "pixelSize",
            }
        })

    if requests:
        _retry_google_request(lambda: worksheet.spreadsheet.batch_update({"requests": requests}))


def _apply_date_format(worksheet, column_index: int, first_row: int, last_row: int) -> None:
    """Ставит формат dd.mm.yyyy на столбец дат листа данных."""
    if last_row < first_row:
        return
    _retry_google_request(lambda: worksheet.spreadsheet.batch_update({
        "requests": [{
            "repeatCell": {
                "range": {
                    "sheetId": worksheet.id,
                    "startRowIndex": first_row - 1,
                    "endRowIndex": last_row,
                    "startColumnIndex": column_index - 1,
                    "endColumnIndex": column_index,
                },
                "cell": {"userEnteredFormat": {"numberFormat": {
                    "type": "DATE",
                    "pattern": DATE_NUMBER_FORMAT,
                }}},
                "fields": "userEnteredFormat.numberFormat",
            }
        }]
    }))



def _write_matrix_chunked(worksheet, matrix: list[list], *, chunk_size: int = 400) -> None:
    """Расширяет лист при необходимости и пишет данные небольшими порциями."""
    if not matrix:
        return
    width = max((len(row) for row in matrix), default=1)
    # Листы создаются с запасом, но при превышении размера сетки расширяем их.
    current_rows = getattr(worksheet, "row_count", 0)
    current_cols = getattr(worksheet, "col_count", 0)
    target_rows = max(len(matrix), current_rows if isinstance(current_rows, int) else 0, 1)
    target_cols = max(width, current_cols if isinstance(current_cols, int) else 0, 1)
    if (not isinstance(current_rows, int) or target_rows > current_rows or
            not isinstance(current_cols, int) or target_cols > current_cols):
        worksheet.resize(rows=target_rows, cols=target_cols)

    # Записываем максимум 400 строк за запрос, чтобы не упираться в лимит размера тела API.
    for offset in range(0, len(matrix), chunk_size):
        chunk = matrix[offset:offset + chunk_size]
        start_row = offset + 1
        end_row = offset + len(chunk)
        end_col = _col_letter(width)
        _retry_google_request(lambda: worksheet.update(
            chunk,
            range_name=f"A{start_row}:{end_col}{end_row}",
            value_input_option="USER_ENTERED",
        ))

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


def _build_investments_matrix(db: Session) -> list[list[object]]:
    """Возвращает все инвестиции с датой, суммой и исходным комментарием."""
    investments = db.query(Investment).order_by(Investment.date, Investment.id).all()
    return [
        ["Дата", "Сумма", "Комментарий"],
        *[
            [
                _safe_iso(investment.date),
                float(investment.amount or 0),
                investment.comment or "",
            ]
            for investment in investments
        ],
    ]


def _ensure_writeoffs_sheet(spreadsheet) -> str:
    """Гарантирует существование листа «Списания», не трогая данные заказчика.

    Списания (съели сами / неуточненные / подарки) ведёт заказчик вручную,
    в базе ERP их пока нет. Лист обязателен: строки 46 и 53 отчёта считают
    его через SUMIFS, и без листа формулы дали бы #REF!.

    Возвращает статус: "created" — лист создан и заполнен заголовками,
    "seeded" — лист был пуст, записаны только заголовки,
    "kept" — лист существует с данными, не тронут.
    """
    status = "seeded"
    try:
        worksheet = spreadsheet.worksheet(WRITEOFFS_SHEET_TITLE)
    except gspread.exceptions.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(
            title=WRITEOFFS_SHEET_TITLE,
            rows=str(DATA_RANGE_LAST_ROW),
            cols=str(len(WRITEOFFS_HEADERS)),
        )
        status = "created"

    if status != "created":
        try:
            existing = worksheet.get_values()
        except gspread.exceptions.APIError:
            existing = None
        if existing and any(any(cell for cell in row) for row in existing):
            return "kept"

    header_range = f"A1:{_col_letter(len(WRITEOFFS_HEADERS))}1"
    _retry_google_request(lambda: worksheet.update(
        [WRITEOFFS_HEADERS],
        range_name=header_range,
        value_input_option="USER_ENTERED",
    ))
    worksheet.freeze(rows=1)
    return status


def sync_operations_to_sheets(db: Session, spreadsheet_id: str | None = None) -> dict:
    """Выгружает P&L, операции и инвестиции в Google Sheets.


    Выгрузки независимы: ошибка одной не блокирует остальные. Если любая
    из них завершилась ошибкой, исключение поднимается после всех попыток.
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
    investments_matrix = None
    errors: list[str] = []

    try:
        report = build_report(db)
        report_matrix = report_to_matrix(
            report, separator=settings.GOOGLE_FORMULA_SEPARATOR
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Не удалось построить отчёт P&L")
        errors.append(f"Отчёт P&L: {exc}")

    try:
        operations_matrix = _build_operations_matrix(db)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Не удалось построить выгрузку операций")
        errors.append(f"Операции: {exc}")

    try:
        investments_matrix = _build_investments_matrix(db)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Не удалось построить выгрузку инвестиций")
        errors.append(f"Инвестиции: {exc}")

    report_synced = False
    operations_synced = False
    investments_synced = False
    writeoffs_status = None

    # Лист «Списания» готовим до отчёта: его строки 46 и 53 ссылаются на
    # этот лист, и при отсутствии листа SUMIFS дали бы #REF!.
    try:
        writeoffs_status = _ensure_writeoffs_sheet(spreadsheet)
    except gspread.exceptions.APIError as exc:
        logger.exception("Ошибка Google Sheets API при подготовке листа списаний")
        errors.append(f"Списания: ошибка Google Sheets API: {exc}")
    except Exception as exc:  # noqa: BLE001
        logger.exception("Ошибка при подготовке листа списаний")
        errors.append(f"Списания: {exc}")

    # Записываем отчёт независимо от результата подготовки операций.
    if report is not None and report_matrix is not None:
        try:
            report_worksheet = _get_or_create_worksheet(
                spreadsheet, REPORT_SHEET_TITLE
            )
            report_worksheet.clear()
            _write_matrix_chunked(report_worksheet, report_matrix)
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
            _write_matrix_chunked(operations_worksheet, operations_matrix)
            operations_worksheet.freeze(rows=2)
            operations_worksheet.set_basic_filter()
            # Дата в столбце B — как в эталоне (dd.mm.yyyy); SUMIFS отчёта
            # сравнивает её с датой месяца из строки 3, поэтому это должны
            # быть настоящие даты, а не текст.
            _apply_date_format(
                operations_worksheet, 2, 3, len(operations_matrix) + DATE_FORMAT_TAIL_ROWS
            )
            operations_synced = True
        except gspread.exceptions.APIError as exc:
            logger.exception("Ошибка Google Sheets API при записи операций")
            errors.append(f"Операции: ошибка Google Sheets API: {exc}")
        except Exception as exc:  # noqa: BLE001
            logger.exception("Ошибка при записи операций")
            errors.append(f"Операции: {exc}")

    if investments_matrix is not None:
        try:
            investments_worksheet = _get_or_create_worksheet(
                spreadsheet, INVESTMENTS_SHEET_TITLE
            )
            try:
                investments_worksheet.clear_basic_filter()
            except Exception:  # noqa: BLE001
                pass
            investments_worksheet.clear()
            _write_matrix_chunked(investments_worksheet, investments_matrix)
            investments_worksheet.freeze(rows=1)
            investments_worksheet.set_basic_filter()
            _apply_date_format(
                investments_worksheet, 1, 2, len(investments_matrix) + DATE_FORMAT_TAIL_ROWS
            )
            investments_synced = True
        except gspread.exceptions.APIError as exc:
            logger.exception("Ошибка Google Sheets API при записи инвестиций")
            errors.append(f"Инвестиции: ошибка Google Sheets API: {exc}")
        except Exception as exc:  # noqa: BLE001
            logger.exception("Ошибка при записи инвестиций")
            errors.append(f"Инвестиции: {exc}")

    operations_count = 0
    if operations_matrix is not None:
        # Заголовок + пустая строка фильтра не являются операциями.
        operations_count = max(0, len(operations_matrix) - 2)
    investments_count = max(0, len(investments_matrix) - 1) if investments_matrix is not None else 0

    result = {
        "synced": operations_count if operations_synced else 0,
        "report_rows": len(report_matrix) if report_matrix is not None else 0,
        "operations_rows": operations_count if operations_synced else 0,
        "spreadsheet_id": spreadsheet_id,
        "sheet_title": REPORT_SHEET_TITLE,
        "operations_sheet_title": OPERATIONS_SHEET_TITLE,
        "investments_rows": investments_count if investments_synced else 0,
        "investments_sheet_title": INVESTMENTS_SHEET_TITLE,
        "writeoffs_sheet_title": WRITEOFFS_SHEET_TITLE,
        "writeoffs_status": writeoffs_status,
        "months": report.months if report is not None else [],
        "report_synced": report_synced,
        "operations_synced": operations_synced,
        "investments_synced": investments_synced,
        "errors": errors,
    }

    if errors:
        raise RuntimeError("Синхронизация завершена с ошибками: " + " | ".join(errors))

    return result
