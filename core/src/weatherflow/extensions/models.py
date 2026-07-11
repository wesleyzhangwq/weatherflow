import hashlib
import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from weatherflow.runtime import AgentDefinition


class PackageFile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str = Field(min_length=1, max_length=500)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("path")
    @classmethod
    def safe_relative_path(cls, value: str) -> str:
        path = Path(value)
        if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
            raise ValueError("package file path must be normalized and relative")
        return value


class PackageManifestBase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1"] = "1"
    kind: str
    name: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[a-z0-9.-]+)?$")
    description: str = Field(min_length=1, max_length=500)
    files: tuple[PackageFile, ...]

    def digest(self) -> str:
        encoded = json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(encoded).hexdigest()

    def reference(self) -> str:
        return f"{self.kind}:{self.name}@{self.version}:{self.digest()}"


class CapabilityPackManifest(PackageManifestBase):
    kind: Literal["capability_pack"] = "capability_pack"
    tool_ids: tuple[str, ...]
    requested_scopes: tuple[str, ...] = ()


class SkillPackageManifest(PackageManifestBase):
    kind: Literal["skill"] = "skill"
    prompt_file: str
    suggested_tool_ids: tuple[str, ...] = ()


class AgentDefinitionPackageManifest(PackageManifestBase):
    kind: Literal["agent_definition"] = "agent_definition"
    agent_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    prompt_file: str
    is_leaf: bool = True
    tool_filter: tuple[str, ...] = ()
    skill_filter: tuple[str, ...] = ()
    max_steps: int = Field(default=20, ge=1, le=100)

    def to_agent_definition(self, prompt: str) -> AgentDefinition:
        return AgentDefinition(
            agent_id=self.agent_id,
            system_prompt=prompt,
            is_leaf=self.is_leaf,
            tool_filter=frozenset(self.tool_filter),
            skill_filter=frozenset(self.skill_filter),
            max_steps=self.max_steps,
        )


PackageManifest = Annotated[
    CapabilityPackManifest | SkillPackageManifest | AgentDefinitionPackageManifest,
    Field(discriminator="kind"),
]


class InstalledPackage(BaseModel):
    model_config = ConfigDict(frozen=True)

    reference: str
    relative_path: str
    manifest: PackageManifest
    created: bool
