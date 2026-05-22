from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.memory.schemas import ActionProposal


def test_action_proposal_generates_unique_ids() -> None:
    a = ActionProposal(
        kind="focus_block",
        title="Deep Work: memory refactor",
        rationale="User named a concrete work item",
        tool_name="calendar.create_focus_block",
        tool_arguments={"title": "Deep Work: memory refactor", "duration_minutes": 90},
    )
    b = ActionProposal(
        kind="focus_block",
        title="Deep Work: memory refactor",
        rationale="User named a concrete work item",
        tool_name="calendar.create_focus_block",
        tool_arguments={"title": "Deep Work: memory refactor", "duration_minutes": 90},
    )
    assert a.id != b.id


def test_action_proposal_requires_confirmation_by_default() -> None:
    a = ActionProposal(
        kind="github_issue",
        title="Refactor memory retrieval",
        rationale="User described a concrete engineering task",
        tool_name="github.create_issue",
        tool_arguments={"title": "Refactor memory retrieval", "owner": "wesleyzhangwq", "repo": "weatherflow"},
    )
    assert a.requires_confirmation is True


def test_action_proposal_rejects_unknown_kind() -> None:
    with pytest.raises(ValidationError):
        ActionProposal(
            kind="unknown_kind",
            title="Bad",
            rationale="Test",
            tool_name="some.tool",
            tool_arguments={},
        )


def test_action_proposal_all_valid_kinds() -> None:
    for kind in ("calendar_event", "focus_block", "github_issue", "github_file_update"):
        a = ActionProposal(
            kind=kind,
            title="Test",
            rationale="Test",
            tool_name="some.tool",
            tool_arguments={},
        )
        assert a.kind == kind
