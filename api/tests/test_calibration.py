"""热电偶校准核验 API 测试：真实 FastAPI 应用 + 真实 SQLite 落库。"""

import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import app


def payload(
    probe_id="TC-1",
    calibrated_at="2026-09-12T10:00:00Z",
    tolerance=2.0,
    groups=None,
):
    if groups is None:
        groups = [
            {"set_temperature": 100, "indicator_reading": 101, "standard_reading": 100},
            {"set_temperature": 500, "indicator_reading": 502, "standard_reading": 500},
            {"set_temperature": 1000, "indicator_reading": 998, "standard_reading": 1000},
        ]
    return {
        "probe_id": probe_id,
        "calibrated_at": calibrated_at,
        "tolerance": tolerance,
        "groups": groups,
    }


@pytest.fixture()
def client(isolated_db):
    with TestClient(app) as test_client:
        yield test_client


class TestQualifiedBoundary:
    def test_max_abs_equal_to_tolerance_is_qualified(self, client):
        # 各组误差 +1 / +2 / -2，最大绝对误差恰为 2.0 == 允许偏差 -> 合格
        response = client.post("/api/calibrations", json=payload())
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["indication_errors"] == [1.0, 2.0, -2.0]
        assert body["max_abs_error"] == 2.0
        assert body["verdict"] == "qualified"
        assert body["verdict_label"] == "合格"
        assert body["group_count"] == 3
        assert body["groups"][1]["indication_error"] == 2.0
        assert body["id"] is not None

    def test_decimal_boundary_exact_equality_is_qualified(self, client):
        # 误差恰为 2.5（0.1 不能用二进制浮点精确表示），允许偏差 2.5 -> 合格
        groups = [
            {"set_temperature": 100.0, "indicator_reading": 102.5, "standard_reading": 100.0},
            {"set_temperature": 200.0, "indicator_reading": 200.0, "standard_reading": 200.0},
            {"set_temperature": 300.0, "indicator_reading": 300.0, "standard_reading": 300.0},
        ]
        response = client.post(
            "/api/calibrations", json=payload(tolerance=2.5, groups=groups)
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["max_abs_error"] == 2.5
        assert body["verdict"] == "qualified"

    def test_persisted_detail_reopened_after_reload(self, client):
        created = client.post("/api/calibrations", json=payload()).json()
        # 模拟刷新/重启：新的 TestClient 仍能按编号打开
        with TestClient(app) as reopened:
            detail = reopened.get(f"/api/calibrations/{created['id']}").json()
        assert detail["id"] == created["id"]
        assert detail["probe_id"] == "TC-1"
        assert detail["calibrated_at"] == "2026-09-12T10:00:00Z"
        assert detail["tolerance"] == 2.0
        assert detail["indication_errors"] == [1.0, 2.0, -2.0]
        assert detail["max_abs_error"] == 2.0
        assert detail["verdict"] == "qualified"
        assert detail["verdict_label"] == "合格"
        # 原始读数逐字保留，逐组带 index 与示值误差作为判定依据
        assert detail["groups"][0] == {
            "index": 0,
            "set_temperature": 100,
            "indicator_reading": 101,
            "standard_reading": 100,
            "indication_error": 1.0,
        }
        assert detail["created_at"] == created["created_at"]
        assert db.count_calibrations() == 1


class TestUnqualified:
    def test_single_point_exceeding_tolerance_is_unqualified(self, client):
        groups = [
            {"set_temperature": 100, "indicator_reading": 101, "standard_reading": 100},
            {"set_temperature": 500, "indicator_reading": 502, "standard_reading": 500},
            {"set_temperature": 1000, "indicator_reading": 1003, "standard_reading": 1000},
        ]
        response = client.post(
            "/api/calibrations", json=payload(probe_id="TC-BAD", groups=groups)
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["indication_errors"] == [1.0, 2.0, 3.0]
        assert body["max_abs_error"] == 3.0
        assert body["verdict"] == "unqualified"
        assert body["verdict_label"] == "不合格"

    def test_negative_error_exceeding_is_unqualified(self, client):
        # 仪表偏低 -2.1，绝对值超差
        groups = [
            {"set_temperature": 100, "indicator_reading": 97.9, "standard_reading": 100},
            {"set_temperature": 200, "indicator_reading": 200, "standard_reading": 200},
            {"set_temperature": 300, "indicator_reading": 300, "standard_reading": 300},
        ]
        body = client.post(
            "/api/calibrations", json=payload(probe_id="TC-LOW", tolerance=2, groups=groups)
        ).json()
        assert body["max_abs_error"] == 2.1
        assert body["verdict"] == "unqualified"


class TestValidation:
    def test_all_errors_collected_and_located(self, client):
        bad = {
            "probe_id": "   ",
            "calibrated_at": "not-a-time",
            "tolerance": -1,
            "groups": [
                # 第 0 组仪表读数越界
                {"set_temperature": 100, "indicator_reading": 1500, "standard_reading": 100},
                # 第 1 组设定温度不高于第 0 组 -> 非递增
                {"set_temperature": 100, "indicator_reading": 100, "standard_reading": 100},
                # 第 2 组标准器读数越下限
                {"set_temperature": 1000, "indicator_reading": 1000, "standard_reading": -5},
            ],
        }
        response = client.post("/api/calibrations", json=bad)
        assert response.status_code == 422
        errors = response.json()["detail"]["errors"]
        located = {(e["index"], e["field"]) for e in errors}
        assert (None, "probe_id") in located
        assert (None, "calibrated_at") in located
        assert (None, "tolerance") in located
        assert (0, "indicator_reading") in located
        assert (1, "set_temperature") in located
        assert (2, "standard_reading") in located
        assert db.count_calibrations() == 0

    def test_group_count_out_of_range_rejected(self, client):
        g = {
            "set_temperature": 100,
            "indicator_reading": 100,
            "standard_reading": 100,
        }
        for count in (0, 2, 13):
            body = payload(groups=[{**g, "set_temperature": 100 * i + 1} for i in range(count)])
            response = client.post("/api/calibrations", json=body)
            assert response.status_code == 422, count
            assert any(e["field"] == "groups" for e in response.json()["detail"]["errors"])
        assert db.count_calibrations() == 0

    def test_group_count_three_and_twelve_accepted(self, client):
        g = lambda t: {  # noqa: E731
            "set_temperature": t,
            "indicator_reading": t,
            "standard_reading": t,
        }
        for count in (3, 12):
            response = client.post(
                "/api/calibrations",
                json=payload(probe_id=f"TC-N{count}", groups=[g(100 * i + 1) for i in range(count)]),
            )
            assert response.status_code == 201, (count, response.text)
        assert db.count_calibrations() == 2

    def test_reading_outside_range_rejected(self, client):
        for field, value in (
            ("set_temperature", 1401),
            ("indicator_reading", -0.1),
            ("standard_reading", 1400.5),
        ):
            groups = [
                {"set_temperature": 100, "indicator_reading": 100, "standard_reading": 100},
                {"set_temperature": 200, "indicator_reading": 200, "standard_reading": 200},
                {"set_temperature": 300, "indicator_reading": 300, "standard_reading": 300},
            ]
            groups[0][field] = value
            response = client.post(
                "/api/calibrations", json=payload(probe_id=f"TC-{field}", groups=groups)
            )
            assert response.status_code == 422, field
            assert (0, field) in {
                (e["index"], e["field"])
                for e in response.json()["detail"]["errors"]
            }
        assert db.count_calibrations() == 0

    def test_non_positive_tolerance_rejected(self, client):
        for tolerance in (0, -2):
            response = client.post(
                "/api/calibrations", json=payload(tolerance=tolerance)
            )
            assert response.status_code == 422, tolerance
            assert response.json()["detail"]["errors"][0]["field"] == "tolerance"
        assert db.count_calibrations() == 0

    def test_non_numeric_and_nan_rejected(self, client):
        groups = [
            {"set_temperature": "热", "indicator_reading": 100, "standard_reading": 100},
            {"set_temperature": 200, "indicator_reading": True, "standard_reading": 200},
            {"set_temperature": 300, "indicator_reading": 300, "standard_reading": 300},
        ]
        response = client.post(
            "/api/calibrations", json=payload(probe_id="TC-NAN", groups=groups)
        )
        assert response.status_code == 422
        located = {
            (e["index"], e["field"]) for e in response.json()["detail"]["errors"]
        }
        assert (0, "set_temperature") in located
        assert (1, "indicator_reading") in located  # bool 不接受
        assert db.count_calibrations() == 0

    def test_malformed_body_rejected(self, client):
        response = client.post("/api/calibrations", json=[])
        assert response.status_code == 422
        assert db.count_calibrations() == 0


class TestDuplicate:
    def test_same_probe_and_calibration_time_conflicts(self, client):
        first = client.post("/api/calibrations", json=payload())
        assert first.status_code == 201

        # 同探头、同校准时间（即使读数不同）-> 409，定位到探头编号
        groups2 = [
            {"set_temperature": 100, "indicator_reading": 100, "standard_reading": 100},
            {"set_temperature": 500, "indicator_reading": 501, "standard_reading": 500},
            {"set_temperature": 1000, "indicator_reading": 999, "standard_reading": 1000},
        ]
        response = client.post(
            "/api/calibrations", json=payload(groups=groups2)
        )
        assert response.status_code == 409, response.text
        detail = response.json()["detail"]
        assert detail["reason"] == "duplicate_calibration"
        assert detail["errors"][0]["field"] == "probe_id"
        assert db.count_calibrations() == 1

    def test_same_instant_different_timezone_is_duplicate(self, client):
        client.post("/api/calibrations", json=payload(calibrated_at="2026-09-12T10:00:00Z"))
        # 同一瞬时的 +08:00 表示（18:00+08:00 == 10:00Z）也算重复
        response = client.post(
            "/api/calibrations",
            json=payload(calibrated_at="2026-09-12T18:00:00+08:00"),
        )
        assert response.status_code == 409
        assert db.count_calibrations() == 1

    def test_different_probe_or_time_allowed(self, client):
        client.post("/api/calibrations", json=payload(probe_id="TC-A"))
        # 不同探头、同时间
        assert client.post(
            "/api/calibrations", json=payload(probe_id="TC-B")
        ).status_code == 201
        # 同探头、不同时间
        assert client.post(
            "/api/calibrations",
            json=payload(probe_id="TC-A", calibrated_at="2026-09-13T10:00:00Z"),
        ).status_code == 201
        assert db.count_calibrations() == 3


class TestDetailNotFound:
    def test_missing_calibration_is_404(self, client):
        response = client.get("/api/calibrations/999")
        assert response.status_code == 404
        assert response.json()["detail"]["reason"] == "calibration_not_found"


class TestExistingBatchFlowUnaffected:
    """核验单功能不影响既有窑次提交、复算与对比。"""

    def test_batch_create_and_count_independent(self, client):
        assert client.post(
            "/api/calibrations", json=payload()
        ).status_code == 201
        batch_payload = {
            "name": "K-AFTER-CAL",
            "points": [
                {"time": "2026-09-11T08:00:00Z", "temperature": 600},
                {"time": "2026-09-11T13:00:00Z", "temperature": 600},
            ],
        }
        response = client.post("/api/batches", json=batch_payload)
        assert response.status_code == 201
        assert response.json()["verdict"] == "underfired"
        # 两类记录互不串扰
        assert db.count_batches() == 1
        assert db.count_calibrations() == 1
        listing = client.get("/api/batches").json()["batches"]
        assert [b["name"] for b in listing] == ["K-AFTER-CAL"]
