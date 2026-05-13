"""Memory layer tests: schema, FTS5, semantic upsert, vector cosine."""

from __future__ import annotations

from app.memory import episodic, semantic, timeline
from app.memory.vector import SqliteVectorStore


def test_episodic_add_and_fts_roundtrip() -> None:
    e1 = episodic.add("Today I shipped a small RAG prototype.", source="checkin")
    e2 = episodic.add("Felt overwhelmed by too many AI tutorials.", source="checkin")
    assert e1 != e2

    hits = episodic.fts_search("rag")
    assert len(hits) == 1
    assert hits[0].id == e1
    assert "rag" in hits[0].content.lower()

    hits2 = episodic.fts_search("tutorials")
    assert len(hits2) == 1
    assert hits2[0].id == e2

    assert episodic.count() == 2


def test_semantic_upsert_blends_confidence() -> None:
    semantic.upsert("evening_efficiency", "low after 9pm", confidence=0.6)
    semantic.upsert("evening_efficiency", "low after 10pm", confidence=0.8)

    item = semantic.get("evening_efficiency")
    assert item is not None
    assert item.value == "low after 10pm"
    # blended (0.6 + 0.8) / 2 = 0.7
    assert abs(item.confidence - 0.7) < 1e-6


def test_timeline_add_and_recent() -> None:
    timeline.add("First RAG project shipped", kind="milestone", tags=["rag", "ai"])
    timeline.add("Started learning agents", kind="phase", tags=["agents"])

    items = timeline.recent()
    assert len(items) == 2
    titles = [i.title for i in items]
    assert "First RAG project shipped" in titles


def test_sqlite_vector_store_cosine_search() -> None:
    store = SqliteVectorStore()

    rag_vec = [1.0, 0.1, 0.0, 0.0]
    burnout_vec = [0.0, 0.0, 1.0, 0.1]
    other_vec = [0.0, 1.0, 0.0, 0.0]

    store.upsert("rag prototype shipped", source="checkin", embedding=rag_vec)
    store.upsert("very tired this week", source="checkin", embedding=burnout_vec)
    store.upsert("project switching a lot", source="checkin", embedding=other_vec)

    hits = store.search([1.0, 0.0, 0.0, 0.0], top_k=2)
    assert len(hits) == 2
    assert hits[0].content == "rag prototype shipped"
    assert hits[0].score > hits[1].score
