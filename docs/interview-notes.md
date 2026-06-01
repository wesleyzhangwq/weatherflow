# WeatherFlow v2 — 面试 Q&A 素材

> 基于 weatherflow-architecture-v2.md + ADR-003，整理高频面试问题与回答。
> 共 18 条 Q&A，覆盖记忆系统、多 Agent 编排、可观测、评测、生产化。

---

## 记忆系统（mem0 / L2.5）

### Q1: 你的记忆系统有几层？各自的作用？

**A**: 四层。L1 是 SQLite append-only 事件日志——唯一真理来源。L2 是每次请求临时装配的 EvidenceBundle（不落盘）。L2.5 是 v2 新增的语义召回层，用 mem0 + Qdrant 存储 L1 高价值事件的向量投影。L3 是人类可读可改的 profile.md（6 个固定章节），通过 DelayedMemoryWriter 四道门槛写入。

### Q2: 为什么 mem0 是"派生投影"而不是新的真理来源？

**A**: 因为删掉整个 Qdrant，我们的 `rebuild_memory.py` 脚本能从 L1 一键重建。每条 mem0 记忆都携带 `source_event_id` 回链到 L1 真实事件。这条不变量保证了系统的可追溯性和可重建性——区别于"随便接个向量库"。

### Q3: L2.5 解决了什么 v1 的硬伤？

**A**: v1 的 ContextLoader 只按"最近 N 条"装配 evidence，召回不了"三周前那次相似的 Overload"。语义检索用当前 trigger 的语义去匹配历史记忆，补了这个盲区。

### Q4: 哪些事件会被投影到 L2.5？

**A**: 只有白名单事件：check-in、confirmed hypothesis、executed_action、含明确偏好的 chat_turn。低价值事件如 reasoning_step、tool_call、原始 snapshot 不投影。

---

## 多 Agent 编排（LangGraph）

### Q5: 为什么要从单 ReAct 升级到 LangGraph？

**A**: 三个原因：(1) 单循环无法做 self-check，critic 节点在图中天然存在；(2) LangGraph 的 interrupt 机制天然支持 Proposal 的 human-in-the-loop；(3) checkpointer 让断点恢复声明化。

### Q6: 你的图有哪些节点？各自负责什么？

**A**: 六个节点——load_context（装配 bundle 含 L2.5）、recall_memory（语义检索）、plan（planner 决策）、act（worker 执行工具）、criticize（groundedness 自检）、synthesize（最终回答）。act 和 plan 之间有条件边可多轮调用，criticize 不通过可回退 plan。

### Q7: Proposal 是怎么做成 human-in-the-loop 的？

**A**: write tool 调用时，act 节点创建 proposal 并暂停图执行（LangGraph interrupt）。State 通过 checkpointer 持久化到独立 SQLite 文件。用户确认后，从断点 resume 继续图。v1 不变量保持：write 必经确认。

### Q8: Critic 节点做什么？怎么防 LLM 幻觉？

**A**: Critic 校验 hypothesis 的每条 evidence 的 source_event_id 是否在 bundle 中真实存在。不达标 → verdict=retry，回退 plan 节点重试一次。这是 v1 校验逻辑的"运行时自检版本"——在 Agent 内部就拦截，而非等到写入 L1 前。

---

## 可观测性

### Q9: 你怎么追踪一次 agent run 的全貌？

**A**: Langfuse trace 树：一次 agent run = 一个 trace，每个 graph 节点 = span，工具调用 = span，记录 token/cost/模型名。OpenTelemetry 提供跨层 traceId 透传（HTTP → orchestrator → graph → tool → LLM），一个 grep 就能串起全链路。

### Q10: Langfuse 不可用时怎么办？

**A**: 降级为结构化 JSON 日志 + console OTel exporter。不报错、不阻塞核心功能。这是 env 缺失时的确定性降级策略。

---

## 评测（Eval）

### Q11: 你怎么衡量 Agent 的质量？

**A**: 自建评测集（≥30 条标注样本）覆盖四个维度：check-in→label 区间、hypothesis faithfulness（每条 evidence 的 source 必须真实）、记忆召回相关性（Recall@1/MRR）、多轮 chat groundedness。LLM-as-judge 自动评分，回归 harness 一键跑全集输出记分卡。

### Q12: 什么是轨迹评测？

**A**: 评 planner 选工具是否合理（该用 calendar 不该用 github.create_issue）、critic 是否抓到了注入的错误（fabricated source_event_id）、是否过度调用工具。这是多 Agent 架构特有的评测维度。

---

## 产品宪法与设计决策

### Q13: 你提到"克制的主动"——具体怎么克制？

**A**: 桌面宠物可在新 hypothesis 出现时做轻微动效（角色微动、状态切换动画）。红线：不可弹系统通知、不可抢焦点、不可弹窗打断。必须可在设置里一键关闭（`proactivity.enabled`）。这是为了产品差异化，但严格限制在"不打断"范围内。

### Q14: 为什么把 Calendar+GitHub 从硬编码改成 Provider SPI？

**A**: 架构灵活性。每个 provider 自注册工具、自声明健康检查，降低集成新 provider 的边际成本。但产品立场不变：每新增一个 provider 必须有产品理由。SPI 是给未来的选择权，不是开放平台邀请。

### Q15: L1 append-only 在 v2 有没有被放松？

**A**: 没有。L1 永远 append-only，永不修改永不删除。v2 新增的 L2.5 是 L1 的派生层，L3 profile.md 仍然只通过 DelayedMemoryWriter 写入。这是整个项目的根基不变量。

---

## 生产化

### Q16: 你的部署方案是什么？

**A**: 全栈 docker-compose 一键起：backend + Qdrant + Langfuse（含 PostgreSQL）+ frontend + MCP servers。健康检查、依赖顺序。`docker compose up` 后 `/health` 和 `/api/meta/status` 全绿。

### Q17: Qdrant 挂了系统还能用吗？

**A**: 能。所有 mem0/语义检索调用都有 try/except 降级——回退到纯"最近性"模式（v1 行为）。不会崩溃、不会丢数据。L1 不受影响。

### Q18: 你怎么处理 reasoning model 的 <think> 标签？

**A**: `core/llm.py::chat_json` 做 JSON 模式调用时自动 strip。`chat_agent.py::_strip_think` 做 function-calling 响应的 strip。v2 的 graph act 节点同样调用 `_strip_think`。如果不 strip，<think> 块会被写入 L1（append-only，无法修改），永久污染数据。
