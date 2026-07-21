import { describe, expect, it } from "vitest";

import type { CanvasNode, DocumentMetadata } from "./contracts";
import {
  citationRole,
  documentStageDetails,
  edgeKindDetails,
  nodeRole,
  summarizeResources,
} from "./universe";

const timestamp = "2026-07-21T12:00:00.000Z";

function document(
  status: DocumentMetadata["status"],
  processingStage: DocumentMetadata["processingStage"],
): DocumentMetadata {
  return {
    id: `document-${status}`,
    canvasId: "canvas-1",
    fileName: `${status}.pdf`,
    fileType: "pdf",
    mediaType: "application/pdf",
    fileSize: 1024,
    pageCount: 3,
    status,
    processingStage,
    errorMessage: null,
    chunkCount: status === "ready" ? 8 : 0,
    createdAt: timestamp,
    updatedAt: timestamp,
  };
}

function node(partial: Partial<CanvasNode>): CanvasNode {
  return {
    id: partial.id ?? "node-1",
    canvasId: "canvas-1",
    type: partial.type ?? "note",
    title: partial.title ?? "Research note",
    text: partial.text ?? "",
    position: { x: 0, y: 0 },
    width: 320,
    height: 240,
    revision: 1,
    createdAt: timestamp,
    updatedAt: timestamp,
    ...partial,
  };
}

describe("semantic universe mapping", () => {
  it("maps existing node types to plain-language hierarchy roles", () => {
    expect(nodeRole(node({ type: "note" })).label).toBe("Moon · Supporting Note");
    expect(nodeRole(node({ type: "ai_response" })).label).toBe("Star · Answer Hub");
    expect(
      nodeRole(
        node({
          type: "document",
          title: "Aurora",
          document: document("ready", "ready"),
        }),
      ).label,
    ).toBe("Planet · Document");
  });

  it("labels citation fragments without changing citation identity", () => {
    expect(citationRole({ ordinal: 2, documentTitle: "Aurora Operating Notes" })).toMatchObject({
      level: "asteroid",
      label: "Asteroid · Evidence Fragment",
      plainLabel: "Asteroid · Evidence Fragment · Citation 2",
    });
  });

  it("distinguishes pathway types with accessible explanations", () => {
    expect(edgeKindDetails.default.plainLabel).toContain("User-created relationship");
    expect(edgeKindDetails.generated_from.plainLabel).toContain("selected context");
    expect(edgeKindDetails.cites.plainLabel).toContain("exact source passage");
  });

  it("summarizes only real resources from canvas nodes", () => {
    const readyDocumentNode = node({
      id: "ready-document",
      type: "document",
      document: document("ready", "ready"),
    });
    const processingDocumentNode = node({
      id: "processing-document",
      type: "document",
      document: document("processing", "embedding"),
    });
    const failedDocumentNode = node({
      id: "failed-document",
      type: "document",
      document: document("retryable_failure", "failed"),
    });
    const responseNode = node({
      id: "response",
      type: "ai_response",
      citations: [
        {
          id: "citation-1",
          sourceId: "source-1",
          documentId: "document-ready",
          documentTitle: "ready.pdf",
          chunkId: "chunk-1",
          pageNumber: 1,
          heading: null,
          chunkIndex: 0,
          startOffset: 0,
          endOffset: 100,
          excerpt: "Evidence excerpt",
          claim: null,
          ordinal: 1,
        },
      ],
    });

    expect(
      summarizeResources(
        [readyDocumentNode, processingDocumentNode, failedDocumentNode, responseNode],
        [readyDocumentNode, responseNode],
      ),
    ).toEqual({
      documents: 3,
      readyDocuments: 1,
      processingDocuments: 1,
      failedDocuments: 1,
      selectedItems: 2,
      citations: 1,
      responses: 1,
    });
  });

  it("uses real processing stage labels without invented percentages", () => {
    expect(documentStageDetails.indexing.label).toBe("Updating retrieval index");
    expect(documentStageDetails.indexing.userAction).not.toContain("%");
    expect(documentStageDetails.failed.failed).toBe(true);
  });
});
