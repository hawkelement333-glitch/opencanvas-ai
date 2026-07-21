import { afterEach, describe, expect, it, vi } from "vitest";

import { APIError, canvasApi } from "./api-client";

const validCanvas = {
  id: "canvas-1",
  workspaceId: "00000000-0000-4000-8000-000000000002",
  name: "Launch plan",
  viewport: { x: 0, y: 0, zoom: 1 },
  revision: 0,
  createdAt: "2026-07-16T18:00:00Z",
  updatedAt: "2026-07-16T18:00:00Z",
};

afterEach(() => vi.restoreAllMocks());

describe("canvas API client", () => {
  it("validates successful responses with Zod", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify([validCanvas]), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await expect(canvasApi.listCanvases()).resolves.toEqual([validCanvas]);
  });

  it("rejects malformed server responses", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify([{ id: "missing-required-fields" }]), { status: 200 }),
    );

    await expect(canvasApi.listCanvases()).rejects.toMatchObject({
      code: "invalid_response",
      status: 502,
    });
  });

  it("surfaces safe provider failures", async () => {
    const timeoutSpy = vi.spyOn(window, "setTimeout");
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          title: "AI service unavailable",
          detail: "The AI provider could not complete the request. Try again.",
          code: "ai_provider_error",
        }),
        { status: 502, headers: { "Content-Type": "application/problem+json" } },
      ),
    );

    const request = canvasApi.askAI("canvas-1", {
      instruction: "Summarize this",
      selectedNodeIds: ["node-1"],
    });

    await expect(request).rejects.toEqual(
      expect.objectContaining<Partial<APIError>>({
        message: "The AI provider could not complete the request. Try again.",
        status: 502,
        code: "ai_provider_error",
      }),
    );
    expect(timeoutSpy).toHaveBeenCalledWith(expect.any(Function), 180_000);
  });

  it("uploads documents as multipart data without setting an unsafe content type", async () => {
    const timeoutSpy = vi.spyOn(window, "setTimeout");
    const timestamp = "2026-07-16T18:00:00Z";
    const document = {
      id: "document-1",
      canvasId: "canvas-1",
      fileName: "facts.md",
      fileType: "markdown",
      mediaType: "text/markdown",
      fileSize: 42,
      pageCount: null,
      status: "processing",
      processingStage: "extracting",
      errorMessage: null,
      chunkCount: 0,
      createdAt: timestamp,
      updatedAt: timestamp,
    };
    const node = {
      id: "node-document-1",
      canvasId: "canvas-1",
      type: "document",
      title: "facts.md",
      text: "",
      position: { x: 20, y: 40 },
      width: 340,
      height: 280,
      revision: 0,
      document,
      createdAt: timestamp,
      updatedAt: timestamp,
    };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ document, node }), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      }),
    );

    const file = new File(["# Verified facts"], "facts.md", { type: "text/markdown" });
    await expect(canvasApi.uploadDocument("canvas-1", file, { x: 20, y: 40 })).resolves.toEqual({
      document,
      node,
    });

    const requestInit = fetchMock.mock.calls[0]?.[1];
    expect(requestInit?.body).toBeInstanceOf(FormData);
    expect(requestInit?.headers).not.toHaveProperty("Content-Type");
    const uploaded = (requestInit?.body as FormData).get("file");
    expect(uploaded).toBeInstanceOf(File);
    expect((uploaded as File).name).toBe("facts.md");
    expect(timeoutSpy).toHaveBeenCalledWith(expect.any(Function), 180_000);
  });
});
