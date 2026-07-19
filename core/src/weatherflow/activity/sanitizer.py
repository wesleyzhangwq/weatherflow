from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from weatherflow.activity.models import ObservedActivityFact


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
            "awsaccesskeyid",
            "client_secret",
            "code",
            "cookie",
            "credential",
            "id_token",
            "key",
            "oauth_token",
            "password",
            "refresh_token",
            "secret",
            "sig",
            "signature",
            "token",
            "x-amz-credential",
            "x-amz-security-token",
            "x-amz-signature",
            "x-goog-credential",
            "x-goog-signature",
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
            r"\b(?:api[_ -]?key|access[_ -]?token|secret|password|cookie)"
            r"\s*[:=]\s*[^\s&]+",
            re.IGNORECASE,
        ),
    )

    def sanitize(self, fact: ObservedActivityFact) -> SanitizedActivity:
        event = fact.model_dump(mode="json")
        redaction_count = 0
        for key, value in tuple(event.items()):
            if not isinstance(value, str):
                continue
            if key == "url":
                event[key], count = self._sanitize_url(value)
            else:
                event[key], count = self._sanitize_text(value)
            redaction_count += count
        serialized = json.dumps(
            event,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return SanitizedActivity(
            event=event,
            redaction_count=redaction_count,
            serialized=serialized,
        )

    def serialize_untrusted(self, facts: list[ObservedActivityFact]) -> str:
        events = [self.sanitize(fact).event for fact in facts]
        serialized = json.dumps(
            events,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return f"<untrusted_activity_data>\n{serialized}\n</untrusted_activity_data>"

    def sanitize_text(self, value: str) -> tuple[str, int]:
        return self._sanitize_text(value)

    def _sanitize_url(self, value: str) -> tuple[str, int]:
        try:
            parsed = urlsplit(value)
            hostname = parsed.hostname or ""
            port = parsed.port
        except ValueError:
            return self._sanitize_text(value)
        count = 0
        if parsed.username is not None or parsed.password is not None:
            count += 1
        if port is not None:
            hostname = f"{hostname}:{port}"

        query: list[tuple[str, str]] = []
        for key, query_value in parse_qsl(parsed.query, keep_blank_values=True):
            if self._sensitive_query_key(key):
                query.append((key, "[REDACTED]"))
                count += 1
            else:
                sanitized, replacements = self._sanitize_text(query_value)
                query.append((key, sanitized))
                count += replacements
        if parsed.fragment:
            count += 1
        path, path_count = self._sanitize_text(parsed.path)
        count += path_count
        return (
            urlunsplit(
                (
                    parsed.scheme,
                    hostname,
                    path,
                    urlencode(query, doseq=True),
                    "",
                )
            ),
            count,
        )

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
