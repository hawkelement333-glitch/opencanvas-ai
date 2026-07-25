import { describe, expect, it } from "vitest";

import {
  RELATIONSHIP_PRESENTATION,
  canvasEdges,
  normalizeActivity,
  relationshipEdges,
  resourceNodes,
  workflowDag,
} from "./dynamic-universe";
import { graphRelationshipSchema } from "./universe-contracts";
import type { GraphRelationship, UniverseViewport, WorkflowExecution } from "./universe-contracts";

const timestamp = "2026-07-25T18:00:00Z";
const ids = {
  workspace: "10000000-0000-4000-8000-000000000001",
  canvas: "20000000-0000-4000-8000-000000000001",
  source: "30000000-0000-4000-8000-000000000001",
  target: "40000000-0000-4000-8000-000000000001",
  relationship: "50000000-0000-4000-8000-000000000001",
  trace: "60000000-0000-4000-8000-000000000001",
  user: "70000000-0000-4000-8000-000000000001",
  execution: "80000000-0000-4000-8000-000000000001",
  version: "90000000-0000-4000-8000-000000000001",
  definition: "a0000000-0000-4000-8000-000000000001",
  plan: "b0000000-0000-4000-8000-000000000001",
  stepOne: "c0000000-0000-4000-8000-000000000001",
  stepTwo: "d0000000-0000-4000-8000-000000000001",
};

const viewport: UniverseViewport = {
  canvas: {
    id: ids.canvas,
    workspaceId: ids.workspace,
    name: "Universe",
    viewport: { x: 0, y: 0, zoom: 1 },
    revision: 2,
    createdAt: timestamp,
    updatedAt: timestamp,
  },
  canvasRevision: 2,
  graphRevision: 7,
  nodes: [
    {
      id: ids.source,
      canvasId: ids.canvas,
      type: "note",
      title: "Selected note",
      text: "Evidence",
      position: { x: 10, y: 20 },
      width: 320,
      height: 240,
      revision: 1,
      createdAt: timestamp,
      updatedAt: timestamp,
    },
  ],
  edges: [
    {
      id: ids.relationship,
      canvasId: ids.canvas,
      sourceNodeId: ids.source,
      targetNodeId: ids.target,
      kind: "cites",
      label: "exact citation",
      revision: 0,
      createdAt: timestamp,
      updatedAt: timestamp,
    },
  ],
  boundaryNodes: [
    { id: ids.target, type: "document", title: "Boundary source", position: { x: 900, y: 20 } },
  ],
  selectedNodes: [],
  nextCursor: null,
  bounded: true,
};

const relationship: GraphRelationship = {
  relationshipId: ids.relationship,
  relationshipType: "contradicts",
  source: { kind: "note", objectId: ids.source },
  target: { kind: "document", objectId: ids.target },
  userId: ids.user,
  workspaceId: ids.workspace,
  canvasId: ids.canvas,
  version: 1,
  lifecycleState: "active",
  graphRevision: 7,
  canonicalDigest: "a".repeat(64),
  currentState: "superseded",
  provenance: {
    provenanceId: ids.plan,
    originType: "citation_derived",
    actorUserId: ids.user,
    executionId: ids.execution,
    sourceReferenceId: ids.source,
    ruleId: null,
    ruleVersion: null,
    traceId: ids.trace,
    provenanceDigest: "b".repeat(64),
    createdAt: timestamp,
  },
  createdAt: timestamp,
  replayed: false,
};

const workflow: WorkflowExecution = {
  executionId: ids.execution,
  definitionId: ids.definition,
  versionId: ids.version,
  workspaceId: ids.workspace,
  canvasId: ids.canvas,
  status: "awaiting_approval",
  outcome: null,
  planId: ids.plan,
  planDigest: "c".repeat(64),
  inputDigest: "d".repeat(64),
  graphRevision: 7,
  selectedObjectIds: [ids.source],
  output: null,
  outputDigest: null,
  traceId: ids.trace,
  createdAt: timestamp,
  deadlineAt: "2026-07-25T19:00:00Z",
  cancelRequestedAt: null,
  completedAt: null,
  duplicate: false,
  steps: [
    {
      stepExecutionId: ids.stepTwo,
      stepKey: "approve",
      stepType: "human_approval",
      dependsOn: ["retrieve"],
      capability: "workflow.step.execute",
      riskClass: "r2_transient_action",
      requestedAction: "workflow.approval",
      affectedResourceId: null,
      status: "awaiting_approval",
      attemptCount: 0,
      maxAttempts: 1,
      approvalRequired: true,
      controlledExecutionId: null,
      approvalId: ids.plan,
      retrievalId: null,
      evidenceBundleId: null,
      effectId: null,
      rollbackResultId: null,
      safeFailureClass: null,
      outputDigest: null,
      startedAt: null,
      completedAt: null,
    },
    {
      stepExecutionId: ids.stepOne,
      stepKey: "retrieve",
      stepType: "graph_retrieval",
      dependsOn: [],
      capability: "retrieval.selected.search",
      riskClass: "r1_draft",
      requestedAction: null,
      affectedResourceId: null,
      status: "succeeded",
      attemptCount: 1,
      maxAttempts: 2,
      approvalRequired: false,
      controlledExecutionId: null,
      approvalId: null,
      retrievalId: ids.plan,
      evidenceBundleId: null,
      effectId: null,
      rollbackResultId: null,
      safeFailureClass: null,
      outputDigest: "e".repeat(64),
      startedAt: timestamp,
      completedAt: timestamp,
    },
  ],
};

describe("Dynamic Universe view-model adaptation", () => {
  it("keeps selected context separate from graph connection and boundary state", () => {
    const nodes = resourceNodes(viewport, new Set([ids.source]));
    expect(nodes.map((node) => node.id)).toEqual([ids.source, ids.target]);
    expect(nodes[0]?.data.selectedContext).toBe(true);
    expect(nodes[1]?.data.selectedContext).toBe(false);
    expect(nodes[1]?.data.boundary).toBe(true);
    expect(canvasEdges(viewport)[0]).toMatchObject({
      source: ids.source,
      target: ids.target,
      data: { authoritative: true },
    });
  });

  it("maps every closed relationship kind and exposes direction without color", () => {
    expect(Object.keys(RELATIONSHIP_PRESENTATION)).toHaveLength(8);
    expect(RELATIONSHIP_PRESENTATION.related_to.direction).toBe("bidirectional");
    expect(RELATIONSHIP_PRESENTATION.contradicts.direction).toBe("bidirectional");
    expect(RELATIONSHIP_PRESENTATION.cites.direction).toBe("forward");

    const edge = relationshipEdges([relationship])[0];
    expect(edge).toMatchObject({
      source: ids.source,
      target: ids.target,
      label: "contradicts · superseded",
      data: { direction: "bidirectional", historical: true, graphRevision: 7 },
    });
  });

  it("produces a deterministic DAG with dependencies and does not infer completion", () => {
    const first = workflowDag(workflow);
    const second = workflowDag({ ...workflow, steps: [...workflow.steps].reverse() });
    expect(first).toEqual(second);
    expect(first.nodes.map((node) => [node.data.label, node.position])).toEqual([
      ["approve", { x: 280, y: 0 }],
      ["retrieve", { x: 0, y: 0 }],
    ]);
    expect(first.edges).toEqual([
      expect.objectContaining({ source: ids.stepOne, target: ids.stepTwo }),
    ]);
    expect(first.nodes.find((node) => node.id === ids.stepTwo)?.data.status).toBe(
      "awaiting_approval",
    );
  });

  it("does not crash on a malformed cyclic presentation dependency", () => {
    const cyclic = {
      ...workflow,
      steps: workflow.steps.map((step) => ({
        ...step,
        dependsOn: step.stepKey === "retrieve" ? ["approve"] : ["retrieve"],
      })),
    };
    expect(() => workflowDag(cyclic)).not.toThrow();
  });

  it("fails closed on unknown relationship registry values and unsupported self-links", () => {
    expect(
      graphRelationshipSchema.safeParse({ ...relationship, relationshipType: "invented_edge" })
        .success,
    ).toBe(false);
    expect(
      graphRelationshipSchema.safeParse({
        ...relationship,
        target: relationship.source,
      }).success,
    ).toBe(false);
  });

  it("keeps maximum bounded resource adaptation deterministic", () => {
    const nodes = Array.from({ length: 200 }, (_, index) => ({
      ...viewport.nodes[0]!,
      id: `${String(index).padStart(8, "0")}-0000-4000-8000-000000000001`,
      title: `Node ${index}`,
      position: { x: (index % 20) * 350, y: Math.floor(index / 20) * 260 },
    }));
    const bounded = { ...viewport, nodes, edges: [], boundaryNodes: [] };
    expect(resourceNodes(bounded, new Set())).toEqual(resourceNodes(bounded, new Set()));
    expect(resourceNodes(bounded, new Set())).toHaveLength(200);
  });

  it("deduplicates activity projection delivery and preserves deterministic newest-first order", () => {
    const base = {
      eventId: ids.relationship,
      eventType: "workflow.step.succeeded",
      sequence: 7,
      workspaceId: ids.workspace,
      canvasId: ids.canvas,
      subjectKind: "workflow_step",
      subjectId: ids.stepOne,
      actorUserId: ids.user,
      executionId: ids.execution,
      graphRevision: 7,
      traceId: ids.trace,
      occurredAt: timestamp,
      status: "delivered" as const,
      projected: true,
    };
    const older = { ...base, eventId: ids.definition, sequence: 6 };
    expect(normalizeActivity([older, base, base]).map((event) => event.eventId)).toEqual([
      base.eventId,
      older.eventId,
    ]);
  });
});
