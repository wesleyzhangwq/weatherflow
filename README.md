# WeatherFlow v2

> **节奏镜像 + 日常驾驶舱。** 给陷入「低效—无复盘—更低效」循环的开发者。

完整设计（single source of truth）：[weatherflow-architecture-v2.md](./weatherflow-architecture-v2.md)
v2 决策记录：[docs/ADR-003-v2-pivot.md](./docs/ADR-003-v2-pivot.md) ·
v1 文档存档：[weatherflow-architecture-v1.md](./weatherflow-architecture-v1.md)

> **v2 做了什么**：在 v1（事件溯源 + 单 ReAct agent）的地基上，补齐生产级 LLM 应用的硬通货——
> **多 Agent 编排（LangGraph）**、**语义记忆层（mem0 + Qdrant，L1 的可重建派生投影）**、
> **全链路可观测（Langfuse trace + OpenTelemetry traceId + 指标）**、**评测回归 harness**，
> 以及一个体现「克制的主动」的**桌面宠物卫星 App（Electron）**。
> 关键不变量没有放松：**L1 永远 append-only，一切皆派生**。
>
> **v2.5（overhaul）**：Agent 原生接口层重造——**统一 MCP server（全协议表面）+ Skills 体系 + 协议先行的工具注册**。详见下节与 [docs/overhaul/](./docs/overhaul/)。

---

## Agent 原生接口：MCP × Skills

任何 MCP host（Claude Code / Keel / 自研客户端）一条命令接入 WeatherFlow 的全部能力：

```bash
claude mcp add weatherflow -- uv run python -m mcp_servers.weatherflow
# 或远程多客户端：uv run python -m mcp_servers.weatherflow --transport http --port 8765
```

**统一 server 的协议表面**（`mcp_servers/weatherflow/`）：

| 维度 | 内容 |
|---|---|
| **Tools ×15** | `calendar.*` + `github.*`，全部带 **ToolAnnotations**（readOnly/destructive/idempotent/openWorld）+ `_meta.weatherflow.mode` 三态桶——host 可据此自建门禁策略 |
| **Resources ×5** | `weatherflow://profile`（L3 画像）· `events/recent`（L1 尾）· `rhythm/current` · `hypotheses/active` · `skills`（技能索引）——只读、store 缺失时优雅降级 |
| **Prompts ×3** | `weekly_review` / `plan_today` / `rhythm_checkin` 参数化工作流 |
| **传输 ×2** | stdio（默认）+ streamable HTTP（`--transport http`） |

**Skills**（[skills/](./skills/)）：能力（MCP）之上的方法论层——周回顾怎么做才有证据纪律、
教练该有什么礼仪、server 怎么接怎么修。渐进披露格式，且**可经协议分发**：
`skill://weatherflow/{name}` 直接取 SKILL.md 全文，远程 host 无需文件系统。

**协议先行**：backend 启动时经 MCP `list_tools` **发现**工具注册表
（三态从 annotations/meta 推导，destructive 永不注册），手写表只是离线兜底——
schema 的唯一事实源是 server 本身；读路径走 actor 式**长驻会话池**（每命令一个 owner task），
复用连接、传输开销摊销为零。

**安全模型三层**：annotations 声明（server 诚实自报）→ host 门禁（三态注册表 + 写操作一律
Proposal/HITL）→ server 侧兜底（`WF_MCP_WRITE_TOOLS_ENABLED` 总闸 + 全部写工具支持 `dry_run`）。

---

## 产品宪法（v2 标注）

| # | 宪法 | v2 状态 |
|---|---|---|
| 1 | **身份** — 节奏教练 + 日常驾驶舱 | 保留 |
| 2 | **双模式** — 节奏镜像（被动）+ 日常驾驶舱（主动） | 保留 |
| 3 | **第一屏** — 永远是 hypothesis 卡片堆 | 保留 |
| 4 | **集成红线** — 核心集成只有 Calendar 和 GitHub | **v2 修改**：重构为可插拔 Provider SPI，仍是 curated 小集合 |
| 5 | **承诺** — 在 burnout 前拉一把 | 保留 |
| 6 | **哲学** — hypothesis 必须有 evidence，evidence 必须可溯源 | 保留；**v2 放开**：允许向量库作为 L1 的派生召回层 |
| 7 | **节制的主动** | **v2 修改**：克制提示（calibrated proactivity）——可轻微动效，禁系统通知 / 禁抢焦点 / 可关闭 |
| 8 | **写操作唯一入口** — Proposal 只在 Chat 流程中生成 | 保留；v2 实现为 LangGraph human-in-the-loop interrupt + checkpointer |
| 9 | **卡片是脸** | 保留 |

详见 ADR-003 的 10 条决策与 supersedes 表。

---

## 四种输入 → 六种输出

```
T1 Check-in        ─┐
T2 定时检查 (6h)   ─┼─ run_rhythm() / generate_hypothesis() ─┬→ L1 events 表
T3 Hypothesis 校准 ─┤   (LangGraph 子图, v1 fallback)        ├→ Hypothesis 卡片堆 (主页 ≤3)
T4 Chat 消息       ─┘                                        ├→ Chat SSE 流
                                                              ├→ Proposal 卡 (Chat 拦截 write)
                                                              ├→ DelayedMemoryWriter → profile.md
                                                              └→ L1 审计记录
```

---

## 四层记忆系统（v2 新增 L2.5）

```
L1  Event Log (SQLite, append-only)            ← 唯一真理，永不修改
      │
      ├─► L2   Working Context (EvidenceBundle)  ← 每请求装配，基于「最近性」
      │
      ├─► L2.5 Semantic Memory (mem0 + Qdrant)   ← 【v2 新增】基于「语义相关性」的召回层
      │          · 是 L1 高价值事件的派生投影（带回指 source_event_id）
      │          · 可由 scripts/rebuild_memory.py 从 L1 完整重建
      │          · 绝不是新的真理来源
      │
      └─► L3   Profile.md (6 固定章节)            ← DelayedMemoryWriter 四道门槛
```

| 层 | 形态 | 写入路径 |
|---|---|---|
| **L1** Event Log | SQLite `events` 单表，append-only | 所有 4 种输入直接落库 |
| **L2** Working Context | EvidenceBundle（临时，不落盘） | 每次请求 ContextLoader 从 L1 装配 |
| **L2.5** Semantic Memory | mem0 + Qdrant 向量库 | MemoryProjector 投影白名单事件；可从 L1 重建 |
| **L3** Profile.md | 6 个固定章节的 markdown | DelayedMemoryWriter 经 4 道门槛后写入 |

> **不变量**：删掉整个 Qdrant，`scripts/rebuild_memory.py` 能从 L1 把 L2.5 一键重建。
> 每条语义记忆都带 `source_event_id` 回链，可被 hypothesis 引用、可在 UI 溯源。

---

## 多 Agent 编排（LangGraph）

v2 把单 ReAct loop 升级为带 planner / worker / critic 的状态图：

```
        load_context → recall_memory → plan → act → criticize → synthesize → END
                                               ↑          │
                                               └── retry ─┘   (groundedness 不达标回退 re-plan)
```

- **act** 节点承载工具循环：read → observation，write → Proposal（human-in-the-loop interrupt）。
- **criticize** 节点做运行时自检：校验答案/hypothesis 的每条 evidence 是否真挂在 bundle 内真实 `source_event_id`，不达标触发一次 re-plan。
- **Proposal interrupt**：write tool 让图暂停并由 checkpointer 持久化；`POST /api/actions/{id}/execute` 确认后从断点 `resume`，继续推理。
- **RhythmAgent 子图**（T1/T2）：`recall → hypothesize → verify_sources → persist`，与 chat 图共享 recall 节点。

> **降级**：`langgraph` 现在是硬依赖（chat 图 + checkpointer 在 lifespan 编译）；`run_rhythm` 在图执行失败时
> 回退 v1 `generate_hypothesis`。mem0 / langfuse 保持 try/except 降级：Qdrant 不在 → 纯 recency 召回，
> 缺 Langfuse key → 只打结构化日志。SSE 事件契约（§10.2）不变，新增 `answer_delta`（token 流）与
> `memories_recalled`（语义召回可视化）两个事件。

---

## 可观测性

- **Langfuse**：每次 LLM 调用包成 trace，记录 model / token / latency（`core/llm.py::_post_chat`）。缺 key 时降级为只打结构化日志、不报错。
- **OpenTelemetry traceId**：`TraceContextMiddleware` 在 HTTP 入口生成/透传 traceId（`X-Trace-Id` header），经 contextvars 贯穿 router → orchestrator → graph 节点 → tool → llm，并回写到响应头。
- **结构化日志**：JSON 日志带 `trace_id / conversation_id / user_id`。
- **指标**：`GET /api/meta/metrics` 暴露 token 用量、各阶段延迟 P50/P95、调用计数等。

---

## 评测（Eval）

> **🚧 已整体拆除，待重建。** 原 v1 评测框架把静态结构检查与 live 评测混在一起，
> 且半数 judge（recall/groundedness/trajectory）从未接到真实 agent 链路、12 条
> check-in 样本被静默丢弃。鉴于 v2 agent 架构（多 Agent 图 / 真 HITL / trace 树）
> 已巨变，评测体系将针对新架构**推倒重建**（ADR-005）。旧框架与 30 条标注样本保留
> 在 git 历史中供重建参考。

---

## 快速开始

### 方式 A — 一键 docker-compose（全栈）

```bash
cp .env.example .env
# 至少填: OPENAI_API_KEY, OPENAI_BASE_URL, CHAT_MODEL（语义记忆需 EMBEDDING_API_KEY）
docker compose up -d            # backend + frontend + qdrant + langfuse(+ langfuse-db)
curl http://127.0.0.1:8765/health
curl http://127.0.0.1:8765/api/meta/status   # v2_services 健康检查
```

### 方式 B — 本地开发

```bash
cp .env.example .env
uv sync --all-packages --all-extras

# 后端
uv run uvicorn app.main:app --app-dir backend --port 8765
# 前端
cd frontend && npm install && npm run dev
# (可选) 语义记忆只需 Qdrant：
docker compose up -d qdrant
# (可选) Langfuse trace 树：
docker compose up -d langfuse

# CLI
uv run wf start              # 一键起后端 + 前端
uv run wf setup-calendar     # 一次性的 Google OAuth 授权
```

> **本机代理用户**（Clash/V2Ray 等）：若 LLM/embedding 调用偶发
> `CERTIFICATE_VERIFY_FAILED`，在 `.env` 里把这些 API 域名加入
> `NO_PROXY_HOSTS`（例：`NO_PROXY_HOSTS=api.minimaxi.com,api.siliconflow.cn`）
> 让它们绕开代理直连。

### 桌面宠物（Electron）

```bash
cd desktop && npm install && npm run dev   # 透明无边框小窗 + 系统托盘
```

角色表情映射 6 种 rhythm label（Flow / Recovery / Steady / Overload / Blocked / Fragmented），
通过 SSE/poll 订阅后端当前 hypothesis；新 hypothesis 时做**克制**的提示动效（不弹通知、不抢焦点、可在设置里关闭）。

---

## API 一览

| Method | Path | 触发 | 说明 |
|---|---|---|---|
| POST | `/api/checkin` | T1 | 三问表单 → 同步返回 hypothesis（经 rhythm 子图） |
| GET  | `/api/hypotheses` | — | 主页堆（最多 3） |
| GET  | `/api/hypotheses/history` | — | 完整 hypothesis 时间线 + 状态 |
| POST | `/api/hypotheses/{id}/feedback` | T3 | verdict ∈ confirmed/rejected/partial |
| POST | `/api/chat/stream` | T4 | SSE 流（LangGraph chat 图，v1 fallback） |
| GET  | `/api/actions/proposals` | — | 列出 pending proposal |
| POST | `/api/actions/{id}/execute` | — | 确认后调用 MCP write tool，并 resume 暂停的图 |
| POST | `/api/actions/{id}/reject` | — | 拒绝 |
| GET  | `/api/profile` | — | 读 profile.md |
| GET  | `/api/events/{id}` | — | 单 event 详情（evidence 溯源用） |
| GET  | `/api/meta/status` | — | 健康检查（含 v2 服务：Qdrant / Langfuse） |
| GET  | `/api/meta/metrics` | — | 业务指标（token / 延迟 P50·P95 / 计数） |

T2 由 scheduler 在每 0/6/12/18 点自动触发，写 `evidence_summary → hypothesis`。

---

## 测试

```bash
uv run --package weatherflow-backend --extra dev pytest backend/tests -q   # 73 tests
```

```
tests/contracts/  — schema 硬约束 (label 词表 / source_event_id / append-only)
tests/flows/      — T1/T3/T4 端到端 + check-in→feedback→stack + chat SSE 事件顺序
tests/memory/     — DelayedMemoryWriter 四道门槛 / card stack 派生 / 语义投影白名单
tests/tools/      — Dispatcher read/write/destructive
tests/agents/     — LangGraph chat 图 / rhythm 子图 / graph_runner fallback
```

---

## 工程结构

```
backend/app/
├── memory/
│   ├── event_log.py / schemas.py / context_loader.py
│   ├── hypotheses_view.py / delayed_writer.py / profile_md.py
│   └── semantic/           # v2 L2.5: projector.py / recall.py / mem0_config.py
├── agents/
│   ├── rhythm_agent.py / chat_agent.py
│   └── graph/              # v2: state.py / chat_graph.py / rhythm_graph.py
│   │                       #     graph_runner.py / checkpoint.py
├── core/
│   ├── orchestrator.py / scheduled_check.py / scheduler.py
│   ├── evidence_summarizer.py / llm.py
├── observability/          # v2: langfuse_integration.py / tracing.py / structured_logging.py
├── mcp_client/             # client.py / tool_registry.py / dispatcher.py
├── providers/              # v2 Provider SPI: base.py / calendar.py / github.py
├── routers/                # FastAPI 路由
└── main.py
scripts/rebuild_memory.py   # v2: 从 L1 重建 L2.5（证明派生投影不变量）
mcp_servers/                # Calendar + GitHub MCP server
frontend/                   # Next.js: HypothesisStack / DataStrip / Chat / Profile
desktop/                    # v2 Phase 2: Electron 桌面宠物卫星 App
docs/                       # ADR-001/002/003 + interview-notes + v2 审计
docker-compose.yml          # backend + frontend + qdrant + langfuse(+ db)
```

---

## v1 → v2

v2 是 v1 之上的「求职硬通货」演进，不是推倒重来：保留事件溯源地基与全部 v1 不变量，
新增多 Agent / 语义记忆 / 可观测 / 评测 / 桌面宠物。设计立场与 supersedes 关系见
[ADR-003](./docs/ADR-003-v2-pivot.md)，面试 Q&A 见 [docs/interview-notes.md](./docs/interview-notes.md)。
