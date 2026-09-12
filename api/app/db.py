"""SQLite 持久化层。

合法提交落库五要素：原始采样点、未舍入积分、展示值（一位小数字符串）、
结论与逐段计热贡献明细；非法提交在校验阶段即被拦截，绝不会写入本库。

复算落库：按当前规则复算历史窑次时，结果以**新窑次**写入，
``source_batch_id`` 记录来源窑次编号、``recomputed_at`` 记录复算时间，
原记录保持只读；普通提交这两列为 NULL。

升级兼容：旧版本库的 ``batches`` 表没有 ``segments_json`` 等后增列，
:func:`init_db` 会以 ``ALTER TABLE`` 就地补齐；已有记录这些列为 NULL，
分段明细由服务层在读取时依据已存原始点确定性补算，不回写、不改原结论。
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
    segments_json TEXT,
    source_batch_id INTEGER,
    recomputed_at TEXT,
    created_at TEXT NOT NULL
)
"""


def db_path() -> str:
    return os.environ.get("HEATWORK_DB", "heatwork.db")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    return conn


def _column_names(conn: sqlite3.Connection, table: str) -> List[str]:
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(_SCHEMA)
        # 兼容升级前已存在的库：缺列则就地添加，旧记录这些列为 NULL。
        # segments_json 缺失时由服务层读取时补算，不改动原有字段；
        # source_batch_id / recomputed_at 为 NULL 表示非复算记录。
        columns = _column_names(conn, "batches")
        if "segments_json" not in columns:
            conn.execute("ALTER TABLE batches ADD COLUMN segments_json TEXT")
        if "source_batch_id" not in columns:
            conn.execute("ALTER TABLE batches ADD COLUMN source_batch_id INTEGER")
        if "recomputed_at" not in columns:
            conn.execute("ALTER TABLE batches ADD COLUMN recomputed_at TEXT")


def insert_batch(
    *,
    name: str,
    points: List[Dict[str, Any]],
    integral_raw: float,
    integral_display: str,
    verdict: str,
    segments: List[Dict[str, Any]],
    source_batch_id: Optional[int] = None,
    recomputed_at: Optional[str] = None,
) -> Dict[str, Any]:
    created_at = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        # 原始点、总积分与分段明细在同一条 INSERT（同一事务）中落库；
        # 复算记录同时落来源窑次编号与复算时间，原记录不被触碰
        cursor = conn.execute(
            """
            INSERT INTO batches
                (name, points_json, point_count, integral_raw,
                 integral_display, verdict, segments_json,
                 source_batch_id, recomputed_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                json.dumps(points, ensure_ascii=False),
                len(points),
                integral_raw,
                integral_display,
                verdict,
                json.dumps(segments, ensure_ascii=False),
                source_batch_id,
                recomputed_at,
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
        "segments": segments,
        "source_batch_id": source_batch_id,
        "recomputed_at": recomputed_at,
        "created_at": created_at,
    }


def list_batches() -> List[Dict[str, Any]]:
    with _connect() as conn:
        # LEFT JOIN 取来源窑次名称，供历史列表标识「复算自某窑次」
        rows = conn.execute(
            """
            SELECT b.id, b.name, b.point_count, b.integral_raw,
                   b.integral_display, b.verdict, b.created_at,
                   b.source_batch_id, s.name AS source_name
            FROM batches b
            LEFT JOIN batches s ON s.id = b.source_batch_id
            ORDER BY b.id DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def get_batch(batch_id: int) -> Optional[Dict[str, Any]]:
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT id, name, points_json, point_count, integral_raw,
                   integral_display, verdict, segments_json,
                   source_batch_id, recomputed_at, created_at
            FROM batches WHERE id = ?
            """,
            (batch_id,),
        ).fetchone()
    if row is None:
        return None
    record = dict(row)
    record["points"] = json.loads(record.pop("points_json"))
    segments_json = record.pop("segments_json")
    # 旧记录没有明细列值时为 None，由服务层决定是否补算
    record["segments"] = json.loads(segments_json) if segments_json else None
    return record


def count_batches() -> int:
    with _connect() as conn:
        (count,) = conn.execute("SELECT COUNT(*) FROM batches").fetchone()
    return count
