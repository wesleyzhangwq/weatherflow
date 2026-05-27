# WeatherFlow 架构设计文档 v1

> 本文档是 WeatherFlow(以下简称 WF)v1 版本的完整设计参考。它涵盖产品定位、四种输入、Hypothesis 生成机制、Evidence 与 Source 追溯、记忆系统、ContextLoader、工具系统、SSE 协议和数据流。
>
> 文档目标:作为 WF 开发期间的单一真实来源(single source of truth)。所有架构决策、命名约定、数据模型都以本文档为准。代码与本文档冲突时,以本文档为准并修正代码。

---

## 0. 文档说明

**版本**:v1
**适用阶段**:WF MVP 开发期
**更新原则**:本文档每次更新都应该在末尾"决策变更记录"里追加一条 changelog,不直接覆盖历史决策。

**阅读路径建议**:
- 第一次读:按章节顺序通读一遍
- 后续查阅:第 4 章(数据模型)、第 5 章(Hypothesis 生成)、第 6 章(ContextLoader)是最常翻的部分
- 写代码前:先对照第 12 章(数据流图)确认理解一致

---

## 1. 产品宪法

WF 的所有设计决策必须服从以下九条产品宪法。新增功能时,先检查是否与下列任一条冲突;若冲突,功能不做,或修改宪法(后者门槛极高)。

### 第一条(身份)
WeatherFlow 是给陷入"低效—无复盘—更低效"循环的开发者的**节奏教练 + 日常驾驶舱**。

### 第二条(双模式)
WF 有且仅有两种使用模式,缺一不可:
- **节奏镜像**:每日状态卡片 + hypothesis 校准。低频、高分量、被动触发。
- **日常驾驶舱**:Chat 查询/规划 Calendar 和 GitHub。高频、轻量、用户主动。

两种模式互相喂养——驾驶舱的每次交互都是镜像的 evidence,镜像的每次理解都让驾驶舱回答更精准。

### 第三条(第一屏)
**用户对自己状态的感知是这个产品的一切。**
打开 WF,第一屏永远是节奏卡片堆。查日程要往下滑或打字。这个 friction 是故意的。

### 第四条(集成红线)
核心集成只有 **Calendar 和 GitHub**。其他不集成——不是"暂时不集成",是**产品立场**。

### 第五条(承诺)
WF 不让你更高效,WF 让你**看清自己的节奏,在冲向 burnout 之前拉一把**。
加法工具(Reclaim/Motion)塞更多任务,WF 是减法工具——必要时建议你少做。

### 第六条(哲学)
WF 不假装比你更懂你。**我们一起拼凑理解**,不是 AI 替你判断。
所以 hypothesis 必须有 evidence,evidence 必须可溯源,profile.md 必须用户可读可改。

### 第七条(节制的主动)
WF 不打扰用户、不发通知、不主动 push。
但 WF 自己会在背景里持续保持对用户的理解——通过每 6 小时的定时检查更新 evidence 和卡片。
当用户来找它时,它已经准备好了。

### 第八条(写操作的唯一入口)
Proposal 只在 **Chat 流程**中生成。Check-in、主页卡片操作、定时检查永远不产生写操作建议。
所有 write tool 的调用必须先转 Proposal,经用户确认后才执行。

### 第九条(卡片是脸)
Hypothesis 卡片是 WF 主页的核心 UI。每张卡都必须能被校准、能被溯源到具体 evidence event。
卡片堆是"待校准队列",经用户校准为"准"的卡片才会进入长期记忆。

---

## 2. 输入清单

WF 系统有且仅有以下 4 种输入。任何新增功能都必须能映射到这 4 种之一,否则需要先讨论是否扩展输入清单(高门槛)。

### 输入 T1:Check-in 提交
- **触发者**:用户主动
- **形式**:三问回答(天气必填 + 项目可选 + 摩擦点可选 + 自由文本可选)
- **频率**:用户决定,产品引导每天 1-2 次,但同一天多次提交也允许
- **核心意图**:用户主动提供主观信号,告诉 WF "我现在的内在状态"

### 输入 T2:定时检查
- **触发者**:系统(scheduler)
- **形式**:固定时刻触发,每 6 小时一次(00:00、06:00、12:00、18:00 本地时间)
- **频率**:固定,不受用户活跃度影响
- **核心意图**:让 evidence(Calendar + GitHub)保持新鲜,并基于新 evidence 生成新 hypothesis

### 输入 T3:Hypothesis 校准
- **触发者**:用户主动
- **形式**:对当前主页大卡选择"准 / 不准 / 部分准"(粗粒度三选一)
- **频率**:用户决定
- **核心意图**:用户对 WF 判断的反馈,完成"理解你"闭环

### 输入 T4:Chat 消息
- **触发者**:用户主动
- **形式**:自然语言消息
- **频率**:用户决定,可能高频
- **核心意图**:驾驶舱——查询日程/repo、规划下一步、要求 WF 解释自己的判断

---

## 3. 输出清单

WF 系统的所有副作用必须落入以下 6 种输出之一。

### 输出 O1:Hypothesis 卡片(主页)
- **受众**:用户
- **形式**:卡片堆,最多 3 张,新的进堆顶,超过 3 张自动淘汰最旧的
- **更新触发**:T1、T2、T4(Chat 同会话多次只更新最近一张 chat 卡)、T3(校准后大卡消失,小卡升级)

### 输出 O2:SSE 流式回答(Chat)
- **受众**:用户
- **形式**:事件流(`context_loaded` / `hypothesis_generated` / `reasoning_step` / `tool_call_*` / `observation_summary` / `proposal_created` / `final_answer`)
- **更新触发**:仅 T4

### 输出 O3:Proposal 卡片
- **受众**:用户
- **形式**:可确认的写操作建议(创建 focus block、calendar event、GitHub issue 等)
- **更新触发**:仅 T4(Chat 流程中产生)

### 输出 O4:L1 Event 落库
- **受众**:系统
- **形式**:写一条 event 到 SQLite events 表
- **更新触发**:T1、T2、T3、T4 全部都会写;系统内部行为(reasoning_step、tool_call、proposal、profile_patch 等)也会写

### 输出 O5:DelayedMemoryWriter 异步触发
- **受众**:系统(冷路径)
- **形式**:异步检查 L1 是否有满足门槛的新事件,生成 profile patch
- **更新触发**:T1、T3、T4 完成后异步触发一次

### 输出 O6:用户主动 push
**WF v1 不实现**。第七条宪法明确禁止。

---

## 4. 核心数据模型

### 4.1 L1 Event 类型清单

L1 是 SQLite 里一张表 `events`,所有事件都进这一张表。完整 schema:

```sql
CREATE TABLE events (
    id           TEXT PRIMARY KEY,        -- ULID 或 UUID,自动生成
    type         TEXT NOT NULL,           -- 事件类型(见下表)
    user_id      TEXT NOT NULL,
    timestamp    DATETIME NOT NULL,       -- UTC
    payload      TEXT NOT NULL,           -- JSON,该类型事件的具体数据
    refs         TEXT,                    -- JSON,引用其他 event 的 id(可选)
    INDEX idx_user_type_time (user_id, type, timestamp DESC)
);
```

**关键不变量**:
- L1 是 **append-only**。任何已写入的 event **永不修改、永不删除**。
- L1 写入是**确定性的**,不经过 LLM 判断。
- 所有理解(L2 工作记忆、L3 长期画像)都从 L1 派生;L1 完整则系统永远可以从头重建。

#### 完整事件类型表

| Type | 触发时机 | Payload 关键字段 | Refs |
|---|---|---|---|
| `checkin` | T1 用户提交 | `weather`, `project`, `friction_point`, `free_text` | — |
| `calendar_snapshot` | T2 定时检查拉 Calendar | `events`(数组)、`window_start`、`window_end` | — |
| `github_snapshot` | T2 定时检查拉 GitHub | `commits`、`prs`、`issues`、`active_repos` | — |
| `evidence_summary` | T2 LLM 摘要后 | `text`(自然语言摘要) | `sources`(指向 calendar_snapshot + github_snapshot) |
| `hypothesis` | T1/T2/T4 + 用户主动重新生成 | `label`、`confidence`、`evidence[]`(每条带 source_event_id)、`counter_evidence[]`、`missing_evidence[]`、`source_tag`(checkin/scheduled/chat) | `triggered_by`、`evidence_sources` |
| `hypothesis_feedback` | T3 用户校准 | `hypothesis_id`、`verdict`(confirmed/rejected/partial) | `target`(指向 hypothesis) |
| `chat_turn` | T4 用户每条消息 | `role`、`content`、`conversation_id` | — |
| `reasoning_step` | T4 Agent 内部推理 | `text`(对外可见的摘要) | `parent`(指向 chat_turn) |
| `tool_call` | T4 Agent 调用 read tool | `tool_name`、`arguments`、`result` | `parent` |
| `proposal` | T4 Agent 想调用 write tool | `tool_name`、`arguments`、`rationale`、`status`(pending/confirmed/rejected/expired) | `parent`、`from_reasoning` |
| `executed_action` | 用户确认 proposal 后执行 | `proposal_id`、`tool_name`、`result` | `proposal` |
| `profile_patch` | DelayedMemoryWriter 更新 profile.md | `section`、`diff`、`triggered_by`(指向 L1 事件 id 数组) | `triggered_by` |

#### 用户可见性

| 用户可在"节奏历史"页查看 | 用户不可见(仅内部) |
|---|---|
| checkin | calendar_snapshot |
| hypothesis | github_snapshot |
| hypothesis_feedback | evidence_summary |
| proposal | reasoning_step |
| executed_action | tool_call |
| | profile_patch |
| | chat_turn(可在 chat 历史页看,但不在"节奏历史") |

理由见第 11 章。

### 4.2 Hypothesis 数据结构

Hypothesis 的 payload 强制契约:

```json
{
  "label": "Overload",
  "confidence": 0.72,
  "summary": "交付和协作同时偏高,当前更像 Overload。",

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
      "text": "今天 check-in 选了 🌫 大雾,说'有点乱'",
      "source_event_id": "evt_checkin_01HXYZ..."
    }
  ],

  "counter_evidence": [
    {
      "text": "GitHub 仍有持续推进,因此不是完全 Blocked",
      "source_event_id": "evt_github_snapshot_01HXYZ..."
    }
  ],

  "missing_evidence": [
    "还缺少明天日历的最新空档信息"
  ],

  "source_tag": "checkin"
}
```

**硬约束**:
- `evidence` 数组每一项**必须**包含 `source_event_id`,且该 id 必须在 L1 中真实存在
- `counter_evidence` 同样必须带 `source_event_id`
- `missing_evidence` 是纯文本(它本身就是"没有 source"的声明)
- `source_tag` ∈ `{checkin, scheduled, chat, recalibrate}`,用于卡片 UI 显示来源 tag
- 校验在写入 L1 前完成,id 不真实存在 → 拒绝写入,触发 Agent 重生成或降级

**Label 词表(v1 固定)**:
- `Flow` — 状态好,高产
- `Recovery` — 节奏轻,适合恢复
- `Steady` — 平稳推进
- `Overload` — 过载
- `Blocked` — 卡住,无法推进
- `Fragmented` — 碎片化,难专注

(对应 check-in 五种天气,但 label 集合略大于天气集合,因为 hypothesis 综合了多源 evidence)

### 4.3 Evidence 数据结构与 source 追溯

**核心原则**:任何 hypothesis 的任何 evidence 都必须挂一个 `source_event_id`,这个 id 在 L1 里真实存在。

**Source 不是被"生成"的,而是"已经存在"的。** 每一条数据落入 L1 时,自动获得 event id。这个 id 就是该数据成为某个 hypothesis 的 evidence 时的 source。

具体生成流程:

```python
def append_event(type, user_id, payload, refs=None) -> str:
    event_id = generate_ulid()  # 或 uuid4()
    db.execute(
        "INSERT INTO events (id, type, user_id, timestamp, payload, refs) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [event_id, type, user_id, utcnow(), json.dumps(payload), json.dumps(refs or {})]
    )
    return event_id
```

所有 event 落库即有 id,后续被引用时直接使用。

**Evidence 在 Bundle 中的形态**:

ContextLoader 给 LLM 的 evidence 一定**连同 event_id 一起给**:

```
=== Evidence Bundle ===

[evt_calendar_snapshot_01HXYZABC]
Calendar window: last 3 days
Events count: 12
Details:
  - 2026-05-20 10:00 Team standup
  - 2026-05-20 14:00 Design review
  ...

[evt_github_snapshot_01HXYZDEF]
GitHub window: last 7 days
Commits: 8 (vs 20 in previous week)
Active repos: ["weatherflow", "agentguard"]

[evt_checkin_01HXYZGHI]
Weather: 🌫 大雾
Project: weatherflow
Friction: 缺少信息或决策依赖
Free text: "今天有点乱"

=== End of Bundle ===
```

LLM 在 prompt 中被明确告知:
> 你在 evidence 中引用任何事实时,必须在 source_event_id 字段填入你看到的那个 `[evt_xxx]` id,原样抄写,不要修改、不要编造。

**校验**:LLM 输出后,系统逐条核对 `source_event_id` 是否在 bundle 中出现过。任何不匹配 → 拒绝。

### 4.4 Profile.md 章节结构

**存储**:本地一个真实的 .md 文件,路径由 WF 管理(例如 `~/.weatherflow/{user_id}/profile.md`)。
**编辑权限**:用户可用任何编辑器手动改;WF 通过 DelayedMemoryWriter 写入时使用文件锁。

**章节固定**(v1 不允许用户增删章节,只允许编辑章节内容):

```markdown
# Identity
<用户身份、长期目标、自我认知。例如:独立开发者,聚焦 LLM/Agent/RAG。>

# Active Projects
<当前活跃项目列表,作为 check-in 项目选项的来源。>
- WeatherFlow (since 2026-04, primary)
- AgentGuard (since 2026-03, secondary)

# Rhythm Patterns
<已被验证的节奏规律。>
- Overload 信号:会议 ≥4 + DL 任务并行
- Recovery 模式:单一 deep work block 比多任务清单更有效

# Preferences
<工具、时间、工作方式偏好。>
- 工具:Cursor, Claude Code
- 时间:上午 deep work,下午容易碎片化

# Anti-patterns
<历史上反复证明不适合用户的模式。>
- 同时启动多个新方向 → 历史上 3 次失败

# Recent Themes
<最近 N 周的滚动主题,DelayedMemoryWriter 维护。>
```

**Active Projects 的更新路径**(三条):
1. 用户手动编辑
2. 从 GitHub 自动识别:过去 14 天有 commit 的 repo 进入候选(确定性逻辑,不调 LLM)
3. DelayedMemoryWriter 基于 check-in 中"其他工作 + 自由文本"反复出现的关键词,建议加入

### 4.5 主页卡片堆数据模型

**容量**:最多 3 张
**排序**:按生成时间倒序,最新在上
**淘汰**:容量超过 3 张时,淘汰最旧的(被淘汰的 hypothesis 在 L1 中仍然保留)

**卡片状态**:
- `active`:在主页堆上展示
- `confirmed`:用户校准为"准",从主页消失,L1 保留,进入 DelayedMemoryWriter 候选
- `rejected`:用户校准为"不准",从主页消失,L1 保留(标记 rejected),不进候选
- `partial`:用户校准为"部分准",从主页消失,L1 保留(标记 partial),不进候选
- `expired`:被新卡片挤出堆,从主页消失,L1 保留

**卡片 UI 展示**:

```
┌──────────────────────────────────────────┐
│ 🏷 来源: 定时检查 · 11:00                │  ← source_tag
│                                          │
│ 🌧 状态: Overload  (confidence: 0.72)    │  ← label
│                                          │
│ 依据:                                    │  ← evidence,每条可点击溯源
│  · 过去 3 天有 12 场会议        ⓘ        │
│  · GitHub 提交比上周下降 60%    ⓘ        │
│  · 今天 check-in 选了 🌫 大雾    ⓘ        │
│                                          │
│ 反方证据:                                │  ← counter_evidence
│  · GitHub 仍有推进              ⓘ        │
│                                          │
│ 缺少的信息:                              │  ← missing_evidence
│  · 明天日历的最新空档                    │
│                                          │
│  [准] [不准] [部分准]                    │  ← 只有大卡显示这三个按钮
└──────────────────────────────────────────┘
```

**校准行为**:
- 只有最上面的大卡可校准
- 校准后该卡片从主页消失,下面的小卡升级为大卡
- 校准**不主动触发**新 hypothesis 生成(等下一次 T1/T2/T4 自然触发)
- 主页堆从 3 张变 2 张,自然呼吸

---

## 5. Hypothesis 生成机制

### 5.1 统一生成函数

无论哪种触发,Hypothesis 生成都走同一个函数:

```python
async def generate_hypothesis(
    trigger_event_id: str,
    user_id: str,
    mode: Literal["checkin", "background", "chat"]
) -> str:
    """
    所有 hypothesis 生成的统一入口。返回新 hypothesis 的 event id。
    """
    # 1. 装配 evidence bundle(L2,临时,不落盘)
    bundle = await context_loader.load(
        user_id=user_id,
        trigger_event_id=trigger_event_id,
        mode=mode,
    )

    # 2. 跑 Agent
    hyp = await rhythm_agent.generate_hypothesis(bundle=bundle, mode=mode)

    # 3. 校验 source_event_id 真实性
    valid_ids = bundle.all_event_ids()
    for e in hyp.evidence + hyp.counter_evidence:
        if e.source_event_id not in valid_ids:
            raise InvalidHypothesis(
                f"Agent referenced non-existent event_id: {e.source_event_id}"
            )

    # 4. 落 L1
    return await event_log.append(
        type="hypothesis",
        user_id=user_id,
        payload=hyp.dict(),
        refs={
            "triggered_by": trigger_event_id,
            "evidence_sources": [e.source_event_id for e in hyp.evidence]
        }
    )
```

四个触发点都调这个函数,只传不同 mode。

### 5.2 四种触发的差异

**核心相同**:都先把触发事件落 L1 → 装配 bundle → 调 Agent → 校验 source → 落 hypothesis。

**关键差异**(只在两点):

| 触发 | 是否拉新外部数据 | mode 参数 | source_tag |
|---|---|---|---|
| T1 Check-in | ❌ 不拉 | `checkin` | `checkin` |
| T2 定时检查 | ✅ 拉 Calendar + GitHub,LLM 摘要 | `background` | `scheduled` |
| T4 Chat 首轮 | ❌ 不拉 | `chat` | `chat` |

**T1 与 T2 的互补性**:
- T1 引入的新材料是**主观信号**(check-in),其他 evidence 复用上次定时检查的成果
- T2 引入的新材料是**客观数据**(calendar + github snapshot),其他 evidence 复用上次 check-in
- 两条线交替推进,共同维持系统对用户的理解新鲜

**T3 校准不在此列**:校准只标记 hypothesis 状态,**不主动生成新 hypothesis**(见 §5.3)。

**T4 Chat 多轮**:同一 conversation_id 内多次 reasoning,只在**首轮**生成新 hypothesis 写主页堆;后续轮的 hypothesis 是内部 reasoning 的一部分,不写主页,但写 L1。具体规则见 §5.5。

### 5.3 校准动作的处理

**校准是"标记 + 移除",不触发新 hypothesis 生成。** 完整流程:

```
用户点击当前大卡的 [准]/[不准]/[部分准]
   ↓
POST /api/hypothesis/{id}/feedback { verdict: ... }
   ↓
1. 写入 L1: hypothesis_feedback event,payload 包含 verdict
2. 更新原 hypothesis 在 UI 上的状态为 confirmed/rejected/partial
   (L1 中的原 hypothesis event 不修改;状态通过 hypothesis_feedback 的存在派生)
3. 从主页堆移除该卡片(纯 UI 状态变更)
4. 下面的小卡升级为大卡
5. 主页堆容量自然减一
6. 异步触发 DelayedMemoryWriter(仅当 verdict = confirmed 时才会被冷路径选中)
```

**关键不变量**:校准动作本身**不调 LLM**。它是确定性的事件写入 + UI 状态变更。

### 5.4 Evidence 收集与 Source 追溯

Evidence 收集机制对所有 mode 相同。完整流程:

```
ContextLoader.load(user_id, trigger_event_id, mode)
   ↓
1. 强制加入 trigger event 自身(它一定是 evidence 的一部分)
2. 按 §6.1 的清单从 L1 装配各类最近事件
3. 按 §6.2 的 mode 规则加载 profile.md 相关章节
4. 检查 token 上限(§6.3),超出则按优先级截断
5. 返回 EvidenceBundle 对象,每条 evidence 自带 event_id
```

Source 追溯的可验证性:
- UI 中每条 evidence 都有 ⓘ 按钮
- 点击 ⓘ 触发 `GET /api/events/{source_event_id}`,展开该 event 的 payload
- 用户可自己验证 evidence 是否真实

### 5.5 Chat 中的 Hypothesis 处理

**规则 1**:同一 `conversation_id` 内,Chat 首轮 reasoning 生成的 hypothesis **进主页堆**。
**规则 2**:同一 `conversation_id` 内,后续轮的 reasoning **更新最近一张 chat 卡**,不新增。
**规则 3**:首轮 hypothesis 在一次 conversation 内**保持稳定**——它是后续 reasoning 的依据,除非用户在对话中明确说"我的状态变了"。
**规则 4**:不同 `conversation_id` 之间不共享 chat 卡;新 conversation 的首轮 hypothesis 是新的卡片。

实现层面,Chat 卡片的"更新"通过在 L1 写入新 hypothesis event 实现(L1 不改旧 event),主页堆查询时按"同一 conversation_id 取最新一张 chat 卡"派生 UI 状态。

---

## 6. ContextLoader 装配规则

### 6.1 通用 Bundle 结构

无论 mode 如何,Bundle 都包含以下成分:

| 成分 | 数量 | 来源 |
|---|---|---|
| Trigger event | 1 | 必含,即触发本次生成的那个 event |
| 最近 hypothesis | 3 | L1 中最近 3 条 hypothesis event |
| 最近 hypothesis_feedback | 5 | L1 中最近 5 条 feedback event |
| 最近 check-in | 3 | L1 中最近 3 条 checkin event |
| 最近 calendar_snapshot | 1 | L1 中最近一条 |
| 最近 github_snapshot | 1 | L1 中最近一条 |
| 最近 evidence_summary | 1 | L1 中最近一条(T2 产生) |
| profile.md 相关章节 | 由 mode 决定 | 见 §6.2 |

每条 evidence 在 Bundle 中都自带 `event_id`,供 LLM 在输出时引用。

### 6.2 各 mode 的 scope 差异

唯一的差异在 profile 章节选择:

| Mode | 加载的 profile 章节 |
|---|---|
| `checkin` | Rhythm Patterns + Recent Themes + Active Projects |
| `background` | Rhythm Patterns + Anti-patterns + Recent Themes |
| `chat` | Identity + Preferences + Rhythm Patterns + Active Projects |

理由:
- checkin 关注当下节奏判断 + 用户身份的"近况"
- background 关注模式识别,Anti-patterns 帮助避免误判
- chat 进入驾驶舱场景,需要 identity 和 preferences 来回答个性化查询

### 6.3 Token 上限与截断

**上限**:Bundle 序列化后的总 token 数不超过 **8000**(给 Agent 留足空间生成输出)。

**截断优先级**(从最先被截断到最不能截断):
1. evidence_summary 的全文(可只保留摘要 label + 关键数字)
2. 较旧的 hypothesis(保留最新 1 条即可)
3. 较旧的 check-in 的 free_text(保留结构化字段)
4. profile 中较长的章节内容(按段落级别截断)

**永远不截断**:
- Trigger event 自身(它一定要进 LLM)
- 最近一条 calendar_snapshot 的事件计数和会议密度统计
- 最近一条 github_snapshot 的活动指标
- 最近 3 条 hypothesis_feedback(它们是用户校准信号,价值密度极高)

### 6.4 首次使用场景

**第一次 check-in 时**:
- profile.md 还是初始模板(章节都在,但内容是空的或默认提示)
- L1 里只有这一条 checkin event
- Bundle 几乎为空,只有 trigger event 自身

**处理方式**:
- 仍然生成 hypothesis,evidence 字段只有 1 条(指向这次 check-in)
- counter_evidence 和 missing_evidence 可以为空
- 卡片在 UI 上显得简短,但建立了 L1 中的第一条 hypothesis 记录
- 第二次 check-in 起,Bundle 开始有历史可参考

---

## 7. 工具系统

### 7.1 工具分类

所有工具在 ToolRegistry 中注册,每个工具自带 `mode` 字段:

```python
class Tool:
    name: str
    mode: Literal["read", "write", "destructive"]
    schema: dict
    run: Callable
```

**Mode 行为**:
- `read`:Agent 可直接调用,结果作为 observation
- `write`:Agent "调用"该工具,实际转为 Proposal,需用户确认后才真正执行
- `destructive`:**默认从工具列表中过滤掉**,Agent 看不到这些工具的 schema,不可能调用。v1 阶段不暴露任何 destructive 工具。

### 7.2 Calendar 工具清单

| Tool | Mode | 描述 |
|---|---|---|
| `calendar.find_free_slots` | read | 查找指定日期范围内的空档 |
| `calendar.list_events` | read | 列出指定日期范围的事件 |
| `calendar.get_event` | read | 获取单个事件详情 |
| `calendar.create_focus_block` | write | 创建一个 deep work block |
| `calendar.create_event` | write | 创建一般事件 |
| `calendar.update_event` | write | 修改事件 |
| `calendar.delete_event` | destructive | (不暴露) |

### 7.3 GitHub 工具清单

| Tool | Mode | 描述 |
|---|---|---|
| `github.list_repos` | read | 列出活跃 repo |
| `github.get_repo_status` | read | 获取 repo 的最近活动概况 |
| `github.list_issues` | read | 列出 issue |
| `github.list_prs` | read | 列出 PR |
| `github.get_commit_activity` | read | 获取提交活动统计 |
| `github.create_issue` | write | 创建 issue |
| `github.comment_on_issue` | write | 评论 issue |
| `github.close_issue` | destructive | (不暴露) |
| `github.delete_*` | destructive | (不暴露) |

### 7.4 Proposal 机制

当 Agent 决定调用一个 write tool 时,Dispatcher 拦截并转为 Proposal:

```python
async def dispatch(action, agent):
    tool = TOOLS[action.tool_name]

    if tool.mode == "destructive":
        raise ToolNotAvailable(tool.name)

    if tool.mode == "read":
        result = await tool.run(**action.arguments)
        agent.observe(result)
        return ("observation", result)

    if tool.mode == "write":
        proposal_id = await event_log.append(
            type="proposal",
            payload={
                "tool_name": tool.name,
                "arguments": action.arguments,
                "rationale": agent.last_reasoning,
                "status": "pending"
            }
        )
        agent.observe({"proposal_created": proposal_id})
        return ("proposal", proposal_id)
```

**Proposal 生命周期**:
1. `pending`:Agent 创建,等待用户确认
2. `confirmed`:用户点确认,真正执行 MCP 工具
3. `rejected`:用户拒绝
4. `expired`:超过 N 小时无确认(v1 设为 24 小时)

状态变更不修改原 proposal event,而是写新 event(如 `executed_action`、`proposal_rejected`)。

**Proposal 执行接口**:`POST /api/actions/{proposal_id}/execute { confirmed: true }`

---

## 8. 定时检查(T2)详细流程

### 8.1 触发

- **频率**:每 6 小时一次
- **触发时刻**:固定时刻,以用户本地时区为准(00:00、06:00、12:00、18:00)
- **用户活跃度**:不受影响,即使用户多日不活跃也照常运行

### 8.2 完整流程

```python
async def scheduled_check(user_id):
    # 1. 拉 Calendar(MCP read tool)
    calendar_data = await calendar_mcp.list_events(
        user_id, window="last_3_days_and_next_3_days"
    )
    cal_id = await event_log.append(
        type="calendar_snapshot",
        user_id=user_id,
        payload={"events": calendar_data, ...}
    )

    # 2. 拉 GitHub(MCP read tool)
    github_data = await github_mcp.get_activity(
        user_id, window="last_7_days"
    )
    gh_id = await event_log.append(
        type="github_snapshot",
        user_id=user_id,
        payload=github_data
    )

    # 3. LLM 摘要(为后续 hypothesis 提供压缩态 evidence)
    summary_text = await llm_summarize_evidence(calendar_data, github_data)
    summary_id = await event_log.append(
        type="evidence_summary",
        user_id=user_id,
        payload={"text": summary_text},
        refs={"sources": [cal_id, gh_id]}
    )

    # 4. 生成 hypothesis,trigger 用 summary
    await generate_hypothesis(
        trigger_event_id=summary_id,
        user_id=user_id,
        mode="background"
    )

    # 5. 主页堆插入新卡(自动淘汰最旧)
    # 这步由 UI 层在拉取主页数据时按时间排序自动完成,无需特殊代码
```

### 8.3 LLM 摘要的作用

每次定时检查产生**两类 evidence**:
- 原始 snapshot(`calendar_snapshot`、`github_snapshot`)—— 保留全量数据,供溯源
- LLM 摘要(`evidence_summary`)—— 自然语言压缩态,供后续 hypothesis 生成时**优先使用**

**摘要 vs 原始 snapshot 的使用规则**:
- 后续 hypothesis 生成时,ContextLoader 在 Bundle 中**使用 evidence_summary 作为主要 evidence,不展开原始 snapshot 的全部内容**
- 但原始 snapshot 仍保留在 L1,且**仍可作为 source_event_id 被引用**(因为摘要是从它们派生的,引用更原始的 source 更可信)
- UI 上用户点击溯源时,可以一直向下追到 `calendar_snapshot`/`github_snapshot` 的原始数据

**理由**:摘要省 token,原始数据保溯源,两者并存而不重复使用。

---

## 9. 记忆系统

### 9.1 三层结构

```
L1 Event Log          事实层:所有发生过的事,确定性、append-only
   ↓ 读
L2 Working Context    临时层:每次请求装配的 evidence bundle,不落盘
   (送给 LLM)

L1 Event Log          (同一个 L1)
   ↓ 异步扫描
DelayedMemoryWriter   闸门:有门槛地从 L1 提炼出 L3
   ↓ 通过门槛
L3 Profile.md         理解层:长期画像,人类可读可改
```

**关键**:DelayedMemoryWriter **不是一层**,是 L1 → L3 之间的**工序**。

### 9.2 DelayedMemoryWriter 规则

#### 触发时机
- T1、T3、T4 完成后异步触发一次
- 每 12 小时定时跑一次(兜底,防止边角情况漏处理)

#### 门槛规则(必须**全部**满足)

**规则 A:事件类型白名单**

只有以下类型的 L1 events 被考虑:
- `hypothesis` + 关联的 `hypothesis_feedback.verdict == "confirmed"`
- `executed_action`(用户确认执行过的 proposal)
- 显式偏好语句(从 chat_turn 中通过关键词识别)

明确排除:
- `hypothesis_feedback.verdict == "rejected"` 或 `"partial"` — 用户校准为否定,不进候选
- 未被校准的 hypothesis(包括被淘汰为 expired 的)— 不算 ground truth

**规则 B:冷却时间**

同一 `profile section` 在过去 **24 小时**内只能被 patch 一次。

**规则 C:重复阈值**(仅适用于 Rhythm Patterns 和 Anti-patterns 章节)

某个模式必须在过去 **14 天**内至少出现 **3 次**才能进 profile。
单次 confirmed 信号也写 L1,但不会立即 patch 长期画像。

**规则 D:LLM 摘要的信心检查**

DelayedMemoryWriter 用 LLM 生成 patch 内容时,LLM 在 prompt 中被要求输出一个 `confidence`。低于 0.6 → 放弃本次 patch。

#### 实现细节

```python
async def maybe_update(user_id: str):
    last_processed = read_last_processed_timestamp(user_id)

    # 规则 A:白名单查询
    candidates = await db.fetch_high_signal_events(
        user_id, since=last_processed
    )
    if not candidates:
        return

    # 按章节分组
    grouped = group_candidates_by_target_section(candidates)

    for section, events in grouped.items():
        # 规则 B:冷却时间
        if await within_cooldown(user_id, section, hours=24):
            continue

        # 规则 C:重复阈值
        if section in ("Rhythm Patterns", "Anti-patterns"):
            if not meets_repetition_threshold(events, min_count=3, window_days=14):
                continue

        # 规则 D:LLM 摘要
        current_section = profile_store.read_section(user_id, section)
        patch = await llm_generate_patch(
            events, current_section, target_section=section
        )
        if patch.confidence < 0.6:
            continue

        # 应用 patch
        await profile_store.apply_patch(user_id, section, patch)

        # 写审计 event
        await event_log.append(
            type="profile_patch",
            user_id=user_id,
            payload={
                "section": section,
                "diff": patch.diff,
                "confidence": patch.confidence
            },
            refs={"triggered_by": [e.id for e in events]}
        )

    update_last_processed_timestamp(user_id)
```

### 9.3 Profile.md 章节与更新机制

每个章节的更新触发条件:

| 章节 | 谁可以写 | 触发条件 |
|---|---|---|
| Identity | 用户手动 | 用户编辑 .md 文件 |
| Active Projects | 用户手动 + GitHub 自动识别 + DelayedMemoryWriter | 见 §4.4 |
| Rhythm Patterns | DelayedMemoryWriter + 用户手动 | confirmed hypothesis 累计模式 |
| Preferences | DelayedMemoryWriter + 用户手动 | chat 中明确偏好语句 |
| Anti-patterns | DelayedMemoryWriter + 用户手动 | rejected hypothesis + executed_action 失败模式 |
| Recent Themes | DelayedMemoryWriter | 滚动窗口,自动维护 |

### 9.4 Ground Truth 晋升路径

用户校准是 hypothesis 进入长期记忆的唯一通道:

```
hypothesis 生成 → L1 (status: active)
   ↓
用户在主页校准
   ├─→ "准" → hypothesis_feedback (verdict: confirmed) → L1
   │           ↓
   │           DelayedMemoryWriter 候选
   │           ↓ (满足冷却 + 重复阈值 + LLM 信心)
   │           profile.md patch + profile_patch event
   │
   ├─→ "不准" → hypothesis_feedback (verdict: rejected) → L1
   │            ↓
   │            不进候选(但 L1 保留,作为未来 evidence 时的反例信号)
   │
   ├─→ "部分准" → hypothesis_feedback (verdict: partial) → L1
   │              ↓
   │              不进候选(同上)
   │
   └─→ 未校准被挤出 → status: expired → L1 保留 → 不进候选
```

**重要不变量**:
- L1 永远 append-only,所有 hypothesis 不论命运如何都保留
- 只有 verdict = confirmed 的 hypothesis 有资格进入 DelayedMemoryWriter
- profile.md 的每次变更都有 profile_patch event 作为审计记录,可回溯、可回滚

---

## 10. SSE 事件协议

Chat 接口(`POST /api/chat/stream`)返回 SSE 事件流。Check-in 接口为同步返回(非流式)。

### 10.1 Chat SSE 事件类型

| Event | Payload | 何时发送 |
|---|---|---|
| `context_loaded` | `{ message: string }` | Bundle 装配完成 |
| `hypothesis_generated` | Hypothesis 对象 | 首轮 reasoning 输出 hypothesis 后 |
| `reasoning_step` | `{ content: string }` | 每次 reasoning summary |
| `tool_call_started` | `{ tool_name, arguments }` | 读工具调用开始 |
| `tool_call_finished` | `{ tool_name, status }` | 读工具调用结束 |
| `observation_summary` | `{ content: string }` | 工具结果的可读摘要 |
| `proposal_created` | Proposal 对象 | 写工具被拦截,生成 proposal |
| `final_answer` | `{ content: string }` | 终止,Agent 给出最终回答 |
| `error` | `{ message: string }` | 任何阶段出错 |

### 10.2 事件顺序约束

- `context_loaded` 必须最先发送
- `hypothesis_generated` 必须在 `context_loaded` 之后、首个 `reasoning_step` 之前
- `final_answer` 必须最后发送,且只发送一次
- `proposal_created` 不终止流,可继续 reasoning(但通常 final_answer 紧随其后)
- `tool_call_started` 与对应的 `tool_call_finished` + `observation_summary` 成对出现

### 10.3 Check-in 返回

Check-in 不使用 SSE,直接返回:

```json
POST /api/checkin
{
  "checkin_id": "evt_checkin_01HXYZ...",
  "hypothesis": { ... 完整 Hypothesis 对象 }
}
```

UI 拿到 hypothesis 后将其作为新卡片插入主页堆顶。

---

## 11. 用户可见性策略

### 11.1 用户可见的 events

在"节奏历史"页面中,用户可查看以下事件类型:
- `checkin`
- `hypothesis`(以及关联的 `hypothesis_feedback`)
- `proposal`(以及关联的 `executed_action`)

UI 将这些 events 渲染为可读的时间线,evidence 字段中的 `source_event_id` 全部可点击溯源到原始 event 的 payload。

### 11.2 用户不可见的 events

以下 events 落 L1,但**不在任何用户 UI 中展示**:
- `calendar_snapshot`、`github_snapshot`(原始数据,通过 evidence 溯源时间接可见)
- `evidence_summary`(LLM 摘要,通过 evidence 溯源时间接可见)
- `reasoning_step`、`tool_call`(实现细节)
- `profile_patch`(profile 变更审计,仅用户编辑 .md 时间接看到效果)

### 11.3 用户对 profile.md 的可见性

用户**始终可读可改** profile.md:
- WF 提供"打开 profile.md"的入口(调起系统编辑器或在 WF 内显示)
- 用户编辑 .md 文件后,WF 在下次读取时使用新内容
- WF 通过 DelayedMemoryWriter 写入时使用文件锁,防止冲突

---

## 12. 数据流图(端到端)

### 12.1 场景 A:Check-in 提交

```
用户在主页点 "Check-in" 按钮
   ↓
UI 弹出三问表单
   ↓
用户填写:🌧 小雨 / WeatherFlow / 任务复杂度超预期 / "今天卡在 RAG"
   ↓
POST /api/checkin { weather, project, friction_point, free_text }
   ↓
[后端]
1. event_log.append("checkin", payload) → checkin_id
2. context_loader.load(user_id, checkin_id, mode="checkin") → bundle
3. rhythm_agent.generate_hypothesis(bundle, mode="checkin") → hyp
4. 校验所有 source_event_id 真实性
5. event_log.append("hypothesis", payload=hyp, refs={...}) → hyp_id
6. 异步: delayed_memory_writer.maybe_update(user_id)
   ↓
返回: { checkin_id, hypothesis: {...} }
   ↓
UI 把新 hypothesis 插入主页堆顶,挤掉最旧的(若堆已满)
```

### 12.2 场景 B:定时检查

```
Scheduler 在 12:00 触发
   ↓
[后端]
1. await calendar_mcp.list_events(...) → calendar_data
   event_log.append("calendar_snapshot", payload=calendar_data) → cal_id
2. await github_mcp.get_activity(...) → github_data
   event_log.append("github_snapshot", payload=github_data) → gh_id
3. summary = await llm_summarize(calendar_data, github_data)
   event_log.append("evidence_summary", payload={text: summary},
                    refs={sources: [cal_id, gh_id]}) → summary_id
4. context_loader.load(user_id, summary_id, mode="background") → bundle
5. rhythm_agent.generate_hypothesis(bundle, mode="background") → hyp
6. 校验 source_event_id
7. event_log.append("hypothesis", payload=hyp, refs={...}) → hyp_id
   ↓
用户下次打开 WF 时,主页堆顶已经是这张新 hypothesis
```

### 12.3 场景 C:校准

```
用户在主页大卡点 [不准]
   ↓
POST /api/hypothesis/{hyp_id}/feedback { verdict: "rejected" }
   ↓
[后端]
1. event_log.append("hypothesis_feedback",
                    payload={hypothesis_id: hyp_id, verdict: "rejected"},
                    refs={target: hyp_id}) → feedback_id
2. 异步: delayed_memory_writer.maybe_update(user_id)
   (rejected 不进候选,但写入 L1)
   ↓
返回: { feedback_id, removed_hypothesis_id: hyp_id }
   ↓
UI:
- 把该卡片从堆上移除
- 下面的小卡升级为大卡
- 堆从 3 张变 2 张
- 不主动生成新 hypothesis
```

### 12.4 场景 D:Chat

```
用户在 chat 输入 "帮我看看明天怎么安排"
   ↓
POST /api/chat/stream { message, conversation_id }
   ↓
[后端]
1. event_log.append("chat_turn", payload={role:"user", content}, ...) → turn_id
2. context_loader.load(user_id, turn_id, mode="chat") → bundle
3. SSE: context_loaded
4. rhythm_agent 启动 ReAct loop:
   a. 首轮 reasoning 输出 hypothesis
      → event_log.append("hypothesis", ..., source_tag="chat") → hyp_id
      → SSE: hypothesis_generated
      → (UI 把这张 hyp 插入主页堆,标记为 chat 卡)
   b. 输出 reasoning_step "我先查明天日程"
      → event_log.append("reasoning_step", ...)
      → SSE: reasoning_step
   c. Agent 决定调 calendar.find_free_slots
      → dispatcher: tool.mode == "read"
      → SSE: tool_call_started
      → 调用 MCP,得到 observation
      → event_log.append("tool_call", ...)
      → SSE: tool_call_finished + observation_summary
   d. 输出 reasoning_step "你状态偏 Overload,建议只保护一个 deep work block"
   e. Agent 决定调 calendar.create_focus_block
      → dispatcher: tool.mode == "write"
      → event_log.append("proposal", ...) → proposal_id
      → SSE: proposal_created
   f. 输出 final_answer
      → event_log.append("chat_turn", payload={role:"assistant", ...})
      → SSE: final_answer
5. 异步: delayed_memory_writer.maybe_update(user_id)
```

### 12.5 场景 E:Proposal 执行

```
用户在 chat 中看到 proposal 卡片,点击 "确认"
   ↓
POST /api/actions/{proposal_id}/execute { confirmed: true }
   ↓
[后端]
1. 读取 proposal event,提取 tool_name 和 arguments
2. 调用 MCP write tool: calendar.create_focus_block(...)
3. event_log.append("executed_action",
                    payload={proposal_id, tool_name, result},
                    refs={proposal: proposal_id}) → action_id
4. 异步: delayed_memory_writer.maybe_update(user_id)
   (executed_action 进候选)
   ↓
返回: { action_id, result }
```

---

## 附录 A:关键决策记录

每条决策标注**为什么这么定**,以便未来回看时不需要重新推导。

### A.1 Hypothesis 卡片采用"堆栈 + 校准消除"模型

**决策**:主页最多 3 张卡,新的进堆顶,校准后大卡消失,小卡升级,堆从 3 张变 2 张。

**理由**:
- 主页堆 = "待校准队列",语义清晰
- 校准是 hypothesis 进入长期记忆的唯一通道,这个动作必须显式且有意义
- 卡片堆"自然呼吸"(被校准就少,被触发就多),不需要复杂的过期逻辑
- 用户不会被无限堆积的卡片淹没

### A.2 校准不主动触发新 hypothesis

**决策**:校准只标记 + 移除,不生成替补卡。下一次 T1/T2/T4 触发时自然补充。

**理由**:
- 符合产品宪法第七条(节制的主动)
- 实现极简
- 如果用户校准后想立刻看新判断,可以做一次 check-in
- 避免"用户刚说不准,WF 立刻又给一张可能也不准的卡"的尴尬循环

### A.3 所有 hypothesis 都落 L1,无论校准结果

**决策**:用户校准为 rejected/partial 的 hypothesis 也保留在 L1,只是不进 DelayedMemoryWriter 候选。

**理由**:
- 保持 L1 append-only 不变量
- "不准"的 hypothesis 是高价值反例,未来 evidence 装配时可用
- 系统的可追溯性、可调试性、可重建性依赖 L1 完整
- 长期画像不会被污染——这个目标通过 DelayedMemoryWriter 的 SQL 过滤实现,而非 L1 删除实现

### A.4 LLM 摘要 + 原始 snapshot 并存

**决策**:T2 既保留原始 calendar_snapshot/github_snapshot,又生成 evidence_summary。后续 hypothesis 生成在 Bundle 中**使用摘要,不展开原始数据**;但 evidence 的 source_event_id 可指向原始 snapshot,UI 溯源可一路下钻。

**理由**:
- 摘要省 token,Bundle 更精炼
- 原始数据保溯源,evidence 可信度不打折
- 用户在 UI 上点击 ⓘ 可以看到真实的会议列表、commit 详情,而非 LLM 改写后的语言

### A.5 source_event_id 是硬约束

**决策**:Hypothesis 的 evidence 字段每一项必须挂 `source_event_id`,且该 id 必须在 Bundle 中真实出现。违反则拒绝写入 L1。

**理由**:
- 防止 LLM 编造证据(数字幻觉、时间漂移、原话改写)
- 让"evidence 可溯源"从口头承诺变为强制契约
- UI 点击溯源功能依赖此约束
- 用户校准时可以精准指出"具体哪条 evidence 不对"

### A.6 定时检查固定时刻、不看用户活跃度

**决策**:每 6 小时一次(00:00、06:00、12:00、18:00 本地时区),无论用户是否活跃。

**理由**:
- 固定时刻可预测,便于调试和用户心智模型建立
- 不看活跃度避免"用户回归时主页是 3 天前的判断"的尴尬
- 6 小时频率在 LLM 成本和 evidence 新鲜度之间平衡良好
- 对独立开发者预算友好(一天 4 次 background hypothesis 调用)

### A.7 用户首次使用允许"几乎空 bundle"的 hypothesis

**决策**:第一次 check-in 时即使 bundle 几乎只有 trigger event,也照常生成 hypothesis。

**理由**:
- 避免冷启动门槛阻碍用户首次体验
- 让"L1 第一条 hypothesis"自然产生,后续历史从此开始积累
- 简短卡片本身也是 WF 哲学的体现——不假装比用户更懂用户

### A.8 Chat 中的 hypothesis 进主页堆,但同会话内不重复进

**决策**:同 conversation_id 内只有首轮 hypothesis 进堆;后续轮的 reasoning hypothesis 写 L1,但主页堆查询时按 conversation_id 取最新一张派生。

**理由**:
- 同会话频繁更新主页堆会淹没其他来源
- 但完全不进堆又会让 chat 中的判断"游离于主页之外",违反"单一真实状态视图"原则
- 同会话取最新一张是折中:既反映对话中的状态演化,又不挤掉 check-in 和定时检查的卡

### A.9 Profile.md 章节固定

**决策**:v1 阶段固定 6 个章节(Identity / Active Projects / Rhythm Patterns / Preferences / Anti-patterns / Recent Themes),用户不可增删章节,只可编辑内容。

**理由**:
- DelayedMemoryWriter 的写入逻辑依赖已知章节结构
- 固定章节让 ContextLoader 的 mode-section 映射可枚举、可测试
- 用户对"章节框架"的控制权 v1 阶段不开放,降低复杂度
- v2 阶段可考虑允许用户加章节,但目前不是优先级

---

## 附录 B:文件树建议(供工程实现参考)

```
weatherflow/
├── docs/
│   └── architecture-v1.md          ← 本文档
├── src/
│   ├── orchestrator.py             ← handle_trigger 主入口
│   ├── context_loader.py
│   ├── rhythm_agent/
│   │   ├── agent.py
│   │   ├── prompts/
│   │   │   ├── checkin_mode.md
│   │   │   ├── background_mode.md
│   │   │   └── chat_mode.md
│   │   └── schemas.py
│   ├── event_log/
│   │   ├── store.py
│   │   ├── schema.sql
│   │   └── event_types.py
│   ├── tools/
│   │   ├── registry.py
│   │   ├── dispatcher.py
│   │   ├── calendar_mcp.py
│   │   └── github_mcp.py
│   ├── memory/
│   │   ├── delayed_writer.py
│   │   ├── profile_store.py
│   │   └── rules.py
│   ├── api/
│   │   ├── checkin.py
│   │   ├── chat.py
│   │   ├── feedback.py
│   │   └── actions.py
│   └── scheduler/
│       └── timed_check.py
└── tests/
    └── ...
```

---

## 决策变更记录

| 日期 | 变更 | 原因 |
|---|---|---|
| 2026-05-22 | v1 初版 | 与设计讨论同步建立 |

---

**文档结束**

如需变更任何条款,请先在团队/项目内讨论并取得共识,然后在本文档对应章节修改,并在"决策变更记录"追加 changelog 条目。
