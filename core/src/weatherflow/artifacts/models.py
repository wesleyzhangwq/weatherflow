from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from ulid import ULID


class ArtifactManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    run_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    media_type: str = Field(min_length=1)
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    relative_path: str = Field(min_length=1)
    validation: dict[str, Any]
    created_at: datetime

    @classmethod
    def new(
        cls,
        *,
        run_id: str,
        name: str,
        media_type: str,
        digest: str,
        size_bytes: int,
        relative_path: str,
        validation: dict[str, Any] | None = None,
    ) -> "ArtifactManifest":
        return cls(
            id=str(ULID()),
            run_id=run_id,
            name=name,
            media_type=media_type,
            digest=digest,
            size_bytes=size_bytes,
            relative_path=relative_path,
            validation=validation or {},
            created_at=datetime.now(UTC),
        )
