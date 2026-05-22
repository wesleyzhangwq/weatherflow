"""Compatibility shim — real implementation is in app.providers.github_direct."""

from app.providers.github_direct import GithubConnector, normalize_github_summary

__all__ = ["GithubConnector", "normalize_github_summary"]
