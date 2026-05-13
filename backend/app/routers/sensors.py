"""Sensor ingestion endpoints — git activity, notes activity, workspace.

Each ingest endpoint also triggers a state recompute so the dashboard
reflects new behavioral signal immediately (the gap was the original design
goal: "理解模式"必须可见).
"""

from __future__ import annotations

import logging
from typing import List

from fastapi import APIRouter, Body, Depends

from app.agents import StateAgent
from app.config import get_settings
from app.core.llm import LLMClient
from app.memory import git_repo, notes_repo, workspace_repo
from app.memory.schemas import (
    GitActivityIn,
    GitActivityRecord,
    NotesActivityIn,
    NotesActivityRecord,
    SensorSweepIn,
    WorkspaceActivityIn,
    WorkspaceActivityRecord,
)
from app.routers._deps import get_llm
from app.sensors.sweep_runner import run_sensor_sweep

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/sensors", tags=["sensors"])


async def _refresh_state(llm: LLMClient) -> None:
    try:
        await StateAgent(llm).estimate()
    except Exception:
        logger.exception("state refresh after sensor ingest failed")


# -------------------------- Bundled sweep ------------------------
@router.post("/sweep")
async def sensor_sweep(
    body: SensorSweepIn = Body(default_factory=SensorSweepIn),
    llm: LLMClient = Depends(get_llm),
) -> dict:
    """Run git + notes + workspace in one shot.

    Empty root lists use server defaults (``SENSOR_SWEEP_*`` env or ``~/Projects`` / ``~/Notes``).
    After a non-dry run, state is recomputed once (single LLM call).
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
    if not body.dry_run:
        await _refresh_state(llm)
    return summary


# -------------------------- Git ----------------------------
@router.post("/git", response_model=GitActivityRecord)
async def ingest_git(
    payload: GitActivityIn,
    llm: LLMClient = Depends(get_llm),
) -> GitActivityRecord:
    rid = git_repo.add(payload)
    rows = git_repo.recent(limit=1)
    record = (
        rows[0]
        if rows and rows[0].id == rid
        else GitActivityRecord(id=rid, ts="", **payload.model_dump())
    )
    await _refresh_state(llm)
    return record


@router.get("/git/recent", response_model=List[GitActivityRecord])
async def recent_git(limit: int = 30) -> List[GitActivityRecord]:
    return git_repo.recent(limit=limit)


# -------------------------- Notes --------------------------
@router.post("/notes", response_model=NotesActivityRecord)
async def ingest_notes(
    payload: NotesActivityIn,
    llm: LLMClient = Depends(get_llm),
) -> NotesActivityRecord:
    rid = notes_repo.add(payload)
    rows = notes_repo.recent(limit=1)
    record = (
        rows[0]
        if rows and rows[0].id == rid
        else NotesActivityRecord(id=rid, ts="", **payload.model_dump())
    )
    await _refresh_state(llm)
    return record


@router.get("/notes/recent", response_model=List[NotesActivityRecord])
async def recent_notes(limit: int = 30) -> List[NotesActivityRecord]:
    return notes_repo.recent(limit=limit)


# -------------------------- Workspace ------------------------
@router.post("/workspace", response_model=WorkspaceActivityRecord)
async def ingest_workspace(
    payload: WorkspaceActivityIn,
    llm: LLMClient = Depends(get_llm),
) -> WorkspaceActivityRecord:
    rid = workspace_repo.add(payload)
    rows = workspace_repo.recent(limit=1)
    record = (
        rows[0]
        if rows and rows[0].id == rid
        else WorkspaceActivityRecord(id=rid, ts="", **payload.model_dump())
    )
    await _refresh_state(llm)
    return record


@router.get("/workspace/recent", response_model=List[WorkspaceActivityRecord])
async def recent_workspace(limit: int = 30) -> List[WorkspaceActivityRecord]:
    return workspace_repo.recent(limit=limit)
