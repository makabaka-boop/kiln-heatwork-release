"""轨迹对比：纯曲线/对比逻辑与对比接口的落库联调测试。"""

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from fractions import Fraction

import pytest
from fastapi.testclient import TestClient

from app import db
from app.compare import (
    build_curve,
    compare_curves,
    heatwork_at,
    temperature_at,
)
from app.heatwork import compute_heatwork
from app.main import app

T0 = datetime(2026, 9, 11, 8, 0, tzinfo=timezone.utc)


def at(minutes=0):
    return T0 + timedelta(minutes=minutes)


# README 同款曲线：600 -> 700（120 min）-> 700（120 min）-> 600（60 min）
STANDARD_CURVE = [
    (at(0), 600.0),
    (at(120), 700.0),
    (at(240), 700.0),
    (at(300), 600.0),
]

# 同一轨迹按 30 min 加密采样（各点都落在 STANDARD_CURVE 的折线上）
DENSE_CURVE = [
    (at(0), 600.0),
    (at(30), 625.0),
    (at(60), 650.0),
    (at(90), 675.0),
    (at(120), 700.0),
    (at(150), 700.0),
    (at(180), 700.0),
    (at(210), 700.0),
    (at(240), 700.0),
    (at(270), 650.0),
    (at(300), 600.0),
]

# 局部升温偏差：前 60 min 就升到 700°C，之后与标准曲线一致
DEVIATED_CURVE = [
    (at(0), 600.0),
    (at(30), 650.0),
    (at(60), 700.0),
    (at(120), 700.0),
    (at(240), 700.0),
    (at(300), 600.0),
]

# 含小数温度的等价轨迹：600 -> 603.6（30 min）-> 603.6（60 min），
# 分别按 30 min 与 10 min 采样，加密点十进制取值都落在同一折线上
DECIMAL_COARSE_CURVE = [
    (at(0), 600.0),
    (at(30), 603.6),
    (at(90), 603.6),
]
DECIMAL_DENSE_CURVE = [
    (at(0), 600.0),
    (at(10), 601.2),
    (at(20), 602.4),
    (at(30), 603.6),
    (at(60), 603.6),
    (at(90), 603.6),
]


class TestCurve:
    def test_elapsed_minutes_aligned_to_first_sample(self):
        curve = build_curve(STANDARD_CURVE)
        assert curve.elapsed_minutes == (0, 120, 240, 300)
        assert curve.span_minutes == 300

    def test_prefix_heatwork_matches_total_integral(self):
        curve = build_curve(STANDARD_CURVE)
        assert curve.heatwork_prefix[-1] == compute_heatwork(STANDARD_CURVE)
        assert curve.heatwork_prefix == (0, 6000, 18000, 21000)

    def test_temperature_at_interpolates_linearly(self):
        curve = build_curve(STANDARD_CURVE)
        assert temperature_at(curve, Fraction(0)) == 600
        assert temperature_at(curve, Fraction(30)) == 625
        assert temperature_at(curve, Fraction(270)) == 650
        assert temperature_at(curve, Fraction(300)) == 600

    def test_heatwork_at_interpolates_partial_segment(self):
        curve = build_curve(STANDARD_CURVE)
        # 30 min 处超出量 25：三角形 25*30/2 = 375
        assert heatwork_at(curve, Fraction(30)) == 375
        # 270 min 处：18000 + 下降段前 30 min（超出量 100 -> 50）
        assert heatwork_at(curve, Fraction(270)) == 18000 + (100 + 50) * 30 // 2
        assert heatwork_at(curve, Fraction(300)) == 21000

    def test_single_point_curve_has_zero_span(self):
        curve = build_curve([(at(0), 700.0)])
        assert curve.span_minutes == 0
        assert temperature_at(curve, Fraction(0)) == 700
        assert heatwork_at(curve, Fraction(0)) == 0


class TestCompareCurves:
    def test_equivalent_trajectories_differently_sampled_give_zero_deltas(self):
        comparison = compare_curves(
            build_curve(STANDARD_CURVE), build_curve(DENSE_CURVE)
        )
        assert comparison is not None
        assert comparison.common_minutes == 300
        # 时间轴为双方采样时刻的并集（加密曲线的 11 个节点）
        assert [float(node.elapsed_minutes) for node in comparison.nodes] == [
            0, 30, 60, 90, 120, 150, 180, 210, 240, 270, 300
        ]
        for node in comparison.nodes:
            assert node.temperature_delta == 0
            assert node.heatwork_delta == 0

    def test_decimal_temperatures_equivalent_trajectories_give_zero_deltas(self):
        # 含小数温度的等价轨迹：中间对齐节点的差值必须严格为零，
        # 不允许浮点二进制展开带来微小非零差值
        comparison = compare_curves(
            build_curve(DECIMAL_COARSE_CURVE), build_curve(DECIMAL_DENSE_CURVE)
        )
        assert comparison is not None
        assert comparison.common_minutes == 90
        assert [float(node.elapsed_minutes) for node in comparison.nodes] == [
            0, 10, 20, 30, 60, 90
        ]
        for node in comparison.nodes:
            assert node.temperature_delta == 0
            assert node.heatwork_delta == 0

    def test_local_deviation_sign_and_values(self):
        comparison = compare_curves(
            build_curve(DEVIATED_CURVE), build_curve(STANDARD_CURVE)
        )
        assert comparison is not None
        nodes = {float(n.elapsed_minutes): n for n in comparison.nodes}
        assert sorted(nodes) == [0, 30, 60, 120, 240, 300]
        # 温度差：偏差段为正，回到同一轨迹后为 0
        assert nodes[0].temperature_delta == 0
        assert nodes[30].temperature_delta == 25
        assert nodes[60].temperature_delta == 50
        assert nodes[120].temperature_delta == 0
        assert nodes[300].temperature_delta == 0
        # 累计计热差：偏差段逐步拉大，之后保持 +3000
        assert nodes[0].heatwork_delta == 0
        assert nodes[30].heatwork_delta == 375
        assert nodes[60].heatwork_delta == 1500
        assert nodes[120].heatwork_delta == 3000
        assert nodes[240].heatwork_delta == 3000
        assert nodes[300].heatwork_delta == 3000

    def test_common_interval_limited_by_shorter_curve(self):
        shorter = [(at(0), 600.0), (at(120), 700.0)]
        comparison = compare_curves(
            build_curve(STANDARD_CURVE), build_curve(shorter)
        )
        assert comparison is not None
        assert comparison.common_minutes == 120
        # 只保留共同区间内的节点
        assert [float(n.elapsed_minutes) for n in comparison.nodes] == [0, 120]
        for node in comparison.nodes:
            assert node.temperature_delta == 0
            assert node.heatwork_delta == 0

    def test_zero_span_curve_yields_no_common_interval(self):
        single = build_curve([(at(0), 700.0)])
        assert compare_curves(single, build_curve(STANDARD_CURVE)) is None
        assert compare_curves(build_curve(STANDARD_CURVE), single) is None
        assert compare_curves(single, single) is None


# ---------- 对比接口 ----------

STANDARD_PAYLOAD = [
    {"time": "2026-09-11T08:00:00Z", "temperature": 600},
    {"time": "2026-09-11T10:00:00Z", "temperature": 700},
    {"time": "2026-09-11T12:00:00Z", "temperature": 700},
    {"time": "2026-09-11T13:00:00Z", "temperature": 600},
]

DENSE_PAYLOAD = [
    {"time": "2026-09-11T08:00:00Z", "temperature": 600},
    {"time": "2026-09-11T08:30:00Z", "temperature": 625},
    {"time": "2026-09-11T09:00:00Z", "temperature": 650},
    {"time": "2026-09-11T09:30:00Z", "temperature": 675},
    {"time": "2026-09-11T10:00:00Z", "temperature": 700},
    {"time": "2026-09-11T10:30:00Z", "temperature": 700},
    {"time": "2026-09-11T11:00:00Z", "temperature": 700},
    {"time": "2026-09-11T11:30:00Z", "temperature": 700},
    {"time": "2026-09-11T12:00:00Z", "temperature": 700},
    {"time": "2026-09-11T12:30:00Z", "temperature": 650},
    {"time": "2026-09-11T13:00:00Z", "temperature": 600},
]

DEVIATED_PAYLOAD = [
    {"time": "2026-09-11T08:00:00Z", "temperature": 600},
    {"time": "2026-09-11T08:30:00Z", "temperature": 650},
    {"time": "2026-09-11T09:00:00Z", "temperature": 700},
    {"time": "2026-09-11T10:00:00Z", "temperature": 700},
    {"time": "2026-09-11T12:00:00Z", "temperature": 700},
    {"time": "2026-09-11T13:00:00Z", "temperature": 600},
]

# 含小数温度的等价轨迹（30 min 与 10 min 两种采样频率）
DECIMAL_COARSE_PAYLOAD = [
    {"time": "2026-09-11T08:00:00Z", "temperature": 600.0},
    {"time": "2026-09-11T08:30:00Z", "temperature": 603.6},
    {"time": "2026-09-11T09:30:00Z", "temperature": 603.6},
]
DECIMAL_DENSE_PAYLOAD = [
    {"time": "2026-09-11T08:00:00Z", "temperature": 600.0},
    {"time": "2026-09-11T08:10:00Z", "temperature": 601.2},
    {"time": "2026-09-11T08:20:00Z", "temperature": 602.4},
    {"time": "2026-09-11T08:30:00Z", "temperature": 603.6},
    {"time": "2026-09-11T08:50:00Z", "temperature": 603.6},
    {"time": "2026-09-11T09:30:00Z", "temperature": 603.6},
]


@pytest.fixture()
def client(isolated_db):
    with TestClient(app) as test_client:
        yield test_client


def create(client, name, points):
    response = client.post("/api/batches", json={"name": name, "points": points})
    assert response.status_code == 201
    return response.json()


class TestCompareEndpoint:
    def test_equivalent_trajectories_all_zero_deltas(self, client):
        current = create(client, "K-std", STANDARD_PAYLOAD)
        reference = create(client, "K-dense", DENSE_PAYLOAD)
        before = db.count_batches()

        response = client.get(f"/api/batches/{current['id']}/compare/{reference['id']}")
        assert response.status_code == 200
        body = response.json()
        # 只返回对齐节点、两类差值及双方摘要
        assert set(body) == {"batch", "reference", "common_minutes", "nodes"}
        assert body["common_minutes"] == 300
        assert body["batch"]["id"] == current["id"]
        assert body["batch"]["name"] == "K-std"
        assert body["batch"]["verdict_label"] == "合格"
        assert body["reference"]["id"] == reference["id"]
        assert body["reference"]["name"] == "K-dense"
        assert [node["elapsed_minutes"] for node in body["nodes"]] == [
            0, 30, 60, 90, 120, 150, 180, 210, 240, 270, 300
        ]
        for node in body["nodes"]:
            assert node["temperature_delta"] == 0
            assert node["heatwork_delta"] == 0
        # 对比为只读：记录数不变
        assert db.count_batches() == before

    def test_local_deviation_sign_and_values(self, client):
        current = create(client, "K-dev", DEVIATED_PAYLOAD)
        reference = create(client, "K-std", STANDARD_PAYLOAD)

        response = client.get(f"/api/batches/{current['id']}/compare/{reference['id']}")
        assert response.status_code == 200
        nodes = {n["elapsed_minutes"]: n for n in response.json()["nodes"]}
        assert sorted(nodes) == [0, 30, 60, 120, 240, 300]
        assert nodes[30]["temperature_delta"] == 25
        assert nodes[60]["temperature_delta"] == 50
        assert nodes[120]["temperature_delta"] == 0
        assert nodes[30]["heatwork_delta"] == 375
        assert nodes[60]["heatwork_delta"] == 1500
        assert nodes[120]["heatwork_delta"] == 3000
        assert nodes[300]["heatwork_delta"] == 3000

        # 反向对比：符号全部取反
        response = client.get(f"/api/batches/{reference['id']}/compare/{current['id']}")
        assert response.status_code == 200
        reversed_nodes = {n["elapsed_minutes"]: n for n in response.json()["nodes"]}
        assert reversed_nodes[30]["temperature_delta"] == -25
        assert reversed_nodes[60]["heatwork_delta"] == -1500
        assert reversed_nodes[300]["heatwork_delta"] == -3000

    def test_missing_record_returns_404_reason(self, client):
        current = create(client, "K-std", STANDARD_PAYLOAD)
        response = client.get(f"/api/batches/{current['id']}/compare/999")
        assert response.status_code == 404
        assert response.json()["detail"]["reason"] == "batch_not_found"

        response = client.get(f"/api/batches/999/compare/{current['id']}")
        assert response.status_code == 404
        assert response.json()["detail"]["reason"] == "batch_not_found"

    def test_compare_does_not_change_existing_responses(self, client):
        current = create(client, "K-std", STANDARD_PAYLOAD)
        reference = create(client, "K-dev", DEVIATED_PAYLOAD)
        detail_before = client.get(f"/api/batches/{current['id']}").json()
        list_before = client.get("/api/batches").json()

        response = client.get(f"/api/batches/{current['id']}/compare/{reference['id']}")
        assert response.status_code == 200

        # 既有创建/列表/详情响应不受对比影响
        assert client.get("/api/batches").json() == list_before
        assert client.get(f"/api/batches/{current['id']}").json() == detail_before

    def test_decimal_temperatures_all_zero_deltas(self, client):
        # 含小数温度的等价轨迹经接口对比：各节点差值严格为零
        current = create(client, "K-dec-coarse", DECIMAL_COARSE_PAYLOAD)
        reference = create(client, "K-dec-dense", DECIMAL_DENSE_PAYLOAD)

        response = client.get(f"/api/batches/{current['id']}/compare/{reference['id']}")
        assert response.status_code == 200
        body = response.json()
        assert body["common_minutes"] == 90
        assert [node["elapsed_minutes"] for node in body["nodes"]] == [
            0, 10, 20, 30, 50, 90
        ]
        for node in body["nodes"]:
            assert node["temperature_delta"] == 0
            assert node["heatwork_delta"] == 0


class TestCompareQueryEntry:
    """约定查询式入口：GET /api/batches/{id}/compare?reference_id=..."""

    def test_query_entry_returns_common_interval_and_nodes(self, client):
        current = create(client, "K-std", STANDARD_PAYLOAD)
        reference = create(client, "K-dense", DENSE_PAYLOAD)

        response = client.get(
            f"/api/batches/{current['id']}/compare",
            params={"reference_id": reference["id"]},
        )
        assert response.status_code == 200
        body = response.json()
        # 与路径式入口结果完全一致：共同区间、逐节点差值与双方摘要
        path_body = client.get(
            f"/api/batches/{current['id']}/compare/{reference['id']}"
        ).json()
        assert body == path_body
        assert body["common_minutes"] == 300
        assert body["batch"]["id"] == current["id"]
        assert body["reference"]["id"] == reference["id"]
        for node in body["nodes"]:
            assert node["temperature_delta"] == 0
            assert node["heatwork_delta"] == 0

    def test_query_entry_missing_record_returns_404_reason(self, client):
        current = create(client, "K-std", STANDARD_PAYLOAD)
        response = client.get(
            f"/api/batches/{current['id']}/compare", params={"reference_id": 999}
        )
        assert response.status_code == 404
        assert response.json()["detail"]["reason"] == "batch_not_found"

        response = client.get(
            "/api/batches/999/compare", params={"reference_id": current["id"]}
        )
        assert response.status_code == 404
        assert response.json()["detail"]["reason"] == "batch_not_found"

    def test_query_entry_decimal_temperatures_zero_deltas(self, client):
        current = create(client, "K-dec-coarse", DECIMAL_COARSE_PAYLOAD)
        reference = create(client, "K-dec-dense", DECIMAL_DENSE_PAYLOAD)

        response = client.get(
            f"/api/batches/{current['id']}/compare",
            params={"reference_id": reference["id"]},
        )
        assert response.status_code == 200
        for node in response.json()["nodes"]:
            assert node["temperature_delta"] == 0
            assert node["heatwork_delta"] == 0


# 升级前旧表结构（无 segments_json 等后增列）
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


@pytest.fixture()
def legacy_client(tmp_path, monkeypatch):
    """旧库：一条时刻不可解析的记录 + 一条只有单个采样点的记录。"""
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
        (
            "LEGACY-BROKEN",
            json.dumps(
                [
                    {"time": "not-a-timestamp", "temperature": 700},
                    {"time": "2026-09-11T01:00:00Z", "temperature": 700},
                ]
            ),
            2,
            1500.0,
            "1500.0",
            "underfired",
            created,
        ),
    )
    conn.execute(
        insert,
        (
            "LEGACY-SINGLE",
            json.dumps([{"time": "2026-09-11T01:00:00Z", "temperature": 700}]),
            1,
            0.0,
            "0.0",
            "underfired",
            created,
        ),
    )
    conn.commit()
    conn.close()
    monkeypatch.setenv("HEATWORK_DB", str(path))
    db.init_db()
    with TestClient(app) as test_client:
        yield test_client


class TestCompareLegacyFailures:
    def test_broken_series_returns_422_reason(self, legacy_client):
        ok = create(legacy_client, "K-std", STANDARD_PAYLOAD)
        before = db.count_batches()

        # 非法旧记录无论作为当前记录还是参照，都区分原因失败
        for url in (
            f"/api/batches/1/compare/{ok['id']}",
            f"/api/batches/{ok['id']}/compare/1",
        ):
            response = legacy_client.get(url)
            assert response.status_code == 422
            detail = response.json()["detail"]
            assert detail["reason"] == "series_invalid"
            assert "LEGACY-BROKEN" in detail["message"]
        # 失败不新增记录
        assert db.count_batches() == before

    def test_single_point_record_has_no_common_interval(self, legacy_client):
        ok = create(legacy_client, "K-std", STANDARD_PAYLOAD)
        response = legacy_client.get(f"/api/batches/{ok['id']}/compare/2")
        assert response.status_code == 422
        assert response.json()["detail"]["reason"] == "no_common_interval"

    def test_legacy_valid_record_compares_normally(self, legacy_client):
        # 合法旧记录（无分段明细列值）同样只按已存原始点参与对比
        conn = sqlite3.connect(db.db_path())
        with conn:
            conn.execute(
                "INSERT INTO batches (name, points_json, point_count,"
                " integral_raw, integral_display, verdict, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    "LEGACY-OK",
                    json.dumps(STANDARD_PAYLOAD),
                    4,
                    21000.0,
                    "21000.0",
                    "qualified",
                    "2026-09-10T00:00:00+00:00",
                ),
            )
        conn.close()
        current = create(legacy_client, "K-dense", DENSE_PAYLOAD)

        response = legacy_client.get(f"/api/batches/{current['id']}/compare/3")
        assert response.status_code == 200
        for node in response.json()["nodes"]:
            assert node["temperature_delta"] == 0
            assert node["heatwork_delta"] == 0
