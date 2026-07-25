import { z } from "zod";

import { canvasEdgeSchema, canvasNodeSchema, canvasSchema, pointSchema } from "./contracts";

const timestamp = z.string().datetime({ offset: true });
const uuid = z.string().uuid();

export const universeBoundaryNodeSchema = z.object({
  id: uuid,
  type: z.enum(["note", "ai_response", "document"]),
  title: z.string().min(1).max(160),
  position: pointSchema,
});

export const universeViewportSchema = z.object({
  canvas: canvasSchema,
  canvasRevision: z.number().int().nonnegative(),
  graphRevision: z.number().int().nonnegative(),
  nodes: z.array(canvasNodeSchema).max(200),
  edges: z.array(canvasEdgeSchema).max(500),
  boundaryNodes: z.array(universeBoundaryNodeSchema).max(1_000),
  selectedNodes: z.array(canvasNodeSchema).max(50),
  nextCursor: uuid.nullable(),
  bounded: z.boolean(),
});

export const graphRelationshipTypeSchema = z.enum([
  "references",
  "derived_from",
  "related_to",
  "cites",
  "supports",
  "contradicts",
  "produced_by",
  "affected_by",
]);
export const graphHistoryStateSchema = z.enum(["active", "inactive", "superseded", "rejected"]);
const graphEntityReferenceSchema = z.object({
  kind: z.enum(["document", "note", "execution"]),
  objectId: uuid,
});
export const graphRelationshipSchema = z
  .object({
    relationshipId: uuid,
    relationshipType: graphRelationshipTypeSchema,
    source: graphEntityReferenceSchema,
    target: graphEntityReferenceSchema,
    userId: uuid,
    workspaceId: uuid,
    canvasId: uuid,
    version: z.number().int().positive(),
    lifecycleState: z.string().min(1),
    graphRevision: z.number().int().positive(),
    canonicalDigest: z.string().regex(/^[a-f0-9]{64}$/i),
    currentState: graphHistoryStateSchema,
    provenance: z.object({
      provenanceId: uuid,
      originType: z.enum([
        "user_created",
        "imported_canonical",
        "citation_derived",
        "controlled_agent_approved",
        "deterministic_rule",
      ]),
      actorUserId: uuid,
      executionId: uuid.nullable(),
      sourceReferenceId: uuid.nullable(),
      ruleId: z.string().nullable(),
      ruleVersion: z.string().nullable(),
      traceId: uuid,
      provenanceDigest: z.string().regex(/^[a-f0-9]{64}$/i),
      createdAt: timestamp,
    }),
    createdAt: timestamp,
    replayed: z.boolean().default(false),
  })
  .refine((relationship) => relationship.source.objectId !== relationship.target.objectId, {
    message: "Knowledge graph self-links are not supported",
    path: ["target", "objectId"],
  });

export const retrievalDecisionSchema = z.object({
  decisionId: uuid,
  objectId: uuid,
  relationshipId: uuid.nullable(),
  included: z.boolean(),
  reasonCode: z.string().min(1).max(80),
  distance: z.number().int().nonnegative(),
  rank: z.number().int().positive().nullable(),
  score: z.number().finite().nullable(),
  relationshipPath: z.array(uuid).max(64),
});
export const retrievalCitationSchema = z.object({
  citationId: uuid,
  canonicalObjectId: uuid,
  canonicalVersion: z.number().int().positive(),
  sourceVersion: z.number().int().positive(),
  sourceSha256: z.string().regex(/^[a-f0-9]{64}$/i),
  sourceTitle: z.string().min(1),
  sourceType: z.string().min(1),
  passageIdentity: z.string().min(1),
  excerpt: z.string(),
  excerptSha256: z.string().regex(/^[a-f0-9]{64}$/i),
  locator: z.record(z.string(), z.unknown()),
  relationshipPath: z.array(uuid).max(64),
  graphRevision: z.number().int().nonnegative(),
  ordinal: z.number().int().positive(),
  citationSchemaVersion: z.string().min(1),
  traceId: uuid,
});
export const graphRetrievalSchema = z.object({
  retrievalId: uuid,
  workspaceId: uuid,
  canvasId: uuid,
  query: z.string(),
  selectedObjectIds: z.array(uuid).max(50),
  seedObjectIds: z.array(uuid).max(50),
  graphRevision: z.number().int().nonnegative(),
  algorithmVersion: z.string().min(1),
  schemaVersion: z.string().min(1),
  mode: z.literal("selected_graph"),
  outcome: z.enum(["supported", "conflicting_evidence", "insufficient_evidence", "bounded_result"]),
  bounded: z.boolean(),
  traceId: uuid,
  createdAt: timestamp,
  duplicate: z.boolean(),
  decisions: z.array(retrievalDecisionSchema).max(1_000),
  citations: z.array(retrievalCitationSchema).max(100),
});

export const apaRenderSchema = z.object({
  rendererVersion: z.string().min(1),
  citations: z
    .array(z.object({ citationId: uuid, inText: z.string(), reference: z.string() }))
    .max(100),
});
export const retrievalTraceSummarySchema = z.object({
  traceId: uuid,
  statuses: z.array(z.string()).max(500),
  eventTypes: z.array(z.string()).max(500),
  safeMetadata: z.array(z.record(z.string(), z.unknown())).max(500),
});
export const evidenceBundleSchema = z.object({
  bundleId: uuid,
  retrievalId: uuid,
  schemaVersion: z.string().min(1),
  state: z.string().min(1),
  artifactSha256: z
    .string()
    .regex(/^[a-f0-9]{64}$/i)
    .nullable(),
  byteSize: z.number().int().nonnegative().max(100_000_000),
  manifest: z.record(z.string(), z.unknown()),
  traceId: uuid,
  createdAt: timestamp,
});

export const workflowStepStatusSchema = z.enum([
  "pending",
  "blocked",
  "awaiting_approval",
  "ready",
  "claimed",
  "running",
  "succeeded",
  "retry_waiting",
  "failed",
  "canceled",
  "compensating",
  "compensated",
  "compensation_failed",
  "skipped",
]);
export const workflowStepSchema = z.object({
  stepExecutionId: uuid,
  stepKey: z.string().min(1),
  stepType: z.string().min(1),
  dependsOn: z.array(z.string()).max(31),
  capability: z.string().min(1),
  riskClass: z.enum(["r0_observation", "r1_draft", "r2_transient_action", "r3_durable_write"]),
  requestedAction: z.string().nullable(),
  affectedResourceId: uuid.nullable(),
  status: workflowStepStatusSchema,
  attemptCount: z.number().int().nonnegative(),
  maxAttempts: z.number().int().positive().max(4),
  approvalRequired: z.boolean(),
  controlledExecutionId: uuid.nullable(),
  approvalId: uuid.nullable(),
  retrievalId: uuid.nullable(),
  evidenceBundleId: uuid.nullable(),
  effectId: uuid.nullable(),
  rollbackResultId: uuid.nullable(),
  safeFailureClass: z.string().nullable(),
  outputDigest: z.string().nullable(),
  startedAt: timestamp.nullable(),
  completedAt: timestamp.nullable(),
});
export const workflowExecutionSchema = z.object({
  executionId: uuid,
  definitionId: uuid,
  versionId: uuid,
  workspaceId: uuid,
  canvasId: uuid,
  status: z.enum([
    "requested",
    "planned",
    "awaiting_approval",
    "ready",
    "running",
    "cancel_requested",
    "canceling",
    "compensating",
    "completed",
    "failed",
    "canceled",
    "compensated",
    "compensation_failed",
  ]),
  outcome: z.string().nullable(),
  planId: uuid,
  planDigest: z.string().regex(/^[a-f0-9]{64}$/i),
  inputDigest: z.string().regex(/^[a-f0-9]{64}$/i),
  graphRevision: z.number().int().nonnegative(),
  selectedObjectIds: z.array(uuid).max(50),
  output: z.record(z.string(), z.unknown()).nullable(),
  outputDigest: z.string().nullable(),
  traceId: uuid,
  createdAt: timestamp,
  deadlineAt: timestamp,
  cancelRequestedAt: timestamp.nullable(),
  completedAt: timestamp.nullable(),
  steps: z.array(workflowStepSchema).max(32),
  duplicate: z.boolean(),
});

export const activitySchema = z.object({
  eventId: uuid,
  eventType: z.string().min(1),
  sequence: z.number().int().positive(),
  workspaceId: uuid,
  canvasId: uuid.nullable(),
  subjectKind: z.string().min(1),
  subjectId: uuid,
  actorUserId: uuid,
  executionId: uuid.nullable(),
  graphRevision: z.number().int().positive().nullable(),
  traceId: uuid,
  occurredAt: timestamp,
  status: z.enum([
    "pending_delivery",
    "actively_delivering",
    "delivered",
    "retry_waiting",
    "terminal_delivery_failure",
  ]),
  projected: z.boolean(),
});

export type UniverseViewport = z.infer<typeof universeViewportSchema>;
export type GraphRelationship = z.infer<typeof graphRelationshipSchema>;
export type GraphRetrieval = z.infer<typeof graphRetrievalSchema>;
export type RetrievalCitation = z.infer<typeof retrievalCitationSchema>;
export type ApaRender = z.infer<typeof apaRenderSchema>;
export type RetrievalTraceSummary = z.infer<typeof retrievalTraceSummarySchema>;
export type EvidenceBundle = z.infer<typeof evidenceBundleSchema>;
export type WorkflowExecution = z.infer<typeof workflowExecutionSchema>;
export type WorkflowStep = z.infer<typeof workflowStepSchema>;
export type Activity = z.infer<typeof activitySchema>;
