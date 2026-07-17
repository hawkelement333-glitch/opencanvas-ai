import { describe, expect, it, vi } from "vitest";

import { AutosaveQueue } from "./autosave-queue";
import type { CanvasNode } from "./contracts";

function node(text: string, revision = 0): CanvasNode {
  return {
    id: "node-1",
    canvasId: "canvas-1",
    type: "note",
    title: "Note",
    text,
    position: { x: 0, y: 0 },
    width: 320,
    height: 240,
    revision,
    createdAt: "2026-07-16T18:00:00Z",
    updatedAt: "2026-07-16T18:00:00Z",
  };
}

describe("AutosaveQueue", () => {
  it("serializes edits and rebases edits made during an in-flight save", async () => {
    let releaseFirst: ((value: CanvasNode) => void) | undefined;
    const firstSave = new Promise<CanvasNode>((resolve) => {
      releaseFirst = resolve;
    });
    const save = vi
      .fn<(value: CanvasNode) => Promise<CanvasNode>>()
      .mockReturnValueOnce(firstSave)
      .mockImplementation(async (value) => ({ ...value, revision: 2 }));
    const onSaved = vi.fn();
    const queue = new AutosaveQueue({ save, onSaved, onStateChange: vi.fn(), debounceMs: 60_000 });

    queue.mark(node("first"));
    const flushing = queue.flush();
    queue.mark(node("newer"));
    releaseFirst?.({ ...node("first"), revision: 1 });
    await flushing;

    expect(save).toHaveBeenCalledTimes(2);
    expect(save.mock.calls[1]?.[0]).toMatchObject({ text: "newer", revision: 1 });
    expect(onSaved).toHaveBeenLastCalledWith(expect.objectContaining({ revision: 2 }));
  });

  it("retains failed changes for an explicit retry", async () => {
    const save = vi
      .fn<(value: CanvasNode) => Promise<CanvasNode>>()
      .mockRejectedValueOnce(new Error("offline"))
      .mockImplementation(async (value) => ({ ...value, revision: 1 }));
    const states = vi.fn();
    const queue = new AutosaveQueue({ save, onSaved: vi.fn(), onStateChange: states });

    queue.mark(node("keep me"));
    await queue.flush();
    queue.retry();
    await vi.waitFor(() => expect(save).toHaveBeenCalledTimes(2));

    expect(states).toHaveBeenCalledWith(expect.objectContaining({ status: "error" }));
    await vi.waitFor(() =>
      expect(states).toHaveBeenLastCalledWith(expect.objectContaining({ status: "saved" })),
    );
  });
});
