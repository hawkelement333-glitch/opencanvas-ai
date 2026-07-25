"use client";

import {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  type NodeProps,
} from "@xyflow/react";
import { BookOpen, Bot, FileText, Orbit, StickyNote } from "lucide-react";
import { memo, useMemo } from "react";

import {
  canvasEdges,
  relationshipEdges,
  resourceNodes,
  type UniverseResourceNode,
} from "@/lib/dynamic-universe";
import type { GraphRelationship, UniverseViewport } from "@/lib/universe-contracts";

function icon(kind: string) {
  if (kind === "document") return <FileText size={15} aria-hidden="true" />;
  if (kind === "note") return <StickyNote size={15} aria-hidden="true" />;
  if (kind === "execution" || kind === "ai_response") return <Bot size={15} aria-hidden="true" />;
  return <BookOpen size={15} aria-hidden="true" />;
}

const ResourceCard = memo(function ResourceCard({
  data,
  selected,
}: NodeProps<UniverseResourceNode>) {
  const state = data.boundary
    ? "Connected beyond this bounded view"
    : data.selectedContext
      ? "Selected for context"
      : "Eligible, not selected";
  return (
    <article
      className={[
        "universe-node",
        data.selectedContext ? "is-context" : "",
        data.boundary ? "is-boundary" : "",
        data.historical ? "is-historical" : "",
        selected ? "is-focused" : "",
      ]
        .filter(Boolean)
        .join(" ")}
      aria-label={`${data.kind}: ${data.label}. ${state}`}
    >
      <span className="universe-node__icon">{icon(data.kind)}</span>
      <span>
        <small>{data.kind.replaceAll("_", " ")}</small>
        <strong>{data.label}</strong>
        <em>{state}</em>
      </span>
    </article>
  );
});

const nodeTypes = { universeResource: ResourceCard };

function stablePhantomPosition(id: string, index: number) {
  const hash = [...id].reduce((total, value) => (total * 31 + value.charCodeAt(0)) >>> 0, 7);
  const angle = ((hash % 360) * Math.PI) / 180;
  const radius = 650 + (index % 5) * 90;
  return { x: Math.round(Math.cos(angle) * radius), y: Math.round(Math.sin(angle) * radius) };
}

export function UniverseGraph({
  viewport,
  relationships,
  selectedIds,
  search,
  focusedObject,
  onToggleContext,
  onFocus,
}: {
  viewport: UniverseViewport;
  relationships: readonly GraphRelationship[];
  selectedIds: ReadonlySet<string>;
  search: string;
  focusedObject?: { id: string; label: string; kind: string };
  onToggleContext: (nodeId: string) => void;
  onFocus: (nodeId: string) => void;
}) {
  const graph = useMemo(() => {
    const base = resourceNodes(viewport, selectedIds);
    const known = new Set(base.map((node) => node.id));
    const phantom = new Map<string, UniverseResourceNode>();
    relationships.forEach((relationship) => {
      [relationship.source, relationship.target].forEach((endpoint) => {
        if (!known.has(endpoint.objectId) && !phantom.has(endpoint.objectId)) {
          phantom.set(endpoint.objectId, {
            id: endpoint.objectId,
            type: "universeResource",
            position: stablePhantomPosition(endpoint.objectId, phantom.size),
            draggable: false,
            selectable: true,
            data: {
              label: `Canonical ${endpoint.kind} · ${endpoint.objectId.slice(0, 8)}`,
              kind: endpoint.kind,
              selectedContext: selectedIds.has(endpoint.objectId),
              boundary: true,
              historical: false,
            },
          });
        }
      });
    });
    if (focusedObject && !known.has(focusedObject.id) && !phantom.has(focusedObject.id)) {
      phantom.set(focusedObject.id, {
        id: focusedObject.id,
        type: "universeResource",
        position: stablePhantomPosition(focusedObject.id, phantom.size),
        draggable: false,
        data: {
          label: focusedObject.label,
          kind: focusedObject.kind,
          selectedContext: selectedIds.has(focusedObject.id),
          boundary: true,
          historical: false,
        },
      });
    }
    const needle = search.trim().toLocaleLowerCase();
    const nodes = [...base, ...phantom.values()]
      .filter(
        (node) =>
          !needle ||
          node.data.label.toLocaleLowerCase().includes(needle) ||
          node.data.kind.includes(needle) ||
          node.id.toLocaleLowerCase().includes(needle),
      )
      .map((node) => ({ ...node, selected: node.id === focusedObject?.id }));
    const visible = new Set(nodes.map((node) => node.id));
    const edges = [...canvasEdges(viewport), ...relationshipEdges(relationships)].filter(
      (edge) => visible.has(edge.source) && visible.has(edge.target),
    );
    return { nodes, edges };
  }, [focusedObject, relationships, search, selectedIds, viewport]);

  return (
    <section className="universe-graph" aria-label="Dynamic Universe spatial view">
      <p className="sr-only" aria-live="polite">
        Showing {graph.nodes.length} resources and {graph.edges.length} relationships. Visual
        proximity does not grant context or authority.
      </p>
      <ReactFlowProvider>
        <ReactFlow
          nodes={graph.nodes}
          edges={graph.edges}
          nodeTypes={nodeTypes}
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable
          fitView
          minZoom={0.15}
          maxZoom={2}
          onNodeClick={(_, node) => onFocus(node.id)}
          onNodeDoubleClick={(_, node) => {
            if (!node.data.boundary) onToggleContext(node.id);
          }}
          aria-label="Knowledge universe. Use the accessible list for keyboard selection."
        >
          <Background variant={BackgroundVariant.Dots} gap={28} size={1} color="#24384f" />
          <MiniMap pannable zoomable aria-label="Universe overview" />
          <Controls showInteractive={false} />
        </ReactFlow>
      </ReactFlowProvider>
      <div className="universe-graph__hint">
        <Orbit size={14} aria-hidden="true" />
        Double-click an eligible resource to change selected context. Connections never select
        automatically.
      </div>
    </section>
  );
}
