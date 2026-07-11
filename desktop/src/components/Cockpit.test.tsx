import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { WeatherFlowClient } from "../bridge";
import type { DesktopSnapshot } from "../types";
import { Cockpit } from "./Cockpit";

const snapshot: DesktopSnapshot = {
  rhythm: { snapshot: { id: "s1", summary: "Steady rhythm", valid_until: "2026-07-12" }, policy: { proactivity: "silent", work_mode: "normal" }, weather: { scene: "fair", intensity: .5, transition: "steady", snapshot_id: "s1", valid_until: "2026-07-12", presentation_version: "v1" } },
  latest_run: { id: "r1", user_intent: "Ship release", status: "waiting_approval", result_summary: null, updated_at: "2026-07-12" },
};

it("shows explicit operational detail and handles approval", async () => {
  const client = {
    approvals: vi.fn().mockResolvedValue([{ id: "a1", action_id: "x1", run_id: "r1", status: "pending", version: 0 }]),
    timeline: vi.fn().mockResolvedValue([{ id: "e1", type: "run.created", recorded_at: "2026-07-12", payload: {} }]),
    artifacts: vi.fn().mockResolvedValue([{ id: "f1", run_id: "r1", name: "release.md", media_type: "text/markdown", digest: "d", size_bytes: 12 }]),
    decide: vi.fn().mockResolvedValue({}),
  } as unknown as WeatherFlowClient;
  render(<Cockpit client={client} snapshot={snapshot} offline={false} />);
  expect(await screen.findByText("Ship release")).toBeInTheDocument();
  expect(await screen.findByText("release.md")).toBeInTheDocument();
  fireEvent.click(await screen.findByRole("button", { name: "Approve" }));
  await waitFor(() => expect(client.decide).toHaveBeenCalledWith("a1", "approve", 0));
  expect(screen.getByText("Silent")).toBeInTheDocument();
});

describe("Cockpit lifecycle", () => {
  it("has no code path that opens another Cockpit from run events", async () => {
    const client = { approvals: vi.fn().mockResolvedValue([]), timeline: vi.fn().mockResolvedValue([]), artifacts: vi.fn().mockResolvedValue([]) } as unknown as WeatherFlowClient;
    const open = vi.fn();
    window.addEventListener("weatherflow:open_cockpit", open);
    render(<Cockpit client={client} snapshot={snapshot} offline={false} />);
    await screen.findByText("Daily cockpit");
    expect(open).not.toHaveBeenCalled();
    window.removeEventListener("weatherflow:open_cockpit", open);
  });
});
