import { expect, it } from "vitest";
import {
  browserCategory,
  browserTabToHeartbeat,
} from "../browser-extension/activity.mjs";

it("preserves complete focused-tab metadata for the raw activity vault", () => {
  const heartbeat = browserTabToHeartbeat(
    {
      id: 42,
      windowId: 7,
      active: true,
      audible: true,
      incognito: true,
      title: "ActivityWatch/activitywatch: Free and open-source automated time tracker",
      url: "https://github.com/ActivityWatch/activitywatch?tab=readme-ov-file#readme",
    },
    {
      browserName: "Chrome",
      deviceId: "device-1",
      eventId: "event-1",
      observedAt: new Date("2026-07-16T06:00:00Z"),
    },
  );

  expect(heartbeat).toEqual({
    source: "browser_tab",
    device_id: "device-1",
    source_instance: "weatherflow-browser-chrome",
    source_event_id: "event-1",
    observed_at: "2026-07-16T06:00:00.000Z",
    pulsetime_seconds: 80,
    browser_name: "Chrome",
    browser_window_id: "7",
    browser_tab_id: "42",
    url: "https://github.com/ActivityWatch/activitywatch?tab=readme-ov-file#readme",
    domain: "github.com",
    tab_title: "ActivityWatch/activitywatch: Free and open-source automated time tracker",
    audible: true,
    incognito: true,
    focused: true,
    idle_state: "active",
    category: "development",
  });
});

it("classifies browser categories without changing exact URL or title", () => {
  expect(browserCategory("github.com")).toBe("development");
  expect(browserCategory("docs.google.com")).toBe("planning");
  expect(browserCategory("unknown.example")).toBe("research");
});

it("records browser-window focus separately from the active tab flag", () => {
  const heartbeat = browserTabToHeartbeat(
    {
      id: 9,
      windowId: 2,
      active: true,
      incognito: false,
      title: "Background browser",
      url: "https://example.com/",
    },
    {
      browserName: "Chrome",
      deviceId: "device-1",
      eventId: "event-2",
      observedAt: new Date("2026-07-16T06:00:00Z"),
      focused: false,
    },
  );

  expect(heartbeat.focused).toBe(false);
});
