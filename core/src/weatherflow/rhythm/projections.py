from datetime import UTC, datetime

from weatherflow.rhythm.models import (
    DimensionName,
    Freshness,
    HumanStateSnapshot,
    RhythmPolicy,
    WeatherPresentation,
    WeatherScene,
    WorkMode,
)


def project_weather(
    snapshot: HumanStateSnapshot, *, now: datetime | None = None
) -> WeatherPresentation:
    current = now or datetime.now(UTC)
    dimensions = snapshot.dimensions
    mean_confidence = sum(item.confidence for item in dimensions.values()) / len(dimensions)
    if (
        current >= snapshot.valid_until
        or snapshot.freshness is Freshness.EXPIRED
        or mean_confidence < 0.35
    ):
        scene = WeatherScene.MIXED
        intensity = 0.2
    elif (
        dimensions[DimensionName.COGNITIVE_LOAD].value >= 0.72
        and dimensions[DimensionName.RECOVERY_NEED].value >= 0.60
    ):
        scene = WeatherScene.STORM
        intensity = dimensions[DimensionName.COGNITIVE_LOAD].value
    elif dimensions[DimensionName.FRAGMENTATION].value >= 0.65:
        scene = WeatherScene.FOG
        intensity = dimensions[DimensionName.FRAGMENTATION].value
    elif (
        dimensions[DimensionName.FRICTION].value >= 0.65
        and dimensions[DimensionName.MOMENTUM].value <= 0.40
    ):
        scene = WeatherScene.STILL
        intensity = dimensions[DimensionName.FRICTION].value
    elif (
        dimensions[DimensionName.RECOVERY_NEED].value >= 0.70
        or dimensions[DimensionName.ENERGY].value <= 0.30
    ):
        scene = WeatherScene.NIGHT
        intensity = dimensions[DimensionName.RECOVERY_NEED].value
    elif (
        dimensions[DimensionName.MOMENTUM].value >= 0.70
        and dimensions[DimensionName.ENERGY].value >= 0.55
    ):
        scene = WeatherScene.CLEAR
        intensity = dimensions[DimensionName.MOMENTUM].value
    else:
        scene = WeatherScene.FAIR
        intensity = 0.50
    return WeatherPresentation(
        scene=scene,
        intensity=intensity,
        transition="steady",
        snapshot_id=snapshot.id,
        valid_until=snapshot.valid_until,
    )


def project_policy(snapshot: HumanStateSnapshot, *, now: datetime | None = None) -> RhythmPolicy:
    scene = project_weather(snapshot, now=now).scene
    common = {
        "reason_refs": snapshot.supporting_event_ids,
        "valid_until": snapshot.valid_until,
    }
    if scene is WeatherScene.STORM:
        return RhythmPolicy(
            interaction_budget="minimal",
            response_density="compact",
            delegation_bias="favor",
            scope_pressure="reduce",
            work_mode=WorkMode.SINGLE_THREAD,
            **common,
        )
    if scene is WeatherScene.FOG:
        return RhythmPolicy(
            interaction_budget="minimal",
            response_density="compact",
            delegation_bias="neutral",
            scope_pressure="hold",
            work_mode=WorkMode.SINGLE_THREAD,
            **common,
        )
    if scene is WeatherScene.STILL:
        return RhythmPolicy(
            interaction_budget="normal",
            response_density="detailed",
            delegation_bias="favor",
            scope_pressure="hold",
            work_mode=WorkMode.DIAGNOSTIC,
            **common,
        )
    if scene is WeatherScene.NIGHT:
        return RhythmPolicy(
            interaction_budget="minimal",
            response_density="compact",
            delegation_bias="favor",
            scope_pressure="reduce",
            work_mode=WorkMode.SINGLE_THREAD,
            **common,
        )
    return RhythmPolicy(
        interaction_budget="normal",
        response_density="normal",
        delegation_bias="neutral",
        scope_pressure="hold",
        work_mode=WorkMode.NORMAL,
        **common,
    )
