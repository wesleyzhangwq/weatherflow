"""Profile.md store — L3 long-term picture.

Six fixed sections (architecture-v1.md §4.4). Users can read/edit the file
freely; the DelayedMemoryWriter and direct user edits coordinate via
``fcntl.flock`` (ADR D17). Sections cannot be added or removed in v1 (ADR §A).
"""

from __future__ import annotations

import fcntl
import re
from pathlib import Path
from typing import Dict, Iterable

from app.config import get_settings
from app.memory.schemas import ProfileSection

SECTION_ORDER: tuple[ProfileSection, ...] = (
    "Identity",
    "Active Projects",
    "Rhythm Patterns",
    "Preferences",
    "Anti-patterns",
    "Recent Themes",
)


_SECTION_DEFAULTS: Dict[ProfileSection, str] = {
    "Identity": "_由用户手动维护。描述你的身份、长期目标、自我认知。_\n\n> 例：独立开发者，聚焦 LLM/Agent/RAG 方向。",
    "Active Projects": (
        "_当前活跃项目列表，作为 check-in 项目选项的来源。_\n"
        "_由用户手动 + GitHub 自动识别 + DelayedMemoryWriter 共同维护。_"
    ),
    "Rhythm Patterns": (
        "_由 DelayedMemoryWriter 维护，记录已被验证的节奏规律。_\n"
        "_用户也可以手动编辑、增删条目。_"
    ),
    "Preferences": "_由 DelayedMemoryWriter 从 Chat 中识别，记录工具/时间/工作方式偏好。_",
    "Anti-patterns": "_由 DelayedMemoryWriter 维护，记录历史上反复证明不适合你的模式。_",
    "Recent Themes": "_由 DelayedMemoryWriter 自动维护的滚动主题（最近 N 周）。_",
}


def _profile_dir(user_id: str | None = None) -> Path:
    settings = get_settings()
    uid = user_id or settings.default_user_id
    root = Path(settings.resolved_memory_markdown_dir).expanduser() / uid
    root.mkdir(parents=True, exist_ok=True)
    return root


def profile_path(user_id: str | None = None) -> Path:
    return _profile_dir(user_id) / "profile.md"


def _initial_body() -> str:
    parts: list[str] = []
    for section in SECTION_ORDER:
        parts.append(f"# {section}\n\n{_SECTION_DEFAULTS[section].rstrip()}\n")
    return "\n".join(parts)


def ensure_profile(user_id: str | None = None) -> Path:
    path = profile_path(user_id)
    if not path.exists():
        path.write_text(_initial_body(), encoding="utf-8")
    return path


_SECTION_RE = re.compile(r"(?m)^# (?P<title>.+?)\s*$")


def _split_sections(body: str) -> Dict[str, str]:
    matches = list(_SECTION_RE.finditer(body))
    sections: Dict[str, str] = {}
    for i, m in enumerate(matches):
        title = m.group("title").strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        sections[title] = body[start:end].strip("\n").strip() + "\n"
    return sections


def read_profile(user_id: str | None = None) -> str:
    path = ensure_profile(user_id)
    return path.read_text(encoding="utf-8")


def read_sections(
    *, sections: Iterable[ProfileSection] | None = None, user_id: str | None = None
) -> Dict[ProfileSection, str]:
    body = read_profile(user_id)
    split = _split_sections(body)
    selected = list(sections) if sections else list(SECTION_ORDER)
    out: Dict[ProfileSection, str] = {}
    for name in selected:
        out[name] = split.get(name, _SECTION_DEFAULTS.get(name, "")).strip()
    return out


def write_section(
    section: ProfileSection, content: str, *, user_id: str | None = None
) -> Path:
    if section not in SECTION_ORDER:
        raise ValueError(f"Unknown profile section: {section!r}")
    path = ensure_profile(user_id)
    with open(path, "r+", encoding="utf-8") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            body = f.read()
            sections = _split_sections(body)
            sections[section] = content.strip() + "\n"
            new_body_parts: list[str] = []
            for name in SECTION_ORDER:
                text = sections.get(name, _SECTION_DEFAULTS[name]).strip()
                new_body_parts.append(f"# {name}\n\n{text}\n")
            new_body = "\n".join(new_body_parts)
            f.seek(0)
            f.write(new_body)
            f.truncate()
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    return path


def apply_patch(
    section: ProfileSection,
    diff: str,
    *,
    user_id: str | None = None,
) -> Path:
    """Apply a DelayedMemoryWriter patch.

    The 'diff' is a free-form markdown chunk produced by the LLM (ADR D7).
    We treat it as the **new full content** of the target section, replacing
    whatever was there. The previous content is preserved in the L1 audit
    record (profile_patch event), so this is non-destructive in the
    full-system sense.
    """
    return write_section(section, diff, user_id=user_id)


__all__ = [
    "SECTION_ORDER",
    "apply_patch",
    "ensure_profile",
    "profile_path",
    "read_profile",
    "read_sections",
    "write_section",
]
