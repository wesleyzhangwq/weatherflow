import { beforeEach, describe, expect, it, vi } from "vitest";
import { invoke } from "@tauri-apps/api/core";
import {
  bridgeConfig,
  resolveBridgeConfig,
  WeatherFlowBridgeError,
  WeatherFlowClient,
} from "./bridge";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn() }));

describe("WeatherFlowClient", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.mocked(invoke).mockReset();
    delete (window as Window & { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__;
    delete window.__WEATHERFLOW_BRIDGE__;
  });

  it("authenticates command submission and keeps execute in the daemon", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ id: "run-1", status: "queued" }), { status: 201 }),
    );
    const client = new WeatherFlowClient({ baseUrl: "http://127.0.0.1:9000", token: "secret" });

    await client.createRun("Ship release", "request-1", "workspace-1");

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:9000/v1/runs",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ Authorization: "Bearer secret" }),
      }),
    );
    const body = JSON.parse((fetchMock.mock.calls[0][1]?.body as string));
    expect(body).toEqual({ user_intent: "Ship release", client_request_id: "request-1", workspace_id: "workspace-1", tool_mode: "ask" });
  });

  it("reads the stable per-Run usage projection without a write request", async () => {
    const payload = {
      schema_version: "run_usage_v1",
      run_id: "run / 1",
      provider: "minimax",
      model: "MiniMax-M2.7",
      input_tokens: 1200,
      cache_read_input_tokens: 0,
      output_tokens: 300,
      total_tokens: 1500,
      cost_amount: 0.00072,
      cost_usd: 0.00072,
      currency: "USD",
      cost_scope: "model_usage_only",
      billing_origin: "minimax_global_paygo",
      cost_status: "known",
      pricing_catalog_version: "minimax-global-paygo-usd-2026-07-21",
      step_count: 1,
      elapsed_seconds: 2,
      timeout_seconds: 1800,
      max_cost_usd: null,
      cost_budget_usage_percent: null,
      cost_budget_status: "unlimited",
      cost_failure_reason: null,
    };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(payload), { status: 200 }),
    );
    const client = new WeatherFlowClient({ baseUrl: "http://127.0.0.1:9000", token: "secret" });

    await expect(client.runUsage("run / 1")).resolves.toEqual(payload);

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:9000/v1/runs/run%20%2F%201/usage",
      expect.objectContaining({ headers: expect.objectContaining({ Authorization: "Bearer secret" }) }),
    );
    expect(fetchMock.mock.calls[0][1]?.method).toBeUndefined();
  });

  it("retains only the typed bridge status and code for broker permission failures", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({
      detail: {
        code: "connector_broker_permission",
        retryable: false,
        message: "upstream response that must not survive in the renderer error",
      },
    }), { status: 403 }));
    const client = new WeatherFlowClient({ baseUrl: "http://127.0.0.1:9000", token: "secret" });

    const error = await client.configureConnectors().then(
      () => null,
      (caught: unknown) => caught,
    );

    expect(error).toBeInstanceOf(WeatherFlowBridgeError);
    expect(error).toMatchObject({ status: 403, code: "connector_broker_permission" });
    expect((error as { detail?: unknown }).detail).toBeUndefined();
    expect((error as Error).message).not.toContain("upstream response");
    expect(JSON.stringify(error)).not.toContain("upstream response");
  });

  it("keeps the browser fallback explicit for non-Tauri development", () => {
    expect(bridgeConfig()).toEqual({ baseUrl: "http://127.0.0.1:8765" });
  });

  it("uses the explicit browser fallback outside the Tauri shell", async () => {
    await expect(resolveBridgeConfig()).resolves.toEqual({ baseUrl: "http://127.0.0.1:8765" });
  });

  it("does not treat the Tauri development shell as an unauthenticated browser fallback", async () => {
    vi.useFakeTimers();
    Object.defineProperty(window, "__TAURI_INTERNALS__", { configurable: true, value: {} });
    vi.mocked(invoke).mockRejectedValue(new Error("daemon unavailable"));
    const configPromise = import("./bridge").then(({ resolveBridgeConfig }) => resolveBridgeConfig());
    const rejection = configPromise.then(() => null, (error: unknown) => error);

    await vi.runAllTimersAsync();
    await expect(rejection).resolves.toBeInstanceOf(Error);
    delete (window as Window & { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__;
    vi.useRealTimers();
  });

  it("refreshes stale injected Tauri bridge config and retries one read-only GET", async () => {
    Object.defineProperty(window, "__TAURI_INTERNALS__", { configurable: true, value: {} });
    window.__WEATHERFLOW_BRIDGE__ = {
      baseUrl: "http://127.0.0.1:41001",
      token: "stale-token",
    };
    vi.mocked(invoke).mockResolvedValue({
      baseUrl: "http://127.0.0.1:41002",
      token: "fresh-token",
    });
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }));
    const client = new WeatherFlowClient(window.__WEATHERFLOW_BRIDGE__);

    await expect(client.workspaces()).resolves.toEqual([]);

    expect(invoke).toHaveBeenCalledTimes(1);
    expect(invoke).toHaveBeenCalledWith("daemon_bridge");
    expect(fetchMock.mock.calls.map(([url, init]) => [
      url,
      (init?.headers as Record<string, string>).Authorization,
    ])).toEqual([
      ["http://127.0.0.1:41001/v1/workspaces", "Bearer stale-token"],
      ["http://127.0.0.1:41002/v1/workspaces", "Bearer fresh-token"],
    ]);
    expect(window.__WEATHERFLOW_BRIDGE__).toEqual({
      baseUrl: "http://127.0.0.1:41001",
      token: "stale-token",
    });
  });

  it("refreshes a stale Tauri token only for bridge_unauthorized GET responses", async () => {
    Object.defineProperty(window, "__TAURI_INTERNALS__", { configurable: true, value: {} });
    window.__WEATHERFLOW_BRIDGE__ = {
      baseUrl: "http://127.0.0.1:41001",
      token: "stale-token",
    };
    vi.mocked(invoke).mockResolvedValue({
      baseUrl: "http://127.0.0.1:41002",
      token: "fresh-token",
    });
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(JSON.stringify({
        detail: { code: "bridge_unauthorized" },
      }), { status: 401 }))
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }));
    const client = new WeatherFlowClient(window.__WEATHERFLOW_BRIDGE__);

    await expect(client.workspaces()).resolves.toEqual([]);

    expect(invoke).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("does not refresh a GET for an application-level unauthorized response", async () => {
    Object.defineProperty(window, "__TAURI_INTERNALS__", { configurable: true, value: {} });
    vi.mocked(invoke).mockResolvedValue({
      baseUrl: "http://127.0.0.1:41002",
      token: "fresh-token",
    });
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({
        detail: { code: "connector_broker_auth" },
      }), { status: 401 }),
    );
    const client = new WeatherFlowClient({
      baseUrl: "http://127.0.0.1:41001",
      token: "current-token",
    });

    await expect(client.providerModels("github")).rejects.toMatchObject({
      status: 401,
      code: "connector_broker_auth",
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(invoke).not.toHaveBeenCalled();
  });

  it("does not refresh or retry a write request after a bridge failure", async () => {
    Object.defineProperty(window, "__TAURI_INTERNALS__", { configurable: true, value: {} });
    vi.mocked(invoke).mockResolvedValue({
      baseUrl: "http://127.0.0.1:41002",
      token: "fresh-token",
    });
    const failure = new TypeError("Failed to fetch");
    const fetchMock = vi.spyOn(globalThis, "fetch").mockRejectedValue(failure);
    const client = new WeatherFlowClient({
      baseUrl: "http://127.0.0.1:41001",
      token: "stale-token",
    });

    await expect(client.createRun("Do not replay", "request-1")).rejects.toBe(failure);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(invoke).not.toHaveBeenCalled();
  });

  it("retries a failed GET at most once after refreshing the Tauri bridge", async () => {
    Object.defineProperty(window, "__TAURI_INTERNALS__", { configurable: true, value: {} });
    vi.mocked(invoke).mockResolvedValue({
      baseUrl: "http://127.0.0.1:41002",
      token: "fresh-token",
    });
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockRejectedValueOnce(new TypeError("stale bridge"))
      .mockRejectedValueOnce(new TypeError("fresh bridge unavailable"));
    const client = new WeatherFlowClient({
      baseUrl: "http://127.0.0.1:41001",
      token: "stale-token",
    });

    await expect(client.workspaces()).rejects.toThrow("fresh bridge unavailable");

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(invoke).toHaveBeenCalledTimes(1);
  });

  it("authenticates event sockets without putting the token in the logged URL", () => {
    const opened: { url?: string; protocols?: string[] } = {};
    class Socket {
      onmessage = null;
      onclose = null;

      constructor(url: URL, protocols?: string[]) {
        opened.url = url.toString();
        opened.protocols = protocols;
      }
    }
    vi.stubGlobal("WebSocket", Socket);
    const client = new WeatherFlowClient({ baseUrl: "http://127.0.0.1:9000", token: "secret" });

    client.events(null, vi.fn(), vi.fn());

    expect(opened.url).toBe("ws://127.0.0.1:9000/v1/events");
    expect(opened.url).not.toContain("secret");
    expect(opened.protocols).toEqual(["weatherflow-v1", "weatherflow-auth.secret"]);
    vi.unstubAllGlobals();
  });

  it("manages durable conversation sessions and binds a new run to one", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        id: "session-1", workspace_id: "workspace-1", title: "新对话", pinned: false,
        latest_run_id: null, created_at: "2026-07-14T01:00:00Z", updated_at: "2026-07-14T01:00:00Z",
      }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        id: "session-1", workspace_id: "workspace-1", title: "发布计划", pinned: true,
        latest_run_id: null, created_at: "2026-07-14T01:00:00Z", updated_at: "2026-07-14T01:01:00Z",
      }), { status: 200 }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        id: "run-1", workspace_id: "workspace-1", user_intent: "检查发布计划", status: "queued",
        result_summary: null, updated_at: "2026-07-14T01:02:00Z",
      }), { status: 200 }));
    const client = new WeatherFlowClient({ baseUrl: "http://127.0.0.1:9000", token: "secret" });

    await client.sessions("workspace-1");
    await client.createSession("workspace-1");
    await client.updateSession("session-1", "workspace-1", { title: "发布计划", pinned: true });
    await client.deleteSession("session-1", "workspace-1");
    await client.createRun("检查发布计划", "request-1", "workspace-1", null, "session-1");

    expect(fetchMock.mock.calls.map(([url, init]) => [url, init?.method, init?.body])).toEqual([
      ["http://127.0.0.1:9000/v1/sessions?workspace_id=workspace-1", undefined, undefined],
      ["http://127.0.0.1:9000/v1/sessions", "POST", JSON.stringify({ workspace_id: "workspace-1" })],
      ["http://127.0.0.1:9000/v1/sessions/session-1?workspace_id=workspace-1", "PATCH", JSON.stringify({ title: "发布计划", pinned: true })],
      ["http://127.0.0.1:9000/v1/sessions/session-1?workspace_id=workspace-1", "DELETE", undefined],
      ["http://127.0.0.1:9000/v1/runs", "POST", JSON.stringify({ user_intent: "检查发布计划", client_request_id: "request-1", workspace_id: "workspace-1", context_run_id: null, session_id: "session-1", tool_mode: "ask" })],
    ]);
  });

  it("requests durable install approvals without renderer confirmation authority", async () => {
    const response = {
      status: "needs_approval", action_id: "action-1", approval_id: "approval-1",
      approval_version: 0, run_id: "run-1", preview: {},
    };
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockImplementation(async () => new Response(JSON.stringify(response), { status: 202 }));
    const client = new WeatherFlowClient({ baseUrl: "http://127.0.0.1:9000", token: "secret" });

    await client.installSkill("focus-coach", "workspace-1", 3, "skill-request-1");
    await client.installMCP("filesystem", "workspace-1", "mcp-request-1");
    await client.decide("approval-1", "approve", 0, "workspace-1");

    const bodies = fetchMock.mock.calls.map(([, init]) => JSON.parse(init?.body as string));
    expect(bodies).toEqual([
      { workspace_id: "workspace-1", expected_workspace_version: 3, client_request_id: "skill-request-1" },
      { workspace_id: "workspace-1", client_request_id: "mcp-request-1" },
      { decision: "approve", expected_version: 0, resume: true, workspace_id: "workspace-1" },
    ]);
    expect(JSON.stringify(bodies)).not.toContain("confirm");
    expect(JSON.stringify(bodies)).not.toContain("approved_action_id");
  });

  it("queries the read-only Watch API with bounded explicit windows", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(
      async () => new Response(JSON.stringify([]), { status: 200 }),
    );
    const client = new WeatherFlowClient({
      baseUrl: "http://127.0.0.1:9000",
      token: "secret",
    });
    const start = new Date("2026-07-15T16:00:00.000Z");
    const end = new Date("2026-07-16T02:00:00.000Z");

    await client.watchSourceStatus();
    await client.watchCurrent();
    await client.watchOAuthFeed("workspace/1", 18);
    await client.watchDashboard(start, end);
    await client.watchSummaries(20);
    await client.watchTasks(30, "failed");
    await client.watchRegenerateTask("task/with spaces");
    await client.watchTrends(start, end, "week");
    await client.watchSummarySettings();
    await client.updateWatchSummarySettings({
      model_workspace_id: "workspace-1",
      model: "MiniMax-M3-fast",
      expected_version: 2,
    });

    expect(fetchMock.mock.calls.map(([url, init]) => [url, init?.method])).toEqual([
      ["http://127.0.0.1:9000/v1/watch/source-status", undefined],
      ["http://127.0.0.1:9000/v1/watch/current", undefined],
      ["http://127.0.0.1:9000/v1/watch/oauth-feed?workspace_id=workspace%2F1&limit=18", undefined],
      ["http://127.0.0.1:9000/v1/watch/dashboard?start=2026-07-15T16%3A00%3A00.000Z&end=2026-07-16T02%3A00%3A00.000Z&limit=500", undefined],
      ["http://127.0.0.1:9000/v1/watch/summaries?limit=20", undefined],
      ["http://127.0.0.1:9000/v1/watch/tasks?limit=30&status=failed", undefined],
      ["http://127.0.0.1:9000/v1/watch/tasks/task%2Fwith%20spaces/regenerate", "POST"],
      ["http://127.0.0.1:9000/v1/watch/trends?start=2026-07-15T16%3A00%3A00.000Z&end=2026-07-16T02%3A00%3A00.000Z&granularity=week", undefined],
      ["http://127.0.0.1:9000/v1/watch/settings/summary", undefined],
      ["http://127.0.0.1:9000/v1/watch/settings/summary", "PATCH"],
    ]);
    expect(JSON.parse(fetchMock.mock.calls[6]?.[1]?.body as string)).toEqual({
      reason: "user_requested",
    });
    expect(JSON.parse(fetchMock.mock.calls[9]?.[1]?.body as string)).toEqual({
      model_workspace_id: "workspace-1",
      model: "MiniMax-M3-fast",
      expected_version: 2,
    });
    expect(JSON.stringify(fetchMock.mock.calls)).not.toContain("/v1/activity/heartbeats");
  });

  it("does not expose state-inference bridge methods", () => {
    expect(WeatherFlowClient.prototype).not.toHaveProperty("watchStateAssessment");
    expect(WeatherFlowClient.prototype).not.toHaveProperty("watchInferenceEvidence");
  });
});
