import { describe, expect, it } from "vitest";

import {
  aiResultSchema,
  askAIInputSchema,
  buildAIRequest,
  canvasNodeSchema,
  citationSchema,
  createNodeDraft,
  documentSearchInputSchema,
  type CanvasNode,
} from "./contracts";

const selectedNode: CanvasNode = {
  id: "node-1",
  canvasId: "canvas-1",
  type: "note",
  title: "Product brief",
  text: "Build a spatial workspace.",
  position: { x: 40, y: 80 },
  width: 320,
  height: 240,
  revision: 0,
  createdAt: "2026-07-16T18:00:00Z",
  updatedAt: "2026-07-16T18:00:00Z",
};

describe("canvas contracts", () => {
  it("creates a production-sized text note draft", () => {
    expect(createNodeDraft({ x: 40, y: 80 })).toEqual({
      type: "note",
      title: "Untitled note",
      text: "",
      position: { x: 40, y: 80 },
      width: 320,
      height: 240,
    });
  });

  it("constructs AI context from selected nodes in selection order", () => {
    const second = { ...selectedNode, id: "node-2", title: "Research" };

    expect(buildAIRequest("Find the shared theme", [selectedNode, second])).toEqual({
      instruction: "Find the shared theme",
      selectedNodeIds: ["node-1", "node-2"],
    });
  });

  it("rejects invalid AI requests before they reach the server", () => {
    expect(() => askAIInputSchema.parse({ instruction: "", selectedNodeIds: [] })).toThrow();
  });

  it("accepts document nodes with processing metadata", () => {
    const documentNode = canvasNodeSchema.parse({
      ...selectedNode,
      id: "document-node-1",
      type: "document",
      title: "facts.pdf",
      text: "",
      document: {
        id: "document-1",
        canvasId: "canvas-1",
        fileName: "facts.pdf",
        fileType: "pdf",
        mediaType: "application/pdf",
        fileSize: 1_024,
        pageCount: 2,
        status: "processing",
        processingStage: "embedding",
        errorMessage: null,
        chunkCount: 4,
        createdAt: "2026-07-16T18:00:00Z",
        updatedAt: "2026-07-16T18:00:00Z",
      },
    });

    expect(documentNode.document?.processingStage).toBe("embedding");
  });

  it("validates citations and rejects nonexistent source identifiers", () => {
    const valid = {
      id: "citation-1",
      sourceId: "S1",
      documentId: "document-1",
      documentTitle: "facts.pdf",
      chunkId: "chunk-1",
      chunkIndex: 1,
      startOffset: 90,
      endOffset: 140,
      pageNumber: 2,
      heading: null,
      excerpt: "The launch date is October 14.",
      claim: "The launch date is October 14.",
      ordinal: 1,
    };

    expect(citationSchema.parse(valid).sourceId).toBe("S1");
    expect(() => citationSchema.parse({ ...valid, chunkId: "" })).toThrow();
    expect(() => citationSchema.parse({ ...valid, endOffset: 90 })).toThrow();
    expect(() =>
      aiResultSchema.parse({
        requestId: "request-1",
        responseId: "response-1",
        node: { ...selectedNode, type: "ai_response" },
        edges: [],
        mock: true,
        grounded: true,
        insufficientEvidence: false,
        citations: [{ ...valid, sourceId: "" }],
      }),
    ).toThrow();
  });

  it("requires search to remain scoped to unique selected documents", () => {
    expect(
      documentSearchInputSchema.parse({ query: "launch date", documentIds: ["document-1"] }),
    ).toEqual({ query: "launch date", documentIds: ["document-1"] });
    expect(() =>
      documentSearchInputSchema.parse({
        query: "launch date",
        documentIds: ["document-1", "document-1"],
      }),
    ).toThrow();
  });
});
