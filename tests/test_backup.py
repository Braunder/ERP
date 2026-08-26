"""Тесты сервиса резервного копирования."""
from pathlib import Path

from app.config import settings
from app.services.backup import backup_database, list_backups, restore_database


def test_backup_database_creates_copy(client, monkeypatch, tmp_path):
    db_path = tmp_path / "app.db"
    backup_dir = tmp_path / "backups"

    # Создаём файл БД
    db_path.write_text("sqlite test db")

    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setattr(settings, "BACKUP_DIR", str(backup_dir))
    monkeypatch.setattr(settings, "BACKUP_KEEP", 7)

    backup_path = backup_database()

    assert backup_path is not None
    assert backup_path.exists()
    assert backup_path.parent == backup_dir
    assert backup_path.suffix == ".db"
    assert backup_path.read_text() == "sqlite test db"


def test_backup_rotation_keeps_only_backup_keep(client, monkeypatch, tmp_path):
    db_path = tmp_path / "app.db"
    backup_dir = tmp_path / "backups"
    db_path.write_text("sqlite test db")

    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setattr(settings, "BACKUP_DIR", str(backup_dir))
    monkeypatch.setattr(settings, "BACKUP_KEEP", 3)

    created: list[Path] = []
    for _ in range(settings.BACKUP_KEEP + 1):
        path = backup_database()
        assert path is not None
        created.append(path)

    backups = list_backups()
    assert len(backups) == settings.BACKUP_KEEP
    assert created[-1] in backups  # последняя копия должна остаться
    assert created[0] not in backups  # самая старая должна быть удалена


def test_restore_database_replaces_current_db(client, monkeypatch, tmp_path):
    db_path = tmp_path / "app.db"
    backup_dir = tmp_path / "backups"
    db_path.write_text("current data")

    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setattr(settings, "BACKUP_DIR", str(backup_dir))

    backup_path = backup_database()
    assert backup_path is not None

    db_path.write_text("corrupted data")
    restore_database(backup_path)

    assert db_path.read_text() == "current data"


def test_backup_page_requires_auth(client):
    response = client.get("/backups", follow_redirects=False)
    assert response.status_code == 302


def test_backup_page(client):
    client.post("/login", data={"password": "admin"})
    response = client.get("/backups")
    assert response.status_code == 200
    assert "Бэкапы" in response.text


def test_api_backups(client, monkeypatch, tmp_path):
    db_path = tmp_path / "app.db"
    backup_dir = tmp_path / "backups"
    db_path.write_text("sqlite test db")

    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setattr(settings, "BACKUP_DIR", str(backup_dir))

    backup_database()

    client.post("/login", data={"password": "admin"})
    response = client.get("/api/backups")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["filename"].startswith("app_")
    assert data[0]["size_bytes"] > 0
