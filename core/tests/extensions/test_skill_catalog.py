import json
from pathlib import Path

import pytest

from weatherflow.events import EventLedger
from weatherflow.extensions import PackageIntegrityError, PackageStore
from weatherflow.extensions.catalog import (
    SkillCatalogError,
    SkillCatalogService,
    WesleySkillCatalog,
)
from weatherflow.storage import Database
from weatherflow.workspaces import Workspace, WorkspaceRepository, WorkspaceVersionConflict


def write_skill(
    repository: Path,
    directory: str,
    *,
    name: str | None = None,
    description: str = "Use this skill for careful release reviews.",
    frontmatter: str | None = None,
    extra_files: dict[str, str] | None = None,
) -> Path:
    skill_root = repository / "skills" / directory
    skill_root.mkdir(parents=True)
    if frontmatter is None:
        frontmatter = (
            "---\n"
            f"name: {name or directory}\n"
            f"description: {description}\n"
            "metadata:\n"
            "  related:\n"
            "  - test-driven-development\n"
            "  reads:\n"
            "  - project-context\n"
            "license: MIT\n"
            "---\n"
        )
    (skill_root / "SKILL.md").write_text(
        f"{frontmatter}\n# Release review\n\nKeep evidence concise.\n",
        encoding="utf-8",
    )
    for relative, content in (extra_files or {}).items():
        path = skill_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return skill_root


def write_chinese_catalog(repository: Path) -> None:
    docs = repository / "docs"
    docs.mkdir(parents=True)
    (docs / "skills-list.md").write_text(
        """# Skills 清单

## 完整 Skills 清单

### 工程流程与代码质量

| Skill | 职责 | 边界 |
| --- | --- | --- |
| `release-review` | 审查发布证据与风险。 | 不执行发布，也不授予工具权限。 |
""",
        encoding="utf-8",
    )


def test_catalog_scans_verified_metadata_and_chinese_descriptions(tmp_path: Path) -> None:
    repository = tmp_path / "wesley-skills"
    write_skill(repository, "release-review")
    write_chinese_catalog(repository)

    entries = WesleySkillCatalog(repository).scan()

    assert len(entries) == 1
    entry = entries[0]
    assert entry.id == "release-review"
    assert entry.name == "release-review"
    assert entry.description == "Use this skill for careful release reviews."
    assert entry.description_zh == "审查发布证据与风险。"
    assert entry.boundary_zh == "不执行发布，也不授予工具权限。"
    assert entry.category == "工程流程与代码质量"
    assert entry.related == ("test-driven-development",)
    assert entry.reads == ("project-context",)
    assert entry.license == "MIT"
    assert entry.validation_status == "valid"
    assert entry.validation_errors == ()
    assert len(entry.source_digest) == 64


def test_catalog_reports_invalid_frontmatter_mismatch_and_duplicate_ids(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "wesley-skills"
    write_skill(repository, "broken", frontmatter="---\nname: broken\n---\n")
    write_skill(repository, "mismatch", name="other-name")
    write_skill(repository, "duplicate-a", name="same-name")
    write_skill(repository, "duplicate-b", name="same-name")

    entries = {entry.id: entry for entry in WesleySkillCatalog(repository).scan()}

    assert entries["broken"].validation_status == "invalid"
    assert "description is required" in entries["broken"].validation_errors
    assert entries["mismatch"].validation_status == "invalid"
    assert (
        "frontmatter name must match the skill directory" in entries["mismatch"].validation_errors
    )
    assert "duplicate frontmatter name" in entries["duplicate-a"].validation_errors
    assert "duplicate frontmatter name" in entries["duplicate-b"].validation_errors


def test_catalog_rejects_traversal_and_source_symlinks(tmp_path: Path) -> None:
    repository = tmp_path / "wesley-skills"
    write_skill(
        repository,
        "unsafe-name",
        name="../outside",
    )
    linked = write_skill(repository, "linked")
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    (linked / "outside.txt").symlink_to(outside)

    entries = {entry.id: entry for entry in WesleySkillCatalog(repository).scan()}

    assert entries["unsafe-name"].validation_status == "invalid"
    assert "frontmatter name is invalid" in entries["unsafe-name"].validation_errors
    assert entries["linked"].validation_status == "invalid"
    assert "skill source contains a symlink" in entries["linked"].validation_errors
    with pytest.raises(SkillCatalogError):
        WesleySkillCatalog(repository).materialize_snapshot(
            "linked",
            tmp_path / "snapshot",
        )


@pytest.mark.parametrize(
    "reference",
    [
        "skill:../outside@1.0.0:" + "a" * 64,
        "unknown:release-review@1.0.0:" + "a" * 64,
        "skill:release-review@latest:" + "a" * 64,
        "skill:release-review@1.0.0:not-a-digest",
    ],
)
def test_package_store_never_removes_an_unvalidated_reference(
    tmp_path: Path,
    reference: str,
) -> None:
    with pytest.raises(PackageIntegrityError):
        PackageStore(tmp_path / "internal").remove_reference(reference)


async def test_snapshot_is_store_compatible_and_independent_from_source(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "wesley-skills"
    source = write_skill(
        repository,
        "release-review",
        extra_files={"references/checklist.md": "Verify the changelog."},
    )
    catalog = WesleySkillCatalog(repository)

    snapshot = catalog.materialize_snapshot("release-review", tmp_path / "snapshot")
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["kind"] == "skill"
    assert manifest["name"] == "release-review"
    assert manifest["prompt_file"] == "SKILL.md"
    assert manifest["suggested_tool_ids"] == []
    assert {item["path"] for item in manifest["files"]} == {
        "SKILL.md",
        "references/checklist.md",
    }

    store = PackageStore(tmp_path / "internal")
    installed = await store.install_verified(snapshot)
    for path in sorted(source.rglob("*"), reverse=True):
        path.unlink() if path.is_file() else path.rmdir()
    source.rmdir()
    for path in sorted(snapshot.rglob("*"), reverse=True):
        path.unlink() if path.is_file() else path.rmdir()
    snapshot.rmdir()

    prompt = await store.load_skill_prompt(installed.reference)
    assert "Keep evidence concise." in prompt


async def test_service_reports_install_state_and_uninstalls_skill(tmp_path: Path) -> None:
    repository = tmp_path / "wesley-skills"
    write_skill(repository, "release-review")
    database = Database(tmp_path / "weatherflow.db")
    await database.initialize()
    workspaces = WorkspaceRepository(database)
    workspace = Workspace.new(
        name="Skills",
        action_roots=[tmp_path / "project"],
        internal_root=tmp_path / "internal",
        artifact_root=tmp_path / "artifacts",
    )
    await workspaces.create(workspace)
    service = SkillCatalogService(
        catalog=WesleySkillCatalog(repository),
        database=database,
        workspaces=workspaces,
        ledger=EventLedger(database),
    )

    before = await service.list_for_workspace(workspace.id)
    assert before[0].installed is False
    installed = await service.install_for_workspace(
        "release-review",
        workspace_id=workspace.id,
        expected_workspace_version=0,
    )
    after = await service.list_for_workspace(workspace.id)
    assert after[0].installed is True
    assert after[0].installed_reference == installed.reference

    updated = await service.uninstall_from_workspace(
        "release-review",
        workspace_id=workspace.id,
        expected_workspace_version=1,
    )
    assert updated.version == 2
    assert updated.installed_skills == ()
    assert updated.extension_refs == ()
    with pytest.raises(PackageIntegrityError):
        await PackageStore(workspace.internal_root).load_skill_prompt(installed.reference)

    events = await EventLedger(database).list_stream("workspace", workspace.id)
    assert [event.type for event in events] == [
        "extension.installed",
        "extension.uninstalled",
    ]


async def test_service_fails_closed_for_invalid_skill_and_stale_workspace(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "wesley-skills"
    write_skill(repository, "release-review")
    write_skill(repository, "broken", frontmatter="not frontmatter")
    database = Database(tmp_path / "weatherflow.db")
    await database.initialize()
    workspaces = WorkspaceRepository(database)
    workspace = Workspace.new(
        name="Skills",
        action_roots=[tmp_path / "project"],
        internal_root=tmp_path / "internal",
        artifact_root=tmp_path / "artifacts",
    )
    await workspaces.create(workspace)
    service = SkillCatalogService(
        catalog=WesleySkillCatalog(repository),
        database=database,
        workspaces=workspaces,
        ledger=EventLedger(database),
    )

    with pytest.raises(SkillCatalogError):
        await service.install_for_workspace(
            "broken",
            workspace_id=workspace.id,
            expected_workspace_version=0,
        )
    await service.install_for_workspace(
        "release-review",
        workspace_id=workspace.id,
        expected_workspace_version=0,
    )
    with pytest.raises(WorkspaceVersionConflict):
        await service.uninstall_from_workspace(
            "release-review",
            workspace_id=workspace.id,
            expected_workspace_version=0,
        )
