import asyncio
import hashlib
import os
import tempfile
from pathlib import Path
from typing import Any

from weatherflow.artifacts.models import ArtifactManifest
from weatherflow.artifacts.repository import ArtifactRepository
from weatherflow.events import Actor, Event, EventLedger
from weatherflow.storage import Database
from weatherflow.workspaces import Workspace


class ArtifactNameError(ValueError):
    pass


class ArtifactIntegrityError(RuntimeError):
    pass


class ArtifactStore:
    def __init__(
        self,
        *,
        database: Database,
        repository: ArtifactRepository,
        ledger: EventLedger,
    ) -> None:
        self.database = database
        self.repository = repository
        self.ledger = ledger

    async def put_bytes(
        self,
        *,
        run_id: str,
        workspace: Workspace,
        name: str,
        media_type: str,
        data: bytes,
        validation: dict[str, Any] | None = None,
    ) -> ArtifactManifest:
        self._validate_name(name)
        digest = hashlib.sha256(data).hexdigest()
        relative = Path("sha256") / digest[:2] / digest
        root, target = await asyncio.to_thread(
            self._artifact_paths, workspace.artifact_root, relative
        )
        if not target.is_relative_to(root):
            raise ArtifactIntegrityError("artifact path escaped its root")
        created = await asyncio.to_thread(self._ensure_blob, target, data, digest)
        manifest = ArtifactManifest.new(
            run_id=run_id,
            name=name,
            media_type=media_type,
            digest=digest,
            size_bytes=len(data),
            relative_path=relative.as_posix(),
            validation=validation,
        )
        try:
            async with self.database.transaction() as connection:
                await self.repository.create_in(connection, manifest)
                await self.ledger.append_in(
                    connection,
                    Event.new(
                        type="artifact.created",
                        actor=Actor.AGENT,
                        stream_kind="artifact",
                        stream_id=manifest.id,
                        correlation_id=run_id,
                        payload={
                            "name": name,
                            "media_type": media_type,
                            "digest": digest,
                            "size_bytes": len(data),
                            "validation": manifest.validation,
                        },
                    ),
                )
        except BaseException:
            if created and await self.repository.count_digest(digest) == 0:
                await asyncio.to_thread(target.unlink, missing_ok=True)
            raise
        return manifest

    @staticmethod
    def _validate_name(name: str) -> None:
        if not name or name in {".", ".."} or Path(name).name != name:
            raise ArtifactNameError(name)

    @staticmethod
    def _artifact_paths(artifact_root: str, relative: Path) -> tuple[Path, Path]:
        root = Path(artifact_root).resolve()
        return root, (root / relative).resolve()

    @classmethod
    def _ensure_blob(cls, target: Path, data: bytes, digest: str) -> bool:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            cls._verify_blob(target, digest, len(data))
            return False
        descriptor, temporary_name = tempfile.mkstemp(
            dir=target.parent,
            prefix=f".{digest}.",
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as file:
                file.write(data)
                file.flush()
                os.fsync(file.fileno())
            if target.exists():
                cls._verify_blob(target, digest, len(data))
                temporary.unlink(missing_ok=True)
                return False
            os.replace(temporary, target)
            return True
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _verify_blob(path: Path, digest: str, size: int) -> None:
        data = path.read_bytes()
        if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
            raise ArtifactIntegrityError(str(path))
