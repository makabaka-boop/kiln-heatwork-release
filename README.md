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

合法提交会保存**原始采样点、未舍入积分、展示值、结论与逐段计热贡献明细**
到 SQLite（命名卷 `api-data`），刷新页面后仍可在「历史记录」中点开复查；
任一采样点非法则整次不落库，页面在对应位置标出索引与原因。

## 一键验收

`verify` 是一次性验收服务，对运行中的 web 与 api 做真实 HTTP 联调：
经 nginx 代理提交合法/边界/非法批次，并用**独立复写的积分实现**复核
积分、舍入、结论、分段明细与落库行为，全部通过则以退出码 0 结束。
`legacy-seed`（仅 verify profile）会先向 api 的卷写入两条模拟
「升级前保存」的旧记录（无分段明细），verify 借此验收升级兼容性。

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

## 分段计热贡献明细

仅看总热值难以定位哪段升温或保温贡献异常，因此每次合法提交还会按
**相邻采样段**生成贡献明细，与原始点、总积分在同一事务中落库，
并随创建响应与详情响应返回（`segments` 字段，按时间顺序）：

| 字段 | 含义 |
| --- | --- |
| `index` | 段序号（第 `i` 段连接采样点 `i` 与 `i+1`） |
| `start_time` / `end_time` | 段起止时刻（与提交的原始时刻字符串一致） |
| `heating_minutes` | 有效计热分钟数：段内温度高于 600 °C 的时长（穿越段只算交点一侧） |
| `contribution` | 该段未舍入贡献值（°C·min） |
| `share` | 占总积分的比例（总量为 0 时各段记 0） |

各段 `contribution` 之和与 `integral_raw` 在精确有理数层面恒等；
低于起点的零贡献段同样保留展示。页面在提交成功后的判定结果中
直接展示明细表，历史详情中按时间顺序呈现。

**升级兼容**：旧版本库的 `batches` 表没有明细列，启动时自动
`ALTER TABLE` 补齐，已有记录该列为 NULL。读取旧记录的详情时，
服务依据已存原始点**确定性补算**明细后返回，不回写数据库、
不改动原结论；若已存采样点无法形成合法时间序列（时刻不可解析
或未严格递增），详情仍展示原判定，`segments` 为 `null`，
并由 `segments_note` 说明无法生成明细的原因。

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
| POST | `/api/batches` | 提交窑次；201 返回判定与分段明细，422 返回全部定位错误 |
| GET | `/api/batches` | 历史列表（新的在前） |
| GET | `/api/batches/{id}` | 详情，含原始采样点、未舍入积分与分段明细 |

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
`verdict_label` 为 `欠烧 | 合格 | 过烧`；`segments` 为逐段贡献明细
（见上节），`segments_note` 为 `null`。详情响应字段相同；升级前的
旧记录若无法补算明细，则 `segments` 为 `null`、`segments_note`
说明原因，原判定与积分不受影响。

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
# 后端：积分边界、分段明细、校验、API 落库、旧库升级兼容（61 例）
cd api && pip install -r requirements-dev.txt && pytest

# 前端：错误映射、结论展示、分段明细表、表单交互（15 例）
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

## 故障排查

- **web 服务一直 unhealthy**：web 的健康检查只探测自身 nginx
  （`http://127.0.0.1/`），不穿透到 api；对 api 的启动顺序依赖由
  `depends_on: service_healthy` 保证，端到端联通性由 verify 的
  「web 代理 /api 到后端」用例验收。nginx 通过 Docker 内嵌 DNS
  （`resolver 127.0.0.11`）在请求期解析 `api`，api 容器重建、IP 变化后
  无需重启 web 即可恢复代理。
- 查看健康检查失败原因：`docker inspect --format '{{json .State.Health}}' <容器>`。

## 目录结构

```
├── docker-compose.yml      # web / api / verify / legacy-seed 服务
├── api/                    # FastAPI 后端
│   ├── app/heatwork.py     #   计热积分与逐段贡献（精确有理数 + half-up 舍入）
│   ├── app/validation.py   #   逐点校验，收集全部可定位错误
│   ├── app/db.py           #   SQLite 落库与旧表就地升级
│   └── tests/              #   pytest：积分边界 / 分段明细 / 校验 / 升级兼容
├── web/                    # React 前端
│   ├── src/components/     #   表单（逐点错误定位）、结果、分段明细、历史、详情
│   ├── src/__tests__/      #   Vitest 单元与组件测试
│   └── e2e/                #   Playwright 真实联调
└── verify/                 # 一次性验收服务（独立复算 + 真实 HTTP）
    ├── verify.py           #   验收用例
    └── legacy_seed.py      #   写入模拟「升级前」的旧记录（仅 verify profile）
```
