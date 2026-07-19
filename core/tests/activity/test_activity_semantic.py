from datetime import UTC, datetime, timedelta

from weatherflow.activity import (
    ActivityCoverageStatus,
    ActivitySemanticQueryService,
    ActivityService,
    ActivitySourceHealth,
    ActivityWatchBucket,
    ActivityWatchEvent,
    ActivityWatchInfo,
)


class StubRepository:
    pass


class FakeActivityWatch:
    def __init__(self, start: datetime) -> None:
        self.start = start
        self.query_statements: tuple[str, ...] = ()
        self.event_calls: list[tuple[str, datetime, datetime, int]] = []
        self._buckets = [
            ActivityWatchBucket(
                id="window-local",
                type="currentwindow",
                client="aw-watcher-window",
                hostname="host",
                metadata={"start": start, "end": start + timedelta(hours=1)},
            ),
            ActivityWatchBucket(
                id="afk-local",
                type="afkstatus",
                client="aw-watcher-afk",
                hostname="host",
                metadata={"start": start, "end": start + timedelta(hours=1)},
            ),
            ActivityWatchBucket(
                id="web-local",
                type="web.tab.current",
                client="aw-watcher-web",
                hostname="host",
                metadata={"start": start, "end": start + timedelta(hours=1)},
            ),
            ActivityWatchBucket(
                id="window-old-host",
                type="currentwindow",
                client="aw-watcher-window",
                hostname="old-host",
                metadata={"start": start, "end": start + timedelta(hours=1)},
            ),
        ]

    async def info(self):
        return ActivityWatchInfo(hostname="host", version="v0.13.1", device_id="device")

    async def buckets(self):
        return list(self._buckets)

    async def classes(self):
        return [
            {
                "name": ["Work", "Programming"],
                "rule": {
                    "type": "regex",
                    "regex": r"Visual\s+Studio\s+Code",
                },
            },
            {"name": ["Uncategorized"], "rule": {"type": None}},
        ]

    async def settings(self):
        return {"classes": await self.classes()}

    async def events(self, bucket_id, *, start, end, limit=5_000):
        self.event_calls.append((bucket_id, start, end, limit))
        events = {
            "window-local": [
                ActivityWatchEvent(
                    id="1",
                    bucket_id=bucket_id,
                    timestamp=self.start,
                    duration=600,
                    data={"app": "Visual Studio Code", "title": "WeatherFlow"},
                ),
                ActivityWatchEvent(
                    id="2",
                    bucket_id=bucket_id,
                    timestamp=self.start + timedelta(minutes=10),
                    duration=600,
                    data={"app": "Safari", "title": "Docs"},
                ),
            ],
            "afk-local": [
                ActivityWatchEvent(
                    id="active-1",
                    bucket_id=bucket_id,
                    timestamp=self.start,
                    duration=300,
                    data={"status": "not-afk"},
                ),
                ActivityWatchEvent(
                    id="afk-1",
                    bucket_id=bucket_id,
                    timestamp=self.start + timedelta(minutes=5),
                    duration=150,
                    data={"status": "afk"},
                ),
                ActivityWatchEvent(
                    id="active-2",
                    bucket_id=bucket_id,
                    timestamp=self.start + timedelta(minutes=7, seconds=30),
                    duration=750,
                    data={"status": "not-afk"},
                ),
            ],
            "web-local": [
                ActivityWatchEvent(
                    id="1",
                    bucket_id=bucket_id,
                    timestamp=self.start + timedelta(minutes=10),
                    duration=600,
                    data={
                        "url": "https://example.com/docs",
                        "title": "Docs",
                    },
                )
            ],
            "web-firefox": [
                ActivityWatchEvent(
                    id="firefox-1",
                    bucket_id=bucket_id,
                    timestamp=self.start + timedelta(minutes=2),
                    duration=60,
                    data={
                        "url": "https://mozilla.example/reference",
                        "title": "Reference",
                    },
                )
            ],
            "window-old-host": [
                ActivityWatchEvent(
                    id="old",
                    bucket_id=bucket_id,
                    timestamp=self.start,
                    duration=3600,
                    data={"app": "Must not double count", "title": "old"},
                )
            ],
        }[bucket_id]
        return [event for event in events if event.timestamp < end and event.ended_at > start][
            :limit
        ]

    async def query(self, *, start, end, statements):
        self.query_statements = tuple(statements)
        return [
            [
                {
                    "duration": 1050,
                    "data": {"$category": ["Work", "Programming"]},
                }
            ]
        ]

    async def close(self):
        return None


async def test_statistics_use_one_host_and_do_not_add_browser_to_active_time() -> None:
    start = datetime(2026, 7, 16, 0, tzinfo=UTC)
    client = FakeActivityWatch(start)
    service = ActivitySemanticQueryService(
        client=client,
        repository=StubRepository(),
    )

    statistics = await service.statistics(
        start=start,
        end=start + timedelta(minutes=20),
    )

    assert statistics.active_seconds == 1050
    assert statistics.afk_seconds == 150
    assert statistics.browser_seconds == 600
    assert statistics.application_seconds == {
        "Visual Studio Code": 450,
        "Safari": 600,
    }
    assert statistics.category_seconds == {"Work / Programming": 1050}
    assert statistics.app_switch_count == 1
    assert statistics.category_switch_count == 1
    assert statistics.observed_seconds == 1200
    assert statistics.unobserved_seconds == 0
    assert statistics.window_observed_seconds == 1200
    assert statistics.afk_observed_seconds == 1200
    assert statistics.web_observed_seconds == 600
    assert statistics.coverage_ratio == 1
    assert statistics.coverage_status is ActivityCoverageStatus.COMPLETE
    assert statistics.source_bucket_ids == (
        "window-local",
        "afk-local",
        "web-local",
    )
    assert all(call[0] != "window-old-host" for call in client.event_calls)
    assert "find_bucket" not in "\n".join(client.query_statements)
    assert 'query_bucket("window-local")' in client.query_statements[1]
    assert r'"regex":"Visual\s+Studio\s+Code"' in client.query_statements[0]
    assert r'"regex":"Visual\\s+Studio\\s+Code"' not in client.query_statements[0]


async def test_context_pack_reuses_the_complete_window_read_for_a_precise_safe_sequence() -> None:
    start = datetime(2026, 7, 16, 0, tzinfo=UTC)
    service = ActivitySemanticQueryService(
        client=FakeActivityWatch(start),
        repository=StubRepository(),
    )

    window = await service.collect_window(
        start=start,
        end=start + timedelta(minutes=20),
    )
    assert window.context_pack is not None
    pack = window.context_pack

    assert pack.window_start.isoformat() == "2026-07-16T08:00:00+08:00"
    assert pack.statistics.active_seconds == 1050
    assert pack.statistics.category_seconds == {"Work / Programming": 1050}
    assert any(item.title == "WeatherFlow" for item in pack.evidence)
    assert any(item.domain == "example.com" for item in pack.evidence)
    assert all(item.url is None for item in pack.evidence)
    assert [item.category for item in pack.category_episodes][-1] == "Uncategorized"
    assert pack.category_transitions[-1].to_category == "Uncategorized"
    serialized = pack.model_dump_json()
    assert "window-local" not in serialized
    assert '"event_id"' not in serialized
    persisted_digests = {reference.event_digest for reference in window.evidence_refs}
    referenced_digests = (
        {item.evidence_key for item in pack.evidence}
        | {key for episode in pack.category_episodes for key in episode.evidence_keys}
        | {key for transition in pack.category_transitions for key in transition.evidence_keys}
        | {key for interval in pack.afk_intervals for key in interval.evidence_keys}
    )
    assert referenced_digests <= persisted_digests


async def test_dashboard_statistics_and_timeline_share_one_complete_source_read() -> None:
    start = datetime(2026, 7, 16, 0, tzinfo=UTC)
    client = FakeActivityWatch(start)
    service = ActivitySemanticQueryService(
        client=client,
        repository=StubRepository(),
    )

    dashboard = await service.dashboard_window(
        start=start,
        end=start + timedelta(minutes=20),
        limit=1,
    )

    calls_by_bucket: dict[str, int] = {}
    for bucket_id, *_rest in client.event_calls:
        calls_by_bucket[bucket_id] = calls_by_bucket.get(bucket_id, 0) + 1
    assert calls_by_bucket == {
        "window-local": 1,
        "afk-local": 1,
        "web-local": 1,
    }
    assert dashboard.statistics.active_seconds == 1050
    assert len(dashboard.timeline.facts) == 1
    assert dashboard.timeline.facts[0].timestamp == start + timedelta(minutes=10)
    assert dashboard.timeline.truncated is True


async def test_watch_timeline_starts_at_the_latest_interval_and_moves_backwards() -> None:
    start = datetime(2026, 7, 16, 0, tzinfo=UTC)
    service = ActivitySemanticQueryService(
        client=FakeActivityWatch(start),
        repository=StubRepository(),
    )

    timeline = await service.timeline(
        start=start,
        end=start + timedelta(minutes=20),
        limit=3,
    )

    assert [fact.ended_at for fact in timeline.facts] == sorted(
        (fact.ended_at for fact in timeline.facts),
        reverse=True,
    )
    assert timeline.facts[0].timestamp == start + timedelta(minutes=10)


async def test_statistics_merge_all_local_browser_buckets() -> None:
    start = datetime(2026, 7, 16, 0, tzinfo=UTC)
    client = FakeActivityWatch(start)
    client._buckets.append(
        ActivityWatchBucket(
            id="web-firefox",
            type="web.tab.current",
            client="aw-watcher-web-firefox",
            hostname="host",
            metadata={"start": start, "end": start + timedelta(hours=1)},
        )
    )
    service = ActivitySemanticQueryService(
        client=client,
        repository=StubRepository(),
    )

    statistics = await service.statistics(
        start=start,
        end=start + timedelta(minutes=20),
    )

    assert statistics.browser_seconds == 660
    assert statistics.domain_seconds == {
        "example.com": 600,
        "mozilla.example": 60,
    }
    assert statistics.source_bucket_ids == (
        "window-local",
        "afk-local",
        "web-firefox",
        "web-local",
    )


async def test_historical_query_uses_intersecting_rotated_host_bucket() -> None:
    historical = datetime(2026, 7, 1, 0, tzinfo=UTC)
    client = FakeActivityWatch(historical)
    current_start = historical + timedelta(days=15)
    client._buckets[0] = ActivityWatchBucket(
        id="window-local",
        type="currentwindow",
        client="aw-watcher-window",
        hostname="host",
        metadata={"start": current_start, "end": current_start + timedelta(hours=1)},
    )
    client._buckets[1] = ActivityWatchBucket(
        id="afk-local",
        type="afkstatus",
        client="aw-watcher-afk",
        hostname="host",
        metadata={"start": current_start, "end": current_start + timedelta(hours=1)},
    )
    client._buckets[3] = ActivityWatchBucket(
        id="window-old-host",
        type="currentwindow",
        client="aw-watcher-window",
        hostname="old-host",
        metadata={"start": historical, "end": historical + timedelta(hours=1)},
    )
    client._buckets.append(
        ActivityWatchBucket(
            id="afk-old-host",
            type="afkstatus",
            client="aw-watcher-afk",
            hostname="old-host",
            metadata={"start": historical, "end": historical + timedelta(hours=1)},
        )
    )
    original_events = client.events

    async def events(bucket_id, *, start, end, limit=5_000):
        if bucket_id == "afk-old-host":
            return [
                ActivityWatchEvent(
                    id="old-afk",
                    bucket_id=bucket_id,
                    timestamp=historical,
                    duration=1200,
                    data={"status": "not-afk"},
                )
            ]
        return await original_events(
            bucket_id,
            start=start,
            end=end,
            limit=limit,
        )

    client.events = events
    service = ActivitySemanticQueryService(
        client=client,
        repository=StubRepository(),
    )

    result = await service.query_range(
        start=historical,
        end=historical + timedelta(minutes=20),
    )

    assert {fact.bucket_id for fact in result.facts} == {
        "window-old-host",
        "afk-old-host",
    }


async def test_statistics_merge_paired_source_segments_across_host_rotation() -> None:
    start = datetime(2026, 7, 16, 0, tzinfo=UTC)
    switch = start + timedelta(minutes=10)
    end = start + timedelta(minutes=20)

    class RotatedActivityWatch:
        async def info(self):
            return ActivityWatchInfo(
                hostname="current-host",
                version="v0.13.1",
                device_id="device",
            )

        async def buckets(self):
            return [
                ActivityWatchBucket(
                    id="window-old",
                    type="currentwindow",
                    client="aw-watcher-window",
                    hostname="old-host",
                    metadata={"start": start, "end": switch},
                ),
                ActivityWatchBucket(
                    id="afk-old",
                    type="afkstatus",
                    client="aw-watcher-afk",
                    hostname="old-host",
                    metadata={"start": start, "end": switch},
                ),
                ActivityWatchBucket(
                    id="window-current",
                    type="currentwindow",
                    client="aw-watcher-window",
                    hostname="current-host",
                    metadata={"start": switch, "end": end},
                ),
                ActivityWatchBucket(
                    id="afk-current",
                    type="afkstatus",
                    client="aw-watcher-afk",
                    hostname="current-host",
                    metadata={"start": switch, "end": end},
                ),
            ]

        async def classes(self):
            return []

        async def events(self, bucket_id, *, start, end, limit=5_000):
            source = {
                "window-old": ActivityWatchEvent(
                    id="old-window",
                    bucket_id=bucket_id,
                    timestamp=start if start > globals_start else globals_start,
                    duration=600,
                    data={"app": "Old Editor", "title": "Old"},
                ),
                "afk-old": ActivityWatchEvent(
                    id="old-afk",
                    bucket_id=bucket_id,
                    timestamp=globals_start,
                    duration=600,
                    data={"status": "not-afk"},
                ),
                "window-current": ActivityWatchEvent(
                    id="current-window",
                    bucket_id=bucket_id,
                    timestamp=switch,
                    duration=600,
                    data={"app": "Current Editor", "title": "Current"},
                ),
                "afk-current": ActivityWatchEvent(
                    id="current-afk",
                    bucket_id=bucket_id,
                    timestamp=switch,
                    duration=600,
                    data={"status": "not-afk"},
                ),
            }[bucket_id]
            return [source] if source.timestamp < end and source.ended_at > start else []

        async def query(self, *, start, end, statements):
            assert (
                'query_bucket("window-old")' in statements[1]
                or 'query_bucket("window-current")' in statements[1]
            )
            return [
                [
                    {
                        "duration": (end - start).total_seconds(),
                        "data": {"$category": ["Uncategorized"]},
                    }
                ]
            ]

    globals_start = start
    client = RotatedActivityWatch()
    service = ActivitySemanticQueryService(
        client=client,
        repository=StubRepository(),
    )

    statistics = await service.statistics(start=start, end=end)

    assert statistics.active_seconds == 1200
    assert statistics.application_seconds == {
        "Old Editor": 600,
        "Current Editor": 600,
    }
    assert statistics.coverage_status is ActivityCoverageStatus.COMPLETE
    assert statistics.source_bucket_ids == (
        "window-old",
        "afk-old",
        "window-current",
        "afk-current",
    )


async def test_current_state_keeps_window_as_application_and_web_as_context() -> None:
    now = datetime(2026, 7, 16, 0, 20, tzinfo=UTC)
    client = FakeActivityWatch(now - timedelta(minutes=20))
    service = ActivitySemanticQueryService(
        client=client,
        repository=StubRepository(),
    )

    current = await service.current_state(now=now)

    assert current.observed is not None
    assert current.observed.kind.value == "window"
    assert current.observed.application == "Safari"
    assert current.web_context is not None
    assert current.web_context.kind.value == "web"


async def test_current_state_semantic_query_contains_observed_facts_only() -> None:
    now = datetime(2026, 7, 16, 0, 20, tzinfo=UTC)
    service = ActivityService(
        client=FakeActivityWatch(now - timedelta(minutes=20)),
        repository=StubRepository(),
    )

    result = await service.semantic_query("current_state", {}, time_anchor=now)

    assert result["source_health"] == "available"
    assert result["afk_state"] == "active"
    assert result["untrusted_activity_data"]
    assert "inference" not in result


async def test_current_state_does_not_relabel_stale_events_as_current() -> None:
    start = datetime(2026, 7, 16, 0, tzinfo=UTC)
    client = FakeActivityWatch(start)
    service = ActivitySemanticQueryService(
        client=client,
        repository=StubRepository(),
    )

    current = await service.current_state(now=start + timedelta(hours=2))

    assert current.observed is None
    assert current.web_context is None
    assert current.afk_state.value == "unknown"


async def test_current_state_uses_short_window_and_caps_browser_bucket_fanout() -> None:
    now = datetime(2026, 7, 16, 0, 20, tzinfo=UTC)
    client = FakeActivityWatch(now - timedelta(minutes=20))
    for index in range(30):
        client._buckets.append(
            ActivityWatchBucket(
                id=f"web-extra-{index:02d}",
                type="web.tab.current",
                client=f"aw-watcher-web-{index:02d}",
                hostname="host",
                metadata={
                    "start": now - timedelta(hours=1),
                    "end": now + timedelta(hours=1),
                },
            )
        )
    original_events = client.events

    async def events(bucket_id, *, start, end, limit=5_000):
        if bucket_id.startswith("web-extra-"):
            client.event_calls.append((bucket_id, start, end, limit))
            return []
        return await original_events(
            bucket_id,
            start=start,
            end=end,
            limit=limit,
        )

    client.events = events
    repository = StubRepository()
    service = ActivitySemanticQueryService(
        client=client,
        repository=repository,
    )

    current = await service.current_state(now=now)

    assert current.observed is not None
    assert len(client.event_calls) <= 18
    assert all(call[1] == now - timedelta(minutes=5) for call in client.event_calls)
    assert len({call[0] for call in client.event_calls if call[0].startswith("web-")}) <= 16


async def test_afk_remains_available_when_window_watcher_is_missing() -> None:
    start = datetime(2026, 7, 16, 0, tzinfo=UTC)
    client = FakeActivityWatch(start)
    client._buckets = [
        bucket for bucket in client._buckets if "window" not in bucket.id and "web" not in bucket.id
    ]
    service = ActivitySemanticQueryService(
        client=client,
        repository=StubRepository(),
    )

    current = await service.current_state(now=start + timedelta(minutes=20))
    window = await service.afk_status(
        start=start,
        end=start + timedelta(minutes=20),
    )

    assert current.source_health is ActivitySourceHealth.AVAILABLE
    assert current.observed is None
    assert current.afk_state.value == "active"
    assert window == {
        "active_seconds": 1050,
        "afk_seconds": 150,
    }


async def test_current_state_reads_observed_facts_without_inference_refresh() -> None:
    start = datetime(2026, 7, 16, 0, tzinfo=UTC)

    class FlakyRefreshActivityWatch(FakeActivityWatch):
        def __init__(self, source_start):
            super().__init__(source_start)
            self.info_calls = 0

        async def info(self):
            self.info_calls += 1
            if self.info_calls > 1:
                raise RuntimeError("transient refresh failure")
            return await super().info()

    client = FlakyRefreshActivityWatch(start)
    service = ActivitySemanticQueryService(
        client=client,
        repository=StubRepository(),
    )

    current = await service.current_state(now=start + timedelta(minutes=20))

    assert current.source_health is ActivitySourceHealth.AVAILABLE
    assert current.observed is not None
    assert current.observed.application == "Safari"
    assert client.info_calls == 1


async def test_filtered_range_reads_complete_source_before_local_filtering() -> None:
    start = datetime(2026, 7, 16, 0, tzinfo=UTC)
    client = FakeActivityWatch(start)
    original_events = client.events

    async def events(bucket_id, *, start, end, limit=5_000):
        if bucket_id != "window-local":
            return await original_events(
                bucket_id,
                start=start,
                end=end,
                limit=limit,
            )
        source = [
            ActivityWatchEvent(
                id=str(index),
                bucket_id=bucket_id,
                timestamp=client.start + timedelta(minutes=index),
                duration=60,
                data={
                    "app": "Target" if index == 3 else "Noise",
                    "title": str(index),
                },
            )
            for index in range(4)
        ]
        return [event for event in source if event.timestamp < end and event.ended_at > start][
            :limit
        ]

    client.events = events
    service = ActivitySemanticQueryService(
        client=client,
        repository=StubRepository(),
    )
    service.max_events_per_bucket = 2

    result = await service.query_range(
        start=start,
        end=start + timedelta(minutes=4),
        app_name="Target",
        limit=1,
    )

    assert [fact.application for fact in result.facts] == ["Target"]
    assert result.truncated is False


async def test_switches_during_afk_are_not_counted_as_active_context_switches() -> None:
    start = datetime(2026, 7, 16, 0, tzinfo=UTC)
    client = FakeActivityWatch(start)
    original_events = client.events

    async def events(bucket_id, *, start, end, limit=5_000):
        if bucket_id != "window-local":
            return await original_events(
                bucket_id,
                start=start,
                end=end,
                limit=limit,
            )
        source = [
            ActivityWatchEvent(
                id="before",
                bucket_id=bucket_id,
                timestamp=client.start,
                duration=300,
                data={"app": "Code", "title": "Before"},
            ),
            ActivityWatchEvent(
                id="during",
                bucket_id=bucket_id,
                timestamp=client.start + timedelta(minutes=5),
                duration=150,
                data={"app": "Mail", "title": "During AFK"},
            ),
            ActivityWatchEvent(
                id="after",
                bucket_id=bucket_id,
                timestamp=client.start + timedelta(minutes=7, seconds=30),
                duration=750,
                data={"app": "Code", "title": "After"},
            ),
        ]
        return [event for event in source if event.timestamp < end and event.ended_at > start][
            :limit
        ]

    client.events = events
    service = ActivitySemanticQueryService(
        client=client,
        repository=StubRepository(),
    )

    statistics = await service.statistics(
        start=start,
        end=start + timedelta(minutes=20),
    )

    assert statistics.app_switch_count == 0
