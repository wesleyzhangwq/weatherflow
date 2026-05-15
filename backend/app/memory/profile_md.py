"""Single-file long-term profile memory.

The profile is intentionally boring: one Markdown file that a curious coder can
open, edit, diff, and understand. It is the only long-term memory surface used
by the lightweight daily loop.
"""

from __future__ import annotations

from pathlib import Path

from app.config import get_settings

DEFAULT_PROFILE = """# WeatherFlow Profile

_Auto-maintained by WeatherFlow. You can edit this file directly._

## Current read

- 还没有足够稳定的长期画像。

## Useful patterns

- 暂无。

## Hypothesis feedback

- 暂无。

## User notes

<!-- WeatherFlow keeps this section intact when refreshing the profile. -->
"""


def profile_path() -> Path:
    root = Path(get_settings().resolved_memory_markdown_dir).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    return root / "profile.md"


def ensure_profile() -> Path:
    path = profile_path()
    if not path.exists():
        path.write_text(DEFAULT_PROFILE.rstrip() + "\n", encoding="utf-8")
    return path


def read_profile(*, max_chars: int = 5000) -> str:
    path = ensure_profile()
    return path.read_text(encoding="utf-8")[:max_chars]


def user_notes_section(existing: str) -> str:
    marker = "## User notes"
    if marker not in existing:
        return "## User notes\n\n<!-- WeatherFlow keeps this section intact when refreshing the profile. -->\n"
    return existing[existing.index(marker):].strip() + "\n"


def write_profile(body_md: str) -> Path:
    existing = read_profile(max_chars=20000)
    notes = user_notes_section(existing)
    body = (body_md or "").strip()
    if "## User notes" in body:
        body = body[: body.index("## User notes")].strip()
    if not body:
        body = DEFAULT_PROFILE.split("## User notes", 1)[0].strip()
    path = ensure_profile()
    path.write_text(body.rstrip() + "\n\n" + notes.rstrip() + "\n", encoding="utf-8")
    return path


__all__ = ["DEFAULT_PROFILE", "ensure_profile", "profile_path", "read_profile", "write_profile"]
