import { webcrypto, createHash } from "node:crypto";
import { afterEach, describe, expect, it, vi } from "vitest";

import { secureUploadApi } from "./api-client";

const result = {
  sessionId: "00000000-0000-4000-8000-000000000001",
  workspaceId: "00000000-0000-4000-8000-000000000002",
  canvasId: "00000000-0000-4000-8000-000000000003",
  documentId: "00000000-0000-4000-8000-000000000004",
  documentVersionId: "00000000-0000-4000-8000-000000000005",
  objectVersionId: "00000000-0000-4000-8000-000000000006",
  state: "requested",
  objectState: "quarantined",
  scanOutcome: null,
  safeReasonCode: null,
  capability: "test-only-capability",
  uploadPath: "https://untrusted.invalid/upload",
  expiresAt: "2026-11-16T12:05:00Z",
  scanDeadlineAt: null,
  duplicate: false,
};
const response = () => new Response(JSON.stringify(result), { status: 200 });
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("secure upload API transport", () => {
  it("binds initialization to exact bytes and position without a legacy multipart upload", async () => {
    vi.stubGlobal("crypto", webcrypto);
    const file = new File(["evaluation document"], "example.txt", { type: "text/plain" });
    Object.defineProperty(file, "arrayBuffer", {
      value: async () => new TextEncoder().encode("evaluation document").buffer,
    });
    const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(response());
    await secureUploadApi.initiate(
      result.workspaceId,
      result.canvasId,
      file,
      { x: 12, y: 34 },
      "idempotency-test",
    );
    const [url, init] = fetch.mock.calls[0]!;
    expect(url).toContain(
      `/workspaces/${result.workspaceId}/canvases/${result.canvasId}/upload-sessions`,
    );
    expect(JSON.parse(init!.body as string)).toEqual({
      fileName: "example.txt",
      mediaType: "text/plain",
      sizeBytes: file.size,
      sha256: createHash("sha256").update("evaluation document").digest("hex"),
      idempotencyKey: "idempotency-test",
      x: 12,
      y: 34,
    });
    expect(fetch).toHaveBeenCalledTimes(1);
  });
  it("sends capability only to the configured API upload route with authenticated CSRF protection", async () => {
    document.cookie = "mobius_session_csrf=test-csrf";
    const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(response());
    const file = new File(["bytes"], "example.txt");
    await secureUploadApi.uploadContent(result.sessionId, file, result.capability);
    const [url, init] = fetch.mock.calls[0]!;
    expect(url).toContain(`/upload-sessions/${result.sessionId}/content`);
    expect(url).not.toContain("untrusted.invalid");
    expect(init).toMatchObject({
      method: "PUT",
      body: file,
      credentials: "include",
      headers: {
        "Content-Type": "application/octet-stream",
        "X-Upload-Capability": result.capability,
        "X-CSRF-Token": "test-csrf",
      },
    });
  });
  it("reloads authorized status without a capability and binds deletion to the exact session", async () => {
    const fetch = vi.spyOn(globalThis, "fetch").mockImplementation(async () => response());
    await secureUploadApi.getForDocument(result.documentId);
    expect(fetch.mock.calls[0]![0]).toContain(`/documents/${result.documentId}/upload-session`);
    expect(fetch.mock.calls[0]![1]!.headers).not.toHaveProperty("X-Upload-Capability");
    await secureUploadApi.requestDeletion(
      result.workspaceId,
      result.canvasId,
      result.sessionId,
      "delete-once",
    );
    expect(fetch.mock.calls[1]![0]).toContain(
      `/upload-sessions/${result.sessionId}/deletion-requests`,
    );
    expect(JSON.parse(fetch.mock.calls[1]![1]!.body as string)).toEqual({
      idempotencyKey: "delete-once",
      reasonCode: "user_requested",
    });
  });
  it("does not retry an uncertain write", async () => {
    const fetch = vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("connection lost"));
    await expect(
      secureUploadApi.complete(result.workspaceId, result.canvasId, result.sessionId),
    ).rejects.toMatchObject({ code: "network_error" });
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});
