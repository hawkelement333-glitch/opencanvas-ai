import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { Citation, DocumentMetadata } from "@/lib/contracts";

import { DocumentPreviewPanel } from "./document-preview-panel";

const api = vi.hoisted(() => ({
  getDocumentText: vi.fn(),
  getSourcePassage: vi.fn(),
}));

vi.mock("@/lib/api-client", () => ({
  canvasApi: api,
  getErrorMessage: (error: unknown) => (error instanceof Error ? error.message : "Unknown error"),
}));

const longFileName =
  "Solar deployment evidence with an intentionally long title that must remain understandable.pdf";

const document: DocumentMetadata = {
  id: "document-1",
  canvasId: "canvas-1",
  fileName: longFileName,
  fileType: "pdf",
  mediaType: "application/pdf",
  fileSize: 4_096,
  pageCount: 3,
  status: "ready",
  processingStage: "ready",
  errorMessage: null,
  chunkCount: 4,
  createdAt: "2026-07-21T12:00:00.000Z",
  updatedAt: "2026-07-21T12:00:00.000Z",
};

const citation: Citation = {
  id: "citation-1",
  sourceId: "source-1",
  documentId: document.id,
  documentTitle: document.fileName,
  chunkId: "chunk-1",
  pageNumber: 2,
  heading: "Deployment evidence",
  chunkIndex: 1,
  startOffset: 40,
  endOffset: 180,
  excerpt: "The cited passage supports the deployment claim.",
  claim: "The deployment completed successfully.",
  ordinal: 1,
};

function renderPreview(onClose = vi.fn()) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return {
    onClose,
    ...render(
      <QueryClientProvider client={queryClient}>
        <DocumentPreviewPanel document={document} citation={citation} onClose={onClose} />
      </QueryClientProvider>,
    ),
  };
}

describe("DocumentPreviewPanel", () => {
  it("preserves long source identity and focuses the resolved cited passage", async () => {
    api.getDocumentText.mockResolvedValue({
      documentId: document.id,
      fileName: document.fileName,
      text: "Full extracted source text with a long line that remains available to readers.",
      sections: [
        {
          pageNumber: 2,
          heading: "Deployment evidence",
          startOffset: 40,
          endOffset: 180,
        },
      ],
    });
    api.getSourcePassage.mockResolvedValue({
      documentId: document.id,
      chunkId: citation.chunkId,
      documentTitle: document.fileName,
      pageNumber: 2,
      heading: "Deployment evidence",
      chunkIndex: 1,
      startOffset: 40,
      endOffset: 180,
      text: "The exact cited source passage remains readable and linked to the answer.",
    });

    const { onClose } = renderPreview();

    expect(screen.getByRole("dialog", { name: longFileName })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: longFileName })).toHaveAttribute(
      "title",
      longFileName,
    );
    expect(screen.getByLabelText("Document metadata")).toHaveTextContent("4 passages");
    expect(screen.getByRole("button", { name: "Close document preview" })).toBeInTheDocument();

    const passage = await screen.findByTestId("source-passage");
    await waitFor(() => expect(passage).toHaveFocus());
    expect(passage).toHaveAccessibleName("Cited passage");
    expect(passage).toHaveTextContent(
      "The exact cited source passage remains readable and linked to the answer.",
    );
    expect(screen.getByLabelText("Extracted document text")).toHaveTextContent(
      "Full extracted source text",
    );

    await userEvent.click(screen.getByRole("button", { name: "Close document preview" }));
    expect(onClose).toHaveBeenCalledOnce();
  });
});
