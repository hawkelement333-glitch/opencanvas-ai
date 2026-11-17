import { MarkerType, type Edge, type Node } from "@xyflow/react";

import type { CanvasEdge, CanvasNode, Citation, SecureUpload } from "./contracts";
import { edgeKindDetails } from "./universe";

export type CanvasNodeData = Record<string, unknown> & {
  node: CanvasNode;
  pending: boolean;
  secureUploadRequired?: boolean;
  secureUpload?: SecureUpload;
  secureUploadRefreshFailed?: boolean;
};

export type CanvasFlowNode = Node<CanvasNodeData, "canvasCard" | "documentCard">;
export type CanvasFlowEdge = Edge<Record<string, unknown> & { edge: CanvasEdge }>;

export interface NodeHandlers {
  onTitleChange: (nodeId: string, title: string) => void;
  onTextChange: (nodeId: string, text: string) => void;
  onDuplicate: (nodeId: string) => void;
  onDelete: (nodeId: string) => void;
  onSelect: (nodeId: string, additive: boolean) => void;
  onPreviewDocument: (nodeId: string) => void;
  onRetryDocument: (nodeId: string) => void;
  onDeleteDocument: (nodeId: string) => void;
  onOpenCitation: (citation: Citation) => void;
}

export function toFlowNode(
  node: CanvasNode,
  options: { pending?: boolean; selected?: boolean } = {},
): CanvasFlowNode {
  return {
    id: node.id,
    type: node.type === "document" ? "documentCard" : "canvasCard",
    position: node.position,
    selected: options.selected ?? false,
    style: { width: node.width, height: node.height },
    data: {
      node,
      pending: options.pending ?? false,
    },
  };
}

export function toFlowEdge(edge: CanvasEdge): CanvasFlowEdge {
  const isCitation = edge.kind === "cites";
  const details = edgeKindDetails[edge.kind];
  return {
    id: edge.id,
    source: edge.sourceNodeId,
    target: edge.targetNodeId,
    label: edge.label ?? details.label,
    type: "smoothstep",
    animated: edge.kind === "generated_from",
    markerEnd: { type: MarkerType.ArrowClosed, width: 18, height: 18 },
    className: details.className,
    style: isCitation ? { stroke: "#61c4d6", strokeDasharray: "5 5", strokeWidth: 1.6 } : undefined,
    data: { edge },
  };
}

export function selectedCanvasNodes(nodes: readonly CanvasFlowNode[]): CanvasNode[] {
  return nodes.filter((node) => node.selected && !node.data.pending).map((node) => node.data.node);
}

export function upsertFlowNode(
  nodes: readonly CanvasFlowNode[],
  incoming: CanvasFlowNode,
): CanvasFlowNode[] {
  const index = nodes.findIndex((node) => node.id === incoming.id);
  if (index === -1) return [...nodes, incoming];
  return nodes.map((node) => (node.id === incoming.id ? incoming : node));
}

export function upsertFlowEdges(
  edges: readonly CanvasFlowEdge[],
  incoming: readonly CanvasFlowEdge[],
): CanvasFlowEdge[] {
  const replacements = new Map(incoming.map((edge) => [edge.id, edge]));
  const retained = edges.map((edge) => replacements.get(edge.id) ?? edge);
  const existing = new Set(edges.map((edge) => edge.id));
  return [...retained, ...incoming.filter((edge) => !existing.has(edge.id))];
}

export function removeDocumentCitations(
  nodes: readonly CanvasFlowNode[],
  deletedDocumentIds: ReadonlySet<string>,
): CanvasFlowNode[] {
  if (deletedDocumentIds.size === 0) return [...nodes];
  return nodes.map((node) => {
    const citations = node.data.node.citations ?? [];
    const retained = citations.filter((citation) => !deletedDocumentIds.has(citation.documentId));
    const provenance = node.data.node.draftProvenance;
    const availableOriginalCitations = provenance?.citations.filter(
      (citation) => !deletedDocumentIds.has(citation.documentId),
    );
    if (
      retained.length === citations.length &&
      availableOriginalCitations?.length === provenance?.citations.length
    )
      return node;
    return {
      ...node,
      data: {
        ...node.data,
        node: {
          ...node.data.node,
          citations: retained,
          // Remove unavailable navigation only; immutable evidence remains server-owned.
          draftProvenance: provenance
            ? { ...provenance, citations: availableOriginalCitations ?? [] }
            : provenance,
        },
      },
    };
  });
}

export function removeResponseCitationEdges(
  edges: readonly CanvasFlowEdge[],
  responseNodeId: string,
): CanvasFlowEdge[] {
  return edges.filter(
    (edge) => !(edge.source === responseNodeId && edge.data?.edge.kind === "cites"),
  );
}

/** Admit one saved derivative without replacing concurrent local canvas work. */
export function admitSavedDraftArtifact(
  nodes: readonly CanvasFlowNode[],
  edges: readonly CanvasFlowEdge[],
  saved: CanvasNode,
  refreshedEdges: readonly CanvasEdge[],
): { nodes: CanvasFlowNode[]; edges: CanvasFlowEdge[] } {
  const current = nodes.map((node) => ({ ...node, selected: false }));
  const existing = current.find((node) => node.id === saved.id);
  const next = upsertFlowNode(
    current,
    existing ? { ...existing, selected: true } : toFlowNode(saved, { selected: true }),
  );
  // A duplicate save only selects the existing local artifact. It cannot restore
  // links the user has removed or overwrite pending local edits with a snapshot.
  if (existing) return { nodes: next, edges: [...edges] };
  const ids = new Set(next.map((node) => node.id));
  const edgeIds = new Set(edges.map((edge) => edge.id));
  const createdEdges = refreshedEdges.filter(
    (edge) =>
      !edgeIds.has(edge.id) &&
      (edge.sourceNodeId === saved.id || edge.targetNodeId === saved.id) &&
      ids.has(edge.sourceNodeId) &&
      ids.has(edge.targetNodeId),
  );
  return { nodes: next, edges: [...edges, ...createdEdges.map(toFlowEdge)] };
}
