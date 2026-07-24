import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { createElement } from "react";

import { ControlledDraftPanel } from "./controlled-draft-panel";
import type { CanvasNode, ControlledDraft } from "@/lib/contracts";

const selected: CanvasNode[] = [
  {
    id: "a0000000-0000-4000-8000-000000000001",
    canvasId: "b0000000-0000-4000-8000-000000000001",
    type: "note",
    title: "Launch hypothesis",
    text: "Teams need shared spatial context.",
    position: { x: 0, y: 0 },
    width: 320,
    height: 240,
    revision: 0,
    createdAt: "2026-07-16T18:00:00Z",
    updatedAt: "2026-07-16T18:00:00Z",
  },
];

const result: ControlledDraft = {
  executionId: "c0000000-0000-4000-8000-000000000001",
  traceId: "d0000000-0000-4000-8000-000000000001",
  responseId: "e0000000-0000-4000-8000-000000000001",
  text: "Shared spatial context is supported.",
  insufficientEvidence: false,
  duplicate: false,
  citations: [
    {
      sourceId: "source-1",
      documentId: "f0000000-0000-4000-8000-000000000001",
      documentVersion: 1,
      chunkId: "10000000-0000-4000-8000-000000000001",
      claim: "Teams need shared spatial context.",
      quote: "shared spatial context",
    },
  ],
};

function renderPanel(onStart = vi.fn().mockResolvedValue(result)) {
  return {
    onStart,
    ...render(
      createElement(ControlledDraftPanel, {
        canvasId: "b0000000-0000-4000-8000-000000000001",
        selectedNodes: selected,
        onStart,
        onOpenCitation: vi.fn(),
        onClearSelection: vi.fn(),
        getTraceUrl: (traceId) => `/trace/${traceId}`,
      }),
    ),
  };
}

describe("ControlledDraftPanel", () => {
  it("starts only after explicit user action and shows a read-only grounded draft", async () => {
    const user = userEvent.setup();
    const { onStart } = renderPanel();
    expect(onStart).not.toHaveBeenCalled();
    await user.type(screen.getByTestId("controlled-draft-input"), "Summarize this idea");
    await user.click(screen.getByTestId("start-controlled-draft"));
    expect(await screen.findByText(/Grounded draft confirmed/i)).toBeInTheDocument();
    expect(onStart).toHaveBeenCalledWith(
      expect.objectContaining({
        canvasId: "b0000000-0000-4000-8000-000000000001",
        instruction: "Summarize this idea",
        selectedNodeIds: [selected[0]!.id],
      }),
    );
    expect(screen.getByRole("button", { name: "Citation [1]" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Inspect Trace/i })).toHaveAttribute(
      "href",
      `/trace/${result.traceId}`,
    );
    expect(
      screen.queryByRole("button", { name: /save|apply|create note/i }),
    ).not.toBeInTheDocument();
  });

  it("shows the server-request state and blocks duplicate starts", async () => {
    const user = userEvent.setup();
    let resolve!: (value: ControlledDraft) => void;
    const onStart = vi.fn().mockImplementation(
      () =>
        new Promise<ControlledDraft>((done) => {
          resolve = done;
        }),
    );
    renderPanel(onStart);
    await user.type(screen.getByTestId("controlled-draft-input"), "Find a risk");
    await user.click(screen.getByTestId("start-controlled-draft"));
    expect(screen.getByText(/Starting controlled draft/i)).toBeInTheDocument();
    expect(screen.getByTestId("start-controlled-draft")).toBeDisabled();
    await user.click(screen.getByTestId("start-controlled-draft"));
    expect(onStart).toHaveBeenCalledTimes(1);
    resolve(result);
    expect(await screen.findByTestId("controlled-draft-result")).toBeInTheDocument();
  });

  it("does not expose an unsafe failure message", async () => {
    const user = userEvent.setup();
    renderPanel(vi.fn().mockRejectedValue(new Error("provider token: secret-value")));
    await user.type(screen.getByTestId("controlled-draft-input"), "Find a risk");
    await user.click(screen.getByTestId("start-controlled-draft"));
    expect(await screen.findByRole("alert")).toHaveTextContent(/could not be completed/i);
    expect(screen.queryByText(/secret-value/i)).not.toBeInTheDocument();
  });
});
