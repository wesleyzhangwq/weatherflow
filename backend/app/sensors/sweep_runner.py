"""One-shot behavior sensor sweep — git, notes, workspace.

Used by ``POST /api/sensors/sweep`` and the optional background scheduler.
Writes directly to SQLite repos (same effect as the three separate CLI scans).
"""

from __future__ import annotations

import re
import subprocess
import time
from collections import Counter
from pathlib import Path
from typing import Any, List, Optional

from app.config import Settings, get_settings
from app.memory import git_repo, notes_repo, workspace_repo
from app.memory.schemas import (
    GitActivityIn,
    GitActivityRecord,
    NotesActivityIn,
    NotesActivityRecord,
    WorkspaceActivityIn,
    WorkspaceActivityRecord,
)
from app.sensors import hypotheses as hypothesis_builder

_SKIP_WS = {".git", "node_modules", ".venv", "venv", "dist", "build", ".idea", "__pycache__"}
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_TAG_RE = re.compile(r"(?:^|\s)#([A-Za-z0-9_/-]{2,})")
_WORD_RE = re.compile(r"\w+", re.UNICODE)
_FRONTMATTER_TAGS_RE = re.compile(
    r"^\s*tags?\s*:\s*(.+)$", re.MULTILINE | re.IGNORECASE
)


def _paths_from_csv(s: str) -> List[Path]:
    return [Path(p.strip()).expanduser() for p in s.split(",") if p.strip()]


def _resolve_git_roots(settings: Settings, override: Optional[List[str]]) -> List[Path]:
    if override:
        return [Path(p).expanduser() for p in override]
    if settings.sensor_sweep_git_roots.strip():
        return _paths_from_csv(settings.sensor_sweep_git_roots)
    return [Path.home() / "Projects"]


def _resolve_notes_roots(settings: Settings, override: Optional[List[str]]) -> List[Path]:
    if override:
        return [Path(p).expanduser() for p in override]
    if settings.sensor_sweep_notes_roots.strip():
        return _paths_from_csv(settings.sensor_sweep_notes_roots)
    return [Path.home() / "Notes"]


def _resolve_workspace_roots(settings: Settings, override: Optional[List[str]]) -> List[Path]:
    if override:
        return [Path(p).expanduser() for p in override]
    if settings.sensor_sweep_workspace_roots.strip():
        return _paths_from_csv(settings.sensor_sweep_workspace_roots)
    return [Path.home() / "Projects"]


def _is_git(p: Path) -> bool:
    return (p / ".git").exists()


def _commits_since(repo: Path, days: int) -> int:
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "log", f"--since={days} days ago", "--pretty=oneline"],
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        ).stdout
    except (subprocess.SubprocessError, FileNotFoundError):
        return 0
    return sum(1 for ln in out.splitlines() if ln.strip())


def _collect_git_repos(roots: List[Path]) -> List[Path]:
    repos: list[Path] = []
    for r in roots:
        if not r.exists():
            continue
        if _is_git(r):
            repos.append(r)
            continue
        try:
            for child in sorted(r.iterdir()):
                if child.is_dir() and _is_git(child):
                    repos.append(child)
        except OSError:
            continue
    return repos


def _sweep_git(roots: List[Path], window: int, dry_run: bool) -> dict[str, Any]:
    repos = _collect_git_repos(roots)
    out = {"repos_scanned": len(repos), "records_written": 0, "skipped": not repos}
    if not repos:
        return out
    stats = [(p, _commits_since(p, window)) for p in repos]
    active = [s for s in stats if s[1] > 0]
    project_count = len(active)
    switch_score = (
        (project_count - 1) / max(1, len(stats) - 1) if len(stats) > 1 else 0.0
    )
    for repo, commits in active:
        if dry_run:
            continue
        payload = GitActivityIn(
            repo=str(repo),
            commit_count=int(commits),
            project_count=int(project_count),
            switch_score=round(switch_score, 3),
            window_days=int(window),
        )
        rid = git_repo.add(payload)
        hypothesis_builder.from_git(
            GitActivityRecord(id=rid, ts="", **payload.model_dump())
        )
        out["records_written"] += 1
    if dry_run:
        out["records_written"] = len(active)
    return out


def _iter_md(root: Path):
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in {".md", ".markdown", ".mdx"}:
            continue
        if {".git", "node_modules", ".obsidian", ".trash"} & set(p.parts):
            continue
        yield p


def _word_count(text: str) -> int:
    return len(_WORD_RE.findall(text))


def _extract_tags(text: str) -> list[str]:
    tags: list[str] = []
    fm = _FRONTMATTER_RE.match(text)
    if fm:
        for line in _FRONTMATTER_TAGS_RE.findall(fm.group(1)):
            chunk = line.strip().strip("[]")
            for raw in re.split(r"[,\s]+", chunk):
                raw = raw.strip().lstrip("#").strip("\"'")
                if raw:
                    tags.append(raw)
    for raw in _TAG_RE.findall(text):
        tags.append(raw.strip())
    return tags


def _sweep_notes(roots: List[Path], window: int, dry_run: bool) -> dict[str, Any]:
    cutoff = time.time() - window * 86400
    out = {"roots": len(roots), "records_written": 0}
    for r in roots:
        if not r.exists():
            continue
        file_count = 0
        new_file_count = 0
        edited_count = 0
        total_words = 0
        new_words = 0
        tags: Counter[str] = Counter()
        for p in _iter_md(r):
            try:
                stat = p.stat()
                text = p.read_text(encoding="utf-8", errors="ignore")
            except (OSError, UnicodeDecodeError):
                continue
            wc = _word_count(text)
            file_count += 1
            total_words += wc
            if stat.st_mtime >= cutoff:
                edited_count += 1
            if stat.st_ctime >= cutoff:
                new_file_count += 1
                new_words += wc
            for t in _extract_tags(text):
                tags[t.lower()] += 1
        if file_count == 0:
            continue
        avg = round(total_words / file_count, 1)
        top_topics = [t for t, _ in tags.most_common(8)]
        payload = NotesActivityIn(
            root=str(r.resolve()),
            file_count=file_count,
            new_file_count=new_file_count,
            edited_count=edited_count,
            total_words=total_words,
            new_words=new_words,
            avg_words=avg,
            top_topics=top_topics,
            window_days=window,
        )
        if not dry_run:
            rid = notes_repo.add(payload)
            hypothesis_builder.from_notes(
                NotesActivityRecord(id=rid, ts="", **payload.model_dump())
            )
        out["records_written"] += 1
    return out


def _sweep_workspace(roots: List[Path], window: int, dry_run: bool) -> dict[str, Any]:
    cutoff = time.time() - window * 86400
    out = {"roots": len(roots), "records_written": 0}
    for r in roots:
        if not r.exists():
            continue
        r = r.resolve()
        project_mtimes: dict[str, float] = {}
        touched = 0
        for p in r.rglob("*"):
            if not p.is_file():
                continue
            if _SKIP_WS & set(p.parts):
                continue
            try:
                st = p.stat()
            except OSError:
                continue
            if st.st_mtime < cutoff:
                continue
            touched += 1
            try:
                rel = p.relative_to(r)
            except ValueError:
                continue
            if not rel.parts:
                continue
            proj = rel.parts[0]
            project_mtimes[proj] = max(project_mtimes.get(proj, 0.0), st.st_mtime)
        active = len(project_mtimes)
        frag = round(min(1.0, (active - 1) / 10.0), 3) if active > 1 else 0.0
        top_dirs = [
            k
            for k, _ in sorted(project_mtimes.items(), key=lambda kv: kv[1], reverse=True)
        ][:16]
        payload = WorkspaceActivityIn(
            root=str(r),
            active_project_count=active,
            touched_paths=touched,
            fragmentation_score=frag,
            top_dirs=top_dirs,
            window_days=window,
        )
        if not dry_run:
            rid = workspace_repo.add(payload)
            hypothesis_builder.from_workspace(
                WorkspaceActivityRecord(id=rid, ts="", **payload.model_dump())
            )
        out["records_written"] += 1
    return out


def run_sensor_sweep(
    *,
    settings: Optional[Settings] = None,
    git_roots: Optional[List[str]] = None,
    notes_roots: Optional[List[str]] = None,
    workspace_roots: Optional[List[str]] = None,
    window_days: int = 14,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run git, notes, and workspace sensors."""
    settings = settings or get_settings()
    g_roots = _resolve_git_roots(settings, git_roots)
    n_roots = _resolve_notes_roots(settings, notes_roots)
    w_roots = _resolve_workspace_roots(settings, workspace_roots)

    return {
        "dry_run": dry_run,
        "window_days": window_days,
        "git": _sweep_git(g_roots, window_days, dry_run),
        "notes": _sweep_notes(n_roots, window_days, dry_run),
        "workspace": _sweep_workspace(w_roots, window_days, dry_run),
    }


__all__ = ["run_sensor_sweep"]
