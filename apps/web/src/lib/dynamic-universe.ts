import type { Node, Edge } from "@xyflow/react";

import type { CanvasNode } from "./contracts";
import type {
  Activity,
  GraphRelationship,
  UniverseViewport,
  WorkflowExecution,
  WorkflowStep,
} from "./universe-contracts";

export const RELATIONSHIP_PRESENTATION = {
  references: { label: "references", direction: "forward" },
  derived_from: { label: "derived from", direction: "forward" },
  related_to: { label: "related to", direction: "bidirectional" },
  cites: { label: "cites", direction: "forward" },
  supports: { label: "supports", direction: "forward" },
  contradicts: { label: "contradicts", direction: "bidirectional" },
  produced_by: { label: "produced by", direction: "forward" },
  affected_by: { label: "affected by", direction: "forward" },
} as const;

export type UniverseResourceNode = Node<{
  label: string;
  kind: string;
  selectedContext: boolean;
  boundary: boolean;
  historical: boolean;
}>;

export function resourceNodes(
  viewport: UniverseViewport,
  selectedIds: ReadonlySet<string>,
): UniverseResourceNode[] {
  const visible = viewport.nodes.map((node) => resourceNode(node, selectedIds.has(node.id), false));
  const loaded = new Set(visible.map((node) => node.id));
  const selected = viewport.selectedNodes
    .filter((node) => !loaded.has(node.id))
    .map((node) => resourceNode(node, true, false));
  const boundary = viewport.boundaryNodes
    .filter((node) => !loaded.has(node.id) && !selectedIds.has(node.id))
    .map<UniverseResourceNode>((node) => ({
      id: node.id,
      type: "universeResource",
      position: node.position,
      selectable: false,
      draggable: false,
      data: {
        label: node.title,
        kind: node.type,
        selectedContext: false,
        boundary: true,
        historical: false,
      },
    }));
  return [...visible, ...selected, ...boundary];
}

function resourceNode(
  node: CanvasNode,
  selectedContext: boolean,
  boundary: boolean,
): UniverseResourceNode {
  return {
    id: node.id,
    type: "universeResource",
    position: node.position,
    data: {
      label: node.title,
      kind: node.type,
      selectedContext,
      boundary,
      historical: false,
    },
  };
}

export function canvasEdges(viewport: UniverseViewport): Edge[] {
  return viewport.edges.map((edge) => ({
    id: `canvas:${edge.id}`,
    source: edge.sourceNodeId,
    target: edge.targetNodeId,
    label: edge.label ?? edge.kind.replaceAll("_", " "),
    type: "smoothstep",
    animated: false,
    data: { kind: edge.kind, authoritative: true },
  }));
}

export function relationshipEdges(relationships: readonly GraphRelationship[]): Edge[] {
  return [...relationships]
    .sort((left, right) => left.relationshipId.localeCompare(right.relationshipId))
    .map((relationship) => {
      const presentation = RELATIONSHIP_PRESENTATION[relationship.relationshipType];
      const historical = relationship.currentState !== "active";
      return {
        id: `graph:${relationship.relationshipId}`,
        source: relationship.source.objectId,
        target: relationship.target.objectId,
        label: `${presentation.label}${historical ? ` · ${relationship.currentState}` : ""}`,
        type: "smoothstep",
        animated: false,
        selectable: true,
        data: {
          relationshipId: relationship.relationshipId,
          relationshipType: relationship.relationshipType,
          direction: presentation.direction,
          historical,
          graphRevision: relationship.graphRevision,
        },
        markerEnd:
          presentation.direction === "forward" ? { type: "arrowclosed" as const } : undefined,
        className: historical ? "universe-edge--historical" : undefined,
      };
    });
}

export type WorkflowNode = Node<{
  label: string;
  stepType: string;
  status: WorkflowStep["status"];
  approvalRequired: boolean;
  attempts: string;
}>;

export function workflowDag(execution: WorkflowExecution): {
  nodes: WorkflowNode[];
  edges: Edge[];
} {
  const byKey = new Map(execution.steps.map((step) => [step.stepKey, step]));
  const depth = new Map<string, number>();
  const visiting = new Set<string>();
  const resolveDepth = (key: string): number => {
    if (depth.has(key)) return depth.get(key) ?? 0;
    if (visiting.has(key)) return 0;
    visiting.add(key);
    const step = byKey.get(key);
    const value =
      step && step.dependsOn.length > 0
        ? 1 + Math.max(...step.dependsOn.map((dependency) => resolveDepth(dependency)))
        : 0;
    visiting.delete(key);
    depth.set(key, value);
    return value;
  };
  execution.steps.forEach((step) => resolveDepth(step.stepKey));

  const lanes = new Map<number, WorkflowStep[]>();
  [...execution.steps]
    .sort((left, right) => left.stepKey.localeCompare(right.stepKey))
    .forEach((step) => {
      const column = depth.get(step.stepKey) ?? 0;
      lanes.set(column, [...(lanes.get(column) ?? []), step]);
    });

  const nodes = [...execution.steps]
    .sort((left, right) => left.stepKey.localeCompare(right.stepKey))
    .map<WorkflowNode>((step) => {
      const column = depth.get(step.stepKey) ?? 0;
      const row = (lanes.get(column) ?? []).findIndex(
        (candidate) => candidate.stepKey === step.stepKey,
      );
      return {
        id: step.stepExecutionId,
        type: "workflowStep",
        position: { x: column * 280, y: Math.max(0, row) * 150 },
        draggable: false,
        data: {
          label: step.stepKey,
          stepType: step.stepType,
          status: step.status,
          approvalRequired: step.approvalRequired,
          attempts: `${step.attemptCount}/${step.maxAttempts}`,
        },
      };
    });
  const stepId = new Map(execution.steps.map((step) => [step.stepKey, step.stepExecutionId]));
  const edges = execution.steps.flatMap((step) =>
    step.dependsOn.flatMap((dependency) => {
      const source = stepId.get(dependency);
      if (!source) return [];
      return [
        {
          id: `workflow:${source}:${step.stepExecutionId}`,
          source,
          target: step.stepExecutionId,
          type: "smoothstep",
          animated: step.status === "running",
        },
      ];
    }),
  );
  return { nodes, edges };
}

export function safeShortId(value: string | null | undefined): string {
  return value ? `${value.slice(0, 8)}…${value.slice(-4)}` : "Unavailable";
}

export function isWorkflowTerminal(status: WorkflowExecution["status"]): boolean {
  return ["completed", "failed", "canceled", "compensated", "compensation_failed"].includes(status);
}

export function normalizeActivity(rows: readonly Activity[]): Activity[] {
  const unique = new Map(rows.map((event) => [event.eventId, event]));
  return [...unique.values()].sort(
    (left, right) => right.sequence - left.sequence || right.eventId.localeCompare(left.eventId),
  );
}
