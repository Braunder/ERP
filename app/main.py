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
app.mount("/images", StaticFiles(directory=str(APP_DIR.parent / "images")), name="images")
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
                max-width: 1200px;
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
            .header h1 { margin: 0; font-size: 2.1rem; }
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
                font-size: 1.4rem;
            }
            .card h3 {
                margin: 16px 0 8px;
                font-size: 1.05rem;
                color: var(--text);
            }
            .card p, .card li, .card blockquote {
                color: var(--muted);
                line-height: 1.7;
                font-size: 1rem;
            }
            .card ul, .card ol {
                margin: 0;
                padding-left: 20px;
            }
            .card li + li { margin-top: 6px; }
            blockquote {
                margin: 12px 0 0;
                padding: 10px 14px;
                background: #eef6ff;
                border-left: 4px solid var(--primary);
                border-radius: 0 10px 10px 0;
            }
            .image-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
                gap: 16px;
                margin-top: 14px;
            }
            .image-box {
                background: white;
                border: 1px solid var(--line);
                border-radius: 12px;
                overflow: hidden;
            }
            .image-box img {
                display: block;
                width: 100%;
                height: auto;
                border-bottom: 1px solid var(--line);
            }
            .image-box span {
                display: block;
                padding: 8px 10px;
                font-size: 0.84rem;
                color: var(--muted);
            }
            @media (max-width: 768px) {
                .wrap { padding: 0 10px; margin-top: 20px; }
                .header, .content { padding-left: 16px; padding-right: 16px; }
            }
        </style>
    </head>
    <body>
        <div class="wrap">
            <header class="header">
                <h1>Инструкция по работе в ERP</h1>
                <p>Полная памятка по работе с системой: вход, операции, категории, графики, таблицы, синхронизация и бэкапы.</p>
            </header>
            <main class="content">
                <div class="badge-row">
                    <span class="badge">Вход</span>
                    <span class="badge">Операции</span>
                    <span class="badge">Категории</span>
                    <span class="badge">Графики</span>
                    <span class="badge">Таблица</span>
                    <span class="badge">Бэкапы</span>
                </div>

                <section class="card">
                    <h2>1. Как открыть систему</h2>
                    <ol>
                        <li>Откройте ссылку, которая используется в вашей компании или на сервере.</li>
                        <li>Войдите в систему под своим логином и паролем.</li>
                        <li>После входа откроется главное меню и рабочая область.</li>
                    </ol>
                    <div class="image-grid">
                        <div class="image-box"><img src="/images/login.png" alt="Страница входа"><span>Страница входа</span></div>
                        <div class="image-box"><img src="/images/menu_default.png" alt="Главное окно"><span>Главное окно</span></div>
                    </div>
                    <p>В интерфейсе обычно есть меню разделов, списки данных, кнопки добавления, редактирования и удаления, а также панель статистики и фильтров.</p>
                </section>

                <section class="card">
                    <h2>2. Основные разделы системы</h2>
                    <p>В обычной работе используют следующие разделы:</p>
                    <ul>
                        <li>Операции</li>
                        <li>Категории</li>
                        <li>Поставщики</li>
                        <li>Сотрудники</li>
                        <li>Продукты</li>
                        <li>Статистика</li>
                        <li>Синхронизация</li>
                        <li>Резервные копии</li>
                    </ul>
                    <div class="image-grid">
                        <div class="image-box"><img src="/images/menu.png" alt="Меню разделов"><span>Меню разделов</span></div>
                    </div>
                </section>

                <section class="card">
                    <h2>3. Как создать новую операцию</h2>
                    <ol>
                        <li>Откройте раздел «Операции».</li>
                        <li>Нажмите кнопку «Новая операция».</li>
                        <li>Заполните поля: дата, тип операции, категория, сумма, комментарий, способ оплаты, поставщик, сотрудник или другие поля, если они появились.</li>
                        <li>Нажмите «Сохранить».</li>
                    </ol>
                    <div class="image-grid">
                        <div class="image-box"><img src="/images/menu_operation.png" alt="Форма операции"><span>Кнопка новой операции</span></div>
                        <div class="image-box"><img src="/images/new_operation.png" alt="Заполнение операции"><span>Форма операции</span></div>
                        <div class="image-box"><img src="/images/save_operation.png" alt="Сохранение операции"><span>Сохранение</span></div>
                    </div>
                    <blockquote>Некоторые категории требуют дополнительных данных. Если после выбора категории появились новые поля, их нужно заполнить обязательно.</blockquote>
                </section>

                <section class="card">
                    <h2>4. Как выбрать категорию правильно</h2>
                    <ol>
                        <li>В поле «Категория» откройте выпадающий список.</li>
                        <li>Выберите подходящую категорию.</li>
                        <li>Если система предлагает выбрать подкатегорию, выберите и её.</li>
                    </ol>
                    <div class="image-grid">
                        <div class="image-box"><img src="/images/type_operation.png" alt="Выбор типа операции"><span>Выбор категории</span></div>
                        <div class="image-box"><img src="/images/category_change.png" alt="Категория и подкатегория"><span>Подкатегория</span></div>
                    </div>
                    <p>Полезное правило: выбирайте категорию как можно точнее, не оставляйте пустую категорию и проверяйте тип доход/расход перед сохранением.</p>
                </section>

                <section class="card">
                    <h2>5. Как посмотреть список операций</h2>
                    <ol>
                        <li>Откройте раздел «Операции».</li>
                        <li>Перед вами появится таблица со всеми записями.</li>
                        <li>Можно отфильтровать записи по периоду, типу, категории и другим параметрам.</li>
                    </ol>
                    <div class="image-grid">
                        <div class="image-box"><img src="/images/menu_operations.png" alt="Список операций"><span>Список операций</span></div>
                    </div>
                    <p>Обычно в таблице видно дату, тип сделки, категорию, сумму, комментарий, способ оплаты, поставщика или сотрудника.</p>
                </section>

                <section class="card">
                    <h2>6. Как отредактировать или удалить операцию</h2>
                    <h3>Редактирование</h3>
                    <ol>
                        <li>Найдите нужную строку в таблице.</li>
                        <li>Нажмите кнопку редактирования.</li>
                        <li>Исправьте данные и сохраните изменения.</li>
                    </ol>
                    <div class="image-grid">
                        <div class="image-box"><img src="/images/edit_operations.png" alt="Редактирование операции"><span>Редактирование</span></div>
                        <div class="image-box"><img src="/images/del_operations.png" alt="Удаление операции"><span>Удаление</span></div>
                    </div>
                    <blockquote>Перед удалением лучше проверить, что это не ошибка: после удаления операция не восстанавливается автоматически.</blockquote>
                </section>

                <section class="card">
                    <h2>7. Как работать со справочниками</h2>
                    <h3>Категории</h3>
                    <p>Открывайте раздел «Категории», если нужно добавить новую категорию, изменить тип (доход/расход), указать родительскую категорию или настроить обязательные дополнительные поля.</p>
                    <div class="image-grid"><div class="image-box"><img src="/images/category.png" alt="Категории"><span>Категории</span></div></div>

                    <h3>Поставщики</h3>
                    <p>Используйте раздел «Поставщики», когда нужно добавить нового поставщика, привязать его к расходной операции или хранить контактные данные.</p>
                    <div class="image-grid"><div class="image-box"><img src="/images/delivery.png" alt="Поставщики"><span>Поставщики</span></div></div>

                    <h3>Сотрудники</h3>
                    <p>Раздел «Сотрудники» нужен для указания ответственных лиц или участников операций.</p>
                    <div class="image-grid"><div class="image-box"><img src="/images/staff.png" alt="Сотрудники"><span>Сотрудники</span></div></div>

                    <h3>Продукты</h3>
                    <p>Раздел «Продукты» используется для учёта товаров и позиций, которые затем участвуют в операциях.</p>
                    <div class="image-grid"><div class="image-box"><img src="/images/products.png" alt="Продукты"><span>Продукты</span></div></div>
                </section>

                <section class="card">
                    <h2>8. Как использовать цены и товары в операциях</h2>
                    <p>Если нужно учитывать закупку товаров или услуг у поставщиков, используйте связанные справочники: продукт, поставщик, цена товара у поставщика.</p>
                    <div class="image-grid"><div class="image-box"><img src="/images/buy_demo.png" alt="Цены по поставщикам"><span>Цены и товары</span></div></div>
                </section>

                <section class="card">
                    <h2>9. Как смотреть статистику и графики</h2>
                    <ol>
                        <li>Откройте раздел «Графики».</li>
                        <li>Вы увидите общий доход, расход, баланс, графики по периодам и распределение по категориям.</li>
                    </ol>
                    <div class="image-grid">
                        <div class="image-box"><img src="/images/graphs.png" alt="Графики"><span>Графики</span></div>
                        <div class="image-box"><img src="/images/graphs_1.png" alt="Фильтры графики"><span>Фильтры</span></div>
                    </div>
                    <p>Доход — это всё, что пришло; расход — всё, что ушло; баланс — разница между доходом и расходом.</p>
                </section>

                <section class="card">
                    <h2>10. Как пользоваться фильтрами в графике</h2>
                    <p>На странице графики обычно доступны следующие фильтры: тип операций, категория, период от/до, способ оплаты.</p>
                    <ul>
                        <li>доходы по месяцу;</li>
                        <li>расходы по категории;</li>
                        <li>операции за период по методу оплаты.</li>
                    </ul>
                </section>

                <section class="card">
                    <h2>11. Как проверить отчёт по месяцам</h2>
                    <p>Если нужен сводный финансовый взгляд, используйте раздел со сводкой или отчётом. Откройте «Таблица» и сравните доходы, расходы и итоговую прибыль.</p>
                    <div class="image-grid"><div class="image-box"><img src="/images/tables.png" alt="Отчёт по месяцам"><span>Отчёт</span></div></div>
                </section>

                <section class="card">
                    <h2>12. Как синхронизировать данные с Google Таблицей</h2>
                    <ol>
                        <li>Откройте раздел «Синхронизация».</li>
                        <li>Проверьте, что синхронизация включена.</li>
                        <li>Нажмите кнопку «Синхронизировать сейчас», если нужно обновить данные вручную.</li>
                        <li>Проверьте, что таблица обновилась.</li>
                    </ol>
                    <div class="image-grid">
                        <div class="image-box"><img src="/images/sync.png" alt="Синхронизация"><span>Синхронизация</span></div>
                        <div class="image-box"><img src="/images/table_operations.png" alt="Таблица операций"><span>Лист Операции</span></div>
                    </div>
                    <blockquote>Если данные не появились, проверьте доступ к таблице и корректность ID таблицы.</blockquote>
                </section>

                <section class="card">
                    <h2>13. Что такое лист «Отчет» и лист «Операции»</h2>
                    <h3>Лист «Отчет»</h3>
                    <p>Это сводка по финансовым показателям: доходы, расходы, прибыль и структура по категориям.</p>
                    <div class="image-grid"><div class="image-box"><img src="/images/price.png" alt="Лист Отчет"><span>Лист Отчет</span></div></div>

                    <h3>Лист «Операции»</h3>
                    <p>Это полный список всех записей, которые были добавлены в ERP.</p>
                    <div class="image-grid"><div class="image-box"><img src="/images/table_operations.png" alt="Лист Операции"><span>Лист Операции</span></div></div>
                </section>

                <section class="card">
                    <h2>14. Как сделать резервную копию</h2>
                    <ol>
                        <li>Откройте раздел «Резервные копии».</li>
                        <li>Нажмите кнопку создания копии.</li>
                        <li>Дождитесь завершения операции.</li>
                    </ol>
                    <div class="image-grid">
                        <div class="image-box"><img src="/images/backup.png" alt="Резервные копии"><span>Бэкап</span></div>
                        <div class="image-box"><img src="/images/backup_1.png" alt="Создание бэкапа"><span>Создание</span></div>
                    </div>
                    <p>Когда это важно: перед массовыми исправлениями, перед восстановлением данных, после больших изменений в справочниках и в конце рабочего дня.</p>
                </section>

                <section class="card">
                    <h2>15. Как восстановить резервную копию</h2>
                    <ol>
                        <li>Откройте раздел «Резервные копии».</li>
                        <li>Выберите нужную копию.</li>
                        <li>Нажмите «Восстановить».</li>
                        <li>Подтвердите действие.</li>
                    </ol>
                    <div class="image-grid"><div class="image-box"><img src="/images/backup_2.png" alt="Восстановление копии"><span>Восстановление</span></div></div>
                    <blockquote>Важно: восстановление возвращает данные к состоянию на момент создания копии. Это может изменить текущие записи, поэтому используйте это осторожно.</blockquote>
                </section>

                <section class="card">
                    <h2>16. Что делать, если что-то не работает</h2>
                    <h3>Проверьте в таком порядке</h3>
                    <ol>
                        <li>Система запущена и доступна по ссылке.</li>
                        <li>Вы вошли под корректным пользователем.</li>
                        <li>Убедитесь, что нужный раздел открыт.</li>
                        <li>Проверьте фильтры и даты.</li>
                        <li>Если это синхронизация — проверьте доступ к Google Таблице.</li>
                        <li>Если данные не обновляются — посмотрите журнал синхронизации или резервные копии.</li>
                    </ol>
                    <h3>Частые причины проблем</h3>
                    <ul>
                        <li>неверная ссылка или сервер недоступен;</li>
                        <li>фильтры слишком жёсткие;</li>
                        <li>нет доступа к Google Таблице;</li>
                        <li>синхронизация выключена;</li>
                        <li>данные были изменены вручную и не сохранены.</li>
                    </ul>
                </section>

                <section class="card">
                    <h2>17. Рекомендации по ежедневной работе</h2>
                    <h3>Каждый день</h3>
                    <ul>
                        <li>вносите операции сразу после события;</li>
                        <li>проверяйте корректность категорий;</li>
                        <li>следите за суммами и комментариями;</li>
                        <li>контролируйте дубли и ошибки в справочниках.</li>
                    </ul>
                    <h3>Раз в неделю</h3>
                    <ul>
                        <li>сверяйте статистику с реальными данными;</li>
                        <li>проверяйте, что доходы и расходы отражены корректно;</li>
                        <li>убеждайтесь, что синхронизация работает.</li>
                    </ul>
                    <h3>Раз в месяц</h3>
                    <ul>
                        <li>проверяйте итоговые отчёты;</li>
                        <li>сверяйте данные с фактическими финансовыми результатами;</li>
                        <li>обновляйте справочники при изменении структуры бизнеса.</li>
                    </ul>
                </section>

                <section class="card">
                    <h2>18. Краткая памятка</h2>
                    <ol>
                        <li>Войдите в ERP.</li>
                        <li>Откройте раздел «Операции».</li>
                        <li>Добавьте новую запись.</li>
                        <li>Выберите правильную категорию и сумму.</li>
                        <li>Проверьте статистику.</li>
                        <li>Сверяйте данные в Google Таблице при необходимости.</li>
                        <li>Держите резервные копии актуальными.</li>
                    </ol>
                </section>

                <section class="card">
                    <h2>19. Итог</h2>
                    <p>Когда проект уже запущен, ERP-система обычно используется как рабочий инструмент для ежедневного учёта и анализа: фиксировать операции, проверять доходы и расходы, поддерживать справочники, анализировать статистику, выгружать данные в Google Таблицу и сохранять резервные копии.</p>
                    <p>Это помогает вести расчёты аккуратно, быстро и без ручного копирования информации.</p>
                </section>

                <section class="card">
                    <h2>20. Полезные термины</h2>
                    <h3>Операция</h3>
                    <p>Запись о доходе или расходе.</p>
                    <h3>Категория</h3>
                    <p>Группа, к которой относится операция.</p>
                    <h3>Синхронизация</h3>
                    <p>Автоматическая выгрузка данных в Google Таблицу.</p>
                    <h3>Резервная копия</h3>
                    <p>Копия данных на случай потери или ошибки.</p>
                </section>

                <section class="card">
                    <h2>21. Полезный совет</h2>
                    <ul>
                        <li>вносить операции сразу;</li>
                        <li>проверять категорию перед сохранением;</li>
                        <li>не оставлять пустые обязательные поля;</li>
                        <li>периодически смотреть статистику и синхронизацию.</li>
                    </ul>
                    <blockquote>Так работа в ERP будет стабильной, понятной и без лишних ошибок.</blockquote>
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
