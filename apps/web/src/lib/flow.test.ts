import { describe, expect, it } from "vitest";

import type { CanvasEdge, CanvasNode } from "./contracts";
import {
  admitSavedDraftArtifact,
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

describe("saved draft citation availability", () => {
  it("removes deleted-source navigation without mutating original evidence or edited content", () => {
    const citation = {
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
    };
    const original = {
      executionId: "exec",
      responseId: "response",
      traceId: "trace",
      originalText: "Original text",
      edited: true,
      insufficientEvidence: false,
      citations: [citation],
    };
    const flowNode = toFlowNode({
      ...domainNode("answer"),
      type: "ai_response",
      text: "User edit",
      draftProvenance: original,
    });
    const [cleaned] = removeDocumentCitations([flowNode], new Set(["document-a"]));
    expect(cleaned?.data.node.text).toBe("User edit");
    expect(cleaned?.data.node.draftProvenance).toEqual({ ...original, citations: [] });
    expect(original.citations).toEqual([citation]);
  });
});

describe("explicit artifact admission preserves concurrent local work", () => {
  it("keeps newer text, local additions and edges, and excludes links to deleted nodes", () => {
    const local = toFlowNode({ ...domainNode("source"), text: "Newer unsaved text" });
    const newlyAdded = toFlowNode(domainNode("added-during-save"));
    const localEdge = toFlowEdge({
      ...domainEdge("local", "default"),
      sourceNodeId: "source",
      targetNodeId: "added-during-save",
      label: "New local edge",
    });
    const created = { ...domainNode("saved"), type: "ai_response" as const };
    const generated = {
      ...domainEdge("generated", "generated_from"),
      sourceNodeId: "source",
      targetNodeId: "saved",
    };
    const deletedSourceEdge = {
      ...generated,
      id: "deleted-source-edge",
      sourceNodeId: "deleted-during-save",
    };
    const unrelatedSnapshotEdge = {
      ...generated,
      id: "unrelated",
      sourceNodeId: "source",
      targetNodeId: "added-during-save",
    };
    const merged = admitSavedDraftArtifact([local, newlyAdded], [localEdge], created, [
      generated,
      deletedSourceEdge,
      unrelatedSnapshotEdge,
    ]);
    expect(merged.nodes.map((node) => node.id)).toEqual(["source", "added-during-save", "saved"]);
    expect(merged.nodes[0]?.data.node.text).toBe("Newer unsaved text");
    expect(merged.nodes.filter((node) => node.selected).map((node) => node.id)).toEqual(["saved"]);
    expect(merged.edges.map((edge) => edge.id)).toEqual(["local", "generated"]);
    expect(merged.edges[0]).toBe(localEdge);
  });

  it("duplicate save cannot overwrite edits or restore user-removed artifact edges", () => {
    const edited = toFlowNode({ ...domainNode("saved"), text: "User edit in flight" });
    const merged = admitSavedDraftArtifact(
      [edited],
      [],
      { ...domainNode("saved"), text: "Older snapshot" },
      [{ ...domainEdge("old-edge", "generated_from"), targetNodeId: "saved" }],
    );
    expect(merged.nodes).toHaveLength(1);
    expect(merged.nodes[0]?.data.node.text).toBe("User edit in flight");
    expect(merged.edges).toEqual([]);
  });
});
