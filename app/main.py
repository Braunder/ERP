"""Точка входа FastAPI: middleware, роутеры, события."""
import logging
import re
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
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


def _inline_markdown(text: str) -> str:
    text = re.sub(r"\[(.+?)\]\((https?://[^)]+|[^)]+)\)", r'<a href="\2" target="_blank" rel="noopener noreferrer">\1</a>', text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    return text.strip()


def _markdown_to_html(markdown_text: str) -> str:
    parts: list[str] = []
    lines = markdown_text.splitlines()
    i = 0

    while i < len(lines):
        line = lines[i].rstrip()

        if not line.strip():
            i += 1
            continue

        if line.startswith("# "):
            parts.append(f"<h1>{_inline_markdown(line[2:])}</h1>")
            i += 1
            continue

        if line.startswith("## "):
            parts.append(f"<h2>{_inline_markdown(line[3:])}</h2>")
            i += 1
            continue

        if line.startswith("### "):
            parts.append(f"<h3>{_inline_markdown(line[4:])}</h3>")
            i += 1
            continue

        if line.startswith("---"):
            parts.append("<hr>")
            i += 1
            continue

        if line.startswith("> "):
            parts.append(f"<blockquote>{_inline_markdown(line[2:])}</blockquote>")
            i += 1
            continue

        if line.startswith("!") and "![" in line and "](" in line:
            match = re.search(r"!\[(.*?)\]\((.*?)\)", line)
            if match:
                alt, src = match.groups()
                image_src = src if src.startswith("http") else f"/{src.lstrip('/')}"
                parts.append(f'<figure class="help-figure"><img src="{image_src}" alt="{alt}"><figcaption>{alt}</figcaption></figure>')
                i += 1
                continue

        if line.startswith("- ") or re.match(r"^\d+\. ", line):
            items = []
            while i < len(lines) and (lines[i].startswith("- ") or re.match(r"^\d+\. ", lines[i])):
                item_line = lines[i].lstrip("- ").strip()
                item_line = re.sub(r"^\d+\. ", "", item_line)
                items.append(_inline_markdown(item_line))
                i += 1
            tag = "ul" if line.startswith("- ") else "ol"
            parts.append(f"<{tag}>" + "".join(f"<li>{item}</li>" for item in items) + f"</{tag}>")
            continue

        para_lines = [line]
        while i + 1 < len(lines) and not lines[i + 1].startswith(("# ", "## ", "### ", "---", "> ", "!", "- ", "* ")) and lines[i + 1].strip():
            i += 1
            para_lines.append(lines[i])

        paragraph = " ".join(part.strip() for part in para_lines if part.strip())
        if paragraph:
            parts.append(f"<p>{_inline_markdown(paragraph)}</p>")
        i += 1

    return "\n".join(parts)


@app.get("/help")
async def help_page(request: Request):
    instruction_file = APP_DIR.parent / "INSTRUCTION.md"
    markdown_text = instruction_file.read_text(encoding="utf-8") if instruction_file.exists() else "# Помощь\n\nИнструкция пока недоступна."
    return templates.TemplateResponse(
        "help.html",
        {
            "request": request,
            "content": _markdown_to_html(markdown_text),
            "title": "Помощь",
        },
    )


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
