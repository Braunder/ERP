"""Инициализация БД: безопасное применение Alembic-миграций и seed-данных."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from app.database import Base, engine, SessionLocal
from app.seed import seed_db
import app.models  # noqa: F401 — регистрирует все модели в Base.metadata


def _alembic_config() -> Config:
    cfg = Config(str(Path(__file__).resolve().parent / "alembic.ini"))
    # env.py использует DATABASE_URL из настроек приложения; ini нужен для расположения миграций.
    return cfg


def _adopt_existing_schema_if_complete() -> bool:
    """Если старая БД создана через create_all без Alembic, помечает head только
    после проверки, что все таблицы и колонки текущих моделей уже существуют.
    При несовпадении останавливается, не меняя версию и не скрывая проблему.
    """
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    model_tables = set(Base.metadata.tables)
    if "alembic_version" in existing_tables or not (existing_tables & model_tables):
        return False

    missing = []
    for table_name, table in Base.metadata.tables.items():
        if table_name not in existing_tables:
            missing.append(f"{table_name}: таблица отсутствует")
            continue
        present_columns = {column["name"] for column in inspector.get_columns(table_name)}
        for column in table.columns:
            if column.name not in present_columns:
                missing.append(f"{table_name}.{column.name}: колонка отсутствует")
    if missing:
        details = "\n".join(f"- {item}" for item in missing[:30])
        raise RuntimeError(
            "В существующей БД нет alembic_version, а схема не совпадает с моделями. "
            "Автоматически отмечать миграции небезопасно. Сделайте резервную копию и "
            "выполните отдельную миграцию схемы. Найдено:\n" + details
        )

    command.stamp(_alembic_config(), "head")
    print("Существующая схема проверена; Alembic отмечен на head.")
    return True


def run_migrations() -> None:
    print("Проверка и применение миграций Alembic...")
    # Загружаем модели до инспекции схемы.
    Base.metadata
    if not _adopt_existing_schema_if_complete():
        command.upgrade(_alembic_config(), "head")
    print("Миграции проверены/применены.")


def seed_data() -> None:
    db = SessionLocal()
    try:
        seed_db(db)
        db.commit()
        print("Справочники проверены.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> None:
    run_migrations()
    seed_data()
    print("Инициализация базы данных завершена.")


if __name__ == "__main__":
    main()
