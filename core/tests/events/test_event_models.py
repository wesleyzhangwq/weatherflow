from datetime import UTC

import pytest
from pydantic import ValidationError

from weatherflow.events.models import Actor, Event, RetentionClass, Sensitivity


def test_event_new_generates_ulid_and_utc_timestamp() -> None:
    event = Event.new(
        type="run.created",
        actor=Actor.USER,
        stream_kind="run",
        stream_id="run-1",
        correlation_id="run-1",
        payload={"intent": "prepare release"},
    )

    assert len(event.id) == 26
    assert event.recorded_at.tzinfo is UTC
    assert event.sensitivity is Sensitivity.NORMAL
    assert event.retention_class is RetentionClass.AUDIT


def test_event_is_immutable() -> None:
    event = Event.new(
        type="run.created",
        actor=Actor.SYSTEM,
        stream_kind="run",
        stream_id="run-1",
        correlation_id="run-1",
        payload={},
    )

    with pytest.raises(ValidationError):
        event.type = "run.changed"
