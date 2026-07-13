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
    expect(body).toEqual({ user_intent: "Ship release", client_request_id: "request-1", workspace_id: "workspace-1" });
  });

  it("keeps the browser fallback explicit for non-Tauri development", () => {
    expect(bridgeConfig()).toEqual({ baseUrl: "http://127.0.0.1:8765" });
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
});
