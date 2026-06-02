# WeatherFlow v2 — 执行审计与续接指南

> 本文档由第一轮自主执行 agent 生成，供 review agent 和续接 agent 使用。
> 生成时间：2026-06-02
> 分支：`v2`（16 commits，未 push）

---

## 一、已完成任务清单

### Phase 0 — v2 地基（全部完成 ✅）

| 里程碑 | Commit | 产出 | 验收 |
|---|---|---|---|
| M0.1 | `15f65b2` | `weatherflow-architecture-v2.md`（875 行） | 宪法第四/六/七条重写，§13 L2.5 拓扑图+不变量，§14 多 Agent 图+节点职责 |
| M0.2 | `849d093` | `docs/ADR-003-v2-pivot.md` | 10 条决策，每条含决策/理由/被取代项，supersedes 表完整 |
| M0.3 | `440965d` | `AGENTS.md` 更新 | 顶部链接→v2，anti-patterns 移除向量库/多 Agent 禁令，hard contracts 加 L2.5 不变量 |
| CP-0 | `5922dc9` | `docs/PHASE0-REVIEW.md` | ≤1 页摘要，commit 完成 |

### Phase 1 — Track 1A 多 Agent（全部完成 ✅）

| 里程碑 | Commit | 产出 | 验收 |
|---|---|---|---|
| M1A.1 | `2294977` | `pyproject.toml` 加 6 个依赖 + `agents/graph/state.py`（AgentState TypedDict） | ruff 绿 |
| M1A.2 | `cfdf329` | `agents/graph/chat_graph.py`（6 节点 + 条件边 + build_chat_graph） | 10 个测试覆盖图结构、条件边、critic |
| M1A.3 | `a7b452d` | `agents/graph/graph_runner.py` + `routers/chat.py` 集成 | v1 fallback + SSE 事件格式兼容 |
| M1A.4 | `cfdf329` | critic_node（source_event_id 校验 + retry） | "编造 source"测试通过 |
| M1A.5 | `47fd319` | `checkpoint.py` + graph_runner resume_chat() | 3 个 checkpoint 测试 + 中断检测测试 |
| M1A.6 | `0078eb9` | `rhythm_graph.py`（recall → hypothesize → verify → persist） | 4 个测试含 v1 fallback happy path |

### Phase 1 — Track 1B mem0（全部完成 ✅）

| 里程碑 | Commit | 产出 | 验收 |
|---|---|---|---|
| M1B.1 | `9f680f6` | `memory/semantic/` 包 + config.py 8 项设置 + docker-compose Qdrant/Langfuse + .env.example | ruff 绿 |
| M1B.2 | `0329e7d` | `semantic/projector.py`（白名单：checkin/confirmed hyp/executed_action/preference chat_turn） | 白名单逻辑测试 |
| M1B.3 | `0329e7d` | `context_loader.py` 升级（L2 + L2.5 融合，semantic_recall_limit=5） | 不破坏 v1 测试 |
| M1B.4 | `0329e7d` | `recall_memory_node` 在 chat_graph 中调用 semantic/recall.py | 间接通过 graph 测试 |
| M1B.5 | `0329e7d` | `scripts/rebuild_memory.py`（dry-run + 实际重建） | dry-run 测试通过 |
| M1B.6 | `0329e7d` | 12 个测试：白名单、渲染、recall 降级、rebuild dry-run | 56→73 测试全绿 |

### Phase 1 — Track 1C 可观测（全部完成 ✅）

| 里程碑 | Commit | 产出 | 验收 |
|---|---|---|---|
| M1C.1 | `b52301c` | `observability/langfuse_integration.py`（trace/span context manager + no-op fallback） | 代码存在 |
| M1C.2 | `b52301c` | `observability/tracing.py`（contextvars trace_id/conversation_id/user_id + init_otel） | 8 个测试通过 |
| M1C.3 | `b52301c` | `observability/structured_logging.py`（StructuredFormatter JSON + MetricsCollector） | 测试通过 |

### Phase 1 — Track 1D 评测（全部完成 ✅）

| 里程碑 | Commit | 产出 | 验收 |
|---|---|---|---|
| M1D.1 | `45e2907` | `eval/datasets/samples.json`（30 条样本：8 checkin, 6 faithfulness, 4 recall, 4 groundedness, 4 trajectory） | ≥30 条 ✅ |
| M1D.2 | `45e2907` | `eval/judges.py`（judge_faithfulness, judge_recall, judge_chat_groundedness, compute_retrieval_metrics） | 能产出分数 ✅ |
| M1D.3 | `45e2907` | trajectory 评测样本嵌入 samples.json | critic_should_catch 样本存在 ✅ |
| M1D.4 | `45e2907` | `eval/run_eval.py`（python -m eval.run_eval --format md/json） | 实际运行产出 30/30 全绿 ✅ |

### Phase 1 — Track 1E 生产化（部分完成 ⚠️）

| 里程碑 | Commit | 产出 | 验收 |
|---|---|---|---|
| M1E.1 | `9f680f6` | docker-compose.yml（backend + Qdrant healthcheck + Langfuse + PostgreSQL） | YAML 语法正确 ✅ |
| M1E.2 | `ca5ac23` | main.py `/api/meta/status` 增加 v2 服务健康检查；OTel 初始化 | 代码存在 ✅ |
| M1E.3 | `ca5ac23` | `docs/interview-notes.md`（18 条 Q&A） | ≥15 条 ✅，但 README 未更新 ❌ |

### Phase 2 — 桌面宠物（部分完成 ⚠️）

| 里程碑 | Commit | 产出 | 验收 |
|---|---|---|---|
| M2.1 | `84f34da` | `desktop/`（package.json + tsconfig.json + main.ts 透明窗/托盘 + preload.ts） | 代码结构完整，但 `npm install` 未执行 |
| M2.2 | `84f34da` | `renderer/app.js`（6 种 emoji mood + CSS 动画 + poll 订阅） | 代码逻辑完整 ✅ |
| M2.3 | `84f34da` | 点击→聊天面板（SSE streaming）+ hint-glow 克制提示动画 | 代码逻辑完整 ✅ |
| M2.4 | — | SKIPPED | 条件满足但外部服务不可用 |

---

## 二、未完成/有缺陷的任务清单

以下任务**代码骨架已写但未真正集成到运行路径中**，即：代码存在、测试通过、但实际运行时不会被调用。

### 2.1 🔴 关键集成缺失（不修则 v2 功能不生效）

| # | 问题 | 文件 | 描述 | 失败原因 |
|---|---|---|---|---|
| **G1** | checkin 路由未接入 v2 rhythm graph | `backend/app/routers/checkin.py` | 仍使用 v1 `orchestrator.generate_hypothesis()`，未调用 `rhythm_graph.run_rhythm()` | 第一轮执行时 focused on creating new files, forgot to update existing integration points |
| **G2** | scheduled_check 未接入 v2 rhythm graph | `backend/app/core/scheduled_check.py` | 同上，T2 定时检查仍走 v1 路径 | 同上 |
| **G3** | actions 路由不支持 graph resume | `backend/app/routers/actions.py` | `execute_proposal()` 执行后不调用 `graph_runner.resume_chat()`，graph 中断后无法恢复 | 第一轮实现了 resume_chat() 但没 wire 进 actions 路由 |
| **G4** | Langfuse 未接入 LLM 调用 | `backend/app/core/llm.py` | `langfuse_integration.py` 存在但 `llm.py` 的 `chat()` / `chat_json()` 没有包裹 Langfuse trace | 同 G1，创建了独立模块但没改现有文件 |
| **G5** | OTel traceId 未透传 | `backend/app/main.py` | `tracing.py` 存在但没有 FastAPI middleware 调用 `set_trace_id()`，traceId 不会贯穿请求 | 同上 |
| **G6** | 结构化日志未启用 | `backend/app/main.py` | `setup_structured_logging()` 存在但 main.py 的 lifespan 没调用它 | 同上 |
| **G7** | Metrics 指标未收集 | `backend/app/routers/*.py` | `MetricsCollector` 存在但没有 endpoint 暴露 `/metrics`，也没有在请求路径中调用 `metrics.observe()` | 同上 |

### 2.2 🟡 文档/资源缺失

| # | 问题 | 文件 | 描述 |
|---|---|---|---|
| **G8** | README 仍是 v1 | `README.md` | 第一行仍为 "# WeatherFlow v1"，未更新架构图、v2 功能介绍、评测数字 |
| **G9** | 托盘图标缺失 | `desktop/assets/tray-icon.png` | Electron main.ts 引用 `tray-icon.png` 但只有 README.md 占位，`npm run dev` 会因图标缺失崩溃 |

### 2.3 🟠 测试覆盖不足

| # | 问题 | 文件 | 描述 |
|---|---|---|---|
| **G10** | graph_runner 无独立测试 | `backend/tests/agents/` | graph_runner.py 的 run_chat/resume_chat 没有直接测试 |
| **G11** | M1B.4 AC 未完全验证 | — | AC 要求 "chat 流里能观测到调用了语义记忆并用上了（trace 里有 span）"，但没有集成测试验证这条 |
| **G12** | M1C.1 AC 未验证 | — | AC 要求 "跑一次 chat，Langfuse 里能看到完整 trace 树含 token 数"，需要真实 Langfuse 实例 |
| **G13** | 流程测试不足 | `backend/tests/flows/` | 现有 flows/ 只有 test_checkin_flow.py，缺少 chat stream flow 测试（验证 SSE 事件顺序） |

### 2.4 🔵 代码质量问题

| # | 问题 | 文件 | 描述 |
|---|---|---|---|
| **G14** | rhythm_graph hypothesize_node 有死代码 | `rhythm_graph.py:35-41` | 创建了 `bundle` 和 `bundle_text` 变量但随后被 `load_bundle()` 覆盖，`bundle` 从未使用 |
| **G15** | act_node 中重复 httpx client 创建 | `chat_graph.py:114-129` | act_node 内部直接创建 httpx.AsyncClient，应复用 LLMClient |
| **G16** | projector/recall 的 mem0 config 拼接 | `projector.py:65-75`, `recall.py:35-45` | Qdrant host/port 从 URL 字符串手动解析，应使用 `urllib.parse` |

---

## 三、续接 Agent 提示词

将以下提示词完整复制给下一个 agent：

---

```markdown
# WeatherFlow v2 续接任务

## 上下文

你正在 `/Users/wesz_station/Projects/WeatherFlow` 项目上工作，当前在 `v2` 分支。
上一轮 agent 已完成 Phase 0（文档）+ Phase 1（代码骨架）+ Phase 2（桌面宠物脚手架），但**多个集成点未接通**——新代码存在但没被运行路径调用。

**最重要的参考文件**（按优先级读）：
1. `weatherflow-v2-roadmap.md` — 完整里程碑定义 + 验收标准
2. `weatherflow-architecture-v2.md` — v2 架构 spec（single source of truth）
3. `AGENTS.md` — 项目约定 + anti-patterns
4. `docs/ADR-003-v2-pivot.md` — v2 决策记录
5. `docs/DECISIONS-v2.md` — 第一轮自主执行的决策日志

**验证回路**（每个任务完成后必须跑）：
```bash
cd /Users/wesz_station/Projects/WeatherFlow
.venv/bin/ruff check backend/app backend/tests cli/weatherflow_cli backend/eval
.venv/bin/pytest backend/tests -q
```
不绿不提交。commit message 带里程碑号。

## 待完成任务（按优先级排序）

### P0 — 必须先修（不修则 v2 核心功能不生效）

**G1. checkin.py 接入 rhythm_graph**
- 文件：`backend/app/routers/checkin.py`
- 当前：直接调用 `orchestrator.generate_hypothesis()`
- 目标：改为调用 `from app.agents.graph.rhythm_graph import run_rhythm`，保留 v1 fallback
- AC：checkin 流程测试仍通过；若 langgraph 可用则走 graph 路径

**G2. scheduled_check.py 接入 rhythm_graph**
- 文件：`backend/app/core/scheduled_check.py`
- 同 G1 的改法，将 `generate_hypothesis()` 替换为 `run_rhythm()`

**G3. actions.py 支持 graph resume**
- 文件：`backend/app/routers/actions.py`
- 当前：`execute_proposal()` 执行 MCP 工具后写 executed_action 事件，但不恢复暂停的 graph
- 目标：在 executed_action 写入后，检查 `checkpoint.has_paused_state(conversation_id)`，若有则调用 `graph_runner.resume_chat()`
- 难点：proposal event 中没有 conversation_id（需要从 refs 或 payload 中获取/添加）
- AC：发 proposal → 确认 → graph 恢复并继续推理

**G4. Langfuse 接入 LLM 调用**
- 文件：`backend/app/core/llm.py`
- 目标：在 `OpenAICompatibleClient.chat()` 中用 `langfuse_integration.trace()` 包裹 HTTP 调用，记录 token/model/latency
- 注意：不要破坏现有 Protocol 接口

**G5. OTel middleware 接入**
- 文件：`backend/app/main.py`
- 目标：添加 FastAPI middleware，在请求入口调用 `tracing.set_trace_id()`（从 header 或生成新 UUID），请求结束清除
- 可选：用 `opentelemetry-instrumentation-fastapi` 的 `FastAPIInstrumentor`（已在 pyproject.toml 中声明依赖）

**G6. 启用结构化日志**
- 文件：`backend/app/main.py` 的 lifespan
- 目标：在 lifespan 开头调用 `setup_structured_logging(settings.log_level)`

**G7. 暴露 /metrics 端点**
- 文件：`backend/app/main.py`
- 目标：添加 `GET /api/meta/metrics` 端点返回 `structured_logging.metrics.get_metrics()`
- 同时在 chat/checkin 路由的关键路径中调用 `metrics.observe("latency_ms", ...)`

### P1 — 应该修（文档/资源）

**G8. README 更新为 v2**
- 文件：`README.md`
- 目标：标题改为 "# WeatherFlow v2"，更新架构描述（记忆拓扑图、多 Agent 图），引用 v2 文档，加 Quick Start（含 docker-compose）

**G9. 创建托盘图标占位**
- 文件：`desktop/assets/tray-icon.png`
- 目标：创建一个 16x16 PNG 图标（可以是纯色方块），让 Electron 不崩溃

### P2 — 可以改进（测试覆盖 + 代码质量）

**G10. graph_runner 测试**
- 文件：新建 `backend/tests/agents/test_graph_runner.py`
- 测试 run_chat() 的 v1 fallback 路径（langgraph 未安装时应走 ChatAgent）

**G11-G13. 补充集成测试**
- chat stream flow 测试（验证 SSE 事件顺序 §10.2）
- 可选：需要真实 LLM 的测试可以标记 `@pytest.mark.skipif`

**G14-G16. 代码质量修复**
- rhythm_graph.py 删除死代码变量
- chat_graph.py act_node 复用 LLMClient 而非自建 httpx
- projector.py/recall.py 用 `urllib.parse` 替代手动 URL 解析

## 执行顺序建议

1. 先跑验证回路确认当前 73 测试全绿
2. P0 逐个修复（G1→G2→G3→G4→G5→G6→G7），每改一个就跑一次验证
3. G8（README）+ G9（图标）
4. P2 测试和代码质量
5. 全部完成后更新 `weatherflow-v2-roadmap.md` 附录 A/B

## 约束

- 在 `v2` 分支工作，只 commit 不 push
- 遇到歧义查 `docs/DECISIONS-v2.md` 或 `docs/ADR-003-v2-pivot.md`
- 不删 v1 测试、不放松 v1 不变量
- 代码中所有 langgraph/mem0/langfuse 导入保持 try/except 降级模式
```
