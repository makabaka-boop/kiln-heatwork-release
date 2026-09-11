"""API 联调测试：真实 FastAPI 应用 + 真实 SQLite 落库。"""

import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import app


@pytest.fixture()
def client(isolated_db):
    with TestClient(app) as test_client:
        yield test_client


def constant_batch(name, temperature, minutes, start="2026-09-11T00:00:00Z"):
    """构造恒温批次的合法提交体。"""
    from datetime import datetime, timedelta, timezone

    t0 = datetime.fromisoformat(start.replace("Z", "+00:00"))
    t1 = t0 + timedelta(minutes=minutes)
    fmt = lambda dt: dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "name": name,
        "points": [
            {"time": fmt(t0), "temperature": temperature},
            {"time": fmt(t1), "temperature": temperature},
        ],
    }


class TestValidSubmission:
    def test_create_and_review_after_restart(self, client):
        payload = constant_batch("K-660-300", 660.0, 300)
        response = client.post("/api/batches", json=payload)
        assert response.status_code == 201
        body = response.json()
        assert body["integral_raw"] == 18000.0
        assert body["integral_display"] == "18000.0"
        assert body["verdict"] == "qualified"
        assert body["verdict_label"] == "合格"

        # 模拟刷新/重启：换一个 TestClient 实例，数据仍在
        with TestClient(app) as reopened:
            listing = reopened.get("/api/batches").json()["batches"]
            assert [b["id"] for b in listing] == [body["id"]]
            detail = reopened.get(f"/api/batches/{body['id']}").json()
            assert detail["points"] == payload["points"]
            assert detail["integral_raw"] == 18000.0
            assert detail["integral_display"] == "18000.0"
            assert detail["verdict_label"] == "合格"

    def test_raw_points_preserved_verbatim(self, client):
        payload = {
            "name": "K-raw",
            "points": [
                {"time": "2026-09-11T08:00:00+08:00", "temperature": 700},
                {"time": "2026-09-11T09:30:00+08:00", "temperature": 650.5},
            ],
        }
        created = client.post("/api/batches", json=payload).json()
        detail = client.get(f"/api/batches/{created['id']}").json()
        assert detail["points"] == payload["points"]


class TestVerdictBoundaries:
    @pytest.mark.parametrize(
        "temperature,minutes,display,verdict,label",
        [
            (689.9995, 200, "17999.9", "underfired", "欠烧"),
            (660.0, 300, "18000.0", "qualified", "合格"),
            (640.0, 600, "24000.0", "qualified", "合格"),
            (640.001, 600, "24000.6", "overfired", "过烧"),
        ],
    )
    def test_classification_edges(
        self, client, temperature, minutes, display, verdict, label
    ):
        payload = constant_batch("K-edge", temperature, minutes)
        body = client.post("/api/batches", json=payload).json()
        assert body["integral_display"] == display
        assert body["verdict"] == verdict
        assert body["verdict_label"] == label

    def test_crossing_segment_example(self, client):
        # README 示例：500 -> 700 用 60 min，积分恰为 1500.0 -> 欠烧
        payload = {
            "name": "K-cross",
            "points": [
                {"time": "2026-09-11T00:00:00Z", "temperature": 500.0},
                {"time": "2026-09-11T01:00:00Z", "temperature": 700.0},
            ],
        }
        body = client.post("/api/batches", json=payload).json()
        assert body["integral_display"] == "1500.0"
        assert body["verdict"] == "underfired"


class TestInvalidSubmission:
    def test_invalid_points_not_persisted_and_errors_located(self, client):
        payload = {
            "name": "K-bad",
            "points": [
                {"time": "2026-09-11T08:00:00Z", "temperature": 620.0},
                {"time": "2026-09-11T09:00:00Z", "temperature": 1500.0},
                {"time": "2026-09-11T08:30:00Z", "temperature": 640.0},
            ],
        }
        response = client.post("/api/batches", json=payload)
        assert response.status_code == 422
        errors = response.json()["detail"]["errors"]
        located = {(e["index"], e["field"]) for e in errors}
        assert (1, "temperature") in located
        assert (2, "time") in located
        assert db.count_batches() == 0

    def test_valid_then_invalid_keeps_only_valid(self, client):
        ok = constant_batch("K-ok", 660.0, 300)
        assert client.post("/api/batches", json=ok).status_code == 201
        bad = constant_batch("K-bad", 1600.0, 300)
        assert client.post("/api/batches", json=bad).status_code == 422
        assert db.count_batches() == 1
        listing = client.get("/api/batches").json()["batches"]
        assert [b["name"] for b in listing] == ["K-ok"]

    def test_malformed_body_rejected(self, client):
        response = client.post("/api/batches", json={"name": "K", "points": {}})
        assert response.status_code == 422
        assert db.count_batches() == 0

    def test_missing_batch_is_404(self, client):
        assert client.get("/api/batches/999").status_code == 404
