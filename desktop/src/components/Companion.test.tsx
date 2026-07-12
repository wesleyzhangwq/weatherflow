import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Companion } from "./Companion";
import type { DesktopSnapshot } from "../types";

const snapshot: DesktopSnapshot = {
  rhythm: {
    snapshot: { id: "state-1", summary: "Overloaded", valid_until: "2026-07-12" },
    policy: { proactivity: "silent", work_mode: "single_thread" },
    weather: { scene: "storm", intensity: 0.9, transition: "steady", snapshot_id: "state-1", valid_until: "2026-07-12", presentation_version: "weather-v1" },
  },
  latest_run: { id: "run-1", workspace_id: "w1", user_intent: "Ship", status: "waiting_approval", result_summary: null, updated_at: "2026-07-12" },
  workspace: { id: "w1", name: "Project", action_roots: ["/tmp/project"], installed_packs: ["developer"] },
  metadata_sensor_enabled: false,
};

describe("Companion", () => {
  it("keeps weather separate from the approval ring and never speaks proactively", () => {
    const { container } = render(<Companion snapshot={snapshot} onOpenCapsule={() => undefined} onOpenCockpit={() => undefined} />);
    const shell = container.querySelector(".companion-shell");
    expect(shell).toHaveAttribute("data-weather", "storm");
    expect(shell).toHaveAttribute("data-ring", "approval");
    expect(screen.getByLabelText("Approval waiting")).toBeInTheDocument();
    expect(container.querySelector(".speech-bubble")).not.toBeInTheDocument();
    expect(screen.queryByText("Overloaded")).not.toBeInTheDocument();
  });

  it("opens Capsule on character click and Cockpit only on explicit control", () => {
    const openCapsule = vi.fn();
    const openCockpit = vi.fn();
    render(<Companion snapshot={snapshot} onOpenCapsule={openCapsule} onOpenCockpit={openCockpit} />);
    fireEvent.click(screen.getByLabelText("Open command capsule"));
    expect(openCapsule).toHaveBeenCalledOnce();
    expect(openCockpit).not.toHaveBeenCalled();
    fireEvent.click(screen.getByLabelText("Open Cockpit"));
    expect(openCockpit).toHaveBeenCalledOnce();
  });

  it("surfaces an unavailable opted-in sensor without changing weather", () => {
    const optedIn = { ...snapshot, metadata_sensor_enabled: true };
    const { container } = render(<Companion snapshot={optedIn} sensorAvailable={false} onOpenCapsule={() => undefined} onOpenCockpit={() => undefined} />);
    expect(screen.getByRole("status")).toHaveTextContent("Activity signal unavailable");
    expect(container.querySelector(".companion-shell")).toHaveAttribute("data-weather", "storm");
  });
});
