import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Capsule } from "./Capsule";
import { WeatherFlowClient } from "../bridge";

describe("Capsule", () => {
  it("is pure input and closes immediately after daemon acceptance", async () => {
    const client = { createRun: vi.fn().mockResolvedValue({ id: "run-1" }) } as unknown as WeatherFlowClient;
    const accepted = vi.fn();
    render(<Capsule client={client} workspaceId="w1" onAccepted={accepted} onCancel={() => undefined} />);
    const input = screen.getByLabelText("告诉 WeatherFlow 要做什么");
    fireEvent.change(input, { target: { value: "Ship the release" } });
    fireEvent.submit(input.closest("form")!);
    await waitFor(() => expect(accepted).toHaveBeenCalledOnce());
    expect(client.createRun).toHaveBeenCalledWith("Ship the release", expect.any(String), "w1");
    expect(screen.queryByText("控制台")).not.toBeInTheDocument();
  });

  it("can be cancelled with Escape or the visible close button", () => {
    const cancel = vi.fn();
    const client = { createRun: vi.fn() } as unknown as WeatherFlowClient;
    const { rerender } = render(<Capsule client={client} workspaceId="w1" onAccepted={() => undefined} onCancel={cancel} />);
    fireEvent.keyDown(screen.getByLabelText("告诉 WeatherFlow 要做什么"), { key: "Escape" });
    expect(cancel).toHaveBeenCalledOnce();
    rerender(<Capsule client={client} workspaceId="w1" onAccepted={() => undefined} onCancel={cancel} />);
    fireEvent.click(screen.getByRole("button", { name: "关闭输入框" }));
    expect(cancel).toHaveBeenCalledTimes(2);
  });

  it("cancels automatically when the window loses focus", () => {
    const cancel = vi.fn();
    const client = { createRun: vi.fn() } as unknown as WeatherFlowClient;
    render(<Capsule client={client} workspaceId="w1" onAccepted={() => undefined} onCancel={cancel} />);
    fireEvent.blur(window);
    expect(cancel).toHaveBeenCalledOnce();
  });

  it("keeps input visible when acceptance fails", async () => {
    const client = { createRun: vi.fn().mockRejectedValue(new Error("offline")) } as unknown as WeatherFlowClient;
    render(<Capsule client={client} workspaceId="w1" onAccepted={() => undefined} onCancel={() => undefined} />);
    const input = screen.getByLabelText("告诉 WeatherFlow 要做什么");
    fireEvent.change(input, { target: { value: "Keep this" } });
    fireEvent.submit(input.closest("form")!);
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(input).toHaveValue("Keep this");
  });

  it("keeps desktop Runs behind explicit project authorization", async () => {
    const client = { createRun: vi.fn() } as unknown as WeatherFlowClient;
    render(<Capsule client={client} onAccepted={() => undefined} onCancel={() => undefined} />);
    const input = screen.getByLabelText("告诉 WeatherFlow 要做什么");
    fireEvent.change(input, { target: { value: "Inspect this" } });
    fireEvent.submit(input.closest("form")!);
    expect(await screen.findByRole("alert")).toHaveTextContent("先在控制台选择项目");
    expect(client.createRun).not.toHaveBeenCalled();
  });

  it("does not submit while a Chinese input method is composing", async () => {
    const createRun = vi.fn().mockResolvedValue({ id: "run-1" });
    const client = { createRun } as unknown as WeatherFlowClient;
    render(<Capsule client={client} workspaceId="w1" onAccepted={() => undefined} onCancel={() => undefined} />);
    const input = screen.getByLabelText("告诉 WeatherFlow 要做什么");

    fireEvent.compositionStart(input);
    fireEvent.change(input, { target: { value: "你好" } });
    fireEvent.keyDown(input, { key: "Enter", code: "Enter", keyCode: 229, isComposing: true });
    fireEvent.submit(input.closest("form")!);

    await Promise.resolve();
    expect(createRun).not.toHaveBeenCalled();

    fireEvent.compositionEnd(input);
    fireEvent.submit(input.closest("form")!);
    await waitFor(() => expect(createRun).toHaveBeenCalledOnce());
  });
});
