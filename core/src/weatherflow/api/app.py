import asyncio
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import (
    FastAPI,
    HTTPException,
    Query,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from weatherflow import __version__
from weatherflow.api.schemas import (
    ApprovalDecisionRequest,
    ApprovalView,
    AutomationCreateRequest,
    AutomationUpdateRequest,
    ConnectorConfigureResponse,
    ConnectorConversationAccessRequest,
    ConnectorDisconnectRequest,
    ConnectorSettingsRequest,
    DesktopSnapshot,
    HealthResponse,
    MCPInstallRequest,
    MCPMutationRequest,
    MCPPresetView,
    ModelConfigurationResponse,
    ModelConfigureRequest,
    ModelProviderList,
    OnboardingCompleteRequest,
    ResetConfirmRequest,
    RunCreateRequest,
    SessionCreateRequest,
    SessionUpdateRequest,
    SkillInstallRequest,
    SkillMutationRequest,
    SystemStatus,
    VersionedRequest,
    WorkspaceCreateRequest,
)
from weatherflow.artifacts import ArtifactManifest
from weatherflow.automations import (
    Automation,
    AutomationNotFoundError,
    AutomationRunLink,
    AutomationStatus,
    AutomationVersionConflict,
)
from weatherflow.bootstrap import ContextRunNotFoundError, RuntimeContainer, WorkspaceNotFoundError
from weatherflow.config import Settings
from weatherflow.connectors import (
    ComposioErrorCode,
    ComposioGatewayError,
    ConnectHandoff,
    ConnectionAttempt,
    ConnectorKind,
    ConnectorSnapshot,
    ConnectorStatus,
)
from weatherflow.events import Event, UnknownEventCursor
from weatherflow.extensions import SkillCatalogEntry, SkillCatalogError
from weatherflow.mcp import (
    MCPNotInstalledError,
    MCPPresetUnavailableError,
    UnknownMCPPresetError,
)
from weatherflow.models import (
    AnthropicAuthenticationError,
    AnthropicError,
    AnthropicRetryableError,
    MiniMaxAuthenticationError,
    MiniMaxError,
    MiniMaxRetryableError,
    ModelProvider,
    OpenAIAuthenticationError,
    OpenAIError,
    OpenAIRetryableError,
    ProviderModelCatalog,
    provider_presets,
)
from weatherflow.operations import (
    DiagnosticExport,
    InstallationApprovalRequest,
    InstallationBoundaryError,
    InstallationRequestError,
    LocalMetrics,
    OnboardingState,
    ResetCategory,
    ResetPreview,
    ResetResult,
    SecurityScan,
    SecurityScanner,
)
from weatherflow.rhythm import CurrentRhythm, RhythmInsights, RhythmInsightsService, RhythmSignal
from weatherflow.runs import InvalidTransitionError, Run, RunIdempotencyConflict, RunStatus
from weatherflow.sessions import (
    ConversationSession,
    SessionNotFoundError,
    SessionVersionConflict,
)
from weatherflow.trust import (
    ApprovalAlreadyDecided,
    ApprovalBundle,
    ApprovalStatus,
)
from weatherflow.workspaces import Workspace, WorkspaceVersionConflict


def create_app(
    settings: Settings | None = None,
    *,
    container: RuntimeContainer | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        application.state.lifespan_active = True
        try:
            service = application.state.container
            if service is not None:
                await service.start_background()
            yield
        finally:
            service = application.state.container
            if service is not None:
                await service.close()
            application.state.lifespan_active = False

    app = FastAPI(title="WeatherFlow Core", version=__version__, lifespan=lifespan)
    app.state.settings = resolved_settings
    app.state.container = container
    app.state.container_lock = asyncio.Lock()
    app.state.lifespan_active = False

    @app.exception_handler(ComposioGatewayError)
    async def composio_gateway_failure(
        _request: Request, error: ComposioGatewayError
    ) -> JSONResponse:
        status_by_code = {
            ComposioErrorCode.AUTH: 401,
            ComposioErrorCode.RATE_LIMIT: 429,
            ComposioErrorCode.INPUT: 400,
            ComposioErrorCode.NOT_FOUND: 404,
            ComposioErrorCode.TRANSPORT: 503,
            ComposioErrorCode.UPSTREAM: 502,
            ComposioErrorCode.AUTH_CONFIG_REQUIRED: 409,
        }
        return JSONResponse(
            status_code=status_by_code[error.code],
            content={
                "detail": {
                    "code": f"connector_broker_{error.code.value}",
                    "retryable": error.retryable,
                }
            },
        )

    @app.exception_handler(MiniMaxError)
    @app.exception_handler(OpenAIError)
    @app.exception_handler(AnthropicError)
    async def model_provider_failure(_request: Request, error: Exception) -> JSONResponse:
        if isinstance(
            error,
            (
                MiniMaxAuthenticationError,
                OpenAIAuthenticationError,
                AnthropicAuthenticationError,
            ),
        ):
            status_code = 401
            code = "model_provider_authentication_failed"
            retryable = False
        elif isinstance(
            error,
            (MiniMaxRetryableError, OpenAIRetryableError, AnthropicRetryableError),
        ):
            status_code = 503
            code = "model_provider_unavailable"
            retryable = True
        else:
            status_code = 502
            code = "model_provider_invalid_response"
            retryable = False
        return JSONResponse(
            status_code=status_code,
            content={"detail": {"code": code, "retryable": retryable}},
        )

    @app.middleware("http")
    async def authenticate_bridge(request: Request, call_next):
        if request.method == "OPTIONS":
            return await call_next(request)
        expected = resolved_settings.bridge_token
        if expected is not None and not _valid_token(
            request.headers.get("authorization"), expected
        ):
            return JSONResponse(
                status_code=401,
                content={"detail": {"code": "bridge_unauthorized"}},
            )
        return await call_next(request)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:1421",
            "http://127.0.0.1:1421",
            "tauri://localhost",
            "http://tauri.localhost",
        ],
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    async def runtime() -> RuntimeContainer:
        if app.state.container is None:
            async with app.state.container_lock:
                if app.state.container is None:
                    app.state.container = await RuntimeContainer.create(resolved_settings)
        service = app.state.container
        await service.start_background(
            include_connector_sync=app.state.lifespan_active,
            include_automation_scheduler=app.state.lifespan_active,
        )
        return service

    async def selected_workspace(service: RuntimeContainer, workspace_id: str | None) -> Workspace:
        workspace = (
            await service.workspaces.get(workspace_id)
            if workspace_id is not None
            else service.default_workspace
        )
        if workspace is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "workspace_not_found", "workspace_id": workspace_id},
            )
        return workspace

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(version=__version__)

    @app.post("/v1/runs", response_model=Run, status_code=status.HTTP_201_CREATED)
    async def create_run(request: RunCreateRequest) -> Run:
        service = await runtime()
        try:
            run, _ = await service.submit_run(
                user_intent=request.user_intent,
                client_request_id=request.client_request_id,
                workspace_id=request.workspace_id,
                session_id=request.session_id,
                context_run_id=request.context_run_id,
                execute=False,
            )
        except SessionNotFoundError as error:
            raise HTTPException(
                status_code=404,
                detail={"code": "session_not_found", "session_id": str(error)},
            ) from error
        except RunIdempotencyConflict as error:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "client_request_conflict",
                    "client_request_id": str(error),
                },
            ) from error
        except ContextRunNotFoundError as error:
            raise HTTPException(
                status_code=404,
                detail={"code": "context_run_not_found", "context_run_id": str(error)},
            ) from error
        except WorkspaceNotFoundError as error:
            raise HTTPException(
                status_code=404,
                detail={"code": "workspace_not_found", "workspace_id": str(error)},
            ) from error
        stored = await service.runs.get(run.id)
        if stored is None:
            raise RuntimeError(run.id)
        resumable = {
            RunStatus.QUEUED,
            RunStatus.PLANNING,
            RunStatus.RUNNING,
            RunStatus.PAUSED,
        }
        if stored.status in resumable:
            if request.execute:
                await service.resume_run(run.id)
            else:
                service.schedule_run(run.id)
            stored = await service.runs.get(run.id)
            if stored is None:
                raise RuntimeError(run.id)
        return stored

    @app.get("/v1/runs", response_model=list[Run])
    async def list_runs(
        workspace_id: str | None = None,
        session_id: str | None = None,
        limit: int = Query(default=50, ge=1, le=1000),
    ) -> list[Run]:
        service = await runtime()
        if session_id is not None:
            if workspace_id is None:
                raise HTTPException(
                    status_code=422,
                    detail={"code": "workspace_required"},
                )
            await selected_workspace(service, workspace_id)
            session = await service.sessions.get_for_workspace(session_id, workspace_id)
            if session is None:
                raise HTTPException(
                    status_code=404,
                    detail={"code": "session_not_found", "session_id": session_id},
                )
        return await service.runs.list_recent(
            limit=limit,
            workspace_id=workspace_id,
            session_id=session_id,
        )

    @app.get("/v1/sessions", response_model=list[ConversationSession])
    async def list_sessions(
        workspace_id: str,
        limit: int = Query(default=200, ge=1, le=1000),
    ) -> list[ConversationSession]:
        service = await runtime()
        await selected_workspace(service, workspace_id)
        return await service.sessions.list(workspace_id, limit=limit)

    @app.post(
        "/v1/sessions",
        response_model=ConversationSession,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_session(request: SessionCreateRequest) -> ConversationSession:
        service = await runtime()
        await selected_workspace(service, request.workspace_id)
        session = ConversationSession.new(
            workspace_id=request.workspace_id,
            title=request.title,
        )
        await service.sessions.create(session)
        return session

    @app.patch("/v1/sessions/{session_id}", response_model=ConversationSession)
    async def update_session(
        session_id: str,
        request: SessionUpdateRequest,
        workspace_id: str,
    ) -> ConversationSession:
        service = await runtime()
        await selected_workspace(service, workspace_id)
        current = await service.sessions.get_for_workspace(session_id, workspace_id)
        if current is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "session_not_found", "session_id": session_id},
            )
        try:
            return await service.sessions.update(
                session_id,
                workspace_id=workspace_id,
                expected_version=current.version,
                title=request.title,
                pinned=request.pinned,
            )
        except SessionNotFoundError as error:
            raise HTTPException(
                status_code=404,
                detail={"code": "session_not_found", "session_id": session_id},
            ) from error
        except SessionVersionConflict as error:
            raise HTTPException(
                status_code=409,
                detail={"code": "session_version_conflict", "session_id": session_id},
            ) from error

    @app.delete("/v1/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_session(session_id: str, workspace_id: str) -> None:
        service = await runtime()
        await selected_workspace(service, workspace_id)
        try:
            await service.delete_session(session_id, workspace_id=workspace_id)
        except SessionNotFoundError as error:
            raise HTTPException(
                status_code=404,
                detail={"code": "session_not_found", "session_id": session_id},
            ) from error

    @app.get("/v1/workspaces", response_model=list[Workspace])
    async def list_workspaces() -> list[Workspace]:
        service = await runtime()
        return [
            workspace
            for workspace in await service.workspaces.list_all()
            if workspace.id != service.default_workspace.id
        ]

    @app.post(
        "/v1/workspaces",
        response_model=Workspace,
        status_code=status.HTTP_201_CREATED,
    )
    async def authorize_workspace(request: WorkspaceCreateRequest) -> Workspace:
        service = await runtime()
        try:
            return await service.authorize_workspace(name=request.name, path=request.path)
        except ValueError as error:
            raise HTTPException(
                status_code=422,
                detail={"code": "workspace_path_invalid"},
            ) from error

    @app.get("/v1/workspaces/{workspace_id}", response_model=Workspace)
    async def get_workspace(workspace_id: str) -> Workspace:
        service = await runtime()
        workspace = await service.workspaces.get(workspace_id)
        if workspace is None or workspace.id == service.default_workspace.id:
            raise HTTPException(
                status_code=404,
                detail={"code": "workspace_not_found", "workspace_id": workspace_id},
            )
        return workspace

    @app.get("/v1/automations", response_model=list[Automation])
    async def list_automations(
        workspace_id: str,
        automation_status: AutomationStatus | None = None,
    ) -> list[Automation]:
        service = await runtime()
        await selected_workspace(service, workspace_id)
        return await service.automations.list(workspace_id, status=automation_status)

    @app.post(
        "/v1/automations",
        response_model=Automation,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_automation(request: AutomationCreateRequest) -> Automation:
        service = await runtime()
        await selected_workspace(service, request.workspace_id)
        return await service.automations.create(
            workspace_id=request.workspace_id,
            name=request.name,
            prompt=request.prompt,
            schedule=request.schedule,
        )

    @app.patch("/v1/automations/{automation_id}", response_model=Automation)
    async def update_automation(
        automation_id: str,
        request: AutomationUpdateRequest,
    ) -> Automation:
        service = await runtime()
        try:
            return await service.automations.update(
                automation_id,
                expected_version=request.expected_version,
                name=request.name,
                prompt=request.prompt,
                schedule=request.schedule,
            )
        except AutomationNotFoundError as error:
            raise HTTPException(
                status_code=404,
                detail={"code": "automation_not_found", "automation_id": automation_id},
            ) from error
        except AutomationVersionConflict as error:
            raise HTTPException(
                status_code=409,
                detail={"code": "automation_version_conflict"},
            ) from error

    @app.post("/v1/automations/{automation_id}/pause", response_model=Automation)
    async def pause_automation(
        automation_id: str,
        request: VersionedRequest,
    ) -> Automation:
        service = await runtime()
        try:
            return await service.automations.pause(
                automation_id,
                expected_version=request.expected_version,
            )
        except AutomationNotFoundError as error:
            raise HTTPException(status_code=404, detail={"code": "automation_not_found"}) from error
        except AutomationVersionConflict as error:
            raise HTTPException(
                status_code=409,
                detail={"code": "automation_version_conflict"},
            ) from error

    @app.post("/v1/automations/{automation_id}/resume", response_model=Automation)
    async def resume_automation(
        automation_id: str,
        request: VersionedRequest,
    ) -> Automation:
        service = await runtime()
        try:
            return await service.automations.resume(
                automation_id,
                expected_version=request.expected_version,
            )
        except AutomationNotFoundError as error:
            raise HTTPException(status_code=404, detail={"code": "automation_not_found"}) from error
        except AutomationVersionConflict as error:
            raise HTTPException(
                status_code=409,
                detail={"code": "automation_version_conflict"},
            ) from error

    @app.post("/v1/automations/{automation_id}/run", response_model=AutomationRunLink)
    async def run_automation_now(automation_id: str) -> AutomationRunLink:
        service = await runtime()
        try:
            return await service.automations.run_now(automation_id)
        except AutomationNotFoundError as error:
            raise HTTPException(status_code=404, detail={"code": "automation_not_found"}) from error

    @app.get(
        "/v1/automations/{automation_id}/history",
        response_model=list[AutomationRunLink],
    )
    async def automation_history(
        automation_id: str,
        limit: int = Query(default=100, ge=1, le=1000),
    ) -> list[AutomationRunLink]:
        service = await runtime()
        if await service.automations.get(automation_id) is None:
            raise HTTPException(status_code=404, detail={"code": "automation_not_found"})
        return await service.automations.history(automation_id, limit=limit)

    @app.delete("/v1/automations/{automation_id}", status_code=204)
    async def delete_automation(
        automation_id: str,
        request: VersionedRequest,
    ) -> Response:
        service = await runtime()
        if not request.confirm:
            raise HTTPException(status_code=422, detail={"code": "confirmation_required"})
        try:
            await service.automations.delete(
                automation_id,
                expected_version=request.expected_version,
            )
        except AutomationNotFoundError as error:
            raise HTTPException(
                status_code=404,
                detail={"code": "automation_not_found", "automation_id": automation_id},
            ) from error
        except AutomationVersionConflict as error:
            raise HTTPException(
                status_code=409,
                detail={"code": "automation_version_conflict"},
            ) from error
        return Response(status_code=204)

    @app.get("/v1/skills/catalog", response_model=list[SkillCatalogEntry])
    async def list_skills(workspace_id: str) -> list[SkillCatalogEntry]:
        service = await runtime()
        await selected_workspace(service, workspace_id)
        try:
            return list(await service.skill_catalog.list_for_workspace(workspace_id))
        except SkillCatalogError as error:
            raise HTTPException(
                status_code=503,
                detail={"code": "skill_catalog_unavailable"},
            ) from error

    @app.post(
        "/v1/skills/{skill_id}/install",
        response_model=InstallationApprovalRequest,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def install_skill(
        skill_id: str,
        request: SkillInstallRequest,
    ) -> InstallationApprovalRequest:
        service = await runtime()
        workspace = await selected_workspace(service, request.workspace_id)
        try:
            return await service.installation_approvals.request_skill(
                skill_id=skill_id,
                workspace=workspace,
                expected_workspace_version=request.expected_workspace_version,
                client_request_id=request.client_request_id,
            )
        except WorkspaceVersionConflict as error:
            raise HTTPException(
                status_code=409,
                detail={"code": "workspace_version_conflict"},
            ) from error
        except (SkillCatalogError, InstallationRequestError, ValueError) as error:
            raise HTTPException(status_code=422, detail={"code": "skill_invalid"}) from error

    @app.delete("/v1/skills/{skill_id}", response_model=SkillCatalogEntry)
    async def uninstall_skill(
        skill_id: str,
        request: SkillMutationRequest,
    ) -> SkillCatalogEntry:
        service = await runtime()
        await selected_workspace(service, request.workspace_id)
        if not request.confirm:
            raise HTTPException(status_code=422, detail={"code": "confirmation_required"})
        try:
            await service.skill_catalog.uninstall_from_workspace(
                skill_id,
                workspace_id=request.workspace_id,
                expected_workspace_version=request.expected_workspace_version,
            )
            entries = await service.skill_catalog.list_for_workspace(request.workspace_id)
        except WorkspaceVersionConflict as error:
            raise HTTPException(
                status_code=409,
                detail={"code": "workspace_version_conflict"},
            ) from error
        except (LookupError, SkillCatalogError) as error:
            raise HTTPException(status_code=404, detail={"code": "skill_not_installed"}) from error
        return next(entry for entry in entries if entry.id == skill_id)

    async def mcp_catalog_views(
        service: RuntimeContainer,
        workspace_id: str,
    ) -> list[MCPPresetView]:
        summaries = {item.preset_id: item for item in service.mcp_management.catalog.summaries()}
        states = await service.mcp_management.list_statuses(workspace_id)
        return [
            MCPPresetView(
                **summaries[state.preset_id].model_dump(),
                installed=state.installed,
                enabled=state.enabled,
                health=state.health.value,
                tool_ids=state.tool_ids,
                installed_at=state.installed_at,
                checked_at=state.checked_at,
            )
            for state in states
        ]

    @app.get("/v1/mcp/catalog", response_model=list[MCPPresetView])
    async def list_mcp_presets(workspace_id: str) -> list[MCPPresetView]:
        service = await runtime()
        await selected_workspace(service, workspace_id)
        return await mcp_catalog_views(service, workspace_id)

    @app.post(
        "/v1/mcp/{preset_id}/install",
        response_model=InstallationApprovalRequest,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def install_mcp_preset(
        preset_id: str,
        request: MCPInstallRequest,
    ) -> InstallationApprovalRequest:
        service = await runtime()
        workspace = await selected_workspace(service, request.workspace_id)
        try:
            return await service.installation_approvals.request_mcp(
                preset_id=preset_id,
                workspace=workspace,
                client_request_id=request.client_request_id,
            )
        except UnknownMCPPresetError as error:
            raise HTTPException(status_code=404, detail={"code": "mcp_preset_not_found"}) from error
        except MCPPresetUnavailableError as error:
            raise HTTPException(
                status_code=422,
                detail={"code": "mcp_preset_unavailable"},
            ) from error

    @app.post("/v1/mcp/{preset_id}/enable", response_model=MCPPresetView)
    async def enable_mcp_preset(
        preset_id: str,
        request: MCPMutationRequest,
    ) -> MCPPresetView:
        service = await runtime()
        workspace = await selected_workspace(service, request.workspace_id)
        try:
            await service.enable_mcp(preset_id, workspace)
        except UnknownMCPPresetError as error:
            raise HTTPException(status_code=404, detail={"code": "mcp_preset_not_found"}) from error
        except MCPNotInstalledError as error:
            raise HTTPException(status_code=409, detail={"code": "mcp_not_installed"}) from error
        return next(
            item
            for item in await mcp_catalog_views(service, workspace.id)
            if item.preset_id == preset_id
        )

    @app.post("/v1/mcp/{preset_id}/disable", response_model=MCPPresetView)
    async def disable_mcp_preset(
        preset_id: str,
        request: MCPMutationRequest,
    ) -> MCPPresetView:
        service = await runtime()
        workspace = await selected_workspace(service, request.workspace_id)
        try:
            await service.mcp_management.disable(preset_id, workspace_id=workspace.id)
        except UnknownMCPPresetError as error:
            raise HTTPException(status_code=404, detail={"code": "mcp_preset_not_found"}) from error
        except MCPNotInstalledError as error:
            raise HTTPException(status_code=409, detail={"code": "mcp_not_installed"}) from error
        return next(
            item
            for item in await mcp_catalog_views(service, workspace.id)
            if item.preset_id == preset_id
        )

    @app.get("/v1/runs/{run_id}", response_model=Run)
    async def get_run(run_id: str) -> Run:
        service = await runtime()
        run = await service.runs.get(run_id)
        if run is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "run_not_found", "run_id": run_id},
            )
        return run

    @app.post("/v1/runs/{run_id}/cancel", response_model=Run)
    async def cancel_run(run_id: str) -> Run:
        service = await runtime()
        run = await service.runs.get(run_id)
        if run is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "run_not_found", "run_id": run_id},
            )
        try:
            return await service.cancel_run(run.id)
        except InvalidTransitionError as error:
            raise HTTPException(
                status_code=409,
                detail={"code": "invalid_run_transition", "status": run.status.value},
            ) from error

    @app.get("/v1/runs/{run_id}/timeline", response_model=list[Event])
    async def run_timeline(run_id: str) -> list[Event]:
        service = await runtime()
        run = await service.runs.get(run_id)
        if run is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "run_not_found", "run_id": run_id},
            )
        return await service.ledger.list_correlation(run_id, limit=1000)

    @app.get("/v1/approvals", response_model=list[ApprovalView])
    async def list_approvals(
        approval_status: ApprovalStatus | None = None,
    ) -> list[ApprovalView]:
        service = await runtime()
        approvals = await service.approvals.list_all(status=approval_status)
        views: list[ApprovalView] = []
        for approval in approvals:
            action = await service.actions.get(approval.action_id)
            if action is None:
                raise RuntimeError(f"approval {approval.id} has no Action")
            views.append(
                ApprovalView.model_validate(
                    {
                        **approval.model_dump(mode="json"),
                        "tool_id": action.tool_id,
                        "effect": action.effect,
                        "preview": action.preview,
                    }
                )
            )
        return views

    @app.post("/v1/approvals/{approval_id}/decision", response_model=ApprovalBundle)
    async def decide_approval(approval_id: str, request: ApprovalDecisionRequest) -> ApprovalBundle:
        service = await runtime()
        try:
            approval = await service.approvals.get(approval_id)
            action = await service.actions.get(approval.action_id) if approval else None
            if action is not None and await service.installation_approvals.is_managed_install(
                action
            ):
                if request.workspace_id is None:
                    raise HTTPException(
                        status_code=422,
                        detail={"code": "workspace_required"},
                    )
                bundle = await service.installation_approvals.decide(
                    approval_id=approval_id,
                    expected_version=request.expected_version,
                    approved=request.decision == "approve",
                    workspace_id=request.workspace_id,
                    rationale=request.rationale,
                )
            else:
                bundle = await service.approval_coordinator.decide(
                    approval_id=approval_id,
                    expected_version=request.expected_version,
                    approved=request.decision == "approve",
                    decided_by="user",
                    rationale=request.rationale,
                )
        except LookupError as error:
            raise HTTPException(
                status_code=404,
                detail={"code": "approval_not_found", "approval_id": approval_id},
            ) from error
        except InstallationBoundaryError as error:
            raise HTTPException(
                status_code=404,
                detail={"code": "approval_not_found", "approval_id": approval_id},
            ) from error
        except ApprovalAlreadyDecided as error:
            raise HTTPException(
                status_code=409,
                detail={"code": "approval_already_decided", "approval_id": approval_id},
            ) from error
        if request.resume and not await service.installation_approvals.is_managed_install(
            bundle.action
        ):
            await service.resume_run(bundle.run.id)
            action = await service.actions.get(bundle.action.id)
            approval = await service.approvals.get(bundle.approval.id)
            run = await service.runs.get(bundle.run.id)
            if action is not None and approval is not None and run is not None:
                bundle = ApprovalBundle(action=action, approval=approval, run=run)
        return bundle

    @app.get("/v1/artifacts/{artifact_id}", response_model=ArtifactManifest)
    async def get_artifact(artifact_id: str) -> ArtifactManifest:
        service = await runtime()
        artifact = await service.artifacts.get(artifact_id)
        if artifact is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "artifact_not_found", "artifact_id": artifact_id},
            )
        return artifact

    @app.get("/v1/runs/{run_id}/artifacts", response_model=list[ArtifactManifest])
    async def list_run_artifacts(run_id: str) -> list[ArtifactManifest]:
        service = await runtime()
        run = await service.runs.get(run_id)
        if run is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "run_not_found", "run_id": run_id},
            )
        return await service.run_artifacts(run_id)

    @app.get("/v1/artifacts/{artifact_id}/content")
    async def get_artifact_content(artifact_id: str) -> Response:
        service = await runtime()
        artifact = await service.artifacts.get(artifact_id)
        if artifact is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "artifact_not_found", "artifact_id": artifact_id},
            )
        workspace_run = await service.runs.get(artifact.run_id)
        workspace = (
            await service.workspaces.get(workspace_run.workspace_id)
            if workspace_run is not None
            else None
        )
        if workspace is None:
            raise HTTPException(status_code=409, detail={"code": "artifact_workspace_missing"})
        content = await asyncio.to_thread(
            _read_artifact,
            workspace.artifact_root,
            artifact.relative_path,
        )
        return Response(content=content, media_type=artifact.media_type)

    @app.post(
        "/v1/rhythm/signals",
        response_model=CurrentRhythm,
        status_code=status.HTTP_201_CREATED,
    )
    async def ingest_rhythm_signal(
        signal: RhythmSignal, workspace_id: str | None = None
    ) -> CurrentRhythm:
        service = await runtime()
        workspace = await selected_workspace(service, workspace_id)
        if signal.kind == "activity_metadata":
            onboarding = await service.onboarding.get(workspace.id)
            if not onboarding.metadata_sensor_enabled:
                raise HTTPException(
                    status_code=409,
                    detail={"code": "metadata_sensor_consent_required"},
                )
        return await service.rhythm.ingest(workspace.id, signal)

    @app.get("/v1/rhythm/current", response_model=CurrentRhythm)
    async def current_rhythm(workspace_id: str | None = None) -> CurrentRhythm:
        service = await runtime()
        workspace = await selected_workspace(service, workspace_id)
        return await service.rhythm.current(workspace.id)

    @app.get("/v1/rhythm/insights", response_model=RhythmInsights)
    async def rhythm_insights(workspace_id: str | None = None) -> RhythmInsights:
        service = await runtime()
        workspace = await selected_workspace(service, workspace_id)
        insights = RhythmInsightsService(
            rhythm=service.rhythm,
            ledger=service.ledger,
            profiles=service.memory.assertions,
        )
        return await insights.current(workspace.id)

    @app.get("/v1/desktop/snapshot", response_model=DesktopSnapshot)
    async def desktop_snapshot(workspace_id: str | None = None) -> DesktopSnapshot:
        service = await runtime()
        workspace = await selected_workspace(service, workspace_id)
        rhythm = await service.rhythm.current(workspace.id)
        recent = await service.runs.list_recent(limit=1, workspace_id=workspace.id)
        onboarding = await service.onboarding.get(workspace.id)
        return DesktopSnapshot(
            rhythm=rhythm,
            latest_run=recent[0] if recent else None,
            workspace=workspace,
            metadata_sensor_enabled=onboarding.metadata_sensor_enabled,
        )

    @app.get("/v1/system/status", response_model=SystemStatus)
    async def system_status(workspace_id: str | None = None) -> SystemStatus:
        service = await runtime()
        workspace = await selected_workspace(service, workspace_id)
        providers: dict[str, str] = {}
        for tool in service.catalog.all():
            if tool.source.startswith("builtin.") and tool.source not in {
                "builtin.developer",
                "builtin.personal_operations",
            }:
                providers[tool.source] = tool.health.value
        for connection in service.mcp_connections:
            health = (
                "available"
                if any(tool.health.value == "available" for tool in connection.tools)
                else "unavailable"
            )
            providers[f"mcp.{connection.client.server_name}"] = health
        onboarding = await service.onboarding.get(workspace.id)
        model_status = await service.model_configurations.status(workspace.id)
        return SystemStatus(
            workspace_id=workspace.id,
            onboarding_completed=onboarding.completed,
            installed_packs=workspace.installed_packs,
            providers=providers,
            behavior_sensor={
                "mode": "metadata_only",
                "enabled": onboarding.metadata_sensor_enabled,
                "raw_content_captured": False,
                "fallback_to_deliberate_signals": True,
            },
            retention={
                "raw_behavior": "72h",
                "aggregate_behavior": "90d",
                "memory": "until_explicit_reset",
            },
            model=model_status,
        )

    @app.get("/v1/models/providers", response_model=ModelProviderList)
    async def model_providers() -> ModelProviderList:
        return ModelProviderList(providers=provider_presets())

    @app.get(
        "/v1/models/providers/{provider}/models",
        response_model=ProviderModelCatalog,
    )
    async def provider_models(provider: ModelProvider) -> ProviderModelCatalog:
        service = await runtime()
        return await service.model_configurations.available_models(provider)

    @app.post("/v1/models/configure", response_model=ModelConfigurationResponse)
    async def configure_model(
        request: ModelConfigureRequest,
        workspace_id: str | None = None,
    ) -> ModelConfigurationResponse:
        service = await runtime()
        workspace = await selected_workspace(service, workspace_id)
        try:
            configuration = await service.configure_model(
                workspace_id=workspace.id,
                provider=request.provider,
                model=request.model,
                base_url=request.base_url,
            )
        except ValueError as error:
            raise HTTPException(
                status_code=422,
                detail={"code": "model_configuration_invalid"},
            ) from error
        return ModelConfigurationResponse(
            configuration=configuration,
            status=await service.model_configurations.status(workspace.id),
        )

    @app.post("/v1/connectors/configure", response_model=ConnectorConfigureResponse)
    async def configure_connectors() -> ConnectorConfigureResponse:
        service = await runtime()
        await service.connector_service.configure()
        service.start_connector_background()
        return ConnectorConfigureResponse()

    @app.get("/v1/connectors", response_model=list[ConnectorStatus])
    async def list_connectors(workspace_id: str | None = None) -> list[ConnectorStatus]:
        service = await runtime()
        workspace = await selected_workspace(service, workspace_id)
        return await service.connector_service.statuses(workspace.id)

    @app.post(
        "/v1/connectors/{connector}/connect",
        response_model=ConnectHandoff,
        status_code=status.HTTP_201_CREATED,
    )
    async def connect_connector(
        connector: ConnectorKind, workspace_id: str | None = None
    ) -> ConnectHandoff:
        service = await runtime()
        workspace = await selected_workspace(service, workspace_id)
        try:
            return await service.connector_service.connect(workspace.id, connector)
        except LookupError as error:
            raise HTTPException(
                status_code=409, detail={"code": "connector_not_configured"}
            ) from error

    @app.get("/v1/connector-attempts/{attempt_id}", response_model=ConnectionAttempt)
    async def refresh_connector_attempt(attempt_id: str) -> ConnectionAttempt:
        service = await runtime()
        try:
            return await service.connector_service.refresh_attempt(attempt_id)
        except LookupError as error:
            raise HTTPException(
                status_code=404,
                detail={"code": "connection_attempt_not_found", "attempt_id": attempt_id},
            ) from error

    @app.post("/v1/connectors/{connector}/settings", status_code=204)
    async def update_connector_settings(
        connector: ConnectorKind,
        request: ConnectorSettingsRequest,
        workspace_id: str | None = None,
    ) -> Response:
        service = await runtime()
        workspace = await selected_workspace(service, workspace_id)
        try:
            await service.connector_service.update_settings(
                workspace.id,
                connector,
                auto_fetch_enabled=request.auto_fetch_enabled,
                interval_minutes=request.interval_minutes,
            )
        except LookupError as error:
            raise HTTPException(
                status_code=409, detail={"code": "connector_not_connected"}
            ) from error
        except PermissionError as error:
            raise HTTPException(
                status_code=409,
                detail={"code": "connector_auto_fetch_unsupported"},
            ) from error
        return Response(status_code=204)

    @app.post(
        "/v1/connectors/{connector}/conversation-access",
        response_model=ConnectorStatus,
    )
    async def update_connector_conversation_access(
        connector: ConnectorKind,
        request: ConnectorConversationAccessRequest,
        workspace_id: str | None = None,
    ) -> ConnectorStatus:
        service = await runtime()
        workspace = await selected_workspace(service, workspace_id)
        try:
            await service.connector_service.update_conversation_access(
                workspace.id,
                connector,
                request.conversation_access,
            )
        except LookupError as error:
            raise HTTPException(
                status_code=409, detail={"code": "connector_not_connected"}
            ) from error
        except PermissionError as error:
            raise HTTPException(
                status_code=409,
                detail={"code": "connector_reauthorization_required"},
            ) from error
        return next(
            status
            for status in await service.connector_service.statuses(workspace.id)
            if status.connector is connector
        )

    @app.post("/v1/connectors/{connector}/sync", response_model=ConnectorSnapshot)
    async def sync_connector(
        connector: ConnectorKind, workspace_id: str | None = None
    ) -> ConnectorSnapshot:
        service = await runtime()
        workspace = await selected_workspace(service, workspace_id)
        try:
            return await service.connector_sync.sync(workspace.id, connector)
        except LookupError as error:
            raise HTTPException(
                status_code=409, detail={"code": "connector_not_connected"}
            ) from error

    @app.post("/v1/connectors/{connector}/disconnect", status_code=204)
    async def disconnect_connector(
        connector: ConnectorKind,
        request: ConnectorDisconnectRequest,
        workspace_id: str | None = None,
    ) -> Response:
        if not request.confirm:
            raise HTTPException(status_code=409, detail={"code": "explicit_confirmation_required"})
        service = await runtime()
        workspace = await selected_workspace(service, workspace_id)
        await service.connector_service.disconnect(workspace.id, connector)
        return Response(status_code=204)

    @app.get("/v1/onboarding", response_model=OnboardingState)
    async def onboarding_state(workspace_id: str | None = None) -> OnboardingState:
        service = await runtime()
        workspace = await selected_workspace(service, workspace_id)
        return await service.onboarding.get(workspace.id)

    @app.post("/v1/onboarding/complete", response_model=OnboardingState)
    async def complete_onboarding(
        request: OnboardingCompleteRequest,
        workspace_id: str | None = None,
    ) -> OnboardingState:
        if not request.confirm_local_ownership:
            raise HTTPException(
                status_code=409,
                detail={"code": "local_ownership_confirmation_required"},
            )
        service = await runtime()
        workspace = await selected_workspace(service, workspace_id)
        return await service.onboarding.complete(
            workspace.id,
            metadata_sensor_enabled=request.enable_metadata_sensor,
        )

    @app.get("/v1/diagnostics/metrics", response_model=LocalMetrics)
    async def diagnostic_metrics(workspace_id: str | None = None) -> LocalMetrics:
        service = await runtime()
        workspace = await selected_workspace(service, workspace_id)
        return await service.diagnostics.metrics(workspace.id)

    @app.post(
        "/v1/diagnostics/export",
        response_model=DiagnosticExport,
        status_code=status.HTTP_201_CREATED,
    )
    async def export_diagnostics(
        workspace_id: str | None = None,
    ) -> DiagnosticExport:
        service = await runtime()
        workspace = await selected_workspace(service, workspace_id)
        return await service.diagnostics.export(workspace.id)

    @app.get("/v1/privacy/reset/{category}", response_model=ResetPreview)
    async def preview_reset(
        category: ResetCategory, workspace_id: str | None = None
    ) -> ResetPreview:
        service = await runtime()
        workspace = await selected_workspace(service, workspace_id)
        return await service.privacy.preview_reset(workspace.id, category)

    @app.post("/v1/privacy/reset/{category}", response_model=ResetResult)
    async def reset(
        category: ResetCategory,
        request: ResetConfirmRequest,
        workspace_id: str | None = None,
    ) -> ResetResult:
        if not request.confirm:
            raise HTTPException(
                status_code=409,
                detail={"code": "explicit_confirmation_required"},
            )
        service = await runtime()
        workspace = await selected_workspace(service, workspace_id)
        return await service.privacy.reset(workspace.id, category)

    @app.get("/v1/security/scan", response_model=SecurityScan)
    async def security_scan() -> SecurityScan:
        service = await runtime()
        return await SecurityScanner(service.database).scan()

    @app.websocket("/v1/events")
    async def events(websocket: WebSocket, cursor: str | None = None) -> None:
        expected = resolved_settings.bridge_token
        protocols = websocket.headers.get("sec-websocket-protocol")
        if expected is not None and not _valid_websocket_protocol(protocols, expected):
            await websocket.close(code=4401, reason="bridge unauthorized")
            return
        await websocket.accept(
            subprotocol=(
                "weatherflow-v1" if _requests_protocol(protocols, "weatherflow-v1") else None
            )
        )
        service = await runtime()
        current_cursor = cursor
        try:
            while True:
                try:
                    events = await service.ledger.list_after(current_cursor, limit=100)
                except UnknownEventCursor:
                    await websocket.close(code=4409, reason="cursor unavailable; refresh snapshot")
                    return
                for event in events:
                    await websocket.send_json(event.model_dump(mode="json"))
                    current_cursor = event.id
                if not events:
                    try:
                        message = await asyncio.wait_for(websocket.receive(), timeout=0.25)
                    except TimeoutError:
                        continue
                    if message["type"] == "websocket.disconnect":
                        return
        except (asyncio.CancelledError, WebSocketDisconnect, RuntimeError):
            return

    return app


app = create_app()


def _read_artifact(root_value: str, relative_path: str) -> bytes:
    root = Path(root_value).resolve()
    path = (root / relative_path).resolve()
    if not path.is_relative_to(root):
        raise RuntimeError("artifact path escaped root")
    return path.read_bytes()


def _valid_token(authorization: str | None, expected: str) -> bool:
    if authorization is None or not authorization.startswith("Bearer "):
        return False
    return secrets.compare_digest(authorization.removeprefix("Bearer "), expected)


def _requests_protocol(header: str | None, expected: str) -> bool:
    if header is None:
        return False
    return any(
        secrets.compare_digest(candidate.strip(), expected) for candidate in header.split(",")
    )


def _valid_websocket_protocol(header: str | None, expected: str) -> bool:
    return _requests_protocol(header, f"weatherflow-auth.{expected}")
