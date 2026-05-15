"""Memory feedback writes to events and feeds later memory passes."""

from __future__ import annotations

import json

import pytest

from app.agents.memory_agent import MemoryAgent
from app.memory import events_repo, profile_md
from app.memory.schemas import CheckinRecord, ReflectionRecord
from app.routers.feedback import MemoryFeedbackIn, memory_feedback


pytestmark = pytest.mark.asyncio


async def test_memory_feedback_writes_event() -> None:
    await memory_feedback(
        MemoryFeedbackIn(
            semantic_key="focus_style",
            feedback_type="inaccurate",
            semantic_value_snapshot="总是在上午更专注",
            session_id="test-session",
        )
    )

    events = events_repo.recent(limit=5, session_id="test-session")
    assert len(events) == 1
    event = events[0]
    assert event.type == "memory_feedback"
    assert event.tags == ["memory", "inaccurate"]
    assert event.session_id == "test-session"

    payload = json.loads(event.content)
    assert payload["semantic_key"] == "focus_style"
    assert payload["feedback_type"] == "inaccurate"
    assert payload["semantic_value_snapshot"] == "总是在上午更专注"
    assert payload["created_at"] == event.timestamp


async def test_memory_agent_profile_refresh_includes_memory_feedback(fake_llm) -> None:
    await memory_feedback(
        MemoryFeedbackIn(
            semantic_key="focus_style",
            feedback_type="stale",
            semantic_value_snapshot="以前晚上效率更高",
        )
    )
    fake_llm.queue_chat(
        json.dumps(
            {
                "user_profile": "你正在更新一条过期画像。",
                "behavior_patterns": "- 反馈会进入画像刷新。",
                "goals": "- 不保留过期判断。",
            }
        )
    )

    agent = MemoryAgent(fake_llm)
    await agent.refresh_profile(
        checkin=CheckinRecord(
            id=1,
            date="2026-05-13",
            created_at="2026-05-13T00:00:00Z",
            status="steady",
            did_today="整理了项目",
            stuck_on=None,
            anxiety=None,
            raw=None,
            session_id="default",
        ),
        reflection=ReflectionRecord(
            id=1,
            date="2026-05-13",
            kind="daily",
            content="今天比较稳定。",
            insights=None,
            created_at="2026-05-13T00:00:00Z",
        ),
    )

    chat_calls = [call for call in fake_llm.calls if call[0] == "chat"]
    user_content = chat_calls[0][1][1]["content"]
    assert '"memory_feedback"' in user_content
    assert '"feedback_type": "stale"' in user_content
    assert '"semantic_key": "focus_style"' in user_content


async def test_memory_agent_refresh_profiles_includes_memory_feedback(fake_llm) -> None:
    await memory_feedback(
        MemoryFeedbackIn(
            semantic_key="focus_style",
            feedback_type="important",
            semantic_value_snapshot="现在早上更适合深度工作",
        )
    )
    fake_llm.queue_chat(
        json.dumps(
            {
                "user_profile": "你正在重新校准自己的节奏。",
                "behavior_patterns": "- 早上更适合深度工作。",
                "goals": "- 保留稳定节奏。",
            }
        )
    )

    agent = MemoryAgent(fake_llm)
    await agent.refresh_profiles()

    chat_calls = [call for call in fake_llm.calls if call[0] == "chat"]
    user_content = chat_calls[0][1][1]["content"]
    assert '"memory_feedback"' in user_content
    assert '"feedback_type": "important"' in user_content
    assert "现在早上更适合深度工作" in user_content
    assert "早上更适合深度工作" in profile_md.read_profile()
