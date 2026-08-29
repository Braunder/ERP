"""Инициализация базы данных: создание таблиц и заполнение справочников."""
import sys
from pathlib import Path

# Добавляем app в путь
sys.path.insert(0, str(Path(__file__).parent))

from app.database import engine, Base
from app.seed import seed_db
from alembic.config import Config
from alembic import command


def run_migrations():
    """Выполняет миграции базы данных."""
    print("Выполнение миграций Alembic...")
    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")
    print("✓ Миграции выполнены успешно")


def create_tables():
    """Создает таблицы (если миграции не выполнены)."""
    print("Создание таблиц базы данных...")
    try:
        Base.metadata.create_all(bind=engine)
        print("✓ Таблицы созданы")
    except Exception as e:
        print(f"⚠ Ошибка при создании таблиц: {e}")
        print("Попробуем создать таблицы через Alembic...")
        try:
            run_migrations()
        except Exception as e2:
            print(f"⚠ Ошибка при выполнении миграций: {e2}")
            raise


def seed_data():
    """Заполняет справочники начальными данными."""
    from app.database import SessionLocal
    print("Заполнение справочников...")
    db = SessionLocal()
    try:
        seed_db(db)
        print("✓ Справочники заполнены")
    finally:
        db.close()


def main():
    """Главная функция инициализации."""
    print("=" * 60)
    print("Инициализация базы данных")
    print("=" * 60)

    # Создаем таблицы
    create_tables()

    # Заполняем справочники
    seed_data()

    print("=" * 60)
    print("База данных инициализирована!")
    print("=" * 60)


if __name__ == "__main__":
    main()
