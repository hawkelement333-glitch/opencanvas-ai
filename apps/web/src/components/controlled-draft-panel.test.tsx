import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createElement } from "react";
import { describe, expect, it, vi } from "vitest";

import { ControlledDraftPanel } from "./controlled-draft-panel";
import type { CanvasNode, ControlledDraft } from "@/lib/contracts";

const selected: CanvasNode[] = [
  {
    id: "a0000000-0000-4000-8000-000000000001",
    canvasId: "b0000000-0000-4000-8000-000000000001",
    type: "note",
    title: "Evidence",
    text: "Evidence",
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
  text: "Grounded result",
  insufficientEvidence: false,
  citations: [],
  duplicate: false,
};

function setup(onRun = vi.fn().mockResolvedValue(result)) {
  const onPrepare = vi
    .fn()
    .mockResolvedValue({ executionId: result.executionId, status: "ready", duplicate: false });
  const onCancel = vi
    .fn()
    .mockResolvedValue({
      executionId: result.executionId,
      cancelled: true,
      duplicate: false,
      status: "cancelled",
      reasonCode: "user_requested",
    });
  render(
    createElement(ControlledDraftPanel, {
      canvasId: selected[0]!.canvasId,
      selectedNodes: selected,
      onPrepare,
      onRun,
      onCancel,
      onOpenCitation: vi.fn(),
      onClearSelection: vi.fn(),
      getTraceUrl: (id) => `/trace/${id}`,
    }),
  );
  return { onPrepare, onRun, onCancel };
}

describe("ControlledDraftPanel", () => {
  it("does not start automatically and runs only after a server-issued execution is prepared", async () => {
    const user = userEvent.setup();
    const { onPrepare, onRun } = setup();
    expect(onPrepare).not.toHaveBeenCalled();
    await user.type(screen.getByTestId("controlled-draft-input"), "Summarize evidence");
    await user.click(screen.getByTestId("start-controlled-draft"));
    expect(await screen.findByText(/Grounded draft confirmed/i)).toBeInTheDocument();
    expect(onPrepare).toHaveBeenCalledWith(
      expect.objectContaining({ selectedNodeIds: [selected[0]!.id] }),
    );
    expect(onRun).toHaveBeenCalledWith(result.executionId);
  });

  it("cancels only a server-confirmed running execution", async () => {
    const user = userEvent.setup();
    let resolve!: (value: ControlledDraft) => void;
    const { onCancel } = setup(
      vi.fn().mockImplementation(
        () =>
          new Promise<ControlledDraft>((done) => {
            resolve = done;
          }),
      ),
    );
    await user.type(screen.getByTestId("controlled-draft-input"), "Summarize evidence");
    await user.click(screen.getByTestId("start-controlled-draft"));
    expect(
      await screen.findByRole("button", { name: "Cancel controlled draft" }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Cancel controlled draft" }));
    expect(onCancel).toHaveBeenCalledWith(result.executionId, expect.any(String));
    expect(await screen.findByText(/Controlled draft cancelled/i)).toBeInTheDocument();
    resolve(result);
  });
});
