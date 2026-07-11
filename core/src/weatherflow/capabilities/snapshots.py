import hashlib
import json
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict
from ulid import ULID

from weatherflow.capabilities.models import ToolSpec


class RunCapabilitySnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    run_id: str
    catalog_revision: str
    tools: tuple[ToolSpec, ...]
    digest: str
    created_at: datetime

    @classmethod
    def freeze(
        cls,
        *,
        run_id: str,
        catalog_revision: str,
        tools: Iterable[ToolSpec],
    ) -> "RunCapabilitySnapshot":
        ordered = tuple(sorted(tools, key=lambda item: item.tool_id))
        payload = canonical_snapshot_payload(catalog_revision, ordered)
        digest = hashlib.sha256(canonical_json(payload).encode()).hexdigest()
        return cls(
            id=str(ULID()),
            run_id=run_id,
            catalog_revision=catalog_revision,
            tools=ordered,
            digest=digest,
            created_at=datetime.now(UTC),
        )


def canonical_tool(tool: ToolSpec) -> dict[str, Any]:
    value = tool.model_dump(mode="json")
    value["required_scopes"] = sorted(tool.required_scopes)
    return value


def canonical_snapshot_payload(catalog_revision: str, tools: Iterable[ToolSpec]) -> dict[str, Any]:
    return {
        "catalog_revision": catalog_revision,
        "tools": [canonical_tool(tool) for tool in tools],
    }


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
