"""Tests for the eval framework (v2 Track 1D)."""

from __future__ import annotations

from eval.judges import (
    compute_retrieval_metrics,
    judge_chat_groundedness,
    judge_faithfulness,
    judge_recall,
    load_dataset,
)


def test_load_dataset_has_minimum_samples():
    """Eval dataset must have ≥30 samples."""
    samples = load_dataset()
    assert len(samples) >= 30, f"Only {len(samples)} samples, need ≥30"


def test_load_dataset_covers_all_types():
    """Dataset covers all 4 eval dimensions."""
    samples = load_dataset()
    types = {s["type"] for s in samples}
    assert "checkin_to_label" in types
    assert "hypothesis_faithfulness" in types
    assert "memory_recall" in types
    assert "chat_groundedness" in types


def test_faithfulness_valid_refs_pass():
    sample = {
        "id": "test-f1",
        "type": "hypothesis_faithfulness",
        "input": {
            "hypothesis": {"evidence": [{"source_event_id": "evt_1"}], "counter_evidence": []},
            "bundle_event_ids": ["evt_1"],
        },
        "expected_faithful": True,
    }
    result = judge_faithfulness(sample)
    assert result["pass"] is True


def test_faithfulness_invalid_refs_fail():
    sample = {
        "id": "test-f2",
        "type": "hypothesis_faithfulness",
        "input": {
            "hypothesis": {"evidence": [{"source_event_id": "FAKE"}], "counter_evidence": []},
            "bundle_event_ids": ["evt_1"],
        },
        "expected_faithful": False,
    }
    result = judge_faithfulness(sample)
    assert result["pass"] is True  # judge agrees it's not faithful


def test_recall_top1_relevant():
    sample = {
        "id": "test-r1",
        "type": "memory_recall",
        "query": "test",
        "candidate_memories": [
            {"source_event_id": "good", "score": 0.9},
            {"source_event_id": "bad", "score": 0.1},
        ],
        "expected_relevant_ids": ["good"],
    }
    result = judge_recall(sample)
    assert result["pass"] is True


def test_recall_top1_irrelevant():
    sample = {
        "id": "test-r2",
        "type": "memory_recall",
        "query": "test",
        "candidate_memories": [
            {"source_event_id": "bad", "score": 0.9},
            {"source_event_id": "good", "score": 0.1},
        ],
        "expected_relevant_ids": ["good"],
    }
    result = judge_recall(sample)
    assert result["pass"] is False


def test_groundedness_with_evidence():
    sample = {
        "id": "test-g1",
        "type": "chat_groundedness",
        "input": {"answer": "Based on data...", "evidence": [{"text": "data"}]},
        "expected_grounded": True,
    }
    result = judge_chat_groundedness(sample)
    assert result["pass"] is True


def test_groundedness_without_evidence():
    sample = {
        "id": "test-g2",
        "type": "chat_groundedness",
        "input": {"answer": "I think...", "evidence": []},
        "expected_grounded": False,
    }
    result = judge_chat_groundedness(sample)
    assert result["pass"] is True


def test_retrieval_metrics():
    results = [
        {"pass": True},
        {"pass": False},
        {"pass": True},
    ]
    m = compute_retrieval_metrics(results)
    assert m["recall_at_1"] == 2 / 3
    assert m["total"] == 3
