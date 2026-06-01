# ADR-003: WeatherFlow v2 Pivot 关键决策记录

**日期**：2026-06-01
**状态**：Accepted
**上下文**：WF 从 v1 演进到 v2，引入语义记忆（mem0）、多 Agent 编排（LangGraph）、可观测（Langfuse + OTel）、评测体系，并重写产品宪法中受影响条款。本文档记录 v2 每一项核心决策。

**Supersedes 记录**：本 ADR 显式取代了以下 v1 文档/规则中的若干条目：

| 被取代项 | 原始位置 | 取代决策 |
|---|---|---|
| ❌ 禁止任何向量库 | AGENTS.md anti-patterns、v1 §1 宪法第六条隐含 | D1（允许向量库作为 L1 派生召回层） |
| ❌ ONE rhythm agent + ONE chat agent | AGENTS.md anti-patterns | D3（多 Agent LangGraph 编排） |
| ❌ 绝不打扰用户 / 不主动 push | v1 §1 宪法第七条 | D4（克制提示） |
| ❌ 硬红线：只集成 Calendar + GitHub | v1 §1 宪法第四条 | D5（可插拔集成层） |

---

## D1. 引入 mem0 + Qdrant 作为 L2.5 语义记忆层

**决策**：新增 L2.5 语义记忆层，使用 mem0 + Qdrant 存储 L1 高价值事件的语义投影，供 ContextLoader 做语义召回。

**理由**：
- v1 的 ContextLoader 只按「最近 N 条」装配 evidence（§6.1），召回不了「三周前那次相似的 Overload」。这是 v1 记忆系统的硬伤。
- 语义检索能根据当前 trigger 的语义找到历史上最相关的证据，补充「最近性」召回的盲区。
- mem0 提供了 memory 的生命周期管理（add/search/delete），比裸 Qdrant API 更适合 agent memory 场景。
- 阿里 text-embedding-v4 作为 embedding 模型，与 PaperRAG 项目保持一致，降低心智负担。

**被取代项**：AGENTS.md anti-patterns 中的「❌ Qdrant or any vector DB」；v1 宪法第六条隐含的「L3 只能是 markdown」限制。

**约束**：L2.5 是 L1 的**派生投影**，不是新的真理来源。删掉 Qdrant 能从 L1 一键重建（`rebuild_memory.py`）。

---

## D2. mem0 是派生投影而非新的真理来源

**决策**：mem0 中的每条记忆必须携带 `source_event_id` 回链到 L1 真实事件。mem0 可随时清空并从 L1 重建。

**理由**：
- 「L1 是唯一真理、其余皆派生」是 WF 的核心不变量。引入向量库不能破坏这条。
- 如果 mem0 成为独立的真理来源，系统就无法从 L1 单点重建，可追溯性断裂。
- `source_event_id` 回链确保证据溯源链完整：UI 点击 ⓘ → mem0 memory → L1 event → 原始数据。
- `rebuild_memory.py` 幂等可重跑，是这条不变量的可验证证明。

**被取代项**：AGENTS.md anti-patterns 中「❌ Qdrant or any vector DB. L3 is one editable Markdown file」——改为「允许向量库作为 L1 的派生召回层」。L3 profile.md 仍是人类可读可改的 Markdown 文件。

---

## D3. 引入 LangGraph 多 Agent 编排

**决策**：将 v1 的单 ReAct 循环（`chat_agent.py`，max 8 turns）升级为 LangGraph 状态图，节点包括 load_context → recall_memory → plan → act → criticize → synthesize。

**理由**：
- v1 的单 Agent 无法做 self-check（criticize 节点在图中天然存在，单循环里嵌自检逻辑很丑）。
- LangGraph 的 interrupt 机制天然支持 Proposal 的 human-in-the-loop 模式，比 v1 的 Dispatcher 拦截更优雅。
- checkpointer 让 Proposal 确认后的断点恢复变得声明式。
- LangGraph 的 astream_events 适配 SSE 事件流，可以精确映射 v1 的 SSE 事件契约。
- 多节点结构让 Langfuse trace 树天然有粒度（每个节点 = span）。

**被取代项**：AGENTS.md anti-patterns 中「❌ ONE rhythm agent + ONE chat agent, both use CHAT_MODEL」——改为多 Agent 编排，但 LLM 模型仍统一用 `CHAT_MODEL`（不同节点不配不同模型）。

**约束**：
- SSE 事件契约（v1 §10.2）不变，从 LangGraph astream_events 适配。
- write 工具仍必经 Proposal 确认（interrupt + checkpointer）。
- max-turn 上限和 _strip_think 保留。

---

## D4. 宪法第七条松绑：从「绝不打扰」到「克制提示」

**决策**：桌面宠物可在新 hypothesis 出现时做轻微动效提示（角色微动、状态切换动画）。不可弹系统通知、不可抢焦点、不可弹窗打断。提示强度必须可在设置里关闭。

**理由**：
- 桌面宠物作为 ambient companion，需要有「活」的感觉。完全静默的桌面宠物没有产品差异化。
- 轻微动效（如角色眼睛眨一下、状态色彩渐变）不构成「打扰」——用户可以选择不看。
- 「可关闭」是关键兜底：对任何觉得这是打扰的用户，一键关闭。
- 与第五条承诺不矛盾：WF 仍然是减法工具，轻微动效不是「让你做更多」的 push。

**被取代项**：v1 宪法第七条「WF 不打扰用户、不发通知、不主动 push」中的「不主动 push」——改为「克制提示（calibrated proactivity）」。

**红线**（不可违反）：
- 不可弹系统通知
- 不可抢焦点（always-on-top 不等于抢焦点，宠物窗本身就是 always-on-top）
- 不可弹窗打断
- 必须可在设置里关闭（`proactivity.enabled`）

---

## D5. 宪法第四条松绑：从「硬红线」到「可插拔集成层」

**决策**：将 Calendar 和 GitHub 从硬编码 MCP client 重构为 Provider SPI / Registry 模式。本次迭代只重构现有集成为 provider 层，不新增第三方集成。

**理由**：
- v1 的 Calendar 和 GitHub 是硬编码在 `mcp_client/` 中的，添加新集成需要改多处代码。
- Provider SPI 让每个集成自注册工具、自声明健康检查，降低集成新 provider 的边际成本。
- 但产品立场不变：每新增一个 provider 必须有产品理由。SPI 是架构灵活性，不是开放平台邀请。

**被取代项**：v1 宪法第四条「核心集成只有 Calendar 和 GitHub。其他不集成——不是"暂时不集成"，是产品立场」——改为「可插拔集成层，仍为 curated 小集合」。

**约束**：v2 期间不新增第三方集成，仅重构。

---

## D6. 引入 Langfuse + OpenTelemetry 全链路可观测

**决策**：使用 Langfuse 做 LLM trace，OpenTelemetry 做全链路 traceId 透传。Langfuse 自托管（docker-compose），env 缺失时降级为结构化日志。

**理由**：
- v1 只有 JSON 日志，一次 agent run 的全貌不可见。调试多节点图执行尤其困难。
- Langfuse 专为 LLM 应用设计：trace 树、token 计量、成本追踪、模型对比。
- OpenTelemetry 是行业标准，traceId 透传跨 async / scheduler / MCP 调用，串联全链路。
- 自托管避免外部依赖，env 缺失时降级不影响核心功能。

**被取代项**：无（v1 没有可观测设计，这是纯新增）。

**约束**：env 缺失时系统不报错，降级为只打结构化日志。

---

## D7. 引入 Eval 框架（LLM-as-judge + 轨迹评测）

**决策**：建立评测集（≥30 条标注样本）、LLM-as-judge 评分、轨迹评测、回归 harness。

**理由**：
- 「Agent 好不好」在 v1 只能靠 contracts 测试验证正确性，无法衡量质量（faithfulness、groundedness、召回相关性）。
- 多 Agent 架构引入后，planner 选工具是否合理、critic 是否有效，需要轨迹级评测。
- 回归 harness 确保 v2 迭代不退化：一键跑全集，输出记分卡。

**被取代项**：无（v1 没有 eval 设计，这是纯新增）。

---

## D8. LangGraph checkpointer 使用 SQLite（单独 db 文件）

**决策**：使用 `langgraph-checkpoint-sqlite`，数据库文件为 `data/graph_checkpoints.db`，不与 L1 的 `events` 表混存。

**理由**：
- 复用项目已有的 SQLite 运维经验。
- 单独 db 文件避免 checkpointer 的高频读写污染 L1 的 append-only 语义。
- L1 的 `events` 表是 append-only 历史日志，checkpointer 是临时状态快照，两者语义不同，混存会混淆。

**被取代项**：无（v1 没有 checkpointer）。

---

## D9. Embedding 供应商复用阿里 text-embedding-v4

**决策**：L2.5 的 embedding 使用阿里 `text-embedding-v4`，通过 `EMBEDDING_PROVIDER` / `EMBEDDING_MODEL` / `EMBEDDING_API_KEY` env 可切换。

**理由**：
- 与 PaperRAG 项目保持一致，降低心智负担和运维成本。
- env 可切换保证不锁死供应商。

**被取代项**：无。

---

## D10. 桌面端框架选型：Electron + TypeScript

**决策**：Phase 2 桌面宠物 App 使用 Electron + TypeScript。

**理由**：
- 复用项目现有 Next.js / TypeScript 技术栈。
- Electron 生态成熟，对自主 agent 最可靠（不引入 Rust 工具链这一额外失败面）。
- 透明无边框窗口 + 系统托盘在 Electron 中有成熟方案。

**被取代项**：无（v1 没有桌面端）。

**备选已弃用**：Tauri（Rust 工具链增加失败面，且用户未把 Rust 列为主要学习目标）。

---

**文档结束**
