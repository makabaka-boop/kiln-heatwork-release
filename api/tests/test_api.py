"""API 联调测试：真实 FastAPI 应用 + 真实 SQLite 落库。"""

import json
import sqlite3

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


class TestSegmentBreakdown:
    """逐相邻段计热贡献明细：创建与详情响应均携带，且与总积分一致。"""

    CURVE = [
        {"time": "2026-09-11T08:00:00Z", "temperature": 600},
        {"time": "2026-09-11T10:00:00Z", "temperature": 700},
        {"time": "2026-09-11T12:00:00Z", "temperature": 700},
        {"time": "2026-09-11T13:00:00Z", "temperature": 600},
    ]

    def test_create_returns_segment_breakdown(self, client):
        body = client.post(
            "/api/batches", json={"name": "K-seg", "points": self.CURVE}
        ).json()
        assert body["segments_note"] is None
        segments = body["segments"]
        assert [s["index"] for s in segments] == [0, 1, 2]
        assert [(s["start_time"], s["end_time"]) for s in segments] == [
            ("2026-09-11T08:00:00Z", "2026-09-11T10:00:00Z"),
            ("2026-09-11T10:00:00Z", "2026-09-11T12:00:00Z"),
            ("2026-09-11T12:00:00Z", "2026-09-11T13:00:00Z"),
        ]
        assert [s["heating_minutes"] for s in segments] == [120, 120, 60]
        assert [s["contribution"] for s in segments] == [6000, 12000, 3000]
        # 各段贡献之和 == 既有未舍入总积分
        assert sum(s["contribution"] for s in segments) == body["integral_raw"]
        assert sum(s["share"] for s in segments) == pytest.approx(1.0)
        assert segments[0]["share"] == pytest.approx(6000 / 21000)

    def test_detail_returns_same_segments(self, client):
        created = client.post(
            "/api/batches", json={"name": "K-seg", "points": self.CURVE}
        ).json()
        detail = client.get(f"/api/batches/{created['id']}").json()
        assert detail["segments"] == created["segments"]
        assert detail["segments_note"] is None

    def test_crossing_segment_reports_split_minutes(self, client):
        # 500 -> 700 用 60 min，30 min 处越过 600°C：切段分钟数 30
        payload = {
            "name": "K-cross",
            "points": [
                {"time": "2026-09-11T00:00:00Z", "temperature": 500.0},
                {"time": "2026-09-11T01:00:00Z", "temperature": 700.0},
            ],
        }
        body = client.post("/api/batches", json=payload).json()
        (segment,) = body["segments"]
        assert segment["heating_minutes"] == 30
        assert segment["contribution"] == 1500
        assert segment["share"] == 1.0

    def test_all_below_base_keeps_zero_contribution_segments(self, client):
        payload = {
            "name": "K-cold",
            "points": [
                {"time": "2026-09-11T00:00:00Z", "temperature": 500.0},
                {"time": "2026-09-11T02:00:00Z", "temperature": 550.0},
            ],
        }
        body = client.post("/api/batches", json=payload).json()
        assert body["integral_raw"] == 0
        (segment,) = body["segments"]
        assert segment["contribution"] == 0
        assert segment["heating_minutes"] == 0
        assert segment["share"] == 0

    def test_list_response_unchanged(self, client):
        client.post("/api/batches", json={"name": "K-seg", "points": self.CURVE})
        (item,) = client.get("/api/batches").json()["batches"]
        assert set(item) == {
            "id",
            "name",
            "point_count",
            "integral_raw",
            "integral_display",
            "verdict",
            "verdict_label",
            "created_at",
        }


# 升级前的旧表结构（无 segments_json 列）
_LEGACY_SCHEMA = """
CREATE TABLE batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    points_json TEXT NOT NULL,
    point_count INTEGER NOT NULL,
    integral_raw REAL NOT NULL,
    integral_display TEXT NOT NULL,
    verdict TEXT NOT NULL,
    created_at TEXT NOT NULL
)
"""

_LEGACY_OK_POINTS = [
    {"time": "2026-09-11T08:00:00Z", "temperature": 600},
    {"time": "2026-09-11T10:00:00Z", "temperature": 700},
    {"time": "2026-09-11T12:00:00Z", "temperature": 700},
    {"time": "2026-09-11T13:00:00Z", "temperature": 600},
]

# 旧记录中无法形成合法时间序列的采样点（时刻不可解析）
_LEGACY_BROKEN_POINTS = [
    {"time": "not-a-timestamp", "temperature": 700},
    {"time": "2026-09-11T01:00:00Z", "temperature": 700},
]


@pytest.fixture()
def legacy_db(tmp_path, monkeypatch):
    """模拟升级前的旧库：旧表结构 + 两条无分段明细的历史记录。"""
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.executescript(_LEGACY_SCHEMA)
    created = "2026-09-10T00:00:00+00:00"
    insert = (
        "INSERT INTO batches (name, points_json, point_count, integral_raw,"
        " integral_display, verdict, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)"
    )
    conn.execute(
        insert,
        ("LEGACY-OK", json.dumps(_LEGACY_OK_POINTS), 4, 21000.0, "21000.0",
         "qualified", created),
    )
    conn.execute(
        insert,
        ("LEGACY-BROKEN", json.dumps(_LEGACY_BROKEN_POINTS), 2, 1500.0, "1500.0",
         "underfired", created),
    )
    conn.commit()
    conn.close()
    monkeypatch.setenv("HEATWORK_DB", str(path))
    db.init_db()  # 触发就地升级
    yield path


@pytest.fixture()
def legacy_client(legacy_db):
    with TestClient(app) as test_client:
        yield test_client


class TestLegacyMigration:
    def test_migration_adds_column_and_keeps_rows(self, legacy_db, legacy_client):
        columns = {
            row[1]
            for row in sqlite3.connect(legacy_db).execute(
                "PRAGMA table_info(batches)"
            )
        }
        assert "segments_json" in columns
        # 旧记录照常出现在列表中，响应字段保持兼容
        listing = legacy_client.get("/api/batches").json()["batches"]
        assert [b["name"] for b in listing] == ["LEGACY-BROKEN", "LEGACY-OK"]
        for item in listing:
            assert {
                "id",
                "name",
                "point_count",
                "integral_raw",
                "integral_display",
                "verdict",
                "verdict_label",
                "created_at",
            } <= set(item)

    def test_legacy_detail_recomputes_segments_without_rewrite(
        self, legacy_db, legacy_client
    ):
        detail = legacy_client.get("/api/batches/1").json()
        # 原结论与积分保持不动
        assert detail["verdict"] == "qualified"
        assert detail["integral_display"] == "21000.0"
        assert detail["integral_raw"] == 21000.0
        # 依据已存原始点确定性补算明细
        assert detail["segments_note"] is None
        segments = detail["segments"]
        assert [s["heating_minutes"] for s in segments] == [120, 120, 60]
        assert [s["contribution"] for s in segments] == [6000, 12000, 3000]
        assert sum(s["contribution"] for s in segments) == detail["integral_raw"]
        # 读取不回写：库里 segments_json 仍为 NULL，原结论字段原样保留
        row = sqlite3.connect(legacy_db).execute(
            "SELECT integral_raw, integral_display, verdict, segments_json"
            " FROM batches WHERE id = 1"
        ).fetchone()
        assert row == (21000.0, "21000.0", "qualified", None)

    def test_legacy_detail_with_broken_series_keeps_verdict_and_explains(
        self, legacy_client
    ):
        response = legacy_client.get("/api/batches/2")
        assert response.status_code == 200
        detail = response.json()
        # 原判定照常展示，明细区域说明无法生成的原因
        assert detail["verdict"] == "underfired"
        assert detail["verdict_label"] == "欠烧"
        assert detail["integral_display"] == "1500.0"
        assert detail["segments"] is None
        assert "无法" in detail["segments_note"]

    def test_new_submission_after_migration_stores_segments(self, legacy_client):
        payload = constant_batch("K-after-upgrade", 660.0, 300)
        response = legacy_client.post("/api/batches", json=payload)
        assert response.status_code == 201
        (segment,) = response.json()["segments"]
        assert segment["contribution"] == 18000.0
