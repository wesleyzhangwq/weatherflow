"""Notes (Markdown / Obsidian) activity sensor.

Pure helpers — the CLI runs them locally and POSTs aggregates to
``/api/sensors/notes``. We intentionally do NOT upload note bodies; only
counts, top tags, and word totals.

Diagnostic intent: distinguish "high input, low output" phases from real
writing/learning momentum. Long files with new words = output. Many tiny
collected files = input. The difference matters.
"""

from __future__ import annotations

import re
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_TAG_RE = re.compile(r"(?:^|\s)#([A-Za-z0-9_/-]{2,})")
_WORD_RE = re.compile(r"\w+", re.UNICODE)
_FRONTMATTER_TAGS_RE = re.compile(
    r"^\s*tags?\s*:\s*(.+)$", re.MULTILINE | re.IGNORECASE
)


@dataclass
class NotesStats:
    root: str
    file_count: int
    new_file_count: int
    edited_count: int
    total_words: int
    new_words: int
    avg_words: float
    top_topics: List[str]
    window_days: int


def _iter_markdown(root: Path) -> Iterable[Path]:
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in {".md", ".markdown", ".mdx"}:
            continue
        # skip common noise dirs
        parts = set(p.parts)
        if {".git", "node_modules", ".obsidian", ".trash"} & parts:
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


def scan(root: Path, window_days: int = 14) -> Optional[NotesStats]:
    """Scan a markdown root. Returns ``None`` if root doesn't exist."""
    if not root.exists() or not root.is_dir():
        return None

    cutoff = time.time() - window_days * 86400

    file_count = 0
    new_file_count = 0
    edited_count = 0
    total_words = 0
    new_words = 0
    tags: Counter[str] = Counter()

    for path in _iter_markdown(root):
        try:
            stat = path.stat()
            text = path.read_text(encoding="utf-8", errors="ignore")
        except (OSError, UnicodeDecodeError):
            continue

        wc = _word_count(text)
        file_count += 1
        total_words += wc

        edited_recently = stat.st_mtime >= cutoff
        created_recently = stat.st_ctime >= cutoff

        if edited_recently:
            edited_count += 1
        if created_recently:
            new_file_count += 1
            new_words += wc

        for t in _extract_tags(text):
            tags[t.lower()] += 1

    avg_words = total_words / file_count if file_count else 0.0
    top_topics = [t for t, _ in tags.most_common(8)]

    return NotesStats(
        root=str(root),
        file_count=file_count,
        new_file_count=new_file_count,
        edited_count=edited_count,
        total_words=total_words,
        new_words=new_words,
        avg_words=round(avg_words, 1),
        top_topics=top_topics,
        window_days=window_days,
    )


__all__ = ["NotesStats", "scan"]
