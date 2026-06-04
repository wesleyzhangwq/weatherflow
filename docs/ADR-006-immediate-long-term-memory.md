# ADR-006: Immediate long-term memory (DMW gap → mem0 `infer=True` consolidation)

**日期**: 2026-06-04
**状态**: Accepted
**上下文**: L3 长期画像由 `delayed_writer` (DMW) 的 4 道门槛（24h 冷却 / 14天≥3次 /
conf≥0.6）慢写 `profile.md`。门槛太严 → profile 长期是空的 → 用户体感"用了这么久、
checkin 这么多次，系统根本没在学我"。同时 mem0 只用了 `infer=False`（向量库化），
浪费了它的另一半能力——`infer=True` 的即时事实抽取 + 合并 + 矛盾消解，而这恰好是
L3 现在最缺的"即时沉淀"。

> 本 ADR 在 **不动证据溯源链** 的前提下，新增一个"快写画像层(L3-fast)"。

## 核心约束（为什么不能简单地给 projector 开 infer=True）

`criticize_node` 校验 `hypothesis.evidence[].source_event_id ∈ bundle_event_ids`，
而 `bundle_event_ids = {e.event_id for e in bundle.entries}`。`infer=True` 会
MERGE/改写记忆 → 单一 `source_event_id` 退化为"最后贡献者" → 拿它当证据溯源会被
critic 拒、破坏 FIV 不变量。**所以两类记忆必须物理隔离，落进 bundle 的不同区。**

## 决策

### D1. 两个 mem0 collection，两种用途
| collection | 引擎 | 喂给 | 溯源 |
|---|---|---|---|
| `weatherflow_memories`（现状不变） | `infer=False` | `bundle.entries[]`（证据） | 每条带真实 `source_event_id`，critic 校验 |
| `weatherflow_profile`（新） | `infer=True` | `bundle.live_insights`（画像） | 无单一来源（合成特质），**不进 entries，不被 critic 校验** |

### D2. 按事件类型分级 infer（不按入口、不穿透 router）
决策放在投影/合并模块内部，不给 router 加参数：
- **L3-fast 合并（`infer=True`）**：`chat_turn`(含偏好) · confirmed `hypothesis` ·
  `hypothesis_feedback`(confirm/reject)
- **永远 `infer=False`**：`checkin` · `executed_action` · scheduled 数据——结构化字段
  不交给 LLM "翻译"，避免精度丢失（如枚举被改写成模糊自然语言）。

### D3. confirm/reject 作为信号，不是按 id 删
被 reject 的 hypothesis 本就没进过 episodic mem0（projector 只投 confirmed）。所以
feedback 不做 `delete(id)`，而是把 confirm（佐证句）/ reject（反证句）喂进 L3-fast，
让 mem0 自己强化或下调——矛盾消解是 `infer=True` 的正常工作。

### D4. L3-fast 进 `bundle.live_insights`（新字段），不进 `entries[]`
`EvidenceBundle` 新增 `live_insights: list[str]`；`render()` 作为"Live Insights"
背景块输出。它不参与 `all_event_ids()` → critic 天然不校验它。

### D5. 职责定死（已拍板 2026-06-04）：profile.md 人机共管，DMW 维持保守，即时性归快写层
两层各司其职，不是替代关系：
- **profile.md（L3-slow）= 人机共管的正式档案**：机器（DMW）谨慎写、**用户可人工编辑**。
  正因为要保留人工编辑通道，DMW **必须维持保守**——频繁机器写会踩掉用户的编辑。
  所以 **DMW 的 4 道门槛维持不变**（白名单 / 24h 冷却 / 14天≥3次 / conf≥0.6），不放宽。
- **mem0 L3-fast = 草稿本/即时印象**：扛"即时性"这件事，补 DMW 的空窗期。

推论：**"放宽 DMW"和"profile.md 纯渲染视图"两条路都关闭**——immediacy 交给快写层，
profile.md 保持慢而稳、且人工可编辑（不会被机器全量覆盖）。

### D6. DMW 门槛维持现状（不放宽）
`dmw_section_cooldown_hours=24` / `dmw_pattern_window_days=14` /
`dmw_pattern_min_count=3` / `dmw_min_confidence=0.6` 全部保持不变。profile.md 只收
"已反复验证的稳定画像"，它的"慢"是特性不是缺陷。

## 不变量
1. 证据流（`bundle.entries[]` + episodic mem0）保持 `infer=False` + `source_event_id`
   溯源 + critic 校验——**零改动、零风险**。
2. 画像流（L3-fast）只进 `bundle.live_insights` / `profile_sections`，**永不进 entries**。
3. checkin/scheduled/executed_action 永远 `infer=False`。
4. 两类记忆在两个 collection，物理隔离，互不污染；都可从 L1 重建（`rebuild_memory.py`
   需扩展为重建两层）。
5. L3-fast 受 `PROFILE_CONSOLIDATION_ENABLED` 门控，可灰度/回退；失败不影响主链。

## 改动清单（最小、不动架构）
- `config.py`: `QDRANT_PROFILE_COLLECTION`、`PROFILE_CONSOLIDATION_ENABLED`
- `mem0_config.py`: `build_mem0_config(settings, *, collection=None)`
- **新** `semantic/consolidator.py`: `infer=True` 合并进 profile collection
- `semantic/recall.py`: `recall_profile(query)`
- `schemas.py`: `EvidenceBundle.live_insights` + render
- `context_loader.py`: profile 召回 → `live_insights`（不进 entries）
- `derivations.py`: `run_derivations` 加 `_consolidate` 支（带游标）

## 后果与取舍
- **获得**：长期画像即时变厚、能自我纠正矛盾，profile 不再"死"。
- **成本**：`infer=True` 每次多一次 LLM 调用（仅限 chat/确认/反馈，量可控）；加 fact 计数监控。
- **不做**：不引 Letta/Zep；不动 projector/critic；**不放宽 DMW**（D6）；**不做 profile.md
  纯渲染视图**——保留人工编辑通道（D5）；不全量开 infer。
- **已无未决**：profile.md 人机共管 + DMW 维持保守 + 即时性归快写层，三者一起收敛（D5/D6）。
