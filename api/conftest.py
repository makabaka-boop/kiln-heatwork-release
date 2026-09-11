import pytest

from app import db


@pytest.fixture()
def isolated_db(tmp_path, monkeypatch):
    """每个测试用独立的 SQLite 文件，模拟真实落库。"""
    monkeypatch.setenv("HEATWORK_DB", str(tmp_path / "test.db"))
    db.init_db()
    yield
