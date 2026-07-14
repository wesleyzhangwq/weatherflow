import asyncio
import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from weatherflow.extensions.models import (
    AgentDefinitionPackageManifest,
    InstalledPackage,
    PackageManifest,
)
from weatherflow.runtime import AgentDefinition

MAX_MANIFEST_BYTES = 64_000
MAX_PACKAGE_FILE_BYTES = 2_000_000
PACKAGE_KINDS = frozenset({"agent_definition", "capability_pack", "skill"})
PACKAGE_NAME = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")
PACKAGE_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[a-z0-9.-]+)?$")


class PackageIntegrityError(ValueError):
    pass


class PackageStore:
    def __init__(self, internal_root: str | Path) -> None:
        self.internal_root = Path(internal_root).resolve()
        self.root = self.internal_root / "extensions"

    async def install_verified(self, source: Path) -> InstalledPackage:
        return await asyncio.to_thread(self._install_verified, source)

    async def load_agent_definition(self, reference: str) -> AgentDefinition:
        manifest, root = await asyncio.to_thread(self._load_reference, reference)
        if not isinstance(manifest, AgentDefinitionPackageManifest):
            raise PackageIntegrityError("extension is not an Agent Definition")
        prompt = await asyncio.to_thread(
            self._read_verified_text,
            root,
            manifest.prompt_file,
        )
        return manifest.to_agent_definition(prompt)

    async def load_manifest(self, reference: str) -> PackageManifest:
        manifest, _ = await asyncio.to_thread(self._load_reference, reference)
        return manifest

    async def load_skill_prompt(self, reference: str) -> str:
        manifest, root = await asyncio.to_thread(self._load_reference, reference)
        if manifest.kind != "skill":
            raise PackageIntegrityError("extension is not a Skill")
        return await asyncio.to_thread(
            self._read_verified_text,
            root,
            manifest.prompt_file,
        )

    def remove(self, installed: InstalledPackage) -> None:
        if installed.created:
            path = (self.internal_root / installed.relative_path).resolve()
            if path.is_relative_to(self.root):
                shutil.rmtree(path, ignore_errors=True)

    def remove_reference(self, reference: str) -> None:
        """Remove an inactive immutable snapshot using a validated reference path."""

        root = self._reference_root(reference)
        if root.exists():
            shutil.rmtree(root, ignore_errors=True)

    def _install_verified(self, source_value: Path) -> InstalledPackage:
        source = source_value.resolve()
        if not source.is_dir() or source_value.is_symlink():
            raise PackageIntegrityError("package source must be a real directory")
        manifest = self._read_manifest(source / "manifest.json")
        self._verify_files(source, manifest)
        digest = manifest.digest()
        relative = Path("extensions") / manifest.kind / manifest.name / manifest.version / digest
        target = (self.internal_root / relative).resolve()
        if not target.is_relative_to(self.root):
            raise PackageIntegrityError("package destination escaped internal root")
        if target.exists():
            stored = self._read_manifest(target / "manifest.json")
            self._verify_files(target, stored)
            if stored.digest() != digest:
                raise PackageIntegrityError("stored package digest mismatch")
            return InstalledPackage(
                reference=stored.reference(),
                relative_path=relative.as_posix(),
                manifest=stored,
                created=False,
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(dir=target.parent, prefix=f".{digest}."))
        try:
            for package_file in manifest.files:
                destination = temporary / package_file.path
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source / package_file.path, destination)
            (temporary / "manifest.json").write_text(
                json.dumps(
                    manifest.model_dump(mode="json"),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
            os.replace(temporary, target)
        finally:
            shutil.rmtree(temporary, ignore_errors=True)
        return InstalledPackage(
            reference=manifest.reference(),
            relative_path=relative.as_posix(),
            manifest=manifest,
            created=True,
        )

    def _load_reference(self, reference: str) -> tuple[PackageManifest, Path]:
        root = self._reference_root(reference)
        if not root.is_dir():
            raise PackageIntegrityError("extension is not installed")
        manifest = self._read_manifest(root / "manifest.json")
        self._verify_files(root, manifest)
        if manifest.reference() != reference:
            raise PackageIntegrityError("extension reference digest mismatch")
        return manifest, root

    def _reference_root(self, reference: str) -> Path:
        parts = reference.split(":")
        if len(parts) != 3 or "@" not in parts[1]:
            raise PackageIntegrityError("invalid extension reference")
        kind, identity, digest = parts
        name, version = identity.split("@", 1)
        if (
            not digest
            or any(".." in item or "/" in item or "\\" in item for item in parts)
            or kind not in PACKAGE_KINDS
            or not PACKAGE_NAME.fullmatch(name)
            or not PACKAGE_VERSION.fullmatch(version)
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
        ):
            raise PackageIntegrityError("invalid extension reference")
        root = (self.root / kind / name / version / digest).resolve()
        if not root.is_relative_to(self.root):
            raise PackageIntegrityError("extension reference escaped internal root")
        return root

    @staticmethod
    def _read_manifest(path: Path) -> PackageManifest:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_MANIFEST_BYTES:
            raise PackageIntegrityError("manifest is missing, linked, or too large")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return TypeAdapter(PackageManifest).validate_python(value)
        except (OSError, json.JSONDecodeError, ValidationError) as error:
            raise PackageIntegrityError("manifest is invalid") from error

    @staticmethod
    def _verify_files(source: Path, manifest: PackageManifest) -> None:
        seen: set[str] = set()
        for package_file in manifest.files:
            if package_file.path in seen:
                raise PackageIntegrityError("duplicate package file")
            seen.add(package_file.path)
            path = source / package_file.path
            if path.is_symlink() or not path.is_file():
                raise PackageIntegrityError("package file is missing or linked")
            data = path.read_bytes()
            if len(data) > MAX_PACKAGE_FILE_BYTES:
                raise PackageIntegrityError("package file exceeds size limit")
            if hashlib.sha256(data).hexdigest() != package_file.sha256:
                raise PackageIntegrityError("package file digest mismatch")

    @staticmethod
    def _read_verified_text(root: Path, relative: str) -> str:
        target = (root / relative).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            raise PackageIntegrityError("prompt file is outside the package")
        return target.read_text(encoding="utf-8")
