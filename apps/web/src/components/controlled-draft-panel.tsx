"use client";

import {
  ArrowUp,
  Bot,
  CheckCircle2,
  CircleAlert,
  ExternalLink,
  LoaderCircle,
  MousePointer2,
  X,
} from "lucide-react";
import { useState, type FormEvent } from "react";

import {
  controlledDraftStartInputSchema,
  type CanvasNode,
  type ControlledDraft,
  type ControlledDraftCitation,
  type ControlledDraftCancellation,
  type ControlledDraftPrepared,
} from "@/lib/contracts";
import { nodeRole, summarizeResources } from "@/lib/universe";

interface ControlledDraftPanelProps {
  canvasId: string;
  selectedNodes: readonly CanvasNode[];
  onPrepare: (input: {
    canvasId: string;
    instruction: string;
    selectedNodeIds: string[];
    idempotencyKey: string;
    clientRequestId?: string;
  }) => Promise<ControlledDraftPrepared>;
  onRun: (executionId: string) => Promise<ControlledDraft>;
  onCancel: (executionId: string, idempotencyKey: string) => Promise<ControlledDraftCancellation>;
  onOpenCitation: (citation: ControlledDraftCitation, ordinal: number) => void;
  onClearSelection: () => void;
  getTraceUrl: (traceId: string) => string;
}

function requestKey(): string {
  return globalThis.crypto?.randomUUID?.() ?? `draft-${Math.random().toString(36).slice(2, 18)}`;
}

export function ControlledDraftPanel({
  canvasId,
  selectedNodes,
  onPrepare,
  onRun,
  onCancel,
  onOpenCitation,
  onClearSelection,
  getTraceUrl,
}: ControlledDraftPanelProps) {
  const [instruction, setInstruction] = useState("");
  const [status, setStatus] = useState<
    | { type: "idle" }
    | { type: "starting" }
    | { type: "running"; executionId: string }
    | { type: "cancelling"; executionId: string }
    | { type: "cancelled" }
    | { type: "succeeded"; result: ControlledDraft }
    | { type: "failed"; message: string }
  >({ type: "idle" });
  const selectedResources = summarizeResources(selectedNodes, selectedNodes);
  const active =
    status.type === "starting" || status.type === "running" || status.type === "cancelling";

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const parsed = controlledDraftStartInputSchema.safeParse({
      canvasId,
      instruction,
      selectedNodeIds: selectedNodes.map((node) => node.id),
      idempotencyKey: requestKey(),
      clientRequestId: requestKey(),
    });
    if (!parsed.success) {
      setStatus({
        type: "failed",
        message: parsed.error.issues[0]?.message ?? "Invalid controlled draft request.",
      });
      return;
    }

    setStatus({ type: "starting" });
    try {
      const prepared = await onPrepare(parsed.data);
      setStatus({ type: "running", executionId: prepared.executionId });
      const result = await onRun(prepared.executionId);
      setInstruction("");
      setStatus({ type: "succeeded", result });
    } catch {
      setStatus({
        type: "failed",
        message: "The controlled draft could not be completed. Review the Trace or try again.",
      });
    }
  };

  const cancel = async () => {
    if (status.type !== "running") return;
    const executionId = status.executionId;
    setStatus({ type: "cancelling", executionId });
    try {
      const outcome = await onCancel(executionId, requestKey());
      if (outcome.cancelled && outcome.status === "cancelled") setStatus({ type: "cancelled" });
      else setStatus({ type: "failed", message: "The controlled draft could not be cancelled." });
    } catch {
      setStatus({ type: "failed", message: "The controlled draft could not be cancelled." });
    }
  };

  return (
    <aside className="assistant-panel" aria-label="Controlled grounded draft">
      <div className="assistant-panel__heading">
        <span className="assistant-panel__icon" aria-hidden="true">
          <Bot size={18} />
        </span>
        <div>
          <p>Controlled grounded draft</p>
          <span>Read-only result · selected context only</span>
        </div>
      </div>

      <section className="context-tray" aria-labelledby="controlled-context-title">
        <div className="context-tray__header">
          <div>
            <span id="controlled-context-title">Context Zone</span>
            <strong>{selectedNodes.length}</strong>
          </div>
          {selectedNodes.length > 0 && (
            <button type="button" onClick={onClearSelection}>
              <X size={13} aria-hidden="true" /> Clear
            </button>
          )}
        </div>
        {selectedNodes.length === 0 ? (
          <div className="context-empty" data-testid="empty-selection">
            <MousePointer2 size={18} aria-hidden="true" />
            <p>Select notes or documents to give this draft exact context.</p>
            <span>Hold Shift and click to select several.</span>
          </div>
        ) : (
          <ul className="context-list" data-testid="selected-node-list">
            {selectedNodes.map((node, index) => (
              <li key={node.id}>
                <span>{index + 1}</span>
                <p>{node.title}</p>
                <small>{nodeRole(node).label}</small>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="resource-panel" aria-label="Selected context resources">
        <div>
          <span>Resources</span>
          <strong>{selectedResources.readyDocuments} ready sources</strong>
        </div>
        <dl>
          <div>
            <dt>Selected</dt>
            <dd>{selectedResources.selectedItems}</dd>
          </div>
          <div>
            <dt>Documents</dt>
            <dd>{selectedResources.documents}</dd>
          </div>
          <div>
            <dt>Citations</dt>
            <dd>{selectedResources.citations}</dd>
          </div>
        </dl>
      </section>

      <div className="assistant-panel__spacer" />
      <div className="assistant-state" aria-live="polite" aria-atomic="true">
        {status.type === "starting" && (
          <span className="assistant-state--loading">
            <LoaderCircle size={14} className="spin" aria-hidden="true" /> Starting controlled
            draft…
          </span>
        )}
        {status.type === "running" && (
          <span className="assistant-state--loading">
            <LoaderCircle size={14} className="spin" aria-hidden="true" /> Controlled draft is
            running.{" "}
            <button
              type="button"
              onClick={() => void cancel()}
              aria-label="Cancel controlled draft"
            >
              Cancel
            </button>
          </span>
        )}
        {status.type === "cancelling" && (
          <span className="assistant-state--loading">
            <LoaderCircle size={14} className="spin" aria-hidden="true" /> Cancelling controlled
            draft…
          </span>
        )}
        {status.type === "cancelled" && (
          <span className="assistant-state--warning">
            <CircleAlert size={14} aria-hidden="true" /> Controlled draft cancelled.
          </span>
        )}
        {status.type === "failed" && (
          <span className="assistant-state--error" role="alert">
            <CircleAlert size={14} aria-hidden="true" /> {status.message}
          </span>
        )}
        {status.type === "succeeded" && (
          <div className="controlled-draft-result" data-testid="controlled-draft-result">
            <span
              className={
                status.result.insufficientEvidence
                  ? "assistant-state--warning"
                  : "assistant-state--success"
              }
            >
              {status.result.insufficientEvidence ? (
                <CircleAlert size={14} aria-hidden="true" />
              ) : (
                <CheckCircle2 size={14} aria-hidden="true" />
              )}
              {status.result.insufficientEvidence
                ? "Insufficient evidence in the selected context"
                : "Grounded draft confirmed by the server"}
            </span>
            <p>{status.result.text}</p>
            {status.result.citations.length > 0 && (
              <ol aria-label="Validated citations">
                {status.result.citations.map((citation, index) => (
                  <li key={`${citation.documentId}-${citation.chunkId}`}>
                    <button type="button" onClick={() => onOpenCitation(citation, index + 1)}>
                      Citation [{index + 1}]
                    </button>
                  </li>
                ))}
              </ol>
            )}
            <a href={getTraceUrl(status.result.traceId)} target="_blank" rel="noreferrer">
              Inspect Trace <ExternalLink size={13} aria-hidden="true" />
            </a>
          </div>
        )}
      </div>

      <form className="assistant-composer" onSubmit={submit}>
        <label htmlFor="controlled-draft-instruction">Evidence query</label>
        <textarea
          id="controlled-draft-instruction"
          value={instruction}
          onChange={(event) => {
            setInstruction(event.target.value);
            if (!active) setStatus({ type: "idle" });
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              event.currentTarget.form?.requestSubmit();
            }
          }}
          placeholder="Ask a question that can be answered from selected evidence."
          rows={4}
          maxLength={8_000}
          disabled={active}
          data-testid="controlled-draft-input"
        />
        <div className="assistant-composer__footer">
          <span>{selectedNodes.length} selected · result stays read-only</span>
          <button
            type="submit"
            disabled={active || selectedNodes.length === 0 || !instruction.trim()}
            aria-label="Start controlled draft"
            title={active ? "A controlled draft is already starting" : undefined}
            data-testid="start-controlled-draft"
          >
            {active ? (
              <LoaderCircle size={16} className="spin" aria-hidden="true" />
            ) : (
              <ArrowUp size={16} aria-hidden="true" />
            )}
          </button>
        </div>
      </form>
      <p className="controlled-draft-note">
        Cancellation is available only while the server confirms this controlled execution is
        active.
      </p>
    </aside>
  );
}
