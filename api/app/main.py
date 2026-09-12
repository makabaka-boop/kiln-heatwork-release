"""FastAPI 入口：窑炉烧成判定台 API。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fractions import Fraction
from typing import Any, Dict, List, Optional, Tuple

from fastapi import Body, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import db
from .heatwork import (
    VERDICT_LABELS,
    classify,
    compute_segment_contributions,
    round_half_up_1,
)
from .validation import parse_iso8601, validate_submission


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="窑炉烧成判定台 API", lifespan=lifespan)

# 便于本地开发（Vite dev server 与 API 分端口）；生产经 nginx 同源代理
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _with_label(record: Dict[str, Any]) -> Dict[str, Any]:
    record = dict(record)
    record["verdict_label"] = VERDICT_LABELS[record["verdict"]]
    return record


def _source_summary(source: Dict[str, Any]) -> Dict[str, Any]:
    """复算记录响应中携带的来源窑次摘要（只读信息，不含采样点）。"""
    return {
        "id": source["id"],
        "name": source["name"],
        "integral_display": source["integral_display"],
        "verdict": source["verdict"],
        "verdict_label": VERDICT_LABELS[source["verdict"]],
        "created_at": source["created_at"],
    }


def _attach_source(record: Dict[str, Any]) -> Dict[str, Any]:
    """为复算记录附上来源窑次摘要；普通提交与旧记录为 None。"""
    source_id = record.get("source_batch_id")
    if source_id is None:
        record["source"] = None
        return record
    source = db.get_batch(source_id)
    record["source"] = _source_summary(source) if source is not None else None
    return record


def _build_segments(
    points: List[Tuple[str, datetime, float]],
) -> Tuple[List[Dict[str, Any]], Fraction]:
    """由 (原始时刻字符串, 时刻, 温度) 序列生成分段明细与精确总积分。

    总积分取各段贡献之和，保证「各段贡献之和 == 未舍入总积分」
    在精确有理数层面恒成立；占比在总量为 0 时各段记 0。
    """
    contributions = compute_segment_contributions(
        [(moment, temperature) for _, moment, temperature in points]
    )
    total = sum((seg.contribution for seg in contributions), Fraction(0))
    segments: List[Dict[str, Any]] = []
    for seg in contributions:
        segments.append(
            {
                "index": seg.index,
                "start_time": points[seg.index][0],
                "end_time": points[seg.index + 1][0],
                "heating_minutes": float(seg.heating_minutes),
                "contribution": float(seg.contribution),
                "share": float(seg.contribution / total) if total > 0 else 0.0,
            }
        )
    return segments, total


def _recompute_segments(
    stored_points: Any,
) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    """为升级前的旧记录补算分段明细（确定性，不改写原结论）。

    返回 (明细, None)；已存采样点无法形成合法时间序列时返回
    (None, 原因说明)，原判定与积分保持不动。
    """
    prefix = "该记录为升级前保存，未保存分段明细；"
    if not isinstance(stored_points, list) or len(stored_points) < 2:
        return None, f"{prefix}已存采样点不足 2 个，无法形成计热区段。"
    parsed: List[Tuple[str, datetime, float]] = []
    for index, point in enumerate(stored_points):
        if not isinstance(point, dict):
            return None, f"{prefix}第 {index} 个采样点不是 JSON 对象，无法补算。"
        moment, error = parse_iso8601(point.get("time"))
        if error is not None or moment is None:
            return None, f"{prefix}第 {index} 个采样点时刻无法解析（{error}），无法补算。"
        temperature = point.get("temperature")
        if (
            isinstance(temperature, bool)
            or not isinstance(temperature, (int, float))
            or temperature != temperature  # NaN
        ):
            return None, f"{prefix}第 {index} 个采样点温度不是有效数字，无法补算。"
        parsed.append((point["time"], moment, temperature))
    for index in range(1, len(parsed)):
        if parsed[index][1] <= parsed[index - 1][1]:
            return (
                None,
                f"{prefix}已存采样点时刻未严格递增"
                f"（第 {index} 个不晚于第 {index - 1} 个），无法补算。",
            )
    segments, _ = _build_segments(parsed)
    return segments, None


@app.get("/api/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/api/batches", status_code=201)
def create_batch(payload: Dict[str, Any] = Body(...)) -> Any:
    normalized, errors = validate_submission(payload)
    if errors:
        # 任一非法点 -> 整次不落库，返回全部可定位错误
        return JSONResponse(
            status_code=422,
            content={
                "detail": {
                    "message": "提交数据未通过校验，本次数据未保存。",
                    "errors": [error.to_dict() for error in errors],
                }
            },
        )

    assert normalized is not None
    segments, integral_raw = _build_segments(
        [(p.time_raw, p.moment, p.temperature) for p in normalized.points]
    )
    display = round_half_up_1(integral_raw)
    verdict = classify(display)

    record = db.insert_batch(
        name=normalized.name,
        points=[
            {"time": p.time_raw, "temperature": p.temperature}
            for p in normalized.points
        ],
        integral_raw=float(integral_raw),
        integral_display=str(display),
        verdict=verdict,
        segments=segments,
    )
    record["segments_note"] = None
    record["source"] = None
    return _with_label(record)


@app.get("/api/batches")
def list_batches() -> Dict[str, Any]:
    return {"batches": [_with_label(record) for record in db.list_batches()]}


@app.get("/api/batches/{batch_id}")
def get_batch(batch_id: int) -> Any:
    record = db.get_batch(batch_id)
    if record is None:
        return JSONResponse(
            status_code=404,
            content={"detail": {"message": f"窑次 {batch_id} 不存在"}},
        )
    if record["segments"] is None:
        # 升级前的旧记录：依据已存原始点确定性补算，不回写、不改原结论
        segments, note = _recompute_segments(record["points"])
        record["segments"] = segments
        record["segments_note"] = note
    else:
        record["segments_note"] = None
    return _with_label(_attach_source(record))


@app.post("/api/batches/{batch_id}/recompute", status_code=201)
def recompute_batch(batch_id: int) -> Any:
    """按当前规则复算历史窑次。

    读取来源记录的原始采样点，走与正常提交一致的校验、线性插值、
    分段贡献与判定链路，结果以**新窑次**落库并记录来源窑次编号与
    复算时间；原记录保持只读。来源不存在或其原始点已无法通过当前
    校验时，返回区分原因的失败响应且不新增记录。
    """
    source = db.get_batch(batch_id)
    if source is None:
        return JSONResponse(
            status_code=404,
            content={
                "detail": {
                    "reason": "source_not_found",
                    "message": f"来源窑次 {batch_id} 不存在，无法复算。",
                }
            },
        )

    normalized, errors = validate_submission(
        {"name": source["name"], "points": source["points"]}
    )
    if errors:
        # 原始点已无法通过当前校验：不新增记录，返回全部可定位错误
        return JSONResponse(
            status_code=422,
            content={
                "detail": {
                    "reason": "source_invalid",
                    "message": "该记录的原始采样点未通过当前校验，无法复算，未新增记录。",
                    "errors": [error.to_dict() for error in errors],
                }
            },
        )

    assert normalized is not None
    segments, integral_raw = _build_segments(
        [(p.time_raw, p.moment, p.temperature) for p in normalized.points]
    )
    display = round_half_up_1(integral_raw)
    verdict = classify(display)

    record = db.insert_batch(
        name=normalized.name,
        points=[
            {"time": p.time_raw, "temperature": p.temperature}
            for p in normalized.points
        ],
        integral_raw=float(integral_raw),
        integral_display=str(display),
        verdict=verdict,
        segments=segments,
        source_batch_id=source["id"],
        recomputed_at=datetime.now(timezone.utc).isoformat(),
    )
    record["segments_note"] = None
    record["source"] = _source_summary(source)
    return _with_label(record)
