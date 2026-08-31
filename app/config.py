# app\config.py
"""Настройки приложения, читаются из .env и переменных окружения."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", env_file_encoding="utf-8", extra="ignore")

    DATABASE_URL: str = "sqlite:///data/app.db"
    ADMIN_PASSWORD: str = "admin"
    SECRET_KEY: str = "change-me-in-production"

    # Google Sheets (фаза 3)
    # GOOGLE_SA_FILE — путь к JSON-файлу сервисного аккаунта на диске.
    # Подходит для локальной разработки, где файл ключа лежит рядом с проектом.
    GOOGLE_SA_FILE: str = "gen-lang-client-0103225655-395c3c364797.json"
    # GOOGLE_SA_JSON — содержимое того же JSON-ключа целиком, одной строкой,
    # переданное через переменную окружения. Используется на Railway и
    # других PaaS, где нельзя закоммитить секретный файл в репозиторий.
    # Если задано — имеет приоритет над GOOGLE_SA_FILE.
    GOOGLE_SA_JSON: str = ""
    GOOGLE_SPREADSHEET_ID: str = ""
    SYNC_ENABLED: bool = False
    SYNC_SCHEDULE: str = "0 2 * * *"

    # Резервное копирование (фаза 4)
    BACKUP_DIR: str = "backups"
    BACKUP_KEEP: int = 7
    BACKUP_SCHEDULE: str = "0 3 * * *"
    TIMEZONE: str = "Europe/Moscow"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
