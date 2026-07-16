import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { ScreenTimePanel } from "./ScreenTimePanel";
import type { WeatherFlowClient } from "../bridge";

const preferences = {
  collection_enabled: true,
  macos_enabled: true,
  browser_enabled: true,
  incognito_enabled: false,
  remote_inference_enabled: true,
  model_workspace_id: "w1",
  retention_days: 90 as const,
  version: 3,
};

function client() {
  return {
    activityPreferences: vi.fn().mockResolvedValue(preferences),
    activitySummary: vi.fn().mockResolvedValue({
      window_start: "2026-07-16T00:00:00Z",
      window_end: "2026-07-16T10:00:00Z",
      screen_seconds: 18_300,
      browser_seconds: 7_200,
      idle_seconds: 1_200,
      current_streak_seconds: 3_600,
      app_switch_count: 14,
      tab_switch_count: 27,
      category_seconds: { development: 12_000, research: 4_500, communication: 1_800 },
      top_apps: [{ name: "Visual Studio Code", seconds: 12_000 }, { name: "Terminal", seconds: 3_600 }],
      top_domains: [{ name: "github.com", seconds: 4_800 }],
    }),
    activityEvents: vi.fn().mockResolvedValue([
      {
        id: "event-1", source: "macos_window", device_id: "mac", source_instance: "native", source_event_id: "native-1",
        started_at: "2026-07-16T08:00:00Z", ended_at: "2026-07-16T09:00:00Z", observed_at: "2026-07-16T09:00:00Z", duration_seconds: 3600,
        app_name: "Visual Studio Code", bundle_id: "com.microsoft.VSCode", window_title: "ScreenTimePanel.tsx — WeatherFlow",
        browser_name: null, browser_window_id: null, browser_tab_id: null, url: null, domain: null, tab_title: null,
        audible: null, incognito: null, focused: true, idle_state: "active", category: "development",
      },
      {
        id: "event-2", source: "browser_tab", device_id: "mac", source_instance: "chrome", source_event_id: "tab-1",
        started_at: "2026-07-16T08:15:00Z", ended_at: "2026-07-16T08:45:00Z", observed_at: "2026-07-16T08:45:00Z", duration_seconds: 1800,
        app_name: null, bundle_id: null, window_title: null, browser_name: "Chrome", browser_window_id: "1", browser_tab_id: "2",
        url: "https://github.com/ActivityWatch/activitywatch", domain: "github.com", tab_title: "ActivityWatch/activitywatch",
        audible: false, incognito: false, focused: true, idle_state: "active", category: "development",
      },
    ]),
    activityInferenceHistory: vi.fn().mockResolvedValue([{
      id: "job-1", scheduled_for: "2026-07-16T09:00:00Z", window_start: "2026-07-16T08:00:00Z", window_end: "2026-07-16T09:00:00Z",
      workspace_id: "w1", status: "completed", provider: "openai", model: "gpt-test", base_url: "https://api.openai.com/v1", configuration_version: 3, event_ids: ["event-1", "event-2"], event_count: 2, chunk_count: 1,
      redaction_count: 1, request_payload: "<untrusted_activity_data>…</untrusted_activity_data>", response_payload: "{}", error_code: null,
      snapshot: { id: "state-1", summary: "保持了较长的连续专注。", valid_until: "2026-07-16T10:30:00Z" },
      created_at: "2026-07-16T09:00:00Z", updated_at: "2026-07-16T09:00:03Z",
    }]),
    updateActivityPreferences: vi.fn().mockResolvedValue({ ...preferences, collection_enabled: false, version: 4 }),
    activityExport: vi.fn(),
    deleteActivity: vi.fn(),
  } as unknown as WeatherFlowClient;
}

it("makes screen time visually primary and expands to raw provenance and inference audit", async () => {
  const mockClient = client();
  render(<ScreenTimePanel client={mockClient} workspaceId="w1" now={new Date("2026-07-16T10:00:00Z")} />);

  expect(await screen.findByText("5 小时 5 分")).toBeInTheDocument();
  expect(screen.getByText("浏览器 2 小时")).toBeInTheDocument();
  expect(screen.getByText("应用 14 · 标签 27")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "展开屏幕时间详情" }));

  expect(screen.getByText("全天活动时间线")).toBeInTheDocument();
  expect(screen.getAllByText("Visual Studio Code")).toHaveLength(2);
  expect(screen.getAllByText("github.com")).toHaveLength(2);
  expect(screen.getAllByText("ScreenTimePanel.tsx — WeatherFlow")).toHaveLength(2);
  expect(screen.getByText("保持了较长的连续专注。")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "暂停全部活动记录" }));
  await waitFor(() => expect(mockClient.updateActivityPreferences).toHaveBeenCalled());
});

it("refreshes visible screen-time data without remounting", async () => {
  const mockClient = client();
  const summarySpy = vi.mocked(mockClient.activitySummary);
  const eventsSpy = vi.mocked(mockClient.activityEvents);
  render(
    <ScreenTimePanel
      client={mockClient}
      workspaceId="w1"
      now={new Date("2026-07-16T10:00:00Z")}
      refreshIntervalMs={50}
    />,
  );

  expect(await screen.findByText("5 小时 5 分")).toBeInTheDocument();
  await waitFor(() => expect(summarySpy.mock.calls.length).toBeGreaterThan(1));
  expect(eventsSpy.mock.calls.length).toBeGreaterThan(1);
});
