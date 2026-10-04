"""Единый часовой пояс приложения и локальное время."""
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.config import settings

PROJECT_TIMEZONE = ZoneInfo(settings.TIMEZONE)


def local_now() -> datetime:
    return datetime.now(PROJECT_TIMEZONE)


def local_now_naive() -> datetime:
    return local_now().replace(tzinfo=None)


def local_today() -> date:
    return local_now().date()