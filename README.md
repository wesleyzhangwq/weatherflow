# WeatherFlow v1

> **节奏镜像 + 日常驾驶舱。** 给陷入「低效—无复盘—更低效」循环的开发者。

完整设计：[weatherflow-architecture-v1.md](./weatherflow-architecture-v1.md)
关键技术决策：[docs/ADR-001-v1-refactor.md](./docs/ADR-001-v1-refactor.md)

---

## 产品宪法（节选）

1. **身份** — WeatherFlow 是节奏教练 + 日常驾驶舱。
2. **双模式** — 节奏镜像（被动）+ 日常驾驶舱（主动），缺一不可。
3. **第一屏** — 永远是 hypothesis 卡片堆。查日程要往下滑或打字。
4. **集成红线** — 核心集成只有 Calendar 和 GitHub。**产品立场**。
5. **承诺** — 不让你更高效，让你**看清自己的节奏，在 burnout 前拉一把**。
6. **哲学** — 不假装比你更懂你。**hypothesis 必须有 evidence，evidence 必须可溯源**。
7. **节制的主动** — 不打扰、不通知、不推送。
8. **写操作唯一入口** — Proposal 只在 Chat 流程中生成。
9. **卡片是脸** — Hypothesis 卡是主页核心 UI。

---

## 四种输入 → 六种输出

```
T1 Check-in        ─┐
T2 定时检查 (6h)   ─┼─ generate_hypothesis() ─┬→ L1 events 表
T3 Hypothesis 校准 ─┤                        ├→ Hypothesis 卡片堆 (主页 ≤3)
T4 Chat 消息       ─┘                        ├→ Chat SSE 流
                                              ├→ Proposal 卡 (Chat 拦截 write)
                                              ├→ DelayedMemoryWriter → profile.md
                                              └→ L1 审计记录
```

---

## 三层记忆系统

| 层 | 形态 | 写入路径 |
|---|---|---|
| **L1** Event Log | SQLite `events` 单表，append-only | 所有 4 种输入直接落库 |
| **L2** Working Context | EvidenceBundle (临时，不落盘) | 每次请求时 ContextLoader 从 L1 装配 |
| **L3** Profile.md | 6 个固定章节的 markdown 文件 | DelayedMemoryWriter 经 4 道门槛后写入 |

DelayedMemoryWriter 4 道门槛：
- A. 事件类型白名单（仅 confirmed hypothesis / executed_action）
- B. 同章节 24h 冷却
- C. Rhythm Patterns / Anti-patterns 章节需 14 天内出现 ≥3 次
- D. LLM 自评 confidence ≥ 0.6

---

## 工具系统（§7）

```
read tool        → 直接执行，结果作 observation
write tool       → 被 Dispatcher 拦截，转为 Proposal，等待用户确认
destructive tool → 完全不注册，Agent 看不到 schema
```

支持的工具（来自 Calendar / GitHub MCP server）：
- Calendar：`find_free_slots`、`search_events`、`create_focus_block` (write)、`create_event` (write)
- GitHub：`get_repo_status`、`get_recent_commits`、`list_issues`、`list_pull_requests`、`list_repos`、`create_issue` (write)

---

## 快速开始

```bash
cp .env.example .env
# 至少填: OPENAI_API_KEY, OPENAI_BASE_URL, CHAT_MODEL
uv sync

# 后端
uv run uvicorn app.main:app --app-dir backend --port 8765

# 前端
cd frontend && npm install && npm run dev
```

CLI：

```bash
uv run wf start              # 一键起后端 + 前端
uv run wf stop
uv run wf setup-calendar     # 一次性的 Google OAuth 授权
```

健康检查：

```bash
curl http://127.0.0.1:8765/health
curl http://127.0.0.1:8765/api/meta/status
```

---

## API 一览

| Method | Path | 触发 | 说明 |
|---|---|---|---|
| POST | `/api/checkin` | T1 | 三问表单 → 同步返回 hypothesis |
| GET  | `/api/hypotheses` | — | 主页堆（最多 3） |
| GET  | `/api/hypotheses/history` | — | 完整 hypothesis 时间线 + 状态 |
| POST | `/api/hypotheses/{id}/feedback` | T3 | verdict ∈ confirmed/rejected/partial |
| POST | `/api/chat/stream` | T4 | SSE 流 |
| GET  | `/api/actions/proposals` | — | 列出 pending proposal |
| POST | `/api/actions/{id}/execute` | — | 用户确认后真正调用 MCP write tool |
| POST | `/api/actions/{id}/reject` | — | 拒绝 |
| GET  | `/api/profile` | — | 读 profile.md |
| PUT  | `/api/profile/sections/{section}` | — | 编辑某章节 |
| GET  | `/api/events/{id}` | — | 单 event 详情（evidence 溯源用）|

T2 由 scheduler 在每 0/6/12/18 点自动触发，写 `evidence_summary → hypothesis`。

---

## 数据存储位置

```
backend/data/
├── weatherflow.db       # L1 events 表
└── memory/
    └── default/
        └── profile.md   # L3 长期画像
```

`DATA_DIR` / `MEMORY_MARKDOWN_DIR` 可通过 env 覆盖。

---

## 测试

```bash
uv run pytest backend/tests -q
# 75 tests covering:
#  - tests/contracts/  — schema 硬约束 (label 词表 / source_event_id / append-only)
#  - tests/flows/      — T1/T3 端到端 + check-in→feedback→stack
#  - tests/memory/     — DelayedMemoryWriter 四道门槛 / card stack 派生
#  - tests/tools/      — Dispatcher read/write/destructive
```

---

## 工程结构

```
backend/app/
├── memory/              # L1 / L2 / L3 三层
│   ├── event_log.py
│   ├── schemas.py
│   ├── context_loader.py
│   ├── hypotheses_view.py
│   ├── delayed_writer.py
│   └── profile_md.py
├── agents/
│   ├── rhythm_agent.py  # 生成 hypothesis
│   └── chat_agent.py    # ReAct loop (T4)
├── core/
│   ├── orchestrator.py  # generate_hypothesis() 统一入口
│   ├── scheduled_check.py
│   ├── scheduler.py     # APScheduler
│   ├── evidence_summarizer.py
│   └── llm.py
├── mcp_client/
│   ├── client.py
│   ├── tool_registry.py # 三态 mode 模型
│   └── dispatcher.py    # read/write/destructive 分发
├── providers/
│   ├── calendar.py
│   └── github.py
├── routers/             # FastAPI 路由
└── main.py
mcp_servers/             # Calendar + GitHub MCP server
frontend/                # Next.js, 主页 = HypothesisStack, /chat, /profile
docs/
├── ADR-001-v1-refactor.md
└── PHILOSOPHY.md
```

---

## v1 vs 之前的版本

这次重构推倒了 dev_review / reflection / state_snapshot / patterns 等旧实现，只实现文档 §1 产品宪法允许的最小集。详见 [ADR-001](./docs/ADR-001-v1-refactor.md)。
