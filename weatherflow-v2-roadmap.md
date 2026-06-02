# WeatherFlow v2 — 自主执行任务清单（/goal-ready）

> 本文件是一份**可被 coding agent 通过 `/goal` 模式自主执行**的迭代任务清单。
> 它定义 WeatherFlow 从 v1 到 v2 的演进：**重写产品宪法 → 补齐求职硬通货（多 Agent / mem0 语义记忆 / 可观测 / 评测 / 生产化）→ 桌面宠物卫星 App**。
>
> **执行者须知**：本清单为 **autonomous 规格，含 1 个人工检查点**——完成 Phase 0（重写宪法 + ADR）后 **硬停、结束本次运行**，等人类 review 并重新启动；之后从 Phase 1 一直连续执行到 Phase 2，**期间无需再向人类确认**。先读完「0. 执行协议」「1. v2 架构总览」「附录 D」，再开始。每个里程碑都有明确的验收标准（Acceptance Criteria）。除 Phase 0 检查点外不要中途停下等人——遇到歧义按附录 D 决策并记录，继续推进。

---

## 0. 执行协议（Agent 必读，不可违反）

0. **先切分支**。开始前 `git checkout -b v2`（不要在默认分支上工作）。全程**只 commit、不 push、不合并**——人类会在结束后统一 review 整条 v2 分支。
1. **文档优先（doc-first）**。本项目的最高契约是架构文档 + ADR（见 `AGENTS.md`）。v2 要改根本契约 —— 所以 **Phase 0 的第一件事就是写 v2 架构文档与 ADR-003**，之后所有代码以 v2 文档为准。禁止"代码先跑起来再补文档"。
2. **里程碑串行执行（含 1 个检查点）**。按 `M0.x → M1.x → ...` 顺序执行，每个里程碑独立成一个 commit（message 带里程碑号，如 `M1A.2: chat graph skeleton`）。**唯一的人工检查点在 Phase 0 之后**：完成 M0.1–M0.3 后**结束本次运行**等人 review（见 Phase 0 末尾的检查点块）。**从 Phase 1 起，验收通过即进入下一里程碑，不再停下等人。**
3. **每个里程碑结束必须跑验证回路**（与 CI 一致）：
   ```bash
   # 后端
   uv run --package weatherflow-backend --extra dev ruff check backend/app backend/tests cli/weatherflow_cli
   uv run --package weatherflow-backend --extra dev pytest backend/tests -q
   # 前端（若本里程碑动了前端）
   (cd frontend && npm run lint && npx tsc --noEmit && npm run build)
   ```
   不绿不提交。
4. **每个里程碑必须配套测试**，放进 `backend/tests/{contracts,flows,memory,tools}` 对应子目录；新增 track（agents/observability/eval）时新建对应子目录。
5. **保护 v1 不变量除非 v2 文档显式放开**。L1 永远 append-only；hypothesis 的 evidence 必须带真实 `source_event_id`；write tool 必须走 Proposal 确认。这些 v2 仍然保留。
6. **每完成一个里程碑，回到本文件「附录 A 进度跟踪」把对应项打勾并补一行 changelog。**
7. **遇到歧义/信息不足，不要停下来问人**。按以下顺序自行决断并继续：① 查「附录 D 全局默认决策」有无规定 → ② 没有则选"最不破坏 v1 不变量、最易自验证"的方案 → ③ 把该决策 + 理由追加到 `docs/DECISIONS-v2.md`，继续推进。**唯一允许的硬停止**：验收回路（ruff/pytest/build）连续修复 3 次仍无法转绿，此时把失败现场写进 `docs/BLOCKERS-v2.md`、跳过该里程碑（在附录 A 标记 ⚠️BLOCKED）、继续后续不依赖它的里程碑。绝不为了"跑通"而删测试或放松 v1 硬约束。

---

## 1. v2 架构总览（与 v1 的关键差异）

### 1.1 记忆拓扑升级（最重要）

v1 的记忆是三层（L1 事件 / L2 工作上下文 / L3 profile.md）。v2 **新增一层语义记忆 L2.5**，但严格保持"L1 是唯一真理、其余皆派生"的不变量：

```
L1  Event Log (SQLite, append-only)            ← 唯一真理，永不修改
      │
      ├─► L2   Working Context (EvidenceBundle)  ← 每请求装配，基于"最近性"（v1 §6 已有）
      │
      ├─► L2.5 Semantic Memory (mem0 + Qdrant)   ← 【v2 新增】基于"语义相关性"的召回层
      │          · 是 L1 高价值事件的派生投影
      │          · 可由 scripts/rebuild_memory.py 从 L1 完整重建
      │          · 绝不是新的真理来源
      │
      └─► L3   Profile.md (6 固定章节, 人类可读)  ← DelayedMemoryWriter 四道门槛（v1 §9 已有）
```

> **设计立场（写进 ADR-003）**：mem0 解决 v1 的硬伤 —— ContextLoader 只按"最近 N 条"装配 evidence，召回不了"三周前那次相似的 Overload"。L2.5 用语义检索补这个洞。但它是 **projection**，不是 source of truth：删掉整个 Qdrant，`rebuild_memory.py` 能从 L1 一键重建。这条不变量是这个项目区别于"随便接个向量库"的核心，必须在文档和代码里都立住。

### 1.2 Agent 拓扑升级

| | v1 | v2 |
|---|---|---|
| 编排 | `core/orchestrator.py` 一个函数 + 单 ReAct `chat_agent`（max 8 turns） | **LangGraph 状态图**：planner → memory → worker → critic → synthesize |
| Agent 数 | 1 RhythmAgent + 1 ChatAgent | 多节点协作 + 显式 state + checkpointer |
| Proposal | Dispatcher 拦截 | LangGraph **interrupt（human-in-the-loop）** + checkpointer 恢复 |
| 可观测 | JSON 日志 | **Langfuse trace + OpenTelemetry 全链路 + 指标** |
| 质量 | 靠 contracts 测试 | **eval 集 + LLM-as-judge + 轨迹评测** |

### 1.3 宪法松绑（Phase 0 正式重写）

- 第四条（集成红线 Calendar+GitHub）→ v2 改为**可插拔集成层**，但仍是 curated 小集合。
- 第六条 + anti-pattern（禁向量库 / L3 只能是 markdown）→ v2 放开：**允许向量库作为 L1 的派生召回层**；profile.md 仍是人类可读 L3。
- 第七条（节制的主动）→ v2 改为**"克制提示"（calibrated proactivity，已锁定，不要自行加码）**：桌面宠物**可**在新 hypothesis 出现时做轻微动效提示；**不可**弹系统通知、不可抢焦点、不可弹窗打断。提示强度必须可在设置里关闭。
- anti-pattern "ONE rhythm agent + ONE chat agent" → v2 放开多 Agent。

---

## Phase 0 · v2 地基：重写宪法 + ADR（必须最先做）

**目标**：把 v2 的产品立场与架构边界写成文档，作为后续所有代码的依据。**这一阶段不写业务代码。**

### M0.1 — 撰写 `weatherflow-architecture-v2.md`
- 以 v1 文档为基底，新建 v2 文档（不覆盖 v1，v1 存档）。
- 重写「产品宪法」九条中受影响的第四 / 六 / 七条（见 §1.3），其余保留。
- 新增章节：**§13 语义记忆层（L2.5 / mem0）** —— 写清拓扑、"派生投影"不变量、写入触发、重建机制。
- 新增章节：**§14 多 Agent 编排** —— LangGraph 状态图、节点职责、与 SSE 事件协议（v1 §10）的映射。
- 更新「决策变更记录」，追加 v2 条目。
- **AC**：v2 文档存在；九条宪法逐条标注"保留 / v2 修改"；§13/§14 含拓扑图与不变量声明。

### M0.2 — 撰写 `docs/ADR-003-v2-pivot.md`
- 逐条记录 v2 决策：为何引入 mem0、为何 mem0 是派生层、为何上 LangGraph、为何松绑主动性。
- 显式标注它 supersede 了 ADR-001 / AGENTS.md anti-patterns 中的哪几条（如"❌ 任何向量库""ONE agent"）。
- **AC**：ADR-003 存在，含 ≥6 条带"决策 / 理由 / 被取代项"的记录。

### M0.3 — 更新 `AGENTS.md`
- 指向 v2 文档为新的 single source of truth；更新 anti-patterns 段（移除已被 v2 取代的禁令，但保留 L1 append-only 等仍有效的）。
- **AC**：`AGENTS.md` 顶部链接指向 v2 文档；mem0/多 Agent 不再被列为 anti-pattern。

> ### 🛑 检查点 CP-0：在此结束本次运行
> 完成 M0.1–M0.3 后：
> 1. 输出 `docs/PHASE0-REVIEW.md`：用 ≤1 页摘要"v2 宪法改了哪几条、ADR-003 的核心立场、与 v1 的不变量差异"。
> 2. commit 当前进度（仍在 `v2` 分支，不 push）。
> 3. **结束本次运行**，明确告知人类"Phase 0 完成，等待 review 后重新启动以执行 Phase 1 起"。
> 4. 人类重新启动你时，跳过 Phase 0，从 M1A.1 开始连续执行到 Phase 2，中途不再停。

---

## Phase 1 · 求职硬通货（核心，按 1A→1E 顺序）

### Track 1A · 多 Agent 编排（LangGraph）—— v2 骨架

**目标**：把单 ReAct loop 升级为带 planner / worker / critic 的 LangGraph 状态图，保留全部 v1 SSE 事件契约。

#### M1A.1 — 引入依赖与 AgentState
- `backend/pyproject.toml` 加 `langgraph`、`langgraph-checkpoint-sqlite`。
- 新建 `backend/app/agents/graph/state.py`：定义 `AgentState`（TypedDict：messages、bundle、hypothesis、plan、observations、proposals、critic_verdict、conversation_id、user_id…）。
- **AC**：依赖装上；`AgentState` 有类型；`ruff` 绿。

#### M1A.2 — 搭图骨架
- 新建 `backend/app/agents/graph/chat_graph.py`：节点 `load_context → recall_memory → plan → act → criticize → synthesize`，act↔plan 间条件边（可多轮工具调用），criticize 不通过可回退 act。
- checkpointer 用 SQLite（复用项目现有 SQLite，单独 db 文件或同库另表）。
- **AC**：图能编译；用假 LLM/工具跑通一条 happy path（单测）。

#### M1A.3 — 迁移 ReAct 逻辑进 worker 节点
- 把 `agents/chat_agent.py` 的 function-calling/工具循环迁进 `act` 节点；保留 `_strip_think`、max-turn 上限。
- **保留 SSE 事件**：`context_loaded / hypothesis_generated / reasoning_step / tool_call_started / tool_call_finished / observation_summary / proposal_created / final_answer`，从图节点里 emit（用 LangGraph stream/astream_events 适配到 `sse-starlette`）。
- **AC**：`/api/chat/stream` 行为与 v1 等价（事件顺序约束 v1 §10.2 不破）；flows 测试通过。

#### M1A.4 — Critic 节点（自检 groundedness）
- `criticize` 节点：校验答案/hypothesis 的每条 evidence 是否真挂在 bundle 内真实 `source_event_id`（v1 硬约束的"运行时自检"版）；不达标触发一次 re-plan。
- **AC**：构造一个"编造 source"的 LLM 输出，critic 能拦截并触发重试（单测）。

#### M1A.5 — Proposal 改造为 human-in-the-loop interrupt
- write tool → LangGraph `interrupt`，state 由 checkpointer 持久化；`POST /api/actions/{id}/execute` 后从断点 `resume` 继续图。
- **AC**：发起 proposal → 流暂停 → 确认后图恢复并写 `executed_action`；tools 测试通过；v1 不变量（write 必经确认）保持。

#### M1A.6 — RhythmAgent 子图
- 把 T1/T2 的 hypothesis 生成包成小子图 `recall → hypothesize → verify_sources → persist`，与 chat 图共享 memory 召回节点。
- **AC**：check-in 同步接口与 T2 定时检查行为不变；contracts 测试通过。

---

### Track 1B · mem0 语义记忆（L2.5）

**目标**：新增可重建的语义召回层，喂给 ContextLoader 与 memory 节点；严守"派生投影"不变量。

#### M1B.1 — 依赖与配置
- 加 `mem0ai`、`qdrant-client`；`docker-compose.yml` 加 Qdrant 服务；`.env.example` 加 `QDRANT_URL`、`MEM0_*`、`EMBEDDING_*`。
- 新建 `backend/app/memory/semantic/` 包。
- **AC**：`docker compose up -d qdrant` 起得来；配置项进 `config.py`。

#### M1B.2 — MemoryProjector（L1 → mem0）
- `semantic/projector.py`：订阅 L1 append（或在 orchestrator 写完高价值事件后调用），把白名单事件（`checkin` / `confirmed hypothesis` / `executed_action` / 含明确偏好的 `chat_turn`）抽取为 mem0 memory，**带回指 `source_event_id`**。
- 不抽取低价值事件（reasoning_step、tool_call、snapshot 原始数据）。
- **AC**：一条 confirmed hypothesis 落库后，mem0 里出现可被语义检索到的记忆，且能回链到原 event。

#### M1B.3 — ContextLoader v2：融合最近性 + 语义召回
- `context_loader.py` 在 v1 的"最近 N 条"基础上，新增"与 trigger 语义最相关的 K 条历史记忆"（来自 mem0），合并去重，仍受 §6.3 token 上限约束。
- 每条语义召回的 evidence 同样带 `source_event_id`（来自 M1B.2 的回链），可被 hypothesis 引用、可在 UI 溯源。
- **AC**：构造"三周前相似 Overload"场景，bundle 能召回它；token 上限不破；溯源 id 真实。

#### M1B.4 — memory 节点接入图
- Track 1A 的 `recall_memory` 节点查询 mem0，结果进 state，供 plan/synthesize 使用。
- **AC**：chat 流里能观测到"调用了语义记忆并用上了"（trace 里有 span）。

#### M1B.5 — `scripts/rebuild_memory.py`（证明不变量）
- 清空 Qdrant → 遍历 L1 全部事件 → 重新投影 → 重建 mem0。幂等。
- **AC**：删库重建后，M1B.3 的召回场景结果一致；脚本可重复运行无重复写入。

#### M1B.6 — 测试
- `tests/memory/`：投影白名单、回链真实性、重建幂等、user 隔离。
- **AC**：全绿。

---

### Track 1C · 可观测（Langfuse + OpenTelemetry）

**目标**：每次 agent run 可在 trace 里看全貌；全链路一个 traceId；关键业务指标可见。

#### M1C.1 — Langfuse 接入
- `docker-compose.yml` 自托管 Langfuse（或配云端 key）；`core/llm.py` 所有 LLM 调用 + LangGraph 节点用 Langfuse 包裹。
- 一次 agent run = 一个 trace；节点 = span；工具调用 = span；记录 token / cost / 模型名。
- **AC**：跑一次 chat，Langfuse 里能看到完整 trace 树含 token 数。

#### M1C.2 — OpenTelemetry 全链路 traceId
- HTTP 入口生成 traceId（contextvars 透传，跨 async / 跨 APScheduler 任务 / 跨 MCP 调用）；导出到 console 或 Jaeger。
- **AC**：一次请求 grep traceId 能串起 router → orchestrator → graph 节点 → tool → llm。

#### M1C.3 — 结构化日志 + 指标
- JSON 日志带 `trace_id / conversation_id / user_id`；暴露指标：token 用量、各阶段延迟 P50/P95、hypothesis confidence 分布、记忆召回命中率、proposal 确认率。
- **AC**：指标端点/仪表可读到上述指标。

---

### Track 1D · 评测（Eval）

**目标**：让"agent 好不好"可量化、可回归。

#### M1D.1 — 评测集
- `backend/eval/datasets/`：①check-in→期望 label 区间 ②hypothesis faithfulness（每条 evidence 的 source 必须真实且相关）③记忆召回相关性 ④多轮 chat groundedness。
- **AC**：≥30 条标注样本，结构化存放。

#### M1D.2 — LLM-as-judge + 指标
- `backend/eval/judges.py`：hypothesis 质量、答案 groundedness 打分；检索类指标（Recall@K / MRR）评 mem0 召回。
- **AC**：能对一批样本产出分数。

#### M1D.3 — 轨迹评测（multi-agent）
- 评 planner 选工具是否合理、critic 是否抓到了注入的错误、是否过度调用工具。
- **AC**：构造"该被 critic 拦截"的样本，轨迹评测能标记出来。

#### M1D.4 — 回归 harness + 报告
- `backend/eval/run_eval.py` 一键跑全集，输出 markdown/JSON 记分卡（含 P50/P95、faithfulness、召回指标）；可选接 CI。
- **AC**：一条命令产出一份带数字的报告。

---

### Track 1E · 生产化

**目标**：整套能一键起、能讲部署故事。

#### M1E.1 — 全栈 docker-compose
- backend + Qdrant + Langfuse + frontend + MCP servers + （可选）Jaeger 一键起；健康检查；依赖顺序。
- **AC**：`docker compose up` 后 `curl /health` 与 `/api/meta/status` 全绿。

#### M1E.2 — 降级与配置硬化
- LLM / Qdrant / mem0 / provider 不可用时确定性降级（延续 v1 fallback 风格，绝不在证据不足时过度推断）；secrets 走 env；`.env.example` 补全。
- **AC**：杀掉 Qdrant，chat 仍能用"最近性 bundle"降级回答（不崩）。

#### M1E.3 — README v2 + 架构图 + 面试素材
- 更新 README：v2 解决了什么、记忆拓扑图、多 Agent 图、性能/评测数字。
- `docs/interview-notes.md`：把 mem0 派生投影不变量、LangGraph human-in-the-loop、可观测、评测整理成 Q&A。
- **AC**：README 有架构图与真实数字；面试 Q&A ≥15 条。

---

## Phase 2 · 前沿 capstone：桌面宠物卫星 App

**定位**：独立桌面端 App，复用 WF v2 后端（HTTP + SSE）当大脑。WF 主干基本不动。体现 v2 宪法的"克制的主动"。

> 注：用户未把桌面客户端列为主要技术栈学习目标，故本阶段**重交付、轻深挖**：能跑、能讲、能演示即可，不要陷进 Rust/原生细节。
> **技术选型已定（不要再问）：Electron + TypeScript。** 理由：复用项目现有 Next.js/TS 技术栈、生态成熟、对自主 agent 最可靠（不引入 Rust 工具链这一额外失败面）。如人类将来想换 Tauri，改 `desktop/` 脚手架即可，但本次执行一律用 Electron。

#### M2.1 — 脚手架（Electron，已定型，不询问）
- 搭 `desktop/` 子项目（Electron + TypeScript），能起一个透明、无边框、always-on-top 的小窗 + 系统托盘。
- **AC**：`npm run dev`（在 `desktop/` 下）后桌面出现一个可拖动的小窗 + 托盘图标。

#### M2.2 — 角色与状态映射
- 一个小角色（Rive/Lottie/精灵图），表情/动作映射 6 种 rhythm label（Flow/Recovery/Steady/Overload/Blocked/Fragmented）。
- 通过 SSE/poll 订阅 WF 当前 hypothesis，状态变化驱动表情。
- **AC**：后端 hypothesis 变 Overload，桌面角色切到"过载"表情。

#### M2.3 — 点击即聊 + 克制的主动
- 点角色弹出轻量 chat（复用 `/api/chat/stream`）；新 hypothesis 时角色做一个**克制**的提示动作（轻微动效，**不弹系统通知、不抢焦点**）。
- **AC**：能在桌面直接对话；主动提示符合"克制"边界（可配置开关）。

#### M2.4（条件 stretch）— 屏幕/语音多模态
- 截图理解当前在干什么 / 语音输入。
- **自评条件（满足才做，不询问人）**：M0–M2.3 全部里程碑均为 ✅（无 ⚠️BLOCKED）。不满足则**跳过**，在附录 A 标记 `SKIPPED（前置未全绿）`、附录 B 记一行，正常结束本次执行。

---

## 附录 A · 进度跟踪（每完成一项，Agent 在此打勾 + 追加 changelog）

```
[x] M0.1  v2 架构文档
[x] M0.2  ADR-003
[x] M0.3  AGENTS.md 更新
[x] M1A.1 LangGraph 依赖 + AgentState
[x] M1A.2 图骨架
[x] M1A.3 ReAct 迁移 + SSE 保持
[x] M1A.4 Critic 节点
[x] M1A.5 Proposal human-in-the-loop
[x] M1A.6 RhythmAgent 子图
[x] M1B.1 mem0/Qdrant 依赖配置
[x] M1B.2 MemoryProjector
[x] M1B.3 ContextLoader v2 融合召回
[x] M1B.4 memory 节点接入
[x] M1B.5 rebuild_memory.py
[x] M1B.6 记忆测试
[x] M1C.1 Langfuse
[x] M1C.2 OpenTelemetry traceId
[x] M1C.3 结构化日志 + 指标
[x] M1D.1 评测集
[x] M1D.2 LLM-as-judge
[x] M1D.3 轨迹评测
[x] M1D.4 回归 harness + 报告
[x] M1E.1 全栈 docker-compose
[x] M1E.2 降级 + 配置硬化
[x] M1E.3 README v2 + 面试素材
[x] M2.1  桌面脚手架
[x] M2.2  角色状态映射
[x] M2.3  点击即聊 + 克制主动
[SKIPPED] M2.4  (可选) 多模态 — 条件满足但依赖外部视觉/语音服务，环境不可用
```

## 附录 B · changelog

| 日期 | 里程碑 | 变更摘要 |
|---|---|---|
| 2026-06-01 | — | v2 roadmap 初版建立 |
| 2026-06-01 | M0.1 | 新建 weatherflow-architecture-v2.md（宪法第四/六/七条重写，§13 L2.5，§14 多 Agent） |
| 2026-06-01 | M0.2 | 新建 docs/ADR-003-v2-pivot.md（10 条决策，supersedes v1 中的向量库禁令/单 Agent 限制/禁止主动） |
| 2026-06-01 | M0.3 | 更新 AGENTS.md（指向 v2 为 single source of truth，移除 mem0/多 Agent anti-pattern） |
| 2026-06-02 | M1A.1 | 加 langgraph/checkpoint-sqlite/mem0/OTel 依赖；AgentState TypedDict |
| 2026-06-02 | M1A.2+M1A.4 | chat_graph.py（6 节点状态图 + 条件边 + critic groundedness 自检） |
| 2026-06-02 | M1A.3 | graph_runner.py 适配器：图执行 → SSE 事件流，保留 v1 fallback |
| 2026-06-02 | M1A.5 | Proposal interrupt：checkpoint.py 状态暂存 + resume_chat() 恢复 |
| 2026-06-02 | M1A.6 | rhythm_graph.py 子图：recall → hypothesize → verify → persist |
| 2026-06-02 | M1B.1 | semantic/ 包 + config.py Qdrant/mem0/embedding 设置 + docker-compose Qdrant/Langfuse |
| 2026-06-02 | M1B.2-M1B.6 | projector.py（白名单投影）+ recall.py（语义检索）+ context_loader v2 + rebuild_memory.py + 12 测试 |
| 2026-06-02 | M1C.1-M1C.3 | observability/：Langfuse trace/span + OTel contextvars + 结构化 JSON 日志 + MetricsCollector |
| 2026-06-02 | M1D.1-M1D.4 | eval/：30 条标注样本 + judges.py（faithfulness/recall/groundedness）+ run_eval.py 回归 harness |
| 2026-06-02 | M1E.2-M1E.3 | 健康状态 v2 检查 + OTel 初始化 + docs/interview-notes.md（18 条 Q&A） |
| 2026-06-02 | M2.1-M2.3 | desktop/：Electron 透明窗 + 6 种 mood emoji/动画 + SSE 聊天 + 克制提示 |
| 2026-06-02 | M2.4 | SKIPPED — 条件满足但依赖外部视觉/语音服务 |
| 2026-06-02 | G1/G2/G14 | 续接：checkin + scheduled_check 接入 rhythm 子图（run_rhythm，含 v1 fallback）；清理 hypothesize_node 死代码 |
| 2026-06-02 | G3 | 续接：actions execute 后 resume 暂停的 chat 图（M1A.5 真正接通），续推理落 L1 |
| 2026-06-02 | G4/G15 | 续接：llm.py 用 Langfuse 包裹 LLM 调用并记录 token/延迟；新增 chat_raw，act_node 复用 LLMClient |
| 2026-06-02 | G5/G6/G7 | 续接：TraceContextMiddleware（traceId）+ 结构化日志启用 + /api/meta/metrics |
| 2026-06-02 | G8/G9 | 续接：README 重写为 v2（拓扑图/多 Agent 图/评测数字/docker-compose）+ 桌面托盘图标 |
| 2026-06-02 | G16 | 续接：mem0 config 抽成 build_mem0_config（urllib.parse），projector/recall 复用 |
| 2026-06-02 | G10-G13 | 续接：graph_runner fallback / resume / SSE 事件顺序 / 可观测 wiring 测试（73→86） |
| 2026-06-02 | ADR-004 | 决定完全采用 v2 范式（图唯一路径 / 真 HITL / trace 树 / astream / FIV 记忆） |
| 2026-06-02 | ADR-004 P1-P3 | per-request 共享 LLM client + trace/span contextvar；真 SqliteSaver checkpointer + interrupt()；一次 run 一棵 Langfuse trace 树 |
| 2026-06-02 | ADR-004 P4 | graph.astream 真流式：边跑边推 SSE（取代跑完一次性吐） |
| 2026-06-02 | ADR-004 P5 | FIV 记忆：derivations 单一 fan-out 接通 mem0 写入（修 G17）+ 收编 DMW；retrieval.py 两策略 |
| 2026-06-02 | ADR-004 P6 | 删 v1 chat_agent 旁路；更新 AGENTS.md / 架构 §13/§14（FIV + 真 HITL）；93 测试绿 |

---

## 附录 C · 求职映射（每个 track 对应的简历/面试卖点）

| Track | 简历能写的一句话 | 面试高频考点 |
|---|---|---|
| 1A 多 Agent | 用 LangGraph 把单 ReAct 升级为 planner/worker/critic 状态图，proposal 做成 human-in-the-loop interrupt + checkpointer 断点恢复 | 多 Agent 编排、状态持久化、HITL、为什么不用裸 ReAct |
| 1B mem0 | 在事件溯源架构上加语义记忆层，作为 L1 的可重建派生投影，不破坏 append-only 不变量 | 向量检索、记忆系统设计、为什么 mem0 是 projection 而非 source of truth |
| 1C 可观测 | Langfuse trace + OpenTelemetry 全链路 traceId，token/延迟/召回命中率可量化 | LLM 应用可观测性、分布式追踪、成本控制 |
| 1D 评测 | 自建 agent 评测集 + LLM-as-judge + 轨迹评测 + 回归 harness | RAG/Agent 评测方法论、faithfulness、如何防回归 |
| 1E 生产化 | 全栈 docker-compose 一键起 + 确定性降级 | 部署、降级、配置管理 |
| 2 桌面宠物 | 复用 agent 后端的桌面端 ambient companion，体现"克制的主动" | 产品差异化、客户端 + agent 集成 |

---

## 附录 D · 全局默认决策（autonomous 执行遇到歧义时按此处理，不要问人）

### D.0 人类已拍板的决策（2026-06-01，最高优先级，不要改）

| 议题 | 人类决定 | 影响 |
|---|---|---|
| 执行范围/检查点 | **Phase 0 后硬停一次**，review 通过后连续跑完 Phase 1→2 | 见执行协议第 2 条 + CP-0 检查点块 |
| 桌面端框架 | **Electron + TypeScript** | Phase 2 / M2.1 |
| 主动性边界 | **克制提示**（可轻微动效，禁系统通知/禁抢焦点/可关闭） | M0.1 宪法重写 + M2.3 |
| AI 依赖 | **务实云 API**：MiniMax（agent）+ 阿里 text-embedding-v4 + Langfuse 自托管 | 全 Phase 1 |
| 集成红线 | **本次只把 Calendar/GitHub 重构成可插拔 provider 层（SPI/registry），不新增第三方集成** | M0.1 宪法第四条 + 不做新 provider |

### D.1 技术默认

| 议题 | 已定默认 | 备注 |
|---|---|---|
| 桌面端框架 | **Electron + TypeScript** | 见 Phase 2 注 |
| Embedding 供应商 | 复用 PaperRAG 的 **阿里 `text-embedding-v4`**，env 可切（`EMBEDDING_PROVIDER` / `EMBEDDING_MODEL` / `EMBEDDING_API_KEY`） | 保持两项目一致，降低心智负担 |
| 向量库 | **Qdrant**（复用 PaperRAG 经验，docker 起） | 不要引入第二个向量库 |
| LangGraph checkpointer | **SQLite**（`langgraph-checkpoint-sqlite`），单独 db 文件 `data/graph_checkpoints.db` | 不要和 L1 的 `events` 表混存 |
| Langfuse | **docker-compose 自托管**（与 M1E.1 一致）；env 缺失时降级为"只打结构化日志、不报错" | 不要因为缺 key 就崩 |
| LLM 模型 | 沿用现有 `CHAT_MODEL` env，不为不同节点配不同模型 | 延续 ADR-001 D3 |
| 包管理 | 后端 `uv`、前端/desktop `npm` | 与现有一致 |
| 测试框架 | `pytest`（后端）；desktop 端最小化测试即可 | 与现有一致 |
| 新增 Python 包归属 | agents 图 → `app/agents/graph/`；语义记忆 → `app/memory/semantic/`；评测 → `backend/eval/` | 与清单里的路径一致 |
| 何时更新 v1 不变量测试 | 仅当 v2 文档显式放开某约束时，才改对应 contracts 测试，并在 commit message 注明 supersede 了哪条 | 否则一律保持 v1 测试绿 |
| 信息确实不足又无默认 | 选"最不破坏 v1 不变量 + 最易自验证"方案，记入 `docs/DECISIONS-v2.md` 继续 | 见执行协议第 7 条 |

> 附录 A 的状态标记约定：`[ ]` 未做 · `[x]` 完成且验收绿 · `⚠️BLOCKED` 验证连续 3 次修不绿已跳过（详见 `docs/BLOCKERS-v2.md`）· `SKIPPED` 条件未满足主动跳过。
