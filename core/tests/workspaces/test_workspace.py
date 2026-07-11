from pathlib import Path

from weatherflow.workspaces import NetworkPolicy, Workspace


def test_new_workspace_normalizes_immutable_authority_fields(tmp_path: Path) -> None:
    workspace = Workspace.new(
        name="WeatherFlow",
        action_roots=[tmp_path / "project"],
        internal_root=tmp_path / ".weatherflow",
        artifact_root=tmp_path / "artifacts",
        granted_scopes={"repo:weatherflow", "calendar:read"},
    )

    assert len(workspace.id) == 26
    assert workspace.action_roots == (str((tmp_path / "project").resolve()),)
    assert workspace.granted_scopes == frozenset({"repo:weatherflow", "calendar:read"})
    assert workspace.network_policy is NetworkPolicy.DECLARED


def test_action_path_must_be_inside_an_authorized_root(tmp_path: Path) -> None:
    workspace = Workspace.new(
        name="WeatherFlow",
        action_roots=[tmp_path / "project"],
        internal_root=tmp_path / ".weatherflow",
        artifact_root=tmp_path / "artifacts",
    )

    assert workspace.allows_action_path(tmp_path / "project" / "src" / "app.py")
    assert not workspace.allows_action_path(tmp_path / "other" / "secret.txt")


def test_internal_root_is_never_an_action_root(tmp_path: Path) -> None:
    workspace = Workspace.new(
        name="WeatherFlow",
        action_roots=[tmp_path],
        internal_root=tmp_path / ".weatherflow",
        artifact_root=tmp_path / "artifacts",
    )

    assert not workspace.allows_action_path(tmp_path / ".weatherflow")
    assert not workspace.allows_action_path(tmp_path / ".weatherflow" / "weatherflow.db")
