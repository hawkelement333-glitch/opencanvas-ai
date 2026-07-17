# Changelog

This project follows a milestone-oriented pre-release history. The repository has dated Build Week
commits on `main`; no release tag has been created.

## [Unreleased] — proposed `v0.3.0-buildweek-demo`

### Added

- Isolated deterministic competition demo and reset workflow.
- Canonical `pnpm validate` release gate and non-publishing GitHub Actions CI.
- Public README, judge setup, demo, Build Week, Trace, security-model, limitations, contribution, conduct, release, and submission documentation.
- Copyright/license recommendation and third-party dependency notices for owner review.

### Security

- Demo mode refuses production mode, live providers, OpenAI credentials, and non-demo database/storage paths.
- Release hygiene and secret-scan checks prepared for the final candidate.

### Changed

- Replaced an aspirational architecture document with the as-built Phase 1–3 architecture.
- Clarified that supported/insufficient-evidence states are implemented while automatic inference/conflict classification and a complete Trace UI are deferred.

## Milestone 3 — Trace and canonical knowledge foundation

### Added

- Append-only Trace events, filtered read APIs, parent traces, actor/workspace/object correlation, and structured success/failure evidence.
- Canonical workspace, object, Document, Chunk, Note, Execution, lifecycle, and first-class directional Relationship persistence.
- Additive Canvas-to-Workspace compatibility backfill.
- Strict canonical APIs, repositories, domain services, and replaceable in-process event contracts.
- Tests for Trace lifecycle, failure evidence, mutation atomicity, workspace isolation, lifecycle, versions, and canonical graph behavior.

## Milestone 2 — Document intelligence

### Added

- Secure PDF, TXT, Markdown, and DOCX upload, storage, extraction, processing status, retry, and deletion.
- Configurable overlapping chunks with page/heading/offset metadata.
- Server-side mock/OpenAI embeddings and selected-document pgvector retrieval.
- Grounded answers, validated citations, source passage preview, and explicit insufficient-evidence behavior.
- Structured AI execution, selected-node, retrieval, citation, source, model-configuration, and token-usage snapshots.

## Milestone 1 — Canvas MVP

### Added

- Persistent canvases with editable, movable, resizable, duplicable, and deletable note nodes.
- Directional visual edges, multi-selection, autosave, explicit save, and refresh restoration.
- Server-side AI context construction, deterministic mock mode, and editable connected AI-response nodes.
- Frontend, backend, and browser workflow tests.

[Unreleased]: docs/RELEASE_NOTES_v0.3.0-buildweek-demo.md
