"""提交数据校验。

设计要点：

* 手工逐层校验，**收集全部错误**而不是遇到第一个就抛出，
  这样前端可以在每个采样点对应的位置上同时标出所有问题；
* 每条错误都带 ``index``（采样点下标，从 0 开始；与具体点无关时为
  ``None``）与 ``field``（``name`` / ``points`` / ``time`` /
  ``temperature``），前端据此定位；
* 只要存在任一非法点，校验即整体失败，调用方不得落库。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, List, Optional, Tuple

MIN_POINTS = 2
MAX_POINTS = 200
MAX_SPAN_HOURS = 12
MIN_TEMPERATURE_C = 0
MAX_TEMPERATURE_C = 1400
MAX_NAME_LENGTH = 120


@dataclass
class FieldError:
    """一个可定位到页面具体位置的校验错误。"""

    index: Optional[int]
    field: str
    message: str

    def to_dict(self) -> dict:
        return {"index": self.index, "field": self.field, "message": self.message}


@dataclass
class NormalizedPoint:
    """校验通过的采样点：保留原始输入，同时给出解析后的时刻。"""

    time_raw: str
    temperature: float
    moment: datetime


@dataclass
class NormalizedSubmission:
    name: str
    points: List[NormalizedPoint]


def _parse_iso8601(value: Any) -> Tuple[Optional[datetime], Optional[str]]:
    """解析 ISO 8601 时刻；naive 时刻按 UTC 处理。返回 (时刻, 错误信息)。"""
    if not isinstance(value, str) or not value.strip():
        return None, "时刻必须为 ISO 8601 字符串，例如 2026-09-11T08:00:00Z"
    text = value.strip()
    if "T" not in text and " " not in text:
        return None, "时刻须包含日期与时间，例如 2026-09-11T08:00:00Z"
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None, f"无法按 ISO 8601 解析时刻：{text!r}"
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment, None


def _validate_temperature(value: Any) -> Optional[str]:
    # bool 是 int 的子类，必须显式排除
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "温度必须为数字（摄氏）"
    if value != value:  # NaN
        return "温度不能为 NaN"
    if not (MIN_TEMPERATURE_C <= value <= MAX_TEMPERATURE_C):
        return (
            f"温度须在 {MIN_TEMPERATURE_C} 至 {MAX_TEMPERATURE_C}°C 之间，"
            f"收到 {value}"
        )
    return None


def validate_submission(payload: Any) -> Tuple[Optional[NormalizedSubmission], List[FieldError]]:
    """校验整次提交。返回 (规范化数据, 错误列表)；有错时数据为 None。"""
    errors: List[FieldError] = []
    if not isinstance(payload, dict):
        return None, [FieldError(None, "body", "请求体必须为 JSON 对象")]

    # ---- 窑次名称 ----
    name = payload.get("name")
    if not isinstance(name, str) or not name.strip():
        errors.append(FieldError(None, "name", "窑次名称不能为空"))
        name_clean = ""
    else:
        name_clean = name.strip()
        if len(name_clean) > MAX_NAME_LENGTH:
            errors.append(
                FieldError(None, "name", f"窑次名称不能超过 {MAX_NAME_LENGTH} 个字符")
            )

    # ---- 采样点数量 ----
    points = payload.get("points")
    if not isinstance(points, list):
        errors.append(FieldError(None, "points", "points 必须为采样点数组"))
        return None, errors
    if not (MIN_POINTS <= len(points) <= MAX_POINTS):
        errors.append(
            FieldError(
                None,
                "points",
                f"采样点数量须在 {MIN_POINTS} 至 {MAX_POINTS} 个之间，收到 {len(points)} 个",
            )
        )

    # ---- 逐点校验 ----
    normalized: List[Optional[NormalizedPoint]] = []
    moments: List[Tuple[int, datetime]] = []  # 时刻可解析的点，供跨点校验
    for idx, point in enumerate(points):
        if not isinstance(point, dict):
            errors.append(FieldError(idx, "point", f"第 {idx} 个采样点必须为 JSON 对象"))
            normalized.append(None)
            continue
        moment, time_error = _parse_iso8601(point.get("time"))
        if time_error:
            errors.append(FieldError(idx, "time", time_error))
        else:
            moments.append((idx, moment))
        temperature = point.get("temperature")
        temp_error = _validate_temperature(temperature)
        if temp_error:
            errors.append(FieldError(idx, "temperature", temp_error))
        if moment is not None and temp_error is None:
            normalized.append(
                NormalizedPoint(
                    time_raw=point.get("time"),
                    temperature=temperature,
                    moment=moment,
                )
            )
        else:
            normalized.append(None)

    # ---- 跨点校验：严格递增与首末间隔 ----
    # 只要时刻本身可解析就参与比较，即使同一点的温度等其他字段非法，
    # 这样递增性问题不会被其他错误掩盖。
    for (prev_idx, prev_moment), (idx, moment) in zip(moments, moments[1:]):
        if moment <= prev_moment:
            errors.append(
                FieldError(
                    idx,
                    "time",
                    "时刻必须严格递增："
                    f"该点不晚于第 {prev_idx} 个采样点 "
                    f"{prev_moment.isoformat()}",
                )
            )
    if len(moments) >= 2:
        first = moments[0][1]
        last = moments[-1][1]
        span_hours = (last - first).total_seconds() / 3600
        if span_hours > MAX_SPAN_HOURS:
            errors.append(
                FieldError(
                    None,
                    "points",
                    f"首末采样间隔不得超过 {MAX_SPAN_HOURS} 小时，实际为 "
                    f"{span_hours:.2f} 小时",
                )
            )

    if errors:
        return None, errors
    return NormalizedSubmission(name=name_clean, points=[p for p in normalized if p]), []
