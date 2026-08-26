# ERP — учёт доходов и расходов

FastAPI MVP для учёта доходов и расходов небольшого бизнеса: лавка, ужины, доставка, аренда и другие операции.

Приложение позволяет вести справочники категорий, поставщиков, продуктов и сотрудников, создавать доходные и расходные операции с детализацией по продуктам, смотреть отчёты и графики, а также выгружать данные в Google Sheets и автоматически создавать резервные копии SQLite-базы.

## Фазы проекта

- **Фаза 1**: справочники, операции, авторизация, тесты, alembic.
- **Фаза 2**: множественные продукты в операции, закупочные цены, поиск/фильтры.
- **Фаза 3**: интеграция Google Sheets, графики и отчёты.
- **Фаза 4**: резервное копирование, health-check, функциональное E2E-тестирование, инструкция по деплою.

## Требования

- Python 3.11+
- SQLite (используется по умолчанию)
- Опционально: аккаунт Google Cloud с сервисным аккаунтом для синхронизации с Google Sheets

## Локальный запуск

1. Скопируйте пример настроек:
   ```bash
   cp .env.example .env
   ```

2. Создайте виртуальное окружение и установите зависимости:
   ```bash
   python -m venv .venv
   .venv/Scripts/pip install -r requirements.txt
   ```

3. Примените миграции (опционально, приложение также создаёт таблицы при старте):
   ```bash
   .venv/Scripts/alembic upgrade head
   ```

4. Запустите сервер:
   ```bash
   .venv/Scripts/python run.py
   ```

5. Откройте в браузере: http://localhost:8000

   Пароль по умолчанию: `admin` (задаётся в `.env` через `ADMIN_PASSWORD`).

## Переменные окружения

| Переменная             | Описание                                                            | Значение по умолчанию                                  |
|------------------------|---------------------------------------------------------------------|--------------------------------------------------------|
| `ADMIN_PASSWORD`       | Пароль для входа в веб-интерфейс                                    | `admin`                                                |
| `SECRET_KEY`           | Секретный ключ подписи сессионной cookie                            | `change-me-in-production`                              |
| `DATABASE_URL`         | URL подключения к БД (поддерживается SQLite)                        | `sqlite:///data/app.db`                                |
| `GOOGLE_SA_FILE`       | Путь к JSON-файлу сервисного аккаунта Google                        | `gen-lang-client-0103225655-395c3c364797.json`         |
| `GOOGLE_SPREADSHEET_ID`| ID Google Таблицы для синхронизации                                 | ``                                                     |
| `SYNC_ENABLED`         | Включить автоматическую синхронизацию с Google Sheets               | `false`                                                |
| `SYNC_SCHEDULE`        | Расписание синхронизации в формате cron                             | `0 2 * * *`                                            |
| `BACKUP_DIR`           | Каталог для хранения резервных копий БД                             | `backups`                                              |
| `BACKUP_KEEP`          | Количество хранимых резервных копий                                 | `7`                                                    |
| `BACKUP_SCHEDULE`      | Расписание автоматического бэкапа в формате cron                    | `0 3 * * *`                                            |

## Google Sheets

1. В [Google Cloud Console](https://console.cloud.google.com/) создайте сервисный аккаунт и скачайте JSON-ключ.
2. Укажите путь к JSON в `GOOGLE_SA_FILE` (относительно корня проекта).
3. Скопируйте `client_email` из JSON-файла.
4. Откройте нужную Google Таблицу и добавьте этот email с правами **Редактор** через кнопку "Настройки доступа".
5. Скопируйте ID таблицы из URL (`https://docs.google.com/spreadsheets/d/{ID}/edit`) в `GOOGLE_SPREADSHEET_ID`.
6. Установите `SYNC_ENABLED=true` и, при необходимости, измените `SYNC_SCHEDULE`.

### Формат выгружаемого отчёта

Синхронизация формирует лист **"Отчет"** в формате P&L (доходы/расходы/прибыль) по месяцам:

- **Выручка всего** и разбивка по группам (лавка, кейтеринг, аренда, комиссия).
- **Прямые расходы всего** с детализацией по статьям.
- **Накладные расходы всего** с детализацией по статьям.
- **Налоги и сборы**.
- **Прибыль** и **прибыль итого** (накопительный итог).
- **Инвестиции** (пустая строка для ручного заполнения).

Для каждого месяца выводятся два столбца: **сумма** и **% от выручки**. Доходы и расходы группируются по полю **"Группа отчёта"** в карточке категории (`/categories`).

Основные группы отчёта:

| Группа | Раздел отчёта |
|--------|---------------|
| `revenue_lavka` | Выручка лавка |
| `revenue_catering` | Выручка кейтеринг |
| `revenue_rent` | Выручка аренда |
| `revenue_commission` | Выручка комиссия |
| `direct_*` | Прямые расходы |
| `overhead_*` | Накладные расходы |
| `taxes` | Налоги и сборы |

Если категория не привязана ни к одной группе, она не попадает в отчёт, но остаётся в операциях и графиках.

## Деплой на VPS

### Systemd unit

Создайте файл `/etc/systemd/system/erp.service`:

```ini
[Unit]
Description=ERP FastAPI application
After=network.target

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/opt/erp
Environment="PATH=/opt/erp/.venv/bin"
EnvironmentFile=/opt/erp/.env
ExecStart=/opt/erp/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
ExecReload=/bin/kill -s HUP $MAINPID
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Затем:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now erp
```

### Nginx reverse proxy

Пример конфигурации `/etc/nginx/sites-available/erp`:

```nginx
server {
    listen 80;
    server_name erp.example.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Активируйте конфигурацию:

```bash
sudo ln -s /etc/nginx/sites-available/erp /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### Health-check

Приложение отвечает на `GET /health`:

```json
{"status": "ok", "database": "ok"}
```

При недоступности БД возвращается HTTP 503:

```json
{"status": "error", "database": "error", "detail": "..."}
```

Используйте `/health` для мониторинга и в load balancer.

## Резервное копирование

Автоматическое резервное копирование SQLite-БД запускается по расписанию `BACKUP_SCHEDULE` (по умолчанию ежедневно в 03:00). Копии сохраняются в каталог `BACKUP_DIR` с именами вида `app_YYYYMMDD_HHMMSS.db`.

Ротация оставляет не более `BACKUP_KEEP` последних копий.

Ручное управление доступно в веб-интерфейсе по адресу `/backups` и через API `GET /api/backups`.

### Восстановление из бэкапа

1. Остановите приложение:
   ```bash
   sudo systemctl stop erp
   ```
2. Скопируйте нужную резервную копию на место текущей БД:
   ```bash
   cp backups/app_20240115_030000.db data/app.db
   ```
3. Запустите приложение:
   ```bash
   sudo systemctl start erp
   ```

Также восстановление можно выполнить через веб-интерфейс `/backups` — нажмите кнопку "Восстановить" напротив нужной копии и подтвердите перезапись БД.

## Структура

- `app/main.py` — точка входа FastAPI.
- `app/routers/` — HTML- и API-роутеры.
- `app/models.py` — модели SQLAlchemy.
- `app/seed.py` — начальные категории и сотрудники.
- `app/templates/` — Jinja2-шаблоны.
- `app/static/` — CSS/JS.
- `alembic/` — миграции базы данных.
- `tests/` — pytest-тесты.

## Тесты

```bash
.venv/Scripts/python -m pytest -q
```
