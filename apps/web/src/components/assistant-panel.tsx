"use client";

import {
  ArrowUp,
  Bot,
  CheckCircle2,
  CircleAlert,
  LoaderCircle,
  MousePointer2,
  X,
} from "lucide-react";
import { useState, type FormEvent } from "react";

import { askAIInputSchema, type CanvasNode } from "@/lib/contracts";
import { getErrorMessage } from "@/lib/api-client";
import { nodeRole, summarizeResources } from "@/lib/universe";

interface AssistantPanelProps {
  selectedNodes: readonly CanvasNode[];
  onAsk: (instruction: string) => Promise<{
    mock: boolean;
    grounded: boolean;
    insufficientEvidence: boolean;
  }>;
  onClearSelection: () => void;
}

export function AssistantPanel({ selectedNodes, onAsk, onClearSelection }: AssistantPanelProps) {
  const [instruction, setInstruction] = useState("");
  const [status, setStatus] = useState<
    | { type: "idle" }
    | { type: "asking" }
    | { type: "success"; mock: boolean; grounded: boolean; insufficientEvidence: boolean }
    | { type: "error"; message: string }
  >({ type: "idle" });
  const selectedResources = summarizeResources(selectedNodes, selectedNodes);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const parsed = askAIInputSchema.safeParse({
      instruction,
      selectedNodeIds: selectedNodes.map((node) => node.id),
    });
    if (!parsed.success) {
      setStatus({ type: "error", message: parsed.error.issues[0]?.message ?? "Invalid request" });
      return;
    }

    setStatus({ type: "asking" });
    try {
      const result = await onAsk(parsed.data.instruction);
      setInstruction("");
      setStatus({ type: "success", ...result });
    } catch (error) {
      setStatus({ type: "error", message: getErrorMessage(error) });
    }
  };

  return (
    <aside className="assistant-panel" aria-label="Controlled evidence query">
      <div className="assistant-panel__heading">
        <span className="assistant-panel__icon" aria-hidden="true">
          <Bot size={18} />
        </span>
        <div>
          <p>Ask from selected evidence</p>
          <span>Controlled context only · no unselected sources</span>
        </div>
      </div>

      <section className="context-tray" aria-labelledby="context-title">
        <div className="context-tray__header">
          <div>
            <span id="context-title">Context Zone</span>
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
            <p>Select notes or documents to give the assistant exact context.</p>
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

      <div className="assistant-state" aria-live="polite">
        {status.type === "asking" && (
          <span className="assistant-state--loading">
            <LoaderCircle size={14} className="spin" aria-hidden="true" /> Reasoning across{" "}
            {selectedNodes.length} {selectedNodes.length === 1 ? "item" : "items"}…
          </span>
        )}
        {status.type === "success" && (
          <span
            className={
              status.insufficientEvidence ? "assistant-state--warning" : "assistant-state--success"
            }
          >
            {status.insufficientEvidence ? (
              <CircleAlert size={14} aria-hidden="true" />
            ) : (
              <CheckCircle2 size={14} aria-hidden="true" />
            )}{" "}
            {status.insufficientEvidence
              ? "The selected sources lack sufficient evidence"
              : status.grounded
                ? "Grounded response added with citations"
                : "Response added to your canvas"}
            {status.mock && <small>Mock AI</small>}
          </span>
        )}
        {status.type === "error" && (
          <span className="assistant-state--error" role="alert">
            <CircleAlert size={14} aria-hidden="true" /> {status.message}
          </span>
        )}
      </div>

      <form className="assistant-composer" onSubmit={submit}>
        <label htmlFor="assistant-instruction">Evidence query</label>
        <textarea
          id="assistant-instruction"
          value={instruction}
          onChange={(event) => {
            setInstruction(event.target.value);
            if (status.type !== "asking") setStatus({ type: "idle" });
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              event.currentTarget.form?.requestSubmit();
            }
          }}
          placeholder="Ask a question that can be answered from the selected evidence."
          rows={4}
          maxLength={8_000}
          disabled={status.type === "asking"}
          data-testid="assistant-input"
        />
        <div className="assistant-composer__footer">
          <span>{selectedNodes.length} selected · Enter to ask</span>
          <button
            type="submit"
            disabled={status.type === "asking" || selectedNodes.length === 0 || !instruction.trim()}
            aria-label="Ask assistant"
            data-testid="ask-assistant"
          >
            {status.type === "asking" ? (
              <LoaderCircle size={16} className="spin" aria-hidden="true" />
            ) : (
              <ArrowUp size={16} aria-hidden="true" />
            )}
          </button>
        </div>
      </form>
    </aside>
  );
}
