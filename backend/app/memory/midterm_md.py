"""Mid-term memory: human-readable Markdown under ``memory/``."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Iterable, List, Optional

from app.config import get_settings
from app.memory.schemas import ReflectionRecord, SemanticItem, UserStateOut


def _memory_root() -> Path:
    s = get_settings()
    root = Path(s.resolved_memory_markdown_dir)
    root.mkdir(parents=True, exist_ok=True)
    for sub in ("daily", "weekly", "profiles"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root


def daily_path(for_date: Optional[str] = None) -> Path:
    d = for_date or date.today().isoformat()
    return _memory_root() / "daily" / f"{d}.md"


def weekly_path(for_date: Optional[date] = None) -> Path:
    d = for_date or date.today()
    iso = d.isocalendar()
    label = f"{iso.year}-W{iso.week:02d}"
    return _memory_root() / "weekly" / f"{label}.md"


def profile_paths() -> dict[str, Path]:
    root = _memory_root() / "profiles"
    return {
        "user_profile": root / "user_profile.md",
        "behavior_patterns": root / "behavior_patterns.md",
        "goals": root / "goals.md",
    }


def _ensure_profile_templates(paths: dict[str, Path]) -> None:
    templates = {
        "user_profile": "# User profile\n\n_Auto-maintained by WeatherFlow. Edit freely._\n\n",
        "behavior_patterns": "# Behavior patterns\n\n",
        "goals": "# Goals\n\n",
    }
    for key, p in paths.items():
        if not p.exists():
            p.write_text(templates[key], encoding="utf-8")


def write_daily_summary(
    *,
    for_date: str,
    state: Optional[UserStateOut],
    reflection: Optional[ReflectionRecord],
    event_lines: Optional[List[str]] = None,
    semantic_hints: Optional[Iterable[SemanticItem]] = None,
    insight_note: Optional[str] = None,
) -> Path:
    """Write or overwrite the daily markdown digest."""
    path = daily_path(for_date)
    lines: list[str] = [f"# {for_date}", ""]

    if state:
        lines.extend(
            [
                "## State",
                f"Focus: {state.focus}",
                f"Stress: {state.stress}",
                f"Burnout: {state.burnout}",
                f"Momentum: {state.momentum}",
                f"Confidence: {state.confidence}",
                f"Motivation: {state.motivation}",
                f"Weather: {state.weather_label}",
                "",
            ]
        )

    if event_lines:
        lines.append("## Events")
        for ln in event_lines:
            lines.append(f"- {ln}")
        lines.append("")

    if reflection:
        lines.extend(["## Reflection", "", reflection.content.strip(), ""])

    if semantic_hints:
        lines.append("## Semantic hints (KV)")
        for it in list(semantic_hints)[:12]:
            lines.append(f"- **{it.key}**: {it.value} _(conf {it.confidence:.2f})_")
        lines.append("")

    if insight_note:
        lines.extend(["## Insight", "", insight_note.strip(), ""])

    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return path


def append_weekly_section(
    *,
    week_label: str,
    reflection_excerpt: str,
    summary_bullets: List[str],
) -> Path:
    path = weekly_path()
    block = [
        f"## {week_label} — {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "### Summary",
    ]
    for b in summary_bullets:
        block.append(f"- {b}")
    block.extend(["", "### Reflection excerpt", "", reflection_excerpt.strip(), "", "---", ""])
    if path.exists():
        path.write_text(path.read_text(encoding="utf-8") + "\n".join(block), encoding="utf-8")
    else:
        path.write_text("# Weekly review\n\n" + "\n".join(block), encoding="utf-8")
    return path


def write_profile_bundle(
    *,
    user_profile_md: str,
    behavior_md: str,
    goals_md: str,
) -> None:
    paths = profile_paths()
    _ensure_profile_templates(paths)
    paths["user_profile"].write_text(user_profile_md.strip() + "\n", encoding="utf-8")
    paths["behavior_patterns"].write_text(behavior_md.strip() + "\n", encoding="utf-8")
    paths["goals"].write_text(goals_md.strip() + "\n", encoding="utf-8")


def read_profile_snippets(max_chars: int = 4000) -> str:
    paths = profile_paths()
    _ensure_profile_templates(paths)
    chunks: list[str] = []
    for name, p in paths.items():
        text = p.read_text(encoding="utf-8")
        chunks.append(f"### {name}\n{text[: max_chars // 3]}")
    return "\n\n".join(chunks)


def read_daily_markdown(for_date: Optional[str] = None, max_chars: int = 8000) -> str:
    p = daily_path(for_date)
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8")[:max_chars]


__all__ = [
    "daily_path",
    "weekly_path",
    "profile_paths",
    "write_daily_summary",
    "append_weekly_section",
    "write_profile_bundle",
    "read_profile_snippets",
    "read_daily_markdown",
]
