"""Pydantic models for GitHub MCP tool inputs and outputs."""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, field_validator


class GitHubRepoInput(BaseModel):
    owner: str
    repo: str
    window_days: int = 7

    @field_validator("owner", "repo")
    @classmethod
    def non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must be non-empty")
        return v


class GitHubRecentCommitsInput(BaseModel):
    owner: str
    repo: str
    branch: str = "main"
    since: Optional[str] = None
    limit: int = 30

    @field_validator("owner", "repo")
    @classmethod
    def non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must be non-empty")
        return v


class GitHubListIssuesInput(BaseModel):
    owner: str
    repo: str
    state: Literal["open", "closed", "all"] = "open"
    labels: Optional[List[str]] = None
    limit: int = 50

    @field_validator("owner", "repo")
    @classmethod
    def non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must be non-empty")
        return v


class GitHubCreateIssueInput(BaseModel):
    owner: str
    repo: str
    title: str
    body: str = ""
    labels: Optional[List[str]] = None
    dry_run: bool = False

    @field_validator("owner", "repo")
    @classmethod
    def non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must be non-empty")
        return v


class GitHubGetFileInput(BaseModel):
    owner: str
    repo: str
    path: str
    ref: str = "main"
    max_bytes: int = 50000

    @field_validator("owner", "repo", "path")
    @classmethod
    def non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must be non-empty")
        return v

    @field_validator("max_bytes")
    @classmethod
    def within_limit(cls, v: int) -> int:
        if v > 100000:
            raise ValueError("max_bytes must be <= 100000")
        return v


class GitHubCreateOrUpdateFileInput(BaseModel):
    owner: str
    repo: str
    path: str
    content: str
    message: str
    branch: str = "main"
    expected_sha: Optional[str] = None
    dry_run: bool = False

    @field_validator("owner", "repo", "path")
    @classmethod
    def non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must be non-empty")
        return v


__all__ = [
    "GitHubRepoInput",
    "GitHubRecentCommitsInput",
    "GitHubListIssuesInput",
    "GitHubCreateIssueInput",
    "GitHubGetFileInput",
    "GitHubCreateOrUpdateFileInput",
]
