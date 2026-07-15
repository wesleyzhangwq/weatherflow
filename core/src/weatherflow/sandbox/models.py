from enum import StrEnum
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SandboxNetworkMode(StrEnum):
    OFFLINE = "offline"
    LOOPBACK = "loopback"
    HTTPS_EGRESS = "https_egress"


class SandboxLimits(BaseModel):
    model_config = ConfigDict(frozen=True)

    wall_time_seconds: float = Field(default=300, gt=0, le=3_600)
    cpu_time_seconds: int = Field(default=300, ge=1, le=3_600)
    max_file_size_bytes: int = Field(default=2 * 1024**3, ge=1024**2)
    max_open_files: int = Field(default=2_048, ge=32, le=4_096)
    max_output_bytes: int = Field(default=1024**2, ge=4_096, le=16 * 1024**2)


SAFE_ENVIRONMENT_KEYS = frozenset(
    {
        "CARGO_HOME",
        "CARGO_TERM_COLOR",
        "CI",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "NO_COLOR",
        "PATH",
        "PYENV_ROOT",
        "RUSTUP_HOME",
        "TERM",
    }
)


class SandboxRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    argv: tuple[str, ...] = Field(min_length=1, max_length=64)
    cwd: str
    readable_roots: tuple[str, ...] = Field(min_length=1, max_length=64)
    writable_roots: tuple[str, ...] = Field(default=(), max_length=16)
    environment: dict[str, str] = Field(default_factory=dict)
    network: SandboxNetworkMode = SandboxNetworkMode.OFFLINE
    limits: SandboxLimits = SandboxLimits()

    @field_validator("argv")
    @classmethod
    def validate_argv(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item or "\x00" in item or len(item) > 16_384 for item in value):
            raise ValueError("sandbox argv is empty, malformed, or exceeds limits")
        return value

    @field_validator("cwd")
    @classmethod
    def normalize_cwd(cls, value: str) -> str:
        return _absolute_resolved_path(value, "working directory")

    @field_validator("readable_roots", "writable_roots")
    @classmethod
    def normalize_roots(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(_absolute_resolved_path(value, "sandbox root") for value in values)
        if len(normalized) != len(set(normalized)):
            raise ValueError("sandbox roots must be unique")
        return normalized

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, value: dict[str, str]) -> dict[str, str]:
        unknown = set(value) - SAFE_ENVIRONMENT_KEYS
        if unknown:
            raise ValueError("sandbox environment contains unreviewed keys")
        if any(
            not key or "\x00" in key or "\x00" in item or len(key) > 64 or len(item) > 16_384
            for key, item in value.items()
        ):
            raise ValueError("sandbox environment is malformed or exceeds limits")
        return dict(value)

    @model_validator(mode="after")
    def validate_scope(self) -> Self:
        cwd = Path(self.cwd)
        if not any(_contains(Path(root), cwd) for root in self.readable_roots):
            raise ValueError("sandbox working directory is outside readable roots")
        for root in self.writable_roots:
            if not any(_contains(Path(readable), Path(root)) for readable in self.readable_roots):
                raise ValueError("sandbox writable root is outside readable roots")
        return self


class SandboxResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    backend_id: str
    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    duration_ms: int = Field(ge=0)
    network: SandboxNetworkMode


def _absolute_resolved_path(value: str, label: str) -> str:
    if not value or "\x00" in value or len(value) > 16_384:
        raise ValueError(f"{label} is malformed or exceeds limits")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError(f"{label} must be absolute")
    return str(path.resolve())


def _contains(root: Path, candidate: Path) -> bool:
    return candidate == root or candidate.is_relative_to(root)
