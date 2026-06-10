#!/usr/bin/env python3
"""Confidence calibration analysis — L3 online eval.

Reads hypothesis + hypothesis_feedback events from L1, computes:
  1. Per-label confirmed/partial/rejected counts
  2. Confidence calibration curve (binned) + ECE
  3. Overall accuracy by source_tag

Usage:
    python scripts/eval_calibration.py                  # default DB
    python scripts/eval_calibration.py --db path/to.db  # explicit DB
    python scripts/eval_calibration.py --json            # machine-readable
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.memory import event_log  # noqa: E402


def _load_pairs(db_path: str | None) -> list[dict]:
    """Join hypothesis events with their feedback."""
    if db_path:
        event_log.init_db(db_path)
        event_log.set_db_path(db_path)

    hypotheses = event_log.list_recent(types=["hypothesis"], limit=10000)
    feedbacks = event_log.list_recent(types=["hypothesis_feedback"], limit=10000)

    fb_map: dict[str, str] = {}
    for fb in feedbacks:
        hid = fb.payload.get("hypothesis_id", "")
        verdict = fb.payload.get("verdict", "")
        if hid and verdict:
            fb_map[hid] = verdict

    pairs = []
    for h in hypotheses:
        verdict = fb_map.get(h.id)
        if verdict is None:
            continue
        pairs.append({
            "id": h.id,
            "label": h.payload.get("label", "?"),
            "confidence": h.payload.get("confidence", 0.0),
            "source_tag": h.payload.get("source_tag", "?"),
            "verdict": verdict,
        })
    return pairs


def _label_breakdown(pairs: list[dict]) -> dict[str, dict[str, int]]:
    breakdown: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for p in pairs:
        breakdown[p["label"]][p["verdict"]] += 1
    return {k: dict(v) for k, v in breakdown.items()}


_BINS = [(0.0, 0.5), (0.5, 0.7), (0.7, 0.9), (0.9, 1.01)]
_BIN_LABELS = ["0.0-0.5", "0.5-0.7", "0.7-0.9", "0.9-1.0"]


def _calibration(pairs: list[dict]) -> tuple[list[dict], float]:
    """Bin hypotheses by confidence, compute actual confirmed rate per bin + ECE."""
    bins: list[list[dict]] = [[] for _ in _BINS]
    for p in pairs:
        c = p["confidence"]
        for i, (lo, hi) in enumerate(_BINS):
            if lo <= c < hi:
                bins[i].append(p)
                break

    rows = []
    ece_sum = 0.0
    total = len(pairs) or 1
    for i, (lo, hi) in enumerate(_BINS):
        bucket = bins[i]
        n = len(bucket)
        if n == 0:
            rows.append({"bin": _BIN_LABELS[i], "n": 0, "avg_conf": 0, "confirmed_rate": 0})
            continue
        avg_conf = sum(p["confidence"] for p in bucket) / n
        confirmed_rate = sum(1 for p in bucket if p["verdict"] == "confirmed") / n
        ece_sum += abs(avg_conf - confirmed_rate) * n
        rows.append({
            "bin": _BIN_LABELS[i],
            "n": n,
            "avg_conf": round(avg_conf, 3),
            "confirmed_rate": round(confirmed_rate, 3),
        })

    ece = round(ece_sum / total, 4)
    return rows, ece


def _source_tag_accuracy(pairs: list[dict]) -> dict[str, dict]:
    by_tag: dict[str, list[dict]] = defaultdict(list)
    for p in pairs:
        by_tag[p["source_tag"]].append(p)
    out = {}
    for tag, items in by_tag.items():
        n = len(items)
        confirmed = sum(1 for p in items if p["verdict"] == "confirmed")
        out[tag] = {"n": n, "confirmed": confirmed, "rate": round(confirmed / n, 3) if n else 0}
    return out


def main():
    parser = argparse.ArgumentParser(description="WeatherFlow confidence calibration eval")
    parser.add_argument("--db", default=None, help="Path to L1 SQLite database")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of text")
    args = parser.parse_args()

    pairs = _load_pairs(args.db)

    if not pairs:
        print("No hypothesis–feedback pairs found. Submit feedback on hypotheses first.")
        return

    breakdown = _label_breakdown(pairs)
    cal_rows, ece = _calibration(pairs)
    tag_acc = _source_tag_accuracy(pairs)

    report = {
        "total_pairs": len(pairs),
        "label_breakdown": breakdown,
        "calibration_bins": cal_rows,
        "ece": ece,
        "source_tag_accuracy": tag_acc,
    }

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return

    print(f"\n{'='*60}")
    print("  WeatherFlow Confidence Calibration Report")
    print(f"  {len(pairs)} hypothesis-feedback pairs")
    print(f"{'='*60}\n")

    print("Label Breakdown:")
    for label, counts in sorted(breakdown.items()):
        total = sum(counts.values())
        parts = ", ".join(f"{v}: {c}" for v, c in sorted(counts.items()))
        print(f"  {label:12s}  n={total:3d}  ({parts})")

    print(f"\nCalibration Curve (ECE = {ece}):")
    print(f"  {'Bin':10s} {'N':>5s} {'Avg Conf':>10s} {'Confirmed%':>12s} {'Gap':>8s}")
    for row in cal_rows:
        gap = abs(row["avg_conf"] - row["confirmed_rate"]) if row["n"] else 0
        print(
            f"  {row['bin']:10s} {row['n']:5d} {row['avg_conf']:10.3f} "
            f"{row['confirmed_rate']:12.3f} {gap:8.3f}"
        )

    print("\nAccuracy by Source Tag:")
    for tag, info in sorted(tag_acc.items()):
        print(f"  {tag:12s}  n={info['n']:3d}  confirmed_rate={info['rate']:.3f}")

    print()


if __name__ == "__main__":
    main()
