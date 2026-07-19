from __future__ import annotations

from datetime import UTC, datetime

from weatherflow.activity import (
    CategoryMatcher,
    ObservedActivityFact,
    category_rule_version,
)


def test_category_rule_version_is_canonical_and_order_sensitive() -> None:
    first = [
        {
            "name": ["Work", "Programming"],
            "rule": {
                "regex": "GitHub|vim",
                "type": "regex",
                "select_keys": ["app", "title"],
            },
            "data": {"score": 10, "color": "#0F0"},
        },
        {
            "name": ["Work", "Programming", "Editor"],
            "rule": {"regex": "^vim$", "type": "regex", "ignore_case": True},
        },
        {"name": ["Uncategorized"], "rule": {"type": None}},
    ]
    same = [
        {
            "data": {"color": "#0F0", "score": 10},
            "rule": {
                "type": "regex",
                "regex": "GitHub|vim",
                "select_keys": ["app", "title"],
            },
            "name": ["Work", "Programming"],
        },
        {
            "rule": {"ignore_case": True, "type": "regex", "regex": "^vim$"},
            "name": ["Work", "Programming", "Editor"],
        },
        {"rule": {"type": None}, "name": ["Uncategorized"]},
    ]
    reordered = list(reversed(first))

    one = category_rule_version(first)
    two = category_rule_version(same)
    three = category_rule_version(reordered)

    assert one.id == two.id
    assert one.canonical_json == two.canonical_json
    assert one.id != three.id
    assert len(one.id) == 64
    assert one.rule_count == 2


def test_category_matcher_mirrors_deepest_and_later_activitywatch_rule() -> None:
    matcher = CategoryMatcher(
        [
            {"name": ["Work"], "rule": {"type": "regex", "regex": "Code"}},
            {
                "name": ["Work", "Programming"],
                "rule": {
                    "type": "regex",
                    "regex": "^visual studio code$",
                    "ignore_case": True,
                    "select_keys": ["app"],
                },
            },
            {
                "name": ["Other", "SameDepth"],
                "rule": {"type": "regex", "regex": "Code"},
            },
        ]
    )
    fact = ObservedActivityFact(
        kind="window",
        bucket_id="window",
        event_id="1",
        timestamp=datetime(2026, 7, 16, tzinfo=UTC),
        duration=60,
        application="Visual Studio Code",
        title="WeatherFlow",
    )

    assert matcher.match(fact) == "Other / SameDepth"
