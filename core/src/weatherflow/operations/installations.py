from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from weatherflow.capabilities import IdempotencyKind, ToolEffect, ToolSpec
from weatherflow.extensions import SkillCatalogError, SkillCatalogService
from weatherflow.mcp import (
    MCPInstallAuthorization,
    MCPManagementService,
    MCPPresetUnavailableError,
    MCPWorkspaceContext,
    UnknownMCPPresetError,
)
from weatherflow.runs import Run, RunCoordinator, RunRepository, RunStatus
from weatherflow.runtime import (
    ActionExecutionCoordinator,
    ActionExecutionStatus,
    DefinitiveToolError,
    ToolExecutionContext,
    ToolExecutionResult,
)
from weatherflow.trust import (
    Action,
    ActionRepository,
    ActionStatus,
    Approval,
    ApprovalBundle,
    ApprovalCoordinator,
    ApprovalRepository,
    ApprovalStatus,
)
from weatherflow.workspaces import Workspace, WorkspaceRepository, WorkspaceVersionConflict

SKILL_INSTALL_TOOL_ID = "skills.catalog_install"
MCP_INSTALL_TOOL_ID = "mcp.preset_install"
MANAGED_INSTALL_TOOL_IDS = frozenset({SKILL_INSTALL_TOOL_ID, MCP_INSTALL_TOOL_ID})


def skill_install_tool_spec() -> ToolSpec:
    return ToolSpec(
        tool_id=SKILL_INSTALL_TOOL_ID,
        description="Install one validated Skill catalog entry after durable approval",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        effect=ToolEffect.INSTALL,
        idempotency=IdempotencyKind.KEY,
        timeout_seconds=120,
        source="builtin.skill_catalog",
        source_version="1",
    )


def mcp_install_tool_spec() -> ToolSpec:
    return ToolSpec(
        tool_id=MCP_INSTALL_TOOL_ID,
        description="Install one fixed MCP preset after durable approval",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        effect=ToolEffect.INSTALL,
        idempotency=IdempotencyKind.KEY,
        timeout_seconds=300,
        source="builtin.mcp_catalog",
        source_version="1",
    )


class InstallationRequestError(ValueError):
    pass


class InstallationBoundaryError(PermissionError):
    pass


class InstallationApprovalRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["needs_approval"] = "needs_approval"
    action_id: str
    approval_id: str
    approval_version: int
    run_id: str
    preview: dict[str, object]

    @classmethod
    def from_bundle(cls, bundle: ApprovalBundle) -> "InstallationApprovalRequest":
        return cls(
            action_id=bundle.action.id,
            approval_id=bundle.approval.id,
            approval_version=bundle.approval.version,
            run_id=bundle.run.id,
            preview=bundle.action.preview,
        )


class _SkillInstallExecutor:
    def __init__(self, catalog: SkillCatalogService) -> None:
        self.catalog = catalog

    async def execute(
        self,
        tool: ToolSpec,
        arguments: dict,
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        if tool.tool_id != SKILL_INSTALL_TOOL_ID or context.action_id is None:
            raise PermissionError("Skill installation requires an approved Action")
        skill_id = arguments.get("skill_id")
        workspace_id = arguments.get("workspace_id")
        expected_version = arguments.get("expected_workspace_version")
        if (
            not isinstance(skill_id, str)
            or workspace_id != context.workspace_id
            or not isinstance(expected_version, int)
        ):
            raise DefinitiveToolError("invalid Skill installation arguments")
        try:
            installed = await self.catalog.install_for_workspace(
                skill_id,
                workspace_id=context.workspace_id,
                expected_workspace_version=expected_version,
            )
        except (SkillCatalogError, ValueError, WorkspaceVersionConflict) as error:
            raise DefinitiveToolError(str(error)) from error
        return ToolExecutionResult(
            output={
                "kind": "skill",
                "name": installed.manifest.name,
                "reference": installed.reference,
            }
        )


class _MCPInstallExecutor:
    def __init__(self, management: MCPManagementService) -> None:
        self.management = management

    async def execute(
        self,
        tool: ToolSpec,
        arguments: dict,
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        if tool.tool_id != MCP_INSTALL_TOOL_ID or context.action_id is None:
            raise PermissionError("MCP installation requires an approved Action")
        preset_id = arguments.get("preset_id")
        workspace_id = arguments.get("workspace_id")
        internal_root = arguments.get("internal_root")
        action_roots = arguments.get("action_roots")
        if (
            not isinstance(preset_id, str)
            or workspace_id != context.workspace_id
            or not isinstance(internal_root, str)
            or not isinstance(action_roots, list)
            or not all(isinstance(root, str) for root in action_roots)
        ):
            raise DefinitiveToolError("invalid MCP installation arguments")
        try:
            state = await self.management.install(
                preset_id,
                workspace=MCPWorkspaceContext(
                    workspace_id=context.workspace_id,
                    internal_root=Path(internal_root),
                    action_roots=tuple(Path(root) for root in action_roots),
                ),
                authorization=MCPInstallAuthorization(approved_action_id=context.action_id),
            )
        except (UnknownMCPPresetError, MCPPresetUnavailableError) as error:
            raise DefinitiveToolError(str(error)) from error
        return ToolExecutionResult(
            output={"kind": "mcp", "preset_id": preset_id, "installed": state.installed}
        )


class InstallationApprovalService:
    def __init__(
        self,
        *,
        workspaces: WorkspaceRepository,
        runs: RunRepository,
        run_coordinator: RunCoordinator,
        actions: ActionRepository,
        approvals: ApprovalRepository,
        approval_coordinator: ApprovalCoordinator,
        action_execution: ActionExecutionCoordinator,
        skill_catalog: SkillCatalogService,
        mcp_management: MCPManagementService,
    ) -> None:
        self.workspaces = workspaces
        self.runs = runs
        self.run_coordinator = run_coordinator
        self.actions = actions
        self.approvals = approvals
        self.approval_coordinator = approval_coordinator
        self.action_execution = action_execution
        self.skill_catalog = skill_catalog
        self.mcp_management = mcp_management
        self.skill_executor = _SkillInstallExecutor(skill_catalog)
        self.mcp_executor = _MCPInstallExecutor(mcp_management)

    async def request_skill(
        self,
        *,
        skill_id: str,
        workspace: Workspace,
        expected_workspace_version: int,
        client_request_id: str,
    ) -> InstallationApprovalRequest:
        if workspace.version != expected_workspace_version:
            raise WorkspaceVersionConflict(workspace.id)
        entries = await self.skill_catalog.list_for_workspace(workspace.id)
        entry = next((item for item in entries if item.id == skill_id), None)
        if entry is None or entry.validation_status != "valid" or entry.installed:
            raise InstallationRequestError(skill_id)
        open_bundle = await self._open_bundle(
            tool_id=SKILL_INSTALL_TOOL_ID,
            workspace_id=workspace.id,
            target_key="skill_id",
            target_value=skill_id,
        )
        if open_bundle is not None:
            return InstallationApprovalRequest.from_bundle(open_bundle)
        bundle = await self._propose(
            workspace=workspace,
            client_request_id=client_request_id,
            tool=skill_install_tool_spec(),
            arguments={
                "skill_id": skill_id,
                "workspace_id": workspace.id,
                "expected_workspace_version": expected_workspace_version,
            },
            preview={
                "operation": "install_skill",
                "skill_id": skill_id,
                "workspace_id": workspace.id,
            },
            user_intent=f"Install Skill {skill_id}",
        )
        return InstallationApprovalRequest.from_bundle(bundle)

    async def request_mcp(
        self,
        *,
        preset_id: str,
        workspace: Workspace,
        client_request_id: str,
    ) -> InstallationApprovalRequest:
        preset = self.mcp_management.catalog.require(preset_id)
        if not preset.available:
            raise MCPPresetUnavailableError(preset.unavailable_reason or preset_id)
        open_bundle = await self._open_bundle(
            tool_id=MCP_INSTALL_TOOL_ID,
            workspace_id=workspace.id,
            target_key="preset_id",
            target_value=preset_id,
        )
        if open_bundle is not None:
            return InstallationApprovalRequest.from_bundle(open_bundle)
        bundle = await self._propose(
            workspace=workspace,
            client_request_id=client_request_id,
            tool=mcp_install_tool_spec(),
            arguments={
                "preset_id": preset_id,
                "workspace_id": workspace.id,
                "internal_root": str(workspace.internal_root),
                "action_roots": list(workspace.action_roots),
            },
            preview={
                "operation": "install_mcp",
                "preset_id": preset_id,
                "workspace_id": workspace.id,
                "version": preset.package_version,
            },
            user_intent=f"Install MCP preset {preset_id}",
        )
        return InstallationApprovalRequest.from_bundle(bundle)

    async def _propose(
        self,
        *,
        workspace: Workspace,
        client_request_id: str,
        tool: ToolSpec,
        arguments: dict[str, object],
        preview: dict[str, object],
        user_intent: str,
    ) -> ApprovalBundle:
        request_key = f"installation:{client_request_id}"
        run = await self.run_coordinator.create_run(
            client_request_id=request_key,
            user_intent=user_intent,
            workspace_id=workspace.id,
        )
        existing = await self.actions.get_by_idempotency_key(request_key)
        if existing is None:
            if run.status is RunStatus.QUEUED:
                run = await self.run_coordinator.transition(
                    run_id=run.id,
                    target=RunStatus.PLANNING,
                    expected_version=run.version,
                )
            if run.status is RunStatus.PLANNING:
                run = await self.run_coordinator.transition(
                    run_id=run.id,
                    target=RunStatus.RUNNING,
                    expected_version=run.version,
                )
        return await self.approval_coordinator.propose(
            run_id=run.id,
            expected_run_version=run.version,
            tool=tool,
            workspace=workspace,
            arguments=arguments,
            idempotency_key=request_key,
            preview=preview,
        )

    async def _open_bundle(
        self,
        *,
        tool_id: str,
        workspace_id: str,
        target_key: str,
        target_value: str,
    ) -> ApprovalBundle | None:
        for action in await self.actions.list_all():
            if (
                action.tool_id != tool_id
                or action.status not in {ActionStatus.PROPOSED, ActionStatus.APPROVED}
                or action.arguments.get("workspace_id") != workspace_id
                or action.arguments.get(target_key) != target_value
            ):
                continue
            approval = await self.approvals.get_by_action_id(action.id)
            run = await self.runs.get(action.run_id)
            if (
                approval is not None
                and run is not None
                and approval.status in {ApprovalStatus.PENDING, ApprovalStatus.APPROVED}
            ):
                return ApprovalBundle(action=action, approval=approval, run=run)
        return None

    async def is_managed_install(self, action: Action) -> bool:
        return action.tool_id in MANAGED_INSTALL_TOOL_IDS

    async def action_for_run(self, run_id: str) -> Action | None:
        action = await self.actions.get_by_run_id(run_id)
        if action is None or action.tool_id not in MANAGED_INSTALL_TOOL_IDS:
            return None
        return action

    async def decide(
        self,
        *,
        approval_id: str,
        expected_version: int,
        approved: bool,
        workspace_id: str,
        rationale: str | None = None,
    ) -> ApprovalBundle:
        approval, action, run, workspace = await self._load_boundary(approval_id, workspace_id)
        bundle = await self.approval_coordinator.decide(
            approval_id=approval.id,
            expected_version=expected_version,
            approved=approved,
            decided_by="user",
            rationale=rationale,
        )
        if not approved:
            return await self._cancel_denied(bundle)
        if bundle.action.status in {
            ActionStatus.SUCCEEDED,
            ActionStatus.FAILED,
            ActionStatus.NEEDS_REVIEW,
        }:
            return await self._refresh_bundle(bundle)
        tool, executor = self._route(action)
        outcome = await self.action_execution.execute(
            action_id=action.id,
            tool=tool,
            workspace=workspace,
            executor=executor,
        )
        current_run = await self.runs.get(run.id)
        if current_run is not None and current_run.status is RunStatus.RUNNING:
            if outcome.status is ActionExecutionStatus.SUCCEEDED:
                await self.run_coordinator.transition(
                    run_id=run.id,
                    target=RunStatus.SUCCEEDED,
                    expected_version=current_run.version,
                    result_summary="Installation completed",
                )
            elif outcome.status is ActionExecutionStatus.FAILED:
                await self.run_coordinator.transition(
                    run_id=run.id,
                    target=RunStatus.FAILED,
                    expected_version=current_run.version,
                    error_class=outcome.action.error_class,
                    error_message=outcome.action.error_message,
                )
        return await self._refresh_bundle(bundle)

    async def recover_executing(self) -> None:
        for action in await self.actions.list_all(status=ActionStatus.EXECUTING):
            if action.tool_id not in MANAGED_INSTALL_TOOL_IDS:
                continue
            run = await self.runs.get(action.run_id)
            workspace = await self.workspaces.get(run.workspace_id) if run else None
            if run is None or workspace is None:
                continue
            tool, executor = self._route(action)
            await self.action_execution.execute(
                action_id=action.id,
                tool=tool,
                workspace=workspace,
                executor=executor,
            )

    async def _load_boundary(
        self, approval_id: str, workspace_id: str
    ) -> tuple[Approval, Action, Run, Workspace]:
        approval = await self.approvals.get(approval_id)
        action = await self.actions.get(approval.action_id) if approval else None
        run = await self.runs.get(approval.run_id) if approval else None
        workspace = await self.workspaces.get(workspace_id)
        if (
            approval is None
            or action is None
            or run is None
            or workspace is None
            or action.tool_id not in MANAGED_INSTALL_TOOL_IDS
            or run.workspace_id != workspace_id
            or action.arguments.get("workspace_id") != workspace_id
        ):
            raise InstallationBoundaryError(approval_id)
        return approval, action, run, workspace

    def _route(self, action: Action):
        if action.tool_id == SKILL_INSTALL_TOOL_ID:
            return skill_install_tool_spec(), self.skill_executor
        if action.tool_id == MCP_INSTALL_TOOL_ID:
            return mcp_install_tool_spec(), self.mcp_executor
        raise InstallationBoundaryError(action.id)

    async def _cancel_denied(self, bundle: ApprovalBundle) -> ApprovalBundle:
        run = await self.runs.get(bundle.run.id)
        if run is not None and run.status is RunStatus.RUNNING:
            await self.run_coordinator.transition(
                run_id=run.id,
                target=RunStatus.CANCELLED,
                expected_version=run.version,
            )
        return await self._refresh_bundle(bundle)

    async def _refresh_bundle(self, bundle: ApprovalBundle) -> ApprovalBundle:
        action = await self.actions.get(bundle.action.id)
        approval = await self.approvals.get(bundle.approval.id)
        run = await self.runs.get(bundle.run.id)
        if action is None or approval is None or run is None:
            raise InstallationBoundaryError(bundle.approval.id)
        return ApprovalBundle(action=action, approval=approval, run=run)
