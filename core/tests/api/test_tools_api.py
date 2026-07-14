import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from weatherflow.api.app import create_app
from weatherflow.bootstrap import RuntimeContainer
from weatherflow.config import Settings


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
                    "confirm": True,
                },
            )
            assert install.status_code == 200
            assert install.json()["installed"] is True

            mcp = client.get("/v1/mcp/catalog", params={"workspace_id": workspace.id})
            assert mcp.status_code == 200
            by_id = {item["preset_id"]: item for item in mcp.json()}
            assert by_id["filesystem"]["installed"] is False
            assert by_id["playwright"]["available"] is True
            assert by_id["fetch"]["available"] is False
            assert "package_name" not in by_id["filesystem"]


def test_install_endpoints_require_an_explicit_confirmation(tmp_path: Path) -> None:
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
                    "confirm": False,
                },
            )
            assert skill.status_code == 422
            assert skill.json()["detail"]["code"] == "confirmation_required"

            mcp = client.post(
                "/v1/mcp/filesystem/install",
                json={"workspace_id": workspace.id, "confirm": False},
            )
            assert mcp.status_code == 422
            assert mcp.json()["detail"]["code"] == "confirmation_required"
