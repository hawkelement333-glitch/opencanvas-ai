"use client";

import { Handle, NodeResizer, Position, type NodeProps } from "@xyflow/react";
import { Bot, BookOpen, Copy, LoaderCircle, StickyNote, Trash2 } from "lucide-react";
import {
  createContext,
  memo,
  useContext,
  type ChangeEvent,
  type MouseEvent,
  type ReactNode,
} from "react";

import type { Citation } from "@/lib/contracts";
import type { CanvasFlowNode, NodeHandlers } from "@/lib/flow";

const CanvasNodeActionsContext = createContext<NodeHandlers | null>(null);

export function useCanvasNodeActions(): NodeHandlers {
  const actions = useContext(CanvasNodeActionsContext);
  if (!actions) throw new Error("Canvas node actions are unavailable.");
  return actions;
}

export function CanvasNodeActionsProvider({
  actions,
  children,
}: {
  actions: NodeHandlers;
  children: ReactNode;
}) {
  return (
    <CanvasNodeActionsContext.Provider value={actions}>
      {children}
    </CanvasNodeActionsContext.Provider>
  );
}

function stopPropagation(event: MouseEvent): void {
  event.stopPropagation();
}

function citationLocation(citation: Citation): string {
  if (citation.pageNumber) {
    return `Page ${citation.pageNumber}${citation.heading ? ` · ${citation.heading}` : ""}`;
  }
  if (citation.heading) return citation.heading;
  return `Passage ${citation.chunkIndex + 1} · chars ${citation.startOffset}–${citation.endOffset}`;
}

export function ResponseCitations({
  citations,
  onOpen,
}: {
  citations: readonly Citation[];
  onOpen: (citation: Citation) => void;
}) {
  return (
    <section className="canvas-node__citations nodrag nopan" aria-label="Response sources">
      {citations.length > 0 ? (
        <>
          <span className="canvas-node__citations-heading">
            <BookOpen size={12} aria-hidden="true" /> {citations.length}{" "}
            {citations.length === 1 ? "source" : "sources"}
          </span>
          <ol>
            {citations.map((citation) => (
              <li key={citation.id}>
                <button
                  type="button"
                  onClick={() => onOpen(citation)}
                  onPointerDown={(event) => event.stopPropagation()}
                  aria-label={`Open source ${citation.ordinal}: ${citation.documentTitle}`}
                  data-testid={`citation-${citation.id}`}
                >
                  <strong>[{citation.ordinal}]</strong>
                  <span>{citation.documentTitle}</span>
                  <small>{citationLocation(citation)}</small>
                </button>
              </li>
            ))}
          </ol>
        </>
      ) : (
        <span className="canvas-node__ungrounded">No source citations</span>
      )}
    </section>
  );
}

export const CanvasNodeCard = memo(function CanvasNodeCard({
  id,
  data,
  selected,
}: NodeProps<CanvasFlowNode>) {
  const actions = useCanvasNodeActions();
  const { node, pending } = data;
  const isAI = node.type === "ai_response";
  const citations = node.citations ?? [];

  const changeTitle = (event: ChangeEvent<HTMLInputElement>) => {
    actions.onTitleChange(id, event.target.value);
  };

  const changeText = (event: ChangeEvent<HTMLTextAreaElement>) => {
    actions.onTextChange(id, event.target.value);
  };

  return (
    <article
      className={`canvas-node ${isAI ? "canvas-node--ai" : ""} ${pending ? "canvas-node--pending" : ""}`}
      data-testid={`canvas-node-${id}`}
      aria-label={`${isAI ? "AI response" : "Note"}: ${node.title}`}
    >
      <NodeResizer
        color={isAI ? "#b39aff" : "#d8ff8d"}
        isVisible={selected && !pending}
        minWidth={220}
        minHeight={140}
        maxWidth={1_600}
        maxHeight={1_200}
        lineClassName="canvas-node__resize-line"
        handleClassName="canvas-node__resize-handle"
      />

      {!pending && (
        <>
          <Handle
            type="target"
            position={Position.Left}
            className="canvas-node__handle canvas-node__handle--target"
            aria-label="Incoming connection"
          />
          <Handle
            type="source"
            position={Position.Right}
            className="canvas-node__handle canvas-node__handle--source"
            aria-label="Create outgoing connection"
          />
        </>
      )}

      <header className="canvas-node__header">
        <span className="canvas-node__kind" title={isAI ? "AI-generated note" : "Text note"}>
          {isAI ? (
            <Bot size={14} aria-hidden="true" />
          ) : (
            <StickyNote size={14} aria-hidden="true" />
          )}
          {isAI ? "AI response" : "Note"}
        </span>
        <div className="canvas-node__actions nodrag" onMouseDown={stopPropagation}>
          <button
            type="button"
            onClick={() => actions.onDuplicate(id)}
            disabled={pending}
            aria-label={`Duplicate ${node.title}`}
            title="Duplicate node"
            data-testid={`duplicate-node-${id}`}
          >
            <Copy size={14} aria-hidden="true" />
          </button>
          <button
            type="button"
            onClick={() => actions.onDelete(id)}
            disabled={pending}
            aria-label={`Delete ${node.title}`}
            title="Delete node"
            data-testid={`delete-node-${id}`}
          >
            <Trash2 size={14} aria-hidden="true" />
          </button>
        </div>
      </header>

      <input
        className="canvas-node__title nodrag nopan"
        aria-label="Node title"
        value={node.title}
        onChange={changeTitle}
        onPointerDown={(event) => {
          event.stopPropagation();
          actions.onSelect(id, event.shiftKey || event.metaKey || event.ctrlKey);
        }}
        onBlur={(event) => {
          if (!event.currentTarget.value.trim()) actions.onTitleChange(id, "Untitled note");
        }}
        onKeyDown={(event) => {
          if (!((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s")) {
            event.stopPropagation();
          }
        }}
        disabled={pending}
        maxLength={160}
        data-testid={`node-title-${id}`}
      />
      <textarea
        className="canvas-node__editor nodrag nopan nowheel"
        aria-label={`${node.title} content`}
        value={node.text}
        onChange={changeText}
        onPointerDown={(event) => {
          event.stopPropagation();
          actions.onSelect(id, event.shiftKey || event.metaKey || event.ctrlKey);
        }}
        onKeyDown={(event) => {
          if (!((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s")) {
            event.stopPropagation();
          }
        }}
        disabled={pending}
        maxLength={100_000}
        placeholder={isAI ? "The generated response will appear here…" : "Start typing…"}
        data-testid={`node-text-${id}`}
      />

      {isAI && <ResponseCitations citations={citations} onOpen={actions.onOpenCitation} />}

      {pending && (
        <span className="canvas-node__pending" role="status">
          <LoaderCircle size={13} className="spin" aria-hidden="true" /> Creating note…
        </span>
      )}
    </article>
  );
});
