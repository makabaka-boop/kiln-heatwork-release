# 窑炉烧成判定台

窑炉控制器导出的采样间隔不固定，温度又可能在两个采样点之间越过计热起点。
本系统接收一窑次的温度采样点，按统一约定积分出计热值（°C·min），
并给出唯一结论：**欠烧 / 合格 / 过烧**。

- 后端：FastAPI + SQLite（`api/`）
- 前端：React + Vite + TypeScript（`web/`）
- 编排：Docker Compose（`web`、`api` 与一次性验收服务 `verify`）

## 快速开始

```bash
docker compose up --build
```

- 判定台页面：http://localhost:8080 （可用 `WEB_PORT` 覆盖宿主端口）
- API：http://localhost:8000/api/health （可用 `API_PORT` 覆盖宿主端口）

```bash
WEB_PORT=9000 API_PORT=9001 docker compose up --build
```

合法提交会保存**原始采样点、未舍入积分、展示值与结论**到 SQLite
（命名卷 `api-data`），刷新页面后仍可在「历史记录」中点开复查；
任一采样点非法则整次不落库，页面在对应位置标出索引与原因。

## 一键验收

`verify` 是一次性验收服务，对运行中的 web 与 api 做真实 HTTP 联调：
经 nginx 代理提交合法/边界/非法批次，并用**独立复写的积分实现**复核
积分、舍入、结论与落库行为，全部通过则以退出码 0 结束。

```bash
docker compose --profile verify up --build --exit-code-from verify --abort-on-container-exit
```

## 判定规则

1. 相邻采样点之间温度**线性**变化，这是唯一的插值约定；
2. 只累计温度**高于 600 °C** 的部分，即对 `max(T(t) − 600, 0)` 关于时间积分；
3. 跨越 600 °C 时先按线性关系求交点、再切段，以梯形法求面积，单位 °C·min；
4. 积分按**四舍五入（half-up）保留一位小数**得到展示值；
5. 以展示值判定：`< 18000.0` 欠烧；`18000.0 ~ 24000.0`（含两端）合格；
   `> 24000.0` 过烧。

## 积分实现与示例演算

实现见 [`api/app/heatwork.py`](api/app/heatwork.py)。核心是单段积分
`_segment_area`：记段长 `dt`（分钟）、两端点超出 600 °C 的量 `e0`、`e1`：

- `e0 ≤ 0` 且 `e1 ≤ 0`：整段不高于计热起点，贡献 0；
- `e0 > 0` 且 `e1 > 0`：整段在起点之上，梯形面积 `(e0 + e1) · dt / 2`；
- 段内穿越 600 °C：线性求交点位置 `s* = e0 / (e0 − e1)`，
  只取高于起点的那半个三角形——下降段 `e0 · s* · dt / 2`，
  上升段 `e1 · (1 − s*) · dt / 2`。

全程用 `Fraction` 做精确有理数运算，最后才转 `Decimal` 做 half-up 舍入，
避免浮点误差影响 `…x.x5` 边界的判定。

**示例一（穿越切段）**：两点 `(00:00, 500 °C)`、`(01:00, 700 °C)`。
温度 60 min 内从 500 线性升到 700，在 30 min 处越过 600 °C；
只有后 30 min 计热，超出量从 0 线性升到 100 °C：

```
面积 = 1/2 × 30 min × 100 °C = 1500.0 °C·min   -> 欠烧
```

**示例二（页面「填入示例」按钮的曲线）**：

| 时刻 | 温度 |
| --- | --- |
| 08:00 | 600 °C |
| 10:00 | 700 °C |
| 12:00 | 700 °C |
| 13:00 | 600 °C |

```
08:00-10:00  600→700  梯形 (0+100)/2 × 120   =  6000.0
10:00-12:00  700→700  矩形 100 × 120         = 12000.0
12:00-13:00  700→600  三角形 100 × 60 / 2    =  3000.0
合计                                       = 21000.0 °C·min -> 合格
```

## 提交校验

| 规则 | 错误定位 |
| --- | --- |
| 窑次名称非空（≤ 120 字符） | 名称输入框 |
| 采样点 2–200 个 | 表单整体错误区 |
| 每点 `time` 为合法 ISO 8601（须含时刻；无时区按 UTC） | 对应该点时刻框 |
| 每点 `temperature` 为 0–1400 的数字 | 对应该点温度框 |
| 时刻严格递增（同一瞬时不同时区表示也算重复） | 对应该点时刻框 |
| 首末间隔 ≤ 12 小时（含恰 12 小时） | 表单整体错误区 |

所有错误一次收集完毕再返回；任一非法点则整次不落库。

## API 一览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 健康检查 |
| POST | `/api/batches` | 提交窑次；201 返回判定，422 返回全部定位错误 |
| GET | `/api/batches` | 历史列表（新的在前） |
| GET | `/api/batches/{id}` | 详情，含原始采样点与未舍入积分 |

提交体：

```json
{
  "name": "K-2026-0911-A",
  "points": [
    {"time": "2026-09-11T08:00:00Z", "temperature": 600},
    {"time": "2026-09-11T10:00:00Z", "temperature": 700}
  ]
}
```

201 响应（节选）：`integral_raw` 为未舍入积分，`integral_display`
为一位小数字符串，`verdict` ∈ `underfired | qualified | overfired`，
`verdict_label` 为 `欠烧 | 合格 | 过烧`。

422 响应：

```json
{
  "detail": {
    "message": "提交数据未通过校验，本次数据未保存。",
    "errors": [
      {"index": 1, "field": "temperature", "message": "温度须在 0 至 1400°C 之间，收到 1500"},
      {"index": 2, "field": "time", "message": "时刻必须严格递增：该点不晚于第 1 个采样点 …"}
    ]
  }
}
```

## 测试

```bash
# 后端：积分边界、校验、API 落库（45 例）
cd api && pip install -r requirements-dev.txt && pytest

# 前端：错误映射、结论展示、表单交互（11 例）
cd web && npm ci && npm test

# 真实联调：浏览器 -> web -> api -> SQLite（3 例）
docker compose up --build -d          # 或本地起 uvicorn + vite preview
cd web && npx playwright install chromium
PLAYWRIGHT_BASE_URL=http://localhost:8080 npm run test:e2e
```

## 本地开发

```bash
cd api && pip install -r requirements-dev.txt
uvicorn app.main:app --reload          # http://localhost:8000

cd web && npm ci && npm run dev        # http://localhost:5173（/api 已代理到 8000）
```

## 目录结构

```
├── docker-compose.yml      # web / api / verify 三服务
├── api/                    # FastAPI 后端
│   ├── app/heatwork.py     #   计热积分（精确有理数 + half-up 舍入）
│   ├── app/validation.py   #   逐点校验，收集全部可定位错误
│   ├── app/db.py           #   SQLite 落库
│   └── tests/              #   pytest：积分边界 / 校验 / API 联调
├── web/                    # React 前端
│   ├── src/components/     #   表单（逐点错误定位）、结果、历史、详情
│   ├── src/__tests__/      #   Vitest 单元与组件测试
│   └── e2e/                #   Playwright 真实联调
└── verify/                 # 一次性验收服务（独立复算 + 真实 HTTP）
```
