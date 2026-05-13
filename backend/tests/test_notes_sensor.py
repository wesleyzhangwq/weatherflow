"""Notes sensor + repo tests."""

from __future__ import annotations

from pathlib import Path

from app.memory import notes_repo
from app.memory.schemas import NotesActivityIn
from app.sensors.notes import scan as scan_notes


def test_scan_counts_words_and_tags(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text(
        "---\ntags: [agents, rag]\n---\n# hello\nThis note has eight English words here.",
        encoding="utf-8",
    )
    (tmp_path / "b.md").write_text(
        "Just three words. #ai #ai\nMore words and #agents follow.",
        encoding="utf-8",
    )
    (tmp_path / "c.txt").write_text("ignored", encoding="utf-8")

    stats = scan_notes(tmp_path, window_days=14)
    assert stats is not None
    assert stats.file_count == 2
    # Both files were created in this test, so counted as new.
    assert stats.new_file_count == 2
    assert stats.total_words > 10
    # Tags should include front-matter and inline forms, deduped/case-folded.
    assert set(stats.top_topics) >= {"agents", "rag", "ai"}


def test_notes_repo_roundtrip_with_topics() -> None:
    rid = notes_repo.add(
        NotesActivityIn(
            root="/tmp/v",
            file_count=10,
            new_file_count=3,
            edited_count=4,
            total_words=1000,
            new_words=120,
            avg_words=100.0,
            top_topics=["agents", "rag"],
        )
    )
    items = notes_repo.recent(limit=5)
    assert items
    item = next(i for i in items if i.id == rid)
    assert item.top_topics == ["agents", "rag"]
    assert item.new_words == 120


def test_scan_returns_none_for_missing_root(tmp_path: Path) -> None:
    missing = tmp_path / "does_not_exist"
    assert scan_notes(missing) is None
