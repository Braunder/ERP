"""Авторизация: login, logout, установка сессионной cookie."""
from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from pathlib import Path
from starlette.templating import Jinja2Templates

from app.config import settings
from app.deps import serializer

router = APIRouter(tags=["auth"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / "templates"))


@router.get("/login")
async def login_page(request: Request, error: str | None = None):
    return templates.TemplateResponse(request, "login.html", {"error": error})


@router.post("/login")
async def login_post(password: str = Form(...)):
    if password == settings.ADMIN_PASSWORD:
        response = RedirectResponse(url="/", status_code=302)
        response.set_cookie(
            "session",
            serializer.dumps({"auth": True}),
            httponly=True,
            samesite="lax",
            secure=settings.COOKIE_SECURE,
        )
        return response
    return RedirectResponse(url="/login?error=1", status_code=302)


@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie("session")
    return response
