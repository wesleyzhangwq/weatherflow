import { beforeEach, describe, expect, it, vi } from "vitest";
import { bridgeConfig, WeatherFlowClient } from "./bridge";

describe("WeatherFlowClient", () => {
  beforeEach(() => vi.restoreAllMocks());

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

  it("keeps the browser fallback explicit for non-Tauri development", () => {
    expect(bridgeConfig()).toEqual({ baseUrl: "http://127.0.0.1:8765" });
  });

  it("does not treat the Tauri development shell as an unauthenticated browser fallback", async () => {
    vi.useFakeTimers();
    Object.defineProperty(window, "__TAURI_INTERNALS__", { configurable: true, value: {} });
    const configPromise = import("./bridge").then(({ resolveBridgeConfig }) => resolveBridgeConfig());
    const rejection = configPromise.then(() => null, (error: unknown) => error);

    await vi.runAllTimersAsync();
    await expect(rejection).resolves.toBeInstanceOf(Error);
    delete (window as Window & { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__;
    vi.useRealTimers();
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
});
