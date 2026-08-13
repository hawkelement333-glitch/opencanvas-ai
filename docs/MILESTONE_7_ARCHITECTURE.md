# Milestone 7 Production Hardening Architecture

Date: 2026-07-27

Current status verified 2026-08-13: architecture and checkpoints 7.1–7.7 are
complete and committed. The retained checkpoint 7.7 terminal lifecycle chain
validates through `MILESTONE_7_7_COMPLETE` at
`b191a392922f94557e6ebf5914113b5e229ab00e`. Checkpoint 7.8 has begun only its
first authorized audit surface, architecture and checkpoint scope, on the
local-only `milestone-7-8-production-readiness-audit-local` branch. Historical
checkpoint sections below retain the status and authority that applied when
they were written.

Checkpoint 7.2 implementation record: migration `20260726_0026` is the sole
head and direct child of `20260725_0025`. The deterministic Indexer, immutable
revision/publication evidence, active retrieval-head projection, scoped APIs,
and bounded status/cancel UI now implement this architecture. Production
publication remains fail-closed until checkpoint 7.3 supplies and proves the
clean-object gate.

Checkpoint 7.3 implementation record: migration `20260726_0027` is the sole
head and direct child of `20260726_0026`. Provider-neutral private versioned
storage, quarantine-only capabilities, hostile-input controls, trusted
immutable scanner results, checksum-verified promotion, clean-consumer gates,
and lifecycle/recovery evidence now realize sections 10.1–10.6. See
[`MILESTONE_7_3_OBJECT_STORAGE_UPLOAD_SECURITY_MALWARE_QUARANTINE_HANDOFF.md`](MILESTONE_7_3_OBJECT_STORAGE_UPLOAD_SECURITY_MALWARE_QUARANTINE_HANDOFF.md).

Checkpoint 7.4 implementation record: migration `20260726_0028` is the sole
head and direct child of `20260726_0027`. Durable request/job/delivery/attempt/
retry/outcome/dead-letter/replay identities, generation-fenced PostgreSQL
workers, atomic existing evidence integration, and the provider-neutral
shared-limit contract now realize the approved work and rate-limit boundary.
The Redis adapter requires credential-free private `rediss`, Microsoft Entra
managed-identity tokens, opaque HMAC keys, and one `{limits}` hash slot for
atomic multi-key Lua. Deployed modes refuse the local in-memory fake. See
[`MILESTONE_7_4_DURABLE_QUEUES_SHARED_LIMITS_HANDOFF.md`](MILESTONE_7_4_DURABLE_QUEUES_SHARED_LIMITS_HANDOFF.md).

Checkpoint 7.5 implementation record: the provider-neutral operational
telemetry layer now validates closed structured logs, bounded metrics and
W3C-compatible spans; uses environment/deployment-scoped pseudonymous
correlations; enforces redaction, cardinality, buffering, timeout, retry,
sampling, baggage, and shutdown limits; and separates public readiness from
allowlisted operator health. Versioned signal, dashboard, provisional
objective, alert, privacy/retention, escalation, integrity-monitor, and
runbook artifacts realize section 13 without a migration. Product Trace,
audit, events, outbox, and activity remain authoritative and independent.
See [`OBSERVABILITY_ARCHITECTURE.md`](OBSERVABILITY_ARCHITECTURE.md).

Checkpoint 7.6 implementation record: the recovery-only Valkey adapter and
immutable deployment image support the isolated managed recovery exercise.
Managed full restore, PITR, encrypted portable recovery, failback, private
effect-lock validation, evidence signing, role revocation, and zero-residue
cleanup passed. Results 14–24 passed and the final Stage 3 decision is
`DEPLOYMENT VALIDATED`. The measured restore durations are exercise upper
bounds, not production SLOs. Exact Stage 3 posted cost remains unavailable
because Azure returned `429` and usage posting is delayed; category logs did
not arrive before cleanup although private metrics were confirmed. See
[`MILESTONE_7_6_BACKUP_RESTORE_DISASTER_RECOVERY_HANDOFF.md`](MILESTONE_7_6_BACKUP_RESTORE_DISASTER_RECOVERY_HANDOFF.md)
and [`PRODUCTION_RECOVERY_RUNBOOK.md`](PRODUCTION_RECOVERY_RUNBOOK.md).

PostgreSQL compatibility amendments:
[`MILESTONE_7_POSTGRESQL_MIGRATION_0005_COMPATIBILITY_AMENDMENT.md`](MILESTONE_7_POSTGRESQL_MIGRATION_0005_COMPATIBILITY_AMENDMENT.md).
Live PostgreSQL 17 validation proved that historical revision
`20260718_0005` cannot recreate `workspaces` while
`canonical_objects_workspace_id_fkey` depends on `workspaces_pkey`. One
documentation-governed, hash-ledgered compatibility correction to migration
`0005`, plus focused guarded-runner error-preservation work, is authorized.
Subsequent clean-chain validation proved that migrations `20260725_0023` and
`20260725_0024` apply the same unsafe comma parser to
PostgreSQL-canonicalized check expressions. The
[`MILESTONE_7_POSTGRESQL_MIGRATIONS_0023_0024_COMPATIBILITY_AMENDMENT.md`](MILESTONE_7_POSTGRESQL_MIGRATIONS_0023_0024_COMPATIBILITY_AMENDMENT.md)
authorizes corrections to exactly those two files within the same future
combined checkpoint. Live implementation validation then proved that
`0023`'s derived-table resource backfill independently resolves untyped nulls
as `text` before assignment to UUID destinations. The
[`MILESTONE_7_POSTGRESQL_MIGRATION_0023_UUID_NULL_COMPATIBILITY_AMENDMENT.md`](MILESTONE_7_POSTGRESQL_MIGRATION_0023_UUID_NULL_COMPATIBILITY_AMENDMENT.md)
authorizes only explicit PostgreSQL UUID typing for those placeholders and
focused tests. The next live attempt reached `0023` trigger installation and
proved that both affected migrations contain references to an undefined
mutation function. The
[`MILESTONE_7_POSTGRESQL_TRIGGER_FUNCTION_COMPATIBILITY_AMENDMENT.md`](MILESTONE_7_POSTGRESQL_TRIGGER_FUNCTION_COMPATIBILITY_AMENDMENT.md)
authorizes exactly four references to reuse the existing equivalent deny-all
trigger function. A later combined validation proved that migration
`0021` and its matching ORM metadata leave the `current_role` table-column
identifier unquoted in a textual check, so PostgreSQL resolves session
`CURRENT_ROLE` instead. The
[`MILESTONE_7_POSTGRESQL_MIGRATION_0021_CURRENT_ROLE_COMPATIBILITY_AMENDMENT.md`](MILESTONE_7_POSTGRESQL_MIGRATION_0021_CURRENT_ROLE_COMPATIBILITY_AMENDMENT.md)
selects an identical explicitly quoted textual expression for migration and
ORM metadata and requires exact role, initial-owner, session-independence, and
schema-parity proof. With that candidate correction present, the next live
attempt proved that `_backfill_owner_memberships()` also leaves
`current_role` bare in the raw transition `INSERT` target list. The
[`MILESTONE_7_POSTGRESQL_MIGRATION_0021_BACKFILL_CURRENT_ROLE_COMPATIBILITY_AMENDMENT.md`](MILESTONE_7_POSTGRESQL_MIGRATION_0021_BACKFILL_CURRENT_ROLE_COMPATIBILITY_AMENDMENT.md)
authorizes quoting exactly that one additional SQL identifier with no data,
scope, row-count, ownership, or history change. This is not a general
relaxation of migration
immutability. That combined PostgreSQL and SQLite validation gate subsequently
passed, permitting checkpoint 7.2 and migration `0026` to proceed.

Implementation-grounded clarification: checkpoint 7.1 uses the established
`Settings`, SQLAlchemy, Alembic, lifespan, and health boundaries. PostgreSQL
17, pgvector `0.7.0` or newer, exact configured schema head,
`READ COMMITTED`, bounded pool acquisition, connection recycling, statement,
lock, and idle-transaction timeouts, verified TLS in deployed modes, dedicated
API/worker/migration credential declarations, and one PostgreSQL advisory lock
are enforced without an application migration. Public readiness collapses
database failures to a safe dependency response. Managed-provider validation
remains a later controlled staging operation, not evidence produced locally.

Baseline branch: `milestone-6-7-final-collaboration-security-audit-local`

Baseline commit: `b355cdeac98e866e2de06bde650fff3c21f4c63d`

Baseline Alembic head: `20260725_0025`

Implementation branch: `milestone-7-production-hardening-architecture-local`

## 1. Purpose

Milestone 7 converts the completed local Mobius Core application into a
production-operable system without weakening the authority, evidence, graph,
workflow, agent, or collaboration contracts completed in Milestones 4–6.

The milestone owns:

- production runtime foundations and managed PostgreSQL;
- deterministic, provenance-complete indexing and reindexing;
- private managed object storage, hostile-upload quarantine, and malware
  scanning;
- durable background work, bounded retries, cancellation, leases,
  dead-letter handling, and shared rate limits;
- privacy-preserving observability and operational control;
- backup, restore, rollback, and disaster recovery;
- load, capacity, resilience, and infrastructure-security validation; and
- a final production-readiness audit before Milestone 8.

This document makes architecture decisions only. It adds no production code,
test, migration, dependency, configuration, CI, deployment, provider account,
or live infrastructure.

## 2. Preserved contracts

Milestone 7 must preserve these permanent rules:

1. Authority is deny by default and derived by the server.
2. User, membership, workspace, canvas, resource, immutable version, action,
   approval, and execution identities remain distinct.
3. Visual adjacency, possession of an identifier, storage access, queue
   delivery, or Indexer possession never grants authority.
4. Revocation is monotonic. A stale request or worker cannot publish an effect
   or result after authority, membership, share, source, or cancellation state
   changes.
5. Append-only audit, Trace, event provenance, lifecycle, approval, effect,
   rollback, and collaboration evidence remains append only.
6. Existing domain events, transactional outbox, Trace, audit, and activity
   projections are extended. Milestone 7 creates no parallel event, outbox,
   audit, or Trace system.
7. Uploaded bytes remain untrusted until validation and the required malware
   scan produce a current `clean` decision.
8. Untrusted content does not become trusted evidence merely because it was
   parsed, embedded, indexed, or returned by a model.
9. Source bytes, parsed text, normalized text, chunks, deterministic metadata,
   vector artifacts, index revisions, citations, comments, workflow outputs,
   and agent proposals remain separate typed records.
10. Protected publication rechecks current authority and lifecycle state in
    the committing transaction.
11. Retries and duplicate deliveries cannot duplicate durable effects,
    publication, Trace roots, audit evidence, or activity.
12. Production secrets never enter source control, client bundles, logs,
    metrics, distributed traces, Trace, audit, events, activity, or error
    responses.
13. Development and the deterministic demo retain local substitutes and do not
    depend on live providers, managed services, network access, or paid
    credentials.

## 3. Repository constraints and current gaps

The architecture extends these existing seams:

- `Document`, `DocumentVersion`, `DocumentFile`, `DocumentChunk`,
  `DocumentEmbedding`, and `DocumentProcessingJob` already provide scoped
  document identities, byte hashes, versions, chunks, embeddings, persisted
  jobs, idempotency keys, and worker heartbeats.
- `DocumentStorage` already has memory, local, and private S3-compatible
  adapters with opaque keys and no public object URLs.
- document processing already validates bounded uploads, extracts supported
  formats, chunks content, writes embeddings, records safe failures, and
  supports retry.
- controlled workflow and agent execution already use ownership, leases,
  retry bounds, cancellation, authority generations, stale-result
  suppression, Trace, audit, and effect evidence.
- domain events already have immutable provenance, a transactional outbox,
  bounded delivery attempts, leases, and idempotent activity projections.
- Milestone 6 already supplies memberships, roles, typed sharing, ownership,
  authority snapshots, revocation generations, and exact invoker attribution.
- configuration already has explicit demo, development, test, staging, and
  production modes and fails closed for missing production dependencies.

The proved production gaps are:

- no managed PostgreSQL runtime validation, connection-budget proof, failover
  exercise, or production query profile;
- no quarantine object class, upload session, malware evidence, clean-object
  promotion, scanner adapter, or parser sandbox;
- current document chunks are replaceable processing output rather than
  immutable, provenance-complete index revisions;
- no complete parser, normalizer, metadata extractor, chunker, embedding, and
  Indexer manifest;
- no explicit publication record separating a built index from the retrieval
  head;
- the document queue is durable but brokerless, models retries as processing
  attempts incompletely, and lacks full lease generations, dead-letter
  evidence, and bounded administration;
- rate limits are per process and therefore bypassable across replicas;
- private S3-compatible storage exists but has not been externally validated
  and has no quarantine/retention/versioning contract;
- operational telemetry, alerts, service objectives, and incident evidence are
  not production-defined;
- backup and rollback procedures are documented but not exercised against
  managed infrastructure;
- capacity, stress, soak, spike, dependency-failure, and recovery limits are
  not measured;
- current readiness documents contain pre-Milestone 5/6 statements about
  collaboration and process-local events that are no longer true.

No repository contradiction prevents this architecture.

## 4. System topology

The production topology is provider neutral:

```text
browser
  -> trusted edge / TLS / request limits
  -> web
  -> API
       -> managed PostgreSQL + pgvector
       -> shared atomic rate-limit store
       -> private object-storage interface
       -> scanner interface
       -> durable work-queue interface
       -> model and embedding provider interfaces
       -> telemetry interface
  -> worker pools
       -> durable work queue
       -> managed PostgreSQL
       -> quarantine / clean object storage
       -> isolated parsers
       -> scanner and embedding interfaces

managed control plane
  -> secrets and workload identities
  -> backup / PITR
  -> logs, metrics, distributed traces, alerts
  -> immutable operational exercise evidence
```

PostgreSQL remains the application system of record. Object storage is the
system of record for immutable source bytes. A queue delivery is only a wake-up
hint; it is never job truth, authority, publication evidence, or proof of
completion. Telemetry is operational evidence and never replaces application
audit or Trace.

## 5. Scope and tenant model

The current repository has no separate `Tenant` entity. Creating one during
production hardening would invent product semantics and weaken the completed
workspace authority model. For Milestone 7:

- the authenticated user is derived from the server session;
- membership and its authority generation are resolved server side;
- workspace is the primary data-isolation domain;
- canvas and resource scope are resolved through typed parent relationships;
- “tenant isolation” means that no user, job, object, index, telemetry item,
  recovery operation, or operator action can cross the authorized workspace
  boundary;
- a user may belong to multiple workspaces, but every operation is bound to
  one exact workspace unless an existing closed API explicitly returns a
  separately authorized list;
- no client-selected workspace, object key, queue field, or telemetry tag is
  authoritative.

Application authorization and composite scope constraints remain mandatory.
Database roles are least privilege: the API, worker, migration runner, backup
operator, and read-only observability jobs use separate credentials.

### 5.1 PostgreSQL row-level security decision

Milestone 7 does not make PostgreSQL row-level security a completion
dependency. The current schema represents scope through a mix of direct
workspace columns and typed parent joins, and authenticated users may hold
several workspace memberships. Introducing session-variable allowlists across
pooled API, worker, migration, backup, and maintenance connections would add a
second authorization engine whose bypass and reset behavior is not currently
proved.

The selected design is:

- preserve the centralized Milestone 6 authorizer;
- preserve and extend composite user/workspace/canvas/resource constraints;
- use separate least-privilege database roles;
- require transaction-scoped server-derived identifiers for all protected
  repository calls;
- validate tenant isolation on managed PostgreSQL, including pool reuse,
  failover, retries, stale authority, and worker paths;
- deny direct application use of migration or backup roles; and
- document RLS as a later defense-in-depth amendment only if a complete policy
  map, pool-reset proof, maintenance strategy, and cross-table test suite are
  approved.

This is a deliberate rejection, not an unresolved architecture decision.

## 6. Checkpoint dependency order

The required order is:

1. **7.1 Production Runtime Foundation and Managed PostgreSQL**
2. **7.2 Deterministic Indexer and Ingestion Pipeline**
3. **7.3 Object Storage, Upload Security, and Malware Quarantine**
4. **7.4 Durable Queues, Workers, Retries, and Shared Rate Limits**
5. **7.5 Observability and Operational Controls**
6. **7.6 Backup, Restore, Rollback, and Disaster Recovery**
7. **7.7 Load, Capacity, Resilience, and Infrastructure Security**
8. **7.8 Final Production-Readiness Audit**

The implementation remains sequential because each checkpoint must finish,
validate, document, and commit its complete migration—if any—before the next
checkpoint. Later checkpoints may exercise earlier systems but may not rewrite
their committed migrations.

Checkpoint 7.2 may initially exercise the current private storage adapter.
Checkpoint 7.3 then adds the required production quarantine and clean-object
gate before any production Indexer publication is enabled. Therefore 7.2 is
not production-enabled on its own.

## 7. Deterministic Indexer

### 7.1 Identity

Every ingestion and index operation binds:

- server-derived user and current membership identity;
- workspace and canvas;
- document and immutable `DocumentVersion`;
- storage object version and SHA-256 checksum;
- ingestion request and request digest;
- job run and processing attempt;
- parser, normalizer, metadata extractor, chunker, embedding materializer, and
  Indexer component versions;
- an immutable pipeline manifest digest;
- source, normalized-content, metadata, chunk, and vector-artifact digests;
- index revision and publication identities;
- authority and cancellation generations;
- Trace root and audit identity.

Opaque UUIDs are public identities. Raw storage keys, checksums, component
internals, and infrastructure identifiers are private operational data.

### 7.2 Lifecycle

The closed lifecycle is:

```text
requested
  -> quarantined
  -> scanning
  -> rejected | clean
  -> queued
  -> parsing
  -> normalizing
  -> chunking
  -> indexing
  -> completed
  -> published
```

`failed`, `canceled`, and `superseded` are terminal for one request or
revision. Retry creates a new append-only attempt under the same job run; it
does not erase the failed attempt. A superseding source version never mutates
the prior version or its published index revision.

### 7.3 Determinism contract

The pipeline manifest is canonical JSON over output-affecting pipeline inputs:

- parser name, semantic version, build digest, and closed options;
- normalizer version and Unicode/newline/whitespace rules;
- metadata-extractor version and allowlisted fields;
- chunker version, tokenization rules, size, overlap, and boundary rules;
- embedding provider, model, dimensions, request format, and materializer
  version;
- Indexer version and schema version; and
- every server-owned configuration value that can affect output.

Source checksum and immutable source-version identity are bound separately and
immutably on the ingestion request and index revision. They are deliberately
not part of the reusable pipeline-manifest identity: including a
document-specific version identity would prevent the required workspace-scoped
exact and normalized-content deduplication. Rejected alternative: one manifest
per document version. It preserved provenance but made cross-document
same-workspace reuse impossible and conflated source evidence with component
configuration. The selected split preserves both provenance and safe reuse.

The same source bytes and the same manifest must produce the same normalized
text, metadata, chunk boundaries, chunk contents, stable chunk identities, and
structural index digest. Timestamps, random identifiers, host paths, locale,
timezone, dependency iteration order, and worker identity cannot affect those
outputs.

External vector providers may not guarantee bit-identical recomputation.
Mobius therefore treats the first successful vector artifact for an exact
manifest as immutable canonical materialization. Duplicate delivery reuses it.
If later recomputation under the same manifest yields a different artifact
digest, the attempt fails closed with `nondeterministic_dependency_output`;
it cannot replace or publish over the canonical revision. An intentional
provider/model/configuration change creates a new manifest and index revision.

### 7.4 Deterministic adapters

Parsers are closed, versioned adapters for supported types. They run in an
isolated process or container with:

- no network access;
- a read-only input;
- a write-only bounded scratch area;
- non-root identity;
- CPU, memory, file, page, object-count, recursion, and wall-clock limits;
- dependency/build digest attribution; and
- a structured result envelope with safe failure codes.

Normalization removes unstable container metadata and applies explicit
Unicode, newline, heading, table, and whitespace rules. Deterministic metadata
extractors emit only allowlisted facts present in or mechanically derived from
the source. They cannot invent titles, tags, classifications, taxonomies,
relationships, archival decisions, or evidence.

### 7.5 Stable chunk and revision identity

Stable private chunk identity is derived from a server-owned namespace plus:

```text
workspace_id
document_version_id
pipeline_manifest_digest
chunk_index
chunk_content_digest
```

The derivation is not exposed as a content oracle. An immutable index revision
contains the exact source version, normalized artifact digest, ordered chunk
manifest, deterministic metadata manifest, vector-artifact manifest, pipeline
manifest, actor/system identity, and evidence references.

Current `DocumentChunk` and `DocumentEmbedding` records become a compatibility
projection during migration. New retrieval reads the active immutable
publication; historical index revisions remain reconstructable.

### 7.6 Deduplication

- Byte-level deduplication is permitted only within one workspace and security
  class.
- Normalized-content and deterministic near-duplicate fingerprints are
  workspace-scoped diagnostic facts, never cross-workspace discovery.
- A duplicate upload does not reveal whether another user or workspace owns
  the same bytes.
- Safe reuse requires current access to the same immutable source version and
  an exact matching pipeline manifest.
- Duplicate request delivery returns the existing request/job/revision result
  for the same idempotency key and digest.
- Reusing an idempotency key with another digest fails with conflict.
- Publication has a uniqueness constraint so one revision cannot be published
  twice into the same retrieval head generation.

### 7.7 Publication

Building an index and publishing it are separate operations. Publication is a
short database transaction that locks the always-present source document and
the existing retrieval head, if any, then rechecks:

- current user or system authority;
- active membership, workspace, canvas, document, and source version;
- matching source checksum and storage object version;
- current `clean` malware decision;
- no cancellation, deletion, archival, or supersession;
- complete parser and provenance manifests;
- successful immutable index revision;
- matching job lease and authority/cancellation generations; and
- the required event, outbox, Trace, audit, and activity inputs.

The transaction appends the publication record, advances the active retrieval
head, emits the domain event and outbox record, and records Trace/audit
references atomically. If any check fails, no retrieval head moves. A stale
worker may retain an unused immutable artifact but cannot commit publication.

### 7.8 Failure registry

The closed safe failure registry includes:

- `unsupported_format`;
- `partial_upload`;
- `checksum_mismatch`;
- `malware_detected`;
- `scan_unavailable`;
- `scan_timeout`;
- `suspicious_content`;
- `encrypted_archive`;
- `archive_limit_exceeded`;
- `corrupt_source`;
- `parser_crash`;
- `parser_timeout`;
- `parser_resource_limit`;
- `normalization_failed`;
- `metadata_extraction_failed`;
- `embedding_failed`;
- `nondeterministic_dependency_output`;
- `storage_unavailable`;
- `database_unavailable`;
- `authority_revoked`;
- `membership_revoked`;
- `resource_revoked`;
- `source_changed`;
- `superseded`;
- `canceled`;
- `lease_lost`;
- `publication_conflict`; and
- `internal_safe_failure`.

Only explicitly transient failures are retryable. Unsupported, infected,
corrupt, policy-rejected, superseded, revoked, canceled, and deterministic
drift failures are terminal until a new authorized request or version exists.

## 8. Indexer and Librarian boundary

The **Indexer** is deterministic Milestone 7 infrastructure. It may:

- ingest a specifically authorized immutable source version;
- validate, parse, normalize, chunk, and extract closed deterministic metadata;
- calculate hashes and scoped duplicate fingerprints;
- materialize an immutable index revision;
- publish an authorized completed revision;
- perform bounded idempotent reindexing;
- report lifecycle, freshness, coverage, drift, and safe failures; and
- emit bounded events, Trace/audit evidence, activity, and metrics.

The Indexer may not:

- make discretionary catalog decisions;
- invent titles, tags, taxonomies, classifications, or relationships;
- archive, delete, restore, share, or broaden access;
- alter source bytes or replace an immutable source version;
- cross workspace boundaries;
- approve itself, grant authority, activate agents, or accept proposals; or
- suppress conflicts, failures, provenance, or historical revisions.

The **Librarian** remains a governed Milestone 9 agent. It may later make
evidence-backed proposals about titles, tags, taxonomy, duplicates, conflicts,
staleness, archival review, reindexing, metadata corrections, relationships,
and catalog quality. Those proposals require current authority, a controlled
workflow, human review where required, and complete Trace/audit evidence. The
Indexer and Librarian cannot be combined into an unrestricted autonomous
system.

## 9. Managed PostgreSQL architecture

### 9.1 Version and extensions

- Production supports one documented PostgreSQL major version at a time; the
  initial target is PostgreSQL 17 with a compatible, pinned pgvector version.
- Staging uses the same major version, extensions, parameter class, pooling
  mode, migration procedure, and representative schema.
- SQLite remains a bounded local/test substitute, not production evidence.

### 9.2 Connections and transactions

- API traffic uses a managed or independently operated transaction pool.
- Workers use a separate pool and connection budget.
- migrations and maintenance use direct, non-pooled administrative
  connections with distinct credentials.
- total API, worker, migration, health, observability, and emergency connection
  budgets stay below the managed service limit with reserved operator capacity.
- request transactions are short; external provider calls never hold database
  locks.
- protected publication uses row locks and the existing generation-fencing
  pattern.
- default transaction isolation is `READ COMMITTED`; serialization-sensitive
  operations use explicit locks, uniqueness, compare-and-swap generations, or
  `SERIALIZABLE` only where a focused proof requires it.
- statement, lock, idle-in-transaction, and connection-acquisition timeouts are
  explicit and emit safe classified failures.

### 9.3 Migration execution

- startup never runs migrations implicitly;
- one reviewed migration task obtains a PostgreSQL advisory lock keyed to the
  application schema;
- the task verifies expected current revision, direct parent, application
  compatibility window, and backup/recovery preconditions;
- only the migration role may change schema;
- API and worker roles cannot run DDL;
- old and new application revisions never run concurrently against an
  incompatible schema;
- additive expand/contract and forward-fix are preferred;
- production downgrade requires an approved, rehearsed recovery plan.

### 9.4 Read/write and failover behavior

The primary database is authoritative. Read replicas, if later enabled, serve
only explicitly stale-tolerant operational or analytical reads. Authority,
membership, publication, approvals, effects, audit, Trace, queue claims, and
read-after-write application paths always use the primary.

Managed failover must preserve committed transactions and may cause ambiguous
client outcomes. Every mutating API therefore uses idempotency keys and request
digests. After reconnect, the client resolves by durable request identity
rather than repeating a mutation blindly.

### 9.5 Maintenance and protection

- encryption in transit is required with certificate verification;
- managed encryption at rest and encrypted backups are required;
- credentials use workload identity or short-lived references when supported;
- autovacuum remains enabled and is monitored for table/index bloat and
  transaction-ID age;
- analyze cadence and vector-index maintenance are workload tested;
- slow queries use redacted fingerprints, never private parameters;
- production data is never copied to development;
- staging data is synthetic or irreversibly sanitized;
- break-glass access is time bounded, approved, logged, and reviewed.

## 10. Object storage and upload security

### 10.1 Provider interface

The existing `DocumentStorage` seam evolves into provider-neutral capabilities:

- `UploadSessionStore`;
- `QuarantineObjectStore`;
- `CleanObjectStore`;
- `ObjectVersionReader`;
- `ObjectRetentionController`; and
- `ObjectIntegrityVerifier`.

The reference production contract is private S3-compatible versioned object
storage. No undocumented vendor behavior is authoritative. Local filesystem
and in-memory substitutes remain available for demo and tests.

### 10.2 Object identity and keys

Database-owned opaque object and object-version UUIDs are authoritative.
Physical keys contain only random opaque segments under environment and
security-class prefixes:

```text
quarantine/{opaque-object-id}/{opaque-version-id}
clean/{opaque-object-id}/{opaque-version-id}
rejected/{opaque-object-id}/{opaque-version-id}
```

Keys do not include user names, email, workspace names, filenames, tenant
identifiers, source titles, or checksums. The database binds object versions
to exact workspace, canvas, document, and source version.

### 10.3 Upload protocol

1. An authenticated, CSRF-protected API request authorizes exact workspace,
   canvas, resource, size, type, checksum algorithm, and operation.
2. The server creates a one-time, short-lived upload session bound to those
   values and returns a signed quarantine-only upload capability.
3. Direct upload, if used, enforces checksum, maximum length, exact method,
   content type, expiry, and single object key. It cannot read, list, delete,
   overwrite, select another key, or target the clean prefix.
4. Completion verifies the provider object version, length, checksum, session
   state, current authority, and current resource lifecycle.
5. A completed object remains quarantined and unreadable to retrieval,
   parsers, models, previews, downloads, and Indexer publication.
6. Scan success records immutable evidence and promotes by server-side copy to
   a new clean object version; it never relabels unscanned bytes in place.
7. The clean copy checksum is verified before the quarantine version becomes
   eligible for retention cleanup.

Multipart sessions are bounded, expired automatically, and reconciled by an
orphan-cleanup job. Completion is idempotent.

### 10.4 Validation and hostile content

Validation checks:

- declared type, extension, signature-derived MIME, and supported-format
  registry;
- exact SHA-256 and size;
- maximum file, page, object, archive-entry, expansion-ratio, recursion,
  nesting, and decompressed-byte limits;
- password protection, encrypted archives, macros, active content, embedded
  executables, malformed structures, and suspicious links;
- scanner result, definition/version, engine version, timestamps, object
  version, and result digest.

Generic archives are not accepted in the initial production scope. Container
formats such as DOCX are opened only by bounded format-specific adapters.
Password-protected, macro-enabled, infected, suspicious, unsupported, timed
out, and indeterminate content fails closed.

### 10.5 Scanner contract

`MalwareScanner.scan(object_version, limits)` returns a signed/verified closed
result:

- `clean`;
- `infected`;
- `suspicious`;
- `unsupported`;
- `error`; or
- `timeout`.

Only `clean` permits promotion. Scanner unavailability, timeout, malformed
response, unknown version, signature failure, or result mismatch preserves
quarantine. A rescan is a new immutable scan record. An administrator may
request a rescan but cannot manually forge `clean`.

### 10.6 Access, retention, and deletion

- Buckets are private, public access is blocked, and encryption is required.
- Browser reads use the authenticated API or a short-lived, exact-object,
  response-bound signed URL after current authorization.
- Signed URLs never grant listing or another operation and are not logged.
- Versioning and deletion protection cover the documented recovery window.
- Legal hold is an operator-controlled policy boundary, not a user-visible
  claim until implemented.
- User deletion and retention workflows append evidence and respect approved
  legal/operational holds; the Indexer cannot decide them.
- Object cleanup is idempotent and reconciles database/object-store orphans
  without deleting an unverified target.

## 11. Durable queues, workers, retries, and cancellation

### 11.1 Selected queue strategy

`DurableWorkQueue` is a provider-neutral interface with:

- enqueue by opaque job-run/attempt identity;
- bounded claim;
- visibility extension;
- acknowledge;
- negative acknowledgement with classified retry time;
- dead-letter handoff; and
- health/depth signals.

The first production adapter uses PostgreSQL row claiming and
`FOR UPDATE SKIP LOCKED`, extending the existing
`DocumentProcessingJob` model. This avoids a database/broker dual-write and
preserves current job truth. An external broker may be added later behind the
same contract after equivalent duplicate-delivery, fencing, recovery, and
outbox tests. Queue technology never changes authority semantics.

### 11.2 Distinct identities

These concepts must not collapse:

| Concept        | Meaning                                                    |
| -------------- | ---------------------------------------------------------- |
| Request        | Authenticated user intent plus idempotency key and digest  |
| Domain state   | Current source, object, scan, and index lifecycle          |
| Job run        | Durable bounded work identity serving one accepted request |
| Queue delivery | At-least-once wake-up for one eligible attempt             |
| Worker lease   | Temporary fenced right to process that attempt             |
| Attempt        | Append-only execution evidence for one claim generation    |
| Retry          | Policy decision creating another eligible attempt          |
| Result         | Immutable candidate artifacts and outcome                  |
| Publication    | Separately authorized commit into retrieval                |

### 11.3 Lease and worker behavior

- workers have opaque deployment-generated identities, not user authority;
- claims use a lease owner, generation, acquisition time, expiry, and
  heartbeat;
- lease renewal is conditional on the same owner, generation, job state,
  authority generation, source version, and cancellation generation;
- a recovered or replaced worker increments the generation;
- a worker that loses its lease may finish local computation but cannot write
  authoritative state or publish;
- graceful shutdown stops claims, cancels provider calls where safe, and
  releases or lets leases expire;
- forced shutdown is recovered through expiry and a new generation;
- worker concurrency is bounded globally and by operation, workspace, source,
  provider, and dependency.

### 11.4 Retry and dead-letter policy

Retry classification is closed and server owned. Transient dependency,
connection, rate, and lease-interruption failures use bounded exponential
backoff with full jitter. Policy rejection, malware, corruption, unsupported
format, cancellation, revocation, supersession, and deterministic drift do not
retry automatically.

Every job declares a maximum attempt count and deadline. Reaching either
creates immutable dead-letter evidence and a safe domain failure. Replay
requires current operator action authority, a new replay request identity,
current source/scan/authority checks, a reason code, Trace/audit evidence, and
a fresh job generation. Replay never edits the old attempts.

Poison jobs cannot monopolize a worker pool. Per-resource serialization,
workspace concurrency caps, queue-age priorities, and circuit breakers prevent
retry storms and noisy-neighbor starvation.

### 11.5 Cancellation and publication

Cancellation increments a durable generation and records the actor, reason,
scope, and evidence. Workers check it:

- before claim;
- before storage/scanner/parser/model calls;
- between bounded stages;
- before artifact persistence;
- before retry scheduling; and
- in the publication transaction.

Cancellation is best effort for external computation but absolute for future
Mobius commits. A canceled or deadline-expired worker cannot publish.

### 11.6 Events and outbox

The existing domain-event transaction and outbox remain the only business
event delivery path. Job state changes append typed domain events in the same
transaction as durable job state. The outbox dispatcher may wake the queue
adapter, project activity, and notify telemetry adapters, but it cannot mark a
job complete. Duplicate outbox delivery is idempotent.

No raw queue payload, lease control, retry override, dead-letter record,
worker identity, or cross-scope job selector is exposed to ordinary browser
APIs.

## 12. Shared rate limits

`SharedRateLimiter` provides atomic consume, inspect-safe-result, and health
operations. The reference production semantics use a Redis-compatible atomic
token bucket or an equivalently tested managed store. In-memory limiting
remains test/demo only.

Server-owned limit keys use HMAC-derived opaque subjects and closed operation
names. Required dimensions include:

- unauthenticated network subject for authentication;
- authenticated user;
- workspace;
- resource;
- operation;
- dependency/provider;
- worker pool; and
- deployment-global emergency ceiling.

Indexing and reindexing also use queued concurrency and byte/page budgets;
HTTP request limits alone are insufficient.

Staging and production fail closed when the shared limiter cannot establish a
decision for authentication, invitations, uploads, comments, indexing,
reindexing, retrieval, workflows, agents, exports, mutations, or expensive
administration. They return safe `429` or dependency `503` with bounded
`Retry-After`; they never silently fall back to per-process unlimited access.
Liveness remains available, while readiness reports the degraded dependency.
Emergency bypass is a time-bounded, audited operator action with stricter
fixed ceilings, never a client header.

Rate-limit counters are ephemeral operational state and require no application
database migration. Decisions that deny or materially suspend work emit
bounded metrics; abuse/security incidents use the existing audit/event path
when a durable product action occurs.

## 13. Observability and operational controls

### 13.1 Evidence classes

| Class                      | Purpose                                              | Authoritative for business history |
| -------------------------- | ---------------------------------------------------- | ---------------------------------- |
| Structured application log | Bounded diagnosis                                    | No                                 |
| Security log               | Authentication/abuse/privileged-access signal        | No, unless linked to audit         |
| Metric                     | Aggregated health, latency, volume, capacity, cost   | No                                 |
| Distributed trace          | Cross-service timing and dependency correlation      | No                                 |
| Trace                      | Product provenance and controlled execution evidence | Yes                                |
| Audit                      | Security/authority/action decision evidence          | Yes                                |
| Domain event/outbox        | Committed business fact and delivery                 | Yes                                |
| Activity                   | Authorized user-facing projection                    | Derived                            |
| Incident record            | Operational investigation and response               | Operational evidence               |

Operational telemetry cannot contain source text, prompts, chunks, model
outputs, comments, invitation tokens, credentials, raw grants, raw approvals,
storage keys, queue payloads, or private identifiers. Correlation uses opaque
request, trace, job, execution, workspace, and deployment identifiers. User
and workspace dimensions are HMAC-pseudonymized where aggregation is needed.

### 13.2 Signals

Required golden signals include:

- request rate, latency, error, and saturation by safe operation class;
- database pool use, acquisition time, transaction time, locks, deadlocks,
  replication/failover state, vacuum age, and slow-query fingerprints;
- object upload/scan/promotion latency, checksum failures, orphan count, and
  storage growth;
- queue depth, oldest age, claim latency, lease loss, attempts, retries,
  cancellation, poison jobs, and dead letters;
- parser/scanner/provider latency, failure class, timeouts, and circuit state;
- index throughput, freshness, coverage, publication latency, drift, and
  deterministic mismatch;
- rate-limit consumption, denials, store health, and bypass use;
- domain-event outbox age, terminal failures, projection lag, and integrity;
- backup age, PITR window, restore-exercise age, and object-version coverage;
- cost and capacity against server-owned ceilings.

### 13.3 Objectives and alerts

Checkpoint 7.5 defines versioned service-level indicators and initial
objectives from staging evidence. Alert thresholds must be actionable,
multi-window where appropriate, and linked to a runbook. Paging signals
include tenant-isolation evidence, malware-gate bypass, audit/outbox integrity,
backup/PITR loss, sustained readiness failure, database exhaustion, queue age,
dead-letter spikes, scanner outage, and publication drift.

Exact numeric capacity and objective values are implementation parameters
derived from 7.7 measurements, not unresolved architecture choices.

### 13.4 Health endpoints

- liveness proves only that the process can serve its event loop;
- readiness checks database primary, schema compatibility, required object
  storage, queue, shared limiter, scanner availability policy, and critical
  provider configuration with short cached probes;
- worker health combines deployment health with a fresh durable heartbeat;
- dependency details are available only to authorized operators;
- public health responses do not reveal versions, hosts, credentials, bucket
  names, queue names, or topology.

## 14. Backup, restore, rollback, and disaster recovery

### 14.1 Recovery objectives

Checkpoint 7.6 sets and validates tiered RPO/RTO values for:

- PostgreSQL business and append-only evidence state;
- immutable clean and quarantine object versions;
- shared rate-limit state, which may be safely rebuilt;
- queues, which are reconstructed from durable job eligibility;
- indexes, which are reconstructable from clean canonical source versions and
  manifests; and
- configuration/secret references, which are recovered from the managed
  control plane, never database dumps.

Exact numeric objectives are approved after managed-provider capabilities and
7.7 workload measurements, then become release gates.

### 14.2 Database and object recovery

- managed continuous backup and PITR are required;
- periodic encrypted portable backups provide provider-exit recovery;
- object versioning, retention, checksum inventory, and deletion protection
  cover the database recovery window;
- one recovery manifest binds database recovery time, object-version inventory
  digest, application/schema version, and evidence archive;
- restore occurs in an isolated environment with isolated secrets, egress,
  storage prefixes, queues, telemetry, and user access;
- restoration never sends emails, provider requests, callbacks, or queued
  mutations until explicitly unlocked after validation.

### 14.3 Cross-resource consistency

After restore:

1. verify Alembic head and schema mappings;
2. validate domain-event, outbox, Trace, audit, and activity referential
   integrity;
3. compare every referenced source object version and checksum;
4. quarantine missing or mismatched objects and block their retrieval heads;
5. rebuild queue eligibility from nonterminal durable jobs;
6. reproject derivable activity;
7. reconstruct indexes from clean canonical sources where needed;
8. compare index/publication manifests;
9. run tenant-isolation and authorization probes; and
10. unlock external effects only after an authorized recovery decision.

Index reconstruction creates new operational attempts but preserves the
original immutable index and publication history. It cannot fabricate missing
source evidence.

### 14.4 Rollback strategy

Application rollback is preferred. Migrations use expand/contract when
possible. A failed incompatible migration is recovered by stopping new
workers/API, preserving evidence, restoring the rehearsed pre-change recovery
point into isolation, validating it, and performing a controlled traffic
switch. Production Alembic downgrade is not a routine rollback mechanism.

Forward-fix is permitted only when it can preserve authority, immutable
history, and current availability more safely than restore. The decision,
approver, evidence, commands, artifacts, and outcome are recorded.

### 14.5 Recovery evidence

Backup and restore evidence must not depend solely on the database being
recovered. Each exercise writes a signed/checksummed immutable manifest and
report to a separately protected operations-evidence store with retention and
operator identity. After successful validation, the application uses existing
audit/domain-event/Trace references for the authorized product-facing
recovery action.

No new application persistence is required in 7.6. A database-only
`backup_records` table was rejected because it cannot independently prove that
the database or object store is recoverable.

Tenant-level point restore is not claimed: shared relational history,
append-only evidence, graph relationships, workflow/agent references, and
object versions make selective rewind unsafe. Tenant repair uses bounded
forward reconstruction or provider-supported isolated restore plus reviewed
data migration.

## 15. Load, capacity, resilience, and infrastructure security

### 15.1 Workload model

Checkpoint 7.7 publishes tested limits for:

- concurrent authenticated users;
- workspace-isolation-domain size, workspaces per authenticated user, and
  members per workspace; no separate tenant entity or client tenant claim is
  inferred for reporting;
- canvases, resources, comments, shares, workflows, agents, and executions per
  workspace;
- documents, total bytes, maximum file, pages, chunks, and index revisions;
- upload and indexing jobs per minute;
- parsing, scan, embedding, and index throughput;
- retrieval, workflow, and agent concurrency;
- queue depth and oldest acceptable age;
- database connections and pool wait;
- worker concurrency;
- object-store throughput; and
- recovery time after each required dependency failure.

Tests use synthetic data and cover representative small, median, large, and
abusive tenants without exposing one tenant to another.

### 15.2 Test modes

- stress tests find the bounded failure point;
- soak tests detect leaks, bloat, lease drift, and long-tail degradation;
- spike tests validate backpressure and recovery;
- failure injection covers network delay, partial responses, scanner/provider
  failure, queue outage, worker loss, database failover, object-store failure,
  retry storms, and ambiguous commits;
- recovery-under-load tests prove bounded resumption without duplicate effects;
- destructive failover and restore tests run only in isolated approved
  environments.

Capacity ceilings are enforced server side. Exceeding them returns safe
backpressure or queues bounded work; it cannot cause unlimited concurrency,
memory, storage, connections, retries, or cost.

### 15.3 Infrastructure security

- immutable non-root images with minimal runtime packages;
- read-only filesystems and bounded scratch storage where feasible;
- private service networking and explicit egress;
- least-privilege workload identities;
- signed build provenance and image/dependency inventory;
- secret, dependency, container, license, and configuration scanning;
- pinned deployment artifacts and reviewed dependency updates;
- network, request, body, upload, parser, job, and cost limits;
- privileged access approval, expiry, logging, and review;
- protected backups and recovery environments;
- no production data in logs, crash dumps, tests, or development.

### 15.4 Current local topology-contract boundary

Internal Checkpoint 7 completes the local versioned operation-definition
matrix for the 15 Checkpoint 6 slots that remain blocked. The matrix binds the
immutable Checkpoint 6 inventory and scope by SHA-256 and records a complete
explicit blocked disposition for every stable operation identity.

No executable method, parser, retained Azure projection, authority, or
provider result was invented. All 15 operations remain blocked and unproved,
all ten infrastructure gates remain blocked, all five runtime gates remain
unproved, and provisioning remains unauthorized. The matrix is preparation
for separately authorized evidence work; it is not Azure observation or
Milestone 7.7 completion.

## 16. Threat model

| Asset            | Attacker / entry point               | Control                                                                                            | Detection                                 | Response                                         | Residual risk                              | Validation                                |
| ---------------- | ------------------------------------ | -------------------------------------------------------------------------------------------------- | ----------------------------------------- | ------------------------------------------------ | ------------------------------------------ | ----------------------------------------- |
| Workspace data   | Authenticated IDOR                   | Server-derived scope, membership/share authority, composite constraints, non-enumerating responses | Cross-scope audit signals                 | Revoke session/share, investigate                | Application query defect                   | PostgreSQL tenant-isolation suite         |
| Upload boundary  | Malicious file upload                | Quarantine-only signed upload, limits, MIME/signature checks, scanner                              | Scan/result and hostile-file metrics      | Reject, retain bounded evidence, isolate         | Scanner false negative                     | Malware corpus and scanner contract tests |
| Parser           | Crafted parser exploit               | Isolated non-root parser, no network, resource limits, pinned build                                | Crash/resource-limit signals              | Kill sandbox, quarantine, patch adapter          | Unknown parser vulnerability               | Hostile-file and sandbox escape tests     |
| Archive handling | Decompression bomb                   | Generic archives rejected; bounded format-container expansion                                      | Expansion-limit metric                    | Reject and rate limit                            | Novel container abuse                      | Bomb/nesting tests                        |
| Object store     | Key manipulation                     | Opaque server-owned keys, typed DB scope, private bucket                                           | Integrity and unauthorized-operation logs | Revoke credentials, quarantine affected versions | Provider/control-plane compromise          | Object contract and cross-scope tests     |
| Clean promotion  | Forged scan result                   | Closed signed scanner result, checksum and object-version binding                                  | Promotion/scan mismatch alert             | Block publication, rotate trust key              | Scanner trust compromise                   | Forgery and replay tests                  |
| Queue            | Forged/substituted job               | Minimal opaque delivery, DB job truth, scope digest, lease fencing                                 | Invalid-delivery metric                   | Drop delivery, investigate producer              | Queue administrator misuse                 | Queue substitution tests                  |
| Publication      | Stale worker                         | Lease, authority, cancellation, source and publication generation checks                           | Lost-lease/publication-conflict metric    | Suppress result, recover job                     | Long external call cost                    | Stale-worker concurrency tests            |
| Durable effects  | Duplicate delivery/retry             | Idempotency key+digest, uniqueness, append-only attempts                                           | Duplicate outcome metric                  | Return existing result                           | Provider side effect before timeout        | Ambiguous-outcome tests                   |
| Availability     | Retry storm/poison job               | Closed retry registry, jitter, deadlines, dead letter, circuit breakers                            | Retry/dead-letter alerts                  | Pause class/workspace, operator replay           | Legitimate backlog delay                   | Retry-storm load tests                    |
| Database         | Connection exhaustion                | Per-service pools/budgets, timeouts, reserved operator capacity                                    | Pool and saturation alert                 | Backpressure, scale/recover                      | Provider regional outage                   | Failover and spike tests                  |
| Database         | Privileged migration misuse          | Dedicated role, advisory lock, expected-head check, reviewed artifact                              | DDL/audit alert                           | Stop rollout, restore/forward-fix                | Provider superuser misuse                  | Migration abuse exercise                  |
| Rate limits      | Multi-replica bypass                 | Shared atomic limiter, HMAC subjects, no silent local fallback                                     | Denial/store-health metrics               | Fail closed, audited emergency ceiling           | Shared store outage                        | Distributed limit tests                   |
| Secrets          | Source/log/client leakage            | Managed references, redaction, bundle and repository scans                                         | Secret scanner and log filters            | Revoke/rotate, incident response                 | Unknown third-party retention              | Canary and rotation exercises             |
| Logs/metrics     | Private-content leakage or injection | Allowlisted structured fields, encoding, bounded values, pseudonyms                                | Telemetry schema validator                | Drop/redact stream, rotate sink access           | Operator access                            | Adversarial telemetry tests               |
| Backups          | Theft                                | Encryption, separate least privilege, retention, access logging                                    | Backup access alerts                      | Revoke key, legal/security response              | Provider/key compromise                    | Restore plus access-control audit         |
| Restore          | Poisoned or inconsistent recovery    | Signed recovery manifest, isolated restore, checksums, effects locked                              | Integrity comparison                      | Abandon target, use earlier point                | Correlated DB/object loss                  | Destructive restore exercise              |
| Authority        | Revoked membership continues work    | Captured generations plus current revalidation at boundaries                                       | Revocation/stale-worker metrics           | Fence work and discard result                    | External provider computation may continue | Revocation concurrency suite              |
| Evidence         | Audit/Trace deletion or rewrite      | Append-only constraints, restricted roles, backup integrity                                        | Continuity and digest checks              | Isolate, restore, incident review                | Privileged DB compromise                   | Tamper and restore tests                  |
| Cost             | Unbounded model/indexing work        | Byte/token/time/concurrency/rate budgets and circuit breakers                                      | Cost/capacity alerts                      | Pause operation class/provider                   | Malicious distributed accounts             | Cost-ceiling load tests                   |
| Runtime          | Dependency/container compromise      | Minimal signed images, SBOM, scanning, egress limits                                               | Runtime and supply-chain alerts           | Quarantine image, rollback, rotate secrets       | Zero-day                                   | Image/dependency audit                    |
| Operator         | Privileged misuse                    | Separate roles, approval, time-bound break glass, immutable evidence                               | Privileged action alerts                  | Revoke, investigate, restore                     | Collusion/provider superuser               | Access review and incident drill          |
| Availability     | Storage exhaustion                   | Quotas, lifecycle, orphan reconciliation, capacity alerts                                          | Growth/remaining-capacity alert           | Backpressure, expand/reclaim safely              | Sudden provider quota                      | Soak and exhaustion tests                 |
| Collaboration    | Stale browser cache after revocation | Existing generation fencing and scoped cache clearing                                              | Unauthorized/revoked response metrics     | Clear/revoke session, investigate                | Client offline data already viewed         | Browser revocation tests                  |

## 17. Event, Trace, audit, activity, and metric strategy

State and evidence commit atomically where they describe one product action.
External telemetry and queue wake-up occur after commit and are idempotent.

| Event                       | Durable state                               | Domain event/outbox                                          | Trace/audit                                    | Activity             | Metric/alert          |
| --------------------------- | ------------------------------------------- | ------------------------------------------------------------ | ---------------------------------------------- | -------------------- | --------------------- |
| Upload requested/completed  | Upload session/object version               | Yes                                                          | Audit; Trace when part of controlled execution | Bounded              | Volume/failure        |
| Quarantined/scan started    | Object lifecycle/scan record                | Yes                                                          | Audit                                          | Safe status          | Queue age             |
| Scan passed/rejected        | Immutable scan result                       | Yes                                                          | Audit                                          | Safe status          | Malware/scanner alert |
| Ingestion requested/queued  | Request/job state                           | Yes                                                          | Trace + audit                                  | Bounded              | Queue rate/depth      |
| Parse/index failed          | Attempt + safe failure                      | Yes for terminal/material state                              | Trace + audit                                  | Safe status          | Failure alert         |
| Index revision created      | Immutable revision                          | Yes                                                          | Trace + audit                                  | Optional safe status | Throughput/drift      |
| Index published             | Publication + head                          | Yes                                                          | Trace + audit                                  | Yes                  | Freshness/latency     |
| Reindex requested           | Request                                     | Yes                                                          | Trace + audit                                  | Yes                  | Rate                  |
| Job retried/dead-lettered   | Attempt/dead-letter                         | Yes for material transition                                  | Trace + audit                                  | Safe status          | Retry/DLQ alert       |
| Backup completed            | External signed exercise evidence           | Existing audit/event only for product-facing operator action | Audit reference                                | No                   | Backup-age alert      |
| Restore exercise completed  | External signed report + existing reference | Existing event                                               | Audit/Trace reference                          | No                   | Exercise-age alert    |
| Capacity threshold exceeded | No product state unless action taken        | Event only for durable mitigation                            | Audit if operator action                       | No                   | Alert                 |

Trace means auditable provenance and execution evidence, not private model
chain of thought. Operational spans never become Trace merely because they
share a correlation identifier.

## 18. Configuration and secrets

Configuration remains layered through the existing settings boundary:

1. immutable non-secret defaults safe for demo/test;
2. environment-specific non-secret configuration;
3. managed secret references resolved by workload identity; and
4. time-bounded operator overrides with audit.

Production configuration validation requires:

- explicit mode and public origins;
- managed PostgreSQL primary, TLS, pool and timeout budgets;
- private versioned object storage and quarantine/clean prefixes;
- scanner, durable queue, and shared limiter adapters;
- telemetry destinations and redaction policy;
- provider/model identities and closed component versions;
- backup/PITR and recovery-evidence targets;
- server-owned upload, parser, job, rate, concurrency, cost, and retention
  limits; and
- unique credentials and resources per environment.

Missing, ambiguous, demo, local, memory, test-bypass, insecure TLS, public
bucket, per-process limiter, or unscanned-upload production configuration
fails startup. Production never falls back to demo or development behavior.

Rotation uses dual-read/single-write only for the bounded overlap needed by
the credential type. New sessions, signatures, uploads, jobs, and encryption
use the current key; old keys are revoked after the documented overlap.
Rotation and compromise runbooks verify that no secret value is logged.

## 19. Provider strategy

| Capability        | Required interface                          | Reference direction                          | Local substitute                                    |
| ----------------- | ------------------------------------------- | -------------------------------------------- | --------------------------------------------------- |
| PostgreSQL        | SQLAlchemy/Alembic + pgvector contract      | Managed PostgreSQL 17                        | Container PostgreSQL; SQLite only for bounded tests |
| Object storage    | Versioned private object capabilities       | S3-compatible                                | Local private filesystem/memory                     |
| Malware scanning  | Closed `MalwareScanner` result              | Managed or isolated scanner meeting contract | Deterministic fake plus hostile fixtures            |
| Durable queue     | `DurableWorkQueue`                          | Hardened PostgreSQL queue first              | Same PostgreSQL/container adapter                   |
| Shared limits     | Atomic `SharedRateLimiter`                  | Redis-compatible managed store               | In-memory deterministic fake                        |
| Telemetry         | Structured log/metric/span interfaces       | OpenTelemetry-compatible export              | Capturing/no-op test adapters                       |
| Secrets           | Secret-reference/workload-identity contract | Managed secret service                       | Explicit local environment values                   |
| Models/embeddings | Existing provider protocols                 | Approved server-side providers               | Deterministic mock                                  |

No provider is selected by marketing preference. Implementation acceptance
depends on contract tests, failure behavior, isolation, recovery, observability,
cost controls, and exit support.

## 20. Migration allocation

No migration is created by this architecture pass.

| Checkpoint | Planned revision | Direct parent   | Complete immutable scope                                                                                                                                                                                          | Explicit exclusions                                                                   | Backfill and downgrade                                                                                                                                            | PostgreSQL validation                                                                                            |
| ---------- | ---------------- | --------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| 7.1        | None             | N/A             | Runtime, pooling, roles, migration lock, timeouts, health, and managed validation require no application durable state                                                                                            | RLS policies; provider metadata; secrets                                              | None                                                                                                                                                              | Pool reuse, role boundaries, transactions, locks, failover, schema compatibility                                 |
| 7.2        | `20260726_0026`  | `20260725_0025` | Scoped ingestion requests/transitions; immutable pipeline manifests, normalized artifacts, deterministic metadata, index revisions/chunks/vector manifests, publication history, and retrieval-head projection    | Upload sessions; malware scans; queue deliveries; rate counters; Librarian data       | Existing ready documents remain compatibility projections; no invented provenance; downgrade removes only unreferenced 7.2 structures in disposable validation    | Constraints, concurrent idempotency, stable output, publication atomicity, vector/index plans                    |
| 7.3        | `20260726_0027`  | `20260726_0026` | Upload sessions; opaque storage objects/versions; quarantine/clean/rejected lifecycle; immutable malware scan evidence; source-version object binding                                                             | Scanner engine internals; secrets; provider bucket names; legal-hold product UI       | Backfill known object keys/checksums as `legacy_unscanned`; never infer `clean`; require controlled scan before production publication; disposable downgrade only | Composite scope, promotion concurrency, checksum/version uniqueness, backfill and object-contract integration    |
| 7.4        | `20260726_0028`  | `20260726_0027` | Existing document-job evolution with job-run identity, authority/cancel/lease generations, bounded attempts, queue deliveries, retry decisions, dead-letter evidence, result/publication links, and claim indexes | Rate-limit counters; workflow/agent table unification; broker internals; raw payloads | Backfill existing rows as legacy bounded job runs/attempts without changing outcomes; disposable downgrade only after removing new rows                           | `SKIP LOCKED`, lease races, failover ambiguity, duplicate delivery, dead letter, cancellation, stale publication |
| 7.5        | None             | N/A             | Telemetry and incident systems use external operational stores plus existing product evidence                                                                                                                     | Private payloads; parallel audit/Trace                                                | None                                                                                                                                                              | Query/log fingerprint and health behavior                                                                        |
| 7.6        | None             | N/A             | Backup/restore evidence uses a separately protected immutable exercise store and existing references                                                                                                              | Database-only backup truth; tenant rewind                                             | None                                                                                                                                                              | Managed PITR and isolated restore                                                                                |
| 7.7        | None             | N/A             | Test results, capacity limits, threat evidence, and runbooks are versioned artifacts, not product data                                                                                                            | Load-test state in production schema                                                  | None                                                                                                                                                              | Stress, soak, failover, recovery                                                                                 |
| 7.8        | None             | N/A             | Audit and release decision use existing evidence and documentation                                                                                                                                                | Milestone 8 persistence                                                               | None                                                                                                                                                              | Sole-head, full mapper and production-readiness gate                                                             |

The durable-state decision ledger is explicit:

- production runtime configuration and secrets: no application migration;
- source ingestion lifecycle, parser/normalizer/chunker manifests,
  deterministic metadata, immutable chunks/index revisions, and publication:
  `0026`;
- object-storage metadata, upload sessions, quarantine, clean promotion, and
  malware evidence: `0027`;
- index job runs, deliveries, leases, attempts, retries, dead letters,
  cancellation, and result/publication fencing: `0028`;
- shared rate-limit counters: no application migration; use the external
  atomic limiter;
- operational incidents: no application migration; use the operations system
  plus existing evidence for product actions;
- backup and restore evidence: no application migration; use independent
  immutable exercise evidence plus existing references.

Committed migrations remain immutable, and an ordinary later correction uses
the next unused revision. The six explicitly documented PostgreSQL
compatibility amendments are a narrow exception because a fresh database
cannot pass the affected historical revisions to reach a corrective child.
They require preserved original hashes, one final validated active hash per
corrected migration, and complete combined validation. No empty revision is
reserved, and no general historical-edit authority is created.

## 21. API and service boundaries

Browser-facing operations extend the existing scoped document routes:

```text
POST   /workspaces/{workspaceId}/canvases/{canvasId}/uploads
POST   /workspaces/{workspaceId}/canvases/{canvasId}/uploads/{uploadId}/complete
GET    /workspaces/{workspaceId}/canvases/{canvasId}/uploads/{uploadId}
POST   /workspaces/{workspaceId}/canvases/{canvasId}/documents/{documentId}/versions/{version}/index-requests
GET    /workspaces/{workspaceId}/canvases/{canvasId}/index-requests/{requestId}
POST   /workspaces/{workspaceId}/canvases/{canvasId}/index-requests/{requestId}/cancel
POST   /workspaces/{workspaceId}/canvases/{canvasId}/documents/{documentId}/reindex
GET    /workspaces/{workspaceId}/canvases/{canvasId}/documents/{documentId}/index-revisions
```

Exact paths may align with existing route conventions during implementation,
but contracts are fixed:

- server-derived principal and typed parent scope;
- current membership/share/action authority;
- CSRF for mutation;
- idempotency key and canonical request digest;
- safe closed status and error codes;
- no storage key, scanner internals, raw queue payload, lease, infrastructure
  identifier, stack trace, database error, secret, or hidden-resource
  existence;
- reindex and operational replay require explicit closed permissions and
  current authority;
- ordinary users cannot claim work, extend leases, force `clean`, publish an
  arbitrary revision, edit attempts, or drain dead letters.

Internal services include `IngestionService`, `IndexBuildService`,
`IndexPublicationService`, `ObjectLifecycleService`, `MalwareScanService`,
`DurableJobService`, `SharedRateLimitService`, and `RecoveryVerificationService`.
Each accepts a server-created scoped command rather than raw client claims.

## 22. Test strategy

Every implementation checkpoint runs focused tests plus affected prior
Milestone 4–6 suites. The final matrix includes:

- unit and service tests;
- database constraint and mapper tests;
- migration upgrade/downgrade/re-upgrade and offline PostgreSQL DDL;
- configured managed PostgreSQL runtime and failover tests;
- object-storage contract, checksum, versioning, retention, orphan, and
  cross-scope tests;
- scanner contract, hostile-file, MIME spoof, active-content, malformed
  structure, timeout, password, nesting, and decompression-bomb tests;
- parser isolation and resource-exhaustion tests;
- Indexer determinism, manifest, deduplication, reindex, supersession, drift,
  and publication-atomicity tests;
- queue/worker claim, duplicate delivery, heartbeat, lease generation, stale
  worker, retry, poison, dead-letter, replay, cancellation, shutdown, and
  failover tests;
- shared multi-replica rate-limit atomicity, failure, bypass, and recovery
  tests;
- authority, membership, share, source, revocation, tenant-isolation,
  non-enumeration, and stale-result tests;
- Trace/audit/event/outbox/activity atomicity and duplicate-delivery tests;
- telemetry redaction and cardinality tests;
- full backup, PITR, object restore, index reconstruction, queue recovery,
  migration recovery, application rollback, and disaster-recovery exercises;
- stress, soak, spike, network delay, dependency loss, worker loss, database
  failover, object/scanner outage, retry-storm, and recovery-under-load tests;
- secret, dependency, container, license, configuration, local-path, and
  repository hygiene;
- frontend/build/browser regression where public status and cancellation
  surfaces change; and
- deterministic demo isolation and regression.

Tests progress from deterministic local substitutes, to containers, to
managed staging services, to production-like isolated environments. Destructive
recovery tests never target production.

## 23. Operational runbooks

Milestone 7 must publish and exercise runbooks for:

- failed or partial upload;
- malware detection, suspicious content, stuck quarantine, and scanner outage;
- parser crash, timeout, resource exhaustion, and dependency vulnerability;
- Indexer backlog, deterministic drift, failed publication, and stale index;
- poison job, dead-letter review/replay, retry storm, lost worker, and queue
  outage;
- shared rate-limit outage, false positive, abuse event, and emergency ceiling;
- database connection exhaustion, slow query, migration failure, and failover;
- object-storage outage, checksum mismatch, orphan, retention error, and
  recovery;
- outbox backlog and audit/Trace integrity failure;
- failed deployment, application rollback, forward-fix, backup failure, PITR,
  full restore, and disaster recovery;
- secret rotation, key compromise, privileged-access review, dependency/image
  compromise, and tenant-isolation incident;
- capacity threshold breach and cost ceiling.

Each runbook specifies detection, safe immediate action, authority and approval,
evidence to preserve, user-impact communication boundary, recovery steps,
verification, rollback, escalation, and post-incident review.

## 24. Rejected alternatives

| Alternative                                             | Decision                                                                                                                |
| ------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| Make the Indexer an autonomous Librarian                | Rejected. Deterministic ingestion and governed discretionary proposals have different authority and evidence contracts. |
| Trust uploaded MIME or extension                        | Rejected. Signature-derived type, limits, checksum, quarantine, and scan are required.                                  |
| Scan after parsing/indexing                             | Rejected. No unsafe bytes reach parsers, retrieval, previews, models, or publication before `clean`.                    |
| Mark a legacy object clean during migration             | Rejected. Backfill cannot invent malware evidence.                                                                      |
| Global cross-workspace content deduplication            | Rejected. It creates disclosure, deletion, encryption, and recovery coupling.                                           |
| Mutable current index rows only                         | Rejected. Immutable revisions and append-only publication preserve provenance and rollback.                             |
| Queue delivery as job truth                             | Rejected. At-least-once delivery cannot prove authority, attempt, effect, or completion.                                |
| Introduce a broker before hardening current jobs        | Rejected initially. It adds dual-write and recovery complexity; the interface permits a later adapter.                  |
| One generic job table replacing workflows and agents    | Rejected. Domain lifecycles differ; share a lease/fencing contract, not false persistence uniformity.                   |
| Separate Indexer event bus/outbox                       | Rejected. Extend the existing domain event and transactional outbox.                                                    |
| Per-process production rate limits                      | Rejected. They are bypassable across replicas.                                                                          |
| Fail open when limiter/scanner is unavailable           | Rejected for protected or abuse-sensitive paths.                                                                        |
| Require PostgreSQL RLS now                              | Rejected as an unproved second authorization engine across multi-workspace pooled connections.                          |
| Run migrations at API startup                           | Rejected. One reviewed locked migration task owns schema change.                                                        |
| Database-only backup evidence                           | Rejected. The affected database cannot independently prove its recovery.                                                |
| Routine production Alembic downgrade                    | Rejected. Prefer application rollback, additive compatibility, forward-fix, or rehearsed restore.                       |
| Store raw prompts/content in telemetry                  | Rejected. Operational diagnosis uses bounded identifiers and safe classifications.                                      |
| Vendor-specific infrastructure semantics in domain code | Rejected. Providers remain behind explicit contract tests.                                                              |

## 25. Risks

- parser libraries and scanners can have false negatives or zero-days;
- vector providers can exhibit output drift despite stable advertised model
  names;
- a PostgreSQL-backed queue shares database failure and connection capacity
  with application traffic;
- object and database recovery points can diverge;
- application-layer authorization retains residual risk from a missed scope
  predicate;
- high-cardinality telemetry can leak identifiers or become expensive;
- aggressive fail-closed controls can reduce availability during dependency
  outages;
- legacy objects require controlled scanning before production publication;
- capacity objectives cannot be credible until measured on approved managed
  staging infrastructure.

Each risk has an explicit control and validation gate above. None authorizes a
weaker production claim.

## 26. Milestone 8 entry criteria

Milestone 8 may begin only after 7.8 proves and records:

- managed PostgreSQL validation, pooling, migration lock, role separation,
  failover behavior, constraints, and tenant isolation;
- private managed object storage, checksum/versioning, secure upload, hostile
  input controls, malware quarantine, and clean promotion;
- deterministic immutable Indexer revisions, provenance, deduplication,
  reindexing, supersession, cancellation, drift, and publication;
- durable queue/workers, at-least-once duplicate safety, leases, recovery,
  bounded retries, poison/dead-letter handling, and stale-result suppression;
- distributed shared rate limits and safe dependency failure;
- privacy-preserving logs, metrics, tracing, dashboards, objectives, alerts,
  incident evidence, and exercised runbooks;
- encrypted backup/PITR, object recovery, queue/outbox recovery, migration and
  application rollback, isolated restore, and disaster-recovery exercise;
- documented enforced capacity/cost ceilings from load, soak, spike, failure,
  and recovery testing;
- infrastructure-security and supply-chain audit;
- no critical or high-severity unresolved production-readiness defect;
- all affected Milestone 4–6, build, browser, migration, hygiene, demo, and
  protected-Git validations passing;
- a clean local completion commit and no unauthorized remote operation.

This authorizes only Milestone 8 Controlled Public Release and Guided
Onboarding work. It does not begin Advanced Collaboration, Mobius Society,
the governed Librarian, Worlds, Spatial, Federation, or Continuity.

## 27. Current implementation boundary

Checkpoints 7.1 through 7.6 are complete locally. Migration `20260726_0028`
is the sole head. Managed staging evidence validates the private/versioned
Azure storage and clean/EICAR scanner prerequisites, with direct personal
blob-tag inspection unavailable by least-privilege design. The application
uses a dedicated exact-evidence scanner-result path rather than personal
authority or a mutable tag.

Checkpoint 7.6 subsequently validated private recovery telemetry metrics in
its isolated Azure environment, but category-log rows had not arrived before
cleanup. Exact Stage 3 posted cost also remains unavailable because of Azure
`429` responses and delayed usage posting. These limitations remain explicit
revalidation gates; the exercise does not certify production deployment,
production SLOs, public release, Milestone 7.8, Milestone 8, or later work.

Milestone 7.7 is now in progress locally. Checkpoint 1 records a
resource-free, non-deployable infrastructure and policy manifest. Checkpoint 2
records a deterministic bounded synthetic-workload and exact local
measurement contract. Checkpoint 3 records the strict, bounded, deterministic
local evidence-package schema, artifact inventory, Checkpoint 2 bindings,
claim controls, completeness states, unsigned/local-retention boundary, and
network-incapable verifier. Its complete package state proves only the local
evidence contract; Milestone 7.7 evidence remains partial.

The first completion audit correctly withheld the commit after a formatter
wrapper attempted a prohibited npm-registry request. The request failed, and
no dependency or lockfile changed. A separately authorized recovery reran the
complete commit gate fully offline through installed executables directly.
Every available gate passed, so Checkpoint 3 is complete locally.

Checkpoint 4 adds the repository-defined local failure-injection planning
framework. Its closed catalog binds 22 later resilience exercises to exact
Checkpoint 1–3 identities, hard workload and cost ceilings, isolated-synthetic
scope, one-fault concurrency, prerequisites, expected outcomes, assertions,
evidence classes, rollback, cleanup, and fail-closed abort conditions. The
framework has no network, process, provider, database, application,
deployment, or infrastructure-mutation client. Its deterministic verifier
reports the local plan valid while keeping execution blocked and Milestone 7.7
evidence partial.

All ten Checkpoint 1 gates remain unresolved. Checkpoint 4 also preserves five
runtime gates: fault-controller shape, isolated environment, live failure
authorization, effect-lock runtime proof, and cleanup-supervisor runtime proof.
No local schema, fixture, or verifier can resolve those gates or upgrade
pending, absent, or unproved managed-environment evidence.

None of the four checkpoints contacted Azure, authorized provisioning,
executed a managed workload or live fault, published a production capacity
claim, signed or published evidence, provided independent retention, or began
Checkpoint 5.

Checkpoint 5 adds aggregate local validation across the public Checkpoint 1–4
contracts. Its deterministic report binds the infrastructure bundle, workload
manifest and reproduced plan/result, evidence package, failure plan, scenario
catalog, and closed validation-requirement catalog. It fails closed on
incompatible or tampered bindings, incomplete validation, unknown input,
strengthened claims, execution capability, resolved external gates, secrets,
private identifiers, absolute paths, traversal, and bounded-output violations.

Local validation completion proves only that the repository contracts
reproduce, validate, and remain mutually compatible. All ten infrastructure
and five runtime gates remain unresolved; managed-environment evidence remains
absent, pending, partial, or unproved as recorded. The validator has no
network, process, provider, workload, fault, deployment, database, or
infrastructure-mutation client. It does not authorize Azure topology
preflight, Checkpoint 6, or any live exercise.

Checkpoint 6 scope definition now binds the approved account fingerprints,
primary and comparison regions, exact intended future resource groups,
24-hour sanitized evidence policy, ten infrastructure gates, five unresolved
runtime gates, and an 18-slot closed default-deny operation inventory. The
current-account context and two exact resource-group absence slots have
repository-verified read-only command templates; the remaining 15 slots are
explicitly blocked rather than filled by assumption. The group templates have
not been executed at this local scope-definition point. This local contract
authorizes no Azure execution and does not resolve any gate.

The first separately authorized read-only Azure Topology Preflight later
proved only the current-account context and produced sanitized evidence
`m7.7-cp6-20260730-195532z`, integrity SHA-256
`f2af5b10703f0f0a88237e1e8f154b330b3f5a9c656aa900a3b397ed851f7a4a`,
classified `complete-with-provisioning-blocked`. The complete canonical
evidence object existed only in memory; the repository preserves its sanitized
report, and documentation does not renew the recorded evidence expiry. It
binds the earlier inventory and is non-authoritative under the revised
inventory and scope integrity values.

The later separately authorized bounded execution ran only
`current-account-context`, `target-group-existence`, and
`cleanup-group-existence`, once each and in committed order. The account
projection matched and both exact group checks returned `false`. The
atomically persisted evidence is `m7.7-cp6-20260731-023407z.json`, integrity
SHA-256
`6f3f06cb92538523bd5cd8809ff498a0e6c0724210445e027b81665433ea51b3`,
classified `complete-with-provisioning-blocked`. It expires at
`2026-08-01T02:34:07Z`; documentation does not renew it. Checkpoint 6 is
complete under its committed exit rule. The other 15 operation slots and all
ten infrastructure gates remain blocked; all five runtime gates remain
unproved. Provisioning remains blocked and Milestone 7.7 remains in progress.

## 28. Internal Checkpoint 7 architecture decision

Formal checkpoint 7 is Milestone 7.7 itself. Internal Checkpoint 7 is a
separate implementation checkpoint inside Milestone 7.7:

**Milestone 7.7 Internal Checkpoint 7 — Azure Topology Operation-Contract
Completion**

The binding decision is
[`MILESTONE_7_7_CHECKPOINT_7_SCOPE_DECISION.md`](MILESTONE_7_7_CHECKPOINT_7_SCOPE_DECISION.md).
It is the seventh currently defined internal checkpoint, follows the completed
Checkpoint 6 boundary, is unstarted, and is not final. No authoritative total
number of internal Milestone 7.7 checkpoints is defined; later checkpoints
remain intentionally undefined until internal Checkpoint 7 reports the exact
remaining gates.

Internal Checkpoint 7 may complete only the local, versioned, default-deny
operation contracts for the 15 currently blocked inventory slots. It executes
no Azure operation, authorizes no provisioning, changes no application,
worker, frontend, Bicep, data, dependency, or migration behavior, and cannot
upgrade an infrastructure or runtime gate. All ten infrastructure gates
remain blocked, all five runtime gates remain unproved, and provisioning
remains unauthorized.

Internal Checkpoint 7 cannot complete formal checkpoint 7.7 or begin Milestone
7.8. Its smallest later separately authorizable action is one local
operation-contract implementation pass with focused fail-closed tests and no
Azure execution.

## 29. Milestone 7.8 entry architecture boundary

The subsequent formal Milestone 7.7 lifecycle completed at
`b191a392922f94557e6ebf5914113b5e229ab00e`. Its retained local terminal
evidence validates the complete nine-stage predecessor chain, the uninterrupted
5,400-second soak with 91 samples, successful cleanup, zero residue, and the
`MILESTONE_7_7_COMPLETE` marker. That completion does not rewrite or invalidate
the historical internal-checkpoint decisions above.

Milestone 7.8 is the **Final Production-Readiness Audit** defined by the
implementation plan and RR-02 of the Mobius Family Architecture Constitution.
It is an audit plus conditional, targeted remediation and validation: only a
defect proved inside the approved audit boundary may be corrected. No separate
numbered internal 7.8 checkpoints are defined. The ordered first audit surface
is architecture and checkpoint scope; later technical audit surfaces remain
unstarted.

Entry requires no Azure mutation and authorizes none by default. Migration
`20260726_0028` remains the sole head, migration `0029` is not planned, and the
canonical checkpoint 7.7 image inputs remain historical and unchanged. The
current audit evidence is recorded in
[`MILESTONE_7_8_ARCHITECTURE_SCOPE_AUDIT_HANDOFF.md`](MILESTONE_7_8_ARCHITECTURE_SCOPE_AUDIT_HANDOFF.md),
with exact findings in
[`MILESTONE_7_8_DEFECT_REGISTER.md`](MILESTONE_7_8_DEFECT_REGISTER.md).
