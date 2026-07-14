import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { WeatherFlowClient } from "./bridge";
import { Capsule } from "./components/Capsule";
import { Cockpit } from "./components/Cockpit";
import { Companion } from "./components/Companion";
import type { Approval, DesktopSnapshot, RunStatus } from "./types";

let advanceToApproval: () => void = () => undefined;

function snapshot(status?: RunStatus): DesktopSnapshot {
  return {
    rhythm: {
      snapshot: { id: "state-overloaded", summary: "High load with limited recovery margin", valid_until: "2026-07-12" },
      policy: { proactivity: "silent", work_mode: "single_thread" },
      weather: { scene: "storm", intensity: 0.92, transition: "steady", snapshot_id: "state-overloaded", valid_until: "2026-07-12", presentation_version: "weather-v1" },
    },
    latest_run: status ? { id: "run-flagship", workspace_id: "w1", user_intent: "Ship with least burden", status, result_summary: status === "succeeded" ? "Release prepared" : null, updated_at: "2026-07-12" } : null,
    workspace: { id: "w1", name: "Project", action_roots: ["/tmp/project"], installed_packs: ["developer"] },
    metadata_sensor_enabled: false,
  };
}

function FlagshipDesktopStory({ client }: { client: WeatherFlowClient }) {
  const [surface, setSurface] = useState<"companion" | "capsule" | "cockpit">("companion");
  const [status, setStatus] = useState<RunStatus | undefined>();
  advanceToApproval = () => setStatus("waiting_approval");
  if (surface === "capsule") {
    return <Capsule client={client} workspaceId="w1" onAccepted={() => { setStatus("running"); setSurface("companion"); }} onCancel={() => setSurface("companion")} />;
  }
  if (surface === "cockpit") {
    return <Cockpit client={client} snapshot={snapshot(status)} offline={false} />;
  }
  return <Companion snapshot={snapshot(status)} onStartDrag={() => undefined} onOpenCapsule={() => setSurface("capsule")} onOpenCockpit={() => setSurface("cockpit")} />;
}

describe("flagship macOS desktop story", () => {
  it("stays silent through background work and opens structured approval only explicitly", async () => {
    let approvalStatus = "pending";
    const approval: Approval = {
      id: "approval-1",
      action_id: "action-1",
      run_id: "run-flagship",
      status: approvalStatus,
      version: 0,
      tool_id: "github.create_release",
      effect: "external_write",
      preview: { tool_id: "github.create_release", arguments: { repository: "wesz/weatherflow", tag: "v3.0.0" } },
    };
    const client = {
      createRun: vi.fn().mockResolvedValue({ id: "run-flagship" }),
      approvals: vi.fn().mockImplementation(async () => [{ ...approval, status: approvalStatus }]),
      runs: vi.fn().mockImplementation(async () => snapshot("waiting_approval").latest_run ? [snapshot("waiting_approval").latest_run] : []),
      timeline: vi.fn().mockResolvedValue([{ id: "event-1", type: "approval.requested", recorded_at: "2026-07-12", payload: {} }]),
      artifacts: vi.fn().mockResolvedValue([{ id: "artifact-1", run_id: "run-flagship", name: "release-checklist.md", media_type: "text/markdown", digest: "digest", size_bytes: 42 }]),
      decide: vi.fn().mockImplementation(async () => { approvalStatus = "approved"; return {}; }),
      status: vi.fn().mockResolvedValue({ local_only: true, telemetry_upload: false, workspace_id: "w1", installed_packs: ["developer"], providers: {}, behavior_sensor: { mode: "metadata_only", raw_content_captured: false, fallback_to_deliberate_signals: true }, retention: {} }),
    } as unknown as WeatherFlowClient;

    const { container } = render(<FlagshipDesktopStory client={client} />);
    expect(container.querySelector(".companion-shell")).toHaveAttribute("data-weather", "storm");
    expect(container.querySelector(".speech-bubble")).not.toBeInTheDocument();

    fireEvent.click(screen.getByLabelText("当前天气：风暴"));
    const input = screen.getByLabelText("告诉 WeatherFlow 要做什么");
    fireEvent.change(input, { target: { value: "Ship with least burden" } });
    fireEvent.submit(input.closest("form")!);
    await waitFor(() => expect(client.createRun).toHaveBeenCalledOnce());
    await waitFor(() => expect(container.querySelector(".companion-shell")).toHaveAttribute("data-agent-state", "active"));

    act(() => advanceToApproval());
    expect(await screen.findByLabelText("等待批准")).toBeInTheDocument();
    expect(screen.queryByText("今日控制台")).not.toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("等待批准"));

    expect(await screen.findByText("github.create_release")).toBeInTheDocument();
    expect(screen.getByText(/v3.0.0/)).toBeInTheDocument();
    expect(await screen.findByText("release-checklist.md")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "批准" }));
    await waitFor(() => expect(client.decide).toHaveBeenCalledWith("approval-1", "approve", 0, "w1"));
  });
});
