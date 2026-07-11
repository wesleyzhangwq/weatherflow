from datetime import datetime
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from weatherflow.artifacts import ArtifactStore
from weatherflow.capabilities.models import ToolEffect, ToolSpec
from weatherflow.runtime import ToolExecutionContext, ToolExecutionResult
from weatherflow.workspaces import WorkspaceRepository

MAX_QUERY_CHARS = 500
MAX_SOURCE_COUNT = 10
MAX_EXCERPT_CHARS = 2_000


class ProviderUnavailableError(RuntimeError):
    """A provider cannot serve requests without exposing private diagnostics."""


class ResearchSource(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str = Field(min_length=1, max_length=300)
    url: str = Field(pattern=r"^https?://", max_length=2_000)
    excerpt: str = ""
    retrieved_at: datetime


class ResearchProvider(Protocol):
    async def search(
        self,
        query: str,
        *,
        limit: int,
    ) -> tuple[ResearchSource, ...]: ...


def research_tool_specs() -> tuple[ToolSpec, ...]:
    return (
        ToolSpec(
            tool_id="research.gather",
            description=(
                "Retrieve bounded web sources and persist a provenance-aware research note"
            ),
            input_schema={
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string", "maxLength": MAX_QUERY_CHARS},
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": MAX_SOURCE_COUNT,
                    },
                },
            },
            output_schema={"type": "object"},
            effect=ToolEffect.NETWORK_READ,
            required_scopes=frozenset({"network:read"}),
            timeout_seconds=30,
            source="builtin.research",
            source_version="1",
        ),
    )


class ResearchExecutor:
    def __init__(
        self,
        *,
        provider: ResearchProvider,
        workspaces: WorkspaceRepository,
        artifacts: ArtifactStore,
    ) -> None:
        self.provider = provider
        self.workspaces = workspaces
        self.artifacts = artifacts

    async def execute(
        self,
        tool: ToolSpec,
        arguments: dict[str, Any],
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        if tool.tool_id != "research.gather":
            raise LookupError(tool.tool_id)
        query = arguments.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string")
        query = query.strip()
        if len(query) > MAX_QUERY_CHARS:
            raise ValueError("query exceeds size limit")
        limit = arguments.get("limit", 5)
        if not isinstance(limit, int) or isinstance(limit, bool):
            raise ValueError("limit must be an integer")
        limit = max(1, min(limit, MAX_SOURCE_COUNT))

        try:
            raw_sources = await self.provider.search(query, limit=limit)
        except ProviderUnavailableError:
            return ToolExecutionResult(
                output={
                    "status": "unavailable",
                    "reason": "research provider unavailable",
                    "query": query,
                }
            )

        sources = _normalize_sources(raw_sources, limit=limit)
        workspace = await self.workspaces.get(context.workspace_id)
        if workspace is None:
            raise LookupError(context.workspace_id)
        report = _render_report(query, sources)
        manifest = await self.artifacts.put_bytes(
            run_id=context.run_id,
            workspace=workspace,
            name=f"research-{context.run_id[:8]}.md",
            media_type="text/markdown",
            data=report.encode(),
            validation={
                "kind": "source-backed-research",
                "source_count": len(sources),
            },
        )
        return ToolExecutionResult(
            output={
                "status": "available",
                "query": query,
                "sources": [
                    _source_output(index, source) for index, source in enumerate(sources, 1)
                ],
                "artifact_id": manifest.id,
            },
            artifact_ids=(manifest.id,),
        )


def _normalize_sources(
    raw_sources: tuple[ResearchSource, ...],
    *,
    limit: int,
) -> tuple[ResearchSource, ...]:
    normalized: list[ResearchSource] = []
    seen_urls: set[str] = set()
    for source in raw_sources:
        if source.url in seen_urls:
            continue
        seen_urls.add(source.url)
        normalized.append(
            source.model_copy(
                update={
                    "title": source.title.strip(),
                    "excerpt": source.excerpt.strip()[:MAX_EXCERPT_CHARS],
                }
            )
        )
        if len(normalized) >= limit:
            break
    return tuple(normalized)


def _source_output(index: int, source: ResearchSource) -> dict[str, Any]:
    return {
        "citation": f"[{index}] {source.title}",
        **source.model_dump(mode="json"),
    }


def _render_report(query: str, sources: tuple[ResearchSource, ...]) -> str:
    lines = [f"# Research: {query}", "", "## Sources", ""]
    if not sources:
        lines.append("No sources were returned.")
    for index, source in enumerate(sources, 1):
        lines.extend(
            [
                f"### [{index}] {source.title}",
                "",
                f"- URL: {source.url}",
                f"- Retrieved: {source.retrieved_at.isoformat()}",
                "",
                source.excerpt or "No excerpt supplied.",
                "",
            ]
        )
    return "\n".join(lines)
