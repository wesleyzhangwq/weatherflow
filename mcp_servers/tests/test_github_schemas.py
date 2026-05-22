from __future__ import annotations

import pytest
from pydantic import ValidationError

from mcp_servers.weatherflow_github.schemas import (
    GitHubCreateIssueInput,
    GitHubCreateOrUpdateFileInput,
    GitHubGetFileInput,
    GitHubListIssuesInput,
    GitHubRecentCommitsInput,
    GitHubRepoInput,
)


def test_repo_input_valid() -> None:
    s = GitHubRepoInput(owner="wesleyzhangwq", repo="weatherflow")
    assert s.window_days == 7


def test_repo_input_rejects_empty_owner() -> None:
    with pytest.raises(ValidationError, match="non-empty"):
        GitHubRepoInput(owner="", repo="weatherflow")


def test_repo_input_rejects_empty_repo() -> None:
    with pytest.raises(ValidationError, match="non-empty"):
        GitHubRepoInput(owner="wesleyzhangwq", repo="")


def test_list_issues_default_state_open() -> None:
    s = GitHubListIssuesInput(owner="wesleyzhangwq", repo="weatherflow")
    assert s.state == "open"


def test_get_file_rejects_empty_path() -> None:
    with pytest.raises(ValidationError):
        GitHubGetFileInput(owner="wesleyzhangwq", repo="weatherflow", path="")


def test_get_file_rejects_max_bytes_over_limit() -> None:
    with pytest.raises(ValidationError, match="max_bytes"):
        GitHubGetFileInput(
            owner="wesleyzhangwq",
            repo="weatherflow",
            path="README.md",
            max_bytes=200000,
        )


def test_create_or_update_file_dry_run_defaults_false() -> None:
    s = GitHubCreateOrUpdateFileInput(
        owner="wesleyzhangwq",
        repo="weatherflow",
        path="docs/log.md",
        content="# Log",
        message="docs: update log",
    )
    assert s.dry_run is False


def test_create_issue_supports_dry_run() -> None:
    s = GitHubCreateIssueInput(
        owner="wesleyzhangwq",
        repo="weatherflow",
        title="Test issue",
        dry_run=True,
    )
    assert s.dry_run is True
