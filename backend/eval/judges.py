"""LLM-as-judge + retrieval metrics for WeatherFlow eval.

Per weatherflow-architecture-v2.md §16.2, judges evaluate:
- Hypothesis faithfulness (evidence source validity)
- Answer groundedness (does answer cite real evidence)
- Retrieval quality (Recall@K, MRR for semantic recall)
"""

from __future__ import annotations

import json
from pathlib import Path


def load_dataset(path: str | None = None) -> list[dict]:
    """Load eval samples from JSON file."""
    if path is None:
        path = str(Path(__file__).parent / "datasets" / "samples.json")
    with open(path) as f:
        return json.load(f)


def judge_faithfulness(sample: dict) -> dict:
    """Judge whether a hypothesis's evidence references are valid.

    Returns: {"pass": bool, "details": str}
    """
    inp = sample["input"]
    hyp = inp["hypothesis"]
    bundle_ids = set(inp["bundle_event_ids"])
    expected = sample["expected_faithful"]

    # Check all evidence source_event_ids
    all_evidence = hyp.get("evidence", []) + hyp.get("counter_evidence", [])
    invalid_refs = []
    for ev in all_evidence:
        sid = ev.get("source_event_id", "")
        if sid and sid not in bundle_ids:
            invalid_refs.append(sid)

    passed = len(invalid_refs) == 0
    return {
        "id": sample["id"],
        "type": "faithfulness",
        "pass": passed == expected,
        "expected": expected,
        "actual": passed,
        "details": f"Invalid refs: {invalid_refs}" if invalid_refs else "All refs valid",
    }


def judge_recall(sample: dict) -> dict:
    """Judge whether semantic recall returns relevant memories.

    Returns: {"pass": bool, "details": str}
    """
    expected_ids = set(sample["expected_relevant_ids"])
    candidates = sample["candidate_memories"]

    # Top-1 by score
    top1 = max(candidates, key=lambda c: c.get("score", 0)) if candidates else {}
    top1_id = top1.get("source_event_id", "")

    passed = top1_id in expected_ids
    return {
        "id": sample["id"],
        "type": "recall",
        "pass": passed,
        "expected_ids": list(expected_ids),
        "top1_id": top1_id,
        "details": f"Top-1: {top1_id}" + (" ✓" if passed else " ✗"),
    }


def judge_chat_groundedness(sample: dict) -> dict:
    """Judge whether a chat answer is grounded in evidence.

    Returns: {"pass": bool, "details": str}
    """
    inp = sample["input"]
    evidence = inp.get("evidence", [])
    expected = sample["expected_grounded"]

    # Simple heuristic: grounded if there's at least one evidence item
    has_evidence = len(evidence) > 0
    passed = has_evidence == expected
    return {
        "id": sample["id"],
        "type": "groundedness",
        "pass": passed,
        "expected": expected,
        "actual": has_evidence,
        "details": f"Evidence count: {len(evidence)}",
    }


def compute_retrieval_metrics(results: list[dict]) -> dict:
    """Compute Recall@K and MRR from recall eval results.

    Args:
        results: list of judge_recall outputs

    Returns:
        {"recall_at_1": float, "mrr": float, "total": int}
    """
    if not results:
        return {"recall_at_1": 0.0, "mrr": 0.0, "total": 0}

    recall_hits = sum(1 for r in results if r["pass"])
    # MRR: reciprocal rank of first relevant item (simplified: always rank 1 if hit)
    mrr_sum = sum(1.0 if r["pass"] else 0.0 for r in results)

    return {
        "recall_at_1": recall_hits / len(results),
        "mrr": mrr_sum / len(results),
        "total": len(results),
    }


__all__ = [
    "load_dataset",
    "judge_faithfulness",
    "judge_recall",
    "judge_chat_groundedness",
    "compute_retrieval_metrics",
]
