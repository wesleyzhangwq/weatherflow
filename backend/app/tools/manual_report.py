"""Manual review report helpers for demo WeatherFlow runs."""

from __future__ import annotations

from collections import Counter

from app.memory import checkin_repo, hypothesis_repo, profile_md, reflection_repo, state_repo


def build_manual_report(*, data_dir: str) -> str:
    states = state_repo.trend(days=1000)
    weather_counts = Counter(s.weather_label for s in states)
    refs = reflection_repo.recent(limit=3)
    pending = hypothesis_repo.pending(limit=1000)
    rated = hypothesis_repo.rated(limit=1000)
    active = hypothesis_repo.active(limit=1000)
    profile = profile_md.read_profile(max_chars=1200)

    lines = [
        "# WeatherFlow Demo Manual Report",
        "",
        f"DATA_DIR: {data_dir}",
        f"Check-ins: {len(checkin_repo.recent(limit=1000))}",
        f"State snapshots: {len(states)}",
        f"Weather distribution: {dict(weather_counts)}",
        f"Hypotheses: pending={len(pending)}, active={len(active)}, rated={len(rated)}",
        "",
        "## Latest reflections",
    ]
    for r in refs:
        suggestion = (r.insights or {}).get("suggestion") if r.insights else None
        lines.append(f"- {r.date} [{r.kind}] {r.content[:120]}")
        if suggestion:
            lines.append(f"  Suggestion: {suggestion[:120]}")

    lines.extend(
        [
            "",
            "## Profile excerpt",
            profile.strip() or "(empty)",
            "",
            "## Human checklist",
            "- 首页第一眼是否能看到天气和下一步建议？",
            "- 天气分布是否随着 300 天阶段变化，而不是全都同一类？",
            "- 下一步建议是否短、具体、可执行？",
            "- profile.md 是否像长期画像，而不是流水账？",
            "- hypothesis 文案是否像可确认的问题，而不是武断结论？",
        ]
    )
    return "\n".join(lines)


__all__ = ["build_manual_report"]
