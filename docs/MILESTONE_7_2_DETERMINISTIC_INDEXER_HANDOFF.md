# Milestone 7.2 Deterministic Indexer Handoff

Date: 2026-07-27

Status: complete locally; production publication disabled; Milestone 7.3
unstarted

Exact checkpoint: **Checkpoint 7.2 — Deterministic Indexer and Ingestion
Pipeline**

Purpose: create provenance-complete, immutable, deterministic index revisions
and separate index construction from authorized retrieval publication.

Parent: `7bec20e867f8a768a916a001718052fe4ceb3c64`

Branch: `milestone-7-2-implementation-local`

Implementation commit: the local commit named `Implement Milestone 7.2`; its
exact SHA is reported in the final task handoff because a commit cannot contain
its own SHA.

Migration: `20260726_0026`, direct child of `20260725_0025`

Migration Git blob hash:
`847a347b3e9f16ccd328c10265060b81937aa6c5`

Evidence owner: application/platform engineering

Validation environment: Windows host, WSL 2 Ubuntu 24.04, PostgreSQL 17.10,
installed pgvector, SQLite, Python 3.12 project environment, Chromium, and
Node/Next.js installed local dependencies. No network, registry, paid
provider, production credential, production data, deployment, or remote Git
operation was used.

## Scope delivered

- server-scoped index and reindex requests with immutable user, membership,
  workspace, canvas, document, document-version, authority-generation,
  cancellation-generation, idempotency, source, manifest, and Trace bindings;
- append-only request transitions, manifests, normalized artifacts, native
  revisions, ordered chunks, vector materializations, publications, audits,
  and failures;
- a deterministic pipeline manifest over every output-affecting component and
  bounded configuration value;
- isolated parsing with no parser network access, a wall timeout, and
  supported POSIX CPU/address-space limits;
- deterministic normalization, allowlisted metadata, stable chunk identity,
  ordered chunk/vector manifests, and output digests;
- workspace-scoped exact-byte and normalized-content deduplication with
  explicit revision/vector reuse evidence;
- versioned near-duplicate diagnostic output under the manifest’s Indexer and
  metadata versions;
- separate build and short publication transactions;
- active retrieval-head projection, publication generations, supersession,
  reindex, cancellation, safe failure, and stale-result suppression;
- current authority/source/version/cancellation revalidation at publication;
- PostgreSQL source-document locking, existing-head locking, uniqueness, and
  duplicate-conflict reconciliation; SQLite uses uniqueness plus savepoint
  reconciliation because it does not implement row-level `FOR UPDATE`;
- existing domain-event/outbox, Trace, audit, and authorized activity
  contracts; no parallel evidence system;
- authenticated, CSRF-protected, rate-limited request, status, cancellation,
  reindex, and safe revision-list APIs under exact parents;
- safe API responses that omit raw source hashes, storage keys, private
  manifests, worker controls, unpublished content, and authority internals;
- accessible preview actions and live status for reindex and cancellation;
- compatibility projections for existing ready document output without
  inventing actors, pipeline provenance, malware status, or publication
  evidence; and
- retrieval gating so native output is visible only through the active
  publication.

Supported parsing formats remain the established `pdf`, `docx`, `md`, and
`txt` adapters. This checkpoint added no dependency and changed no lockfile.

## Preserved architecture and decisions

Milestones 4–6 authority, append-only evidence, controlled execution,
knowledge-graph, Trace, outbox, collaboration, and exact-scope contracts are
preserved. The Indexer is technical infrastructure, not an agent. It cannot
grant access, make semantic catalog decisions, create relationships, archive
or delete sources, approve itself, or broaden a source’s visibility.

Source provenance and component configuration remain distinct. The immutable
request and revision carry the exact source version and checksum. The reusable
pipeline manifest carries output-affecting component identity and
configuration. Rejected alternative: including a document-specific version
identity in the manifest. That would conflate source evidence with pipeline
configuration and prevent required same-workspace cross-document
deduplication. Rejected alternative: mutable “current index” rows without
history. That would lose reconstruction, supersession, rollback, and audit
evidence. Rejected alternative: publication during construction. That would
make unused, canceled, revoked, or incomplete output retrievable.

The implementation keeps build and publication as explicit methods on the
established scoped `IngestionService`. Separate pass-through
`IndexBuildService` and `IndexPublicationService` wrappers were rejected
because they would add parallel abstractions without changing the transaction
or authority boundary.

## Trust boundaries, actors, and data

Protected actors are the authenticated requester, current workspace
membership, API process, bounded local worker execution, database role,
private storage adapter, parser subprocess, and embedding provider adapter.
Network location and possession of an opaque identifier grant no authority.

Entry points are the five scoped APIs and internal request processor. Trust
boundaries are browser to API, API/worker to PostgreSQL, worker to private
document storage, parent worker to isolated parser, and worker to the approved
embedding adapter.

Affected data classes are source-version checksum and binding, normalized
text, allowlisted metadata, chunk content and source locations, embeddings,
pipeline configuration, request/lifecycle state, immutable revision and
publication evidence, Trace, audit, domain events/outbox, safe failure codes,
and the active retrieval projection. Raw checksums, storage keys, vectors,
private manifests, and authority details are operational/private and are not
returned by the new APIs.

Likely attacks and failures include identifier substitution, cross-workspace
dedup disclosure, idempotency replay, duplicate delivery, concurrent
publication, stale membership or authority, changed source bytes, canceled
work, parser escape or resource exhaustion, corrupt input, nondeterministic
dependency output, partial transactions, private-manifest disclosure, and
unsafe production activation.

## Constitutional controls and evidence

| Control                              | Implementation and evidence                                                                                                                                                                      | Result                        |
| ------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------- |
| Deny by default and tenant isolation | Server-derived principal plus current sharing/membership authority; exact workspace/canvas/document/version joins; publication revalidation; cross-workspace negative test                       | Pass                          |
| Immutable evidence                   | ORM mutation guards, database update/delete triggers, composite scope constraints, closed registries, deterministic identities                                                                   | Pass                          |
| Determinism and provenance           | Canonical JSON manifest, versioned components, source/revision digests, ordered chunk/vector manifests, exact actor/scope/Trace linkage                                                          | Pass                          |
| Idempotency and concurrency          | Scoped key/digest uniqueness, duplicate replay, conflict rejection, document row lock, retrieval-head lock, publication uniqueness, savepoint reconciliation                                     | Pass                          |
| Cancellation and stale work          | Append-only cancel generation and transitions; canceled/completed, changed-source, and revoked-authority publication fences                                                                      | Pass                          |
| Failure atomicity                    | Build and publication transactions are separate; injected build failure leaves no artifact/revision/chunk/vector/publication fragment; safe failure/Trace/event evidence is committed separately | Pass                          |
| Parser boundary                      | Spawned process, disabled socket creation, bounded wall time, configured CPU/memory limits where the operating system supports them, safe closed error registry                                  | Pass with platform limitation |
| Configuration integrity              | Closed modes and bounded settings; development/test/demo default to private legacy compatibility; staging/production reject publication enablement before 7.3                                    | Pass                          |
| Privacy and minimization             | Safe API allowlists; no raw hash, key, vector, private manifest, hidden content, or authority internals; dedup never queries across workspaces                                                   | Pass                          |
| Retrieval safety                     | Completed unpublished native output produces insufficient context; active published revision alone advances native retrieval                                                                     | Pass                          |
| Accessibility                        | Named buttons, keyboard-operable controls, polite live status, safe error alert, disabled duplicate action while cancellable                                                                     | Pass                          |
| Migration and identifiers            | One direct head; immutable hash ledger; dialect-aware UUID handling; SQLite and PostgreSQL 17 cycles; representative legacy backfill and trigger proof                                           | Pass                          |
| Dependencies and secrets             | No dependency or lockfile change; installed local tools only; static scans and diff review required before commit                                                                                | Pass                          |
| Production clean-object requirement  | Staging/production publication mode is forced disabled and the legacy processing path returns safe `publication_disabled` before parsing/indexing                                                | Pass as required disablement  |

Parser address-space and CPU enforcement is active on platforms that provide
the Python `resource` module. On Windows the isolated process and wall timeout
remain active, while the local process does not claim POSIX resource-limit
evidence. Production capability remains disabled until the containerized or
managed 7.3 boundary proves the complete hostile-object gate.

## Operations, diagnostics, and response

Durable request transitions, safe failure records, publication generations,
audits, Trace, and domain events provide queryable inputs for throughput,
stage duration, freshness, coverage, failure, drift, dedup reuse, cancellation,
and publication-conflict metrics without source content or raw private
identifiers. Live exporter dashboards and alert delivery remain owned by
checkpoint 7.5; they are not claimed here. Production publication is disabled
until that later operational chain and the 7.3 clean-object gate are available.

Operational owner: application/platform engineering. Security or privacy
escalation goes to the security/privacy owner; a suspected tenant disclosure,
malicious source, corrupt revision, or agent overreach requires immediate
publication disablement, preservation of immutable evidence, authority
revocation where applicable, scope review, and incident handling under the
existing constitution.

Backlog or stale-index diagnosis uses latest request transition, safe failure,
Trace, audit, outbox, revision, publication, and retrieval-head generation.
Raw source content is not added to diagnostics.

## Capacity and cost limits

- parser wall timeout: 30 seconds by default, configurable from 1–300 seconds;
- parser memory limit: 512 MiB by default, bounded from 64 MiB–2 GiB;
- parser CPU limit: 30 seconds by default, bounded from 1–300 seconds;
- active requests: 10 per workspace by default, bounded from 1–100;
- existing file, page, extracted-character, chunk, overlap, embedding batch,
  request-rate, and provider limits remain in force and are included in the
  relevant manifest where they affect output;
- no unbounded retry loop, recursive indexing, cross-workspace lookup, or
  provider fallback is introduced.

Shared distributed counters, durable delivery/dead-letter state, lease
hardening, and production worker capacity are checkpoint 7.4 scope. Their
absence cannot weaken this checkpoint because production publication is
disabled.

## Disablement, rollback, and recovery

Immediate kill switch: set `OPENCANVAS_INDEXER_PUBLICATION_MODE=disabled`.
Staging and production reject any other value. With publication disabled,
native completed output remains invisible and the legacy processing path
fails safely before parsing or indexing.

Before any 7.2 data is relied on in a disposable validation database,
downgrade to `20260725_0025` removes only 7.2-owned structures and preserves
legacy documents, versions, chunks, and embeddings. After reliance, do not
downgrade. Restore the database through the existing protected backup/PITR
process or apply a reviewed forward migration, verify source/version and
manifest digests, rebuild from the private canonical source, and compare the
new revision/publication evidence before advancing a head.

Existing ready rows are compatibility projections. An authorized reindex
creates native evidence. No migration fabricates a clean scan, actor,
component version, or publication.

Immutable native evidence intentionally blocks the legacy hard-delete path
with `409 document_index_history_retained`. Archival/deletion policy is an
explicit 7.2 exclusion. Until that later policy exists, the safer result is to
retain the source and evidence rather than cascade-delete or partially delete
history. Workspace-authorized data export/backup retains the database evidence
and source according to the existing private-storage policy; no new third
party receives it.

Cleanup evidence: disposable PostgreSQL role/database state was removed by
the test fixture; parser children terminate in `finally`; browser and demo
processes are bounded by their runners; generated test reports are removed
before commit.

## Validation evidence

Commands below are described from the repository root; all used installed
local tools.

- Focused Indexer, runtime, and document suite before the final two
  acceptance-only test additions:
  `pytest -q apps/api/tests/test_indexer.py apps/api/tests/test_database_runtime.py apps/api/tests/test_document_processing_retrieval.py`
  — 35 passed.
- Final complete Indexer module, including normalized-content deduplication,
  component drift, and source-change fencing:
  `pytest -q apps/api/tests/test_indexer.py` — 9 passed.
- Focused domain-event correction plus real Indexer events:
  `pytest -q apps/api/tests/test_domain_events.py apps/api/tests/test_indexer.py`
  — 20 passed.
- Representative SQLite backfill/trigger/cycle:
  `pytest -q apps/api/tests/test_indexer_migration.py` — 1 passed.
- Migration validator: `python scripts/validate_migrations.py` — clean upgrade
  to `20260726_0026`, downgrade to `20260725_0025`, and re-upgrade to
  `20260726_0026` passed with integrity and identifier checks.
- Disposable PostgreSQL focused campaign:
  `pytest -q apps/api/tests/test_indexer_postgres.py` with the guarded local
  PostgreSQL test URL — 1 passed; PostgreSQL 17, pgvector, exact trigger
  catalog, domain-event constraint, downgrade, and re-upgrade proved.
- Full application backend regression excluding separately validated
  migration modules: 542 passed, 2 deselected, 1 known Starlette warning, and
  1 stale generic event-fixture failure. The test fixture was corrected; the
  required focused rerun above passed. Per the resource-control rule, the
  14-minute broad suite was not repeated after a test-only correction.
- An earlier oversized backend invocation that included every historical
  migration module exceeded the 15-minute command window and produced no
  result. It was not repeated; dedicated migration evidence is reported
  separately.
- Full API Ruff passed. Strict mypy passed for 87 source files. Python
  compilation passed for affected modules.
- Full frontend regression from `apps/web`: 17 files and 75 tests passed;
  TypeScript, ESLint with zero warnings, Prettier, and Next.js production build
  passed.
- Chromium document workflow: 1 passed, including ready-source preview,
  reindex queued status, cancellation, grounded selected-context answer,
  exact citation resolution, insufficient-evidence behavior, and safe delete
  behavior for the legacy fixture.
- Deterministic demo reset, persisted-provenance check, and startup smoke
  passed at sole head `20260726_0026`.

The first root-scoped frontend invocation did not load the web project’s
Vitest aliases/jsdom or ESLint configuration. It is recorded as an invalid
invocation, not product evidence. The correctly scoped full frontend commands
above passed.

Final repository hygiene, secret/private-path, documentation, whitespace,
diff, staged-diff, protected-ref, stash, recovery-artifact, clean-tree, and
no-upstream checks are recorded after documentation completion and commit.

## Limitations, blocked capabilities, and revalidation

- Production publication is disabled until 7.3 proves private object
  lifecycle, quarantine, current malware evidence, checksum binding, and the
  clean-object gate. Owner: application/platform and security engineering.
  Severity if enabled early: critical. Compensating control: configuration
  validation plus legacy processor kill switch. Corrective action: complete
  7.3. Revalidate on any storage, parser, scan, publication-mode, or deployment
  change. Disablement: `OPENCANVAS_INDEXER_PUBLICATION_MODE=disabled`.
- Windows does not prove POSIX parser CPU/address-space enforcement. Owner:
  platform engineering. Remaining risk is bounded locally by process
  isolation, no parser socket creation, input limits, and wall timeout;
  production remains disabled. Revalidate in the approved production-shaped
  parser runtime during 7.3. No exception permits production activation.
- Live metrics export, alerts, managed backup restoration, capacity/soak, and
  provider outage exercises are not claimed by this local checkpoint.
  Production publication remains disabled; checkpoints 7.5–7.7 own their
  broader provider-shaped proof without rewriting 7.2 evidence.
- Upload sessions, storage-object lifecycle, malware evidence, durable
  queue/dead-letter state, shared rate counters, Librarian proposals,
  autonomous metadata, taxonomy, and archival/deletion decisions are
  explicitly out of scope.
- No migration `0027`, Milestone 7.3 production code, Milestone 7.8 audit,
  Milestone 8 release work, deployment, or publication was started.

Evidence expires and must be revalidated when migration `0026` bytes, Indexer
models/services/APIs, parser or embedding dependency/version, output-affecting
configuration, authority/sharing semantics, retrieval projection, supported
formats, production mode, database dialect/version, or relevant frontend
workflow changes.
