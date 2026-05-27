# ADR-002: 天气 ↔ Label 1:1 语义映射

**日期**: 2026-05-27
**状态**: Accepted
**上下文**: ADR-001 D13 把 label 词表硬编码为 6 个；用户初始的 weather 列表是
5 个（与 D13 不平衡）。本 ADR 调整 weather 列表为 6 个，并建立 1:1 默认映射。

---

## 决策

把 `Weather` 字面量改为 6 个，与 `HypothesisLabel` 一一对应：

| 天气 (`Weather`) | 用户语义 | 默认 label (`HypothesisLabel`) | label 中文 |
|---|---|---|---|
| `sunny` ☀ 晴天 | 清醒高效 · 思路清楚行动顺畅 | `Flow` | 心流高产 |
| `partly_cloudy` ⛅ 多云 | 能工作但不锋利 · 容易分心 | `Steady` | 平稳推进 |
| `cloudy` ☁ 阴天 | 低能量拖延 · 脑子沉启动难 | `Recovery` | 恢复模式 |
| `rainy` 🌧 小雨 | 情绪干扰中 · 焦虑烦躁内耗 | `Overload` | 过载 |
| `thunderstorm` ⛈ 雷暴 | 混乱过载 · 任务失控 | `Blocked` | 卡住 |
| `foggy` 🌫 大雾 | 思路碎片化 · 难以专注 | `Fragmented` | 碎片化 |

---

## 关键原则

**1:1 映射是「默认建议」，不是强制规则。**

LLM 在 RhythmAgent 中拿到这张表，在 evidence 不冲突时按映射输出；evidence
强烈冲突时**可以打破映射**，并在 `summary` 字段中说明理由。

举例：
- 用户点了 `sunny`（自我感觉良好）
- 但 calendar 显示今天 8 场会议、github 在 5 个 repo 来回切、check-in
  friction 选了 `context_switch`
- → 系统可能仍判 `Fragmented`，summary 写「自评晴天但日历密度
  + 多 repo 切换更接近碎片化模式」

这维护了产品宪法第 6 条「不假装比你更懂你」**双向**：
- 用户自评不会被系统悄悄改写
- 但系统也不会盲从用户自评——evidence 驱动

---

## 与文档原 §4.2 的关系

文档 §4.2 原文：
> 对应 check-in 五种天气，但 label 集合略大于天气集合，因为 hypothesis
> 综合了多源 evidence

本 ADR 把这条收紧为 1:1，但保留了「evidence 可以打破映射」的核心精神。

**为什么不保持 5 vs 6**：用户希望每个天气都有清楚的语义对应。1:1 让 UI
解释更直观（每个天气下都能写一句固定的描述）。失去的「label 比 weather
丰富」的属性其实是冗余的——LLM 永远可以基于 evidence 派生更复杂的判断
（比如 confidence 高低 + counter_evidence），不一定需要更多 label 维度。

---

## 实现位置

| 位置 | 改动 |
|---|---|
| `backend/app/memory/schemas.py` | `Weather` 字面量从 5 项扩到 6 项（去 `foggy` 留 + 加 `thunderstorm`） |
| `backend/app/agents/rhythm_agent.py` | system prompt 中嵌入映射表 |
| `frontend/lib/labels.ts` | `WEATHER_TEXT` / `WEATHER_SEMANTIC` / `WEATHER_DEFAULT_LABEL`；`LABEL_TEXT` 全改为中文短语 |
| `frontend/app/checkin/page.tsx` | grid 从 5 列变 3-6 响应式；选中天气下方显示语义说明 |

---

## 向后兼容

- 历史 L1 `checkin` event 中的 `weather` 仍可为 `sunny/partly_cloudy/cloudy/rainy/foggy`
  （没有 `thunderstorm`）—— 完全兼容，Literal 接受所有 6 种
- 历史 `hypothesis` event 的 `label` 集合未变，完全兼容
- 新 check-in 可以使用 `thunderstorm`

---

## 决策变更记录

| 日期 | 变更 | 原因 |
|---|---|---|
| 2026-05-27 | v1 初版 | 用户审批的天气-label 1:1 语义映射 |
