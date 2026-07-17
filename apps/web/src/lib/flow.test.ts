import { describe, expect, it } from "vitest";

import type { CanvasEdge, CanvasNode } from "./contracts";
import {
  removeDocumentCitations,
  removeResponseCitationEdges,
  selectedCanvasNodes,
  toFlowEdge,
  toFlowNode,
} from "./flow";

function domainNode(id: string): CanvasNode {
  return {
    id,
    canvasId: "canvas-1",
    type: "note",
    title: id,
    text: "Context",
    position: { x: 0, y: 0 },
    width: 320,
    height: 240,
    revision: 0,
    createdAt: "2026-07-16T18:00:00Z",
    updatedAt: "2026-07-16T18:00:00Z",
  };
}

function domainEdge(id: string, kind: CanvasEdge["kind"]): CanvasEdge {
  return {
    id,
    canvasId: "canvas-1",
    sourceNodeId: "answer",
    targetNodeId: "source",
    kind,
    label: null,
    revision: 0,
    createdAt: "2026-07-16T18:00:00Z",
    updatedAt: "2026-07-16T18:00:00Z",
  };
}

describe("React Flow adapters", () => {
  it("returns every selected persisted node in visual order", () => {
    const first = toFlowNode(domainNode("one"), { selected: true });
    const ignored = toFlowNode(domainNode("two"));
    const third = toFlowNode(domainNode("three"), { selected: true });

    expect(selectedCanvasNodes([first, ignored, third]).map((node) => node.id)).toEqual([
      "one",
      "three",
    ]);
  });

  it("never includes temporary nodes in AI context", () => {
    const pending = toFlowNode(domainNode("temp-note"), {
      pending: true,
      selected: true,
    });

    expect(selectedCanvasNodes([pending])).toEqual([]);
  });

  it("removes citation badges that point to a deleted document", () => {
    const response = toFlowNode({
      ...domainNode("answer"),
      type: "ai_response",
      citations: [
        {
          id: "citation-a",
          sourceId: "chunk-a",
          documentId: "document-a",
          documentTitle: "A.pdf",
          chunkId: "chunk-a",
          chunkIndex: 0,
          startOffset: 0,
          endOffset: 6,
          pageNumber: 1,
          heading: null,
          excerpt: "Fact A",
          claim: "Claim A",
          ordinal: 1,
        },
        {
          id: "citation-b",
          sourceId: "chunk-b",
          documentId: "document-b",
          documentTitle: "B.pdf",
          chunkId: "chunk-b",
          chunkIndex: 0,
          startOffset: 0,
          endOffset: 6,
          pageNumber: 2,
          heading: null,
          excerpt: "Fact B",
          claim: "Claim B",
          ordinal: 2,
        },
      ],
    });

    const [cleaned] = removeDocumentCitations([response], new Set(["document-a"]));

    expect(cleaned?.data.node.citations).toHaveLength(1);
    expect(cleaned?.data.node.citations?.[0]?.documentId).toBe("document-b");
  });

  it("removes only outgoing citation edges when a response is edited", () => {
    const cite = toFlowEdge(domainEdge("cite", "cites"));
    const generated = toFlowEdge(domainEdge("generated", "generated_from"));

    expect(removeResponseCitationEdges([cite, generated], "answer").map((edge) => edge.id)).toEqual(
      ["generated"],
    );
  });
});
