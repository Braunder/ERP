"""Точка входа FastAPI: middleware, роутеры, события."""
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

from app.database import Base
from app.routers import auth, backups, categories, employees, health, investments, operations, products, report_groups, stats, suppliers, sync
from app.seed import seed_db
from app.services import scheduler as scheduler_module

import app.database as database_module


APP_DIR = Path(__file__).resolve().parent


def _setup_logging() -> None:
    log_dir = APP_DIR.parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "app.log"

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)


_setup_logging()

app = FastAPI(title="ERP учёт доходов/расходов")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))

app.include_router(auth.router)
app.include_router(health.router)
app.include_router(operations.router)
app.include_router(investments.router)
app.include_router(categories.router)
app.include_router(report_groups.router)
app.include_router(suppliers.router)
app.include_router(products.router)
app.include_router(employees.router)
app.include_router(stats.router)
app.include_router(sync.router)
app.include_router(backups.router)


HELP_SECTIONS = [
    {
        "title": "Вход в систему",
        "items": [
            "Откройте ссылку проекта и войдите под своим логином и паролем.",
            "После входа открывается главное меню с разделами: Операции, Категории, Поставщики, Сотрудники, Продукты, Графики, Синхронизация и Бэкапы.",
        ],
    },
    {
        "title": "Как работать с операциями",
        "items": [
            "Откройте раздел Операции и нажмите «Новая операция».",
            "Заполните дату, тип операции, категорию, сумму и комментарий.",
            "Если категория требует доп. поля, заполните их перед сохранением.",
            "Проверяйте категорию до сохранения — это влияет на отчёты и графики.",
        ],
    },
    {
        "title": "Справочники",
        "items": [
            "Категории — для группировки доходов и расходов.",
            "Поставщики — для учёта оплат и закупок.",
            "Сотрудники — для ответственных лиц и участников операций.",
            "Продукты — для товаров и позиций, которые используются в сделках.",
        ],
    },
    {
        "title": "Статистика и графики",
        "items": [
            "Раздел Графики показывает общий доход, расход и баланс.",
            "Фильтры позволяют смотреть данные по типу операции, категории, периоду и способу оплаты.",
            "Если данных нет, система показывает пустое состояние, а не падает с ошибкой.",
        ],
    },
    {
        "title": "Google Таблица",
        "items": [
            "В системе есть ссылка на Google Таблицу, где доступны сводные данные по операциям.",
            "Важно проверять актуальность данных после синхронизации.",
            "Листы таблицы помогают быстро сверять финансовую картину без ручного копирования.",
        ],
    },
    {
        "title": "Резервные копии",
        "items": [
            "Раздел Бэкапы позволяет сделать копию базы данных вручную.",
            "Резервные копии нужны перед массовыми правками, восстановлением или после важных изменений.",
            "Если что-то пошло не так, восстановление из копии помогает быстро вернуть данные.",
        ],
    },
    {
        "title": "Что делать, если есть проблема",
        "items": [
            "Проверьте, что система доступна по ссылке.",
            "Проверьте фильтры, даты и выбранную категорию.",
            "Если проблема с синхронизацией — проверьте доступ к Google Таблице.",
            "Если данные не отображаются — посмотрите, есть ли по запросу запись в системе и актуальные даты.",
        ],
    },
]


@app.get("/help")
async def help_page():
    html = """
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Помощь — ERP</title>
        <style>
            :root {
                --bg: #f3f7ff;
                --card: #ffffff;
                --primary: #0d6efd;
                --primary-dark: #0b5ed7;
                --text: #1f2937;
                --muted: #4b5563;
                --line: #e5e7eb;
                --badge: #eaf2ff;
            }
            * { box-sizing: border-box; }
            body {
                margin: 0;
                font-family: Arial, sans-serif;
                background: linear-gradient(180deg, #f6f8ff 0%, #eef4fb 100%);
                color: var(--text);
            }
            .wrap {
                max-width: 1100px;
                margin: 32px auto 80px;
                padding: 0 18px;
            }
            .header {
                background: linear-gradient(135deg, var(--primary) 0%, #2563eb 100%);
                color: white;
                border-radius: 18px 18px 0 0;
                padding: 28px 28px 24px;
                box-shadow: 0 10px 24px rgba(37, 99, 235, 0.18);
            }
            .header h1 { margin: 0; font-size: 2rem; }
            .header p { margin: 10px 0 0; opacity: 0.95; }
            .content {
                background: var(--card);
                border: 1px solid var(--line);
                border-top: none;
                border-radius: 0 0 18px 18px;
                padding: 24px 28px 40px;
                box-shadow: 0 10px 24px rgba(15, 23, 42, 0.05);
            }
            .badge-row { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 18px; }
            .badge {
                display: inline-block;
                padding: 6px 10px;
                border-radius: 999px;
                background: var(--badge);
                color: #1d4ed8;
                font-size: 0.8rem;
                font-weight: 700;
            }
            .card {
                background: #f8fafc;
                border: 1px solid var(--line);
                border-radius: 14px;
                padding: 20px 22px;
                margin-bottom: 18px;
            }
            .card h2 {
                margin: 0 0 12px;
                font-size: 1.3rem;
            }
            .card ul {
                margin: 0;
                padding-left: 20px;
                color: var(--muted);
                line-height: 1.7;
            }
            li + li { margin-top: 6px; }
            @media (max-width: 768px) {
                .wrap { padding: 0 10px; margin-top: 20px; }
                .header, .content { padding-left: 16px; padding-right: 16px; }
            }
        </style>
    </head>
    <body>
        <div class="wrap">
            <header class="header">
                <h1>Помощь по ERP</h1>
                <p>Короткая памятка по работе в системе: операции, категории, статистика, Google Таблица и бэкапы.</p>
            </header>
            <main class="content">
                <div class="badge-row">
                    <span class="badge">Вход</span>
                    <span class="badge">Операции</span>
                    <span class="badge">Статистика</span>
                    <span class="badge">Таблица</span>
                    <span class="badge">Бэкапы</span>
                </div>

                <section class="card">
                    <h2>Вход в систему</h2>
                    <ul>
                        <li>Откройте ссылку проекта и войдите под своим логином и паролем.</li>
                        <li>После входа открывается главное меню с разделами: Операции, Категории, Поставщики, Сотрудники, Продукты, Графики, Синхронизация и Бэкапы.</li>
                    </ul>
                </section>

                <section class="card">
                    <h2>Как работать с операциями</h2>
                    <ul>
                        <li>Откройте раздел Операции и нажмите «Новая операция».</li>
                        <li>Заполните дату, тип операции, категорию, сумму и комментарий.</li>
                        <li>Если категория требует дополнительные поля, заполните их до сохранения.</li>
                        <li>Проверяйте категорию перед сохранением — это влияет на отчёты и графики.</li>
                    </ul>
                </section>

                <section class="card">
                    <h2>Справочники</h2>
                    <ul>
                        <li>Категории — для группировки доходов и расходов.</li>
                        <li>Поставщики — для учёта оплат и закупок.</li>
                        <li>Сотрудники — для ответственных лиц и участников операций.</li>
                        <li>Продукты — для товаров и позиций, которые используются в сделках.</li>
                    </ul>
                </section>

                <section class="card">
                    <h2>Статистика и графики</h2>
                    <ul>
                        <li>Раздел Графики показывает общий доход, расход и баланс.</li>
                        <li>Фильтры позволяют смотреть данные по типу операции, категории, периоду и способу оплаты.</li>
                        <li>Если данных нет, система показывает пустое состояние, а не падает с ошибкой.</li>
                    </ul>
                </section>

                <section class="card">
                    <h2>Google Таблица</h2>
                    <ul>
                        <li>В системе есть ссылка на Google Таблицу, где доступны сводные данные по операциям.</li>
                        <li>Важно проверять актуальность данных после синхронизации.</li>
                        <li>Листы таблицы помогают быстро сверять финансовую картину без ручного копирования.</li>
                    </ul>
                </section>

                <section class="card">
                    <h2>Резервные копии</h2>
                    <ul>
                        <li>Раздел Бэкапы позволяет сделать копию базы данных вручную.</li>
                        <li>Резервные копии нужны перед массовыми правками, восстановлением или после важных изменений.</li>
                        <li>Если что-то пошло не так, восстановление из копии помогает быстро вернуть данные.</li>
                    </ul>
                </section>

                <section class="card">
                    <h2>Что делать, если есть проблема</h2>
                    <ul>
                        <li>Проверьте, что система доступна по ссылке.</li>
                        <li>Проверьте фильтры, даты и выбранную категорию.</li>
                        <li>Если проблема с синхронизацией — проверьте доступ к Google Таблице.</li>
                        <li>Если данные не отображаются — посмотрите, есть ли запись в системе и актуальные даты.</li>
                    </ul>
                </section>
            </main>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html)


@app.on_event("startup")
async def startup() -> None:
    Base.metadata.create_all(bind=database_module.engine)
    db = database_module.SessionLocal()
    try:
        seed_db(db)
    finally:
        db.close()
    scheduler_module.setup_scheduler()


@app.on_event("shutdown")
async def shutdown() -> None:
    scheduler_module.shutdown_scheduler()


@app.get("/")
async def root() -> RedirectResponse:
    return RedirectResponse(url="/operations", status_code=302)
