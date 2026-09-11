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

def independent_heatwork(points: list[tuple[datetime, float]]) -> Fraction:
    total = Fraction(0)
    for (t0, temp0), (t1, temp1) in zip(points, points[1:]):
        delta = t1 - t0
        micros = delta.days * 86_400_000_000 + delta.seconds * 1_000_000 + delta.microseconds
        dt_min = Fraction(micros, 60_000_000)
        e0, e1 = Fraction(temp0) - 600, Fraction(temp1) - 600
        if e0 <= 0 and e1 <= 0:
            continue
        if e0 > 0 and e1 > 0:
            total += (e0 + e1) * dt_min / 2
        elif e0 > 0:
            total += e0 * (e0 / (e0 - e1)) * dt_min / 2
        else:
            total += e1 * (1 - e0 / (e0 - e1)) * dt_min / 2
    return total


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


def main() -> int:
    print(f"验收目标：api={API_BASE} web={WEB_BASE}")
    if FAILURES:
        print(f"\n{len(FAILURES)} 项验收失败：{', '.join(FAILURES)}")
        return 1
    print("\n全部验收通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
