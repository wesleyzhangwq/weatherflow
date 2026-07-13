import asyncio
import secrets
from pathlib import Path

from fastapi import (
    FastAPI,
    HTTPException,
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
    ConnectorConfigureResponse,
    ConnectorDisconnectRequest,
    ConnectorSettingsRequest,
    DesktopSnapshot,
    HealthResponse,
    ModelConfigurationResponse,
    ModelConfigureRequest,
    ModelProviderList,
    OnboardingCompleteRequest,
    ResetConfirmRequest,
    RunCreateRequest,
    SystemStatus,
    WorkspaceCreateRequest,
)
from weatherflow.artifacts import ArtifactManifest
from weatherflow.bootstrap import RuntimeContainer
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
from weatherflow.models import (
    ModelProvider,
    ProviderModelCatalog,
    provider_presets,
)
from weatherflow.operations import (
    DiagnosticExport,
    LocalMetrics,
    OnboardingState,
    ResetCategory,
    ResetPreview,
    ResetResult,
    SecurityScan,
    SecurityScanner,
)
from weatherflow.rhythm import CurrentRhythm, RhythmSignal
from weatherflow.runs import InvalidTransitionError, Run, RunStatus
from weatherflow.trust import (
    ApprovalAlreadyDecided,
    ApprovalBundle,
    ApprovalStatus,
)
from weatherflow.workspaces import Workspace


def create_app(
    settings: Settings | None = None,
    *,
    container: RuntimeContainer | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings()
    app = FastAPI(title="WeatherFlow Core", version=__version__)
    app.state.settings = resolved_settings
    app.state.container = container
    app.state.container_lock = asyncio.Lock()

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
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    async def runtime() -> RuntimeContainer:
        if app.state.container is None:
            async with app.state.container_lock:
                if app.state.container is None:
                    app.state.container = await RuntimeContainer.create(resolved_settings)
        service = app.state.container
        await service.start_background()
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
                context_run_id=request.context_run_id,
                execute=False,
            )
        except LookupError as error:
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
    async def list_runs(workspace_id: str | None = None, limit: int = 50) -> list[Run]:
        service = await runtime()
        return await service.runs.list_recent(limit=limit, workspace_id=workspace_id)

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
        except ApprovalAlreadyDecided as error:
            raise HTTPException(
                status_code=409,
                detail={"code": "approval_already_decided", "approval_id": approval_id},
            ) from error
        if request.resume:
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
        if not model_status.configured and workspace.id != service.default_workspace.id:
            model_status = await service.model_configurations.status(service.default_workspace.id)
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
        configuration = await service.configure_model(
            workspace_id=workspace.id,
            provider=request.provider,
            model=request.model,
            base_url=request.base_url,
        )
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
        connector: ConnectorKind, request: ConnectorDisconnectRequest
    ) -> Response:
        if not request.confirm:
            raise HTTPException(status_code=409, detail={"code": "explicit_confirmation_required"})
        service = await runtime()
        await service.connector_service.disconnect(connector)
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
