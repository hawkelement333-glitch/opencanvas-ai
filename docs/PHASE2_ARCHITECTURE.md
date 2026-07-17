# Phase 2 architecture: document ingestion and grounded answers

## Status and compatibility boundary

The Phase 2 implementation is layered onto the working Phase 1 application. Existing canvas creation, note and AI-response nodes, directional edges, multi-selection, optimistic revisions, autosave, refresh restoration, and note-only AI requests remain intact. The full validation suite and the manual cited/insufficient-evidence PDF demonstrations have been completed against the finished tree.

A `Document` is a durable source object owned by one canvas. One or more `document` canvas nodes can reference it through `canvas_document_nodes`, so duplicating a node changes the spatial graph without copying the file, extracted text, chunks, or embeddings.

## Runtime components

- The Next.js client supplies upload/drop controls, dedicated document nodes, all six processing-stage presentations, extracted-text preview, source navigation, retry and destructive-delete controls, citation badges, and mixed note/document selection.
- FastAPI owns multipart handling, validation, storage, extraction, chunking, embeddings, retrieval, grounded-answer construction, citation validation, lifecycle operations, and practical per-client throttling.
- PostgreSQL owns application state and 1,536-dimension pgvector embeddings. The Phase 2 migration adds an HNSW cosine index for production retrieval.
- `AIProvider` and `EmbeddingProvider` interfaces isolate deterministic mock implementations from the server-side OpenAI Responses and Embeddings APIs.
- `LocalDocumentStorage` stores bytes under opaque generated keys below a configured, resolved root that is not exposed by the API or served by Next.js.

## Ingestion and processing flow

1. The browser posts a multipart file and desired canvas coordinates to `POST /canvases/{canvas_id}/documents`.
2. The API reads at most the configured limit plus one byte, sanitizes the display name, and verifies the extension, declared media type, and content itself. PDF signatures, UTF-8 text, DOCX structure, archive member paths, encryption, member count, and expanded size are checked on the server.
3. The validated bytes receive a SHA-256 digest and an opaque storage key such as `<document UUID>/<file UUID>.<extension>`. Only the display name and public document metadata are returned.
4. The upload transaction commits the document node in `uploading`, returns it to the canvas, and queues an in-process background task with a fresh database session.
5. A processing attempt commits `extracting`, `chunking`, `embedding`, and `ready`, or a safe `failed` status and actionable error. Retry queues another attempt and force-reprocesses from the stored file.
6. Extractors return structured segments. PDF retains one-based page numbers; Markdown retains ATX headings; DOCX retains paragraph-heading context and table text; TXT retains normalized UTF-8 text. Whitespace normalization preserves paragraphs and section boundaries.
7. OCR is intentionally absent. Empty sources and PDFs with no extractable text enter a failed state explaining that OCR is not enabled.
8. The chunker keeps coherent paragraphs within `OPENCANVAS_DOCUMENT_CHUNK_SIZE_CHARS`, carries controlled overlap from the preceding chunk, and records document ID, stable chunk ID, page, heading, chunk index, and absolute character offsets.
9. Reprocessing replaces the document's existing chunks and cascade-owned embeddings in one attempt. The `(document_id, chunk_index)` uniqueness constraint prevents duplicate chunk positions.
10. The selected embedding provider creates vectors in bounded batches. PostgreSQL stores provider/model metadata with each chunk vector.

Processing runs in an in-process background task. Committed document and processing-job states make each stage observable and retryable, but Phase 2 does not introduce a durable external queue.

## Retrieval and grounding flow

1. The AI route resolves selected node IDs from the database in client selection order; client-provided node content is never trusted as context.
2. Selected note and prior AI nodes contribute bounded text snapshots. Selected document nodes resolve through same-canvas reference rows to ready `Document` records.
3. The question is embedded server-side. Retrieval filters by the exact selected document IDs, ready status, and active embedding model before ranking by cosine similarity.
4. Retrieval captures up to a bounded candidate set. Each candidate receives a deterministic rank, score, `included_in_context` decision, and either no exclusion reason, `below_relevance_threshold`, or `top_k_limit`.
5. Only included passages are turned into stable source IDs and sent to the answer provider. Entire documents are not placed in model context.
6. The grounded prompt contains the user question, selected-note context, retrieved source metadata, and passage text inside explicitly delimited untrusted-data blocks. System instructions say never to obey instructions in uploaded content, never to invent support, and to return insufficient evidence when the sources do not answer the question.
7. The provider returns a typed grounded result. The service rejects unknown identifiers, duplicate invalid references, citations not in the retrieved allow-list, and grounded factual output without the required valid citations.
8. A successful transaction creates the AI node, AI response, citations, source associations, selected-node `generated_from` edges, and optional AI-to-document `cites` edges. An insufficient-evidence result is explicitly marked and contains no citation rows.
9. Citation clicks request `GET /documents/{document_id}/chunks/{chunk_id}` and open the plain-text preview at the matching page, heading, chunk, and character range.

The standalone `/canvases/{canvas_id}/documents/search` endpoint applies the same selected-canvas ownership, ready-state, top-k, threshold, embedding-model, and response-schema rules.

## Persistence model

| Record                     | Responsibility and deletion behavior                                                                                                             |
| -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| `documents`                | Canvas association, sanitized display metadata, SHA-256, extraction status/stage, page and chunk counts, extracted text, safe error, timestamps. |
| `document_files`           | One opaque storage key, detected media type, byte size, and checksum per document; cascades with the document.                                   |
| `canvas_document_nodes`    | Same-canvas reference between a React Flow node and its durable document; multiple node references may point at one document.                    |
| `document_processing_jobs` | Numbered processing attempts, stage, safe failure, start/completion times, and timestamps.                                                       |
| `document_chunks`          | Unique chunk index per document with normalized text, page, heading, and character offsets.                                                      |
| `document_embeddings`      | One provider/model/dimension/vector record per chunk; uses `vector(1536)` and HNSW cosine search in PostgreSQL.                                  |
| `citations`                | Validated response-to-document/chunk link, stable source identifier, claim, supporting excerpt, ordinal, and timestamps.                         |
| `ai_response_sources`      | One cited-document relationship per AI response, source document-node reference, and maximum relevance score.                                    |
| `ai_execution_nodes`       | Selected order, live node/document references, node revision, and immutable title/content snapshots.                                             |
| `ai_execution_chunks`      | Ranked retrieval evidence with live references plus immutable source ID, document name, content, page/heading, and offset snapshots.             |
| `ai_execution_citations`   | Exact validated citation sequence with immutable claim, excerpt, document/chunk ID, page/heading, and offset snapshots.                          |
| `ai_execution_sources`     | Immutable response-node-to-document-node relationships, document identity/title, and maximum relevance score.                                    |

The document row and its relational descendants use foreign-key deletion rules. Deleting a document removes every canvas node that references it, then the document and cascade-owned file metadata, chunks, embeddings, processing jobs, live citations, live response-source relationships, and source edges. The opaque file is removed before committing the pending database deletion; if file removal fails, the database transaction rolls back and retains its storage key for a safe retry. Ordinary note deletion remains unchanged.

## OpenCanvas Trace readiness

Phase 2 does not implement OpenCanvas Trace, but the schema supports future execution inspection and request reconstruction using structured records:

- `ai_requests.id` is the AI execution ID. The row stores the exact instruction, ordered selected-node ID list, legacy context snapshot, provider, model, status/error, model-configuration JSON, retrieval-configuration JSON, prompt version, and timestamps.
- `ai_execution_nodes` stores every selected node in order with its ID, type, revision, immutable title/content snapshots, and referenced document ID.
- `ai_execution_chunks` stores every ranked candidate returned by retrieval, including document/chunk IDs, score, rank, context inclusion/exclusion, exclusion reason, stable source identifier, and immutable source-location/content snapshots.
- `ai_execution_citations` stores each validated model citation in original order, including repeated source IDs, with immutable claim and source-location/content snapshots.
- `ai_execution_sources` stores the immutable response-node, selected document-node, and document relationship used for the grounded response.
- `ai_responses` stores the generated response, provider response ID, grounded and insufficient-evidence decisions, and input/output/total token usage when available.
- `citations` stores the server-validated citation identifiers, claims, excerpts, ordinals, and source-chunk relationships. `ai_response_sources` and graph edges store source-node relationships.

The execution-node and execution-chunk foreign keys use `SET NULL` where source objects may be removed, preserving their snapshots for historical reconstruction. `ai_responses.node_id` also uses `SET NULL`, so deleting the rendered response node does not erase its output or token usage. Required destructive document deletion removes live citation and response-source records while the execution record, answer, retrieval snapshots, immutable validated-citation snapshots, and immutable source-node relationships remain.

This is enough for a later Trace feature to display the original inputs, retrieved candidates and decisions, provider configuration, output, and surviving provenance. Replay orchestration, side-by-side comparison, evaluations, retention policy, and Trace UI remain out of scope.

## API surface

| Method and path                                  | Purpose                                                                         |
| ------------------------------------------------ | ------------------------------------------------------------------------------- |
| `POST /canvases/{canvas_id}/documents`           | Validate, store, place a processing node, and enqueue in-process processing.    |
| `GET /documents/{document_id}`                   | Return public metadata and current processing status.                           |
| `GET /documents/{document_id}/text`              | Return extracted plain text and section locations.                              |
| `GET /documents/{document_id}/chunks/{chunk_id}` | Return one public source passage for citation navigation.                       |
| `POST /documents/{document_id}/retry`            | Force a new processing attempt from the stored file.                            |
| `DELETE /documents/{document_id}`                | Remove the source, stored bytes, references, and cascade-owned data.            |
| `POST /canvases/{canvas_id}/documents/search`    | Search only an explicit list of ready documents on that canvas.                 |
| `POST /canvases/{canvas_id}/ai`                  | Preserve note-only answers or produce a grounded response for mixed selections. |

FastAPI applies strict Pydantic request/response schemas; browser API responses are independently parsed by strict Zod contracts.

## Security controls

- Server-enforced upload, PDF-page, extracted-character, DOCX-member, and expanded-archive limits.
- Generated storage keys, filename normalization, resolved-root containment, no arbitrary file execution, and no public file-serving route.
- Content inspection rather than trust in a client MIME header; PDF signatures, UTF-8 text, and safe DOCX ZIP structure are verified.
- Plain-text React rendering for extracted content; no uploaded HTML execution.
- Same-canvas foreign keys and route checks for document references and selected-document retrieval.
- Uploaded text is explicitly untrusted and isolated from system instructions; provider output citations are validated against server-created source IDs.
- Provider secrets remain server-side and are never placed in a `NEXT_PUBLIC_*` variable.
- Per-process request throttles protect expensive unauthenticated AI and document operations and return `429` with `Retry-After`.
- Security-marked pytest coverage exercises filename/path traversal, MIME/signature mismatch, oversize and DOCX archive attacks, rate limiting, invalid citations, and prompt-injection boundaries.

The current limiter is intentionally lightweight. A multi-replica deployment should replace it with a shared rate/quota service and add authentication, malware scanning, object-storage policy, and operational job workers in later phases.
