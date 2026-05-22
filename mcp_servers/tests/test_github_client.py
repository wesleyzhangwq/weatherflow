from __future__ import annotations

import pytest

from mcp_servers.weatherflow_github.client import build_github_client


def test_build_github_client_raises_when_token_missing(monkeypatch) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="GITHUB_TOKEN"):
        build_github_client()


def test_build_github_client_uses_token_from_env(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "test-token-123")
    client = build_github_client()
    assert client.headers["Authorization"] == "Bearer test-token-123"
    assert client.headers["Accept"] == "application/vnd.github+json"
    assert client.headers["X-GitHub-Api-Version"] == "2022-11-28"
