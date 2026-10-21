import pytest

from app import db


@pytest.fixture(autouse=True)
def temp_database(tmp_path, monkeypatch):
    """Every test gets its own empty database, so tests never touch the real one."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")