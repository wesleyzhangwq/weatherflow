from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from weatherflow.activity.models import (
    CategoryRuleVersion,
    ObservedActivityFact,
    canonical_digest,
)


def normalize_category_rules(raw_rules: Any) -> list[dict[str, Any]]:
    """Return the ordered, JSON-safe ActivityWatch Category rules.

    ActivityWatch Category order is significant because the first matching rule
    wins. Mapping keys are canonicalized by JSON serialization, while list
    order is deliberately retained. Settings entries without an executable rule
    are ignored rather than being mistaken for raw event attributes.
    """

    if isinstance(raw_rules, Mapping):
        raw_rules = raw_rules.get("classes", [])
    if not isinstance(raw_rules, Sequence) or isinstance(raw_rules, (str, bytes)):
        return []

    normalized: list[dict[str, Any]] = []
    for candidate in raw_rules:
        if not isinstance(candidate, Mapping):
            continue
        rule = candidate.get("rule")
        name = candidate.get("name")
        if not isinstance(rule, Mapping):
            continue
        rule_type = rule.get("type")
        if not isinstance(rule_type, str) or not rule_type.strip():
            continue
        if isinstance(name, str):
            names = [name] if name else []
        elif isinstance(name, Sequence) and not isinstance(name, (str, bytes)):
            names = [str(item) for item in name if str(item)]
        else:
            names = []
        if not names:
            continue
        safe = _json_safe(dict(candidate))
        safe["name"] = names
        safe["rule"] = _json_safe(dict(rule))
        normalized.append(safe)
    return normalized


def category_rule_version(raw_rules: Any) -> CategoryRuleVersion:
    normalized = normalize_category_rules(raw_rules)
    canonical_json = json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return CategoryRuleVersion(
        id=canonical_digest(normalized),
        canonical_json=canonical_json,
        rule_count=len(normalized),
    )


class CategoryMatcher:
    """Conservative mirror of ActivityWatch's documented ``Rule`` semantics.

    Server-side ``categorize`` remains authoritative for persisted statistics.
    This evaluator exists for bounded UI filtering and supports only the
    documented regex rule, including ``select_keys`` and ``ignore_case``.
    Unknown future rule types fail closed as non-matches.
    """

    def __init__(self, rules: CategoryRuleVersion | Any) -> None:
        if isinstance(rules, CategoryRuleVersion):
            loaded = json.loads(rules.canonical_json)
        else:
            loaded = normalize_category_rules(rules)
        self.rules: tuple[dict[str, Any], ...] = tuple(loaded)

    def match(self, fact: ObservedActivityFact) -> str:
        values = {
            "app": fact.application or "",
            "title": fact.title or "",
            "url": fact.url or "",
            "domain": fact.domain or "",
        }
        selected = ["Uncategorized"]
        for item in self.rules:
            if self._matches(item["rule"], values):
                candidate = item["name"]
                # ActivityWatch picks the deepest category and biases equal
                # depth toward the later matching rule.
                if len(candidate) >= len(selected):
                    selected = candidate
        return " / ".join(selected)

    def _matches(self, rule: Mapping[str, Any], values: Mapping[str, str]) -> bool:
        rule_type = str(rule.get("type", "")).casefold()
        if rule_type != "regex":
            return False
        pattern = rule.get("regex")
        if not isinstance(pattern, str) or not pattern:
            return False
        selected_keys = rule.get("select_keys")
        if isinstance(selected_keys, Sequence) and not isinstance(selected_keys, (str, bytes)):
            candidates = [values.get(str(key), "") for key in selected_keys]
        else:
            candidates = list(values.values())
        flags = re.IGNORECASE if rule.get("ignore_case") is True else 0
        try:
            expression = re.compile(pattern, flags | re.UNICODE)
        except re.error:
            return False
        return any(expression.search(value) is not None for value in candidates if value)


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_json_safe(item) for item in value]
    return str(value)
