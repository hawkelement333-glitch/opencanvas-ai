import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { createElement } from "react";

import { AssistantPanel } from "./assistant-panel";
import type { CanvasNode } from "@/lib/contracts";

const selected: CanvasNode[] = [
  {
    id: "node-1",
    canvasId: "canvas-1",
    type: "note",
    title: "Launch hypothesis",
    text: "Teams need a shared spatial context.",
    position: { x: 0, y: 0 },
    width: 320,
    height: 240,
    revision: 0,
    createdAt: "2026-07-16T18:00:00Z",
    updatedAt: "2026-07-16T18:00:00Z",
  },
];

describe("AssistantPanel", () => {
  it("constructs and submits an instruction for selected context", async () => {
    const user = userEvent.setup();
    const onAsk = vi.fn().mockResolvedValue({
      mock: true,
      grounded: false,
      insufficientEvidence: false,
    });
    render(
      createElement(AssistantPanel, {
        selectedNodes: selected,
        onAsk,
        onClearSelection: vi.fn(),
      }),
    );

    await user.type(screen.getByTestId("assistant-input"), "Summarize this idea");
    await user.click(screen.getByTestId("ask-assistant"));

    expect(onAsk).toHaveBeenCalledWith("Summarize this idea");
    expect(await screen.findByText(/Response added to your canvas/)).toBeInTheDocument();
    expect(screen.getByText("Mock AI")).toBeInTheDocument();
  });

  it("keeps the instruction available after an API failure", async () => {
    const user = userEvent.setup();
    const onAsk = vi.fn().mockRejectedValue(new Error("AI is temporarily unavailable"));
    render(
      createElement(AssistantPanel, {
        selectedNodes: selected,
        onAsk,
        onClearSelection: vi.fn(),
      }),
    );

    const input = screen.getByTestId("assistant-input");
    await user.type(input, "Find a risk");
    await user.click(screen.getByTestId("ask-assistant"));

    expect(await screen.findByRole("alert")).toHaveTextContent("AI is temporarily unavailable");
    expect(input).toHaveValue("Find a risk");
  });

  it("clearly reports insufficient evidence without claiming grounding", async () => {
    const user = userEvent.setup();
    const onAsk = vi.fn().mockResolvedValue({
      mock: true,
      grounded: false,
      insufficientEvidence: true,
    });
    render(
      createElement(AssistantPanel, {
        selectedNodes: selected,
        onAsk,
        onClearSelection: vi.fn(),
      }),
    );

    await user.type(screen.getByTestId("assistant-input"), "What is the annual revenue?");
    await user.click(screen.getByTestId("ask-assistant"));

    expect(await screen.findByText(/lack sufficient evidence/i)).toBeInTheDocument();
    expect(screen.queryByText(/grounded response/i)).not.toBeInTheDocument();
  });
});
