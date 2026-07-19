import asyncio
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

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
from weatherflow.activity import (
    ActivityCategoryRulesChanged,
    ActivityQueryLimitExceeded,
    ActivitySummarySettingsVersionConflict,
    ActivityWatchProtocolError,
    ActivityWatchUnavailable,
    CategoryMatcher,
    SummaryTaskStatus,
    SummaryTaskType,
)
from weatherflow.api.schemas import (
    ActivityRegenerationRequest,
    ActivityStatisticsView,
    ActivitySummarySettingsUpdateRequest,
    ActivitySummarySettingsView,
    ActivitySummaryTaskView,
    ActivitySummaryView,
    ActivityTimelineEntryView,
    ActivityTrendPointView,
    ActivityWatchDashboardView,
    ActivityWatchSourceStatusView,
    ApprovalDecisionRequest,
    ApprovalView,
    AutomationCreateRequest,
    AutomationUpdateRequest,
    ConnectorConfigureResponse,
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
    OnboardingView,
    ResetConfirmRequest,
    RhythmSignalRequest,
    RunControlCreateRequest,
    RunCreateRequest,
    SessionCreateRequest,
    SessionUpdateRequest,
    SkillInstallRequest,
    SkillMutationRequest,
    SystemStatus,
    VersionedRequest,
    WatchCurrentView,
    WatchOAuthFeedView,
    WatchProfileAssertionView,
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
    ResetCategory,
    ResetPreview,
    ResetResult,
    SecurityScan,
    SecurityScanner,
)
from weatherflow.rhythm import CurrentRhythm
from weatherflow.runs import InvalidTransitionError, Run, RunIdempotencyConflict, RunStatus
from weatherflow.runtime import (
    RunControl,
    RunControlNotFoundError,
    RunControlRejectedError,
)
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
            ComposioErrorCode.BROKER_AUTH: 401,
            ComposioErrorCode.BROKER_PERMISSION: 403,
            ComposioErrorCode.RATE_LIMIT: 429,
            ComposioErrorCode.INPUT: 400,
            ComposioErrorCode.NOT_FOUND: 404,
            ComposioErrorCode.TRANSPORT: 503,
            ComposioErrorCode.UPSTREAM: 502,
            ComposioErrorCode.AUTH_CONFIG_REQUIRED: 409,
        }
        public_code = {
            ComposioErrorCode.AUTH: "connector_provider_auth",
            ComposioErrorCode.BROKER_AUTH: "connector_broker_auth",
            ComposioErrorCode.BROKER_PERMISSION: "connector_broker_permission",
        }.get(error.code, f"connector_broker_{error.code.value}")
        return JSONResponse(
            status_code=status_by_code[error.code],
            content={
                "detail": {
                    "code": public_code,
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

    @app.exception_handler(ActivityWatchUnavailable)
    async def activitywatch_unavailable(
        _request: Request,
        _error: ActivityWatchUnavailable,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "detail": {
                    "code": "activitywatch_unavailable",
                    "retryable": True,
                }
            },
        )

    @app.exception_handler(ActivityWatchProtocolError)
    async def activitywatch_invalid_response(
        _request: Request,
        _error: ActivityWatchProtocolError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=502,
            content={
                "detail": {
                    "code": "activitywatch_invalid_response",
                    "retryable": False,
                }
            },
        )

    @app.exception_handler(ActivityQueryLimitExceeded)
    async def activity_query_limit_exceeded(
        _request: Request,
        _error: ActivityQueryLimitExceeded,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "detail": {
                    "code": "activity_query_limit_exceeded",
                    "retryable": False,
                }
            },
        )

    @app.exception_handler(ActivityCategoryRulesChanged)
    async def activity_category_rules_changed(
        _request: Request,
        _error: ActivityCategoryRulesChanged,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={
                "detail": {
                    "code": "activity_category_rules_changed",
                    "retryable": True,
                }
            },
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
            include_activity_scheduler=app.state.lifespan_active,
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

    @app.get(
        "/v1/watch/settings/summary",
        response_model=ActivitySummarySettingsView,
    )
    async def watch_summary_settings() -> ActivitySummarySettingsView:
        service = await runtime()
        return ActivitySummarySettingsView.model_validate(
            _as_mapping(await service.activity.summary_settings())
        )

    @app.patch(
        "/v1/watch/settings/summary",
        response_model=ActivitySummarySettingsView,
    )
    async def update_watch_summary_settings(
        request: ActivitySummarySettingsUpdateRequest,
    ) -> ActivitySummarySettingsView:
        service = await runtime()
        workspace = await selected_workspace(service, request.model_workspace_id)
        configuration = await service.model_configurations.repository.get(workspace.id)
        if configuration is None:
            raise HTTPException(
                status_code=409,
                detail={"code": "activity_summary_model_not_configured"},
            )
        try:
            updated = await service.activity.update_summary_settings(
                model_workspace_id=workspace.id,
                provider=configuration.provider.value,
                model=request.model,
                model_configuration_version=configuration.version,
                expected_version=request.expected_version,
            )
        except ActivitySummarySettingsVersionConflict as error:
            raise HTTPException(
                status_code=409,
                detail={"code": "activity_summary_settings_version_conflict"},
            ) from error
        except ValueError as error:
            raise HTTPException(
                status_code=422,
                detail={"code": "activity_summary_settings_invalid"},
            ) from error
        return ActivitySummarySettingsView.model_validate(_as_mapping(updated))

    @app.get("/v1/watch/source-status", response_model=ActivityWatchSourceStatusView)
    async def watch_source_status() -> ActivityWatchSourceStatusView:
        service = await runtime()
        return ActivityWatchSourceStatusView.model_validate(
            _project_source_status(await service.activity.source_status())
        )

    @app.get("/v1/watch/current", response_model=WatchCurrentView)
    async def watch_current() -> WatchCurrentView:
        service = await runtime()
        current = await service.activity.current_state()
        return WatchCurrentView.model_validate(
            await _project_current_activity(service.activity, current)
        )

    @app.get("/v1/watch/oauth-feed", response_model=WatchOAuthFeedView)
    async def watch_oauth_feed(
        workspace_id: str | None = None,
        limit: int = Query(default=30, ge=1, le=30),
    ) -> WatchOAuthFeedView:
        service = await runtime()
        workspace = await selected_workspace(service, workspace_id)
        feed = await service.connector_feed.get(workspace.id, limit=limit)
        return WatchOAuthFeedView.model_validate(feed.model_dump(mode="json"))

    @app.get("/v1/watch/profile", response_model=list[WatchProfileAssertionView])
    async def watch_profile(
        workspace_id: str | None = None,
        limit: int = Query(default=8, ge=1, le=50),
    ) -> list[WatchProfileAssertionView]:
        service = await runtime()
        workspace = await selected_workspace(service, workspace_id)
        assertions = await service.memory.list_active_assertions(workspace.id, limit=limit)
        return [
            WatchProfileAssertionView(
                id=assertion.id,
                claim=assertion.claim,
                confidence=assertion.confidence,
                origin=assertion.origin,
                evidence_count=len(assertion.evidence_event_ids),
                updated_at=assertion.updated_at,
            )
            for assertion in assertions
        ]

    @app.get("/v1/watch/dashboard", response_model=ActivityWatchDashboardView)
    async def watch_dashboard(
        start: datetime,
        end: datetime,
        limit: int = Query(default=500, ge=1, le=500),
    ) -> ActivityWatchDashboardView:
        _require_activity_window(start, end, max_days=31)
        service = await runtime()
        dashboard = await service.activity.dashboard_window(
            start=start,
            end=end,
            limit=limit,
        )
        return ActivityWatchDashboardView.model_validate(
            {
                "statistics": await _project_activity_statistics(
                    service.activity,
                    dashboard.statistics,
                ),
                "timeline": await _project_activity_timeline(
                    service.activity,
                    dashboard.timeline,
                ),
            }
        )

    @app.get("/v1/watch/recent", response_model=list[ActivityTimelineEntryView])
    async def watch_recent(
        minutes: int = Query(default=30, ge=1, le=10_080),
        limit: int = Query(default=100, ge=1, le=200),
    ) -> list[ActivityTimelineEntryView]:
        end = datetime.now(UTC)
        start = end - timedelta(minutes=minutes)
        service = await runtime()
        timeline = await service.activity.timeline(start=start, end=end, limit=limit)
        return [
            ActivityTimelineEntryView.model_validate(item)
            for item in await _project_activity_timeline(service.activity, timeline)
        ]

    @app.get("/v1/watch/statistics", response_model=ActivityStatisticsView)
    async def watch_statistics(start: datetime, end: datetime) -> ActivityStatisticsView:
        _require_activity_window(start, end, max_days=370)
        service = await runtime()
        statistics = await service.activity.statistics(start=start, end=end)
        return ActivityStatisticsView.model_validate(
            await _project_activity_statistics(service.activity, statistics)
        )

    @app.get("/v1/watch/applications", response_model=ActivityStatisticsView)
    async def watch_applications(start: datetime, end: datetime) -> ActivityStatisticsView:
        return await watch_statistics(start=start, end=end)

    @app.get("/v1/watch/categories", response_model=ActivityStatisticsView)
    async def watch_categories(start: datetime, end: datetime) -> ActivityStatisticsView:
        return await watch_statistics(start=start, end=end)

    @app.get("/v1/watch/afk", response_model=ActivityStatisticsView)
    async def watch_afk(start: datetime, end: datetime) -> ActivityStatisticsView:
        return await watch_statistics(start=start, end=end)

    @app.get("/v1/watch/switches", response_model=ActivityStatisticsView)
    async def watch_switches(start: datetime, end: datetime) -> ActivityStatisticsView:
        return await watch_statistics(start=start, end=end)

    @app.get("/v1/watch/timeline", response_model=list[ActivityTimelineEntryView])
    async def watch_timeline(
        start: datetime,
        end: datetime,
        limit: int = Query(default=500, ge=1, le=500),
    ) -> list[ActivityTimelineEntryView]:
        _require_activity_window(start, end, max_days=31)
        service = await runtime()
        timeline = await service.activity.timeline(start=start, end=end, limit=limit)
        return [
            ActivityTimelineEntryView.model_validate(item)
            for item in await _project_activity_timeline(service.activity, timeline)
        ]

    @app.get("/v1/watch/summaries", response_model=list[ActivitySummaryView])
    async def watch_summaries(
        kind: Literal["stage_6h", "daily_24h", "weekly", "biweekly", "monthly"] | None = None,
        limit: int = Query(default=20, ge=1, le=100),
    ) -> list[ActivitySummaryView]:
        service = await runtime()
        summaries = await service.activity.summary_history(
            task_type=SummaryTaskType(kind) if kind is not None else None,
            limit=limit,
        )
        return [
            ActivitySummaryView.model_validate(
                await _project_activity_summary(
                    service.activity,
                    item,
                    evidence_limit=20,
                )
            )
            for item in summaries
        ]

    @app.get("/v1/watch/summaries/{summary_id}", response_model=ActivitySummaryView)
    async def watch_summary(summary_id: str) -> ActivitySummaryView:
        service = await runtime()
        summary = await service.activity.get_summary(summary_id)
        if summary is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "activity_summary_not_found"},
            )
        return ActivitySummaryView.model_validate(
            await _project_activity_summary(
                service.activity,
                summary,
                evidence_limit=120,
            )
        )

    @app.get("/v1/watch/tasks", response_model=list[ActivitySummaryTaskView])
    async def watch_tasks(
        status_filter: Literal["pending", "running", "completed", "failed", "needs_retry"]
        | None = Query(default=None, alias="status"),
        limit: int = Query(default=30, ge=1, le=100),
    ) -> list[ActivitySummaryTaskView]:
        service = await runtime()
        tasks = await service.activity.list_tasks(
            statuses=((SummaryTaskStatus(status_filter),) if status_filter is not None else None),
            limit=limit,
        )
        return [
            ActivitySummaryTaskView.model_validate(_project_activity_task(item)) for item in tasks
        ]

    @app.post(
        "/v1/watch/tasks/{task_id}/regenerate",
        response_model=ActivitySummaryTaskView,
    )
    async def regenerate_watch_task(
        task_id: str,
        request: ActivityRegenerationRequest,
    ) -> ActivitySummaryTaskView:
        service = await runtime()
        try:
            task = await service.activity.request_regeneration(
                task_id,
                reason=request.reason,
            )
        except LookupError as error:
            raise HTTPException(
                status_code=404,
                detail={"code": "activity_summary_task_not_found"},
            ) from error
        except ValueError as error:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "activity_summary_regeneration_conflict",
                    "message": str(error),
                },
            ) from error
        return ActivitySummaryTaskView.model_validate(_project_activity_task(task))

    @app.get("/v1/watch/trends", response_model=list[ActivityTrendPointView])
    async def watch_trends(
        start: datetime,
        end: datetime,
        granularity: Literal["week", "month"],
    ) -> list[ActivityTrendPointView]:
        _require_activity_window(start, end, max_days=370)
        service = await runtime()
        points = await service.activity.trends(
            task_type=(
                SummaryTaskType.WEEKLY if granularity == "week" else SummaryTaskType.MONTHLY
            ),
            limit=100,
        )
        return [
            ActivityTrendPointView.model_validate(_project_activity_trend(item))
            for item in points
            if _activity_trend_overlaps(item, start=start, end=end)
        ]

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
                tool_mode=request.tool_mode,
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

    @app.post(
        "/v1/runs/{run_id}/controls",
        response_model=RunControl,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def enqueue_run_control(
        run_id: str,
        request: RunControlCreateRequest,
    ) -> RunControl:
        service = await runtime()
        try:
            return await service.enqueue_run_control(
                run_id=run_id,
                kind=request.kind,
                content=request.content,
            )
        except RunControlNotFoundError as error:
            raise HTTPException(
                status_code=404,
                detail={"code": "run_not_found", "run_id": run_id},
            ) from error
        except RunControlRejectedError as error:
            run = await service.runs.get(run_id)
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "run_control_rejected",
                    "status": run.status.value if run is not None else "unknown",
                },
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
        signal: RhythmSignalRequest, workspace_id: str | None = None
    ) -> CurrentRhythm:
        service = await runtime()
        workspace = await selected_workspace(service, workspace_id)
        return await service.rhythm.ingest(workspace.id, signal)

    @app.get("/v1/rhythm/current", response_model=CurrentRhythm)
    async def current_rhythm(workspace_id: str | None = None) -> CurrentRhythm:
        service = await runtime()
        workspace = await selected_workspace(service, workspace_id)
        return await service.rhythm.current(workspace.id)

    @app.get("/v1/desktop/snapshot", response_model=DesktopSnapshot)
    async def desktop_snapshot(workspace_id: str | None = None) -> DesktopSnapshot:
        service = await runtime()
        workspace = await selected_workspace(service, workspace_id)
        rhythm = await service.rhythm.current(workspace.id)
        recent = await service.runs.list_recent(limit=1, workspace_id=workspace.id)
        return DesktopSnapshot(
            rhythm=rhythm,
            latest_run=recent[0] if recent else None,
            workspace=workspace,
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
                "mode": "activitywatch_read_only",
                "enabled": True,
                "raw_content_captured": False,
                "fallback_to_deliberate_signals": True,
            },
            retention={
                "raw_behavior": "owned_by_activitywatch",
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

    @app.get("/v1/onboarding", response_model=OnboardingView)
    async def onboarding_state(workspace_id: str | None = None) -> OnboardingView:
        service = await runtime()
        workspace = await selected_workspace(service, workspace_id)
        return OnboardingView.model_validate(
            _as_mapping(await service.onboarding.get(workspace.id))
        )

    @app.post("/v1/onboarding/complete", response_model=OnboardingView)
    async def complete_onboarding(
        request: OnboardingCompleteRequest,
        workspace_id: str | None = None,
    ) -> OnboardingView:
        if not request.confirm_local_ownership:
            raise HTTPException(
                status_code=409,
                detail={"code": "local_ownership_confirmation_required"},
            )
        service = await runtime()
        workspace = await selected_workspace(service, workspace_id)
        return OnboardingView.model_validate(
            _as_mapping(
                await service.onboarding.complete(
                    workspace.id,
                    metadata_sensor_enabled=False,
                )
            )
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


def _require_activity_window(
    start: datetime,
    end: datetime,
    *,
    max_days: int,
) -> None:
    if (
        start.tzinfo is None
        or start.utcoffset() is None
        or end.tzinfo is None
        or end.utcoffset() is None
        or end <= start
        or end - start > timedelta(days=max_days)
    ):
        raise HTTPException(
            status_code=422,
            detail={"code": "activity_window_invalid"},
        )


def _as_mapping(value) -> dict:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="python")
    raise TypeError(f"unsupported activity response type: {type(value).__name__}")


def _enum_value(value):
    return getattr(value, "value", value)


def _project_evidence_ref(value) -> dict:
    raw = _as_mapping(value)
    return {
        "activitywatch_server_id": raw.get("activitywatch_server_id"),
        "bucket_id": raw["bucket_id"],
        "event_id": str(raw["event_id"]),
        "event_timestamp": raw.get("event_timestamp"),
        "event_duration": raw.get("event_duration"),
        "event_digest": raw.get("event_digest"),
        "fields_used": tuple(raw.get("fields_used", ())),
    }


def _project_source_status(value) -> dict:
    raw = _as_mapping(value)
    if "reachable" in raw:
        return raw
    return {
        "reachable": _enum_value(raw.get("health")) == "available",
        "server_version": raw.get("server_version"),
        "data_start": raw.get("data_start"),
        "data_end": raw.get("data_end"),
        "checked_at": raw["checked_at"],
        "last_reconciled_at": raw.get("last_reconciled_at"),
        "error_code": raw.get("error_code"),
    }


async def _activity_source_mapping(activity) -> dict:
    return _as_mapping(await activity.source_status())


async def _project_current_activity(activity, value) -> dict:
    raw = _as_mapping(value)
    source: dict | None = None

    async def source_mapping() -> dict:
        nonlocal source
        if source is None:
            source = await _activity_source_mapping(activity)
        return source

    observed = raw.get("observed")
    if observed is None:
        observed_view = None
    else:
        fact = _as_mapping(observed)
        if "started_at" in fact:
            observed_view = fact
        else:
            evidence_refs: tuple[dict, ...] = ()
            fact_object = getattr(value, "observed", None)
            if fact_object is not None and hasattr(fact_object, "evidence_ref"):
                current_source = await source_mapping()
                server_id = current_source.get("server_id") or "activitywatch-local"
                fields_used = tuple(
                    field
                    for field in ("application", "title", "url", "domain", "afk_state")
                    if fact.get(field) is not None
                )
                evidence_refs = (
                    _project_evidence_ref(
                        fact_object.evidence_ref(
                            server_id=server_id,
                            fields_used=fields_used,
                        )
                    ),
                )
            observed_view = {
                "observed_at": raw.get("observed_at", fact["timestamp"]),
                "started_at": fact["timestamp"],
                "duration_seconds": fact.get("duration", 0),
                "app_name": fact.get("application"),
                "window_title": fact.get("title"),
                "url": fact.get("url"),
                "afk_state": _enum_value(raw.get("afk_state", fact.get("afk_state", "unknown"))),
                "evidence_refs": evidence_refs,
            }

    current_source = await source_mapping()
    observed_at = raw.get("observed_at")
    if observed_at is None and observed_view is not None:
        observed_at = observed_view["observed_at"]
    if observed_at is None:
        observed_at = current_source.get("checked_at")
    source_health = raw.get("source_health", current_source.get("health"))
    if source_health is None:
        source_health = "available" if current_source.get("reachable") else "degraded"
    afk_state = raw.get("afk_state")
    if afk_state is None and observed_view is not None:
        afk_state = observed_view["afk_state"]
    return {
        "observed": observed_view,
        "afk_state": _enum_value(afk_state or "unknown"),
        "observed_at": observed_at,
        "source_health": _enum_value(source_health),
    }


async def _project_activity_statistics(activity, value) -> dict:
    raw = _as_mapping(value)
    if "app_seconds" in raw and "category_rule_version" in raw:
        return raw
    source = await _activity_source_mapping(activity)
    return {
        "window_start": raw["window_start"],
        "window_end": raw["window_end"],
        "active_seconds": raw.get("active_seconds", 0),
        "afk_seconds": raw.get("afk_seconds", 0),
        "browser_seconds": raw.get("browser_seconds", 0),
        "app_switch_count": raw.get("app_switch_count", 0),
        "category_switch_count": raw.get("category_switch_count", 0),
        "app_seconds": raw.get("app_seconds", raw.get("application_seconds", {})),
        "category_seconds": raw.get("category_seconds", {}),
        "category_rule_version": (
            raw.get("category_rule_version") or source.get("category_rule_version") or "unavailable"
        ),
        "observed_seconds": raw.get("observed_seconds", 0),
        "unobserved_seconds": raw.get("unobserved_seconds", 0),
        "window_observed_seconds": raw.get("window_observed_seconds", 0),
        "afk_observed_seconds": raw.get("afk_observed_seconds", 0),
        "web_observed_seconds": raw.get("web_observed_seconds", 0),
        "coverage_ratio": raw.get("coverage_ratio", 0),
        "coverage_status": _enum_value(raw.get("coverage_status", "none")),
        "source_bucket_ids": tuple(raw.get("source_bucket_ids", ())),
    }


async def _project_activity_timeline(activity, value) -> list[dict]:
    if isinstance(value, list):
        return [_as_mapping(item) for item in value]
    raw = _as_mapping(value)
    facts = tuple(getattr(value, "facts", raw.get("facts", ())))
    source: dict | None = None
    category_matcher = None
    client = getattr(activity, "client", None)
    if facts and client is not None and hasattr(client, "classes"):
        try:
            category_matcher = CategoryMatcher(await client.classes())
        except (ActivityWatchProtocolError, ActivityWatchUnavailable):
            category_matcher = None
    result: list[dict] = []
    for item in facts:
        fact = _as_mapping(item)
        evidence_refs: tuple[dict, ...] = ()
        if hasattr(item, "evidence_ref"):
            if source is None:
                source = await _activity_source_mapping(activity)
            evidence_refs = (
                _project_evidence_ref(
                    item.evidence_ref(
                        server_id=source.get("server_id") or "activitywatch-local",
                        fields_used=tuple(
                            field
                            for field in (
                                "application",
                                "title",
                                "url",
                                "domain",
                                "afk_state",
                            )
                            if fact.get(field) is not None
                        ),
                    )
                ),
            )
        started_at = fact["timestamp"]
        ended_at = getattr(item, "ended_at", started_at)
        result.append(
            {
                "id": f"{fact['bucket_id']}:{fact['event_id']}",
                "started_at": started_at,
                "ended_at": ended_at,
                "duration_seconds": fact.get("duration", 0),
                "app_name": fact.get("application"),
                "category": (
                    category_matcher.match(item)
                    if category_matcher is not None and hasattr(item, "kind")
                    else fact.get("category")
                ),
                "afk_state": _enum_value(fact.get("afk_state", "unknown")),
                "window_title": fact.get("title"),
                "url": fact.get("url"),
                "evidence_refs": evidence_refs,
            }
        )
    return result


async def _activity_task(activity, task_id: str):
    getter = getattr(activity, "get_task", None)
    if getter is not None:
        return await getter(task_id)
    repository = getattr(activity, "repository", None)
    if repository is not None and hasattr(repository, "get_task"):
        return await repository.get_task(task_id)
    return None


async def _project_activity_summary(
    activity,
    value,
    *,
    evidence_limit: int,
) -> dict:
    raw = _as_mapping(value)
    if "kind" in raw and "narrative" in raw:
        evidence = tuple(raw.get("evidence_refs", ()))
        return {
            **raw,
            "evidence_refs": evidence[:evidence_limit],
            "evidence_count": raw.get("evidence_count", len(evidence)),
        }
    task = await _activity_task(activity, raw["task_id"])
    task_raw = _as_mapping(task) if task is not None else {}
    statistics = await _project_activity_statistics(activity, raw["statistics"])
    return {
        "id": raw["id"],
        "task_id": raw["task_id"],
        "kind": _enum_value(task_raw.get("task_type", "stage_6h")),
        "finality": _enum_value(raw["finality"]),
        "timezone": task_raw.get("timezone", "Asia/Shanghai"),
        "window_start": task_raw.get("window_start", statistics["window_start"]),
        "window_end": task_raw.get("window_end", statistics["window_end"]),
        "statistics": statistics,
        "narrative": raw.get("narrative", raw.get("summary_text", "")),
        "evidence_refs": tuple(
            _project_evidence_ref(item) for item in raw.get("evidence_refs", ())[:evidence_limit]
        ),
        "connector_evidence_refs": tuple(
            _as_mapping(item) for item in raw.get("connector_evidence_refs", ())[:evidence_limit]
        ),
        "connector_coverage": tuple(
            _as_mapping(item) for item in raw.get("connector_coverage", ())
        ),
        "category_rule_version": raw["category_rule_version"],
        "rules_stale": raw.get("rules_stale", raw.get("legacy_rules", False)),
        "provider": raw.get("provider"),
        "model_version": raw.get("model_version", raw.get("model")),
        "requested_provider": raw.get("requested_provider"),
        "requested_model": raw.get("requested_model"),
        "fallback_reason": raw.get("fallback_reason"),
        "summary_settings_version": raw.get("summary_settings_version", 0),
        "prompt_version": raw["prompt_version"],
        "completed_at": raw["completed_at"],
        "attempt_count": task_raw.get("attempt_count"),
        "source_watermark": raw.get("source_watermark"),
        "evidence_count": len(raw.get("evidence_refs", ())),
    }


def _project_activity_task(value) -> dict:
    raw = _as_mapping(value)
    if "kind" in raw and "next_attempt_at" in raw:
        return raw
    return {
        "id": raw["id"],
        "kind": _enum_value(raw.get("kind", raw.get("task_type"))),
        "window_start": raw["window_start"],
        "window_end": raw["window_end"],
        "status": _enum_value(raw["status"]),
        "attempt_count": raw.get("attempt_count", 0),
        "completed_at": raw.get("completed_at"),
        "next_attempt_at": raw.get("next_attempt_at", raw.get("next_retry_at")),
        "error_code": raw.get("error_code"),
        "finality": _enum_value(raw.get("finality")),
        "regeneration_reason": raw.get("regeneration_reason"),
    }


def _project_activity_trend(value) -> dict:
    raw = _as_mapping(value)
    if "app_switch_count" in raw and "dominant_category" in raw:
        return raw
    return {
        "window_start": raw["window_start"],
        "window_end": raw["window_end"],
        "active_seconds": raw.get("active_seconds", 0),
        "afk_seconds": raw.get("afk_seconds", 0),
        "app_switch_count": raw.get(
            "app_switch_count",
            raw.get("context_switch_count", 0),
        ),
        "dominant_category": raw.get("dominant_category"),
    }


def _activity_trend_overlaps(value, *, start: datetime, end: datetime) -> bool:
    raw = _as_mapping(value)
    window_start = _activity_datetime(raw["window_start"])
    window_end = _activity_datetime(raw["window_end"])
    return window_start < end and window_end > start


def _activity_datetime(value) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


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
