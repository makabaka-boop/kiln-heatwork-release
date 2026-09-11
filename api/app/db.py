"""SQLite 持久化层。

合法提交落库四要素：原始采样点、未舍入积分、展示值（一位小数字符串）、
结论；非法提交在校验阶段即被拦截，绝不会写入本库。
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS batches (
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


def db_path() -> str:
    return os.environ.get("HEATWORK_DB", "heatwork.db")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(_SCHEMA)


def insert_batch(
    *,
    name: str,
    points: List[Dict[str, Any]],
    integral_raw: float,
    integral_display: str,
    verdict: str,
) -> Dict[str, Any]:
    created_at = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO batches
                (name, points_json, point_count, integral_raw,
                 integral_display, verdict, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                json.dumps(points, ensure_ascii=False),
                len(points),
                integral_raw,
                integral_display,
                verdict,
                created_at,
            ),
        )
        batch_id = cursor.lastrowid
    return {
        "id": batch_id,
        "name": name,
        "point_count": len(points),
        "integral_raw": integral_raw,
        "integral_display": integral_display,
        "verdict": verdict,
        "created_at": created_at,
    }


def list_batches() -> List[Dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, name, point_count, integral_raw, integral_display,
                   verdict, created_at
            FROM batches ORDER BY id DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def get_batch(batch_id: int) -> Optional[Dict[str, Any]]:
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT id, name, points_json, point_count, integral_raw,
                   integral_display, verdict, created_at
            FROM batches WHERE id = ?
            """,
            (batch_id,),
        ).fetchone()
    if row is None:
        return None
    record = dict(row)
    record["points"] = json.loads(record.pop("points_json"))
    return record


def count_batches() -> int:
    with _connect() as conn:
        (count,) = conn.execute("SELECT COUNT(*) FROM batches").fetchone()
    return count
