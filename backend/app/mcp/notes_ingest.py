"""Server-side markdown vault scan (mirrors CLI ``scan-notes`` aggregate only)."""

from __future__ import annotations

import re
import time
from collections import Counter
from pathlib import Path

from app.memory.schemas import NotesActivityIn

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


def scan_markdown_root(root: Path, window_days: int = 14) -> NotesActivityIn:
    if not root.exists():
        raise FileNotFoundError(str(root))
    cutoff = time.time() - window_days * 86400
    file_count = 0
    new_file_count = 0
    edited_count = 0
    total_words = 0
    new_words = 0
    tags: Counter[str] = Counter()

    for p in _iter_md(root):
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

    return NotesActivityIn(
        root=str(root.resolve()),
        file_count=file_count,
        new_file_count=new_file_count,
        edited_count=edited_count,
        total_words=total_words,
        new_words=new_words,
        avg_words=avg,
        top_topics=top_topics,
        window_days=window_days,
    )


__all__ = ["scan_markdown_root"]
