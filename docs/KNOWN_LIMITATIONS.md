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
- No OCR, password decryption, macro execution, embedded-object execution, or
  content-disarm pipeline. Encrypted, macro-enabled, active, malformed,
  unsupported, suspicious, infected, timed-out, and indeterminate input fails
  closed in quarantine.
- Staging/production require private versioned Azure Blob storage and trusted
  scanner results. Local development and deterministic tests use isolated
  substitutes and do not certify a production provider deployment.
- Direct human reads of Defender blob-index tags are unavailable under the
  least-privilege staging contributor role. Matching Log Analytics evidence
  validated the staging clean/EICAR prerequisite; the application does not use
  a personal identity or mutable tag as its safety decision.
- Trusted staging/production ingestion now executes durable exact-version
  deletion requests through the worker and resolves ambiguous provider commits
  by exact-version readback. The disabled legacy development/demo document path
  still cannot make file unlink and relational commit atomic; a rare commit
  failure after unlink requires operational repair.

## Reliability and scale

- A clean live PostgreSQL 17 migration has proved six historical
  compatibility defect classes across four migrations. Revision
  `20260718_0005` cannot recreate the
  referenced `workspaces` primary-key structure. Revision
  `20260725_0021` uses an unquoted textual `current_role` check that
  PostgreSQL resolves as database session `CURRENT_ROLE`, rejecting valid
  membership transitions. Its raw owner-backfill `INSERT` also uses bare
  `current_role` in the target list, which PostgreSQL rejects as invalid
  syntax independently of the check. Revisions
  `20260725_0023` and `20260725_0024` cannot safely recover closed values from
  PostgreSQL-canonicalized check expressions. Revision `0023` also exposes
  untyped derived-table nulls as `text` to UUID destinations during resource
  backfill. After those corrections, `0023` reaches append-only trigger
  creation and exposes four `0023`/`0024` references to an undefined
  PostgreSQL function. Documentation-governed corrections are authorized but
  not implemented; preserved combined work is not active, and Milestone 7.2
  remains blocked.
- Production-shaped processing uses persisted database jobs and an independently scalable worker.
  The PostgreSQL queue is not a dedicated broker and has no browser lease
  control or full dead-letter administration UI.
- Shared atomic rate limiting is implemented, but the application adapter has
  not yet been revalidated end to end against the approved isolated Azure
  Managed Redis topology.
- Provider-neutral operational observability, dashboards, provisional
  objectives, alerts, health controls, redaction, and bounded failure behavior
  are implemented locally. No approved isolated live telemetry destination was
  available during Milestone 7.5; live exporter authentication/TLS, Azure
  Monitor or Log Analytics, dashboard rendering, alert routing/recovery,
  retention, access revocation, and application-to-Azure behavior remain
  unvalidated.
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

## Current production-readiness boundary

Milestones 7.1–7.7 are complete. Milestone 7.8 remains active and incomplete.
All currently executable local audit work is recorded in the
[pre-expiry continuation handoff](MILESTONE_7_8_PRE_EXPIRY_MAXIMUM_SAFE_PROGRESS_HANDOFF.md).
The retained Automation account, the structurally non-armable Automation
cleanup controller, and the separately authorized managed-provider evidence
campaigns remain external gates. Milestone 8 has not begun.
