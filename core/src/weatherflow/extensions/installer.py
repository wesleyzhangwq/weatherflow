from datetime import UTC, datetime
from pathlib import Path

from weatherflow.capabilities import ToolEffect, ToolSpec
from weatherflow.events import Actor, Event, EventLedger
from weatherflow.extensions.models import InstalledPackage
from weatherflow.extensions.store import PackageStore
from weatherflow.runtime import (
    DefinitiveToolError,
    ToolExecutionContext,
    ToolExecutionResult,
)
from weatherflow.storage import Database
from weatherflow.workspaces import WorkspaceRepository, WorkspaceVersionConflict


def package_install_tool_spec() -> ToolSpec:
    return ToolSpec(
        tool_id="extensions.install",
        description="Install a verified local extension package after explicit approval",
        input_schema={
            "type": "object",
            "required": ["source_path", "expected_workspace_version"],
        },
        output_schema={"type": "object"},
        effect=ToolEffect.INSTALL,
        required_scopes=frozenset({"extensions:install"}),
        source="builtin.extensions",
        source_version="1",
    )


class PackageInstaller:
    def __init__(
        self,
        *,
        database: Database,
        workspaces: WorkspaceRepository,
        ledger: EventLedger,
        store: PackageStore,
    ) -> None:
        self.database = database
        self.workspaces = workspaces
        self.ledger = ledger
        self.store = store

    async def install(
        self,
        source: Path,
        *,
        workspace_id: str,
        expected_workspace_version: int,
        installed_by: str,
    ) -> InstalledPackage:
        installed = await self.store.install_verified(source)
        try:
            async with self.database.transaction() as connection:
                workspace = await self.workspaces.get_in(connection, workspace_id)
                if workspace is None:
                    raise LookupError(workspace_id)
                if workspace.version != expected_workspace_version:
                    raise WorkspaceVersionConflict(workspace_id)
                manifest = installed.manifest
                values = {
                    "version": workspace.version + 1,
                    "updated_at": datetime.now(UTC),
                    "extension_refs": tuple(
                        sorted(
                            {
                                *(
                                    reference
                                    for reference in workspace.extension_refs
                                    if not reference.startswith(f"{manifest.kind}:{manifest.name}@")
                                ),
                                installed.reference,
                            }
                        )
                    ),
                }
                if manifest.kind == "capability_pack":
                    values["installed_packs"] = tuple(
                        sorted({*workspace.installed_packs, manifest.name})
                    )
                elif manifest.kind == "skill":
                    values["installed_skills"] = tuple(
                        sorted({*workspace.installed_skills, manifest.name})
                    )
                else:
                    values["agent_definitions"] = tuple(
                        sorted({*workspace.agent_definitions, manifest.name})
                    )
                updated = workspace.model_copy(update=values)
                await self.workspaces.update_in(
                    connection,
                    updated,
                    expected_version=workspace.version,
                )
                await self.ledger.append_in(
                    connection,
                    Event.new(
                        type="extension.installed",
                        actor=Actor.USER if installed_by == "user" else Actor.SYSTEM,
                        stream_kind="workspace",
                        stream_id=workspace.id,
                        correlation_id=workspace.id,
                        payload={
                            "reference": installed.reference,
                            "kind": manifest.kind,
                            "name": manifest.name,
                            "version": manifest.version,
                            "installed_by": installed_by,
                        },
                    ),
                )
        except BaseException:
            self.store.remove(installed)
            raise
        return installed


class PackageInstallExecutor:
    def __init__(
        self,
        *,
        database: Database,
        workspaces: WorkspaceRepository,
        ledger: EventLedger,
    ) -> None:
        self.database = database
        self.workspaces = workspaces
        self.ledger = ledger

    async def execute(
        self,
        tool: ToolSpec,
        arguments: dict,
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        if tool.tool_id != "extensions.install":
            raise LookupError(tool.tool_id)
        if context.action_id is None or context.idempotency_key is None:
            raise PermissionError("extension install requires an approved Action context")
        source_path = arguments.get("source_path")
        expected_version = arguments.get("expected_workspace_version")
        if not isinstance(source_path, str) or not isinstance(expected_version, int):
            raise DefinitiveToolError("invalid extension install arguments")
        workspace = await self.workspaces.get(context.workspace_id)
        if workspace is None:
            raise DefinitiveToolError("Workspace no longer exists")
        installer = PackageInstaller(
            database=self.database,
            workspaces=self.workspaces,
            ledger=self.ledger,
            store=PackageStore(workspace.internal_root),
        )
        try:
            installed = await installer.install(
                Path(source_path),
                workspace_id=workspace.id,
                expected_workspace_version=expected_version,
                installed_by="agent",
            )
        except (ValueError, WorkspaceVersionConflict) as error:
            raise DefinitiveToolError(str(error)) from error
        return ToolExecutionResult(
            output={
                "reference": installed.reference,
                "kind": installed.manifest.kind,
                "name": installed.manifest.name,
                "version": installed.manifest.version,
            }
        )
