"""Weak sensor hypotheses pipeline tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agents import MemoryAgent, StateAgent
from app.core.orchestrator import Orchestrator
from app.memory import hypothesis_repo, profile_md, state_repo
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
        HypothesisFeedbackIn(feedback="accurate"),
    )

    assert confirmed.status == "confirmed"
    assert confirmed.user_feedback == "confirmed"
    assert confirmed.user_rating == "accurate"
    assert confirmed.confirmed_at is not None

    unsure_item = hypothesis_repo.add_or_bump(
        source_type="notes",
        key="notes.unsure_signal",
        label="这个信号可能还不确定",
        summary="用户可以先标记不确定。",
        confidence=0.2,
    )
    unsure = await hypothesis_feedback(
        unsure_item.id,
        HypothesisFeedbackIn(feedback="unsure"),
    )
    assert unsure.status == "pending"
    assert unsure.user_rating == "unsure"
    assert unsure.confirmed_at is None

    wrong_item = hypothesis_repo.add_or_bump(
        source_type="git",
        key="git.wrong_signal",
        label="这个信号可能不准确",
        summary="用户可以明确否定。",
        confidence=0.2,
    )
    rejected = await hypothesis_feedback(
        wrong_item.id,
        HypothesisFeedbackIn(feedback="inaccurate"),
    )
    assert rejected.status == "rejected"
    assert rejected.user_rating == "inaccurate"
    assert rejected.rejected_at is not None


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
    hypothesis_repo.set_feedback(item.id, "accurate")
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
        "今天先保留一个小闭环就好。",
        json.dumps(
            {
                "user_profile": "你正在恢复稳定。",
                "behavior_patterns": "- 小闭环有帮助。",
                "goals": "- 保持节奏。",
            }
        ),
    )

    response = await submit_checkin(
        CheckinIn(status="还可以", did_today="写了一点东西"),
        orch=Orchestrator(fake_llm),
    )

    assert response.pending_hypotheses
    assert response.pending_hypotheses[0].key == "notes.input_up_output_down"


async def test_profile_refresh_uses_rated_hypotheses(fake_llm) -> None:
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
    unsure = hypothesis_repo.add_or_bump(
        source_type="git",
        key="git.unsure_switching",
        label="项目切换是否真的影响你还不确定",
        summary="用户标记为不确定，不应直接进入 active。",
    )
    hypothesis_repo.set_feedback(confirmed.id, "accurate")
    hypothesis_repo.set_feedback(unsure.id, "unsure")
    fake_llm.queue_chat(
        json.dumps(
            {
                "user_profile": "你会受到工作区分散影响。",
                "behavior_patterns": "- 已确认的分散信号值得参考。",
                "goals": "- 不确定的切换信号先观察。",
            }
        )
    )

    await MemoryAgent(fake_llm).refresh_profile(
        checkin=CheckinRecord(
            id=1,
            date="2026-05-14",
            created_at="2026-05-14T00:00:00Z",
            status="还可以",
            did_today="写了一点东西",
            stuck_on=None,
            anxiety=None,
            raw=None,
            session_id="default",
        ),
        reflection=ReflectionRecord(
            id=1,
            date="2026-05-14",
            kind="daily",
            content="今天比较稳定。",
            insights=None,
            created_at="2026-05-14T00:00:00Z",
        ),
    )

    chat_calls = [call for call in fake_llm.calls if call[0] == "chat"]
    user_content = chat_calls[0][1][1]["content"]
    assert confirmed.key in user_content
    assert pending.key not in user_content
    assert unsure.key in user_content
    assert "已确认的分散信号" in profile_md.read_profile()


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
