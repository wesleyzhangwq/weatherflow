"""``wf scan-notes`` — behavior sensor for markdown / Obsidian roots.

Counts files / new files / total words / new words / top tags over a window
and POSTs the aggregate (NEVER note bodies) to ``/api/sensors/notes``.
"""

from __future__ import annotations

import re
import time
from collections import Counter
from pathlib import Path
from typing import List

import typer
from rich.console import Console
from rich.table import Table

from weatherflow_cli import api

console = Console()

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_TAG_RE = re.compile(r"(?:^|\s)#([A-Za-z0-9_/-]{2,})")
_WORD_RE = re.compile(r"\w+", re.UNICODE)
_FRONTMATTER_TAGS_RE = re.compile(
    r"^\s*tags?\s*:\s*(.+)$", re.MULTILINE | re.IGNORECASE
)


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


def run(
    root: List[Path] = typer.Option(
        [Path.home() / "Notes"],
        "--root",
        "-r",
        help="One or more markdown roots (e.g. your Obsidian vault).",
    ),
    window: int = typer.Option(14, "--window", help="window in days"),
    dry_run: bool = typer.Option(False, "--dry-run", help="don't post"),
) -> None:
    cutoff = time.time() - window * 86400
    sent = 0

    for r in root:
        if not r.exists():
            console.print(f"[yellow]skip missing root: {r}[/yellow]")
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

        avg = round(total_words / file_count, 1) if file_count else 0.0
        top_topics = [t for t, _ in tags.most_common(8)]

        table = Table(title=f"Notes activity — {r}")
        table.add_column("metric")
        table.add_column("value", justify="right")
        for k, v in [
            ("files", file_count),
            ("new files (last %dd)" % window, new_file_count),
            ("edited (last %dd)" % window, edited_count),
            ("total words", total_words),
            ("new words", new_words),
            ("avg words / file", avg),
            ("top topics", ", ".join(top_topics) or "—"),
        ]:
            table.add_row(str(k), str(v))
        console.print(table)

        if file_count == 0:
            console.print(f"[dim]no markdown found under {r}, skipping[/dim]")
            continue

        payload = {
            "root": str(r),
            "file_count": file_count,
            "new_file_count": new_file_count,
            "edited_count": edited_count,
            "total_words": total_words,
            "new_words": new_words,
            "avg_words": avg,
            "top_topics": top_topics,
            "window_days": window,
        }
        if dry_run:
            console.print(f"[dim]would POST {payload}[/dim]")
            continue
        try:
            api.post("/api/sensors/notes", json=payload)
            sent += 1
        except Exception as exc:
            console.print(f"[red]post failed for {r}: {exc}[/red]")

    if not dry_run and sent:
        console.print(f"[green]sent {sent} record(s) to {api.api_base()}[/green]")
