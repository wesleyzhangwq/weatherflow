"""Pattern detector — compare time windows over WeatherFlow state snapshots.

This is the pattern signal engine. It does NOT use an LLM; it produces structured
deltas the LLM then narrates in human voice. Keeping it deterministic keeps
the agent honest about what it actually noticed.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from statistics import mean
from typing import List, Optional

from app.memory import state_repo


# ---------------------------------------------------------------------------
@dataclass
class WindowMetric:
    name: str
    current: float
    previous: float
    delta: float          # current - previous
    pct_delta: Optional[float]  # None if previous was 0


@dataclass
class Pattern:
    code: str             # short slug, e.g. "input_up_output_down"
    severity: str         # "info" | "watch" | "alert"
    label: str            # human-readable
    explanation: str      # short, factual; agent narrates this gently later
    evidence: dict


@dataclass
class PatternReport:
    window_days: int
    metrics: List[WindowMetric]
    patterns: List[Pattern]

    def to_dict(self) -> dict:
        return {
            "window_days": self.window_days,
            "metrics": [asdict(m) for m in self.metrics],
            "patterns": [asdict(p) for p in self.patterns],
        }


# ---------------------------------------------------------------------------
def _split_two_windows(rows: list, *, getter, days: int):
    """Given a sorted-by-ts list, return ([current], [previous]) by ts cutoff."""
    if not rows:
        return [], []
    now = datetime.now()
    cur_cut = now - timedelta(days=days)
    prev_cut = now - timedelta(days=2 * days)
    cur, prev = [], []
    for row in rows:
        try:
            ts = datetime.fromisoformat(getter(row))
        except (TypeError, ValueError):
            continue
        if ts >= cur_cut:
            cur.append(row)
        elif ts >= prev_cut:
            prev.append(row)
    return cur, prev


def _avg(values: list[float]) -> float:
    return float(mean(values)) if values else 0.0


def _pct(curr: float, prev: float) -> Optional[float]:
    if prev == 0:
        return None
    return round((curr - prev) / prev * 100.0, 1)


# ---------------------------------------------------------------------------
def detect(window_days: int = 7) -> PatternReport:
    """Compute window-vs-window metrics and known patterns."""
    metrics: list[WindowMetric] = []

    # ---- State ----
    state_trend = state_repo.trend(days=window_days * 2)
    state_cur, state_prev = _split_two_windows(
        state_trend, getter=lambda r: r.ts, days=window_days
    )

    def state_metric(field: str) -> WindowMetric:
        cur = _avg([getattr(s, field) for s in state_cur])
        prev = _avg([getattr(s, field) for s in state_prev])
        return WindowMetric(
            name=field,
            current=round(cur, 1),
            previous=round(prev, 1),
            delta=round(cur - prev, 1),
            pct_delta=_pct(cur, prev),
        )

    for f in ("focus", "stress", "burnout", "momentum", "confidence", "motivation"):
        metrics.append(state_metric(f))

    # ---- Pattern rules ----
    patterns: list[Pattern] = []

    # 1) Burnout climbing.
    burnout_metric = next((m for m in metrics if m.name == "burnout"), None)
    if burnout_metric and burnout_metric.delta >= 10:
        patterns.append(
            Pattern(
                code="burnout_climbing",
                severity="alert",
                label="Burnout is climbing",
                explanation=(
                    "Burnout score is meaningfully higher than the previous window. "
                    "Time to deliberately reduce scope, not push harder."
                ),
                evidence={
                    "burnout_now": burnout_metric.current,
                    "burnout_prev": burnout_metric.previous,
                },
            )
        )

    # 2) Momentum recovering.
    momentum_metric = next((m for m in metrics if m.name == "momentum"), None)
    if momentum_metric and momentum_metric.delta >= 10 and momentum_metric.previous < 50:
        patterns.append(
            Pattern(
                code="momentum_recovering",
                severity="info",
                label="Momentum recovering",
                explanation=(
                    "Momentum is rising from a low patch. Whatever you did to come back, keep it small and keep it."
                ),
                evidence={
                    "momentum_now": momentum_metric.current,
                    "momentum_prev": momentum_metric.previous,
                },
            )
        )

    return PatternReport(window_days=window_days, metrics=metrics, patterns=patterns)


__all__ = ["detect", "Pattern", "PatternReport", "WindowMetric"]
