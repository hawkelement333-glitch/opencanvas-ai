# Milestone 7 Production Hardening Implementation Plan

Date: 2026-07-26

Status: approved architecture plan; implementation not started

Architecture:
[`MILESTONE_7_ARCHITECTURE.md`](MILESTONE_7_ARCHITECTURE.md)

Current sole Alembic head: `20260725_0025`

## 1. Execution rules

1. Start every checkpoint from the committed, clean prior checkpoint.
2. Verify branch, HEAD, parent, upstream, sole Alembic head, migration hashes,
   and protected references before editing.
3. Inspect the affected implementation and tests before choosing changes.
4. Implement only the current checkpoint.
5. Extend existing models, services, APIs, authority, Trace, audit, events,
   outbox, activity, storage, job, and UI patterns.
6. Derive user, membership, workspace, canvas, resource, immutable version,
   authority, and cancellation scope on the server.
7. Commit durable state and required product evidence atomically.
8. Revalidate current authority and lifecycle before protected effects,
   retries, results, and publication.
9. Keep migrations complete, checkpoint-owned, immutable, and linear.
10. Run focused tests during development and the checkpoint validation matrix
    before commit.
11. Record concrete defects and fixes; do not broaden scope for speculative
    cleanup.
12. Do not contact a remote, deploy, provision production, publish, merge,
    rebase, or start a later checkpoint.

Every checkpoint handoff reports exact SHA, parent, migration head, files,
tests, skips/warnings, defects, clean tree, no upstream, protected references,
and confirmation that no remote operation occurred.

## 2. Dependency and migration plan

| Order | Checkpoint                                                   | Migration       | Direct parent   |
| ----- | ------------------------------------------------------------ | --------------- | --------------- |
| 1     | 7.1 Production Runtime Foundation and Managed PostgreSQL     | None            | N/A             |
| 2     | 7.2 Deterministic Indexer and Ingestion Pipeline             | `20260726_0026` | `20260725_0025` |
| 3     | 7.3 Object Storage, Upload Security, and Malware Quarantine  | `20260726_0027` | `20260726_0026` |
| 4     | 7.4 Durable Queues, Workers, Retries, and Shared Rate Limits | `20260726_0028` | `20260726_0027` |
| 5     | 7.5 Observability and Operational Controls                   | None            | N/A             |
| 6     | 7.6 Backup, Restore, Rollback, and Disaster Recovery         | None            | N/A             |
| 7     | 7.7 Load, Capacity, Resilience, and Infrastructure Security  | None            | N/A             |
| 8     | 7.8 Final Production-Readiness Audit                         | None            | N/A             |

No empty revision is reserved. If a committed migration later needs a
correction, use the next unused revision and record an amendment.

## 3. Checkpoint 7.1 — Production Runtime Foundation and Managed PostgreSQL

### Purpose

Prove a production runtime boundary and managed PostgreSQL operating contract
without changing application product semantics.

### Prerequisites

- Milestone 6.7 completion commit and architecture commit are verified.
- `20260725_0025` is the sole Alembic head.
- approved isolated managed staging resources exist before external validation;
- production data and production credentials are absent.

### Exact scope

- development, test, staging, and production resource separation;
- PostgreSQL 17 and compatible pgvector version policy;
- API, worker, migration, backup, observability, and emergency database roles;
- direct migration connection and transaction-pooled API/worker connections;
- per-service connection budgets and reserved operator capacity;
- transaction, statement, lock, idle, acquisition, and shutdown timeouts;
- advisory-locked one-shot migrations with expected-head validation;
- primary-only protected reads/writes and explicit replica exclusions;
- managed TLS, encryption, credential rotation, backup/PITR prerequisites;
- startup configuration validation and schema compatibility;
- liveness, readiness, dependency, worker, startup, and shutdown behavior;
- vacuum/analyze, vector-index, bloat, slow-query, and failover operating rules;
- managed PostgreSQL authority, concurrency, and tenant-isolation validation.

### Data and migration scope

No migration. Runtime roles, pools, locks, timeouts, health, secret references,
and managed-service policy are not application durable state.

RLS is deliberately excluded. Application authority, typed parent scope,
composite constraints, database least privilege, and managed-PostgreSQL
isolation tests remain authoritative.

### Services and infrastructure interfaces

- preserve the existing SQLAlchemy session and Alembic boundaries;
- add explicit pool/timeout/role configuration through existing settings;
- keep migrations in the one-shot migration service;
- make readiness dependency probes bounded and non-secret;
- preserve SQLite only where current bounded tests require it.

### Authorization and tenant isolation

- API and worker roles receive DML only for required tables;
- migration DDL and backup access are separate;
- every protected repository call receives server-derived scope;
- pool reuse cannot retain another request's transaction or context;
- failover/retry resolution uses durable idempotency identity.

### Events and observability

Runtime health and failover signals are operational telemetry. An authorized
operator action that changes product state uses existing audit/event/Trace
contracts. Database hostnames, connection strings, SQL parameters, and
credentials are never emitted.

### Failure and concurrency behavior

- missing or insecure production configuration fails startup;
- pool exhaustion backpressures with safe dependency errors;
- lock/statement timeout is classified and retried only by operation policy;
- ambiguous commits resolve by idempotency lookup;
- graceful shutdown drains bounded requests and stops new claims;
- failover never causes blind mutation replay.

### Tests and validation

- settings/mode fail-closed tests;
- role and privilege tests;
- pool-budget and pool-reuse tests;
- transaction/lock/statement-timeout tests;
- migration advisory-lock and concurrent-run tests;
- upgrade/downgrade/re-upgrade in disposable PostgreSQL;
- offline PostgreSQL DDL;
- managed PostgreSQL mapper, constraints, vector, concurrency, failover, and
  read-after-write tests;
- cross-user/workspace/canvas/resource/membership isolation;
- stale authority, revocation, idempotency, and ambiguous-commit scenarios;
- readiness/liveness/worker/startup/shutdown tests;
- affected Milestone 4–6 suites, compilation, imports, typing, lint, formatting,
  build, demo, hygiene, secrets, and protected Git checks.

### Documentation and runbooks

Update deployment, database operations, secret rotation, connection
exhaustion, failover, migration failure, rollback, and production-validation
guides. Record provider-neutral requirements and the exact staging evidence.

### Commit and exit

Suggested local commit: `Complete Milestone 7.1 production runtime foundation`

Exit only when managed PostgreSQL behavior is proved, no unapproved fallback
exists, no migration was created, and 7.2 is still unstarted.

### Explicit exclusions

Indexer state, upload/quarantine state, malware scanning, durable job
migration, shared limits, production observability rollout, backup exercise,
load certification, RLS, deployment, and Milestone 8.

## 4. Checkpoint 7.2 — Deterministic Indexer and Ingestion Pipeline

### Purpose

Create provenance-complete, immutable, deterministic index revisions and
separate index construction from authorized retrieval publication.

### Prerequisites

- 7.1 is committed and managed PostgreSQL is available for validation;
- `20260725_0025` remains the sole head before migration creation;
- current document, retrieval, graph, event, Trace, audit, and authority
  contracts are mapped;
- component inputs and output-affecting configuration are closed and versioned.

### Exact scope

- scoped ingestion request and append-only lifecycle;
- immutable source-version binding to existing `DocumentVersion`;
- canonical pipeline manifest and component version attribution;
- isolated parsing contract;
- deterministic normalization and allowlisted metadata extraction;
- stable chunk identity and immutable ordered chunk manifests;
- embedding materialization identity and drift detection;
- workspace-scoped byte and normalized-content deduplication;
- deterministic, versioned near-duplicate diagnostic fingerprint;
- immutable index revision and publication history;
- active retrieval-head projection;
- reindexing, supersession, cancellation, safe retry inputs, and failures;
- exact provenance and Trace/audit/event/outbox/activity integration;
- publication only after complete provenance and current authorization.

### Migration `20260726_0026`

Direct parent: `20260725_0025`.

Complete scope:

- ingestion request identity, idempotency digest, exact user/membership,
  workspace/canvas/document/version scope, authority/cancel generation, and
  lifecycle transitions;
- immutable pipeline/component manifests and normalized-artifact evidence;
- immutable index revisions, deterministic metadata facts, ordered index
  chunks, vector materialization manifests, output digests, and safe failures;
- append-only publication records and one current retrieval-head projection;
- same-scope composite keys, closed registries, uniqueness, check constraints,
  claim/publication indexes, and evidence references.

Backfill:

- preserve existing `DocumentVersion`, `DocumentChunk`, and
  `DocumentEmbedding` history;
- mark existing ready outputs as compatibility projections;
- do not synthesize pipeline versions, malware status, publication evidence,
  actors, or provenance;
- require an authorized reindex to create a native immutable revision.

Downgrade is supported only in disposable validation before 7.2 data is relied
on. It removes 7.2-owned structures without altering migrations through
`0025`.

Explicit exclusions:

- upload sessions and storage-object lifecycle;
- malware evidence or a `clean` assertion;
- queue-delivery/dead-letter state;
- shared rate-limit counters;
- Librarian proposals or semantic catalog judgment.

### Services

- `IngestionService` accepts server-created scoped commands;
- `PipelineManifestService` canonicalizes all output-affecting inputs;
- versioned parser/normalizer/metadata/chunker adapters are pure or isolated;
- `IndexBuildService` writes immutable candidates;
- `IndexPublicationService` performs the short locked revalidation transaction;
- retrieval resolves only the active publication;
- reindex creates a new request/revision and never rewrites history.

### APIs

Add authenticated, CSRF-protected, idempotent request/status/cancel/reindex and
safe revision-list operations under exact workspace/canvas/document parents.
Do not expose raw hashes, storage keys, manifests with private internals,
worker controls, unpublished content, or hidden-resource existence.

### Authorization and isolation

- requester must have current source view and indexing permission;
- operational system execution carries the originating scope and authority
  generation;
- reindex requires explicit permission and cannot broaden source visibility;
- deduplication and diagnostic fingerprints never cross workspaces;
- publication rechecks membership/share/source/current version and cancellation.

### Events and evidence

Use existing domain event/outbox contracts for ingestion requested, queued,
terminal failure, revision created, publication, supersession, cancellation,
and reindex. Trace links exact source/version, request, manifest, attempts,
revision, publication, citations where later used, and safe decisions. Audit
records actor, authority, operation, outcome, and safe reason. Activity exposes
only authorized bounded status.

### Configuration and observability

Component registries and every output-affecting limit are server owned and
included in the manifest. Metrics cover throughput, stage latency, freshness,
coverage, failures, drift, dedup reuse, and publication conflict without
content or raw identities.

### Failure and concurrency behavior

- exact duplicate request returns the existing identity/result;
- conflicting idempotency digest fails;
- component drift under one manifest fails closed;
- source change, cancellation, supersession, revocation, or lease loss blocks
  publication;
- an unused completed artifact is not visible to retrieval;
- concurrent publication uses locks/uniqueness and advances one head once;
- partial transactions leave no request transition, revision, publication,
  event, outbox, audit, Trace, or activity fragment.

### Tests and validation

- pure parser/normalizer/chunker/metadata determinism;
- locale/timezone/order/randomness resistance;
- stable chunk/revision identities;
- exact and normalized dedup, no cross-workspace disclosure;
- vector artifact reuse and nondeterministic-output failure;
- duplicate requests/deliveries and conflicting digests;
- reindex, supersession, cancellation, source change, revocation, stale worker;
- concurrent publication and transaction failure injection;
- exact provenance, event/outbox, audit/Trace/activity atomicity;
- migration backfill, constraints, downgrade/re-upgrade, PostgreSQL runtime;
- retrieval/citation regression against published immutable revisions;
- affected Milestone 4–6, frontend status/cancel, build, demo, and hygiene.

### Documentation and runbooks

Document supported formats, component/version registry, determinism,
publication, reindex, drift, unsupported/corrupt input, parser failure, stale
index, backlog, and recovery. Publish a 7.2 handoff with immutable migration
hash.

### Commit and exit

Suggested local commit: `Complete Milestone 7.2 deterministic Indexer`

Exit only when native index revisions are reconstructable and publication is
atomic. Production upload publication remains disabled until 7.3 proves the
clean-object gate.

### Explicit exclusions

Autonomous metadata, Librarian behavior, taxonomy, archival/deletion decisions,
managed scanner implementation, durable queue hardening, shared limits,
deployment, and Milestone 8.

## 5. Checkpoint 7.3 — Object Storage, Upload Security, and Malware Quarantine

### Purpose

Ensure no uploaded content can reach parsers, retrieval, models, downloads, or
Indexer publication until exact bytes pass bounded validation and malware
scanning.

### Prerequisites

- 7.2 is committed and `20260726_0026` is the sole head;
- approved isolated private versioned object storage and scanner test
  resources exist;
- upload, storage, document-version, Indexer publication, and authorization
  seams are mapped.

### Exact scope

- provider-neutral upload-session, quarantine, clean, retention, version,
  integrity, and scanner interfaces;
- opaque environment/security-class object keys;
- authenticated upload initiation and completion;
- one-time, short-lived quarantine-only signed upload capabilities;
- multipart limits, expiry, abort, and orphan reconciliation;
- size, checksum, signature-MIME, extension/type, active-content, archive,
  object/page, recursion, and expansion controls;
- isolated scanner result verification;
- closed clean/infected/suspicious/unsupported/error/timeout outcomes;
- checksum-verified clean-copy promotion;
- private reads and exact authorized signed downloads;
- versioning, encryption, retention, deletion, and recovery boundary;
- no processing or publication before current `clean`.

### Migration `20260726_0027`

Direct parent: `20260726_0026`.

Complete scope:

- scoped upload sessions and append-only lifecycle transitions;
- opaque logical objects and immutable provider object versions;
- exact workspace/canvas/document/source-version binding;
- quarantine, clean, rejected, retained, and deletion-request lifecycle;
- checksum/size/media/provider-version evidence;
- immutable malware scan requests/results with scanner identity/version and
  result digest;
- clean promotion identity and source/target checksum binding;
- uniqueness, composite scope, closed states, expiry, and reconciliation
  indexes.

Backfill known existing storage keys, byte sizes, and checksums as
`legacy_unscanned`. Never infer `clean`. Production publication requires a
controlled scan/promotion. Demo/development compatibility remains explicit.

Downgrade is disposable-validation only and cannot delete provider objects.
The downgrade reports external cleanup candidates for a separately verified
operation.

Explicit exclusions:

- scanner proprietary internals and signatures;
- provider bucket names or credentials;
- product legal-hold UI/policy;
- generic archive ingestion;
- content-disarm output;
- queue and rate-limit state.

### Services and APIs

Extend the current `DocumentStorage` seam; do not place provider calls in
routes. `UploadLifecycleService` owns sessions/completion;
`MalwareScanService` owns scan requests/results; `ObjectPromotionService` owns
clean copy; `ObjectReconciler` finds incomplete/orphaned state.

Public APIs expose safe upload capability, completion, status, cancellation,
and authorized clean download. They never expose bucket, physical key,
provider version, scanner signature, credentials, internal errors, or a
cross-scope existence oracle.

### Authorization and isolation

Initiation, completion, replacement, rescan, download, deletion request, and
operational replay each reauthorize exact user/membership/workspace/canvas/
document/version. A signed URL is capability-limited transport, not product
authority. Workers derive scope from durable records, not object metadata.

### Events and evidence

Emit existing-domain events/outbox for upload requested/completed/quarantined,
scan started/passed/rejected, promotion, terminal failure, and deletion
transition. Trace/audit bind actor or controlled execution, exact object
version, source version, checksum, scan record, decision, and safe reason.
Activity reveals bounded authorized status only.

### Configuration and observability

Production requires private access-blocked buckets, versioning, encryption,
retention, scanner trust, upload limits, signed URL expiry, and orphan policy.
Metrics cover bytes, session age, completion/checksum failures, scan latency
and outcomes, promotion mismatch, orphans, storage growth, and dependency
health without keys or filenames.

### Failure and concurrency behavior

- partial/expired/mismatched uploads remain quarantined and expire safely;
- scanner outage, timeout, malformed/unknown result, or trust failure keeps
  quarantine;
- concurrent completion/scan/promotion is idempotent;
- clean promotion verifies source and target bytes;
- replacement never mutates an old object version;
- database/object commit ambiguity is reconciled from immutable identity;
- deletion never targets a client-supplied physical key.

### Tests and validation

- object provider contract, versioning, signed capability, private access;
- checksum/size/type/extension spoof and cross-scope substitution;
- malware clean/infected/suspicious/unavailable/timeout/forgery/replay;
- macro, active content, malformed structures, password-protected containers,
  nesting, excessive objects/pages, archive/decompression bombs;
- multipart expiry, duplicate completion, orphan reconciliation;
- promotion atomicity, object/DB failure injection, retention and deletion;
- no parse/retrieval/download/publication before clean;
- migration backfill and `legacy_unscanned` behavior;
- managed object/scanner staging validation;
- affected Indexer, retrieval, authority, collaboration, build, demo, hygiene.

### Documentation and runbooks

Publish upload limits, supported formats, scanner contract, storage lifecycle,
retention/recovery, object outage, checksum mismatch, malware, quarantine,
scanner outage, orphan, and key-compromise runbooks.

### Commit and exit

Suggested local commit: `Complete Milestone 7.3 secure object ingestion`

Exit only when no unscanned or indeterminate byte can enter protected
processing/publication and the migration is immutable.

### Explicit exclusions

Autonomous classification, OCR unless separately approved as deterministic
adapter work, generic archives, legal/compliance claims, durable queue
hardening, shared limits, deployment, and Milestone 8.

## 6. Checkpoint 7.4 — Durable Queues, Workers, Retries, and Shared Rate Limits

### Purpose

Make background processing horizontally safe under at-least-once delivery,
recovery, cancellation, revocation, duplicate delivery, and multi-replica
abuse pressure.

### Prerequisites

- 7.3 is committed and `20260726_0027` is the sole head;
- Indexer and scan operations expose idempotent staged commands;
- approved managed shared-limit test store exists;
- current document, event outbox, workflow, and agent lease patterns are
  compared before implementation.

### Exact scope

- provider-neutral durable queue contract;
- hardened PostgreSQL queue adapter using existing document jobs;
- distinct request, job run, delivery, lease, attempt, retry, result, and
  publication identities;
- worker identity, heartbeat, visibility, lease generation/renewal/recovery;
- bounded attempts/deadlines, exponential backoff/full jitter, poison and
  dead-letter behavior;
- replay with current authority and new identity;
- cancellation generation and boundary checks;
- workspace/resource/global concurrency, backpressure, fair claiming;
- graceful/forced worker shutdown and recovery;
- shared atomic per-network/user/workspace/resource/operation/provider/global
  limits;
- no silent production fallback to process-local limits;
- safe result publication and domain event/outbox integration.

### Migration `20260726_0028`

Direct parent: `20260726_0027`.

Complete scope:

- evolve existing document processing attempts with stable job-run/request
  identity;
- exact user/membership/workspace/canvas/document/version and authority
  generation;
- cancellation and lease generations, expiry, heartbeat, deadline, maximum
  attempts, eligibility, priority class, and result/publication links;
- append-only queue deliveries, retry decisions, outcomes, and dead-letter
  evidence;
- closed job/failure/retry registries;
- uniqueness and claim/fairness/recovery indexes.

Backfill existing processing rows as legacy job runs/attempts while preserving
IDs, order, outcome, error category, and timestamps. Never invent a successful
lease, delivery, Trace, or authority snapshot.

Downgrade is disposable-validation only after new work is absent. It restores
the prior schema shape without altering historical migrations.

Explicit exclusions:

- persistent rate-limit counters;
- raw queue payloads or provider receipt handles;
- unifying workflow/agent persistence;
- a second domain event outbox;
- Milestone 8 jobs.

### Services and APIs

`DurableJobService` owns create/claim/renew/complete/fail/cancel/retry/dead
letter/replay. The worker consumes only opaque identities and loads scope from
PostgreSQL. Existing domain outbox wakes eligible work idempotently.

Ordinary APIs expose request status and authorized cancel. Closed operator
APIs may list safe dead-letter summaries and request replay; they cannot edit
attempts, forge success, set `clean`, bypass authority, control another
workspace, or publish arbitrary output.

`SharedRateLimitService` centralizes all route and worker budgets behind an
atomic adapter.

### Authorization and isolation

Every claim validates typed scope. Every external call, retry, result, and
publication rechecks current authority/cancel/source generations. Operator
replay is separately authorized and audited. Queue delivery fields are
untrusted hints.

### Events and evidence

Durable state and existing event/outbox/Trace/audit references commit
atomically for material transitions. Per-heartbeat noise is metric-only.
Retries and dead letters retain attempt lineage. Duplicate delivery creates no
duplicate event, Trace root, audit, activity, or publication.

### Configuration and observability

Server-owned closed settings define lease, heartbeat, visibility, deadline,
attempt, backoff, jitter, concurrency, queue age, rate windows, bursts,
dependency budgets, and emergency ceilings. Metrics/alerts cover depth, age,
claim latency, lease loss, attempts, cancellations, poison/dead-letter,
limiter health, denials, bypass, saturation, and cost.

### Failure and concurrency behavior

- at-least-once delivery and ambiguous acknowledgement are normal;
- exact duplicates return or no-op against durable state;
- a recovered stale worker cannot commit;
- canceled/deadline-expired/revoked work cannot commit;
- retries never duplicate mutation/publication/evidence;
- queue or limiter outage fails protected operations safely;
- database failover resolves using durable identities;
- poison jobs and one workspace cannot starve the system.

### Tests and validation

- queue contract and PostgreSQL `SKIP LOCKED` claims;
- multi-worker duplicate delivery and fairness;
- lease renewal/loss/recovery and stale-generation commits;
- cancellation/deadline/revocation at every boundary;
- bounded retry success, terminal retry, jitter, poison, dead letter, replay;
- graceful/forced shutdown and worker recovery;
- publication/evidence atomicity under database/queue/provider failures;
- multi-replica shared limiter atomicity by every required dimension;
- limiter outage, safe `429`/`503`, emergency ceiling and audit;
- migration/backfill/PostgreSQL failover;
- affected workflow/agent/outbox/document/Indexer/security/build/demo suites.

### Documentation and runbooks

Publish queue, worker, retry, dead-letter, replay, cancellation, stale worker,
rate-limit, provider outage, lost worker, backlog, and retry-storm runbooks.

### Commit and exit

Suggested local commit: `Complete Milestone 7.4 durable production work`

Exit only when duplicate delivery, stale workers, retry, cancellation,
dead-letter, and distributed limit behavior are proved and `0028` is immutable.

### Explicit exclusions

Autonomous job decisions, unbounded replay, browser lease controls, provider
lock-in, real-time collaboration, deployment, and Milestone 8.

## 7. Checkpoint 7.5 — Observability and Operational Controls

### Purpose

Make production health, degradation, evidence integrity, abuse, capacity, and
incident response visible without leaking private data or duplicating Trace
and audit.

### Prerequisites

- 7.4 is committed and `20260726_0028` is the sole head;
- every service exposes safe correlation identities and closed failures;
- approved isolated telemetry destinations exist.

### Exact scope

- structured application/security logs;
- OpenTelemetry-compatible metrics and bounded distributed traces;
- redaction, allowlists, pseudonymized dimensions, cardinality budgets;
- request/job/execution/workspace/deployment correlations;
- service, database, storage, scanner, queue, limiter, Indexer, provider,
  event/outbox, backup, cost, and capacity dashboards;
- versioned SLIs/SLOs and actionable alert thresholds;
- liveness/readiness/worker/dependency policy;
- on-call, escalation, incident evidence, and runbooks;
- audit/Trace/outbox continuity and integrity checks.

### Data and migration scope

No migration. Telemetry and incident-management data belongs in bounded
operational stores. Product-facing mitigations and privileged actions use
existing audit/event/Trace persistence.

### Services and APIs

Add instrumentation through interfaces at existing service boundaries. Public
health stays minimal; operator-only health exposes safe classifications.
There is no public raw log, metric, trace, topology, audit internals, or
incident administration API.

### Authorization, privacy, and failure

Telemetry never grants authority. Sink failure cannot block a committed
business transaction, but readiness and alerts record sustained loss.
Security/audit evidence required by a protected transaction remains in the
application database; inability to commit it fails the transaction.

### Tests and validation

- telemetry schema and redaction snapshots;
- secret/content/invitation/grant/approval/identifier injection;
- correlation continuity and no chain-of-thought capture;
- cardinality and bounded-value tests;
- dashboard query and alert firing/recovery tests;
- liveness/readiness/dependency disclosure tests;
- outbox/audit/Trace integrity alerts;
- telemetry outage and backpressure;
- affected build, security, browser health, and hygiene suites.

### Documentation, commit, and exit

Publish dashboards, signal catalog, objectives, alerts, on-call/escalation,
incident evidence, privacy, retention, and every required operational runbook.

Suggested local commit: `Complete Milestone 7.5 production observability`

Exit only when required failures are detectable/actionable, private content is
excluded, no migration exists, and 7.6 is unstarted.

### Explicit exclusions

Product analytics, user surveillance, raw source/prompt capture, parallel
audit/Trace, provider-specific lock-in, deployment, and Milestone 8.

## 8. Checkpoint 7.6 — Backup, Restore, Rollback, and Disaster Recovery

### Purpose

Prove that authoritative data, immutable evidence, objects, queues, indexes,
configuration boundaries, and application service can be recovered safely.

### Prerequisites

- 7.5 is committed;
- managed database/object storage and operations-evidence targets exist in an
  isolated recovery environment;
- approved initial RPO/RTO targets and recovery owners are documented;
- external effects can be locked during restore.

### Exact scope

- continuous managed backup/PITR and portable encrypted backup;
- private object versioning, retention, inventory, integrity, and recovery;
- database/object/application/schema recovery manifest;
- isolated full restore and point-in-time recovery;
- configuration/secret reference recovery without secret-value backup in
  application artifacts;
- cross-resource integrity, outbox recovery, queue reconstruction, index
  reconstruction, and evidence continuity;
- migration failure recovery, application rollback, and forward-fix criteria;
- disaster-recovery isolation, traffic switch, and effects unlock;
- deletion/retention interactions and tenant-level restore limitation;
- signed/checksummed exercise evidence and measured RPO/RTO.

### Data and migration scope

No migration. The independent operations-evidence store proves recovery.
Existing audit/event/Trace records reference authorized product-facing
recovery actions.

### Failure and concurrency behavior

Restore targets have isolated credentials, queues, email/provider egress,
object prefixes, telemetry, and user access. Jobs and outbox deliveries are
reconciled idempotently. No external effect resumes until integrity, schema,
authorization, and tenant isolation pass.

### Tests and validation

- backup creation, encryption, retention, access, and integrity;
- full and PITR database restore;
- object version restore and database/object skew;
- missing/mismatched object quarantine;
- outbox projection and job eligibility recovery;
- index reconstruction from clean canonical sources;
- append-only evidence continuity and tamper detection;
- failed migration and prior-image application rollback;
- forward-fix decision exercise;
- isolated disaster recovery and measured RPO/RTO;
- secret/configuration recovery and no secret leakage;
- authorization/tenant/build/smoke after restore.

### Documentation, commit, and exit

Publish backup, PITR, restore, object recovery, index reconstruction, queue/
outbox recovery, migration failure, rollback, forward-fix, DR, evidence, and
tenant-repair runbooks with exercise results.

Suggested local commit: `Complete Milestone 7.6 production recovery`

Exit only after the complete restore/rollback/DR exercises pass and no
application migration was created.

### Explicit exclusions

Unsafe in-place production restore tests, unsupported tenant rewind, legal
retention claims, deployment/public release, and Milestone 8.

## 9. Checkpoint 7.7 — Load, Capacity, Resilience, and Infrastructure Security

### Purpose

Measure, enforce, and publish credible production limits and prove bounded
recovery under realistic and hostile workload conditions.

### Prerequisites

- 7.6 is committed;
- production-like isolated infrastructure matches intended versions/topology;
- synthetic workload generators and cost ceilings are approved;
- all alerts/runbooks are operational.

### Exact scope

- representative tenant/workspace/user/resource/document/workflow/agent model;
- upload, scanner, parser, indexing, retrieval, collaboration, workflow,
  agent, queue, database, object, limiter, and recovery load;
- stress, soak, spike, mixed workload, and recovery-under-load;
- dependency delay/failure, worker loss, database failover, object/scanner/
  limiter/queue outage, ambiguous commit, and retry storm;
- enforced server-side capacity, concurrency, byte/page/token/time/cost limits;
- secret, dependency, image/container, configuration, egress, privilege,
  backup, and supply-chain security;
- formal infrastructure threat-model validation;
- published supported limits, bottlenecks, residual risks, and scale procedure.

### Data and migration scope

No migration. Results, manifests, dashboards, capacity policies, and exercise
reports are versioned operational/repository artifacts. No synthetic load data
enters production.

### Authorization and isolation

Load generators use isolated synthetic identities and workspaces. Tests prove
no noisy-neighbor tenant can cross scope, exhaust reserved control capacity,
bypass rate/concurrency limits, or continue after revocation.

### Tests and validation

- all workload dimensions listed in the architecture;
- long-running soak and peak spike;
- database connection/lock/vector-index pressure;
- storage throughput, multipart/orphan/retention pressure;
- scanner/parser hostile concurrency;
- queue age, poison, fairness, retry storm, stale workers;
- shared limiter atomicity under horizontal scale;
- retrieval/workflow/agent and collaboration mixed load;
- dependency network delay, loss, failover, and recovery;
- secret, source, dependency, license, image, SBOM, signature, configuration,
  privilege, egress, backup, and runtime scans;
- cost ceiling and shutdown;
- post-test data cleanup and evidence integrity.

### Documentation, commit, and exit

Publish workload model, environment, data scale, commands, results, percentiles,
failure points, enforced ceilings, cost, bottlenecks, residual risks, scaling
triggers, alert/runbook outcomes, and security findings.

Suggested local commit: `Complete Milestone 7.7 production resilience audit`

Exit only with documented supported limits, recovered dependencies, no
critical/high unresolved finding, no migration, and 7.8 unstarted.

### Explicit exclusions

Production user-data load testing, unlimited cost, public SLA promises,
deployment/public release, Advanced Collaboration, and Milestone 8.

## 10. Checkpoint 7.8 — Final Production-Readiness Audit

### Purpose

Audit the complete Milestone 7 system, correct only proved defects, close
Production Hardening, and establish the exact Milestone 8 entry boundary.

### Prerequisites

- 7.1–7.7 are individually complete and committed;
- `20260726_0028` is the expected sole Alembic head;
- migrations `0021`–`0028` have recorded immutable hashes;
- all managed staging and destructive recovery evidence is available.

### Exact audit

- architecture and checkpoint scope;
- managed PostgreSQL, pool, roles, migration, failover, tenant isolation;
- object storage, upload authorization, checksums, quarantine, scanner,
  promotion, retention, deletion, and recovery;
- deterministic Indexer manifests, revisions, dedup, drift, reindex,
  supersession, cancellation, publication, and provenance;
- durable queue/workers, leases, duplicate delivery, retry, poison/dead-letter,
  replay, shutdown, recovery, revocation, and stale suppression;
- shared rate limits and failure behavior;
- logs, metrics, distributed traces, objectives, alerts, evidence integrity,
  privacy, dashboards, and runbooks;
- backup, PITR, object recovery, index/queue/outbox reconstruction, rollback,
  DR, RPO/RTO, and exercise evidence;
- capacity ceilings, stress/soak/spike/failure recovery, infrastructure and
  supply-chain security;
- full Milestone 4–6 authority, evidence, graph, retrieval, workflow, agent,
  collaboration, frontend, browser, demo, migration, and Git regressions;
- documentation, limitations, deployment, and Milestone 8 readiness.

### Data and migration scope

No planned migration. Fix only a concrete defect proved by the audit. If a
durable correction is unavoidable, stop, document the contradiction, allocate
the next unused revision through an explicit amendment, and do not rewrite
`0026`–`0028`.

### Required final scenarios

- malicious or indeterminate upload never leaves quarantine;
- exact duplicate upload/request/delivery does not repeat state/evidence;
- deterministic repeat produces the same revision or explicit drift failure;
- stale, canceled, expired, superseded, or revoked worker cannot publish;
- bounded retry succeeds once and poison work dead-letters once;
- lost lease and failover recover without duplicate durable effects;
- cross-user/workspace/canvas/resource/object/job/index substitution fails
  closed and non-enumerating;
- failed transactions leave no partial mutation, publication, lifecycle,
  lease, event/outbox, Trace, audit, or activity;
- managed backup/PITR/object restore and rollback recover a consistent system;
- shared limits remain atomic across replicas and fail safely;
- telemetry contains no secret or private content;
- load and dependency failure respect published ceilings and recover.

### Final validation

Run all affected backend/frontend/browser suites, managed PostgreSQL/object/
scanner/queue/limiter contracts, migration cycles, compilation, imports,
mapper validation, typing, lint, formatting, production build, security,
dependency/container/configuration scans, demo reset/isolation, backup/restore/
rollback/DR, stress/soak/spike/failure recovery, repository hygiene, secrets,
local paths, whitespace, diff, Git objects, immutable migrations, protected
references, clean tree, and no-upstream checks.

### Documentation, commit, and exit

Create `docs/MILESTONE_7_COMPLETION.md`, update current roadmap/progress/
deployment/limitations documents, and record defects, exact results, skips,
warnings, capacities, RPO/RTO, evidence locations, migration hashes, protected
Git state, and local-only boundary.

Suggested local commit: `Complete Milestone 7 production readiness audit`

Exit only when there is no critical/high unresolved production-readiness
defect and every Milestone 8 entry criterion is proved.

### Explicit exclusions

Deployment/public release, guided onboarding, marketing, billing, Advanced
Collaboration, Mobius Society/Librarian, and all later product-family work.

## 11. Cross-checkpoint validation matrix

| Contract                | 7.1          | 7.2      | 7.3           | 7.4         | 7.5       | 7.6     | 7.7    | 7.8   |
| ----------------------- | ------------ | -------- | ------------- | ----------- | --------- | ------- | ------ | ----- |
| Managed PostgreSQL      | Build        | Use      | Regress       | Load        | Observe   | Restore | Stress | Audit |
| Tenant isolation        | Prove        | Index    | Object        | Job/limit   | Redact    | Restore | Load   | Audit |
| Deterministic Indexer   | —            | Build    | Gate          | Execute     | Observe   | Rebuild | Stress | Audit |
| Malware quarantine      | —            | Contract | Build         | Execute     | Observe   | Restore | Fail   | Audit |
| Durable work            | Foundation   | Domain   | Scan use      | Build       | Observe   | Recover | Stress | Audit |
| Shared limits           | Config seam  | Budget   | Upload budget | Build       | Observe   | Recover | Stress | Audit |
| Evidence/outbox         | Regress      | Extend   | Extend        | Extend      | Monitor   | Recover | Stress | Audit |
| Backup/DR               | Prerequisite | Regress  | Object plan   | Queue plan  | Alert     | Prove   | Load   | Audit |
| Infrastructure security | Roles/TLS    | Parser   | Upload        | Queue/limit | Telemetry | Backup  | Full   | Audit |

## 12. Later-milestone boundary

Milestone 7 does not implement Milestone 8 release/onboarding, Milestone 8.5
Advanced Collaboration, simultaneous editing, presence, cursors, CRDT/OT,
offline merge, Milestone 9 Mobius Society or governed Librarian, marketplace,
Academy, reputation, Worlds, Spatial, Federation, or Continuity.

The deterministic Indexer remains infrastructure. Later governed agents may
propose actions but never inherit Indexer or operator authority.
