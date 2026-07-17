import { z } from "zod";

export const canvasNodeTypeSchema = z.enum(["note", "ai_response", "document"]);
export const canvasEdgeKindSchema = z.enum(["default", "generated_from", "cites"]);

export const pointSchema = z.object({
  x: z.number().finite(),
  y: z.number().finite(),
});

export const viewportSchema = pointSchema.extend({
  zoom: z.number().finite().positive().max(8),
});

const timestampSchema = z.string().datetime({ offset: true });

export const documentFileTypeSchema = z.enum(["pdf", "txt", "markdown", "docx"]);
export const documentStatusSchema = z.enum(["processing", "ready", "failed"]);
export const documentProcessingStageSchema = z.enum([
  "uploading",
  "extracting",
  "chunking",
  "embedding",
  "ready",
  "failed",
]);

export const documentMetadataSchema = z.object({
  id: z.string().min(1),
  canvasId: z.string().min(1),
  fileName: z.string().min(1).max(255),
  fileType: documentFileTypeSchema,
  mediaType: z.string().min(1).max(255),
  fileSize: z.number().int().nonnegative(),
  pageCount: z.number().int().positive().nullable(),
  status: documentStatusSchema,
  processingStage: documentProcessingStageSchema,
  errorMessage: z.string().max(2_000).nullable(),
  chunkCount: z.number().int().nonnegative(),
  createdAt: timestampSchema,
  updatedAt: timestampSchema,
});

export const citationSchema = z
  .object({
    id: z.string().min(1),
    sourceId: z.string().min(1),
    documentId: z.string().min(1),
    documentTitle: z.string().min(1).max(255),
    chunkId: z.string().min(1),
    pageNumber: z.number().int().positive().nullable(),
    heading: z.string().max(500).nullable(),
    chunkIndex: z.number().int().nonnegative(),
    startOffset: z.number().int().nonnegative(),
    endOffset: z.number().int().positive(),
    excerpt: z.string().min(1).max(4_000),
    claim: z.string().max(4_000).nullable(),
    ordinal: z.number().int().positive(),
  })
  .refine((citation) => citation.endOffset > citation.startOffset, {
    message: "Citation endOffset must be greater than startOffset",
    path: ["endOffset"],
  });

export const canvasSchema = z.object({
  id: z.string().min(1),
  name: z.string().min(1).max(120),
  viewport: viewportSchema.default({ x: 0, y: 0, zoom: 1 }),
  revision: z.number().int().nonnegative(),
  createdAt: timestampSchema,
  updatedAt: timestampSchema,
});

export const canvasNodeSchema = z.object({
  id: z.string().min(1),
  canvasId: z.string().min(1),
  type: canvasNodeTypeSchema,
  title: z.string().min(1).max(160),
  text: z.string().max(100_000),
  position: pointSchema,
  width: z.number().finite().min(220).max(1_600),
  height: z.number().finite().min(140).max(1_200),
  revision: z.number().int().nonnegative(),
  document: documentMetadataSchema.nullable().optional(),
  citations: z.array(citationSchema).max(100).optional(),
  createdAt: timestampSchema,
  updatedAt: timestampSchema,
});

export const canvasEdgeSchema = z.object({
  id: z.string().min(1),
  canvasId: z.string().min(1),
  sourceNodeId: z.string().min(1),
  targetNodeId: z.string().min(1),
  kind: canvasEdgeKindSchema,
  label: z.string().max(120).nullable(),
  revision: z.number().int().nonnegative(),
  createdAt: timestampSchema,
  updatedAt: timestampSchema,
});

export const canvasSnapshotSchema = z.object({
  canvas: canvasSchema,
  nodes: z.array(canvasNodeSchema),
  edges: z.array(canvasEdgeSchema),
});

export const createCanvasInputSchema = z
  .object({ name: z.string().trim().min(1, "Name is required").max(120) })
  .strict();

export const createNodeInputSchema = z
  .object({
    type: canvasNodeTypeSchema,
    title: z.string().trim().min(1).max(160),
    text: z.string().max(100_000),
    position: pointSchema,
    width: z.number().min(220).max(1_600),
    height: z.number().min(140).max(1_200),
  })
  .strict();

export const updateNodeInputSchema = z
  .object({
    revision: z.number().int().nonnegative(),
    title: z.string().trim().min(1).max(160).optional(),
    text: z.string().max(100_000).optional(),
    position: pointSchema.optional(),
    width: z.number().min(220).max(1_600).optional(),
    height: z.number().min(140).max(1_200).optional(),
  })
  .strict();

export const createEdgeInputSchema = z
  .object({
    sourceNodeId: z.string().min(1),
    targetNodeId: z.string().min(1),
    kind: canvasEdgeKindSchema.default("default"),
    label: z.string().trim().max(120).nullable().default(null),
  })
  .strict()
  .refine((edge) => edge.sourceNodeId !== edge.targetNodeId, {
    message: "A node cannot connect to itself",
    path: ["targetNodeId"],
  });

export const askAIInputSchema = z
  .object({
    instruction: z.string().trim().min(1, "Enter a question or instruction").max(8_000),
    selectedNodeIds: z.array(z.string().min(1)).min(1, "Select at least one node").max(50),
  })
  .strict()
  .refine((request) => new Set(request.selectedNodeIds).size === request.selectedNodeIds.length, {
    message: "Selected nodes must be unique",
    path: ["selectedNodeIds"],
  });

export const aiResultSchema = z.object({
  requestId: z.string().min(1),
  responseId: z.string().min(1),
  node: canvasNodeSchema,
  edges: z.array(canvasEdgeSchema),
  mock: z.boolean(),
  grounded: z.boolean().default(false),
  insufficientEvidence: z.boolean().default(false),
  citations: z.array(citationSchema).max(100).default([]),
});

export const documentUploadResultSchema = z.object({
  document: documentMetadataSchema,
  node: canvasNodeSchema,
});

export const documentTextSectionSchema = z.object({
  pageNumber: z.number().int().positive().nullable(),
  heading: z.string().max(500).nullable(),
  startOffset: z.number().int().nonnegative(),
  endOffset: z.number().int().nonnegative(),
});

export const documentTextSchema = z.object({
  documentId: z.string().min(1),
  fileName: z.string().min(1).max(255),
  text: z.string().max(10_000_000),
  sections: z.array(documentTextSectionSchema),
});

export const sourcePassageSchema = z.object({
  documentId: z.string().min(1),
  chunkId: z.string().min(1),
  documentTitle: z.string().min(1).max(255),
  pageNumber: z.number().int().positive().nullable(),
  heading: z.string().max(500).nullable(),
  chunkIndex: z.number().int().nonnegative(),
  startOffset: z.number().int().nonnegative(),
  endOffset: z.number().int().nonnegative(),
  text: z.string().min(1).max(100_000),
});

export const documentSearchInputSchema = z
  .object({
    query: z.string().trim().min(1).max(8_000),
    documentIds: z.array(z.string().min(1)).min(1).max(50),
    topK: z.number().int().min(1).max(20).optional(),
    minRelevance: z.number().min(-1).max(1).optional(),
  })
  .strict()
  .refine((input) => new Set(input.documentIds).size === input.documentIds.length, {
    message: "Selected documents must be unique",
    path: ["documentIds"],
  });

export const documentSearchResultSchema = z.object({
  query: z.string(),
  matches: z.array(sourcePassageSchema.extend({ score: z.number().min(-1).max(1) })),
  insufficientContext: z.boolean(),
});

export const problemDetailsSchema = z
  .object({
    title: z.string().optional(),
    detail: z
      .union([
        z.string(),
        z.array(z.unknown()),
        z.object({ code: z.string().optional(), message: z.string().optional() }).passthrough(),
      ])
      .optional(),
    status: z.number().int().optional(),
    code: z.string().optional(),
    requestId: z.string().optional(),
  })
  .passthrough();

export const runtimeModeSchema = z.object({
  mode: z.enum(["live", "deterministic_replay"]),
  externalAiEnabled: z.boolean(),
  label: z.string().min(1),
  demoCanvasId: z.string().uuid().nullable(),
  demoTraceId: z.string().uuid().nullable(),
});

export type Canvas = z.infer<typeof canvasSchema>;
export type CanvasNode = z.infer<typeof canvasNodeSchema>;
export type CanvasNodeType = z.infer<typeof canvasNodeTypeSchema>;
export type CanvasEdge = z.infer<typeof canvasEdgeSchema>;
export type CanvasEdgeKind = z.infer<typeof canvasEdgeKindSchema>;
export type CanvasSnapshot = z.infer<typeof canvasSnapshotSchema>;
export type CreateNodeInput = z.infer<typeof createNodeInputSchema>;
export type UpdateNodeInput = z.infer<typeof updateNodeInputSchema>;
export type CreateEdgeInput = z.infer<typeof createEdgeInputSchema>;
export type AskAIInput = z.infer<typeof askAIInputSchema>;
export type AIResult = z.infer<typeof aiResultSchema>;
export type Point = z.infer<typeof pointSchema>;
export type Citation = z.infer<typeof citationSchema>;
export type DocumentFileType = z.infer<typeof documentFileTypeSchema>;
export type DocumentMetadata = z.infer<typeof documentMetadataSchema>;
export type DocumentProcessingStage = z.infer<typeof documentProcessingStageSchema>;
export type DocumentText = z.infer<typeof documentTextSchema>;
export type SourcePassage = z.infer<typeof sourcePassageSchema>;
export type DocumentSearchInput = z.infer<typeof documentSearchInputSchema>;
export type DocumentSearchResult = z.infer<typeof documentSearchResultSchema>;
export type RuntimeMode = z.infer<typeof runtimeModeSchema>;

export const DEFAULT_NODE_SIZE = { width: 320, height: 240 } as const;

export function createNodeDraft(position: Point): CreateNodeInput {
  return {
    type: "note",
    title: "Untitled note",
    text: "",
    position,
    ...DEFAULT_NODE_SIZE,
  };
}

export function buildAIRequest(
  instruction: string,
  selectedNodes: readonly CanvasNode[],
): AskAIInput {
  return askAIInputSchema.parse({
    instruction,
    selectedNodeIds: selectedNodes.map((node) => node.id),
  });
}
