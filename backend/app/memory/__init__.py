"""Memory System — the soul of WeatherFlow.

Memory matters more than the LLM. Layers:
- ``store``    : connection + schema migration
- ``episodic`` : recent events + FTS5 search
- ``semantic`` : long-term user-model KV
- ``timeline`` : growth milestones / phase changes
- ``vector``   : embedding storage abstraction (SQLite BLOB default,
                 Qdrant adapter reserved)
- ``schemas``  : pydantic models
"""

from app.memory.store import get_conn, init_db  # re-export

__all__ = ["get_conn", "init_db"]
