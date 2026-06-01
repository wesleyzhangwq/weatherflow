# Phase 0 Review — WeatherFlow v2 地基

> Phase 0 完成日期：2026-06-01
> 里程碑：M0.1 → M0.2 → M0.3
> 状态：等待人类 review

---

## v2 宪法改了哪几条

九条宪法中，三条修改、六条保留：

| 条款 | v1 → v2 变化 | 关键措辞变化 |
|---|---|---|
| **第四条** | 「硬红线：只集成 Calendar + GitHub」→「可插拔集成层（Provider SPI），仍为 curated 小集合」 | 产品立场不变，架构松绑。本次迭代只重构现有集成为 provider 层，不新增。 |
| **第六条** | 「禁向量库」→「允许向量库作为 L1 的派生召回层（L2.5）」 | L3 profile.md 仍是人类可读可改的 Markdown。L2.5 是 projection，不是 source of truth。 |
| **第七条** | 「绝不打扰 / 不主动 push」→「克制提示（calibrated proactivity）」 | 桌面宠物**可**轻微动效；**不可**弹系统通知 / 抢焦点 / 弹窗打断。可关闭。 |

其余六条（身份、双模式、第一屏、承诺、写操作唯一入口、卡片是脸）保持不变。

---

## ADR-003 核心立场（10 条决策）

| # | 决策 | 一句话理由 |
|---|---|---|
| D1 | 引入 mem0 + Qdrant 作为 L2.5 | ContextLoader 只按最近 N 条召回，补语义检索盲区 |
| D2 | mem0 是派生投影 | 删掉 Qdrant 可从 L1 重建，每条记忆带 source_event_id 回链 |
| D3 | 引入 LangGraph 多 Agent | 单 ReAct 无法 self-check；interrupt 天然支持 Proposal HITL |
| D4 | 宪法第七条松绑为克制提示 | 桌面宠物需要「活」的感觉，但严格限制在不打断范围 |
| D5 | 宪法第四条松绑为 Provider SPI | 架构灵活性 ≠ 开放平台，每新增 provider 需产品理由 |
| D6 | Langfuse + OTel 可观测 | 一次 agent run 全貌不可见 → trace 树 + traceId 透传 |
| D7 | Eval 框架 | Agent 质量只能靠 contracts 测正确性 → eval + LLM-as-judge + 回归 |
| D8 | SQLite checkpointer | 单独 db 文件，不和 L1 events 表混存 |
| D9 | Embedding 阿里 text-embedding-v4 | 与 PaperRAG 一致，env 可切 |
| D10 | Electron + TS 桌面端 | 复用 TS 栈，不引入 Rust 失败面 |

---

## 与 v1 的不变量差异

### 保持不变的硬约束
- L1 append-only（永不修改、永不删除）
- evidence 的 `source_event_id` 必须在 L1 真实存在
- write tool 必经 Proposal 确认
- Calibration 不触发新 hypothesis
- Label/Weather ∈ 6 固定值
- destructive 工具不可见
- Profile.md 用户可读可改
- Chat 多轮 hypothesis 按 conversation_id 派生

### v2 新增约束
- L2.5 是 L1 的派生投影，可从 L1 重建
- Critic 节点做运行时 groundedness 自检（source_event_id 真实性）
- 克制提示有红线：不可弹系统通知、不可抢焦点、可关闭
- Provider SPI 替代硬编码集成，但 curated 小集合不变
- LangGraph checkpointer 使用单独 SQLite 文件

### v1 中被显式取代的禁令（ADR-003 Supersedes）
- ~~❌ 任何向量库~~ → 允许作为 L1 派生召回层
- ~~❌ ONE rhythm agent + ONE chat agent~~ → 多 Agent 编排（仍用 ONE model）
- ~~❌ 绝不打扰用户~~ → 克制提示

---

## 产出物清单

| 文件 | 状态 |
|---|---|
| `weatherflow-architecture-v2.md` | ✅ 新建（875 行） |
| `docs/ADR-003-v2-pivot.md` | ✅ 新建（10 条决策） |
| `AGENTS.md` | ✅ 更新（指向 v2，移除 obsolete anti-patterns） |
| `weatherflow-v2-roadmap.md` | ✅ 附录 A/B 更新 |

---

## 下一步

Phase 0 已完成。**等待人类 review 后重新启动以执行 Phase 1（M1A.1 起）**。Phase 1 起将连续执行到 Phase 2，中途不再停。
