import pytest

from app.core.config import DatabaseSettings


def test_database_settings_keeps_sqlite_default(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert DatabaseSettings.from_env().url == "sqlite:///./test.db"


def test_database_settings_accepts_compose_postgres(monkeypatch):
    url = "postgresql+psycopg://agentic:secret@postgres:5432/agentic"
    monkeypatch.setenv("DATABASE_URL", url)
    assert DatabaseSettings.from_env().url == url


def test_database_settings_rejects_other_drivers(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/agentic")
    with pytest.raises(ValueError):
        DatabaseSettings.from_env()
