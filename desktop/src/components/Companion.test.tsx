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
  it("keeps weather separate from agent status and never speaks proactively", () => {
    const { container } = render(<Companion snapshot={snapshot} onStartDrag={() => undefined} onOpenCapsule={() => undefined} onOpenCockpit={() => undefined} />);
    const shell = container.querySelector(".companion-shell");
    expect(shell).toHaveAttribute("data-weather", "storm");
    expect(shell).toHaveAttribute("data-agent-state", "approval");
    expect(screen.getByLabelText("等待批准")).toBeInTheDocument();
    expect(screen.getByLabelText("当前天气：风暴")).toBeInTheDocument();
    expect(container.querySelector(".character-image")).not.toBeInTheDocument();
    expect(container.querySelector(".weather-particle")).not.toBeInTheDocument();
    expect(container.querySelector(".speech-bubble")).not.toBeInTheDocument();
    expect(screen.queryByText("Overloaded")).not.toBeInTheDocument();
  });

  it("opens Capsule on weather click and Cockpit only on explicit status", () => {
    const openCapsule = vi.fn();
    const openCockpit = vi.fn();
    render(<Companion snapshot={snapshot} onStartDrag={() => undefined} onOpenCapsule={openCapsule} onOpenCockpit={openCockpit} />);
    fireEvent.click(screen.getByLabelText("当前天气：风暴"));
    expect(openCapsule).toHaveBeenCalledOnce();
    expect(openCockpit).not.toHaveBeenCalled();
    fireEvent.click(screen.getByLabelText("等待批准"));
    expect(openCockpit).toHaveBeenCalledOnce();
  });

  it("starts native dragging from the weather icon and suppresses the click", () => {
    const startDrag = vi.fn();
    const openCapsule = vi.fn();
    render(<Companion snapshot={snapshot} onStartDrag={startDrag} onOpenCapsule={openCapsule} onOpenCockpit={() => undefined} />);
    const weather = screen.getByLabelText("当前天气：风暴");
    fireEvent.mouseDown(weather, { clientX: 10, clientY: 10, button: 0 });
    fireEvent.mouseMove(weather, { clientX: 22, clientY: 20, buttons: 1 });
    fireEvent.click(weather);
    expect(startDrag).toHaveBeenCalledOnce();
    expect(openCapsule).not.toHaveBeenCalled();
  });

  it("surfaces an unavailable opted-in sensor without changing weather", () => {
    const optedIn = { ...snapshot, metadata_sensor_enabled: true };
    const { container } = render(<Companion snapshot={optedIn} sensorAvailable={false} onStartDrag={() => undefined} onOpenCapsule={() => undefined} onOpenCockpit={() => undefined} />);
    expect(screen.getByRole("status", { name: "行为信号暂不可用" })).toBeInTheDocument();
    expect(container.querySelector(".companion-shell")).toHaveAttribute("data-weather", "storm");
  });
});
