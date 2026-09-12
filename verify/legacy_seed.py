"""升级前数据种子：向 api 的 SQLite 写入不带分段明细的旧记录。

模拟旧版本留下的窑次数据（``segments_json`` 为 NULL），供 verify 服务
通过真实 HTTP 验收「升级前记录可查看、原结论不改写、明细可补算」。
本服务在 api 健康之后运行（表结构已由 api 完成就地升级），写入即退出。
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import urllib.request
from datetime import datetime, timezone

API_BASE = os.environ.get("API_BASE", "http://api:8000").rstrip("/")
DB_PATH = os.environ.get("HEATWORK_DB", "/data/heatwork.db")

# 与 README 示例相同的曲线：积分 21000.0 -> 合格；分段 6000/12000/3000
LEGACY_OK_POINTS = [
    {"time": "2026-09-11T08:00:00Z", "temperature": 600},
    {"time": "2026-09-11T10:00:00Z", "temperature": 700},
    {"time": "2026-09-11T12:00:00Z", "temperature": 700},
    {"time": "2026-09-11T13:00:00Z", "temperature": 600},
]

# 时刻无法解析的旧数据：无法形成合法时间序列，明细应缺失但原判定保留
LEGACY_BROKEN_POINTS = [
    {"time": "not-a-timestamp", "temperature": 700},
    {"time": "2026-09-11T01:00:00Z", "temperature": 700},
]


def wait_for_api() -> None:
    for _ in range(60):
        try:
            with urllib.request.urlopen(f"{API_BASE}/api/health", timeout=3) as resp:
                if resp.status == 200:
                    return
        except OSError:
            pass
        time.sleep(2)
    raise SystemExit("api 未就绪，无法写入升级前数据")


def main() -> None:
    wait_for_api()
    created_at = datetime.now(timezone.utc).isoformat()
    conn = sqlite3.connect(DB_PATH)
    with conn:
        # 不写 segments_json：模拟升级前保存的记录（该列为 NULL）
        conn.execute(
            """
            INSERT INTO batches
                (name, points_json, point_count, integral_raw,
                 integral_display, verdict, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "LEGACY-QUALIFIED",
                json.dumps(LEGACY_OK_POINTS),
                len(LEGACY_OK_POINTS),
                21000.0,
                "21000.0",
                "qualified",
                created_at,
            ),
        )
        conn.execute(
            """
            INSERT INTO batches
                (name, points_json, point_count, integral_raw,
                 integral_display, verdict, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "LEGACY-BROKEN",
                json.dumps(LEGACY_BROKEN_POINTS),
                len(LEGACY_BROKEN_POINTS),
                1500.0,
                "1500.0",
                "underfired",
                created_at,
            ),
        )
    conn.close()
    print("已写入升级前记录：LEGACY-QUALIFIED / LEGACY-BROKEN")


if __name__ == "__main__":
    main()
