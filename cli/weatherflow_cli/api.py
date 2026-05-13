"""Thin httpx wrapper for the WeatherFlow backend."""

from __future__ import annotations

import os
from typing import Any

import httpx


def api_base() -> str:
    return os.environ.get("WF_API_BASE", "http://127.0.0.1:8765").rstrip("/")


def _client() -> httpx.Client:
    return httpx.Client(base_url=api_base(), timeout=120.0)


def post(path: str, json: dict[str, Any] | None = None, params: dict[str, Any] | None = None):
    with _client() as c:
        r = c.post(path, json=json, params=params)
        r.raise_for_status()
        return r.json()


def get(path: str, params: dict[str, Any] | None = None):
    with _client() as c:
        r = c.get(path, params=params)
        r.raise_for_status()
        return r.json()
