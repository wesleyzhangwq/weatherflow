from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from weatherflow.rhythm.models import (
    ActivityMetadata,
    CheckInSignal,
    CorrectionSignal,
    DimensionEstimate,
    DimensionName,
    Freshness,
    HumanStateSnapshot,
    RhythmSignal,
    TaskBehaviorSignal,
    Trend,
)

SignalFact = tuple[str, RhythmSignal]


BASELINE = {
    DimensionName.ENERGY: 0.55,
    DimensionName.COGNITIVE_LOAD: 0.45,
    DimensionName.FRAGMENTATION: 0.30,
    DimensionName.MOMENTUM: 0.50,
    DimensionName.FRICTION: 0.30,
    DimensionName.RECOVERY_NEED: 0.35,
}


class RhythmEstimator:
    def estimate(
        self,
        workspace_id: str,
        facts: Sequence[SignalFact],
        *,
        now: datetime | None = None,
    ) -> HumanStateSnapshot:
        observed_now = now or datetime.now(UTC)
        values = dict(BASELINE)
        confidence = 0.15
        supporting: list[str] = []
        contradicting: list[str] = []
        observed_times: list[datetime] = []

        for event_id, signal in facts:
            supporting.append(event_id)
            observed_times.append(signal.observed_at)
            if isinstance(signal, ActivityMetadata):
                self._apply_activity(values, signal)
                confidence = max(confidence, 0.60)
            elif isinstance(signal, CorrectionSignal):
                contradicting.extend(item for item in supporting[:-1])
                self._apply_text(values, signal.text, correction=True)
                confidence = 0.95
            elif isinstance(signal, CheckInSignal):
                self._apply_text(values, signal.text, correction=False)
                confidence = max(confidence, 0.82)
            elif isinstance(signal, TaskBehaviorSignal):
                self._apply_task_behavior(values, signal)
                confidence = max(confidence, 0.45)

        latest = max(observed_times, default=observed_now)
        age = observed_now - latest
        if not facts or age > timedelta(hours=2):
            freshness = Freshness.EXPIRED
        elif age > timedelta(minutes=30):
            freshness = Freshness.AGING
            confidence *= 0.65
        else:
            freshness = Freshness.FRESH
        estimates = {
            name: DimensionEstimate(
                value=_clamp(value),
                confidence=_clamp(confidence),
                trend=Trend.STEADY,
                supporting_event_ids=tuple(supporting),
                contradicting_event_ids=tuple(dict.fromkeys(contradicting)),
                freshness=freshness,
            )
            for name, value in values.items()
        }
        window_start = min(observed_times, default=observed_now)
        return HumanStateSnapshot.new(
            workspace_id=workspace_id,
            observed_at=observed_now,
            window_start=window_start,
            window_end=observed_now,
            dimensions=estimates,
            summary=self._summary(values, confidence, freshness),
            supporting_event_ids=tuple(supporting),
            contradicting_event_ids=tuple(dict.fromkeys(contradicting)),
            valid_until=latest + timedelta(minutes=30),
            freshness=freshness,
        )

    @staticmethod
    def _apply_activity(values: dict[DimensionName, float], signal: ActivityMetadata) -> None:
        total = max(signal.active_seconds + signal.idle_seconds, 1)
        active_ratio = signal.active_seconds / total
        idle_ratio = signal.idle_seconds / total
        minutes = max((signal.window_end - signal.window_start).total_seconds() / 60, 1)
        switch_pressure = min(1.0, signal.app_switch_count / (minutes * 2))
        communication = signal.category_seconds.get("communication", 0) / total
        development = signal.category_seconds.get("development", 0) / total
        values[DimensionName.ENERGY] = 0.35 + active_ratio * 0.40 - idle_ratio * 0.10
        values[DimensionName.COGNITIVE_LOAD] = 0.35 + communication * 0.35 + switch_pressure * 0.25
        values[DimensionName.FRAGMENTATION] = 0.20 + switch_pressure * 0.75
        values[DimensionName.MOMENTUM] = 0.35 + development * 0.45 - idle_ratio * 0.15
        values[DimensionName.FRICTION] = 0.25 + switch_pressure * 0.20
        values[DimensionName.RECOVERY_NEED] = 0.30 + active_ratio * 0.30

    @staticmethod
    def _apply_text(values: dict[DimensionName, float], text: str, *, correction: bool) -> None:
        lowered = text.lower()
        if correction and ("not overloaded" in lowered or "steady" in lowered):
            values.update(BASELINE)
            return
        if any(word in lowered for word in ("overloaded", "overload", "过载")):
            values[DimensionName.COGNITIVE_LOAD] = 0.92
            values[DimensionName.RECOVERY_NEED] = 0.78
            values[DimensionName.ENERGY] = 0.35
        if any(word in lowered for word in ("fragmented", "interrupted", "切换")):
            values[DimensionName.FRAGMENTATION] = 0.88
            values[DimensionName.COGNITIVE_LOAD] = 0.68
        if any(word in lowered for word in ("blocked", "stuck", "卡住")):
            values[DimensionName.FRICTION] = 0.90
            values[DimensionName.MOMENTUM] = 0.20
        if any(word in lowered for word in ("focused", "flow", "专注")):
            values[DimensionName.MOMENTUM] = 0.88
            values[DimensionName.ENERGY] = 0.72
            values[DimensionName.FRAGMENTATION] = 0.15
        if any(word in lowered for word in ("recovery", "rest", "休息")):
            values[DimensionName.RECOVERY_NEED] = 0.90
            values[DimensionName.ENERGY] = 0.22
        if any(word in lowered for word in ("exhausted", "tired", "疲惫")):
            values[DimensionName.ENERGY] = 0.25
            values[DimensionName.RECOVERY_NEED] = 0.85

    @staticmethod
    def _apply_task_behavior(
        values: dict[DimensionName, float], signal: TaskBehaviorSignal
    ) -> None:
        if signal.outcome == "succeeded":
            values[DimensionName.MOMENTUM] += 0.05
            values[DimensionName.FRICTION] -= 0.05
        elif signal.outcome == "failed":
            values[DimensionName.FRICTION] += 0.08
        else:
            values[DimensionName.FRICTION] += 0.04

    @staticmethod
    def _summary(
        values: dict[DimensionName, float], confidence: float, freshness: Freshness
    ) -> str:
        if confidence < 0.35 or freshness is Freshness.EXPIRED:
            return "Insufficient current evidence"
        if values[DimensionName.COGNITIVE_LOAD] >= 0.75:
            return "High load with limited recovery margin"
        if values[DimensionName.FRAGMENTATION] >= 0.65:
            return "Attention is fragmented"
        if values[DimensionName.FRICTION] >= 0.65:
            return "Progress appears blocked"
        if values[DimensionName.RECOVERY_NEED] >= 0.70:
            return "Recovery need is elevated"
        if values[DimensionName.MOMENTUM] >= 0.70:
            return "Focused momentum"
        return "Steady rhythm"


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))
