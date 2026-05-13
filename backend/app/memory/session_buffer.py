"""In-memory session buffer — hot short-term window per session_id."""

from __future__ import annotations

from collections import defaultdict, deque
from threading import Lock
from typing import Any, Deque, Dict, List

_MAX_PER_SESSION = 500
_LOCK = Lock()
_BUFFERS: Dict[str, Deque[dict[str, Any]]] = defaultdict(
    lambda: deque(maxlen=_MAX_PER_SESSION)
)


def append(session_id: str, event: dict[str, Any]) -> None:
    sid = session_id or "default"
    with _LOCK:
        _BUFFERS[sid].append(event)


def recent(session_id: str, limit: int = 50) -> List[dict[str, Any]]:
    sid = session_id or "default"
    with _LOCK:
        buf = list(_BUFFERS[sid])
    return buf[-limit:] if limit else buf


def clear(session_id: str) -> None:
    sid = session_id or "default"
    with _LOCK:
        _BUFFERS.pop(sid, None)


__all__ = ["append", "recent", "clear"]
