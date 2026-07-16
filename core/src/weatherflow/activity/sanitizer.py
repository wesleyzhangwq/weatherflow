from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from weatherflow.activity.models import ActivityHeartbeat, ActivityInterval


@dataclass(frozen=True)
class SanitizedActivity:
    event: dict[str, Any]
    redaction_count: int
    serialized: str


class ActivitySanitizer:
    _SENSITIVE_QUERY_KEYS = frozenset(
        {
            "access_token",
            "api_key",
            "apikey",
            "auth",
            "authorization",
            "client_secret",
            "code",
            "credential",
            "id_token",
            "key",
            "oauth_token",
            "password",
            "refresh_token",
            "secret",
            "signature",
            "sig",
            "token",
            "x-amz-credential",
            "x-amz-security-token",
            "x-amz-signature",
            "x-goog-credential",
            "x-goog-signature",
            "awsaccesskeyid",
        }
    )
    _SECRET_PATTERNS = (
        re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
        re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
        re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
        re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
        re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{6,}\b"),
        re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}", re.IGNORECASE),
        re.compile(
            r"\b(?:api[_ -]?key|access[_ -]?token|secret|password)\s*[:=]\s*[^\s&]+",
            re.IGNORECASE,
        ),
    )

    def sanitize(self, interval: ActivityInterval) -> SanitizedActivity:
        event = interval.model_dump(mode="json")
        redaction_count = 0
        for key, value in tuple(event.items()):
            if not isinstance(value, str):
                continue
            if key == "url":
                event[key], count = self._sanitize_url(value)
            else:
                event[key], count = self._sanitize_text(value)
            redaction_count += count
        serialized = json.dumps(event, ensure_ascii=False, sort_keys=True)
        return SanitizedActivity(
            event=event,
            redaction_count=redaction_count,
            serialized=serialized,
        )

    def sanitize_heartbeat(
        self,
        heartbeat: ActivityHeartbeat,
    ) -> tuple[ActivityHeartbeat, int]:
        payload = heartbeat.model_dump(mode="python")
        redaction_count = 0
        for key, value in tuple(payload.items()):
            if not isinstance(value, str):
                continue
            if key == "url":
                payload[key], count = self._sanitize_url(value, drop_fragment=False)
            else:
                payload[key], count = self._sanitize_text(value)
            redaction_count += count
        return ActivityHeartbeat.model_validate(payload), redaction_count

    def serialize_untrusted(self, intervals: list[ActivityInterval]) -> str:
        events = [self.sanitize(interval).event for interval in intervals]
        serialized = json.dumps(events, ensure_ascii=False, sort_keys=True)
        return f"<untrusted_activity_data>\n{serialized}\n</untrusted_activity_data>"

    def _sanitize_url(
        self,
        value: str,
        *,
        drop_fragment: bool = True,
    ) -> tuple[str, int]:
        parsed = urlsplit(value)
        count = 0
        hostname = parsed.hostname or ""
        if parsed.username is not None or parsed.password is not None:
            count += 1
        if parsed.port is not None:
            hostname = f"{hostname}:{parsed.port}"

        query: list[tuple[str, str]] = []
        for key, query_value in parse_qsl(parsed.query, keep_blank_values=True):
            if self._sensitive_query_key(key):
                query.append((key, "[REDACTED]"))
                count += 1
            else:
                sanitized, replacements = self._sanitize_text(query_value)
                query.append((key, sanitized))
                count += replacements
        fragment = ""
        if parsed.fragment:
            if drop_fragment:
                count += 1
            else:
                fragment, fragment_count = self._sanitize_fragment(parsed.fragment)
                count += fragment_count
        path, path_count = self._sanitize_text(parsed.path)
        count += path_count
        return (
            urlunsplit(
                (
                    parsed.scheme,
                    hostname,
                    path,
                    urlencode(query, doseq=True),
                    fragment,
                )
            ),
            count,
        )

    def _sanitize_fragment(self, fragment: str) -> tuple[str, int]:
        if "=" not in fragment and "&" not in fragment:
            return self._sanitize_text(fragment)
        values: list[tuple[str, str]] = []
        count = 0
        for key, value in parse_qsl(fragment, keep_blank_values=True):
            if self._sensitive_query_key(key):
                values.append((key, "[REDACTED]"))
                count += 1
            else:
                sanitized, replacements = self._sanitize_text(value)
                values.append((key, sanitized))
                count += replacements
        return urlencode(values, doseq=True), count

    @classmethod
    def _sensitive_query_key(cls, key: str) -> bool:
        normalized = key.casefold().replace("-", "_")
        compact = normalized.replace("_", "")
        if normalized in cls._SENSITIVE_QUERY_KEYS or compact in cls._SENSITIVE_QUERY_KEYS:
            return True
        return normalized.endswith(
            (
                "_api_key",
                "_credential",
                "_oauth_code",
                "_password",
                "_secret",
                "_signature",
                "_token",
            )
        )

    def _sanitize_text(self, value: str) -> tuple[str, int]:
        count = 0
        sanitized = value
        for pattern in self._SECRET_PATTERNS:
            sanitized, replacements = pattern.subn("[REDACTED]", sanitized)
            count += replacements
        return sanitized, count
