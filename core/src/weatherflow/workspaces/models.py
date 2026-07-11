from collections.abc import Iterable
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field
from ulid import ULID

from weatherflow.runs import RunBudget


class NetworkPolicy(StrEnum):
    OFFLINE = "offline"
    DECLARED = "declared"
    OPEN = "open"


class Workspace(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str = Field(min_length=1)
    action_roots: tuple[str, ...]
    internal_root: str
    artifact_root: str
    granted_scopes: frozenset[str] = frozenset()
    network_policy: NetworkPolicy = NetworkPolicy.DECLARED
    installed_packs: tuple[str, ...] = ()
    installed_skills: tuple[str, ...] = ()
    agent_definitions: tuple[str, ...] = ()
    extension_refs: tuple[str, ...] = ()
    default_budget: RunBudget = RunBudget()
    policy_profile: str = "supervised"
    version: int = Field(default=0, ge=0)
    created_at: datetime
    updated_at: datetime

    @classmethod
    def new(
        cls,
        *,
        name: str,
        action_roots: Iterable[Path | str],
        internal_root: Path | str,
        artifact_root: Path | str,
        granted_scopes: Iterable[str] = (),
        network_policy: NetworkPolicy = NetworkPolicy.DECLARED,
        installed_packs: Iterable[str] = (),
        installed_skills: Iterable[str] = (),
        agent_definitions: Iterable[str] = (),
        extension_refs: Iterable[str] = (),
        default_budget: RunBudget | None = None,
        policy_profile: str = "supervised",
    ) -> "Workspace":
        now = datetime.now(UTC)
        values = {
            "id": str(ULID()),
            "name": name,
            "action_roots": tuple(str(Path(path).resolve()) for path in action_roots),
            "internal_root": str(Path(internal_root).resolve()),
            "artifact_root": str(Path(artifact_root).resolve()),
            "granted_scopes": frozenset(granted_scopes),
            "network_policy": network_policy,
            "installed_packs": tuple(sorted(installed_packs)),
            "installed_skills": tuple(sorted(installed_skills)),
            "agent_definitions": tuple(sorted(agent_definitions)),
            "extension_refs": tuple(sorted(extension_refs)),
            "policy_profile": policy_profile,
            "created_at": now,
            "updated_at": now,
        }
        if default_budget is not None:
            values["default_budget"] = default_budget
        return cls.model_validate(values)

    def allows_action_path(self, path: Path | str) -> bool:
        candidate = Path(path).resolve()
        internal_root = Path(self.internal_root)
        if candidate == internal_root or candidate.is_relative_to(internal_root):
            return False
        return any(
            candidate == Path(root) or candidate.is_relative_to(Path(root))
            for root in self.action_roots
        )
