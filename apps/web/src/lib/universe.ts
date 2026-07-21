import type {
  Canvas,
  CanvasEdgeKind,
  CanvasNode,
  Citation,
  DocumentMetadata,
  DocumentProcessingStage,
  Workspace,
} from "./contracts";

export type UniverseLevel =
  | "universe"
  | "galaxy"
  | "solar_system"
  | "star"
  | "planet"
  | "moon"
  | "asteroid"
  | "person"
  | "vegetation"
  | "wildlife"
  | "society";

export interface UniverseRole {
  level: UniverseLevel;
  label: string;
  plainLabel: string;
  description: string;
}

export interface ResourceSummary {
  documents: number;
  readyDocuments: number;
  processingDocuments: number;
  failedDocuments: number;
  selectedItems: number;
  citations: number;
  responses: number;
}

export const universeRole: UniverseRole = {
  level: "universe",
  label: "Universe",
  plainLabel: "Universe · SolarPlexus Mobius",
  description: "Application-level navigation, runtime state, account controls, and health.",
};

export function workspaceRole(workspace: Pick<Workspace, "name">): UniverseRole {
  return {
    level: "galaxy",
    label: "Galaxy · Workspace",
    plainLabel: `Galaxy · Workspace · ${workspace.name}`,
    description: "A user-owned workspace containing isolated canvases, sources, and evidence.",
  };
}

export function canvasRole(canvas: Pick<Canvas, "name">): UniverseRole {
  return {
    level: "solar_system",
    label: "Solar System",
    plainLabel: `Solar System · ${canvas.name}`,
    description: "A focused project cluster built from real canvas objects and relationships.",
  };
}

export function nodeRole(node: CanvasNode): UniverseRole {
  if (node.type === "document") {
    return {
      level: "planet",
      label: "Planet · Document",
      plainLabel: `Planet · Document · ${node.document?.fileName ?? node.title}`,
      description: "A durable source object with extraction, chunking, and retrieval state.",
    };
  }

  if (node.type === "ai_response") {
    return {
      level: "star",
      label: "Star · Answer Hub",
      plainLabel: `Star · Answer Hub · ${node.title}`,
      description: "An answer node connected to selected context, claims, citations, and Trace.",
    };
  }

  return {
    level: "moon",
    label: "Moon · Supporting Note",
    plainLabel: `Moon · Supporting Note · ${node.title}`,
    description: "A user-authored supporting note that can become controlled context.",
  };
}

export function citationRole(citation: Pick<Citation, "ordinal" | "documentTitle">): UniverseRole {
  return {
    level: "asteroid",
    label: "Asteroid · Evidence Fragment",
    plainLabel: `Asteroid · Evidence Fragment · Citation ${citation.ordinal}`,
    description: `A validated passage from ${citation.documentTitle}.`,
  };
}

export const edgeKindDetails: Record<
  CanvasEdgeKind,
  {
    label: string;
    legendLabel: string;
    plainLabel: string;
    description: string;
    className: string;
  }
> = {
  default: {
    label: "Pathway · Relationship",
    legendLabel: "Relationship",
    plainLabel: "Pathway · User-created relationship",
    description: "A user-created relationship between two canvas objects.",
    className: "canvas-edge--relationship",
  },
  generated_from: {
    label: "Pathway · Context inclusion",
    legendLabel: "Selected context",
    plainLabel: "Pathway · Generated from selected context",
    description: "A response was generated from this selected context item.",
    className: "canvas-edge--context",
  },
  cites: {
    label: "Pathway · Citation",
    legendLabel: "Citation",
    plainLabel: "Pathway · Citation to exact source passage",
    description: "A validated citation links an answer to the exact source passage.",
    className: "canvas-edge--citation",
  },
};

export const documentStageDetails: Record<
  DocumentProcessingStage,
  { label: string; userAction: string; active: boolean; failed: boolean }
> = {
  uploading: {
    label: "Uploading source",
    userAction: "Keep this page open until the file is accepted.",
    active: true,
    failed: false,
  },
  queued: {
    label: "Queued for processing",
    userAction: "The worker has not started this source yet.",
    active: true,
    failed: false,
  },
  validating: {
    label: "Validating file",
    userAction: "Checking type, size, and safety limits.",
    active: true,
    failed: false,
  },
  extracting: {
    label: "Extracting text",
    userAction: "Reading usable text from the stored file.",
    active: true,
    failed: false,
  },
  chunking: {
    label: "Building passages",
    userAction: "Creating source passages for retrieval and citations.",
    active: true,
    failed: false,
  },
  embedding: {
    label: "Creating embeddings",
    userAction: "Preparing retrieval vectors for this source.",
    active: true,
    failed: false,
  },
  indexing: {
    label: "Updating retrieval index",
    userAction: "Making ready passages available to selected-context search.",
    active: true,
    failed: false,
  },
  ready: {
    label: "Ready source",
    userAction: "Available for controlled context and citations.",
    active: false,
    failed: false,
  },
  retrying: {
    label: "Retry queued",
    userAction: "A retry is scheduled or in progress.",
    active: true,
    failed: false,
  },
  deleting: {
    label: "Deleting source",
    userAction: "Removing file content, chunks, and retrieval entries.",
    active: true,
    failed: false,
  },
  deleted: {
    label: "Deleted source",
    userAction: "This source is no longer searchable.",
    active: false,
    failed: false,
  },
  failed: {
    label: "Processing failed",
    userAction: "Review the failure and retry or replace the source.",
    active: false,
    failed: true,
  },
};

export function summarizeResources(
  nodes: readonly CanvasNode[],
  selectedNodes: readonly CanvasNode[] = [],
): ResourceSummary {
  const documents = nodes.flatMap((node) => (node.document ? [node.document] : []));
  return {
    documents: documents.length,
    readyDocuments: documents.filter((document) => document.status === "ready").length,
    processingDocuments: documents.filter(isProcessingDocument).length,
    failedDocuments: documents.filter(isFailedDocument).length,
    selectedItems: selectedNodes.length,
    citations: nodes.reduce((count, node) => count + (node.citations?.length ?? 0), 0),
    responses: nodes.filter((node) => node.type === "ai_response").length,
  };
}

export function isProcessingDocument(document: DocumentMetadata): boolean {
  return ["uploaded", "queued", "processing", "retrying", "deleting"].includes(document.status);
}

export function isFailedDocument(document: DocumentMetadata): boolean {
  return ["failed", "retryable_failure", "permanent_failure"].includes(document.status);
}
