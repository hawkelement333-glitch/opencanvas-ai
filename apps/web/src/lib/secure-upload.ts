import type { SecureUpload } from "./contracts";

export interface SecureUploadPresentation {
  label: string;
  detail: string;
  scanAccepted: boolean;
  poll: boolean;
}

// Only the server's accepted clean decision permits the processing UI. A browser
// clock cannot approve a scan, extend capability expiry, or manufacture timeout.
export function secureUploadPresentation(
  upload: SecureUpload | undefined,
  now = Date.now(),
  refreshFailed = false,
): SecureUploadPresentation {
  if (refreshFailed || !upload) {
    return {
      label: refreshFailed ? "Security status unavailable" : "Checking security status",
      detail: "This file is unavailable until its current security decision can be confirmed.",
      scanAccepted: false,
      poll: true,
    };
  }
  if (upload.objectState === "deleted" || upload.objectState === "deletion_requested") {
    return {
      label: upload.objectState === "deleted" ? "Deleted" : "Deletion requested",
      detail: "This file is unavailable. The server controls its exact-version cleanup.",
      scanAccepted: false,
      poll: upload.objectState === "deletion_requested",
    };
  }
  if (upload.state === "canceled" || upload.objectState === "canceled") {
    return {
      label: "Upload canceled",
      detail: "This file is unavailable.",
      scanAccepted: false,
      poll: false,
    };
  }
  if (upload.state === "expired") {
    return {
      label: "Upload expired",
      detail: "The permission to upload expired. Choose the file again to request a new upload.",
      scanAccepted: false,
      poll: false,
    };
  }
  if (upload.scanOutcome === "timeout" || upload.safeReasonCode === "scan_timeout") {
    return {
      label: "Scan timed out",
      detail:
        "The server rejected this scan window. The file remains quarantined; ask an operator to review or rescan it.",
      scanAccepted: false,
      poll: false,
    };
  }
  if (
    upload.objectState === "rejected" ||
    upload.objectState === "error" ||
    upload.state === "error" ||
    (upload.scanOutcome !== null && upload.scanOutcome !== "clean")
  ) {
    return {
      label: "Upload blocked",
      detail: "The file has no accepted clean decision and cannot be used for extraction or AI.",
      scanAccepted: false,
      poll: false,
    };
  }
  if (upload.objectState === "clean" && upload.scanOutcome === "clean") {
    return {
      label: "Scan complete",
      detail:
        "The server accepted the clean scan. Extraction and indexing must finish before this source is ready.",
      scanAccepted: true,
      poll: false,
    };
  }
  if (upload.state === "requested") {
    return {
      label: "Awaiting file upload",
      detail:
        "The file is not ready. Upload permission expiry is separate from the scan decision window.",
      scanAccepted: false,
      poll: true,
    };
  }
  const overdue = upload.scanDeadlineAt !== null && now >= Date.parse(upload.scanDeadlineAt);
  return {
    label: overdue ? "Scan decision overdue" : "Security scan pending",
    detail: overdue
      ? "No accepted decision was recorded within the window. The file remains quarantined while the server reconciles the outcome."
      : "The file stays quarantined until both native scanner records agree on this exact object version.",
    scanAccepted: false,
    poll: true,
  };
}
