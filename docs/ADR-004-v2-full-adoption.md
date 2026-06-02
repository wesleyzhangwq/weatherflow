# ADR-004: v2 范式完整落地（多 Agent / HITL / 可观测 / 记忆重设计）

**日期**：2026-06-02
**状态**：Accepted
**上下文**：v2（ADR-003）引入了 LangGraph、mem0、Langfuse/OTel，但**只是半采用**——图存在却靠 v1 fallback 旁路遮着、HITL 用进程内 dict 假装持久化、每个节点各开 LLM client 导致 trace 各自成顶层、mem0 写入侧从未接进运行路径（G17）。装包让图上主路后，这些接缝集中暴露。本 ADR 决定**完全采用 v2 范式**：图为唯一执行路径，HITL/可观测/记忆都做到位，并允许改动 v1 遗留结构。

> 本轮**不含** LLM-as-judge 评测升级（缺口②，另开 ADR）与桌面多模态（M2.4）。

**Supersedes 记录**：

| 被取代项 | 原始位置 | 取代决策 |
|---|---|---|
| langgraph 未装 → 全 try/except 降级到 v1 | DECISIONS-v2 Decision 2 | D1（图为唯一路径，langgraph 设硬依赖） |
| resume = 聚焦合成、不重放图 | DECISIONS-v2 Decision 8 | D2（真 `interrupt()` + checkpointer 断点恢复） |
| 进程内 `_paused_states` dict 暂存 | `agents/graph/checkpoint.py` | D2（`AsyncSqliteSaver` 持久化 checkpointer） |
| 每次 LLM 调用 = 一个顶层 Langfuse trace | `core/llm.py::_post_chat`（G4） | D3（一次 run 一棵 trace 树） |
| mem0 写入未接线（projector 仅被 rebuild 调用） | G17 | D5（L1 append 后单一 fan-out 接通投影） |
| "L1/L2/L2.5/L3 四层"叙事 | architecture-v2 §13 | D5（Facts / Index / View 三角色，2 存储） |

---

## 核心原则：可序列化数据 vs 活对象（贯穿 D1–D3 的纪律）

LangGraph 一旦挂 checkpointer，每个 super-step 后会把整个 `AgentState` 序列化写盘（`JsonPlusSerializer`）。因此：

> **可序列化的"键"（conversation_id / run_id / 普通数据）进 `AgentState`；活对象（LLM client、Langfuse trace/span、DB 连接）放 state 之外（contextvar 优先、并发/线程池场景退按 run_id 查的进程内注册表），用 state 里的键去找。**

v1 把执行状态藏在 ReAct 循环的局部变量里、活对象待在 `self`，三者不分家，所以没这问题。v2 把状态外化为可持久化数据，就**必须**划这条线。D2（HITL）是把这条线从"可选"变"强制"的那一下；D3（trace 树）复用同一条线。`observability/tracing.py` 已有 contextvar 基建，扩展即可。

---

## D1. 图为唯一执行路径，删除 v1 旁路

**决策**：LangGraph 设为**硬依赖**。删除 `graph_runner` 里的 v1 fallback（`_run_v1` / `build_chat_graph() is None` 分支）、`rhythm_graph.run_rhythm` 的 v1 fallback、以及 routers 中"langgraph 不可用就走 orchestrator"的 try/except 双路。v1 的 `agents/chat_agent.py`、`core/orchestrator.py` 在迁移完成后删除或降为内部实现细节。**仅对外部服务（mem0/Qdrant/Langfuse）保留优雅降级**——它们是会宕机的服务，langgraph 是纯 Python 库、装上即在。

**理由**：双路维护成本高且语义漂移；降级旁路恰恰是让接缝隐形、bug 延迟爆发的元凶；"做完整"的前提是只有一条权威路径。

**被取代项**：DECISIONS-v2 Decision 2、Decision 6（验证回路改回 `uv run --package weatherflow-backend --extra dev`）。

**约束**：SSE 事件契约（v1 §10.2）不变；max-turn、`_strip_think`、source_event_id 硬约束全部保留。外部服务降级阶梯：mem0/Qdrant 宕 → 语义召回返回 `[]`、退回纯 recency；Langfuse 无 key → trace no-op；L1(SQLite) 永远可用。

---

## D2. 真 HITL：SqliteSaver checkpointer + interrupt()，resume 经 L1 回流（路线 A）

**决策**：
1. lifespan 构造 `AsyncSqliteSaver(settings.graph_checkpoints_path)`，`build_chat_graph(checkpointer=saver)`。
2. act 节点遇 write 工具：`val = interrupt({proposal_id, tool, args})` 真挂起，state 由 checkpointer 持久化，key = `thread_id = conversation_id`。
3. `/api/chat/stream` 跑图带 `config={"configurable":{"thread_id": cid}}`；命中 `__interrupt__` 则 emit 到 `proposal_created` 收流。
4. `/api/actions/{id}/execute` 执行 MCP 写工具后 `ainvoke(Command(resume={...}), config)` 从断点续跑（可再调工具→criticize→synthesize）。
5. **回流＝路线 A**：续推理事件写进 L1（reasoning_step / 最终 assistant chat_turn，带 conversation_id），`/execute` 响应直接回带最终回答；前端 append 或用现有 `GET /api/chat/{cid}/history` 重放。
6. 删除进程内 `agents/graph/checkpoint.py`。

**理由**：内存 dict 重启即丢，而 proposal 活 24h，是真实数据丢失风险；`interrupt()`+checkpointer 是 langgraph 的声明式 HITL，避免"重放整图→重复发 proposal"。回流选 A 因其零新流式设施、契合事件溯源、`/history` 现成；逐字流式的体验投资放到 D4 的主聊天主路。

**被取代项**：DECISIONS-v2 Decision 8；`checkpoint.py`。

**约束**：write 必经确认这条不变量不变（只是实现从"事后探测"变成真 interrupt）。`AsyncSqliteSaver` 连接生命周期在 lifespan 管理（WAL，单连接，独立 db 文件 `data/graph_checkpoints.db`，绝不与 L1 `events` 表混库）。

---

## D3. 一次 run 一棵 Langfuse trace 树

**决策**：
1. `graph_runner` 每请求开根 trace，存进 contextvar `_current_trace_var`（在 `ainvoke` **之前**设，借 `asyncio.create_task` 的上下文拷贝语义对所有节点可见）。
2. 每节点开子 span（`load_context`/`recall`/`plan`/`act`/`criticize`/`synthesize`），存进 `_current_span_var`（本节点任务内）。
3. `core/llm.py::_post_chat` 读当前 span → 建 `generation`（而非新顶层 trace），记 model/token/latency。
4. **每请求共享一个 LLM client**（经 contextvar/注册表注入），取代每节点 `build_llm_client()`。

**理由**：可观测的价值是看那棵树（一次请求 → 各节点 span → token/cost 汇总）；N 个顶层 trace 丢了因果与汇总。共享 client 顺带省掉每请求 N 个 httpx 连接。

**被取代项**：G4 的"每次 LLM 调用一个顶层 trace"。

**约束**：trace/span 是活对象，永不进 `AgentState`（见核心原则）。Langfuse 无 key 时整树 no-op。

---

## D4. 真实流式输出（astream_events）

**决策**：`graph_runner` 用 LangGraph `astream_events`（或 `astream` + 自定义事件）**边执行边推 SSE**，取代现在"跑完一次性吐 `sse_events`"。reasoning_step / tool_call_started / observation_summary / final_answer 在节点产生的当下即推给客户端。

**理由**：这是"多 Agent 做完整"的体验维度——推理过程实时可见，而非确认后干等。

**约束**：事件顺序仍守 v1 §10.2；HITL 命中 interrupt 时，流在 `proposal_created` 后干净结束（见 D2-3）。

---

## D5. 记忆 FIV 重设计 + 接通 mem0 写入（修 G17）

**决策**：把"L1/L2/L2.5/L3 四层"重述为 **Facts / Index / View 三角色、两物理存储**：

- **F（Facts）= L1 events**（SQLite, append-only）——唯一可写真理，不动。
- **I（Index）= 派生召回**——一个 `memory/retrieval.py::Retriever` 下的两种检索策略：`recall_recent`（查 L1）+ `recall_semantic`（查 mem0/Qdrant）。取消"L2/L2.5 两个层"的叫法，它们在 bundle 里本是同质 entry。`context_loader` 变薄，只做编排+渲染+预算。
- **V（View）= profile.md**——经 4 门槛 DMW 慢沉淀的人类可读视图。

**单一 post-write fan-out**：L1 `append` 后由一个 `on_event_appended(rec)` 钩子扇出所有派生——`projector.project_event`（→ mem0，**接通 G17**）+ `delayed_writer.maybe_update`（→ profile.md），收编现散落在 checkin/hypotheses/actions/chat 的 4 份 `_run_dmw_safely`。

**mem0 ↔ profile.md 边界（划死，不合并）**：mem0 存"具体实例"（可遗忘/合并的 episodic 语义召回）；profile.md 存"被验证的概括"（4 门槛、保守、可解释）。两者互不写对方。

**理由**：四层是命名虚高（L2 不落盘、L2.5 即 mem0）；唯一真冗余是 L2.5↔L3 都自称"长期记忆"，边界划清即互补；mem0 写入未接通是当前它形同虚设的实质 bug。保留 4 门槛 DMW 而非折进 mem0，是用可解释性换简洁——对"burnout 前拉一把"的教练，过度概括有害。

**被取代项**：architecture-v2 §13 的"四层"叙事；G17。

**约束**：F append-only、唯一真理；I、V 100% 派生，`rebuild_memory.py` 能从 F 同时重建二者；任何召回项带 `source_event_id ∈ F`；mem0 可遗忘（它是缓存）、profile.md 只经 4 门槛变化，二者皆非真理。

---

## 统一不变量（实现期的验收契约）

1. **L1 append-only，唯一真理**；I、V、图 checkpoint 全部派生/可重建。
2. **活对象不进 `AgentState`**；state 只装可序列化键与数据。
3. **write 必经 Proposal 确认**（现为 `interrupt()` + checkpointer）。
4. 每条 evidence / 召回项带 `source_event_id ∈ L1`；critic 运行时校验不放松。
5. **降级阶梯**：外部服务（mem0/Qdrant/Langfuse）宕 → 优雅降级；langgraph 为硬依赖；L1 永远可用。
6. SSE 事件顺序守 v1 §10.2；模型仍统一 `CHAT_MODEL`（不给节点配不同模型，延续 ADR-001 D3）。

---

## 分阶段实现计划（每阶段结束跑验证回路，绿才提交）

| Phase | 内容 | 关键文件 | 依赖 |
|---|---|---|---|
| **P1 基建** | per-request 共享 LLM client + trace/span 的 contextvar/注册表纪律 | `observability/tracing.py`, `core/llm.py` | — |
| **P2 HITL** | SqliteSaver@lifespan、`build_chat_graph(checkpointer)`、act 节点 `interrupt()`、thread_id config、actions `Command(resume)` + 续推理落 L1；删 `checkpoint.py` | `main.py`, `chat_graph.py`, `graph_runner.py`, `routers/actions.py` | P1 |
| **P3 可观测树** | 根 trace + 节点 span + generation 挂树；移除每节点 `build_llm_client` | `graph_runner.py`, `chat_graph.py`, `llm.py` | P1 |
| **P4 流式** | `astream_events` 边跑边推 SSE | `graph_runner.py`, `routers/chat.py` | P2,P3 |
| **P5 记忆 FIV** | `on_event_appended` fan-out（接 projector/G17 + 收编 DMW）、`retrieval.py::Retriever`、`context_loader` 变薄、边界文档 | `event_log.py`, `memory/semantic/*`, `memory/retrieval.py`(新), `context_loader.py` | — |
| **P6 收尾** | 删 v1 旁路（chat_agent/orchestrator 死路径）、langgraph 转硬依赖、更新 architecture-v2 §13/§14 + AGENTS.md、补/改测试 | 多处 | P2–P5 |

**验证回路**（langgraph 已装，回归 uv）：
```
uv run --package weatherflow-backend --extra dev ruff check backend/app backend/tests cli/weatherflow_cli backend/eval
uv run --package weatherflow-backend --extra dev pytest backend/tests -q
(cd frontend && npm run lint && npx tsc --noEmit && npm run build)
```

## 后果与取舍

- **失去**：无 langgraph 的回退能力（D1）；resume 不逐字流式（D2 路线 A）。
- **获得**：单一权威执行路径、可持久化的真 HITL、可汇总的 trace 树、实时流式、mem0 真正生效、更清晰的记忆心智模型。
- **风险**：`AsyncSqliteSaver` 与 SSE/astream 的交互需小心（P2/P4）；contextvar 在 langgraph executor 下的传播边界（P1，备选注册表已规划）。
- **明确不做**：LLM-as-judge（缺口②，另 ADR）、桌面多模态（M2.4）、mem0 graph memory 替 refs。
