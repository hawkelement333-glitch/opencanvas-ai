"use client";

import {
  Background,
  BackgroundVariant,
  Controls,
  ReactFlow,
  ReactFlowProvider,
  type NodeProps,
} from "@xyflow/react";
import { Check, CircleAlert, Clock3, LoaderCircle, ShieldCheck } from "lucide-react";
import { memo, useMemo } from "react";

import { workflowDag, type WorkflowNode } from "@/lib/dynamic-universe";
import type { WorkflowExecution } from "@/lib/universe-contracts";

function statusIcon(status: string) {
  if (["succeeded", "compensated"].includes(status)) return <Check size={14} aria-hidden="true" />;
  if (["failed", "compensation_failed"].includes(status))
    return <CircleAlert size={14} aria-hidden="true" />;
  if (["running", "claimed", "compensating"].includes(status))
    return <LoaderCircle className="spin" size={14} aria-hidden="true" />;
  return <Clock3 size={14} aria-hidden="true" />;
}

const WorkflowStepCard = memo(function WorkflowStepCard({
  data,
  selected,
}: NodeProps<WorkflowNode>) {
  return (
    <article
      className={`workflow-node workflow-node--${data.status} ${selected ? "is-focused" : ""}`}
      aria-label={`${data.label}, ${data.stepType}, status ${data.status}, attempts ${data.attempts}`}
    >
      <span>{statusIcon(data.status)}</span>
      <span>
        <small>{data.stepType.replaceAll("_", " ")}</small>
        <strong>{data.label}</strong>
        <em>
          {data.status.replaceAll("_", " ")} · attempts {data.attempts}
        </em>
      </span>
      {data.approvalRequired && <ShieldCheck size={14} aria-label="Human approval required" />}
    </article>
  );
});

const nodeTypes = { workflowStep: WorkflowStepCard };

export function WorkflowDag({
  execution,
  onFocusStep,
}: {
  execution: WorkflowExecution;
  onFocusStep: (stepId: string) => void;
}) {
  const graph = useMemo(() => workflowDag(execution), [execution]);
  return (
    <section className="workflow-dag" aria-label="Controlled workflow DAG">
      <ReactFlowProvider>
        <ReactFlow
          nodes={graph.nodes}
          edges={graph.edges}
          nodeTypes={nodeTypes}
          nodesDraggable={false}
          nodesConnectable={false}
          fitView
          minZoom={0.35}
          maxZoom={1.5}
          onNodeClick={(_, node) => onFocusStep(node.id)}
          aria-label={`Workflow ${execution.status}. ${graph.nodes.length} steps.`}
        >
          <Background variant={BackgroundVariant.Lines} gap={32} color="#24384f" />
          <Controls showInteractive={false} />
        </ReactFlow>
      </ReactFlowProvider>
    </section>
  );
}
