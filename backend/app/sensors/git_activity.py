"""Git activity sensor utilities.

The CLI is the primary surface that runs git commands locally and POSTs to
``/api/sensors/git``. This module exposes pure helpers so the same logic can
be reused from the backend (e.g. for a future scheduled scan).
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List


@dataclass
class GitRepoStats:
    repo: str
    commit_count: int
    project_count: int
    switch_score: float
    window_days: int


def _git_commit_count(repo: Path, days: int) -> int:
    try:
        out = subprocess.run(
            [
                "git",
                "-C",
                str(repo),
                "log",
                f"--since={days} days ago",
                "--pretty=oneline",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        ).stdout
    except (subprocess.SubprocessError, FileNotFoundError):
        return 0
    return sum(1 for line in out.splitlines() if line.strip())


def _is_git_repo(path: Path) -> bool:
    return (path / ".git").exists()


def scan(roots: Iterable[Path], window_days: int = 14) -> List[GitRepoStats]:
    """Walk one level under each root and collect stats per repo."""
    repos: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        if _is_git_repo(root):
            repos.append(root)
            continue
        for child in sorted(root.iterdir()):
            if child.is_dir() and _is_git_repo(child):
                repos.append(child)

    active = [r for r in repos if _git_commit_count(r, window_days) > 0]
    project_count = len(active)

    out: list[GitRepoStats] = []
    for repo in repos:
        commits = _git_commit_count(repo, window_days)
        if commits == 0 and len(repos) > 1:
            continue
        switch_score = (
            (project_count - 1) / max(1, len(repos) - 1) if project_count else 0.0
        )
        out.append(
            GitRepoStats(
                repo=str(repo),
                commit_count=commits,
                project_count=project_count,
                switch_score=round(switch_score, 3),
                window_days=window_days,
            )
        )
    return out


__all__ = ["GitRepoStats", "scan"]
