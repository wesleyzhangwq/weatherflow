"""Assemble hybrid memory context for LLM synthesis (read path)."""

from __future__ import annotations

import json
import logging

from app.config import get_settings
from app.core.llm import LLMClient
from app.memory import events_repo, midterm_md
from app.memory.long_term_vector import get_long_term_store
from app.memory.session_buffer import recent as buffer_recent

logger = logging.getLogger(__name__)


async def gather_memory_context(
    llm: LLMClient,
    *,
    query_text: str,
    session_id: str = "default",
    sqlite_event_limit: int = 40,
    buffer_limit: int = 24,
    vector_top_k: int = 6,
) -> str:
    """Return a single markdown bundle: short-term + mid-term + long-term."""
    settings = get_settings()
    lines: list[str] = ["## Memory context (hybrid)", ""]

    buf = buffer_recent(session_id, limit=buffer_limit)
    if buf:
        lines.append("### Session buffer (recent)")
        for item in buf:
            t = item.get("type", "?")
            c = str(item.get("content", ""))[:400]
            lines.append(f"- **{t}**: {c}")
        lines.append("")

    evs = events_repo.recent(limit=sqlite_event_limit, session_id=session_id)
    fb_only = [e for e in evs if e.type == "suggestion_feedback"][:10]
    if fb_only:
        lines.append("### Recent user feedback on suggestions")
        for e in fb_only:
            snippet = e.content[:400]
            try:
                data = json.loads(e.content)
                snippet = json.dumps(data, ensure_ascii=False)[:400]
            except json.JSONDecodeError:
                pass
            lines.append(f"- `{e.timestamp}` {snippet}")
        lines.append("")
    if evs:
        lines.append("### Recent SQLite events")
        for e in evs[:sqlite_event_limit]:
            lines.append(
                f"- `{e.timestamp}` **{e.type}**: {e.content[:320]}"
            )
        lines.append("")

    mid = midterm_md.read_profile_snippets(max_chars=3500)
    if mid.strip():
        lines.append("### Mid-term profiles (excerpt)")
        lines.append(mid)
        lines.append("")

    daily = midterm_md.read_daily_markdown(max_chars=2500)
    if daily.strip():
        lines.append("### Today's daily note (excerpt)")
        lines.append(daily)
        lines.append("")

    qt = (query_text or "").strip() or "user growth patterns habits emotions"
    try:
        vecs = await llm.embed([qt])
        emb = vecs[0] if vecs else None
    except Exception:
        logger.exception("memory context embedding failed; vector retrieval skipped")
        emb = None

    if emb:
        try:
            hits = get_long_term_store(settings).search(emb, top_k=vector_top_k)
            if hits:
                lines.append("### Long-term patterns (vector retrieval)")
                for h in hits:
                    lines.append(f"- ({h.score:.2f}) {h.content}")
                lines.append("")
        except Exception:
            logger.exception("long-term vector retrieval failed")

    return "\n".join(lines).strip()


__all__ = ["gather_memory_context"]
