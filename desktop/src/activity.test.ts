import { expect, it } from "vitest";
import { nativeSampleToHeartbeat } from "./activity";

it("converts native exact window state into an idempotent raw-vault heartbeat", () => {
  const payload = nativeSampleToHeartbeat(
    {
      idle_seconds: 3,
      app_name: "Visual Studio Code",
      bundle_id: "com.microsoft.VSCode",
      window_title: "activity.ts — WeatherFlow",
      focused: true,
      idle_state: "active",
      category: "development",
      accessibility: "granted",
    },
    new Date("2026-07-16T06:00:00Z"),
    "native-1",
    "device-1",
  );

  expect(payload).toEqual({
    source: "macos_window",
    device_id: "device-1",
    source_instance: "weatherflow-desktop",
    source_event_id: "native-1",
    observed_at: "2026-07-16T06:00:00.000Z",
    pulsetime_seconds: 15,
    app_name: "Visual Studio Code",
    bundle_id: "com.microsoft.VSCode",
    window_title: "activity.ts — WeatherFlow",
    focused: true,
    idle_state: "active",
    category: "development",
  });
  expect(payload).not.toHaveProperty("app_switch_count");
  expect(JSON.stringify(payload)).not.toMatch(/keystroke|clipboard|screenshot|audio/i);
});
