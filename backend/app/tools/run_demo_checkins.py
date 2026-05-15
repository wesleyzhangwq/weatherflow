"""Run 300 synthetic check-ins through WeatherFlow in a temporary DATA_DIR.

Usage:
    uv run --package weatherflow-backend python -m app.tools.run_demo_checkins
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path

from app.config import get_settings
from app.core.orchestrator import Orchestrator
from app.memory import checkin_repo, hypothesis_repo
from app.memory.schemas import GitActivityIn, WorkspaceActivityIn
from app.memory.store import init_db, set_db_path
from app.routers.sensors import ingest_git, ingest_workspace
from app.tools.demo_dataset import generate_demo_checkins
from app.tools.manual_report import build_manual_report


class DemoLLM:
    embed_dim = 8

    async def chat(self, messages, **_kwargs) -> str:
        system = str(messages[0].get("content", "")) if messages else ""
        user = str(messages[-1].get("content", "")) if messages else ""
        if "State Agent" in system:
            return json.dumps(_state_from_text(_latest_checkin_block(user)), ensure_ascii=False)
        if "strict json" in user.lower() and "user_profile" in user:
            return json.dumps(
                {
                    "user_profile": "你会受到上下文切换影响，但当任务被拆小后，节奏会逐步回来。",
                    "behavior_patterns": "- 混乱期容易收集过多输入。\n- 恢复期适合小闭环。",
                    "goals": "- 保护清晰任务。\n- 避免在疲惫时开新坑。",
                },
                ensure_ascii=False,
            )
        if "Planning Agent" in system:
            return "先收一个最小闭环，今天不要再开新任务。"
        return "这些记录显示你的节奏在变化。先看见它，不急着修正它。"

    async def embed(self, texts, **_kwargs):
        return [[0.1] * self.embed_dim for _ in texts]

    async def aclose(self) -> None:
        return None


def _state_from_text(text: str) -> dict:
    if "清晰" in text or "有动力" in text:
        return _state("Momentum", 76, 28, 20, 78)
    if "稳定" in text:
        return _state("Recovery", 62, 38, 30, 60)
    if "失控" in text or "焦虑" in text:
        return _state("Overload", 35, 78, 62, 25)
    if "压力大" in text or "疲惫" in text:
        return _state("Burnout", 42, 70, 68, 30)
    return _state("Confusion", 48, 55, 40, 42)


def _latest_checkin_block(user: str) -> str:
    marker = '"latest_checkin":'
    fallback = '"checkin":'
    source = user
    if marker in user:
        source = user.split(marker, 1)[1].split('"latest_state"', 1)[0]
    elif fallback in user:
        source = user.split(fallback, 1)[1].split('"recent_checkins"', 1)[0]
    return source


def _state(label: str, focus: int, stress: int, burnout: int, momentum: int) -> dict:
    return {
        "focus": focus,
        "stress": stress,
        "burnout": burnout,
        "momentum": momentum,
        "confidence": max(30, min(80, momentum + 5)),
        "motivation": max(25, min(85, momentum + 8)),
        "weather_label": label,
        "rationale": "demo offline estimate",
    }


async def run() -> str:
    data_dir = tempfile.mkdtemp(prefix="wf-demo-")
    db_path = str(Path(data_dir) / "weatherflow.db")
    os.environ["DATA_DIR"] = data_dir
    get_settings.cache_clear()  # type: ignore[attr-defined]
    set_db_path(db_path)
    init_db(db_path)

    # Seed a few weak signals so the manual review includes hypotheses.
    await ingest_git(GitActivityIn(repo="/demo/wf", commit_count=1, project_count=4, switch_score=0.72, window_days=7))
    await ingest_workspace(WorkspaceActivityIn(root="/demo", active_project_count=5, touched_paths=80, fragmentation_score=0.68))
    for item in hypothesis_repo.pending(limit=2):
        hypothesis_repo.set_feedback(item.id, "accurate")

    orch = Orchestrator(DemoLLM())
    for row in generate_demo_checkins(300):
        cid = checkin_repo.add(row.checkin, when=row.day)
        record = checkin_repo.get_by_id(cid)
        if record is None:
            raise RuntimeError("demo check-in insert failed")
        await orch.daily_loop(checkin=record, session_id="demo")

    return build_manual_report(data_dir=data_dir)


def main() -> None:
    print(asyncio.run(run()))


if __name__ == "__main__":
    main()
