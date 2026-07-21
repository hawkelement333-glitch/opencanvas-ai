"use client";

import { Handle, NodeResizer, Position, type NodeProps } from "@xyflow/react";
import {
  AlertTriangle,
  CheckCircle2,
  Copy,
  Eye,
  FileText,
  LoaderCircle,
  RefreshCw,
  Trash2,
} from "lucide-react";
import { memo, type MouseEvent } from "react";

import { useCanvasNodeActions } from "@/components/canvas/canvas-node";
import type { DocumentProcessingStage } from "@/lib/contracts";
import type { CanvasFlowNode } from "@/lib/flow";

const stageDetails: Record<DocumentProcessingStage, { label: string }> = {
  uploading: { label: "Uploading" },
  queued: { label: "Queued for processing" },
  validating: { label: "Validating file" },
  extracting: { label: "Extracting text" },
  chunking: { label: "Building passages" },
  embedding: { label: "Creating embeddings" },
  indexing: { label: "Updating retrieval index" },
  ready: { label: "Ready" },
  retrying: { label: "Retry queued" },
  deleting: { label: "Deleting" },
  deleted: { label: "Deleted" },
  failed: { label: "Processing failed" },
};

function formatBytes(bytes: number): string {
  if (bytes < 1_024) return `${bytes} B`;
  if (bytes < 1_048_576) return `${(bytes / 1_024).toFixed(1)} KB`;
  return `${(bytes / 1_048_576).toFixed(1)} MB`;
}

function stopPropagation(event: MouseEvent): void {
  event.stopPropagation();
}

export const DocumentNodeCard = memo(function DocumentNodeCard({
  id,
  data,
  selected,
}: NodeProps<CanvasFlowNode>) {
  const actions = useCanvasNodeActions();
  const { node, pending } = data;
  const document = node.document;
  const stage = document?.processingStage ?? "failed";
  const details = stageDetails[stage];
  const ready = document?.status === "ready";
  const failed =
    !document || ["failed", "retryable_failure", "permanent_failure"].includes(document.status);

  return (
    <article
      className={`canvas-node document-node ${failed ? "document-node--failed" : ""} ${pending ? "canvas-node--pending" : ""}`}
      data-testid={`canvas-node-${id}`}
      aria-label={`Document: ${document?.fileName ?? node.title}`}
    >
      <NodeResizer
        color="#61c4d6"
        isVisible={selected && !pending}
        minWidth={280}
        minHeight={210}
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
        <span className="canvas-node__kind document-node__kind">
          <FileText size={14} aria-hidden="true" /> Document
        </span>
        <div className="canvas-node__actions nodrag" onMouseDown={stopPropagation}>
          <button
            type="button"
            onClick={() => actions.onDuplicate(id)}
            disabled={pending}
            aria-label={`Duplicate reference to ${document?.fileName ?? node.title}`}
            title="Duplicate document reference"
            data-testid={`duplicate-node-${id}`}
          >
            <Copy size={14} aria-hidden="true" />
          </button>
          <button
            type="button"
            onClick={() => actions.onDeleteDocument(id)}
            disabled={pending}
            aria-label={`Delete document ${document?.fileName ?? node.title}`}
            title="Delete document and all stored content"
            data-testid={`delete-document-${id}`}
          >
            <Trash2 size={14} aria-hidden="true" />
          </button>
        </div>
      </header>

      <div
        className="document-node__body nodrag nopan"
        onPointerDown={(event) => {
          event.stopPropagation();
          actions.onSelect(id, event.shiftKey || event.metaKey || event.ctrlKey);
        }}
      >
        <div className="document-node__identity">
          <span aria-hidden="true">
            <FileText size={22} />
          </span>
          <div>
            <strong title={document?.fileName ?? node.title}>
              {document?.fileName ?? node.title}
            </strong>
            <small>
              {document?.fileType.toUpperCase() ?? "FILE"} ·{" "}
              {document ? formatBytes(document.fileSize) : "Metadata unavailable"}
            </small>
          </div>
        </div>

        <dl className="document-node__metadata">
          <div>
            <dt>Pages</dt>
            <dd>{document?.pageCount ?? "—"}</dd>
          </div>
          <div>
            <dt>Passages</dt>
            <dd>{document?.chunkCount ?? "—"}</dd>
          </div>
          <div>
            <dt>Type</dt>
            <dd>{document?.mediaType ?? "Unknown"}</dd>
          </div>
        </dl>

        <div
          className={`document-node__status document-node__status--${stage}`}
          role="status"
          aria-live="polite"
        >
          <span>
            {ready ? (
              <CheckCircle2 size={13} aria-hidden="true" />
            ) : failed ? (
              <AlertTriangle size={13} aria-hidden="true" />
            ) : (
              <LoaderCircle size={13} className="spin" aria-hidden="true" />
            )}
            {details.label}
          </span>
          {!failed && !ready && <small>Stage-based status · completion time varies</small>}
          {failed && document?.errorMessage && <p>{document.errorMessage}</p>}
          {document?.status === "permanent_failure" && (
            <p>Automatic retries are exhausted. Review the file or retry manually.</p>
          )}
        </div>

        <div className="document-node__footer">
          {failed ? (
            <button
              type="button"
              onClick={() => actions.onRetryDocument(id)}
              disabled={!document}
              data-testid={`retry-document-${id}`}
            >
              <RefreshCw size={13} aria-hidden="true" /> Retry processing
            </button>
          ) : (
            <button
              type="button"
              onClick={() => actions.onPreviewDocument(id)}
              disabled={!ready}
              data-testid={`preview-document-${id}`}
            >
              <Eye size={13} aria-hidden="true" /> Preview extracted text
            </button>
          )}
        </div>
      </div>
    </article>
  );
});
