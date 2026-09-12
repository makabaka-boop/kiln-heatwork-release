"""一次性验收服务：对运行中的 web 与 api 做真实 HTTP 联调检查。

检查链路：verify -> web(nginx) -> api(FastAPI) -> SQLite，
并对关键结果用**独立重写的积分实现**复核，全部通过则以 0 退出。
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction

API_BASE = os.environ.get("API_BASE", "http://api:8000").rstrip("/")
WEB_BASE = os.environ.get("WEB_BASE", "http://web").rstrip("/")

FAILURES: list[str] = []


# ---------- 独立复写的计热实现（与被测服务无共享代码） ----------

def _minutes_of(delta: timedelta) -> Fraction:
    micros = delta.days * 86_400_000_000 + delta.seconds * 1_000_000 + delta.microseconds
    return Fraction(micros, 60_000_000)


def independent_segments(
    points: list[tuple[datetime, float]],
) -> list[tuple[Fraction, Fraction]]:
    """逐相邻段独立复算：返回 [(有效计热分钟数, 未舍入贡献)]。"""
    segments: list[tuple[Fraction, Fraction]] = []
    for (t0, temp0), (t1, temp1) in zip(points, points[1:]):
        dt_min = _minutes_of(t1 - t0)
        e0, e1 = Fraction(temp0) - 600, Fraction(temp1) - 600
        if e0 <= 0 and e1 <= 0:
            segments.append((Fraction(0), Fraction(0)))
        elif e0 > 0 and e1 > 0:
            segments.append((dt_min, (e0 + e1) * dt_min / 2))
        elif e0 > 0:
            s_star = e0 / (e0 - e1)
            segments.append((s_star * dt_min, e0 * s_star * dt_min / 2))
        else:
            s_star = e0 / (e0 - e1)
            segments.append(((1 - s_star) * dt_min, e1 * (1 - s_star) * dt_min / 2))
    return segments


def independent_heatwork(points: list[tuple[datetime, float]]) -> Fraction:
    return sum((contribution for _, contribution in independent_segments(points)), Fraction(0))


def independent_display(points: list[tuple[datetime, float]]) -> str:
    raw = independent_heatwork(points)
    value = Decimal(raw.numerator) / Decimal(raw.denominator)
    return str(value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def independent_verdict(display: str) -> str:
    value = Decimal(display)
    if value < Decimal("18000.0"):
        return "underfired"
    if value <= Decimal("24000.0"):
        return "qualified"
    return "overfired"


# ---------- HTTP 辅助 ----------

def request(method: str, url: str, payload: dict | None = None) -> tuple[int, object]:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read()
            return resp.status, json.loads(body) if body else None
    except urllib.error.HTTPError as err:
        body = err.read()
        try:
            return err.code, json.loads(body)
        except json.JSONDecodeError:
            return err.code, body.decode(errors="replace")


def get_text(url: str) -> tuple[int, str]:
    with urllib.request.urlopen(url, timeout=15) as resp:
        return resp.status, resp.read().decode(errors="replace")


# ---------- 检查用例 ----------

def check(name: str):
    def decorator(fn):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - 验收脚本需汇总全部失败
            FAILURES.append(name)
            print(f"FAIL {name}: {exc}")
        else:
            print(f"PASS {name}")
    return decorator


def constant_points(temperature: float, minutes: int):
    t0 = datetime(2026, 9, 11, tzinfo=timezone.utc)
    t1 = t0 + timedelta(minutes=minutes)
    fmt = lambda dt: dt.isoformat().replace("+00:00", "Z")
    return (
        [{"time": fmt(t0), "temperature": temperature}, {"time": fmt(t1), "temperature": temperature}],
        [(t0, temperature), (t1, temperature)],
    )


@check("api 健康检查（直连）")
def _():
    status, body = request("GET", f"{API_BASE}/api/health")
    assert status == 200 and body == {"status": "ok"}, (status, body)


@check("web 提供前端页面")
def _():
    status, html = get_text(f"{WEB_BASE}/")
    assert status == 200, status
    assert '<div id="root">' in html and "窑炉烧成判定台" in html


@check("web 代理 /api 到后端")
def _():
    status, body = request("GET", f"{WEB_BASE}/api/health")
    assert status == 200 and body == {"status": "ok"}, (status, body)


@check("合法提交经 web 代理落库，积分与结论与独立复算一致")
def _():
    payload = {
        "name": "VERIFY-CURVE",
        "points": [
            {"time": "2026-09-11T08:00:00Z", "temperature": 600},
            {"time": "2026-09-11T10:00:00Z", "temperature": 700},
            {"time": "2026-09-11T12:00:00Z", "temperature": 700},
            {"time": "2026-09-11T13:00:00Z", "temperature": 600},
        ],
    }
    moments = [
        (datetime(2026, 9, 11, 8, tzinfo=timezone.utc), 600.0),
        (datetime(2026, 9, 11, 10, tzinfo=timezone.utc), 700.0),
        (datetime(2026, 9, 11, 12, tzinfo=timezone.utc), 700.0),
        (datetime(2026, 9, 11, 13, tzinfo=timezone.utc), 600.0),
    ]
    expected_display = independent_display(moments)
    assert expected_display == "21000.0", expected_display

    status, body = request("POST", f"{WEB_BASE}/api/batches", payload)
    assert status == 201, (status, body)
    assert body["integral_display"] == expected_display, body
    assert body["verdict"] == independent_verdict(expected_display) == "qualified", body
    assert body["verdict_label"] == "合格", body

    # 刷新后仍可复查：列表与详情（原始点逐字保留）
    status, listing = request("GET", f"{WEB_BASE}/api/batches")
    assert status == 200, status
    ids = [b["id"] for b in listing["batches"]]
    assert body["id"] in ids, ids
    status, detail = request("GET", f"{WEB_BASE}/api/batches/{body['id']}")
    assert status == 200, status
    assert detail["points"] == payload["points"], detail["points"]
    assert abs(detail["integral_raw"] - 21000.0) < 1e-9, detail["integral_raw"]


@check("判定边界：18000.0 / 24000.0 合格，越界即欠烧 / 过烧")
def _():
    cases = [
        (689.9995, 200, "underfired", "欠烧"),
        (660.0, 300, "qualified", "合格"),   # 恰为 18000.0
        (640.0, 600, "qualified", "合格"),   # 恰为 24000.0
        (640.001, 600, "overfired", "过烧"),
    ]
    for temperature, minutes, verdict, label in cases:
        payload, moments = constant_points(temperature, minutes)
        expected = independent_display(moments)
        status, body = request(
            "POST", f"{WEB_BASE}/api/batches", {"name": f"VERIFY-{temperature}-{minutes}", "points": payload}
        )
        assert status == 201, (status, body)
        assert body["integral_display"] == expected, (body, expected)
        assert body["verdict"] == verdict, (body, verdict)
        assert body["verdict_label"] == label, (body, label)


@check("非法提交返回可定位错误且整次不落库")
def _():
    status, before = request("GET", f"{WEB_BASE}/api/batches")
    assert status == 200, status
    count_before = len(before["batches"])

    payload = {
        "name": "VERIFY-BAD",
        "points": [
            {"time": "2026-09-11T08:00:00Z", "temperature": 620.0},
            {"time": "2026-09-11T09:00:00Z", "temperature": 1500.0},
            {"time": "2026-09-11T08:30:00Z", "temperature": 640.0},
        ],
    }
    status, body = request("POST", f"{WEB_BASE}/api/batches", payload)
    assert status == 422, (status, body)
    located = {(e["index"], e["field"]) for e in body["detail"]["errors"]}
    assert (1, "temperature") in located, located
    assert (2, "time") in located, located

    status, after = request("GET", f"{WEB_BASE}/api/batches")
    assert status == 200, status
    assert len(after["batches"]) == count_before, "非法提交被落库"


# ---------- 分段计热贡献明细 ----------

def assert_segments_match(body: dict, moments: list[tuple[datetime, float]]):
    """响应中的分段明细与独立复算逐段一致，且总和等于未舍入总积分。"""
    expected = independent_segments(moments)
    segments = body["segments"]
    assert segments is not None and len(segments) == len(expected), body
    assert body["segments_note"] is None, body
    for segment, (minutes, contribution) in zip(segments, expected):
        assert abs(segment["heating_minutes"] - float(minutes)) < 1e-9, segment
        assert abs(segment["contribution"] - float(contribution)) < 1e-9, segment
    total = sum(s["contribution"] for s in segments)
    assert abs(total - body["integral_raw"]) < 1e-9, (total, body["integral_raw"])
    return segments


@check("分段明细：跨越起点自动切段，分钟数与贡献和独立复算一致")
def _():
    payload = {
        "name": "VERIFY-SEG-CROSS",
        "points": [
            {"time": "2026-09-11T00:00:00Z", "temperature": 500.0},
            {"time": "2026-09-11T01:00:00Z", "temperature": 700.0},
        ],
    }
    moments = [
        (datetime(2026, 9, 11, 0, tzinfo=timezone.utc), 500.0),
        (datetime(2026, 9, 11, 1, tzinfo=timezone.utc), 700.0),
    ]
    status, body = request("POST", f"{WEB_BASE}/api/batches", payload)
    assert status == 201, (status, body)
    (segment,) = assert_segments_match(body, moments)
    # 60 min 内 500 -> 700，30 min 处越过 600°C：仅后 30 min 计热
    assert segment["heating_minutes"] == 30, segment
    assert segment["contribution"] == 1500, segment
    assert segment["share"] == 1.0, segment
    assert segment["start_time"] == "2026-09-11T00:00:00Z", segment
    assert segment["end_time"] == "2026-09-11T01:00:00Z", segment


@check("分段明细：全程低温的零贡献段保留可见")
def _():
    payload = {
        "name": "VERIFY-SEG-COLD",
        "points": [
            {"time": "2026-09-11T00:00:00Z", "temperature": 500.0},
            {"time": "2026-09-11T02:00:00Z", "temperature": 550.0},
        ],
    }
    moments = [
        (datetime(2026, 9, 11, 0, tzinfo=timezone.utc), 500.0),
        (datetime(2026, 9, 11, 2, tzinfo=timezone.utc), 550.0),
    ]
    status, body = request("POST", f"{WEB_BASE}/api/batches", payload)
    assert status == 201, (status, body)
    assert body["integral_raw"] == 0, body
    (segment,) = assert_segments_match(body, moments)
    assert segment["contribution"] == 0, segment
    assert segment["heating_minutes"] == 0, segment
    assert segment["share"] == 0, segment


@check("分段明细：多段曲线各段之和等于未舍入总积分，详情一致")
def _():
    payload = {
        "name": "VERIFY-SEG-CURVE",
        "points": [
            {"time": "2026-09-11T08:00:00Z", "temperature": 600},
            {"time": "2026-09-11T10:00:00Z", "temperature": 700},
            {"time": "2026-09-11T12:00:00Z", "temperature": 700},
            {"time": "2026-09-11T13:00:00Z", "temperature": 600},
        ],
    }
    moments = [
        (datetime(2026, 9, 11, 8, tzinfo=timezone.utc), 600.0),
        (datetime(2026, 9, 11, 10, tzinfo=timezone.utc), 700.0),
        (datetime(2026, 9, 11, 12, tzinfo=timezone.utc), 700.0),
        (datetime(2026, 9, 11, 13, tzinfo=timezone.utc), 600.0),
    ]
    status, body = request("POST", f"{WEB_BASE}/api/batches", payload)
    assert status == 201, (status, body)
    segments = assert_segments_match(body, moments)
    assert [s["heating_minutes"] for s in segments] == [120, 120, 60], segments
    assert [s["contribution"] for s in segments] == [6000, 12000, 3000], segments
    assert abs(sum(s["share"] for s in segments) - 1.0) < 1e-9, segments
    assert body["integral_raw"] == 21000.0, body

    # 历史详情按时间顺序返回同一份明细
    status, detail = request("GET", f"{WEB_BASE}/api/batches/{body['id']}")
    assert status == 200, status
    assert detail["segments"] == segments, detail["segments"]
    assert detail["segments_note"] is None, detail


@check("升级前记录可查看：原结论不改写，明细按已存原始点补算")
def _():
    status, listing = request("GET", f"{WEB_BASE}/api/batches")
    assert status == 200, status
    legacy = next(
        (b for b in listing["batches"] if b["name"] == "LEGACY-QUALIFIED"), None
    )
    assert legacy is not None, "legacy-seed 未写入 LEGACY-QUALIFIED"
    # 列表响应保持既有字段
    assert {
        "id",
        "name",
        "point_count",
        "integral_raw",
        "integral_display",
        "verdict",
        "verdict_label",
        "created_at",
    } <= set(legacy), legacy
    assert legacy["verdict"] == "qualified" and legacy["verdict_label"] == "合格"

    status, detail = request("GET", f"{WEB_BASE}/api/batches/{legacy['id']}")
    assert status == 200, status
    # 原判定与积分保持不动
    assert detail["verdict"] == "qualified", detail
    assert detail["integral_display"] == "21000.0", detail
    assert detail["integral_raw"] == 21000.0, detail
    # 明细由服务依据已存原始点确定性补算
    moments = [
        (datetime(2026, 9, 11, 8, tzinfo=timezone.utc), 600.0),
        (datetime(2026, 9, 11, 10, tzinfo=timezone.utc), 700.0),
        (datetime(2026, 9, 11, 12, tzinfo=timezone.utc), 700.0),
        (datetime(2026, 9, 11, 13, tzinfo=timezone.utc), 600.0),
    ]
    segments = assert_segments_match(detail, moments)
    assert [s["contribution"] for s in segments] == [6000, 12000, 3000], segments


@check("升级前异常记录：原判定保留，明细区域说明无法生成原因")
def _():
    status, listing = request("GET", f"{WEB_BASE}/api/batches")
    assert status == 200, status
    legacy = next(
        (b for b in listing["batches"] if b["name"] == "LEGACY-BROKEN"), None
    )
    assert legacy is not None, "legacy-seed 未写入 LEGACY-BROKEN"
    assert legacy["verdict"] == "underfired" and legacy["verdict_label"] == "欠烧"

    status, detail = request("GET", f"{WEB_BASE}/api/batches/{legacy['id']}")
    assert status == 200, status
    # 原判定照常展示
    assert detail["verdict"] == "underfired", detail
    assert detail["integral_display"] == "1500.0", detail
    # 已存采样点无法形成合法时间序列：明细缺失并说明原因
    assert detail["segments"] is None, detail
    assert isinstance(detail["segments_note"], str), detail
    assert "无法" in detail["segments_note"], detail["segments_note"]


def main() -> int:
    print(f"验收目标：api={API_BASE} web={WEB_BASE}")
    if FAILURES:
        print(f"\n{len(FAILURES)} 项验收失败：{', '.join(FAILURES)}")
        return 1
    print("\n全部验收通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
