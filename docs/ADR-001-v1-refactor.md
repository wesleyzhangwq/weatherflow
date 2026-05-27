# ADR-001: WF v1 重构关键决策记录

**日期**: 2026-05-26
**状态**: Accepted
**上下文**: 按 [weatherflow-architecture-v1.md](../weatherflow-architecture-v1.md) 完整重构 WeatherFlow，丢弃所有不在 v1 范围内的旧实现。

本文档记录文档未明确、需要工程判断的所有关键决策，便于未来回溯。

---

## D1. ULID vs UUID

**决策**：使用 ULID（`python-ulid`）作为 L1 event id。
**理由**：
- 文档第 4.1 节示例用 `evt_calendar_snapshot_01HXYZ...` 格式，明显是 ULID
- ULID 按时间排序天然递增，调试和按时间查询都更直观
- 26 字符 base32，比 UUID 短，readable
**备选已弃用**：UUID4（随机性更强但无序）

---

## D2. event id 格式

**决策**：event id = `evt_{type}_{ulid}`，例如 `evt_hypothesis_01HXYZABC123...`。
**理由**：
- 完全对齐文档示例字面值
- 一眼能看出 event 类型，溯源调试更快
- type 段从 enum 取值，不会被注入

---

## D3. Hypothesis Agent 使用的 LLM 模型

**决策**：复用现有 `OpenAICompatibleClient`，默认走 `CHAT_MODEL`（环境变量）；不再为每个 agent 分别配置（移除现有 `chat_model_state/reflection/planning/memory`）。
**理由**：
- 文档没指定模型，由用户用 env 控制
- v1 没有不同 agent 角色，只有一个 RhythmAgent
- 简化配置面

---

## D4. Hypothesis source_event_id 校验失败的恢复策略

**决策**：最多重试 1 次，仍失败则**降级**——保留 LLM 输出但把不合法 evidence 抹掉，至少留 trigger event 作为 evidence。
**理由**：
- 文档第 4.3/5.1 节说"拒绝写入，触发 Agent 重生成或降级"，留有空间
- 单次重试可处理临时性 LLM 漂移
- 降级时永远有 trigger event 兜底，UI 不会显示一张空 evidence 的卡
- 若完全失败（连降级版都无法构造），写入 `hypothesis_generation_error` event 但不抛给前端

---

## D5. conversation_id 谁分配

**决策**：前端生成 ULID（首次进入 chat 页时）；后端只信任并使用，不做校验。
**理由**：
- 让前端控制"新会话/续会话"语义
- 与文档第 5.5 节"同一 conversation_id 内首轮 vs 后续轮"的判断完全一致
- 简单

---

## D6. Profile.md 初始模板

**决策**：初始模板包含全部 6 个章节，每个章节用中文默认提示填充（见 `app/memory/profile_md.py::INITIAL_TEMPLATE`）。
**理由**：
- 文档第 4.4 节明确章节固定且不可增删
- 中文提示让用户能直接编辑
- 默认提示明确写"由 WeatherFlow 自动维护，可手动编辑"

模板见 §A 附录。

---

## D7. DelayedMemoryWriter LLM 摘要 prompt 形态

**决策**：单次 chat completion，要求返回 JSON：`{ "diff": "...", "confidence": 0.0~1.0 }`。
**理由**：
- 简单直接
- confidence 字段直接对应文档第 9.2 节"信心检查 >0.6"
- diff 用 markdown 增量片段（不是 unified diff，太复杂），由 profile_store 用 string append/replace 应用

---

## D8. SSE error 事件后的状态恢复

**决策**：
- 一旦发送 `error` event 立即 close stream
- 已写入 L1 的部分（chat_turn / reasoning_step / tool_call）保留（append-only 不变量）
- 不发送 `final_answer`
- 前端检测到 error 后允许用户重新发送（同一 conversation_id）

**理由**：
- L1 完整性优先于"清理 partial state"
- 重新发送会自然装配新 bundle，包含之前未完成的 turn，agent 可参考

---

## D9. Proposal 24 小时过期的实现

**决策**：**查询时懒标记**。任何 GET proposal/list proposal 接口在返回前扫一遍 pending 且 created_at < now-24h 的 proposal，写入 `proposal_expired` event。
**理由**：
- 不增加调度器 job
- 准确性足够（不需要精确到秒）
- 与 L1 append-only 一致——不修改原 proposal，写新 event

---

## D10. Provider Mode：只保留 MCP

**决策**：删除 `direct`/`dual` provider mode，**只保留 MCP**。删除 `github_direct.py`、`google_calendar_direct.py`、`provider_registry.py`。
**理由**：
- 文档第 7.2/7.3 节工具清单**完全用 MCP 命名**（`calendar.find_free_slots` 等）
- direct mode 是旧架构遗物，新架构没有依据
- 减少 50% 的 provider 代码

---

## D11. 单用户模型

**决策**：v1 写死单用户。`user_id` 固定为 `"default"`，不在 API 暴露，不在前端选择。
**理由**：
- 文档 schema 写了 `user_id` 但全文用单数"用户"
- 简化所有路由签名
- 多用户留给 v2

---

## D12. 旧表数据迁移

**决策**：**推倒重建**。删除 `weatherflow.db`，从空 events 表开始。
**理由**：
- 开发期数据无生产价值
- 旧 schema 与新 schema 几乎无重叠（checkins/reflections/state_snapshots 全部不存在于新 schema）
- 写迁移脚本的工作量远大于数据价值

---

## D13. Hypothesis label 词表硬编码

**决策**：`Flow / Recovery / Steady / Overload / Blocked / Fragmented` 作为 `Literal` 写在 schemas.py 中。LLM 输出必须命中其一，否则视为 invalid hypothesis 触发重试/降级。
**理由**：
- 文档第 4.2 节明确"v1 固定"
- pydantic Literal 自带校验
- 后续扩展只需改一处

---

## D14. evidence_summary 在 Bundle 中的展开规则

**决策**：默认 Bundle 中**用 evidence_summary 的 text 字段代替 raw snapshot**；但 bundle 同时把 raw snapshot 的 event_id **列出来不展开内容**（仅保留 `[evt_calendar_snapshot_xxx] (referenced via summary above)` 占位行），允许 LLM 直接引用原始 snapshot id。
**理由**：
- 完全对齐文档第 8.3 节"摘要省 token，原始数据保溯源"
- LLM 可以选择 source_event_id 指向 summary 或 raw（更可信指向 raw）
- 校验时 raw snapshot 的 id 也在 bundle.all_event_ids 中

---

## D15. 主页堆查询的 SQL 派生规则

**决策**：主页堆 = 最多 3 张 status=active 的 hypothesis。`status` 是**计算属性**而非存储字段。派生规则：

```
status = 'rejected'  if exists feedback with verdict='rejected' for this hyp_id
       = 'partial'   if exists feedback with verdict='partial'
       = 'confirmed' if exists feedback with verdict='confirmed'
       = 'expired'   if this hyp 不是最近 3 张 active 之一
       = 'active'    otherwise
```

主页堆按 `source_tag='chat'` 时**取同 conversation_id 内最新一张**，其他 source_tag 取最新 N 张，按时间倒序取前 3。

**理由**：
- 保持 L1 append-only 不变量（不修改 hypothesis event）
- 文档第 5.5 节"按 conversation_id 取最新一张派生 UI 状态"明确要求
- 可调试：任何时刻可从 L1 重建主页状态

---

## D16. DelayedMemoryWriter "重复阈值" 判定方式

**决策**：仅对 Rhythm Patterns / Anti-patterns 章节适用。判定逻辑：
- 收集最近 14 天所有 verdict=confirmed 的 hypothesis
- 按 `label` 字段计数
- 同 label 出现 >=3 次才触发 patch

**理由**：
- 文档第 9.2 节"某个模式必须在过去 14 天内至少出现 3 次"
- 用 label 作为"模式"代理是最直接的离散化
- Preferences/Active Projects 没有此阈值，按 D7 的 confidence 检查即可

---

## D17. Profile.md 文件锁

**决策**：使用 `fcntl.flock`（Unix）做 LOCK_EX 文件锁；Windows 不支持但 v1 只目标 macOS/Linux。
**理由**：
- 文档第 4.4 节明确要"写入时使用文件锁，防止冲突"
- fcntl 是 stdlib，无新依赖
- DelayedMemoryWriter 与用户手动编辑可能并发

---

## D18. Tool Registry 重构方式

**决策**：删除现有 `MCPToolRegistry`（基于 per-agent permission + rate limit）。新写 `ToolRegistry`，结构：

```python
@dataclass
class Tool:
    name: str
    mode: Literal["read", "write", "destructive"]
    description: str
    schema: dict
    run: Callable
```

destructive 工具**完全不注册**（不出现在 registry 中），Agent 通过 `list_tools()` 看不到。
**理由**：
- 现有 registry 设计是为多 agent 设计，v1 只有 RhythmAgent，过度工程
- 文档第 7.1 节明确"destructive 默认从工具列表中过滤掉，Agent 看不到这些工具的 schema"，最干净的实现就是不注册

---

## D19. Tool Dispatcher 设计

**决策**：单独 `dispatcher.py`，签名 `async dispatch(tool_name, arguments, *, conversation_id, parent_event_id) -> DispatchResult`。

DispatchResult 是 sum type：
- `ObservationResult(content)` — read tool 成功
- `ProposalResult(proposal_id)` — write tool 被拦截
- `ErrorResult(message)` — 调用失败

**理由**：
- 让 ReAct loop 用模式匹配处理 dispatch 结果
- conversation_id + parent_event_id 让所有衍生 event 都能溯源到当前 chat turn

---

## D20. RhythmAgent 实现策略

**决策**：使用 OpenAI function-calling 协议（`tools` + `tool_choice`）实现 ReAct loop。每轮：
1. 把可用工具 schema 注入 `tools` 字段
2. LLM 返回 message + 可选 tool_calls
3. 若 tool_calls 非空：dispatch → 把 observation 作为 tool message 追加 → 下一轮
4. 若无 tool_calls：作为 final_answer 终止

最大轮数：8（避免死循环）。

**理由**：
- function calling 是 LLM 原生协议，比手写 prompt parse 稳定
- OpenAI 兼容 API 都支持
- 8 轮上限对应"3 次读 + 1 次 proposal + 1 次 final"的常见场景，留 3 轮缓冲

---

## D21. Hypothesis 生成与 ReAct 分离

**决策**：在 Chat 流程里，**首轮 hypothesis 生成是独立的一次 LLM 调用**（mode="chat"），不参与 ReAct loop；hypothesis 生成完后才进入 ReAct loop（hypothesis 作为 system 消息的一部分注入）。

**理由**：
- Hypothesis 输出有严格 schema（source_event_id 校验等），与 function calling 的输出格式不一致
- 分离后更易测试和重试
- 文档第 12.4 节流程清晰：先 hypothesis，再 reasoning + tools，最后 final_answer

---

## D22. 测试策略

**决策**：所有旧测试删除。新测试按 v1 文档章节组织：
- `tests/contracts/` — schema 校验、source_event_id 硬约束、label 词表
- `tests/flows/` — T1/T2/T3/T4 端到端
- `tests/memory/` — DelayedMemoryWriter 4 道门槛
- `tests/tools/` — Proposal 拦截、destructive 过滤

**理由**：
- 旧测试覆盖的功能已删除
- 按宪法/章节组织让测试映射文档

---

## §A 附录：Profile.md 初始模板

```markdown
# Identity

_由用户手动维护。描述你的身份、长期目标、自我认知。_

> 例：独立开发者，聚焦 LLM/Agent/RAG 方向。

# Active Projects

_当前活跃项目列表，作为 check-in 项目选项的来源。_
_由用户手动 + GitHub 自动识别 + DelayedMemoryWriter 共同维护。_

# Rhythm Patterns

_由 DelayedMemoryWriter 维护，记录已被验证的节奏规律。_
_用户也可以手动编辑、增删条目。_

# Preferences

_由 DelayedMemoryWriter 从 Chat 中识别，记录工具/时间/工作方式偏好。_

# Anti-patterns

_由 DelayedMemoryWriter 维护，记录历史上反复证明不适合你的模式。_

# Recent Themes

_由 DelayedMemoryWriter 自动维护的滚动主题（最近 N 周）。_
```

---

## §B 附录：决策汇总速查表

| ID | 主题 | 决策 |
|---|---|---|
| D1 | event id 类型 | ULID |
| D2 | event id 格式 | `evt_{type}_{ulid}` |
| D3 | LLM 模型 | 单一 CHAT_MODEL，删 per-agent 配置 |
| D4 | source 校验失败 | 1 次重试后降级到 trigger-only evidence |
| D5 | conversation_id | 前端生成 |
| D6 | profile.md 模板 | 6 章节中文默认提示 |
| D7 | DMW prompt 输出 | JSON: `{diff, confidence}` |
| D8 | SSE error 恢复 | 立即关流，保留 L1 partial |
| D9 | proposal expired | 查询时懒标记 |
| D10 | provider mode | 只保留 MCP |
| D11 | 用户模型 | 单用户 `"default"` |
| D12 | 数据迁移 | 推倒重建 |
| D13 | label 词表 | Literal 硬编码 |
| D14 | summary 与 raw 并存 | summary 全文 + raw id 占位 |
| D15 | 卡片堆派生 | 计算属性，从 feedback 派生 |
| D16 | 重复阈值 | 按 label 计数 |
| D17 | profile 文件锁 | fcntl.flock |
| D18 | tool registry | mode 三态，destructive 不注册 |
| D19 | dispatcher 返回 | Observation/Proposal/Error sum type |
| D20 | RhythmAgent ReAct | function calling, 最大 8 轮 |
| D21 | hypothesis 独立调用 | hypothesis 不参与 function calling |
| D22 | 测试组织 | 按 v1 文档章节分目录 |

---

## 决策变更记录

| 日期 | 变更 | 原因 |
|---|---|---|
| 2026-05-26 | v1 初版 | 与 weatherflow-architecture-v1.md 同步建立 |
