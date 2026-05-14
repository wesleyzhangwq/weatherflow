"""Sensor ingestion endpoints — git activity, notes activity, workspace.

Ingest writes deterministic sensor rows and derives weak hypotheses. Hypotheses
need user confirmation or repetition before they influence state.
"""

from __future__ import annotations
from typing import List

from fastapi import APIRouter, Body, HTTPException, Query

from app.config import get_settings
from app.memory import git_repo, hypothesis_repo, notes_repo, workspace_repo
from app.memory.schemas import (
    GitActivityIn,
    GitActivityRecord,
    HypothesisFeedbackIn,
    HypothesisStatus,
    NotesActivityIn,
    NotesActivityRecord,
    SensorSweepIn,
    SensorHypothesis,
    WorkspaceActivityIn,
    WorkspaceActivityRecord,
)
from app.sensors import hypotheses as hypothesis_builder
from app.sensors.sweep_runner import run_sensor_sweep

router = APIRouter(prefix="/api/sensors", tags=["sensors"])


# -------------------------- Bundled sweep ------------------------
@router.post("/sweep")
async def sensor_sweep(
    body: SensorSweepIn = Body(default_factory=SensorSweepIn),
) -> dict:
    """Run git + notes + workspace in one shot.

    Empty root lists use server defaults (``SENSOR_SWEEP_*`` env or ``~/Projects`` / ``~/Notes``).
    Non-dry runs write sensor rows and weak hypotheses, but do not recompute state.
    """
    settings = get_settings()
    summary = run_sensor_sweep(
        settings=settings,
        git_roots=body.git_roots if body.git_roots else None,
        notes_roots=body.notes_roots if body.notes_roots else None,
        workspace_roots=body.workspace_roots if body.workspace_roots else None,
        window_days=body.window_days,
        dry_run=body.dry_run,
    )
    return summary


# -------------------------- Git ----------------------------
@router.post("/git", response_model=GitActivityRecord)
async def ingest_git(
    payload: GitActivityIn,
) -> GitActivityRecord:
    rid = git_repo.add(payload)
    rows = git_repo.recent(limit=1)
    record = (
        rows[0]
        if rows and rows[0].id == rid
        else GitActivityRecord(id=rid, ts="", **payload.model_dump())
    )
    hypothesis_builder.from_git(record)
    return record


@router.get("/git/recent", response_model=List[GitActivityRecord])
async def recent_git(limit: int = 30) -> List[GitActivityRecord]:
    return git_repo.recent(limit=limit)


# -------------------------- Notes --------------------------
@router.post("/notes", response_model=NotesActivityRecord)
async def ingest_notes(
    payload: NotesActivityIn,
) -> NotesActivityRecord:
    rid = notes_repo.add(payload)
    rows = notes_repo.recent(limit=1)
    record = (
        rows[0]
        if rows and rows[0].id == rid
        else NotesActivityRecord(id=rid, ts="", **payload.model_dump())
    )
    hypothesis_builder.from_notes(record)
    return record


@router.get("/notes/recent", response_model=List[NotesActivityRecord])
async def recent_notes(limit: int = 30) -> List[NotesActivityRecord]:
    return notes_repo.recent(limit=limit)


# -------------------------- Workspace ------------------------
@router.post("/workspace", response_model=WorkspaceActivityRecord)
async def ingest_workspace(
    payload: WorkspaceActivityIn,
) -> WorkspaceActivityRecord:
    rid = workspace_repo.add(payload)
    rows = workspace_repo.recent(limit=1)
    record = (
        rows[0]
        if rows and rows[0].id == rid
        else WorkspaceActivityRecord(id=rid, ts="", **payload.model_dump())
    )
    hypothesis_builder.from_workspace(record)
    return record


@router.get("/workspace/recent", response_model=List[WorkspaceActivityRecord])
async def recent_workspace(limit: int = 30) -> List[WorkspaceActivityRecord]:
    return workspace_repo.recent(limit=limit)


# -------------------------- Hypotheses ------------------------
@router.get("/hypotheses", response_model=List[SensorHypothesis])
async def recent_hypotheses(
    limit: int = 30,
    status: HypothesisStatus | None = Query(default=None),
) -> List[SensorHypothesis]:
    return hypothesis_repo.recent(limit=limit, status=status)


@router.post("/hypotheses/{hypothesis_id}/feedback", response_model=SensorHypothesis)
async def hypothesis_feedback(
    hypothesis_id: int,
    body: HypothesisFeedbackIn,
) -> SensorHypothesis:
    item = hypothesis_repo.set_feedback(hypothesis_id, body.feedback)
    if item is None:
        raise HTTPException(status_code=404, detail="hypothesis not found")
    return item
