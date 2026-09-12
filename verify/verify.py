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


def independent_segment_area(dt_min: Fraction, e0: Fraction, e1: Fraction) -> Fraction:
    """独立复写：单段对 max(T-600, 0) 的积分（dt 为段长分钟）。"""
    if e0 <= 0 and e1 <= 0:
        return Fraction(0)
    if e0 > 0 and e1 > 0:
        return (e0 + e1) * dt_min / 2
    s_star = e0 / (e0 - e1)
    if e0 > 0:
        return e0 * s_star * dt_min / 2
    return e1 * (1 - s_star) * dt_min / 2


def independent_eval(points: list[tuple[datetime, float]], elapsed: Fraction):
    """独立复写：经过 elapsed 分钟处的 (温度, 累计计热)，段内线性插值。"""
    first = points[0][0]
    timeline = [_minutes_of(moment - first) for moment, _ in points]
    temps = [Fraction(temp) for _, temp in points]
    if elapsed <= 0:
        return temps[0], Fraction(0)
    heat = Fraction(0)
    for index in range(len(timeline) - 1):
        t0, t1 = timeline[index], timeline[index + 1]
        if elapsed < t1:
            temp = temps[index] + (temps[index + 1] - temps[index]) * (elapsed - t0) / (t1 - t0)
            heat += independent_segment_area(elapsed - t0, temps[index] - 600, temp - 600)
            return temp, heat
        heat += independent_segment_area(t1 - t0, temps[index] - 600, temps[index + 1] - 600)
    return temps[-1], heat


def independent_compare(
    current: list[tuple[datetime, float]], reference: list[tuple[datetime, float]]
):
    """独立复写：共同持续区间内并集时间轴上的逐节点 (经过分钟, 温度差, 计热差)。"""
    def elapsed_nodes(points):
        return {_minutes_of(moment - points[0][0]) for moment, _ in points}

    common = min(
        _minutes_of(current[-1][0] - current[0][0]),
        _minutes_of(reference[-1][0] - reference[0][0]),
    )
    assert common > 0, "验收用例应始终有正长度共同区间"
    timeline = sorted(
        t for t in elapsed_nodes(current) | elapsed_nodes(reference) if t <= common
    )
    nodes = []
    for t in timeline:
        temp_c, heat_c = independent_eval(current, t)
        temp_r, heat_r = independent_eval(reference, t)
        nodes.append((t, temp_c - temp_r, heat_c - heat_r))
    return common, nodes


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
    # 普通提交：无来源标记，响应字段保持兼容
    assert body["source_batch_id"] is None and body["source"] is None, body

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


# ---------- 按当前规则复算 ----------

RECOMPUTE_CURVE = [
    {"time": "2026-09-11T08:00:00Z", "temperature": 600},
    {"time": "2026-09-11T10:00:00Z", "temperature": 700},
    {"time": "2026-09-11T12:00:00Z", "temperature": 700},
    {"time": "2026-09-11T13:00:00Z", "temperature": 600},
]
RECOMPUTE_MOMENTS = [
    (datetime(2026, 9, 11, 8, tzinfo=timezone.utc), 600.0),
    (datetime(2026, 9, 11, 10, tzinfo=timezone.utc), 700.0),
    (datetime(2026, 9, 11, 12, tzinfo=timezone.utc), 700.0),
    (datetime(2026, 9, 11, 13, tzinfo=timezone.utc), 600.0),
]


@check("复算：合法历史记录按当前规则重算，新记录落库并标注来源")
def _():
    payload = {"name": "VERIFY-RECOMPUTE-SRC", "points": RECOMPUTE_CURVE}
    status, source = request("POST", f"{WEB_BASE}/api/batches", payload)
    assert status == 201, (status, source)

    status, before = request("GET", f"{WEB_BASE}/api/batches")
    assert status == 200, status
    count_before = len(before["batches"])

    # 触发复算：以新窑次落库，响应沿用现有窑次字段并增加来源摘要
    status, body = request("POST", f"{WEB_BASE}/api/batches/{source['id']}/recompute")
    assert status == 201, (status, body)
    assert body["id"] != source["id"], body
    assert body["source_batch_id"] == source["id"], body
    assert body["recomputed_at"], body
    assert body["segments_note"] is None, body
    # 总积分与分段由当前算法重算（与独立复算一致）
    expected_display = independent_display(RECOMPUTE_MOMENTS)
    assert body["integral_display"] == expected_display == "21000.0", body
    assert body["verdict"] == independent_verdict(expected_display), body
    assert_segments_match(body, RECOMPUTE_MOMENTS)
    # 来源摘要
    summary = body["source"]
    assert summary["id"] == source["id"], summary
    assert summary["name"] == "VERIFY-RECOMPUTE-SRC", summary
    assert summary["integral_display"] == source["integral_display"], summary
    assert summary["verdict"] == source["verdict"], summary
    assert summary["verdict_label"] == "合格", summary

    # 历史列表：新增一条且标识「复算自某窑次」
    status, listing = request("GET", f"{WEB_BASE}/api/batches")
    assert status == 200, status
    assert len(listing["batches"]) == count_before + 1, listing
    item = next(b for b in listing["batches"] if b["id"] == body["id"])
    assert item["source_batch_id"] == source["id"], item
    assert item["source_name"] == "VERIFY-RECOMPUTE-SRC", item

    # 刷新后复查：详情携带来源摘要，积分/分段为重算结果，原始点逐字保留
    status, detail = request("GET", f"{WEB_BASE}/api/batches/{body['id']}")
    assert status == 200, status
    assert detail["source_batch_id"] == source["id"], detail
    assert detail["recomputed_at"], detail
    assert detail["source"]["id"] == source["id"], detail
    assert detail["points"] == payload["points"], detail["points"]
    assert_segments_match(detail, RECOMPUTE_MOMENTS)

    # 原记录保持只读：判定与积分不变，且不带来源标记
    status, original = request("GET", f"{WEB_BASE}/api/batches/{source['id']}")
    assert status == 200, status
    assert original["integral_display"] == "21000.0", original
    assert original["verdict"] == "qualified", original
    assert original["source_batch_id"] is None and original["source"] is None, original


@check("复算：升级前合法旧记录可复算，结论由当前算法给出且原记录只读")
def _():
    status, listing = request("GET", f"{WEB_BASE}/api/batches")
    assert status == 200, status
    legacy = next(
        (b for b in listing["batches"] if b["name"] == "LEGACY-QUALIFIED"), None
    )
    assert legacy is not None, "legacy-seed 未写入 LEGACY-QUALIFIED"

    status, body = request("POST", f"{WEB_BASE}/api/batches/{legacy['id']}/recompute")
    assert status == 201, (status, body)
    assert body["source_batch_id"] == legacy["id"], body
    assert body["integral_display"] == independent_display(RECOMPUTE_MOMENTS), body
    assert body["verdict"] == "qualified", body
    assert body["source"]["name"] == "LEGACY-QUALIFIED", body
    assert_segments_match(body, RECOMPUTE_MOMENTS)

    # 原旧记录保持只读：判定与积分不动，仍无来源标记
    status, original = request("GET", f"{WEB_BASE}/api/batches/{legacy['id']}")
    assert status == 200, status
    assert original["integral_display"] == "21000.0", original
    assert original["verdict"] == "qualified", original
    assert original["source_batch_id"] is None, original


@check("复算：不合法旧记录与缺失来源均失败且记录数不变")
def _():
    status, listing = request("GET", f"{WEB_BASE}/api/batches")
    assert status == 200, status
    count_before = len(listing["batches"])
    broken = next(
        (b for b in listing["batches"] if b["name"] == "LEGACY-BROKEN"), None
    )
    assert broken is not None, "legacy-seed 未写入 LEGACY-BROKEN"

    # 原始点已无法通过当前校验 -> 422，原因可区分，附全部定位错误
    status, body = request("POST", f"{WEB_BASE}/api/batches/{broken['id']}/recompute")
    assert status == 422, (status, body)
    assert body["detail"]["reason"] == "source_invalid", body
    assert body["detail"]["errors"], body

    # 来源不存在 -> 404，原因可区分
    status, body = request("POST", f"{WEB_BASE}/api/batches/999999/recompute")
    assert status == 404, (status, body)
    assert body["detail"]["reason"] == "source_not_found", body

    # 两种失败均不新增记录
    status, after = request("GET", f"{WEB_BASE}/api/batches")
    assert status == 200, status
    assert len(after["batches"]) == count_before, "复算失败不应新增记录"


# ---------- 轨迹对比 ----------

# 标准曲线（4 点）与同一轨迹按 30 min 加密采样的曲线（11 点）：轨迹等价
COMPARE_STANDARD = RECOMPUTE_CURVE
COMPARE_STANDARD_MOMENTS = RECOMPUTE_MOMENTS

COMPARE_DENSE = [
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
COMPARE_DENSE_MOMENTS = [
    (datetime(2026, 9, 11, 8, 0, tzinfo=timezone.utc), 600.0),
    (datetime(2026, 9, 11, 8, 30, tzinfo=timezone.utc), 625.0),
    (datetime(2026, 9, 11, 9, 0, tzinfo=timezone.utc), 650.0),
    (datetime(2026, 9, 11, 9, 30, tzinfo=timezone.utc), 675.0),
    (datetime(2026, 9, 11, 10, 0, tzinfo=timezone.utc), 700.0),
    (datetime(2026, 9, 11, 10, 30, tzinfo=timezone.utc), 700.0),
    (datetime(2026, 9, 11, 11, 0, tzinfo=timezone.utc), 700.0),
    (datetime(2026, 9, 11, 11, 30, tzinfo=timezone.utc), 700.0),
    (datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc), 700.0),
    (datetime(2026, 9, 11, 12, 30, tzinfo=timezone.utc), 650.0),
    (datetime(2026, 9, 11, 13, 0, tzinfo=timezone.utc), 600.0),
]

# 局部升温偏差：前 60 min 就升到 700°C，之后与标准曲线一致
COMPARE_DEVIATED = [
    {"time": "2026-09-11T08:00:00Z", "temperature": 600},
    {"time": "2026-09-11T08:30:00Z", "temperature": 650},
    {"time": "2026-09-11T09:00:00Z", "temperature": 700},
    {"time": "2026-09-11T10:00:00Z", "temperature": 700},
    {"time": "2026-09-11T12:00:00Z", "temperature": 700},
    {"time": "2026-09-11T13:00:00Z", "temperature": 600},
]
COMPARE_DEVIATED_MOMENTS = [
    (datetime(2026, 9, 11, 8, 0, tzinfo=timezone.utc), 600.0),
    (datetime(2026, 9, 11, 8, 30, tzinfo=timezone.utc), 650.0),
    (datetime(2026, 9, 11, 9, 0, tzinfo=timezone.utc), 700.0),
    (datetime(2026, 9, 11, 10, 0, tzinfo=timezone.utc), 700.0),
    (datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc), 700.0),
    (datetime(2026, 9, 11, 13, 0, tzinfo=timezone.utc), 600.0),
]


def assert_compare_nodes_match(body: dict, current_moments, reference_moments):
    """响应中的对齐节点与独立复算逐一一致，返回 {经过分钟: 节点}。"""
    common, expected = independent_compare(current_moments, reference_moments)
    assert abs(body["common_minutes"] - float(common)) < 1e-9, body
    assert len(body["nodes"]) == len(expected), body
    for node, (t, dtemp, dheat) in zip(body["nodes"], expected):
        assert abs(node["elapsed_minutes"] - float(t)) < 1e-9, node
        assert abs(node["temperature_delta"] - float(dtemp)) < 1e-9, node
        assert abs(node["heatwork_delta"] - float(dheat)) < 1e-9, node
    return {node["elapsed_minutes"]: node for node in body["nodes"]}


@check("对比：采样间隔不同但轨迹等价的两窑，各节点差值为零")
def _():
    status, current = request(
        "POST", f"{WEB_BASE}/api/batches", {"name": "VERIFY-CMP-STD", "points": COMPARE_STANDARD}
    )
    assert status == 201, (status, current)
    status, reference = request(
        "POST", f"{WEB_BASE}/api/batches", {"name": "VERIFY-CMP-DENSE", "points": COMPARE_DENSE}
    )
    assert status == 201, (status, reference)

    status, listing = request("GET", f"{WEB_BASE}/api/batches")
    count_before = len(listing["batches"])

    status, body = request(
        "GET", f"{WEB_BASE}/api/batches/{current['id']}/compare/{reference['id']}"
    )
    assert status == 200, (status, body)
    # 只返回对齐节点、两类差值及双方摘要
    assert set(body) == {"batch", "reference", "common_minutes", "nodes"}, body
    assert body["batch"]["id"] == current["id"], body
    assert body["batch"]["name"] == "VERIFY-CMP-STD", body
    assert body["batch"]["verdict_label"] == "合格", body
    assert body["reference"]["id"] == reference["id"], body
    assert body["reference"]["name"] == "VERIFY-CMP-DENSE", body
    # 与独立复算一致，且轨迹等价 -> 各节点差值恰为零
    nodes = assert_compare_nodes_match(body, COMPARE_STANDARD_MOMENTS, COMPARE_DENSE_MOMENTS)
    assert sorted(nodes) == [0, 30, 60, 90, 120, 150, 180, 210, 240, 270, 300]
    for node in nodes.values():
        assert node["temperature_delta"] == 0, node
        assert node["heatwork_delta"] == 0, node

    # 对比为只读：记录数不变
    status, after = request("GET", f"{WEB_BASE}/api/batches")
    assert len(after["batches"]) == count_before, "对比不应新增记录"


@check("对比：局部升温偏差经插值后的符号与数值")
def _():
    status, current = request(
        "POST", f"{WEB_BASE}/api/batches", {"name": "VERIFY-CMP-DEV", "points": COMPARE_DEVIATED}
    )
    assert status == 201, (status, current)
    status, reference = request(
        "POST", f"{WEB_BASE}/api/batches", {"name": "VERIFY-CMP-STD-2", "points": COMPARE_STANDARD}
    )
    assert status == 201, (status, reference)

    status, body = request(
        "GET", f"{WEB_BASE}/api/batches/{current['id']}/compare/{reference['id']}"
    )
    assert status == 200, (status, body)
    nodes = assert_compare_nodes_match(body, COMPARE_DEVIATED_MOMENTS, COMPARE_STANDARD_MOMENTS)
    assert sorted(nodes) == [0, 30, 60, 120, 240, 300]
    # 温度差：偏差段为正（+25 / +50），回归同一轨迹后为 0
    assert nodes[0]["temperature_delta"] == 0, nodes[0]
    assert nodes[30]["temperature_delta"] == 25, nodes[30]
    assert nodes[60]["temperature_delta"] == 50, nodes[60]
    assert nodes[120]["temperature_delta"] == 0, nodes[120]
    assert nodes[300]["temperature_delta"] == 0, nodes[300]
    # 累计计热差：偏差段逐步拉大（+375 / +1500 / +3000），之后保持 +3000
    assert nodes[30]["heatwork_delta"] == 375, nodes[30]
    assert nodes[60]["heatwork_delta"] == 1500, nodes[60]
    assert nodes[120]["heatwork_delta"] == 3000, nodes[120]
    assert nodes[240]["heatwork_delta"] == 3000, nodes[240]
    assert nodes[300]["heatwork_delta"] == 3000, nodes[300]

    # 反向对比：符号全部取反
    status, reverse = request(
        "GET", f"{WEB_BASE}/api/batches/{reference['id']}/compare/{current['id']}"
    )
    assert status == 200, (status, reverse)
    reversed_nodes = {node["elapsed_minutes"]: node for node in reverse["nodes"]}
    assert reversed_nodes[30]["temperature_delta"] == -25, reversed_nodes[30]
    assert reversed_nodes[60]["heatwork_delta"] == -1500, reversed_nodes[60]
    assert reversed_nodes[300]["heatwork_delta"] == -3000, reversed_nodes[300]


@check("对比：非法旧记录与缺失记录区分原因失败，且不影响既有数据")
def _():
    status, listing = request("GET", f"{WEB_BASE}/api/batches")
    assert status == 200, status
    count_before = len(listing["batches"])
    broken = next(
        (b for b in listing["batches"] if b["name"] == "LEGACY-BROKEN"), None
    )
    assert broken is not None, "legacy-seed 未写入 LEGACY-BROKEN"
    ok = next(
        (b for b in listing["batches"] if b["name"] == "LEGACY-QUALIFIED"), None
    )
    assert ok is not None, "legacy-seed 未写入 LEGACY-QUALIFIED"

    # 非法旧记录无论作为当前记录还是参照 -> 422，原因可区分
    for url in (
        f"{WEB_BASE}/api/batches/{broken['id']}/compare/{ok['id']}",
        f"{WEB_BASE}/api/batches/{ok['id']}/compare/{broken['id']}",
    ):
        status, body = request("GET", url)
        assert status == 422, (status, body)
        assert body["detail"]["reason"] == "series_invalid", body

    # 任一记录不存在 -> 404，原因可区分
    status, body = request("GET", f"{WEB_BASE}/api/batches/{ok['id']}/compare/999999")
    assert status == 404, (status, body)
    assert body["detail"]["reason"] == "batch_not_found", body
    status, body = request("GET", f"{WEB_BASE}/api/batches/999999/compare/{ok['id']}")
    assert status == 404, (status, body)
    assert body["detail"]["reason"] == "batch_not_found", body

    # 各类失败均不新增记录
    status, after = request("GET", f"{WEB_BASE}/api/batches")
    assert status == 200, status
    assert len(after["batches"]) == count_before, "对比失败不应新增记录"

    # 普通提交与历史复查不受影响
    payload = {"name": "VERIFY-CMP-AFTER", "points": COMPARE_STANDARD}
    status, created = request("POST", f"{WEB_BASE}/api/batches", payload)
    assert status == 201, (status, created)
    assert created["integral_display"] == "21000.0", created
    assert created["verdict"] == "qualified", created
    status, detail = request("GET", f"{WEB_BASE}/api/batches/{created['id']}")
    assert status == 200, status
    assert detail["points"] == payload["points"], detail
    assert detail["verdict"] == "qualified", detail
    # 合法旧记录参与对比正常：与等价新记录各节点差值为零
    status, body = request(
        "GET", f"{WEB_BASE}/api/batches/{created['id']}/compare/{ok['id']}"
    )
    assert status == 200, (status, body)
    for node in body["nodes"]:
        assert node["temperature_delta"] == 0, node
        assert node["heatwork_delta"] == 0, node


def main() -> int:
    print(f"验收目标：api={API_BASE} web={WEB_BASE}")
    if FAILURES:
        print(f"\n{len(FAILURES)} 项验收失败：{', '.join(FAILURES)}")
        return 1
    print("\n全部验收通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
