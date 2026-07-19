import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { WeatherFlowClient } from "./bridge";
import { useWorkspaces } from "./useWorkspaces";

const SELECTED_WORKSPACE_KEY = "weatherflow.selectedWorkspaceId";

beforeEach(() => {
  const values = new Map<string, string>();
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value),
    removeItem: (key: string) => values.delete(key),
    clear: () => values.clear(),
    key: (index: number) => [...values.keys()][index] ?? null,
    get length() { return values.size; },
  } satisfies Storage);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

it("retries the workspace list when the bundled Core is still starting", async () => {
  vi.useFakeTimers();
  localStorage.setItem(SELECTED_WORKSPACE_KEY, "workspace-current");
  const current = {
    id: "workspace-current",
    name: "WeatherFlow",
    action_roots: ["/Users/tester/Projects/WeatherFlow"],
    installed_packs: [],
  };
  const workspaces = vi.fn()
    .mockRejectedValueOnce(new Error("Core is still starting"))
    .mockResolvedValueOnce([current]);
  const client = { workspaces } as unknown as WeatherFlowClient;

  const { result } = renderHook(() => useWorkspaces(client));
  await act(async () => { await Promise.resolve(); });
  expect(workspaces).toHaveBeenCalledTimes(1);

  await act(async () => { await vi.advanceTimersByTimeAsync(500); });

  expect(result.current.workspaces).toEqual([current]);
  expect(result.current.selectedId).toBe("workspace-current");
  expect(workspaces).toHaveBeenCalledTimes(2);
});
