"""Generate weak hypotheses from deterministic sensor rows."""

from __future__ import annotations

from pathlib import Path

from app.memory import hypothesis_repo
from app.memory.schemas import (
    GitActivityRecord,
    NotesActivityRecord,
    SensorHypothesis,
    WorkspaceActivityRecord,
)


def from_git(record: GitActivityRecord) -> list[SensorHypothesis]:
    hypotheses: list[SensorHypothesis] = []
    repo_name = _safe_name(record.repo)
    if record.project_count >= 2 and record.switch_score >= 0.4:
        hypotheses.append(
            hypothesis_repo.add_or_bump(
                source_type="git",
                source_record_id=record.id,
                key=f"git.project_switching_up.{repo_name}",
                label="项目切换可能增多",
                summary=(
                    f"最近 {record.window_days} 天代码活动涉及多个项目，"
                    "这可能只是正常切换，也可能意味着注意力被分散。"
                ),
                evidence={
                    "project_count": record.project_count,
                    "switch_score": round(record.switch_score, 3),
                    "repo": repo_name,
                    "window_days": record.window_days,
                },
                confidence=0.25,
            )
        )
    if record.commit_count >= 5:
        hypotheses.append(
            hypothesis_repo.add_or_bump(
                source_type="git",
                source_record_id=record.id,
                key=f"git.output_active.{repo_name}",
                label="代码推进可能比较活跃",
                summary=(
                    f"最近 {record.window_days} 天有较多提交，"
                    "这可能代表推进顺畅，也可能只是整理或试错。"
                ),
                evidence={
                    "commit_count": record.commit_count,
                    "repo": repo_name,
                    "window_days": record.window_days,
                },
                confidence=0.2,
            )
        )
    return hypotheses


def from_notes(record: NotesActivityRecord) -> list[SensorHypothesis]:
    hypotheses: list[SensorHypothesis] = []
    if record.new_file_count >= 5 and record.new_words < 500:
        hypotheses.append(
            hypothesis_repo.add_or_bump(
                source_type="notes",
                source_record_id=record.id,
                key="notes.input_up_output_down",
                label="输入可能变多，输出可能放缓",
                summary=(
                    "笔记里新增文件较多，但新增文字不多；"
                    "这只是一个弱信号，可能需要你确认是否真的进入了收集模式。"
                ),
                evidence={
                    "new_file_count": record.new_file_count,
                    "new_words": record.new_words,
                    "window_days": record.window_days,
                },
                confidence=0.25,
            )
        )
    if record.new_words >= 800:
        hypotheses.append(
            hypothesis_repo.add_or_bump(
                source_type="notes",
                source_record_id=record.id,
                key="notes.writing_active",
                label="文字输出可能比较活跃",
                summary=(
                    "笔记里新增文字较多，可能代表最近在整理想法或持续写作。"
                ),
                evidence={
                    "new_words": record.new_words,
                    "edited_count": record.edited_count,
                    "window_days": record.window_days,
                },
                confidence=0.2,
            )
        )
    return hypotheses


def from_workspace(record: WorkspaceActivityRecord) -> list[SensorHypothesis]:
    hypotheses: list[SensorHypothesis] = []
    if record.active_project_count >= 4 or record.fragmentation_score >= 0.4:
        hypotheses.append(
            hypothesis_repo.add_or_bump(
                source_type="workspace",
                source_record_id=record.id,
                key="workspace.fragmented_attention",
                label="工作区可能比较分散",
                summary=(
                    "最近触达的项目或路径较多，这可能是正常探索，"
                    "也可能意味着上下文切换偏高。"
                ),
                evidence={
                    "active_project_count": record.active_project_count,
                    "touched_paths": record.touched_paths,
                    "fragmentation_score": round(record.fragmentation_score, 3),
                    "window_days": record.window_days,
                },
                confidence=0.25,
            )
        )
    return hypotheses


def _safe_name(path: str) -> str:
    name = Path(path).name.strip() or "repo"
    return "".join(ch for ch in name.lower() if ch.isalnum() or ch in {"-", "_"})[:48]


__all__ = ["from_git", "from_notes", "from_workspace"]
