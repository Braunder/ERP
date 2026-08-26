"""Общие зависимости FastAPI: авторизация и БД."""
from collections.abc import Generator

from fastapi import HTTPException, Request
from itsdangerous import URLSafeSerializer, BadSignature
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db as _get_db


# Ре-экспорт зависимости БД
def get_db() -> Generator[Session, None, None]:
    yield from _get_db()


serializer = URLSafeSerializer(settings.SECRET_KEY, salt="erp-auth")


def _is_authenticated(request: Request) -> bool:
    session_cookie = request.cookies.get("session")
    if not session_cookie:
        return False
    try:
        data = serializer.loads(session_cookie)
    except BadSignature:
        return False
    return isinstance(data, dict) and data.get("auth") is True


async def require_auth(request: Request) -> None:
    """Проверяет сессию. Для /api/* — 401, для HTML-роутов — редирект на /login."""
    if _is_authenticated(request):
        return

    if request.url.path.startswith("/api/"):
        raise HTTPException(status_code=401, detail="Требуется авторизация")

    raise HTTPException(
        status_code=302,
        detail="Требуется авторизация",
        headers={"Location": "/login"},
    )
