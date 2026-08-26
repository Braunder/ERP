"""Точка входа FastAPI: middleware, роутеры, события."""
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

from app.database import Base
from app.routers import auth, backups, categories, employees, health, operations, products, report_groups, stats, suppliers, sync
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
app.include_router(categories.router)
app.include_router(report_groups.router)
app.include_router(suppliers.router)
app.include_router(products.router)
app.include_router(employees.router)
app.include_router(stats.router)
app.include_router(sync.router)
app.include_router(backups.router)


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
