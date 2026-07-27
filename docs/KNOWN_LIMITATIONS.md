# Known limitations

This register prevents the competition demo and public materials from implying capabilities the release does not have.

## Product

- Authentication supports individual accounts, multiple workspaces,
  memberships, invitations, a closed role/permission registry, typed sharing,
  comments, and collaboration activity. Advanced Real-Time Collaboration is
  not implemented.
- No simultaneous editing, live cursors, detailed presence, CRDT/operational
  transform synchronization, offline merge, or reconnect conflict resolution;
  stale revisions return conflicts.
- No OCR; image-only PDFs fail with guidance.
- Supported node UI is notes, documents, and AI responses—not general code, image-generation, audio, or video objects.
- AI responses are non-streaming.
- No web browsing, external connectors, unbounded autonomous agents, or
  workspace-wide unselected assistant retrieval. Controlled agents and
  bounded Agent Studio remain deny-by-default and scoped.
- Retrieval is deliberately limited to ready documents selected on the active canvas.
- Inference and conflict are not automatically classified.
- No complete end-user Trace explorer, replay, comparison, evaluation, or export UI.

## AI and retrieval

- Mock embeddings are deterministic but are not a semantic-quality substitute for live embeddings.
- A citation proves that the server linked a model claim to an eligible retrieved passage; it does not independently prove the claim is true.
- Relevance depends on chunking, embeddings, configured top-k, and threshold.
- Embedding width is fixed at 1,536 dimensions by the current schema.
- Generated answers require human review.
- Live availability, latency, cost, model access, and output behavior depend on the configured OpenAI project.

## Documents

- PDF extraction depends on embedded text order and quality.
- Markdown heading preservation covers ATX headings; richer syntax is not a full Markdown AST.
- DOCX extraction preserves supported paragraph headings and table text, not full visual layout.
- No OCR, password decryption, macro execution, embedded-object execution, malware scan, or content-disarm pipeline.
- Staging/production support private S3-compatible object storage; the reference development
  Compose stack intentionally uses a shared private local volume.
- File unlink and relational commit cannot be one atomic transaction. A rare commit failure after unlink requires operational repair; staged trash/outbox cleanup is deferred.

## Reliability and scale

- A clean live PostgreSQL 17 migration has proved three historical
  compatibility defects. Revision `20260718_0005` cannot recreate the
  referenced `workspaces` primary-key structure, and revisions
  `20260725_0023` and `20260725_0024` cannot safely recover closed values from
  PostgreSQL-canonicalized check expressions. Revision `0023` also exposes
  untyped derived-table nulls as `text` to UUID destinations during resource
  backfill. Documentation-governed corrections are authorized but not
  implemented; preserved combined work is not active, and Milestone 7.2
  remains blocked.
- Production-shaped processing uses persisted database jobs and an independently scalable worker.
  The database queue is not a dedicated broker and does not yet provide long-running lease
  renewal or dead-letter administration UI.
- Rate limiting is process-local, not distributed.
- Canonical domain events, provenance, transactional outbox delivery attempts,
  and activity projections are durable. Production queue wake-up, operational
  telemetry, and external multi-service delivery still require the Milestone 7
  contract validation.
- No published load/performance benchmarks or capacity claims.

## Canonical compatibility

- Existing canvas notes and visual edges remain the working Phase 1/2 compatibility layer.
- They are not silently converted to canonical notes or semantic relationships.
- Deterministic production ingestion/indexing and workspace-wide unselected
  retrieval remain future work.
- Privileged raw SQL can bypass repository-level subtype and parent validation; normal APIs do not.
- Structured JSON is sanitized but does not have independent depth/byte quotas for every metadata field.

## Security and privacy

- Account deletion and data-export request entry points exist, but export artifact generation,
  formal retention schedules, and legal-hold workflows are not implemented.
- Backup/restore/rollback procedures are documented but have not been validated against a managed
  production deployment.
- Milestone 6 completed a local collaboration-security audit. No production
  infrastructure penetration test, compliance certification, or
  vulnerability-free guarantee exists.
- Uploaded content and execution snapshots may be sensitive; use synthetic demo data.
- Demo isolation protects against accidental live provider/data use when its canonical command is used, but it is not a security sandbox for hostile local users.

## Competition/release

- The repository began with a single imported source snapshot, so Git cannot independently prove the
  chronology of the earlier milestone work.
- The public repository URL, Work and Productivity category, proprietary evaluation terms, and
  synthetic screenshots are complete.
- The public demo video, Codex `/feedback` session ID, and final Devpost form remain manual owner
  actions.
- The proposed `v0.3.0-buildweek-demo` tag has not been created or published.

## Recommended next checkpoint

Implement only the combined migration `0005`, guarded-runner, `0023`, and
`0024` corrections authorized by the
[migration 0005 compatibility amendment](MILESTONE_7_POSTGRESQL_MIGRATION_0005_COMPATIBILITY_AMENDMENT.md)
and the
[migrations 0023 and 0024 compatibility amendment](MILESTONE_7_POSTGRESQL_MIGRATIONS_0023_0024_COMPATIBILITY_AMENDMENT.md).
[The migration 0023 UUID-null compatibility amendment](MILESTONE_7_POSTGRESQL_MIGRATION_0023_UUID_NULL_COMPATIBILITY_AMENDMENT.md)
adds only the required explicit PostgreSQL UUID typing and focused backfill
proof.
Checkpoint 7.2, migration `0026`, deployment, Milestone 8, and later work
remain unstarted until the combined restart gate passes.
