#!/usr/bin/env python3
"""rebuild_memory.py — Rebuild L2.5 semantic memory from L1.

Per weatherflow-architecture-v2.md §13.4, this script proves the
"derived projection" invariant: delete Qdrant data and rebuild from L1.

Usage:
    python scripts/rebuild_memory.py [--user-id default] [--dry-run]

Idempotent: can be run multiple times without duplicate entries.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.memory import event_log
from app.memory.semantic.projector import _is_projectable, _render_for_memory

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def rebuild(user_id: str, dry_run: bool = False) -> dict:
    """Rebuild mem0 from L1 events. Returns stats dict."""
    stats = {"total_events": 0, "projectable": 0, "projected": 0, "errors": 0}

    # Fetch all events for the user
    all_events = event_log.list_recent(types=None, limit=10000)
    user_events = [e for e in all_events if e.user_id == user_id]
    stats["total_events"] = len(user_events)

    logger.info("Found %d events for user %s", len(user_events), user_id)

    if not dry_run:
        try:
            from mem0 import Memory
            from app.config import get_settings

            settings = get_settings()
            config = {
                "vector_store": {
                    "provider": "qdrant",
                    "config": {
                        "host": settings.qdrant_url.replace("http://", "").split(":")[0],
                        "port": int(settings.qdrant_url.split(":")[-1]) if ":" in settings.qdrant_url.split("//")[-1] else 6333,
                        "collection_name": settings.qdrant_collection,
                    },
                },
            }

            m = Memory.from_config(config)

            # Clear existing memories for this user
            try:
                m.delete_all(user_id=user_id)
                logger.info("Cleared existing memories for user %s", user_id)
            except Exception:
                logger.warning("Could not clear existing memories (may not exist yet)")

            # Rebuild from L1
            for rec in user_events:
                stats["total_events"] += 0  # already counted
                if not _is_projectable(rec):
                    continue
                stats["projectable"] += 1

                try:
                    text = _render_for_memory(rec)
                    metadata = {
                        "source_event_id": rec.id,
                        "event_type": rec.type,
                        "timestamp": rec.timestamp,
                        "user_id": user_id,
                    }
                    m.add(text, user_id=user_id, metadata=metadata)
                    stats["projected"] += 1
                except Exception:
                    logger.exception("Failed to project event %s", rec.id)
                    stats["errors"] += 1

        except ImportError:
            logger.error("mem0 not installed. Install with: pip install mem0ai qdrant-client")
            return stats
    else:
        # Dry run: just count
        for rec in user_events:
            if _is_projectable(rec):
                stats["projectable"] += 1
                logger.info("  [DRY] Would project: %s %s (%s)", rec.type, rec.id, rec.timestamp[:19])

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild L2.5 semantic memory from L1")
    parser.add_argument("--user-id", default="default", help="User ID to rebuild for")
    parser.add_argument("--dry-run", action="store_true", help="Only show what would be projected")
    args = parser.parse_args()

    stats = asyncio.run(rebuild(args.user_id, dry_run=args.dry_run))

    print("\n=== Rebuild Results ===")
    print(f"Total events:    {stats['total_events']}")
    print(f"Projectable:     {stats['projectable']}")
    print(f"Projected:       {stats['projected']}")
    print(f"Errors:          {stats['errors']}")

    if stats["errors"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
