"""build_mem0_config — robust QDRANT_URL parsing + embedder wiring (G16).

Updated for ADR-004 D5: embedder now threads base_url + dims; no LLM section
(projector uses infer=False).
"""

from __future__ import annotations

from app.config import Settings
from app.memory.semantic.mem0_config import build_mem0_config


def test_parses_host_and_port_from_url(monkeypatch):
    monkeypatch.setenv("QDRANT_URL", "http://qdrant.internal:6400")
    monkeypatch.setenv("QDRANT_COLLECTION", "wf_mem")
    monkeypatch.setenv("EMBEDDING_API_KEY", "")

    cfg = build_mem0_config(Settings())
    vs = cfg["vector_store"]["config"]
    assert vs["host"] == "qdrant.internal"
    assert vs["port"] == 6400
    assert vs["collection_name"] == "wf_mem"
    assert vs["embedding_model_dims"] == 1024  # default dims
    assert "embedder" not in cfg  # no embedding key configured


def test_defaults_and_embedder_when_key_set(monkeypatch):
    monkeypatch.setenv("QDRANT_URL", "http://127.0.0.1:6333")
    monkeypatch.setenv("EMBEDDING_API_KEY", "secret")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "openai")
    monkeypatch.setenv("EMBEDDING_MODEL", "text-embedding-v4")

    cfg = build_mem0_config(Settings())
    assert cfg["vector_store"]["config"]["port"] == 6333
    assert cfg["vector_store"]["config"]["embedding_model_dims"] == 1024
    assert cfg["embedder"]["config"]["model"] == "text-embedding-v4"
    assert cfg["embedder"]["config"]["embedding_dims"] == 1024
    assert cfg["embedder"]["provider"] == "openai"


def test_embedder_threads_base_url(monkeypatch):
    monkeypatch.setenv("QDRANT_URL", "http://127.0.0.1:6333")
    monkeypatch.setenv("EMBEDDING_API_KEY", "sk-ali")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "openai")
    monkeypatch.setenv("EMBEDDING_MODEL", "text-embedding-v3")
    monkeypatch.setenv("EMBEDDING_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    monkeypatch.setenv("EMBEDDING_DIMS", "1024")

    cfg = build_mem0_config(Settings())
    ec = cfg["embedder"]["config"]
    assert ec["openai_base_url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert ec["embedding_dims"] == 1024


def test_llm_section_points_at_chat_gateway(monkeypatch):
    # mem0 builds the LLM client eagerly at init even though the projector uses
    # infer=False, so it must carry valid creds (here: the MiniMax gateway).
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.minimaxi.com/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-minimax")
    monkeypatch.setenv("CHAT_MODEL", "MiniMax-M3")
    monkeypatch.setenv("EMBEDDING_API_KEY", "sk-ali")

    cfg = build_mem0_config(Settings())
    lc = cfg["llm"]["config"]
    assert cfg["llm"]["provider"] == "openai"
    assert lc["model"] == "MiniMax-M3"
    assert lc["api_key"] == "sk-minimax"
    assert lc["openai_base_url"] == "https://api.minimaxi.com/v1"


def test_collection_param_selects_profile_collection(monkeypatch):
    monkeypatch.setenv("QDRANT_URL", "http://127.0.0.1:6333")
    monkeypatch.setenv("QDRANT_COLLECTION", "weatherflow_memories")
    monkeypatch.setenv("QDRANT_PROFILE_COLLECTION", "weatherflow_profile")

    s = Settings()
    episodic = build_mem0_config(s)
    profile = build_mem0_config(s, collection=s.qdrant_profile_collection)
    assert episodic["vector_store"]["config"]["collection_name"] == "weatherflow_memories"
    assert profile["vector_store"]["config"]["collection_name"] == "weatherflow_profile"


def test_no_base_url_when_empty(monkeypatch):
    monkeypatch.setenv("QDRANT_URL", "http://127.0.0.1:6333")
    monkeypatch.setenv("EMBEDDING_API_KEY", "sk-openai")
    monkeypatch.setenv("EMBEDDING_BASE_URL", "")

    cfg = build_mem0_config(Settings())
    assert "openai_base_url" not in cfg["embedder"]["config"]
