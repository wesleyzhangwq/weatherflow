import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from weatherflow.api.app import create_app
from weatherflow.bootstrap import RuntimeContainer
from weatherflow.config import Settings


class RecordingMCPInstaller:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Path, str]] = []

    async def install(self, preset, *, internal_root: Path, approved_action_id: str) -> None:
        self.calls.append((preset.preset_id, internal_root, approved_action_id))


def _skill_catalog(root: Path) -> Path:
    skill = root / "skills" / "focus-coach"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        """---
name: focus-coach
description: Help a user shape one bounded focus session.
---

Keep the user's goal unchanged and reduce unnecessary task switching.
""",
        encoding="utf-8",
    )
    return root


def test_automation_skill_and_mcp_surfaces_use_one_workspace_boundary(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        skill_catalog_root=_skill_catalog(tmp_path / "wesley-skills"),
    )
    project = tmp_path / "project"
    project.mkdir()

    with asyncio.Runner() as runner:
        container = runner.run(RuntimeContainer.create(settings))
        mcp_installer = RecordingMCPInstaller()
        container.mcp_management.package_installer = mcp_installer
        workspace = runner.run(container.authorize_workspace(name="Project", path=project))
        with TestClient(create_app(settings, container=container)) as client:
            created = client.post(
                "/v1/automations",
                json={
                    "workspace_id": workspace.id,
                    "name": "每日整理",
                    "prompt": "整理今天的三个重点，不执行外部写入。",
                    "schedule": {
                        "kind": "daily",
                        "timezone": "Asia/Shanghai",
                        "at_time": "09:00:00",
                    },
                },
            )
            assert created.status_code == 201
            automation = created.json()
            assert automation["status"] == "enabled"

            run_now = client.post(f"/v1/automations/{automation['id']}/run")
            assert run_now.status_code == 200
            assert run_now.json()["status"] == "submitted"
            assert run_now.json()["client_request_id"].startswith(
                f"automation:{automation['id']}:manual:"
            )
            history = client.get(f"/v1/automations/{automation['id']}/history")
            assert history.status_code == 200
            assert history.json()[0]["run_id"] == run_now.json()["run_id"]

            skills = client.get("/v1/skills/catalog", params={"workspace_id": workspace.id})
            assert skills.status_code == 200
            assert skills.json()[0]["id"] == "focus-coach"
            assert skills.json()[0]["installed"] is False

            install = client.post(
                "/v1/skills/focus-coach/install",
                json={
                    "workspace_id": workspace.id,
                    "expected_workspace_version": workspace.version,
                    "client_request_id": "install-focus-coach",
                },
            )
            assert install.status_code == 202
            assert install.json()["status"] == "needs_approval"
            before_approval = client.get(
                "/v1/skills/catalog", params={"workspace_id": workspace.id}
            )
            assert before_approval.json()[0]["installed"] is False
            approved_skill = client.post(
                f"/v1/approvals/{install.json()['approval_id']}/decision",
                json={
                    "decision": "approve",
                    "expected_version": install.json()["approval_version"],
                    "workspace_id": workspace.id,
                },
            )
            assert approved_skill.status_code == 200
            assert approved_skill.json()["action"]["status"] == "succeeded"
            installed_skills = client.get(
                "/v1/skills/catalog", params={"workspace_id": workspace.id}
            )
            assert installed_skills.json()[0]["installed"] is True

            mcp = client.get("/v1/mcp/catalog", params={"workspace_id": workspace.id})
            assert mcp.status_code == 200
            by_id = {item["preset_id"]: item for item in mcp.json()}
            assert by_id["filesystem"]["installed"] is False
            assert "playwright" not in by_id
            assert "fetch" not in by_id
            assert "context7" not in by_id
            assert "package_name" not in by_id["filesystem"]

            mcp_install = client.post(
                "/v1/mcp/filesystem/install",
                json={
                    "workspace_id": workspace.id,
                    "client_request_id": "install-filesystem-mcp",
                },
            )
            assert mcp_install.status_code == 202
            assert mcp_install.json()["status"] == "needs_approval"
            assert mcp_installer.calls == []
            approved_mcp = client.post(
                f"/v1/approvals/{mcp_install.json()['approval_id']}/decision",
                json={
                    "decision": "approve",
                    "expected_version": mcp_install.json()["approval_version"],
                    "workspace_id": workspace.id,
                },
            )
            assert approved_mcp.status_code == 200
            assert approved_mcp.json()["action"]["status"] == "succeeded"
            assert mcp_installer.calls[0][0] == "filesystem"
            assert mcp_installer.calls[0][2] == mcp_install.json()["action_id"]


def test_install_endpoints_reject_boolean_confirmation_as_authority(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        skill_catalog_root=_skill_catalog(tmp_path / "wesley-skills"),
    )
    with asyncio.Runner() as runner:
        container = runner.run(RuntimeContainer.create(settings))
        workspace = container.default_workspace
        with TestClient(create_app(settings, container=container)) as client:
            skill = client.post(
                "/v1/skills/focus-coach/install",
                json={
                    "workspace_id": workspace.id,
                    "expected_workspace_version": workspace.version,
                    "client_request_id": "skill-boolean-bypass",
                    "confirm": True,
                },
            )
            assert skill.status_code == 422

            mcp = client.post(
                "/v1/mcp/filesystem/install",
                json={
                    "workspace_id": workspace.id,
                    "client_request_id": "mcp-boolean-bypass",
                    "confirm": True,
                },
            )
            assert mcp.status_code == 422


def test_install_approval_cannot_cross_workspace_or_expiry_boundary(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        skill_catalog_root=_skill_catalog(tmp_path / "wesley-skills"),
    )
    owner_root = tmp_path / "owner"
    other_root = tmp_path / "other"
    owner_root.mkdir()
    other_root.mkdir()
    with asyncio.Runner() as runner:
        container = runner.run(RuntimeContainer.create(settings))
        owner = runner.run(container.authorize_workspace(name="Owner", path=owner_root))
        other = runner.run(container.authorize_workspace(name="Other", path=other_root))
        with TestClient(create_app(settings, container=container)) as client:
            cross_workspace = client.post(
                "/v1/skills/focus-coach/install",
                json={
                    "workspace_id": owner.id,
                    "expected_workspace_version": owner.version,
                    "client_request_id": "cross-workspace-install",
                },
            )
            denied = client.post(
                f"/v1/approvals/{cross_workspace.json()['approval_id']}/decision",
                json={
                    "decision": "approve",
                    "expected_version": 0,
                    "workspace_id": other.id,
                },
            )
            assert denied.status_code == 404
            assert denied.json()["detail"]["code"] == "approval_not_found"

            expiring = client.post(
                "/v1/skills/focus-coach/install",
                json={
                    "workspace_id": owner.id,
                    "expected_workspace_version": owner.version,
                    "client_request_id": "expired-install",
                },
            )
            runner.run(
                container.approval_coordinator.expire(
                    approval_id=expiring.json()["approval_id"],
                    expected_version=0,
                )
            )
            expired = client.post(
                f"/v1/approvals/{expiring.json()['approval_id']}/decision",
                json={
                    "decision": "approve",
                    "expected_version": 1,
                    "workspace_id": owner.id,
                },
            )
            assert expired.status_code == 409
            assert expired.json()["detail"]["code"] == "approval_already_decided"

            catalog = client.get("/v1/skills/catalog", params={"workspace_id": owner.id})
            assert catalog.json()[0]["installed"] is False
