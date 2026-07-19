import hashlib
import json
from pathlib import Path

import pytest

from weatherflow.bootstrap import RuntimeContainer
from weatherflow.config import Settings
from weatherflow.events import EventLedger
from weatherflow.extensions import (
    AgentDefinitionPackageManifest,
    PackageInstaller,
    PackageIntegrityError,
    PackageStore,
    package_install_tool_spec,
)
from weatherflow.runs import ToolMode
from weatherflow.runtime import DelegationTurn, FinalTurn, ToolCallTurn
from weatherflow.storage import Database
from weatherflow.workspaces import Workspace, WorkspaceRepository

ROOT = Path(__file__).resolve().parents[3]


def write_package(
    root: Path,
    *,
    kind: str = "agent_definition",
    name: str = "release-auditor",
    content: str = "Audit release evidence only.",
) -> Path:
    root.mkdir()
    prompt = root / "prompt.md"
    prompt.write_text(content)
    manifest = {
        "schema_version": "1",
        "kind": kind,
        "name": name,
        "version": "1.0.0",
        "description": "Test extension",
        "files": [
            {
                "path": "prompt.md",
                "sha256": hashlib.sha256(content.encode()).hexdigest(),
            }
        ],
    }
    if kind == "agent_definition":
        manifest.update(
            {
                "agent_id": "release-auditor",
                "prompt_file": "prompt.md",
                "is_leaf": True,
                "tool_filter": ["developer.read_file"],
                "skill_filter": [],
                "max_steps": 6,
            }
        )
    elif kind == "skill":
        manifest.update(
            {
                "prompt_file": "prompt.md",
                "suggested_tool_ids": ["developer.read_file"],
            }
        )
    else:
        manifest.update(
            {
                "tool_ids": ["developer.read_file"],
                "requested_scopes": ["workspace:read"],
            }
        )
    (root / "manifest.json").write_text(json.dumps(manifest))
    return root


async def setup(tmp_path: Path):
    database = Database(tmp_path / "weatherflow.db")
    await database.initialize()
    workspace = Workspace.new(
        name="Extensions",
        action_roots=[tmp_path / "project"],
        internal_root=tmp_path / "internal",
        artifact_root=tmp_path / "artifacts",
    )
    workspaces = WorkspaceRepository(database)
    await workspaces.create(workspace)
    store = PackageStore(workspace.internal_root)
    installer = PackageInstaller(
        database=database,
        workspaces=workspaces,
        ledger=EventLedger(database),
        store=store,
    )
    return workspaces, workspace, store, installer


async def test_agent_definition_install_is_atomic_versioned_and_loadable(
    tmp_path: Path,
) -> None:
    workspaces, workspace, store, installer = await setup(tmp_path)
    source = write_package(tmp_path / "source")

    installed = await installer.install(
        source,
        workspace_id=workspace.id,
        expected_workspace_version=workspace.version,
        installed_by="user",
    )

    updated = await workspaces.get(workspace.id)
    assert updated is not None and updated.version == 1
    assert updated.agent_definitions == ("release-auditor",)
    assert updated.extension_refs == (installed.reference,)
    definition = await store.load_agent_definition(installed.reference)
    assert definition == AgentDefinitionPackageManifest(
        **installed.manifest.model_dump()
    ).to_agent_definition("Audit release evidence only.")
    assert definition.is_leaf
    assert definition.tool_filter == frozenset({"developer.read_file"})


@pytest.mark.parametrize("kind", ["capability_pack", "skill"])
async def test_pack_and_skill_install_do_not_grant_scopes(
    tmp_path: Path,
    kind: str,
) -> None:
    workspaces, workspace, _, installer = await setup(tmp_path)
    source = write_package(tmp_path / "source", kind=kind, name=f"test-{kind}")

    await installer.install(
        source,
        workspace_id=workspace.id,
        expected_workspace_version=workspace.version,
        installed_by="user",
    )

    updated = await workspaces.get(workspace.id)
    assert updated is not None and updated.granted_scopes == frozenset()
    if kind == "capability_pack":
        assert updated.installed_packs == ("test-capability_pack",)
    else:
        assert updated.installed_skills == ("test-skill",)


async def test_tampered_or_symlinked_package_fails_without_workspace_update(
    tmp_path: Path,
) -> None:
    workspaces, workspace, _, installer = await setup(tmp_path)
    tampered = write_package(tmp_path / "tampered")
    (tampered / "prompt.md").write_text("tampered")

    with pytest.raises(PackageIntegrityError):
        await installer.install(
            tampered,
            workspace_id=workspace.id,
            expected_workspace_version=workspace.version,
            installed_by="user",
        )

    linked = write_package(tmp_path / "linked")
    (linked / "prompt.md").unlink()
    (linked / "prompt.md").symlink_to(tmp_path / "outside")
    with pytest.raises(PackageIntegrityError):
        await installer.install(
            linked,
            workspace_id=workspace.id,
            expected_workspace_version=workspace.version,
            installed_by="user",
        )
    assert await workspaces.get(workspace.id) == workspace


def test_model_driven_package_install_is_always_approval_classified() -> None:
    tool = package_install_tool_spec()

    assert tool.effect == "install"
    assert tool.required_scopes == frozenset({"workspace:write"})


@pytest.mark.parametrize(
    "source",
    sorted((ROOT / "extensions/first-party").glob("*/*")),
    ids=lambda path: path.name,
)
async def test_first_party_packages_use_the_public_verified_contract(
    tmp_path: Path,
    source: Path,
) -> None:
    installed = await PackageStore(tmp_path / "internal").install_verified(source)

    assert installed.manifest.version == "3.0.0"
    assert installed.reference.endswith(installed.manifest.digest())


class ExtensionModel:
    def __init__(self) -> None:
        self.turns = [
            DelegationTurn(agent_id="release-auditor", task="Audit the release"),
            FinalTurn(content="Audit passed"),
            FinalTurn(content="Done"),
        ]
        self.requests = []

    async def complete(self, request):
        self.requests.append(request)
        return self.turns.pop(0)


async def test_installed_skill_and_agent_definition_are_frozen_per_run(
    tmp_path: Path,
) -> None:
    model = ExtensionModel()
    container = await RuntimeContainer.create(Settings(data_dir=tmp_path), model=model)
    workspace = container.default_workspace
    installer = PackageInstaller(
        database=container.database,
        workspaces=container.workspaces,
        ledger=container.ledger,
        store=PackageStore(workspace.internal_root),
    )
    agent_source = write_package(tmp_path / "agent-source")
    skill_source = write_package(
        tmp_path / "skill-source",
        kind="skill",
        name="release-guidance",
        content="Keep the audit concise and evidence-backed.",
    )
    await installer.install(
        agent_source,
        workspace_id=workspace.id,
        expected_workspace_version=0,
        installed_by="user",
    )
    await installer.install(
        skill_source,
        workspace_id=workspace.id,
        expected_workspace_version=1,
        installed_by="user",
    )

    run, outcome = await container.submit_run(
        user_intent="Audit release",
        workspace_id=workspace.id,
    )

    assert outcome is not None and outcome.result_summary == "Done"
    assert model.requests[1].agent.agent_id == "release-auditor"
    assert model.requests[1].agent.system_prompt == "Audit release evidence only."
    checkpoint = await container.checkpoints.get(run.id)
    assert checkpoint is not None
    assert checkpoint.state["skills"]["release-guidance"] == (
        "Keep the audit concise and evidence-backed."
    )


class InstallModel:
    def __init__(self, source: Path) -> None:
        self.turns = [
            ToolCallTurn(
                call_id="install-skill",
                tool_id="extensions.install",
                arguments={
                    "source_path": str(source),
                    "expected_workspace_version": 0,
                },
            ),
            FinalTurn(content="Skill installed for future Runs"),
        ]

    async def complete(self, request):
        return self.turns.pop(0)


async def test_model_driven_install_parks_then_updates_workspace_once(
    tmp_path: Path,
) -> None:
    source = write_package(
        tmp_path / "skill-source",
        kind="skill",
        name="release-guidance",
    )
    container = await RuntimeContainer.create(
        Settings(data_dir=tmp_path / "data"),
        model=InstallModel(source),
    )
    workspace = Workspace.new(
        name="Install approval",
        action_roots=[tmp_path / "project"],
        internal_root=tmp_path / "internal",
        artifact_root=tmp_path / "artifacts",
        granted_scopes={"workspace:write"},
        installed_packs={"developer"},
    )
    await container.workspaces.create(workspace)

    run, waiting = await container.submit_run(
        user_intent="Install the selected release guidance",
        workspace_id=workspace.id,
        tool_mode=ToolMode.BYPASS,
    )
    before = await container.workspaces.get(workspace.id)
    assert waiting is not None and waiting.approval_id is not None
    assert before is not None and before.extension_refs == ()
    await container.approval_coordinator.decide(
        approval_id=waiting.approval_id,
        expected_version=0,
        approved=True,
        decided_by="user",
    )

    completed = await container.resume_run(run.id)

    updated = await container.workspaces.get(workspace.id)
    assert completed.result_summary == "Skill installed for future Runs"
    assert updated is not None and updated.installed_skills == ("release-guidance",)
    assert len(updated.extension_refs) == 1
