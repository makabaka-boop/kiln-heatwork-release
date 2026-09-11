"""FastAPI 入口：窑炉烧成判定台 API。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, Dict

from fastapi import Body, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import db
from .heatwork import VERDICT_LABELS, classify, compute_heatwork, round_half_up_1
from .validation import validate_submission


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
    sample_points = [(p.moment, p.temperature) for p in normalized.points]
    integral_raw = compute_heatwork(sample_points)
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
    )
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
    return _with_label(record)
