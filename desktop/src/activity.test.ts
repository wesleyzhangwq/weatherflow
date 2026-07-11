import { expect, it } from "vitest";
import { ActivityAccumulator } from "./activity";

it("aggregates only privacy-safe activity metadata", () => {
  const start = new Date("2026-07-12T00:00:00Z");
  const accumulator = new ActivityAccumulator(start);
  accumulator.record({ idle_seconds: 1, category: "development" }, 5);
  accumulator.record({ idle_seconds: 0, category: "communication" }, 5);
  const payload = accumulator.flush(new Date("2026-07-12T00:00:10Z"));

  expect(payload).toEqual({
    kind: "activity_metadata",
    observed_at: "2026-07-12T00:00:10.000Z",
    window_start: "2026-07-12T00:00:00.000Z",
    window_end: "2026-07-12T00:00:10.000Z",
    active_seconds: 9,
    idle_seconds: 1,
    app_switch_count: 1,
    category_seconds: { development: 4, communication: 5 },
  });
  expect(JSON.stringify(payload)).not.toMatch(/title|application|keystroke|clipboard|screen/i);
});
