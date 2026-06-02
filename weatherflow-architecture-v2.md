# WeatherFlow 架构设计文档 v2

> 本文档是 WeatherFlow（以下简称 WF）v2 版本的完整设计参考。它在 v1 基础上升级记忆拓扑（新增 L2.5 语义召回层）、Agent 编排（从单 ReAct 升级为 LangGraph 多节点状态图）、可观测（Langfuse + OpenTelemetry）与评测体系，并正式重写产品宪法中受影响的条款。
>
> **v1 文档仍然保留在 `weatherflow-architecture-v1.md`，作为存档。本文档是 v2 阶段的 single source of truth。**
>
> 文档目标：作为 WF v2 开发期间的单一真实来源（single source of truth）。所有架构决策、命名约定、数据模型都以本文档为准。代码与本文档冲突时，以本文档为准并修正代码。

---

## 0. 文档说明

**版本**：v2
**基底**：v1（2026-05-22）
**适用阶段**：WF v2 迭代期（求职硬通货：多 Agent / mem0 / 可观测 / 评测 / 生产化）
**更新原则**：本文档每次更新都应该在末尾「决策变更记录」里追加一条 changelog，不直接覆盖历史决策。

**阅读路径建议**：
- 第一次读：先读第 1 章（宪法），再读 §13（语义记忆）、§14（多 Agent），最后按需查阅 v1 已有章节
- 后续查阅：第 4 章（数据模型）、第 5 章（Hypothesis 生成）、§13、§14 是最常翻的部分
- 写代码前：先对照第 12 章（数据流图）+ §14 的图节点确认理解一致

**v1 → v2 变更速览**：
| 领域 | v1 | v2 |
|---|---|---|
| 记忆拓扑 | L1 / L2 / L3 三层 | L1 / L2 / **L2.5** / L3 四层 |
| Agent 编排 | 单函数 + 单 ReAct chat_agent | LangGraph 状态图（planner → memory → worker → critic → synthesize） |
| Proposal 机制 | Dispatcher 拦截 | LangGraph interrupt（human-in-the-loop）+ checkpointer |
| 可观测 | JSON 日志 | Langfuse trace + OpenTelemetry 全链路 |
| 质量保证 | contracts 测试 | eval 集 + LLM-as-judge + 轨迹评测 + 回归 harness |
| 宪法第四条 | 硬红线：只集成 Calendar + GitHub | 可插拔集成层（provider SPI/registry），仍为 curated 小集合 |
| 宪法第六条 | 禁向量库；L3 只能是 markdown | 允许向量库作为 L1 的派生召回层；L3 profile.md 仍是人类可读 |
| 宪法第七条 | 绝不打扰用户 | 克制提示（calibrated proactivity）：轻微动效可，禁系统通知/抢焦点/弹窗，可关闭 |

---

## 1. 产品宪法

WF 的所有设计决策必须服从以下九条产品宪法。新增功能时，先检查是否与下列任一条冲突；若冲突，功能不做，或修改宪法（后者门槛极高）。

每条标注 **[v1 保留]** 或 **[v2 修改]**。

### 第一条（身份）[v1 保留]
WeatherFlow 是给陷入「低效—无复盘—更低效」循环的开发者的**节奏教练 + 日常驾驶舱**。

### 第二条（双模式）[v1 保留]
WF 有且仅有两种使用模式，缺一不可：
- **节奏镜像**：每日状态卡片 + hypothesis 校准。低频、高分量、被动触发。
- **日常驾驶舱**：Chat 查询/规划 Calendar 和 GitHub。高频、轻量、用户主动。

两种模式互相喂养——驾驶舱的每次交互都是镜像的 evidence，镜像的每次理解都让驾驶舱回答更精准。

### 第三条（第一屏）[v1 保留]
**用户对自己状态的感知是这个产品的一切。**
打开 WF，第一屏永远是节奏卡片堆。查日程要往下滑或打字。这个 friction 是故意的。

### 第四条（集成层）[v2 修改：从「硬红线」改为「可插拔集成层」]
核心集成为 Calendar 和 GitHub，通过 **Provider SPI / Registry** 模式接入。本次迭代（v2）仅重构现有集成为 provider 层，不新增第三方集成。未来可扩展新 provider，但仍为 curated 小集合——不是开放平台。

> v1 原文：「核心集成只有 Calendar 和 GitHub。其他不集成——不是"暂时不集成"，是产品立场。」
> v2 松绑为可插拔架构，但产品立场不变：每新增一个 provider 必须有产品理由，不为了集成而集成。

### 第五条（承诺）[v1 保留]
WF 不让你更高效，WF 让你**看清自己的节奏，在冲向 burnout 之前拉一把**。
加法工具（Reclaim/Motion）塞更多任务，WF 是减法工具——必要时建议你少做。

### 第六条（记忆哲学）[v2 修改：允许向量库作为 L1 派生召回层]
WF 不假装比你更懂你。**我们一起拼凑理解**，不是 AI 替你判断。
所以 hypothesis 必须有 evidence，evidence 必须可溯源，profile.md 必须用户可读可改。

**v2 新增**：允许使用向量库（Qdrant）作为 L1 事件的**语义召回层**（L2.5）。L2.5 是 L1 的派生投影——删掉整个 Qdrant，可从 L1 一键重建。L2.5 绝不是新的真理来源。L3 profile.md 仍然是人类可读可改的 Markdown 文件。

> v1 原文禁「任何向量库」。v2 的理由：ContextLoader 只按「最近 N 条」装配 evidence，召回不了「三周前那次相似的 Overload」。语义检索补这个洞，但作为 projection 而非 source of truth，不破坏 L1 append-only 不变量。

### 第七条（克制的主动）[v2 修改：从「绝不打扰」改为「克制提示」]
WF 不打扰用户、不发系统通知、不抢焦点、不弹窗打断。
但 WF 自己会在背景里持续保持对用户的理解——通过每 6 小时的定时检查更新 evidence 和卡片。
当用户来找它时，它已经准备好了。

**v2 新增**：桌面宠物**可在新 hypothesis 出现时做轻微动效提示**（如角色微动、状态切换动画）。**不可**弹系统通知、不可抢焦点、不可弹窗打断。提示强度必须可在设置里关闭（`proactivity.enabled` 开关）。

> v1 原文「不打扰用户、不发通知、不主动 push」。v2 的理由：桌面宠物作为 ambient companion 需要有「活」的感觉，轻微动效是产品差异化的一部分，但严格限制在「不打断」范围内。

### 第八条（写操作的唯一入口）[v1 保留]
Proposal 只在 **Chat 流程**中生成。Check-in、主页卡片操作、定时检查永远不产生写操作建议。
所有 write tool 的调用必须先转 Proposal，经用户确认后才执行。
v2 中 Proposal 通过 LangGraph interrupt（human-in-the-loop）实现，确认后从 checkpointer 断点恢复。

### 第九条（卡片是脸）[v1 保留]
Hypothesis 卡片是 WF 主页的核心 UI。每张卡都必须能被校准、能被溯源到具体 evidence event。
卡片堆是「待校准队列」，经用户校准为「准」的卡片才会进入长期记忆。

---

## 2. 输入清单（v1 不变）

WF 系统有且仅有以下 4 种输入。任何新增功能都必须能映射到这 4 种之一，否则需要先讨论是否扩展输入清单（高门槛）。

### 输入 T1：Check-in 提交
- **触发者**：用户主动
- **形式**：三问回答（天气必填 + 项目可选 + 摩擦点可选 + 自由文本可选）
- **频率**：用户决定，产品引导每天 1-2 次，但同一天多次提交也允许
- **核心意图**：用户主动提供主观信号，告诉 WF「我现在的内在状态」

### 输入 T2：定时检查
- **触发者**：系统（scheduler）
- **形式**：固定时刻触发，每 6 小时一次（00:00、06:00、12:00、18:00 本地时间）
- **频率**：固定，不受用户活跃度影响
- **核心意图**：让 evidence（Calendar + GitHub）保持新鲜，并基于新 evidence 生成新 hypothesis

### 输入 T3：Hypothesis 校准
- **触发者**：用户主动
- **形式**：对当前主页大卡选择「准 / 不准 / 部分准」（粗粒度三选一）
- **频率**：用户决定
- **核心意图**：用户对 WF 判断的反馈，完成「理解你」闭环

### 输入 T4：Chat 消息
- **触发者**：用户主动
- **形式**：自然语言消息
- **频率**：用户决定，可能高频
- **核心意图**：驾驶舱——查询日程/repo、规划下一步、要求 WF 解释自己的判断

---

## 3. 输出清单（v1 不变，O6 有变化）

WF 系统的所有副作用必须落入以下 6 种输出之一。

### 输出 O1：Hypothesis 卡片（主页）
- **受众**：用户
- **形式**：卡片堆，最多 3 张，新的进堆顶，超过 3 张自动淘汰最旧的
- **更新触发**：T1、T2、T4（Chat 同会话多次只更新最近一张 chat 卡）、T3（校准后大卡消失，小卡升级）

### 输出 O2：SSE 流式回答（Chat）
- **受众**：用户
- **形式**：事件流（`context_loaded` / `hypothesis_generated` / `reasoning_step` / `tool_call_*` / `observation_summary` / `proposal_created` / `final_answer`）
- **更新触发**：仅 T4
- **v2 变更**：SSE 事件仍保持 v1 契约不变，但从 LangGraph astream_events 适配到 sse-starlette

### 输出 O3：Proposal 卡片
- **受众**：用户
- **形式**：可确认的写操作建议（创建 focus block、calendar event、GitHub issue 等）
- **更新触发**：仅 T4（Chat 流程中产生）
- **v2 变更**：Proposal 通过 LangGraph interrupt 暂停图执行，state 由 checkpointer 持久化

### 输出 O4：L1 Event 落库
- **受众**：系统
- **形式**：写一条 event 到 SQLite events 表
- **更新触发**：T1、T2、T3、T4 全部都会写；系统内部行为（reasoning_step、tool_call、proposal、profile_patch 等）也会写

### 输出 O5：DelayedMemoryWriter 异步触发
- **受众**：系统（冷路径）
- **形式**：异步检查 L1 是否有满足门槛的新事件，生成 profile patch
- **更新触发**：T1、T3、T4 完成后异步触发一次

### 输出 O6：克制提示（v2 新增）
- **受众**：用户
- **形式**：桌面宠物在新 hypothesis 出现时做轻微动效提示（角色微动、状态切换动画）
- **更新触发**：新 hypothesis 落 L1 后，通过 SSE 推送到桌面客户端
- **约束**：不可弹系统通知、不可抢焦点、不可弹窗打断。必须可在设置里关闭。

---

## 4. 核心数据模型（v1 基础 + v2 扩展）

### 4.1 L1 Event 类型清单

L1 是 SQLite 里一张表 `events`，所有事件都进这一张表。完整 schema：

```sql
CREATE TABLE events (
    id           TEXT PRIMARY KEY,        -- ULID 或 UUID，自动生成
    type         TEXT NOT NULL,           -- 事件类型（见下表）
    user_id      TEXT NOT NULL,
    timestamp    DATETIME NOT NULL,       -- UTC
    payload      TEXT NOT NULL,           -- JSON，该类型事件的具体数据
    refs         TEXT,                    -- JSON，引用其他 event 的 id（可选）
    INDEX idx_user_type_time (user_id, type, timestamp DESC)
);
```

**关键不变量**（v2 保持不变）：
- L1 是 **append-only**。任何已写入的 event **永不修改、永不删除**。
- L1 写入是**确定性的**，不经过 LLM 判断。
- 所有理解（L2 工作记忆、L2.5 语义召回、L3 长期画像）都从 L1 派生；L1 完整则系统永远可以从头重建。

#### 完整事件类型表

| Type | 触发时机 | Payload 关键字段 | Refs |
|---|---|---|---|
| `checkin` | T1 用户提交 | `weather`, `project`, `friction_point`, `free_text` | — |
| `calendar_snapshot` | T2 定时检查拉 Calendar | `events`（数组）、`window_start`、`window_end` | — |
| `github_snapshot` | T2 定时检查拉 GitHub | `commits`、`prs`、`issues`、`active_repos` | — |
| `evidence_summary` | T2 LLM 摘要后 | `text`（自然语言摘要） | `sources`（指向 calendar_snapshot + github_snapshot） |
| `hypothesis` | T1/T2/T4 + 用户主动重新生成 | `label`、`confidence`、`evidence[]`（每条带 source_event_id）、`counter_evidence[]`、`missing_evidence[]`、`source_tag`（checkin/scheduled/chat） | `triggered_by`、`evidence_sources` |
| `hypothesis_feedback` | T3 用户校准 | `hypothesis_id`、`verdict`（confirmed/rejected/partial） | `target`（指向 hypothesis） |
| `chat_turn` | T4 用户每条消息 | `role`、`content`、`conversation_id` | — |
| `reasoning_step` | T4 Agent 内部推理 | `text`（对外可见的摘要） | `parent`（指向 chat_turn） |
| `tool_call` | T4 Agent 调用 read tool | `tool_name`、`arguments`、`result` | `parent` |
| `proposal` | T4 Agent 想调用 write tool | `tool_name`、`arguments`、`rationale`、`status`（pending/confirmed/rejected/expired） | `parent`、`from_reasoning` |
| `executed_action` | 用户确认 proposal 后执行 | `proposal_id`、`tool_name`、`result` | `proposal` |
| `profile_patch` | DelayedMemoryWriter 更新 profile.md | `section`、`diff`、`triggered_by`（指向 L1 事件 id 数组） | `triggered_by` |

#### 用户可见性（v1 不变）

| 用户可在「节奏历史」页查看 | 用户不可见（仅内部） |
|---|---|
| checkin | calendar_snapshot |
| hypothesis | github_snapshot |
| hypothesis_feedback | evidence_summary |
| proposal | reasoning_step |
| executed_action | tool_call |
| | profile_patch |
| | chat_turn（可在 chat 历史页看，但不在「节奏历史」） |

### 4.2 Hypothesis 数据结构（v1 不变）

Hypothesis 的 payload 强制契约：

```json
{
  "label": "Overload",
  "confidence": 0.72,
  "summary": "交付和协作同时偏高，当前更像 Overload。",

  "evidence": [
    {
      "text": "过去 3 天有 12 场会议",
      "source_event_id": "evt_calendar_snapshot_01HXYZ..."
    },
    {
      "text": "GitHub 主仓库提交比上周下降 60%",
      "source_event_id": "evt_github_snapshot_01HXYZ..."
    },
    {
      "text": "今天 check-in 选了 🌫 大雾，说'有点乱'",
      "source_event_id": "evt_checkin_01HXYZ..."
    }
  ],

  "counter_evidence": [
    {
      "text": "GitHub 仍有持续推进，因此不是完全 Blocked",
      "source_event_id": "evt_github_snapshot_01HXYZ..."
    }
  ],

  "missing_evidence": [
    "还缺少明天日历的最新空档信息"
  ],

  "source_tag": "checkin"
}
```

**硬约束**（v2 保持不变）：
- `evidence` 数组每一项**必须**包含 `source_event_id`，且该 id 必须在 L1 中真实存在
- `counter_evidence` 同样必须带 `source_event_id`
- `missing_evidence` 是纯文本（它本身就是「没有 source」的声明）
- `source_tag` ∈ `{checkin, scheduled, chat, recalibrate}`
- 校验在写入 L1 前完成，id 不真实存在 → 拒绝写入，触发 Agent 重生成或降级

**Label 词表**（v1 不变）：`Flow` / `Recovery` / `Steady` / `Overload` / `Blocked` / `Fragmented`

### 4.3 Evidence 数据结构与 source 追溯（v1 不变 + v2 扩展 L2.5 来源）

**核心原则**：任何 hypothesis 的任何 evidence 都必须挂一个 `source_event_id`，这个 id 在 L1 里真实存在。

**v2 扩展**：当 evidence 来自 L2.5 语义召回时，mem0 memory 记录中同样携带 `source_event_id`（指向原始 L1 event）。因此从 L2.5 召回的 evidence 同样可溯源到 L1。

**校验**：LLM 输出后，系统逐条核对 `source_event_id` 是否在 bundle 中出现过。任何不匹配 → 拒绝。

### 4.4 Profile.md 章节结构（v1 不变）

6 个固定章节：Identity / Active Projects / Rhythm Patterns / Preferences / Anti-patterns / Recent Themes。
L3 profile.md 仍然是人类可读可改的 Markdown 文件，通过 DelayedMemoryWriter 四道门槛写入。

### 4.5 主页卡片堆数据模型（v1 不变）

最多 3 张，按时间倒序，校准后消失，小卡升级。详见 v1 §4.5。

---

## 5. Hypothesis 生成机制（v1 基础 + v2 改造）

### 5.1 统一生成函数（v1 不变）

四个触发点共享同一个 `generate_hypothesis()` 入口。流程：装配 bundle → 跑 Agent → 校验 source_event_id → 落 L1。

**v2 变更**：Agent 内部从单 ReAct 循环升级为 LangGraph 状态图（见 §14），但对外接口不变。

### 5.2 四种触发的差异（v1 不变）

| 触发 | 是否拉新外部数据 | mode 参数 | source_tag |
|---|---|---|---|
| T1 Check-in | ❌ 不拉 | `checkin` | `checkin` |
| T2 定时检查 | ✅ 拉 Calendar + GitHub，LLM 摘要 | `background` | `scheduled` |
| T4 Chat 首轮 | ❌ 不拉 | `chat` | `chat` |

### 5.3 校准动作的处理（v1 不变）

校准是「标记 + 移除」，不触发新 hypothesis 生成。确定性操作，不调 LLM。

### 5.4 Evidence 收集与 Source 追溯（v2 扩展）

ContextLoader v2 在 v1 的「最近 N 条」基础上，新增「与 trigger 语义最相关的 K 条历史记忆」（来自 L2.5 mem0），合并去重，仍受 §6.3 token 上限约束。每条语义召回的 evidence 同样带 `source_event_id`。

### 5.5 Chat 中的 Hypothesis 处理（v1 不变）

同 conversation_id 内首轮进堆，后续轮更新最近一张 chat 卡。详见 v1 §5.5。

---

## 6. ContextLoader 装配规则（v1 基础 + v2 融合语义召回）

### 6.1 通用 Bundle 结构

| 成分 | 数量 | 来源 |
|---|---|---|
| Trigger event | 1 | 必含 |
| 最近 hypothesis | 3 | L1 |
| 最近 hypothesis_feedback | 5 | L1 |
| 最近 check-in | 3 | L1 |
| 最近 calendar_snapshot | 1 | L1 |
| 最近 github_snapshot | 1 | L1 |
| 最近 evidence_summary | 1 | L1 |
| profile.md 相关章节 | 由 mode 决定 | §6.2 |
| **语义召回记忆** | **K 条** | **L2.5 mem0（v2 新增）** |

每条 evidence 在 Bundle 中都自带 `event_id`，供 LLM 在输出时引用。来自 L2.5 的记忆同样携带 `source_event_id` 回链到 L1。

### 6.2 各 mode 的 scope 差异（v1 不变）

| Mode | 加载的 profile 章节 |
|---|---|
| `checkin` | Rhythm Patterns + Recent Themes + Active Projects |
| `background` | Rhythm Patterns + Anti-patterns + Recent Themes |
| `chat` | Identity + Preferences + Rhythm Patterns + Active Projects |

### 6.3 Token 上限与截断（v1 不变，扩展语义召回截断）

**上限**：Bundle 序列化后的总 token 数不超过 **8000**。

**截断优先级**（从最先被截断到最不能截断）：
1. evidence_summary 的全文（可只保留摘要 label + 关键数字）
2. 较旧的 hypothesis（保留最新 1 条即可）
3. 较旧的 check-in 的 free_text（保留结构化字段）
4. profile 中较长的章节内容（按段落级别截断）
5. **语义召回记忆中相关度最低的条目（v2 新增）**

**永远不截断**：
- Trigger event 自身
- 最近一条 calendar_snapshot 的事件计数和会议密度统计
- 最近一条 github_snapshot 的活动指标
- 最近 3 条 hypothesis_feedback

### 6.4 首次使用场景（v1 不变）

第一次 check-in 时 bundle 几乎为空，照常生成简短 hypothesis。L2.5 此时也为空（无历史可检索），降级为纯「最近性」模式。

---

## 7. 工具系统（v1 基础 + v2 Provider SPI）

### 7.1 工具分类（v1 不变）

`read` / `write` / `destructive` 三级模式。destructive 工具默认过滤，不可见。

### 7.2 Provider SPI / Registry（v2 新增）

v2 将 Calendar 和 GitHub 从硬编码 MCP client 重构为 **Provider SPI** 模式：

```python
class Provider(Protocol):
    name: str
    tools: list[Tool]        # 该 provider 暴露的所有工具
    async def health_check(self) -> bool
    async def snapshot(self, user_id: str, window: dict) -> dict

# Registry
class ProviderRegistry:
    def register(self, provider: Provider) -> None: ...
    def get_all_tools(self) -> list[Tool]: ...
    def get_provider(self, name: str) -> Provider: ...
```

- Calendar 和 GitHub 各实现一个 Provider
- 工具注册表从 Registry 动态构建，而非硬编码
- **本次迭代只重构现有集成为 provider 层，不新增第三方集成**

### 7.3 Calendar 工具清单（v1 不变）

| Tool | Mode | 描述 |
|---|---|---|
| `calendar.find_free_slots` | read | 查找指定日期范围内的空档 |
| `calendar.list_events` | read | 列出指定日期范围的事件 |
| `calendar.get_event` | read | 获取单个事件详情 |
| `calendar.create_focus_block` | write | 创建一个 deep work block |
| `calendar.create_event` | write | 创建一般事件 |
| `calendar.update_event` | write | 修改事件 |
| `calendar.delete_event` | destructive | （不暴露） |

### 7.4 GitHub 工具清单（v1 不变）

| Tool | Mode | 描述 |
|---|---|---|
| `github.list_repos` | read | 列出活跃 repo |
| `github.get_repo_status` | read | 获取 repo 的最近活动概况 |
| `github.list_issues` | read | 列出 issue |
| `github.list_prs` | read | 列出 PR |
| `github.get_commit_activity` | read | 获取提交活动统计 |
| `github.create_issue` | write | 创建 issue |
| `github.comment_on_issue` | write | 评论 issue |
| `github.close_issue` | destructive | （不暴露） |
| `github.delete_*` | destructive | （不暴露） |

### 7.5 Proposal 机制（v2 改造为 LangGraph interrupt）

v1 的 Dispatcher 拦截 → v2 的 LangGraph interrupt：
- write tool 调用触发 LangGraph `interrupt()`，图执行暂停
- state 通过 checkpointer 持久化到 SQLite（`data/graph_checkpoints.db`）
- `POST /api/actions/{id}/execute` 后从断点 `resume` 继续图
- v1 不变量保持：write 必经用户确认

---

## 8. 定时检查（T2）详细流程（v1 不变）

每 6 小时一次（00:00/06:00/12:00/18:00 本地时区），不受用户活跃度影响。

流程：拉 Calendar → 拉 GitHub → LLM 摘要 → 生成 hypothesis → 主页堆插入新卡。详见 v1 §8。

---

## 9. 记忆系统（v1 基础 + v2 新增 L2.5）

### 9.1 四层结构

```
L1 Event Log               事实层：所有发生过的事，确定性、append-only
   ↓ 读
L2 Working Context          临时层：每次请求装配的 evidence bundle，不落盘
   (送给 LLM)

   ↓ 语义检索（v2 新增）
L2.5 Semantic Memory        召回层：mem0 + Qdrant，L1 高价值事件的派生投影
   (送给 memory 节点)        可由 rebuild_memory.py 从 L1 完整重建，绝不是新的真理来源

L1 Event Log               （同一个 L1）
   ↓ 异步扫描
DelayedMemoryWriter         闸门：有门槛地从 L1 提炼出 L3
   ↓ 通过门槛
L3 Profile.md               理解层：长期画像，人类可读可改
```

**关键**：
- L2.5 是**新增的一层**，不是替代 L2 或 L3
- L2.5 是 L1 的**派生投影**——删掉 Qdrant，`rebuild_memory.py` 能从 L1 一键重建
- L2.5 解决 v1 的硬伤：ContextLoader 只按「最近 N 条」装配 evidence，召回不了「三周前那次相似的 Overload」

### 9.2 DelayedMemoryWriter 规则（v1 不变）

四道门槛：白名单类型 → 冷却时间（24h）→ 重复阈值（3 次/14 天）→ LLM 信心检查（≥0.6）。详见 v1 §9.2。

### 9.3 Profile.md 章节与更新机制（v1 不变）

### 9.4 Ground Truth 晋升路径（v1 不变）

---

## 10. SSE 事件协议（v1 不变）

### 10.1 Chat SSE 事件类型

| Event | Payload | 何时发送 |
|---|---|---|
| `context_loaded` | `{ message: string }` | Bundle 装配完成 |
| `hypothesis_generated` | Hypothesis 对象 | 首轮 reasoning 输出 hypothesis 后 |
| `reasoning_step` | `{ content: string }` | 每次 reasoning summary |
| `tool_call_started` | `{ tool_name, arguments }` | 读工具调用开始 |
| `tool_call_finished` | `{ tool_name, status }` | 读工具调用结束 |
| `observation_summary` | `{ content: string }` | 工具结果的可读摘要 |
| `proposal_created` | Proposal 对象 | 写工具被拦截，生成 proposal |
| `final_answer` | `{ content: string }` | 终止，Agent 给出最终回答 |
| `error` | `{ message: string }` | 任何阶段出错 |

### 10.2 事件顺序约束（v1 不变）

- `context_loaded` 必须最先发送
- `hypothesis_generated` 必须在 `context_loaded` 之后、首个 `reasoning_step` 之前
- `final_answer` 必须最后发送，且只发送一次
- `proposal_created` 不终止流，可继续 reasoning
- `tool_call_started` 与对应的 `tool_call_finished` + `observation_summary` 成对出现

### 10.3 Check-in 返回（v1 不变）

---

## 11. 用户可见性策略（v1 不变）

详见 v1 §11。

---

## 12. 数据流图（端到端）（v1 不变，内部实现变更）

### 12.1 场景 A：Check-in 提交

```
用户在主页点 "Check-in" 按钮
   ↓
UI 弹出三问表单
   ↓
POST /api/checkin { weather, project, friction_point, free_text }
   ↓
[后端 — v2 内部通过 LangGraph 图执行]
1. event_log.append("checkin", payload) → checkin_id
2. context_loader.load(user_id, checkin_id, mode="checkin") → bundle
   （v2: bundle 包含 L2.5 语义召回的记忆）
3. 图执行：memory → plan → act → criticize → synthesize
4. 校验所有 source_event_id 真实性
   （v2: critic 节点自动校验 groundedness）
5. event_log.append("hypothesis", payload=hyp, refs={...}) → hyp_id
6. 异步: delayed_memory_writer.maybe_update(user_id)
7. 异步: memory_projector.project(hyp_id)  [v2 新增：投影到 L2.5]
   ↓
返回: { checkin_id, hypothesis: {...} }
```

### 12.2 场景 B：定时检查（v1 不变，内部新增 L2.5 投影）

### 12.3 场景 C：校准（v1 不变）

### 12.4 场景 D：Chat（v2 改造为 LangGraph 图流式执行）

```
用户在 chat 输入 "帮我看看明天怎么安排"
   ↓
POST /api/chat/stream { message, conversation_id }
   ↓
[后端 — LangGraph 图执行]
1. event_log.append("chat_turn", payload={role:"user", content}, ...) → turn_id
2. load_context 节点：context_loader.load(user_id, turn_id, mode="chat") → bundle
   （含 L2.5 语义召回）
3. recall_memory 节点：查询 mem0 语义记忆，合并进 state
4. SSE: context_loaded
5. plan 节点：planner 决定工具调用策略
6. act 节点（worker）：执行工具调用，保留 _strip_think + max-turn 上限
   a. 首轮 → hypothesis_generated（进主页堆）
   b. read tool → tool_call_started → tool_call_finished + observation_summary
   c. write tool → interrupt → proposal_created（图暂停，state 持久化）
7. criticize 节点：校验 groundedness（每条 evidence 的 source_event_id 真实性）
   - 不达标 → 回退 plan 节点重试一次
8. synthesize 节点：生成 final_answer
   → SSE: final_answer
9. 异步: delayed_memory_writer.maybe_update(user_id)
10. 异步: memory_projector.project(...)
```

### 12.5 场景 E：Proposal 执行（v2 改造为 checkpointer resume）

```
用户确认 proposal
   ↓
POST /api/actions/{proposal_id}/execute { confirmed: true }
   ↓
[后端]
1. 从 checkpointer 恢复图 state
2. resume 图执行：MCP write tool → executed_action
3. event_log.append("executed_action", ...)
4. 异步: delayed_memory_writer.maybe_update(user_id)
5. 异步: memory_projector.project(...)
   ↓
返回: { action_id, result }
```

---

## 13. 语义记忆层（L2.5 / mem0）[v2 新增]

> **v2.1 更新（ADR-004 D5）**：本层重述为 **FIV** 模型——Facts(L1) / Index / View。
> "L2 / L2.5 两层"合并为 `memory/retrieval.py` 下的两种检索策略（`recall_recent`
> + `recall_semantic`）；ContextLoader 只做编排+预算。写入侧由单一
> `derivations.run_derivations()` fan-out 驱动（**接通了原先未接线的投影，G17**），
> 同时刷新 mem0(L2.5) 与 profile.md(L3)。mem0 存 episodic 实例、profile.md 存
> 经 4 门槛验证的概括，二者互不写对方。

### 13.1 设计目标

v1 的 ContextLoader 只按「最近 N 条」装配 evidence，无法召回「三周前那次相似的 Overload」。L2.5 用语义检索补这个洞。

**设计立场**：mem0 是 **L1 的派生投影**，不是新的真理来源。删掉整个 Qdrant，`rebuild_memory.py` 能从 L1 一键重建。这条不变量是这个项目区别于「随便接个向量库」的核心。

### 13.2 拓扑

```
L1 events (SQLite)
   ↓ MemoryProjector
   · 白名单事件类型：checkin / confirmed hypothesis / executed_action / 含偏好的 chat_turn
   · 每条记忆带 source_event_id 回链到 L1
   · 低价值事件不投影（reasoning_step / tool_call / snapshot 原始数据）

mem0 (Qdrant)
   ↓ 语义检索
ContextLoader v2
   · 与 trigger 语义最相关的 K 条历史记忆
   · 合并到 EvidenceBundle，受 §6.3 token 上限约束
   · 每条证据的 source_event_id 可被 hypothesis 引用、可在 UI 溯源
```

### 13.3 写入触发

MemoryProjector 在以下时机被调用：
- 高价值事件落 L1 后（由 orchestrator 调用）
- 确认的 hypothesis（verdict = confirmed）
- executed_action
- 含明确偏好的 chat_turn

### 13.4 重建机制

`scripts/rebuild_memory.py`：
1. 清空 Qdrant 对应 user 的所有 memory
2. 遍历 L1 全部事件
3. 按白名单过滤，逐条投影到 mem0
4. 幂等：可重复运行无重复写入

### 13.5 不变量

| 不变量 | 含义 |
|---|---|
| L2.5 是派生的 | 删掉 Qdrant 能从 L1 完整重建 |
| 每条记忆有 source_event_id | 回链到 L1 真实事件 |
| L2.5 不是新的真理来源 | 所有理解仍以 L1 为准 |
| User 隔离 | 不同 user 的 memory 严格隔离 |

---

## 14. 多 Agent 编排（LangGraph 状态图）[v2 新增]

> **v2.1 更新（ADR-004 D1–D4）**：图是 Chat 流的**唯一执行路径**（删除 v1 ChatAgent
> 旁路；langgraph 为硬依赖，仅外部服务降级）。Proposal 为真 `interrupt()` +
> `AsyncSqliteSaver` 持久化（`data/graph_checkpoints.db`），`/api/actions/{id}/execute`
> 用 `Command(resume=...)` 续跑、续推理落 L1（回流路线 A）。一次 run = 一棵 Langfuse
> trace（节点=span，LLM=generation，靠 contextvar 串、每请求共享一个 client）。SSE 经
> `graph.astream` 边跑边推。**纪律**：可序列化数据进 AgentState，活对象（client/span）
> 走 contextvar，绝不进 state。

### 14.1 设计目标

把 v1 的单 ReAct 循环（`chat_agent.py`，max 8 turns）升级为带 planner / worker / critic 的 LangGraph 状态图，保留全部 v1 SSE 事件契约。

### 14.2 AgentState

```python
class AgentState(TypedDict):
    messages: list[BaseMessage]       # 对话历史
    bundle: EvidenceBundle            # L2 + L2.5 装配的 evidence
    hypothesis: Hypothesis | None     # 当前 hypothesis
    plan: str | None                  # planner 输出的执行计划
    observations: list[dict]          # 工具调用结果
    proposals: list[dict]             # write tool 产生的 proposal
    critic_verdict: str | None        # "pass" / "retry"
    conversation_id: str
    user_id: str
```

### 14.3 图结构

```
┌──────────┐   ┌──────────┐   ┌────────┐   ┌────────┐   ┌────────────┐
│  load    │──►│  recall  │──►│  plan  │──►│  act   │──►│ criticize  │
│ context  │   │ memory   │   │        │   │(worker)│   │            │
└──────────┘   └──────────┘   └────────┘   └───┬────┘   └─────┬──────┘
                          ▲                     │              │
                          │                     │         pass │
                          │    ┌────────────────┘         ┌────┘
                          │    │  retry                   │
                          │    ▼                         ▼
                          │  ┌────────┐           ┌────────────┐
                          └──│  plan  │           │ synthesize │
                             └────────┘           └────────────┘
```

**节点职责**：

| 节点 | 职责 | v1 对应 |
|---|---|---|
| `load_context` | 调用 ContextLoader v2 装配 bundle（含 L2.5） | `context_loader.load()` |
| `recall_memory` | 查询 mem0 语义记忆，合并进 state | 无（v2 新增） |
| `plan` | planner 决定工具调用策略 | chat_agent 的 reasoning |
| `act` (worker) | 执行工具调用，保留 _strip_think + max-turn | chat_agent 的 function-calling 循环 |
| `criticize` | 校验 groundedness：每条 evidence 的 source_event_id 真实性 | 隐式校验（v1 §5.1 步骤 3） |
| `synthesize` | 生成 final_answer，emit SSE | chat_agent 的 final answer |

### 14.4 条件边

- `act → criticize`：每次工具调用后
- `criticize → plan`：verdict = "retry"（不达标，重新规划）
- `criticize → synthesize`：verdict = "pass"
- `plan → act`：继续工具调用循环
- `act → synthesize`：无更多工具需要调用

### 14.5 Checkpointer

- 使用 SQLite（`langgraph-checkpoint-sqlite`），单独 db 文件 `data/graph_checkpoints.db`
- 不和 L1 的 `events` 表混存
- 用途：Proposal interrupt 的 state 持久化 + 断点恢复

### 14.6 Critic 节点（groundedness 自检）

`criticize` 节点校验：
1. 答案/hypothesis 的每条 evidence 是否挂在 bundle 内真实 `source_event_id`
2. 不达标 → 设 verdict = "retry"，回退 plan 节点，最多重试一次
3. 重试仍不达标 → 降级回答，标注「evidence 不足」

这是 v1 §5.1 步骤 4（校验 source_event_id 真实性）的**运行时自检版本**——在 Agent 内部就拦截，而非等到写入 L1 前。

### 14.7 SSE 事件映射

从 LangGraph astream_events 适配到 sse-starlette：

| LangGraph 事件 | SSE 事件 |
|---|---|
| load_context 完成 | `context_loaded` |
| act 节点输出 hypothesis | `hypothesis_generated` |
| plan 节点输出 reasoning | `reasoning_step` |
| act 节点开始工具调用 | `tool_call_started` |
| act 节点工具调用完成 | `tool_call_finished` + `observation_summary` |
| act 节点 write tool → interrupt | `proposal_created` |
| synthesize 节点输出 | `final_answer` |

### 14.8 RhythmAgent 子图

T1/T2 的 hypothesis 生成复用一个小子图：`recall → hypothesize → verify_sources → persist`，与 chat 图共享 `recall_memory` 节点。

### 14.9 不变量

| 不变量 | 含义 |
|---|---|
| SSE 事件契约不变 | v1 §10.2 的顺序约束保持 |
| write 必经确认 | interrupt + checkpointer，不绕过 |
| source_event_id 硬约束 | critic 节点运行时校验 |
| max-turn 上限 | act 节点保留 v1 的 8 turn 限制 |
| _strip_think | reasoning model 的 <think> 标签照旧剥离 |

---

## 15. 可观测（Langfuse + OpenTelemetry）[v2 新增]

### 15.1 Langfuse

- 一次 agent run = 一个 trace
- 图节点 = span
- 工具调用 = span
- 记录 token / cost / 模型名
- env 缺失时降级为「只打结构化日志、不报错」

### 15.2 OpenTelemetry

- HTTP 入口生成 traceId（contextvars 透传）
- 跨 async / 跨 APScheduler 任务 / 跨 MCP 调用
- 导出到 console 或 Jaeger

### 15.3 结构化日志 + 指标

JSON 日志带 `trace_id / conversation_id / user_id`。
暴露指标：token 用量、各阶段延迟 P50/P95、hypothesis confidence 分布、记忆召回命中率、proposal 确认率。

---

## 16. 评测（Eval）[v2 新增]

> **🚧 v2.1：本章描述的评测框架已整体拆除，待重建（ADR-005）。** 原实现把静态结构
> 检查与 live 评测混在一处，recall/groundedness/trajectory 三类 judge 未接真实
> agent 链路、12 条 check-in 样本未被评估。v2 agent 架构巨变后，评测将针对新架构
> 重建（拆 static/ 与 live/ 两档、judge 接真图/真召回、叠 LLM-as-judge）。以下小节
> 保留为重建时的需求参考。

### 16.1 评测集

`backend/eval/datasets/`：≥30 条标注样本
- check-in → 期望 label 区间
- hypothesis faithfulness（每条 evidence 的 source 必须真实且相关）
- 记忆召回相关性
- 多轮 chat groundedness

### 16.2 LLM-as-judge + 指标

`backend/eval/judges.py`：hypothesis 质量、答案 groundedness 打分；检索类指标（Recall@K / MRR）评 mem0 召回。

### 16.3 轨迹评测（multi-agent）

评 planner 选工具是否合理、critic 是否抓到了注入的错误、是否过度调用工具。

### 16.4 回归 harness + 报告

`backend/eval/run_eval.py` 一键跑全集，输出 markdown/JSON 记分卡。

---

## 17. 生产化 [v2 新增]

### 17.1 全栈 docker-compose

backend + Qdrant + Langfuse + frontend + MCP servers + （可选）Jaeger 一键起。健康检查、依赖顺序。

### 17.2 降级与配置硬化

LLM / Qdrant / mem0 / provider 不可用时确定性降级（延续 v1 fallback 风格）；secrets 走 env。

### 17.3 README v2 + 架构图 + 面试素材

更新 README：v2 解决了什么、记忆拓扑图、多 Agent 图、性能/评测数字。
`docs/interview-notes.md`：面试 Q&A。

---

## 附录 A：关键决策记录（v1 决策保留 + v2 决策见 ADR-003）

v1 的 9 条决策（A.1–A.9）全部保留。v2 的核心决策记录在 `docs/ADR-003-v2-pivot.md`。

---

## 附录 B：文件树建议

```
weatherflow/
├── docs/
│   ├── architecture-v1.md              ← v1 存档
│   └── architecture-v2.md              ← 本文档
├── backend/
│   ├── app/
│   │   ├── agents/
│   │   │   ├── graph/
│   │   │   │   ├── state.py            ← AgentState (v2 新增)
│   │   │   │   └── chat_graph.py       ← LangGraph 图 (v2 新增)
│   │   │   ├── rhythm_agent.py         ← T1/T2 hypothesis 生成
│   │   │   └── chat_agent.py           ← v1 ReAct (逐步迁移进图)
│   │   ├── memory/
│   │   │   ├── semantic/               ← v2 新增：L2.5
│   │   │   │   ├── projector.py        ← L1 → mem0
│   │   │   │   └── ...
│   │   │   ├── event_log.py
│   │   │   ├── schemas.py
│   │   │   ├── context_loader.py       ← v2 升级：融合 L2.5
│   │   │   ├── profile_md.py
│   │   │   ├── hypotheses_view.py
│   │   │   └── delayed_writer.py
│   │   ├── core/
│   │   │   ├── orchestrator.py
│   │   │   ├── llm.py
│   │   │   ├── scheduler.py
│   │   │   └── ...
│   │   ├── providers/                  ← v2 重构：Provider SPI
│   │   │   ├── base.py                 ← Provider protocol
│   │   │   ├── calendar.py
│   │   │   └── github.py
│   │   ├── mcp_client/
│   │   │   ├── client.py
│   │   │   ├── tool_registry.py
│   │   │   └── dispatcher.py
│   │   └── routers/
│   ├── eval/                           ← v2 新增
│   │   ├── datasets/
│   │   ├── judges.py
│   │   └── run_eval.py
│   ├── tests/
│   │   ├── contracts/
│   │   ├── flows/
│   │   ├── memory/
│   │   ├── tools/
│   │   ├── agents/                     ← v2 新增
│   │   └── observability/              ← v2 新增
│   ├── scripts/
│   │   └── rebuild_memory.py           ← v2 新增
│   └── pyproject.toml
├── frontend/
├── desktop/                            ← Phase 2：Electron + TS
├── mcp_servers/
└── docker-compose.yml                  ← v2 扩展：Qdrant + Langfuse
```

---

## 决策变更记录

| 日期 | 变更 | 原因 |
|---|---|---|
| 2026-05-22 | v1 初版 | 与设计讨论同步建立 |
| 2026-06-01 | v2 初版 | v1 → v2 升级：记忆拓扑（L2.5）、Agent 编排（LangGraph）、宪法松绑（第四/六/七条）、可 观测、评测。详见 ADR-003。 |

---

**文档结束**

如需变更任何条款，请先在团队/项目内讨论并取得共识，然后在本文档对应章节修改，并在「决策变更记录」追加 changelog 条目。
