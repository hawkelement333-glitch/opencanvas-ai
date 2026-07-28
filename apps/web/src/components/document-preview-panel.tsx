"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, BookOpen, FileText, LoaderCircle, RefreshCw, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { canvasApi, getErrorMessage } from "@/lib/api-client";
import type { Citation, DocumentMetadata, IndexRequest } from "@/lib/contracts";

interface DocumentPreviewPanelProps {
  workspaceId: string;
  document: DocumentMetadata;
  citation?: Citation;
  onClose: () => void;
}

function sourceLocation(
  pageNumber: number | null,
  heading: string | null,
  chunkIndex?: number,
  startOffset?: number,
  endOffset?: number,
): string {
  if (pageNumber) return `Page ${pageNumber}${heading ? ` · ${heading}` : ""}`;
  if (heading) return heading;
  if (chunkIndex !== undefined && startOffset !== undefined && endOffset !== undefined) {
    return `Passage ${chunkIndex + 1} · chars ${startOffset}–${endOffset}`;
  }
  return "Extracted passage";
}

export function DocumentPreviewPanel({
  workspaceId,
  document,
  citation,
  onClose,
}: DocumentPreviewPanelProps) {
  const passageRef = useRef<HTMLElement>(null);
  const [indexRequest, setIndexRequest] = useState<IndexRequest | null>(null);
  const [indexActionError, setIndexActionError] = useState<string | null>(null);
  const textQuery = useQuery({
    queryKey: ["document", document.id, "text"],
    queryFn: ({ signal }) => canvasApi.getDocumentText(document.id, signal),
    enabled: document.status === "ready",
  });
  const passageQuery = useQuery({
    queryKey: ["document", document.id, "chunk", citation?.chunkId],
    queryFn: ({ signal }) =>
      canvasApi.getSourcePassage(document.id, citation?.chunkId ?? "", signal),
    enabled: Boolean(citation?.chunkId) && document.status === "ready",
  });

  useEffect(() => {
    if (passageQuery.data) passageRef.current?.focus();
  }, [passageQuery.data]);

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);

  useEffect(() => {
    if (!indexRequest?.cancellable) return;
    const timer = window.setInterval(() => {
      void canvasApi
        .getIndexRequest(workspaceId, document.canvasId, indexRequest.requestId)
        .then(setIndexRequest)
        .catch((error: unknown) => setIndexActionError(getErrorMessage(error)));
    }, 1_000);
    return () => window.clearInterval(timer);
  }, [document.canvasId, indexRequest?.cancellable, indexRequest?.requestId, workspaceId]);

  const reindex = async () => {
    setIndexActionError(null);
    try {
      setIndexRequest(await canvasApi.reindexDocument(workspaceId, document.canvasId, document.id));
    } catch (error) {
      setIndexActionError(getErrorMessage(error));
    }
  };

  const cancelIndexing = async () => {
    if (!indexRequest?.cancellable) return;
    setIndexActionError(null);
    try {
      setIndexRequest(
        await canvasApi.cancelIndexRequest(workspaceId, document.canvasId, indexRequest.requestId),
      );
    } catch (error) {
      setIndexActionError(getErrorMessage(error));
    }
  };

  return (
    <aside
      className="document-preview"
      role="dialog"
      aria-modal="false"
      aria-labelledby="document-preview-title"
      data-testid="document-preview"
    >
      <header className="document-preview__header">
        <span aria-hidden="true">
          <FileText size={18} />
        </span>
        <div className="document-preview__heading">
          <small>Source document</small>
          <h2 id="document-preview-title" title={document.fileName}>
            {document.fileName}
          </h2>
        </div>
        <button type="button" onClick={onClose} aria-label="Close document preview">
          <X size={16} aria-hidden="true" />
        </button>
      </header>

      <div className="document-preview__meta" aria-label="Document metadata">
        <span>{document.fileType.toUpperCase()}</span>
        {document.pageCount && <span>{document.pageCount} pages</span>}
        <span>{document.chunkCount} passages</span>
      </div>

      <section className="document-preview__index" aria-label="Document index">
        <button
          type="button"
          onClick={() => void reindex()}
          disabled={document.status !== "ready" || Boolean(indexRequest?.cancellable)}
        >
          <RefreshCw size={13} aria-hidden="true" />
          Reindex document
        </button>
        {indexRequest && (
          <span role="status" aria-live="polite">
            Index status: {indexRequest.state.replaceAll("_", " ")}
          </span>
        )}
        {indexRequest?.cancellable && (
          <button type="button" onClick={() => void cancelIndexing()}>
            Cancel indexing
          </button>
        )}
        {indexActionError && <span role="alert">{indexActionError}</span>}
      </section>

      {citation && (
        <section className="document-preview__citation" aria-labelledby="selected-source-title">
          <div>
            <BookOpen size={14} aria-hidden="true" />
            <strong id="selected-source-title">Citation [{citation.ordinal}]</strong>
          </div>
          <p>
            {sourceLocation(
              citation.pageNumber,
              citation.heading,
              citation.chunkIndex,
              citation.startOffset,
              citation.endOffset,
            )}
          </p>
          {citation.claim && <blockquote>{citation.claim}</blockquote>}
        </section>
      )}

      <div className="document-preview__content">
        {textQuery.isPending ? (
          <div className="document-preview__state" role="status">
            <LoaderCircle size={19} className="spin" aria-hidden="true" /> Loading extracted text…
          </div>
        ) : textQuery.isError ? (
          <div className="document-preview__state document-preview__state--error" role="alert">
            <AlertTriangle size={18} aria-hidden="true" />
            <p>{getErrorMessage(textQuery.error)}</p>
            <button type="button" onClick={() => void textQuery.refetch()}>
              <RefreshCw size={13} aria-hidden="true" /> Try again
            </button>
          </div>
        ) : textQuery.data ? (
          <>
            {citation && (
              <section
                className="document-preview__passage"
                ref={passageRef}
                tabIndex={-1}
                aria-labelledby="cited-passage-title"
                data-testid="source-passage"
              >
                <strong id="cited-passage-title">Cited passage</strong>
                {passageQuery.isPending ? (
                  <span role="status">
                    <LoaderCircle size={13} className="spin" aria-hidden="true" /> Resolving source…
                  </span>
                ) : passageQuery.isError ? (
                  <span role="alert">{getErrorMessage(passageQuery.error)}</span>
                ) : passageQuery.data ? (
                  <>
                    <small>
                      {sourceLocation(
                        passageQuery.data.pageNumber,
                        passageQuery.data.heading,
                        passageQuery.data.chunkIndex,
                        passageQuery.data.startOffset,
                        passageQuery.data.endOffset,
                      )}
                    </small>
                    <p>{passageQuery.data.text}</p>
                  </>
                ) : null}
              </section>
            )}

            {textQuery.data.sections.length > 0 && (
              <nav className="document-preview__sections" aria-label="Document sections">
                {textQuery.data.sections.slice(0, 24).map((section, index) => (
                  <span key={`${section.startOffset}-${index}`}>
                    {section.pageNumber
                      ? `Page ${section.pageNumber}`
                      : section.heading || "Section"}
                  </span>
                ))}
              </nav>
            )}

            <pre
              className="document-preview__text"
              tabIndex={0}
              aria-label="Extracted document text"
            >
              {textQuery.data.text}
            </pre>
          </>
        ) : null}
      </div>
    </aside>
  );
}
