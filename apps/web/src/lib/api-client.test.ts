import { afterEach, describe, expect, it, vi } from "vitest";

import { agentApi, APIError, canvasApi, universeApi } from "./api-client";

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

describe("rollback API client", () => {
  const workspaceId = "10000000-0000-4000-8000-000000000001";
  const canvasId = "20000000-0000-4000-8000-000000000001";
  const effectId = "30000000-0000-4000-8000-000000000001";
  const rollbackApprovalId = "40000000-0000-4000-8000-000000000001";

  it("loads only the server-derived rollback review", async () => {
    const review = {
      effectId,
      forwardAction: "note.create",
      noteId: "50000000-0000-4000-8000-000000000001",
      effectRevision: 0,
      currentRevision: 0,
      rollbackAction: "note.create.rollback",
      rollbackTargetKind: "authoritative_absence",
      requiredCapability: "canvas.note.create.rollback",
      eligible: true,
      approvalRequired: true,
      denialReason: null,
      conflict: false,
    };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(review), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await expect(
      agentApi.reviewReversibleWriteRollback(workspaceId, canvasId, effectId),
    ).resolves.toEqual(review);
    expect(fetchMock.mock.calls[0]?.[0]).toContain(
      `/workspaces/${workspaceId}/agent-executions/canvases/${canvasId}/reversible-effects/${effectId}/rollback-review`,
    );
    expect(fetchMock.mock.calls[0]?.[1]?.method).toBeUndefined();
    expect(fetchMock.mock.calls[0]?.[1]?.body).toBeUndefined();
  });

  it("sends only idempotency material when requesting approval", async () => {
    document.cookie = "mobius_session_csrf=rollback-csrf";
    const approval = {
      rollbackApprovalId,
      effectId,
      noteId: "50000000-0000-4000-8000-000000000001",
      forwardAction: "note.create",
      rollbackAction: "note.create.rollback",
      expectedCurrentRevision: 0,
      rollbackTargetKind: "authoritative_absence",
      expiresAt: "2026-07-24T19:15:00Z",
      duplicate: false,
    };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(approval), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await agentApi.issueReversibleWriteRollbackApproval(
      workspaceId,
      canvasId,
      effectId,
      "approval_key",
    );

    const init = fetchMock.mock.calls[0]?.[1];
    expect(init?.method).toBe("POST");
    expect(JSON.parse(String(init?.body))).toEqual({ idempotencyKey: "approval_key" });
    expect(init?.headers).toMatchObject({ "X-CSRF-Token": "rollback-csrf" });
    expect(String(init?.body)).not.toMatch(
      /capability|digest|revision|evidence|grant|action|expiry/i,
    );
  });

  it("sends only idempotency material when executing an approved rollback", async () => {
    const rollback = {
      rollbackResultId: "60000000-0000-4000-8000-000000000001",
      rollbackApprovalId,
      effectId,
      noteId: "50000000-0000-4000-8000-000000000001",
      rollbackAction: "note.update.rollback",
      rollbackTargetKind: "exact_prior_state",
      resultingRevision: 3,
      createdAt: "2026-07-24T19:01:00Z",
      duplicate: false,
    };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(rollback), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await agentApi.executeReversibleWriteRollback(
      workspaceId,
      canvasId,
      effectId,
      rollbackApprovalId,
      "execute_key",
    );

    const call = fetchMock.mock.calls[0];
    expect(call?.[0]).toContain(`/rollback-approvals/${rollbackApprovalId}/execute`);
    expect(JSON.parse(String(call?.[1]?.body))).toEqual({ idempotencyKey: "execute_key" });
    expect(String(call?.[1]?.body)).not.toMatch(
      /capability|digest|revision|evidence|grant|action|expiry/i,
    );
  });
});

describe("Dynamic Universe API client", () => {
  const workspaceId = "10000000-0000-4000-8000-000000000001";
  const canvasId = "20000000-0000-4000-8000-000000000001";
  const executionId = "30000000-0000-4000-8000-000000000001";
  const stepId = "40000000-0000-4000-8000-000000000001";
  const bundleId = "50000000-0000-4000-8000-000000000001";

  it("requests bounded viewport pages with revision fencing and selection hydration", async () => {
    const response = {
      canvas: { ...validCanvas, id: canvasId, workspaceId },
      canvasRevision: 3,
      graphRevision: 8,
      nodes: [],
      edges: [],
      boundaryNodes: [],
      selectedNodes: [],
      nextCursor: null,
      bounded: false,
    };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(response), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await universeApi.getViewport(canvasId, {
      minX: -100,
      minY: -200,
      maxX: 900,
      maxY: 800,
      limit: 50,
      cursor: bundleId,
      expectedCanvasRevision: 3,
      selectionIds: [stepId],
    });

    const url = new URL(String(fetchMock.mock.calls[0]?.[0]));
    expect(url.pathname).toContain(`/canvases/${canvasId}/universe-viewport`);
    expect(Object.fromEntries(url.searchParams)).toMatchObject({
      minX: "-100",
      minY: "-200",
      maxX: "900",
      maxY: "800",
      limit: "50",
      cursor: bundleId,
      expectedCanvasRevision: "3",
      selectionId: stepId,
    });
  });

  it("sends only an approval decision with CSRF and never client authority fields", async () => {
    document.cookie = "mobius_session_csrf=universe-csrf";
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ status: "changed" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await expect(
      universeApi.decideApproval(workspaceId, canvasId, executionId, stepId, "approved"),
    ).rejects.toMatchObject({ code: "invalid_response" });
    const init = fetchMock.mock.calls[0]?.[1];
    expect(init?.method).toBe("POST");
    expect(init?.headers).toMatchObject({ "X-CSRF-Token": "universe-csrf" });
    expect(JSON.parse(String(init?.body))).toEqual({ decision: "approved" });
    expect(String(init?.body)).not.toMatch(/grant|policy|capability|risk|resource|lease/i);
  });

  it("accepts only bounded ZIP responses for evidence downloads", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(new Uint8Array([80, 75, 3, 4]), {
          status: 200,
          headers: { "Content-Type": "application/zip", "Content-Length": "4" },
        }),
      )
      .mockResolvedValueOnce(
        new Response("<html>not a bundle</html>", {
          status: 200,
          headers: { "Content-Type": "text/html" },
        }),
      );

    await expect(
      universeApi.downloadBundle(workspaceId, canvasId, bundleId),
    ).resolves.toHaveProperty("size", 4);
    await expect(universeApi.downloadBundle(workspaceId, canvasId, bundleId)).rejects.toMatchObject(
      { code: "unsafe_bundle_response", status: 502 },
    );
    expect(fetchMock.mock.calls[0]?.[1]?.headers).toMatchObject({
      "X-CSRF-Token": "universe-csrf",
    });
  });
});
