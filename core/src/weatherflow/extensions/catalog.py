"""Safe local Skill catalog import and per-Workspace activation.

Catalog metadata is descriptive only.  Installing a catalog item converts the
selected source directory into the same immutable, digest-verified package used
by every other WeatherFlow extension; frontmatter never grants tools or scopes.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from weatherflow.events import EventLedger
from weatherflow.extensions.installer import PackageInstaller
from weatherflow.extensions.models import InstalledPackage, PackageFile, SkillPackageManifest
from weatherflow.extensions.store import MAX_PACKAGE_FILE_BYTES, PackageStore
from weatherflow.storage import Database
from weatherflow.workspaces import Workspace, WorkspaceRepository

MAX_FRONTMATTER_BYTES = 64_000
MAX_SKILL_FILES = 128
MAX_SKILL_BYTES = 10_000_000
SKILL_ID = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")
FRONTMATTER_KEY = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*):(?:\s*(.*))?$")
METADATA_KEY = re.compile(r"^ {2}([A-Za-z][A-Za-z0-9_-]*):(?:\s*(.*))?$")
LIST_ITEM = re.compile(r"^ {2,4}-\s+(.+?)\s*$")
ALLOWED_FRONTMATTER_KEYS = {
    "name",
    "description",
    "metadata",
    "license",
    "compatibility",
    "allowed-tools",
}


class SkillCatalogError(ValueError):
    """Raised when a catalog source cannot be safely imported."""


class SkillCatalogEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    description: str
    description_zh: str | None = None
    boundary_zh: str | None = None
    category: str | None = None
    license: str | None = None
    related: tuple[str, ...] = ()
    reads: tuple[str, ...] = ()
    source: Literal["wesley-skills"] = "wesley-skills"
    source_path: str
    source_digest: str = ""
    validation_status: Literal["valid", "invalid"]
    validation_errors: tuple[str, ...] = ()
    installed: bool = False
    installed_reference: str | None = None


@dataclass(frozen=True)
class _Frontmatter:
    name: str
    description: str
    license: str | None
    related: tuple[str, ...]
    reads: tuple[str, ...]


@dataclass(frozen=True)
class _SkillSource:
    entry: SkillCatalogEntry
    files: tuple[tuple[str, bytes], ...]


@dataclass(frozen=True)
class _ChineseMetadata:
    description: str
    boundary: str
    category: str


class WesleySkillCatalog:
    """Read a configurable ``wesley-skills`` checkout without trusting it at runtime."""

    def __init__(self, root: str | Path) -> None:
        configured = Path(root).expanduser()
        if configured.is_symlink():
            raise SkillCatalogError("catalog root must not be a symlink")
        self.root = configured.resolve()
        candidate = self.root / "skills"
        self.skills_root = candidate if candidate.is_dir() else self.root

    def scan(self) -> tuple[SkillCatalogEntry, ...]:
        sources = self._validated_sources()
        return tuple(sorted((source.entry for source in sources), key=lambda entry: entry.id))

    def _validated_sources(self) -> tuple[_SkillSource, ...]:
        sources = self._scan_sources()
        counts = Counter(
            source.entry.name for source in sources if SKILL_ID.fullmatch(source.entry.name)
        )
        validated: list[_SkillSource] = []
        for source in sources:
            entry = source.entry
            errors = list(entry.validation_errors)
            if counts[entry.name] > 1:
                errors.append("duplicate frontmatter name")
            errors = list(dict.fromkeys(errors))
            validated.append(
                _SkillSource(
                    entry=entry.model_copy(
                        update={
                            "validation_status": "invalid" if errors else "valid",
                            "validation_errors": tuple(errors),
                        }
                    ),
                    files=source.files,
                )
            )
        return tuple(validated)

    def materialize_snapshot(self, skill_id: str, destination: str | Path) -> Path:
        if not SKILL_ID.fullmatch(skill_id):
            raise SkillCatalogError("skill id is invalid")
        sources = {source.entry.id: source for source in self._validated_sources()}
        source = sources.get(skill_id)
        if source is None:
            raise SkillCatalogError("skill is not in the configured catalog")
        entry = source.entry
        if entry.validation_status != "valid":
            detail = "; ".join(entry.validation_errors)
            raise SkillCatalogError(f"skill failed catalog validation: {detail}")

        target = Path(destination)
        if target.exists() or target.is_symlink():
            raise SkillCatalogError("snapshot destination already exists")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(dir=target.parent, prefix=f".{skill_id}."))
        try:
            package_files: list[PackageFile] = []
            for relative, data in source.files:
                output = temporary / relative
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(data)
                package_files.append(
                    PackageFile(path=relative, sha256=hashlib.sha256(data).hexdigest())
                )
            manifest = SkillPackageManifest(
                name=entry.name,
                version=f"0.0.0-wesley.{entry.source_digest[:12]}",
                description=entry.description[:500],
                files=tuple(package_files),
                prompt_file="SKILL.md",
                # Catalog annotations describe possible use only. They never
                # become capability or Trust authority.
                suggested_tool_ids=(),
            )
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
        return target

    def _scan_sources(self) -> tuple[_SkillSource, ...]:
        if (
            not self.skills_root.is_dir()
            or self.skills_root.is_symlink()
            or not self.skills_root.resolve().is_relative_to(self.root)
        ):
            raise SkillCatalogError("catalog skills directory is missing or unsafe")
        chinese = self._read_chinese_metadata()
        sources: list[_SkillSource] = []
        for path in sorted(self.skills_root.iterdir(), key=lambda item: item.name):
            if not path.is_dir() and not path.is_symlink():
                continue
            sources.append(self._read_source(path, chinese.get(path.name)))
        return tuple(sources)

    def _read_source(
        self,
        skill_root: Path,
        chinese: _ChineseMetadata | None,
    ) -> _SkillSource:
        errors: list[str] = []
        directory_id = skill_root.name
        if not SKILL_ID.fullmatch(directory_id):
            errors.append("skill directory id is invalid")
        if skill_root.is_symlink():
            errors.append("skill source contains a symlink")

        files: tuple[tuple[str, bytes], ...] = ()
        digest = ""
        try:
            files, digest = self._read_inventory(skill_root)
        except SkillCatalogError as error:
            errors.append(str(error))

        frontmatter: _Frontmatter | None = None
        prompt = dict(files).get("SKILL.md")
        if prompt is None:
            errors.append("SKILL.md is missing")
        else:
            try:
                frontmatter = self._parse_frontmatter(prompt)
            except SkillCatalogError as error:
                errors.append(str(error))

        name = frontmatter.name if frontmatter else directory_id
        description = frontmatter.description if frontmatter else "Invalid Skill package"
        if frontmatter is not None:
            if not SKILL_ID.fullmatch(frontmatter.name):
                errors.append("frontmatter name is invalid")
            elif frontmatter.name != directory_id:
                errors.append("frontmatter name must match the skill directory")
        return _SkillSource(
            entry=SkillCatalogEntry(
                id=directory_id,
                name=name,
                description=description,
                description_zh=chinese.description if chinese else None,
                boundary_zh=chinese.boundary if chinese else None,
                category=chinese.category if chinese else None,
                license=frontmatter.license if frontmatter else None,
                related=frontmatter.related if frontmatter else (),
                reads=frontmatter.reads if frontmatter else (),
                source_path=str(skill_root.absolute()),
                source_digest=digest,
                validation_status="invalid" if errors else "valid",
                validation_errors=tuple(dict.fromkeys(errors)),
            ),
            files=files,
        )

    def _read_inventory(self, skill_root: Path) -> tuple[tuple[tuple[str, bytes], ...], str]:
        if skill_root.is_symlink() or not skill_root.is_dir():
            raise SkillCatalogError("skill source contains a symlink")
        resolved_root = skill_root.resolve()
        if not resolved_root.is_relative_to(self.skills_root.resolve()):
            raise SkillCatalogError("skill source escaped the catalog root")
        payloads: list[tuple[str, bytes]] = []
        total = 0
        for path in sorted(skill_root.rglob("*"), key=lambda item: item.as_posix()):
            if path.is_symlink():
                raise SkillCatalogError("skill source contains a symlink")
            if path.is_dir():
                continue
            if not path.is_file() or not path.resolve().is_relative_to(resolved_root):
                raise SkillCatalogError("skill source escaped the catalog root")
            relative = path.relative_to(skill_root).as_posix()
            if relative == "manifest.json" or ".." in Path(relative).parts:
                raise SkillCatalogError("skill source contains a reserved or unsafe path")
            data = self._read_regular_file(path)
            if len(data) > MAX_PACKAGE_FILE_BYTES:
                raise SkillCatalogError("skill file exceeds the package size limit")
            total += len(data)
            if total > MAX_SKILL_BYTES:
                raise SkillCatalogError("skill source exceeds the total size limit")
            payloads.append((relative, data))
            if len(payloads) > MAX_SKILL_FILES:
                raise SkillCatalogError("skill source contains too many files")
        digest = hashlib.sha256()
        for relative, data in payloads:
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            digest.update(hashlib.sha256(data).digest())
        return tuple(payloads), digest.hexdigest()

    @staticmethod
    def _read_regular_file(path: Path) -> bytes:
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(path, flags)
        except OSError as error:
            raise SkillCatalogError("skill source contains an unreadable file") from error
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise SkillCatalogError("skill source contains a non-regular file")
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                return stream.read(MAX_SKILL_BYTES + 1)
        finally:
            os.close(descriptor)

    @staticmethod
    def _parse_frontmatter(data: bytes) -> _Frontmatter:
        if len(data) > MAX_SKILL_BYTES:
            raise SkillCatalogError("SKILL.md exceeds the size limit")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as error:
            raise SkillCatalogError("SKILL.md is not valid UTF-8") from error
        lines = text.splitlines()
        if not lines or lines[0] != "---":
            raise SkillCatalogError("SKILL.md frontmatter is missing")
        try:
            end = lines.index("---", 1)
        except ValueError as error:
            raise SkillCatalogError("SKILL.md frontmatter is not terminated") from error
        frontmatter_lines = lines[1:end]
        if sum(len(line.encode("utf-8")) + 1 for line in frontmatter_lines) > MAX_FRONTMATTER_BYTES:
            raise SkillCatalogError("SKILL.md frontmatter exceeds the size limit")
        if any("\t" in line for line in frontmatter_lines):
            raise SkillCatalogError("SKILL.md frontmatter contains a tab")

        fields: dict[str, tuple[str, list[str]]] = {}
        current: str | None = None
        for line in frontmatter_lines:
            if not line.strip():
                continue
            if not line.startswith(" "):
                match = FRONTMATTER_KEY.fullmatch(line)
                if match is None:
                    raise SkillCatalogError("SKILL.md frontmatter is malformed")
                key, value = match.groups()
                if key not in ALLOWED_FRONTMATTER_KEYS:
                    raise SkillCatalogError(f"unsupported frontmatter field: {key}")
                if key in fields:
                    raise SkillCatalogError(f"duplicate frontmatter field: {key}")
                fields[key] = (value or "", [])
                current = key
            else:
                if current is None:
                    raise SkillCatalogError("SKILL.md frontmatter is malformed")
                fields[current][1].append(line)

        name = fields.get("name", ("", []))[0].strip()
        if not name:
            raise SkillCatalogError("name is required")
        description_value, description_lines = fields.get("description", ("", []))
        if description_value in {">", "|"}:
            description_value = ""
        description_parts = [
            description_value.strip(),
            *(line.strip() for line in description_lines),
        ]
        description = " ".join(part for part in description_parts if part)
        if not description:
            raise SkillCatalogError("description is required")
        license_value = fields.get("license", ("", []))[0].strip() or None
        metadata_lines = fields.get("metadata", ("", []))[1]
        related = WesleySkillCatalog._metadata_list(metadata_lines, "related")
        reads = WesleySkillCatalog._metadata_list(metadata_lines, "reads")
        return _Frontmatter(
            name=name,
            description=description,
            license=license_value,
            related=related,
            reads=reads,
        )

    @staticmethod
    def _metadata_list(lines: list[str], requested: str) -> tuple[str, ...]:
        active = False
        values: list[str] = []
        for line in lines:
            key_match = METADATA_KEY.fullmatch(line)
            if key_match is not None:
                key, inline = key_match.groups()
                active = key == requested
                if active and inline:
                    if inline.startswith("[") and inline.endswith("]"):
                        values.extend(
                            item.strip().strip("'\"")
                            for item in inline[1:-1].split(",")
                            if item.strip()
                        )
                    else:
                        values.append(inline.strip().strip("'\""))
                continue
            item_match = LIST_ITEM.fullmatch(line)
            if active and item_match is not None:
                values.append(item_match.group(1).strip().strip("'\""))
        return tuple(dict.fromkeys(value for value in values if SKILL_ID.fullmatch(value)))

    def _read_chinese_metadata(self) -> dict[str, _ChineseMetadata]:
        document = self.root / "docs" / "skills-list.md"
        if (
            document.is_symlink()
            or not document.is_file()
            or not document.resolve().is_relative_to(self.root)
        ):
            return {}
        try:
            lines = document.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            return {}
        complete_list = False
        category: str | None = None
        metadata: dict[str, _ChineseMetadata] = {}
        for line in lines:
            if line.strip() == "## 完整 Skills 清单":
                complete_list = True
                continue
            if not complete_list:
                continue
            if line.startswith("### "):
                category = line.removeprefix("### ").strip()
                continue
            if category is None or not line.startswith("|"):
                continue
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if len(cells) != 3 or not cells[0].startswith("`"):
                continue
            skill_id = cells[0].strip("`")
            if SKILL_ID.fullmatch(skill_id):
                metadata[skill_id] = _ChineseMetadata(cells[1], cells[2], category)
        return metadata


class SkillCatalogService:
    """Expose catalog state and explicit user install/uninstall operations."""

    def __init__(
        self,
        *,
        catalog: WesleySkillCatalog,
        database: Database,
        workspaces: WorkspaceRepository,
        ledger: EventLedger,
    ) -> None:
        self.catalog = catalog
        self.database = database
        self.workspaces = workspaces
        self.ledger = ledger

    async def list_for_workspace(self, workspace_id: str) -> tuple[SkillCatalogEntry, ...]:
        workspace = await self.workspaces.get(workspace_id)
        if workspace is None:
            raise LookupError(workspace_id)
        entries = await asyncio.to_thread(self.catalog.scan)
        return tuple(self._with_installation(entry, workspace) for entry in entries)

    async def install_for_workspace(
        self,
        skill_id: str,
        *,
        workspace_id: str,
        expected_workspace_version: int,
    ) -> InstalledPackage:
        workspace = await self.workspaces.get(workspace_id)
        if workspace is None:
            raise LookupError(workspace_id)
        internal_root = Path(workspace.internal_root)
        await asyncio.to_thread(internal_root.mkdir, parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=internal_root, prefix=".skill-import-") as staging:
            snapshot = await asyncio.to_thread(
                self.catalog.materialize_snapshot,
                skill_id,
                Path(staging) / skill_id,
            )
            installer = PackageInstaller(
                database=self.database,
                workspaces=self.workspaces,
                ledger=self.ledger,
                store=PackageStore(workspace.internal_root),
            )
            return await installer.install(
                snapshot,
                workspace_id=workspace_id,
                expected_workspace_version=expected_workspace_version,
                installed_by="user",
            )

    async def uninstall_from_workspace(
        self,
        skill_id: str,
        *,
        workspace_id: str,
        expected_workspace_version: int,
    ) -> Workspace:
        if not SKILL_ID.fullmatch(skill_id):
            raise SkillCatalogError("skill id is invalid")
        workspace = await self.workspaces.get(workspace_id)
        if workspace is None:
            raise LookupError(workspace_id)
        installer = PackageInstaller(
            database=self.database,
            workspaces=self.workspaces,
            ledger=self.ledger,
            store=PackageStore(workspace.internal_root),
        )
        return await installer.uninstall_skill(
            skill_id,
            workspace_id=workspace_id,
            expected_workspace_version=expected_workspace_version,
            uninstalled_by="user",
        )

    @staticmethod
    def _with_installation(entry: SkillCatalogEntry, workspace: Workspace) -> SkillCatalogEntry:
        prefix = f"skill:{entry.name}@"
        reference = next(
            (item for item in workspace.extension_refs if item.startswith(prefix)),
            None,
        )
        installed = entry.name in workspace.installed_skills and reference is not None
        return entry.model_copy(
            update={
                "installed": installed,
                "installed_reference": reference if installed else None,
            }
        )
