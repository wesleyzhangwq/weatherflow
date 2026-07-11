import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Capsule } from "./Capsule";
import { WeatherFlowClient } from "../bridge";

describe("Capsule", () => {
  it("is pure input and closes immediately after daemon acceptance", async () => {
    const client = { createRun: vi.fn().mockResolvedValue({ id: "run-1" }) } as unknown as WeatherFlowClient;
    const accepted = vi.fn();
    render(<Capsule client={client} onAccepted={accepted} />);
    const input = screen.getByLabelText("Tell WeatherFlow what to do");
    fireEvent.change(input, { target: { value: "Ship the release" } });
    fireEvent.submit(input.closest("form")!);
    await waitFor(() => expect(accepted).toHaveBeenCalledOnce());
    expect(client.createRun).toHaveBeenCalledWith("Ship the release", expect.any(String));
    expect(screen.queryByText(/Cockpit/i)).not.toBeInTheDocument();
  });

  it("keeps input visible when acceptance fails", async () => {
    const client = { createRun: vi.fn().mockRejectedValue(new Error("offline")) } as unknown as WeatherFlowClient;
    render(<Capsule client={client} onAccepted={() => undefined} />);
    const input = screen.getByLabelText("Tell WeatherFlow what to do");
    fireEvent.change(input, { target: { value: "Keep this" } });
    fireEvent.submit(input.closest("form")!);
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(input).toHaveValue("Keep this");
  });
});
