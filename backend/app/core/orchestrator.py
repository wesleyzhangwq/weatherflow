"""generate_hypothesis() — unified entry point for T1/T2/T4 hypothesis flows.

Per architecture-v1.md §5.1, all three triggers (check-in, scheduled, chat)
share one code path:

    trigger event → ContextLoader → RhythmAgent → validate → append to L1

The four-trigger differences live elsewhere (the API handlers, the scheduler),
not here. This function is the *single* place where a hypothesis is born.
"""

from __future__ import annotations

import logging
from typing import Optional

from app.agents.rhythm_agent import RhythmAgent
from app.core.llm import LLMClient
from app.memory import context_loader, event_log
from app.memory.context_loader import Mode
from app.memory.schemas import HypothesisPayload

logger = logging.getLogger(__name__)


async def generate_hypothesis(
    *,
    trigger_event_id: str,
    mode: Mode,
    llm: LLMClient,
    user_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
) -> tuple[str, HypothesisPayload]:
    """Generate, validate, and persist a Hypothesis. Returns (hyp_id, payload).

    Caller is responsible for triggering DelayedMemoryWriter asynchronously
    when appropriate (T1/T3/T4 — see §9.2).
    """
    bundle = await context_loader.load(
        trigger_event_id=trigger_event_id,
        mode=mode,
        user_id=user_id,
    )

    agent = RhythmAgent(llm)
    payload = await agent.generate(
        bundle=bundle,
        mode=mode,
        conversation_id=conversation_id,
    )

    evidence_sources = [e.source_event_id for e in payload.evidence]
    hyp_id = event_log.append(
        type="hypothesis",
        payload=payload.model_dump(),
        user_id=user_id,
        refs={
            "triggered_by": trigger_event_id,
            "evidence_sources": evidence_sources,
        },
    )
    logger.info(
        "Hypothesis generated: id=%s label=%s confidence=%.2f mode=%s",
        hyp_id, payload.label, payload.confidence, mode,
    )
    return hyp_id, payload


__all__ = ["generate_hypothesis"]
