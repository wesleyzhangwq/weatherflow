import { act, renderHook } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { WeatherFlowClient } from "./bridge";
import { useDesktopSnapshot } from "./useDesktopSnapshot";


it("reconnects the event ledger stream after a daemon hot reload", async () => {
  vi.useFakeTimers();
  let disconnected: (() => void) | undefined;
  const client = {
    snapshot: vi.fn().mockResolvedValue({}),
    events: vi.fn((_cursor, _onEvent, _onRefresh, onDisconnect) => {
      disconnected = onDisconnect;
      return { close: vi.fn() };
    }),
  } as unknown as WeatherFlowClient;

  renderHook(() => useDesktopSnapshot(client, "workspace-1"));
  await act(async () => { await Promise.resolve(); });
  expect(disconnected).toBeTypeOf("function");

  await act(async () => {
    disconnected?.();
    await vi.advanceTimersByTimeAsync(500);
  });
  expect(client.events).toHaveBeenCalledTimes(2);
  vi.useRealTimers();
});
