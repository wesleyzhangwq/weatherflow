"""RhythmAgent — generates Hypothesis objects given an EvidenceBundle.

This module owns the Hypothesis-generation half of the system. The ReAct loop
(Chat flow, T4) lives in ``app.agents.chat_agent`` and treats the Hypothesis
produced here as fixed input.

See architecture-v1.md §4.2 / §4.3 / §5.1 / §5.5 for the hard contracts:
- Every evidence item MUST carry a `source_event_id` that exists in the bundle
- Label MUST be one of six fixed values
- Confidence MUST be in [0, 1]

ADR D4 sets the retry/fallback strategy: try once, retry once with a stricter
prompt, then degrade to a trigger-only hypothesis rather than raise.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from pydantic import ValidationError

from app.config import get_settings
from app.core.llm import LLMClient, chat_json
from app.memory.schemas import (
    EvidenceBundle,
    EvidenceItem,
    HypothesisLabel,
    HypothesisPayload,
    SourceTag,
)

logger = logging.getLogger(__name__)


_LABEL_HINT = (
    "Label MUST be one of: Flow, Recovery, Steady, Overload, Blocked, Fragmented."
)


_SYSTEM_PROMPT = """你是 WeatherFlow 的节奏教练 (RhythmAgent)。你的任务：基于下面的 Evidence Bundle，对用户当前的工作节奏给出一个 Hypothesis 判断。

**天气 → label 默认映射**（用户在 check-in 中的天气选择给出主观信号；下面是合理的默认对应。若 evidence 与此强烈冲突，可以打破映射并在 summary 中说明理由）：
  · 晴天 sunny       → Flow         (心流高产，思路清楚)
  · 多云 partly_cloudy → Steady       (平稳推进，但不锋利)
  · 阴天 cloudy      → Recovery     (低能量拖延，适合恢复型任务)
  · 小雨 rainy       → Overload     (情绪干扰 + 任务压力)
  · 雷暴 thunderstorm → Blocked      (混乱过载，难以推进)
  · 大雾 foggy       → Fragmented   (碎片化注意力，难以专注)


**硬约束**（违反则你的输出将被拒绝）：
1. evidence 数组的每一项 **必须** 包含 `source_event_id`，且必须从 Bundle 中给出的 `[evt_xxx]` id 原样抄写。不要编造、不要省略前缀、不要缩写。
2. counter_evidence 同样必须带 `source_event_id`。
3. label 必须是固定的六个标签之一：Flow / Recovery / Steady / Overload / Blocked / Fragmented。
4. confidence ∈ [0.0, 1.0]，越自信越接近 1。
5. evidence 不得为空。如果只有 trigger event 可用，至少把 trigger event 列为一条 evidence。
6. summary 是一句中文短句（不超过 30 字），直接说出你的判断。
7. missing_evidence 是纯文本（描述你认为还缺什么信息），不需要 source_event_id。

**输出 schema (JSON)**：
{
  "label": "Steady",
  "confidence": 0.62,
  "summary": "...",
  "evidence": [{"text": "...", "source_event_id": "evt_xxx_..."}],
  "counter_evidence": [{"text": "...", "source_event_id": "evt_xxx_..."}],
  "missing_evidence": ["..."]
}

请直接输出 JSON，不要包裹 ```json``` 代码块。
"""


_MODE_TO_SOURCE_TAG: dict[str, SourceTag] = {
    "checkin": "checkin",
    "background": "scheduled",
    "chat": "chat",
    "recalibrate": "recalibrate",
}


class HypothesisGenerationError(Exception):
    """Raised after exhausting retries and the fallback path."""


class RhythmAgent:
    """Stateless wrapper around an LLM call that produces a HypothesisPayload."""

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    async def generate(
        self,
        *,
        bundle: EvidenceBundle,
        mode: str,
        conversation_id: Optional[str] = None,
    ) -> HypothesisPayload:
        """Two attempts, then fallback. See ADR D4."""
        source_tag = _MODE_TO_SOURCE_TAG.get(mode, "checkin")

        for attempt in (1, 2):
            try:
                raw = await self._call(bundle, attempt=attempt)
                payload = self._parse(raw, bundle, source_tag, conversation_id)
                return payload
            except (ValidationError, ValueError, json.JSONDecodeError) as exc:
                logger.warning(
                    "RhythmAgent attempt %d failed: %s", attempt, exc
                )
                continue

        # Fallback: trigger-only evidence (ADR D4)
        logger.warning("RhythmAgent degrading to trigger-only fallback")
        return self._fallback(bundle, source_tag, conversation_id)

    async def _call(self, bundle: EvidenceBundle, *, attempt: int) -> dict:
        settings = get_settings()
        user_prompt = bundle.render()
        if attempt > 1:
            user_prompt += (
                "\n\n[REMINDER] 上一次输出有问题（source_event_id 不在 bundle 中，或 label 不合法）。"
                "请严格按 schema 输出，source_event_id 必须从 bundle 中的 [evt_xxx] 原样抄。"
            )
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT + "\n" + _LABEL_HINT},
            {"role": "user", "content": user_prompt},
        ]
        # Reasoning models (MiniMax-M2.7, DeepSeek-R1, etc.) burn many tokens
        # on <think> blocks. 800 was too tight — the JSON at the tail got
        # truncated ("Unterminated string"). 4000 leaves room for ~2-3k
        # tokens of reasoning + the actual JSON. chat_json() will strip the
        # think block before parsing.
        raw = await chat_json(
            self._llm,
            messages,
            temperature=settings.chat_temperature,
            max_tokens=4000,
        )
        if not isinstance(raw, dict):
            raise ValueError("Hypothesis JSON root must be an object")
        return raw

    def _parse(
        self,
        raw: dict,
        bundle: EvidenceBundle,
        source_tag: SourceTag,
        conversation_id: Optional[str],
    ) -> HypothesisPayload:
        raw["source_tag"] = source_tag
        if conversation_id:
            raw["conversation_id"] = conversation_id
        # Pydantic does the heavy lifting on shape + label enum + confidence range.
        candidate = HypothesisPayload.model_validate(raw)
        # Now enforce the architecture-v1.md §4.3 hard invariant: every
        # source_event_id MUST exist in the bundle.
        valid_ids = bundle.all_event_ids()
        bad = [
            e.source_event_id
            for e in [*candidate.evidence, *candidate.counter_evidence]
            if e.source_event_id not in valid_ids
        ]
        if bad:
            raise ValueError(
                f"Hypothesis referenced unknown source_event_id(s): {bad}"
            )
        return candidate

    def _fallback(
        self,
        bundle: EvidenceBundle,
        source_tag: SourceTag,
        conversation_id: Optional[str],
    ) -> HypothesisPayload:
        trigger = next(
            (e for e in bundle.entries if e.event_id == bundle.trigger_event_id),
            None,
        )
        if trigger is None:
            # truly empty bundle — should not happen, but make it explicit
            raise HypothesisGenerationError("bundle has no trigger entry")
        return HypothesisPayload(
            label="Steady",
            confidence=0.3,
            summary="信号不足，暂作平稳推进。",
            evidence=[
                EvidenceItem(
                    text=f"基于 {trigger.event_type} 事件的初步判断",
                    source_event_id=trigger.event_id,
                )
            ],
            counter_evidence=[],
            missing_evidence=["更多 evidence；下次定时检查或 check-in 后将重新评估"],
            source_tag=source_tag,
            conversation_id=conversation_id,
        )


__all__ = ["RhythmAgent", "HypothesisGenerationError", "HypothesisLabel"]
