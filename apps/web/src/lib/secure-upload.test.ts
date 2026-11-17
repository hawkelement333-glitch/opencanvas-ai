import { describe, expect, it } from "vitest";

import type { SecureUpload } from "./contracts";
import { secureUploadPresentation } from "./secure-upload";

export const pendingUpload: SecureUpload = {
  sessionId: "00000000-0000-4000-8000-000000000001",
  workspaceId: "00000000-0000-4000-8000-000000000002",
  canvasId: "00000000-0000-4000-8000-000000000003",
  documentId: "00000000-0000-4000-8000-000000000004",
  documentVersionId: "00000000-0000-4000-8000-000000000005",
  objectVersionId: "00000000-0000-4000-8000-000000000006",
  state: "completed",
  objectState: "scan_pending",
  scanOutcome: null,
  safeReasonCode: null,
  capability: null,
  uploadPath: null,
  duplicate: false,
  expiresAt: "2026-11-16T12:05:00Z",
  scanDeadlineAt: "2026-11-16T12:15:00Z",
};

describe("secure upload decision presentation", () => {
  it("keeps completed bytes pending after capability expiry until the separate scan deadline", () => {
    expect(
      secureUploadPresentation(pendingUpload, Date.parse("2026-11-16T12:06:00Z")),
    ).toMatchObject({ label: "Security scan pending", scanAccepted: false, poll: true });
  });
  it("reports an overdue decision without manufacturing a server timeout or a pass", () => {
    expect(
      secureUploadPresentation(pendingUpload, Date.parse("2026-11-16T12:15:00Z")),
    ).toMatchObject({ label: "Scan decision overdue", scanAccepted: false, poll: true });
  });
  it.each([{ scanOutcome: "timeout" as const }, { safeReasonCode: "scan_timeout" }])(
    "reports server timeout and preserves quarantine: %j",
    (result) => {
      expect(secureUploadPresentation({ ...pendingUpload, ...result })).toMatchObject({
        label: "Scan timed out",
        scanAccepted: false,
        poll: false,
      });
    },
  );
  it.each(["infected", "suspicious", "unsupported", "error"] as const)(
    "blocks %s decisions",
    (scanOutcome) => {
      expect(secureUploadPresentation({ ...pendingUpload, scanOutcome })).toMatchObject({
        label: "Upload blocked",
        scanAccepted: false,
        poll: false,
      });
    },
  );
  it("requires both promoted clean object state and server clean outcome", () => {
    expect(secureUploadPresentation({ ...pendingUpload, scanOutcome: "clean" }).scanAccepted).toBe(
      false,
    );
    expect(secureUploadPresentation({ ...pendingUpload, objectState: "clean" }).scanAccepted).toBe(
      false,
    );
    expect(
      secureUploadPresentation({ ...pendingUpload, objectState: "clean", scanOutcome: "clean" }),
    ).toMatchObject({ label: "Scan complete", scanAccepted: true });
  });
  it("fails closed when a previously clean status cannot be refreshed", () => {
    expect(
      secureUploadPresentation(
        { ...pendingUpload, objectState: "clean", scanOutcome: "clean" },
        Date.now(),
        true,
      ),
    ).toMatchObject({ label: "Security status unavailable", scanAccepted: false, poll: true });
  });
  it("does not let stale clean evidence override expiry, cancellation or deletion", () => {
    for (const state of ["expired", "canceled"] as const) {
      expect(
        secureUploadPresentation({
          ...pendingUpload,
          state,
          objectState: "clean",
          scanOutcome: "clean",
        }).scanAccepted,
      ).toBe(false);
    }
    for (const objectState of ["deletion_requested", "deleted"] as const) {
      expect(
        secureUploadPresentation({ ...pendingUpload, objectState, scanOutcome: "clean" })
          .scanAccepted,
      ).toBe(false);
    }
  });
});
