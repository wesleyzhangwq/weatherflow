"""Weak sensor hypotheses pipeline tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agents import MemoryAgent, StateAgent
from app.core.orchestrator import Orchestrator
from app.memory import hypothesis_repo, state_repo
from app.memory.schemas import (
    CheckinIn,
    CheckinRecord,
    GitActivityIn,
    HypothesisFeedbackIn,
    ReflectionRecord,
)
from app.routers.checkin import submit_checkin
from app.routers.sensors import hypothesis_feedback, ingest_git
from app.sensors.sweep_runner import run_sensor_sweep

pytestmark = pytest.mark.asyncio


async def test_sensor_ingest_creates_hypothesis_without_refreshing_state() -> None:
    record = await ingest_git(
        GitActivityIn(
            repo="/tmp/weatherflow",
            commit_count=1,
            project_count=3,
            switch_score=0.7,
            window_days=7,
        )
    )

    assert record.id > 0
    assert state_repo.latest() is None
    pending = hypothesis_repo.pending()
    assert len(pending) == 1
    assert pending[0].source_type == "git"
    assert pending[0].status == "pending"
    assert pending[0].confidence < 0.5


async def test_hypothesis_feedback_confirms_or_rejects() -> None:
    item = hypothesis_repo.add_or_bump(
        source_type="workspace",
        key="workspace.fragmented_attention",
        label="工作区可能比较分散",
        summary="这是一个待确认的弱信号。",
        confidence=0.25,
    )

    confirmed = await hypothesis_feedback(
        item.id,
        HypothesisFeedbackIn(feedback="confirmed"),
    )

    assert confirmed.status == "confirmed"
    assert confirmed.user_feedback == "confirmed"
    assert confirmed.confirmed_at is not None


async def test_hypothesis_repo_bumps_repeated_keys() -> None:
    first = hypothesis_repo.add_or_bump(
        source_type="notes",
        key="notes.input_up_output_down",
        label="输入可能变多，输出可能放缓",
        summary="第一次看到。",
        evidence={"new_file_count": 5},
    )
    second = hypothesis_repo.add_or_bump(
        source_type="notes",
        key="notes.input_up_output_down",
        label="输入可能变多，输出可能放缓",
        summary="第二次看到。",
        evidence={"new_file_count": 6},
    )

    assert second.id == first.id
    assert second.seen_count == 2
    assert second.summary == "第二次看到。"
    assert any(h.key == "notes.input_up_output_down" for h in hypothesis_repo.active())


async def test_state_agent_ignores_pending_hypotheses(fake_llm) -> None:
    hypothesis_repo.add_or_bump(
        source_type="git",
        key="git.project_switching_up.weatherflow",
        label="项目切换可能增多",
        summary="待确认，不应直接影响状态。",
    )
    fake_llm.queue_chat(
        json.dumps(
            {
                "focus": 50,
                "stress": 40,
                "burnout": 30,
                "momentum": 45,
                "confidence": 50,
                "motivation": 50,
                "weather_label": "Confusion",
                "rationale": "先看你自己的 check-in。",
            }
        )
    )

    await StateAgent(fake_llm).estimate()

    chat_calls = [call for call in fake_llm.calls if call[0] == "chat"]
    user_content = chat_calls[0][1][1]["content"]
    assert "active_sensor_hypotheses" in user_content
    assert "git.project_switching_up.weatherflow" not in user_content


async def test_state_agent_uses_confirmed_hypotheses(fake_llm) -> None:
    item = hypothesis_repo.add_or_bump(
        source_type="git",
        key="git.project_switching_up.weatherflow",
        label="项目切换可能增多",
        summary="用户确认过的假设可以进入状态上下文。",
    )
    hypothesis_repo.set_feedback(item.id, "confirmed")
    fake_llm.queue_chat(
        json.dumps(
            {
                "focus": 45,
                "stress": 50,
                "burnout": 35,
                "momentum": 40,
                "confidence": 50,
                "motivation": 50,
                "weather_label": "Overload",
                "rationale": "确认过的切换信号显示上下文较多。",
            }
        )
    )

    await StateAgent(fake_llm).estimate()

    chat_calls = [call for call in fake_llm.calls if call[0] == "chat"]
    user_content = chat_calls[0][1][1]["content"]
    assert "git.project_switching_up.weatherflow" in user_content


async def test_checkin_response_returns_pending_hypotheses(fake_llm) -> None:
    hypothesis_repo.add_or_bump(
        source_type="notes",
        key="notes.input_up_output_down",
        label="输入可能变多，输出可能放缓",
        summary="需要用户确认的弱信号。",
    )
    fake_llm.queue_chat(
        json.dumps(
            {
                "focus": 60,
                "stress": 40,
                "burnout": 30,
                "momentum": 55,
                "confidence": 50,
                "motivation": 55,
                "weather_label": "Recovery",
                "rationale": "今天的状态比较平稳。",
            }
        ),
        "你今天的记录比较安静，但有一点稳定的回到现场。",
        json.dumps({"patterns": []}),
        json.dumps({"semantic": [], "milestones": [], "phases": []}),
        "今天先保留一个小闭环就好。",
    )

    response = await submit_checkin(
        CheckinIn(status="还可以", did_today="写了一点东西"),
        orch=Orchestrator(fake_llm),
    )

    assert response.pending_hypotheses
    assert response.pending_hypotheses[0].key == "notes.input_up_output_down"


async def test_memory_extract_uses_active_not_pending_hypotheses(fake_llm) -> None:
    pending = hypothesis_repo.add_or_bump(
        source_type="notes",
        key="notes.pending_collection_mode",
        label="输入可能变多",
        summary="还没确认，不能进入长期记忆。",
    )
    confirmed = hypothesis_repo.add_or_bump(
        source_type="workspace",
        key="workspace.confirmed_fragmented_attention",
        label="工作区比较分散",
        summary="用户确认过，可以作为长期记忆的辅助证据。",
    )
    hypothesis_repo.set_feedback(confirmed.id, "confirmed")
    fake_llm.queue_chat(json.dumps({"semantic": [], "milestones": [], "phases": []}))

    await MemoryAgent(fake_llm).extract(
        recent_checkins=[
            CheckinRecord(
                id=1,
                date="2026-05-14",
                created_at="2026-05-14T00:00:00Z",
                status="还可以",
                did_today="写了一点东西",
                stuck_on=None,
                anxiety=None,
                raw=None,
                session_id="default",
            )
        ],
        recent_reflections=[
            ReflectionRecord(
                id=1,
                date="2026-05-14",
                kind="daily",
                content="今天比较稳定。",
                insights=None,
                created_at="2026-05-14T00:00:00Z",
            )
        ],
    )

    chat_calls = [call for call in fake_llm.calls if call[0] == "chat"]
    user_content = chat_calls[0][1][1]["content"]
    assert confirmed.key in user_content
    assert pending.key not in user_content


async def test_sensor_sweep_does_not_refresh_state(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()

    summary = run_sensor_sweep(
        git_roots=[str(root)],
        notes_roots=[str(root)],
        workspace_roots=[str(root)],
        window_days=7,
        dry_run=False,
    )

    assert summary["dry_run"] is False
    assert state_repo.latest() is None
