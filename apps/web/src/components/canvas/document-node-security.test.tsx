import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { NodeProps } from "@xyflow/react";

import type { CanvasFlowNode } from "@/lib/flow";
import type { SecureUpload } from "@/lib/contracts";
import { DocumentNodeCard } from "./document-node";

vi.mock("@xyflow/react", () => ({
  Handle: () => null,
  NodeResizer: () => null,
  Position: { Left: "left", Right: "right" },
}));
vi.mock("./canvas-node", () => ({
  useCanvasNodeActions: () => ({
    onDuplicate: vi.fn(),
    onDeleteDocument: vi.fn(),
    onSelect: vi.fn(),
    onPreviewDocument: vi.fn(),
    onRetryDocument: vi.fn(),
  }),
}));

const secure: SecureUpload = {
  sessionId: "session",
  workspaceId: "workspace",
  canvasId: "canvas",
  documentId: "doc",
  documentVersionId: "version",
  objectVersionId: "object",
  state: "completed",
  objectState: "scan_pending",
  scanOutcome: null,
  safeReasonCode: null,
  capability: null,
  uploadPath: null,
  expiresAt: "2026-11-16T12:05:00Z",
  scanDeadlineAt: null,
  duplicate: false,
};
function props(upload: SecureUpload | undefined, ready = true): NodeProps<CanvasFlowNode> {
  return {
    id: "node",
    selected: false,
    data: {
      pending: false,
      secureUploadRequired: true,
      secureUpload: upload,
      node: {
        id: "node",
        canvasId: "canvas",
        title: "Example",
        text: "",
        type: "document",
        position: { x: 0, y: 0 },
        width: 340,
        height: 280,
        revision: 0,
        createdAt: secure.expiresAt,
        updatedAt: secure.expiresAt,
        document: {
          id: "doc",
          canvasId: "canvas",
          fileName: "example.pdf",
          fileType: "pdf",
          mediaType: "application/pdf",
          fileSize: 100,
          pageCount: 1,
          status: ready ? "ready" : "processing",
          processingStage: ready ? "ready" : "extracting",
          errorMessage: null,
          chunkCount: 1,
          createdAt: secure.expiresAt,
          updatedAt: secure.expiresAt,
        },
      },
    },
  } as NodeProps<CanvasFlowNode>;
}

describe("document security status", () => {
  it("does not expose preview from stale ready metadata while scan is pending", () => {
    render(<DocumentNodeCard {...props(secure)} />);
    expect(screen.getByText("Security scan pending")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Preview extracted text" })).toBeDisabled();
    expect(screen.queryByText("Ready")).not.toBeInTheDocument();
  });
  it("reloads fail closed until authorized security state is available", () => {
    render(<DocumentNodeCard {...props(undefined)} />);
    expect(screen.getByText("Checking security status")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Preview extracted text" })).toBeDisabled();
  });
  it("keeps accepted clean promotion separate from extraction completion", () => {
    render(
      <DocumentNodeCard
        {...props({ ...secure, objectState: "clean", scanOutcome: "clean" }, false)}
      />,
    );
    expect(screen.getByText("Extracting text")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Preview extracted text" })).toBeDisabled();
  });
  it("enables preview only after clean acceptance and extraction ready", () => {
    render(
      <DocumentNodeCard {...props({ ...secure, objectState: "clean", scanOutcome: "clean" })} />,
    );
    expect(screen.getByRole("button", { name: "Preview extracted text" })).toBeEnabled();
  });
  it("shows server timeout without offering unsafe processing retry", () => {
    render(<DocumentNodeCard {...props({ ...secure, safeReasonCode: "scan_timeout" })} />);
    expect(screen.getByText("Scan timed out")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Preview extracted text" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Retry processing" })).not.toBeInTheDocument();
  });
  it("labels deletion as requested until the server confirms completion", () => {
    render(
      <DocumentNodeCard
        {...props({ ...secure, objectState: "deletion_requested", scanOutcome: "clean" })}
      />,
    );
    expect(screen.getByText("Deletion requested")).toBeInTheDocument();
    expect(screen.queryByText("Deleted")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Preview extracted text" })).toBeDisabled();
  });
});
