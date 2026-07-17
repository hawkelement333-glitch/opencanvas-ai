# OpenCanvas AI Phase 2 checklist

- [x] Inspect the working Phase 1 data model, APIs, AI provider, persistence queue, and React Flow canvas.
- [x] Define the Phase 2 storage, processing, retrieval, grounding, citation, and deletion architecture.
- [x] Add document, file, chunk, embedding, processing-job, citation, response-source, and canvas-reference persistence.
- [x] Add the PostgreSQL/pgvector migration and reversible cleanup path.
- [x] Implement bounded uploads with extension, declared MIME, content-signature, filename, and size validation.
- [x] Store files under generated identifiers outside web/public directories; never return internal paths.
- [x] Extract PDF pages, Markdown headings, DOCX headings, and plain text without OCR.
- [x] Detect empty/image-only documents and expose actionable processing failures and retry.
- [x] Create deterministic, overlapping, metadata-rich chunks without duplicates on reprocessing.
- [x] Add mock and OpenAI embedding providers behind an interface.
- [x] Restrict vector retrieval to selected ready documents, top-k, and a minimum relevance threshold.
- [x] Build grounded prompts from selected notes and retrieved chunks while treating document text as untrusted data.
- [x] Require structured citations, reject unknown chunk IDs, and persist citations and response-source associations.
- [x] Persist Trace-ready execution records: selected-node versions/snapshots, ranked retrieval candidates and inclusion decisions, exact validated-citation order, immutable source-node relationships, model/retrieval configuration, prompt version, token usage, and generated output—even after live node/document cleanup.
- [x] Preserve the existing note-only AI path and return explicit insufficient-evidence grounded responses.
- [x] Add upload/drop, document nodes, processing states, preview, retry, deletion, citation badges, and source navigation.
- [x] Keep document-node duplication reference-only and allow move, resize, selection, and edges.
- [x] Add extraction, chunking, embedding, retrieval, grounding, deletion, injection, and end-to-end tests.
- [x] Run dependency installation, migrations, format, lint, strict typing, unit/integration/E2E/security tests, and production build.
- [x] Manually verify a cited PDF answer and an unsupported question that returns insufficient evidence.

Out of scope: authentication, OCR, real-time collaboration, web browsing, autonomous agents, image generation, audio, and video.
OpenCanvas Trace UI, replay, comparison, and evaluation remain out of scope; this milestone stores the structured execution evidence they will require.

Next milestone after Phase 2 validation: **semantic memory, hybrid search, and workspace-wide knowledge discovery**.
