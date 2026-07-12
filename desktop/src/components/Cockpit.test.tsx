import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { WeatherFlowClient } from "../bridge";
import type { DesktopSnapshot } from "../types";
import { Cockpit } from "./Cockpit";

const snapshot: DesktopSnapshot = {
  rhythm: { snapshot: { id: "s1", summary: "Steady rhythm", valid_until: "2026-07-12" }, policy: { proactivity: "silent", work_mode: "normal" }, weather: { scene: "fair", intensity: .5, transition: "steady", snapshot_id: "s1", valid_until: "2026-07-12", presentation_version: "v1" } },
  latest_run: { id: "r1", workspace_id: "w1", user_intent: "Ship release", status: "waiting_approval", result_summary: null, updated_at: "2026-07-12" },
  workspace: { id: "w1", name: "Project", action_roots: ["/tmp/project"], installed_packs: ["developer"] },
  metadata_sensor_enabled: false,
};

it("shows explicit operational detail and handles approval", async () => {
  const client = {
    approvals: vi.fn().mockResolvedValue([{ id: "a1", action_id: "x1", run_id: "r1", status: "pending", version: 0 }]),
    runs: vi.fn().mockResolvedValue([{ ...snapshot.latest_run }]),
    timeline: vi.fn().mockResolvedValue([{ id: "e1", type: "run.created", recorded_at: "2026-07-12", payload: {} }]),
    artifacts: vi.fn().mockResolvedValue([{ id: "f1", run_id: "r1", name: "release.md", media_type: "text/markdown", digest: "d", size_bytes: 12 }]),
    decide: vi.fn().mockResolvedValue({}),
    status: vi.fn().mockResolvedValue({ local_only: true, telemetry_upload: false, workspace_id: "w1", installed_packs: ["developer"], providers: {}, behavior_sensor: { mode: "metadata_only", raw_content_captured: false, fallback_to_deliberate_signals: true }, retention: { raw_behavior: "72h", aggregate_behavior: "90d", memory: "until_explicit_reset" } }),
    exportDiagnostics: vi.fn().mockResolvedValue({ path: "/tmp/diagnostic.json", sha256: "d", size_bytes: 10 }),
    previewReset: vi.fn().mockResolvedValue({ category: "behavior", count: 3 }),
    reset: vi.fn().mockResolvedValue({ category: "behavior", deleted_count: 3 }),
  } as unknown as WeatherFlowClient;
  render(<Cockpit client={client} snapshot={snapshot} offline={false} />);
  expect(await screen.findByText("Ship release")).toBeInTheDocument();
  expect(await screen.findByText("release.md")).toBeInTheDocument();
  fireEvent.click(await screen.findByRole("button", { name: "Approve" }));
  await waitFor(() => expect(client.decide).toHaveBeenCalledWith("a1", "approve", 0));
  expect(screen.getByText("Silent")).toBeInTheDocument();
  expect(screen.getAllByText("Check-ins only")).toHaveLength(2);
});

it("requires review then a second explicit click before behavior reset", async () => {
  const client = {
    approvals: vi.fn().mockResolvedValue([]), runs: vi.fn().mockResolvedValue([{ ...snapshot.latest_run }]), timeline: vi.fn().mockResolvedValue([]), artifacts: vi.fn().mockResolvedValue([]),
    status: vi.fn().mockResolvedValue({ local_only: true, telemetry_upload: false, workspace_id: "w1", installed_packs: ["developer"], providers: {}, behavior_sensor: { mode: "metadata_only", raw_content_captured: false, fallback_to_deliberate_signals: true }, retention: { raw_behavior: "72h", aggregate_behavior: "90d", memory: "until_explicit_reset" } }),
    exportDiagnostics: vi.fn().mockResolvedValue({ path: "/tmp/diagnostic.json", sha256: "d", size_bytes: 10 }),
    previewReset: vi.fn().mockResolvedValue({ category: "behavior", count: 3 }),
    reset: vi.fn().mockResolvedValue({ category: "behavior", deleted_count: 3 }),
  } as unknown as WeatherFlowClient;
  render(<Cockpit client={client} snapshot={snapshot} offline={false} />);
  fireEvent.click(await screen.findByRole("button", { name: "Review behavior reset" }));
  expect(client.reset).not.toHaveBeenCalled();
  fireEvent.click(await screen.findByRole("button", { name: "Delete 3 behavior records" }));
  await waitFor(() => expect(client.reset).toHaveBeenCalledWith("behavior", undefined));
});

describe("Cockpit lifecycle", () => {
  it("has no code path that opens another Cockpit from run events", async () => {
    const client = { approvals: vi.fn().mockResolvedValue([]), runs: vi.fn().mockResolvedValue([{ ...snapshot.latest_run }]), timeline: vi.fn().mockResolvedValue([]), artifacts: vi.fn().mockResolvedValue([]), status: vi.fn().mockResolvedValue({ local_only: true, telemetry_upload: false, workspace_id: "w1", installed_packs: [], providers: {}, behavior_sensor: { mode: "metadata_only", raw_content_captured: false, fallback_to_deliberate_signals: true }, retention: {} }) } as unknown as WeatherFlowClient;
    const open = vi.fn();
    window.addEventListener("weatherflow:open_cockpit", open);
    render(<Cockpit client={client} snapshot={snapshot} offline={false} />);
    await screen.findByText("Daily cockpit");
    expect(open).not.toHaveBeenCalled();
    window.removeEventListener("weatherflow:open_cockpit", open);
  });
});
