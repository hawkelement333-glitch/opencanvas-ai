# Milestone 7 Production Hardening Architecture Handoff

Date: 2026-07-26

Status: architecture complete locally; ready for 7.1 implementation

Architecture:
[`MILESTONE_7_ARCHITECTURE.md`](MILESTONE_7_ARCHITECTURE.md)

Implementation plan:
[`MILESTONE_7_IMPLEMENTATION_PLAN.md`](MILESTONE_7_IMPLEMENTATION_PLAN.md)

Progress:
[`MILESTONE_7_PROGRESS.md`](MILESTONE_7_PROGRESS.md)

## Starting checkpoint

- branch: `milestone-6-7-final-collaboration-security-audit-local`;
- HEAD: `b355cdeac98e866e2de06bde650fff3c21f4c63d`;
- parent: `fd8b625bcf0f7650e15efdfba329d33153c59c21`;
- commit: `Complete Milestone 6 collaboration security audit`;
- working tree: clean;
- upstream: none;
- sole Alembic head: `20260725_0025`;
- no later migration existed.

The architecture work was placed on:
`milestone-7-production-hardening-architecture-local`.

Milestone 6 completion and the 6.7 final collaboration-security audit were
present and committed. Protected branches, tags, main, history, and migrations
through `0025` remained unchanged. No remote operation occurred.

## Repository findings

Mobius already has private storage adapters, validated bounded uploads,
document versions and hashes, deterministic local parsing/chunking,
embeddings, persisted document jobs, worker heartbeats, workflow/agent lease
fencing, collaboration authority generations, domain events, a transactional
outbox, Trace, audit, and activity.

The production gaps are managed PostgreSQL proof, hostile-upload quarantine,
malware scanning, immutable provenance-complete index revisions, separate
retrieval publication, complete job lease/dead-letter behavior, shared limits,
production telemetry/alerts, exercised recovery, and measured capacity/
resilience/security.

No contradiction blocked the architecture.

## Approved checkpoint structure

1. 7.1 Production Runtime Foundation and Managed PostgreSQL
2. 7.2 Deterministic Indexer and Ingestion Pipeline
3. 7.3 Object Storage, Upload Security, and Malware Quarantine
4. 7.4 Durable Queues, Workers, Retries, and Shared Rate Limits
5. 7.5 Observability and Operational Controls
6. 7.6 Backup, Restore, Rollback, and Disaster Recovery
7. 7.7 Load, Capacity, Resilience, and Infrastructure Security
8. 7.8 Final Production-Readiness Audit

Implementation is sequential. A checkpoint must be complete and locally
committed before the next begins.

## Core architecture decisions

### Deterministic Indexer

The Indexer is deterministic infrastructure, not an autonomous agent.
Server-derived scope binds exact user, membership, workspace, canvas, source,
immutable source version, object version, checksum, request, job, component
versions, manifest, index revision, publication, Trace, and audit.

Source bytes plus the canonical component/configuration manifest determine
normalized text, deterministic metadata, chunks, identities, and structural
index output. A vector artifact is immutable on first materialization for that
manifest. A contradictory recomputation fails closed rather than replacing
history.

Index construction and retrieval publication are separate. Publication
rechecks clean malware state, exact source/object version, current authority,
membership/share, cancellation/source/lease generations, complete provenance,
and successful immutable revision in one short transaction. A stale, canceled,
expired, superseded, or revoked worker cannot publish.

Deduplication and near-duplicate diagnostics stay inside one workspace.
Historical revisions and publication evidence are immutable.

### Indexer versus Librarian

The Indexer may validate, parse, normalize, chunk, extract closed deterministic
metadata, hash, deduplicate, build revisions, reindex, publish when authorized,
and report safe lifecycle/health.

It cannot invent titles/tags/taxonomy/relationships, make archival or deletion
decisions, share, broaden access, cross workspaces, grant authority, approve
itself, activate agents, suppress evidence, or make discretionary catalog
decisions.

The governed Librarian remains a proposal-bounded Milestone 9 agent. No
Librarian model, service, workflow, persistence, API, event, agent, or UI is
included in Milestone 7 architecture implementation.

### Managed PostgreSQL

The initial production policy is managed PostgreSQL 17 with compatible
pgvector. API and worker use bounded transaction pools; migrations use one
direct administrative connection, a separate role, an expected-head check,
and an advisory lock. Protected operations use the primary. Failover ambiguity
resolves through durable idempotency identity.

The current workspace is the repository's tenant-isolation domain. No
speculative tenant model is introduced. Server-derived centralized authority,
typed parent scope, composite constraints, least-privilege database roles, and
managed-PostgreSQL cross-scope tests remain authoritative.

RLS is deliberately not a Milestone 7 dependency. Multi-workspace membership,
mixed direct/derived scope, pooling, workers, backup, and maintenance make a
second session-variable authorization engine unsafe without a separately
approved complete policy and reset proof.

### Object storage and malware quarantine

The existing storage seam evolves into upload-session, quarantine, clean,
version, retention, integrity, and scanner contracts. Private physical keys
are opaque. Short-lived signed upload capabilities can write only one exact
quarantine object.

Completion verifies version, size, checksum, current scope, and lifecycle.
Only a verified closed `clean` scan result permits a checksum-verified
server-side copy to a new clean object version. Unknown, unavailable, timeout,
suspicious, infected, unsupported, malformed, encrypted, active, or over-limit
content stays quarantined or is rejected. Legacy objects become
`legacy_unscanned`; migration never invents clean evidence.

### Queue, worker, retry, and rate limits

A provider-neutral durable queue contract uses hardened PostgreSQL row claims
first, extending the existing document-job model. Queue delivery is only a
wake-up hint. Request, job run, delivery, lease, attempt, retry, result, and
publication are distinct.

Lease, authority, cancellation, source, and publication generations fence
stale work. Retries are closed, bounded, deadline-limited, exponentially
backed off with jitter, and dead-lettered. Replay requires current operator
authority, reason, new identity, and evidence.

Production limits are shared and atomic by network subject, user, workspace,
resource, operation, provider, worker pool, and global ceiling. Protected paths
fail safely if the shared limiter is unavailable; they never silently become
unlimited per process.

### Observability and recovery

Logs, security logs, metrics, and distributed traces are minimized operational
telemetry and do not replace application Trace/audit/events. They exclude
source text, prompts, chunks, comments, outputs, credentials, tokens, raw
grants/approvals, storage keys, queue payloads, and private infrastructure.

Backup and restore evidence is stored independently of the database being
recovered. Managed PITR, encrypted portable backups, object versioning and
inventory, isolated restore, queue/outbox recovery, index reconstruction,
migration/application rollback, and disaster recovery are exercised. Exact
RPO/RTO and capacity/SLO numbers are approved from managed staging evidence.

## Provider strategy

- managed PostgreSQL 17 and compatible pgvector;
- private versioned S3-compatible object storage;
- contract-tested isolated or managed malware scanner;
- PostgreSQL durable queue adapter first, with an external broker possible
  later behind the same interface;
- Redis-compatible atomic shared rate limiter;
- OpenTelemetry-compatible telemetry;
- managed secret references/workload identities;
- existing provider protocols for models and embeddings;
- deterministic local substitutes for demo and tests.

No live vendor, account, credential, or infrastructure is selected or
provisioned by this architecture pass.

## Planned migrations

| Checkpoint | Revision        | Direct parent   | Complete scope                                                          |
| ---------- | --------------- | --------------- | ----------------------------------------------------------------------- |
| 7.1        | None            | N/A             | Runtime and managed database behavior only                              |
| 7.2        | `20260726_0026` | `20260725_0025` | Ingestion lifecycle, immutable pipeline/index artifacts and publication |
| 7.3        | `20260726_0027` | `20260726_0026` | Upload/object lifecycle, quarantine, scan evidence, clean promotion     |
| 7.4        | `20260726_0028` | `20260726_0027` | Job runs, delivery/lease/attempt/retry/dead-letter/result fencing       |
| 7.5        | None            | N/A             | External telemetry plus existing product evidence                       |
| 7.6        | None            | N/A             | External recovery evidence plus existing references                     |
| 7.7        | None            | N/A             | Capacity/security evidence artifacts                                    |
| 7.8        | None            | N/A             | Audit only                                                              |

No migration is created now. Rate counters, secrets, provider internals,
telemetry, operational incidents, and backup/restore proof do not belong in
the application schema. Any later correction uses the next unused revision;
committed migrations are immutable.

Exception note: live PostgreSQL 17 validation after this architecture handoff
proved that historical revision `20260718_0005` cannot execute its
`workspaces` table recreation while an existing canonical-object foreign key
depends on the workspace primary key. The
[migration 0005 compatibility amendment](MILESTONE_7_POSTGRESQL_MIGRATION_0005_COMPATIBILITY_AMENDMENT.md)
authorizes one transparent, hash-ledgered correction to that file and a
separate guarded-runner error-preservation correction. This narrow exception
supersedes the general immutability statement only for that approved
correction.

Later clean-chain validation also proved that historical revisions
`20260725_0023` and `20260725_0024` cannot safely recover closed registries
from PostgreSQL-canonicalized check expressions. The
[migrations 0023 and 0024 compatibility amendment](MILESTONE_7_POSTGRESQL_MIGRATIONS_0023_0024_COMPATIBILITY_AMENDMENT.md)
authorizes corrections to exactly those two migration files. Together, the
amendments authorize one combined focused implementation checkpoint and do
not authorize migration `0026` or checkpoint 7.2.

The first combined live implementation attempt subsequently proved that
`0023`'s `_backfill_resources()` derived table resolves untyped null
placeholders as `text` before their assignment to nullable UUID columns. The
[migration 0023 UUID-null compatibility amendment](MILESTONE_7_POSTGRESQL_MIGRATION_0023_UUID_NULL_COMPATIBILITY_AMENDMENT.md)
authorizes only explicit UUID typing in that PostgreSQL backfill branch and
focused regression coverage. It preserves the prior amendments and adds no
Milestone 7.2 authority.

The next live combined attempt reached `0023` append-only trigger creation and
failed because migrations `0023` and `0024` contain four references to the
undefined `reject_controlled_agent_security_mutation()` function. The
[trigger-function compatibility amendment](MILESTONE_7_POSTGRESQL_TRIGGER_FUNCTION_COMPATIBILITY_AMENDMENT.md)
authorizes only replacement of those four references with the already-owned
equivalent deny-all function. It preserves the existing trigger names,
update/delete coverage, migration `0017` domain-event guard, and all prior
amendment boundaries.

A later combined attempt proved a separate PostgreSQL identifier collision
in migration `0021`: its textual role check and matching ORM metadata use bare
`current_role`, which PostgreSQL resolves as session `CURRENT_ROLE`. The
[migration 0021 current-role compatibility amendment](MILESTONE_7_POSTGRESQL_MIGRATION_0021_CURRENT_ROLE_COMPATIBILITY_AMENDMENT.md)
selects the same quoted column expression for both definitions. It adds no
membership, invitation, authority, trigger-function, parser, UUID, runner, or
Milestone 7.2 scope.

With that candidate correction present, the next attempt reached migration
`0021`'s owner backfill and proved that its raw transition `INSERT` target list
also leaves `current_role` bare. The
[migration 0021 owner-backfill current-role compatibility amendment](MILESTONE_7_POSTGRESQL_MIGRATION_0021_BACKFILL_CURRENT_ROLE_COMPATIBILITY_AMENDMENT.md)
authorizes quoting exactly that one target identifier while preserving the
existing source, `owner` value, deterministic IDs and cardinalities, exact
scope and history, and within-run timestamp sharing. Re-upgrade may use a fresh
timestamp. It does not revise the completed architecture ledger or start
checkpoint 7.2.

## Evidence and event boundary

Existing domain events and the transactional outbox remain the only business
event delivery system. Upload, quarantine, scan, ingestion, indexing,
publication, retry, dead-letter, cancellation, and recovery product actions
extend it with exact scope and provenance.

Trace records auditable provenance and execution evidence, not private model
chain of thought. Audit records authority/action/outcome. Activity is an
authorized projection. Operational telemetry carries bounded correlations and
safe classes only.

## Threat summary

The architecture explicitly controls:

- malicious files, parser exploitation, MIME spoofing, active content,
  encrypted containers, excessive nesting/pages/objects, and decompression
  bombs;
- tenant escape, object-key manipulation, forged queue delivery, stale
  workers, replay, duplicate effects, retry storms, dead-letter abuse, and
  rate-limit bypass;
- database exhaustion/failover, storage/scanner/queue/limiter outage, ambiguous
  commits, recovery inconsistency, and storage exhaustion;
- secret, telemetry, backup, migration, dependency, image/runtime, supply
  chain, and privileged-operator compromise.

Controls, detection, response, residual risk, and validation are recorded in
the architecture threat-model table.

## Test strategy

Implementation must cover unit/service/database/migration, managed PostgreSQL,
object contract, scanner/hostile-file/parser isolation, deterministic Indexer,
dedup/reindex/publication, queue/worker/lease/retry/dead-letter/cancellation,
shared limits, tenant/revocation/stale authority, evidence atomicity,
telemetry privacy, backup/restore/rollback/DR, stress/soak/spike/failure/
failover/recovery, supply-chain/security, production build/browser, and demo
regression.

Tests progress from deterministic local substitutes to containers, managed
staging services, production-like environments, and isolated destructive
recovery environments.

## Required operational runbooks

Runbooks are required for upload/quarantine/malware/scanner/parser, Indexer
failure/drift/backlog/publication, queue/worker/retry/dead-letter/limiter,
database/storage/provider/outbox failure, migration/deployment rollback,
backup/PITR/restore/DR, secret/key/dependency/image compromise, tenant
isolation, capacity, and cost.

## Milestone 8 entry criteria

The 7.8 audit must prove managed PostgreSQL and tenant isolation, private
storage and clean upload gating, deterministic immutable Indexer publication,
durable bounded work and shared limits, privacy-safe observability and alerts,
backup/restore/rollback/DR, measured/enforced capacity, infrastructure
security, exercised runbooks, full affected regression, immutable migrations,
and no critical/high unresolved readiness defect.

Only then may Milestone 8 Controlled Public Release and Guided Onboarding
begin.

## Boundary confirmation

This architecture pass:

- changed documentation only;
- created no production code, test, migration, dependency, lockfile,
  configuration, CI, deployment, provider, infrastructure, or frontend;
- did not implement 7.1 or any later checkpoint;
- did not start Milestone 8, Advanced Collaboration, Mobius Society, the
  governed Librarian, or later product-family work;
- did not contact or modify a remote.

## Architecture validation

Documentation formatting passed for all 12 changed Markdown files using the
repository's installed Prettier executable. The workspace package wrapper was
also attempted, but it stopped before formatting because pnpm rejected
ignored optional dependency build scripts. Its incidental workspace-file edit
was removed; dependencies, lockfiles, and workspace configuration are
unchanged. The direct installed formatter then passed.

The following local checks passed:

- `prettier --check` for every changed document;
- `git diff --check`;
- trailing-whitespace scan;
- relative Markdown-link resolution;
- one-H1 and non-skipping heading structure;
- 7.1–7.8 checkpoint order and presence;
- migration allocation and direct-parent consistency;
- roadmap order;
- Indexer-versus-Librarian terminology;
- Milestone 7/Milestone 8/Advanced Collaboration/product-family boundaries;
- server-owned scope and limit terminology;
- stale production-readiness and contradiction scan;
- documentation-only changed-file scope;
- prohibited production code, test, migration, dependency, lockfile,
  configuration, CI, and deployment-artifact checks;
- secret-pattern and local-path scans;
- repository hygiene: 361 source files passed;
- Alembic sole head: `20260725_0025`;
- no migration after `0025`;
- immutable migration Git blob hashes through `0025`;
- protected local branch/tag identities and competition tag target;
- Git object integrity; existing unreachable blobs were informational only.

No application tests, builds, typing, lint, migration cycles, or managed
provider tests were run because production code, tests, dependencies,
configuration, and migrations did not change. Those validations belong to
the implementation checkpoints.

The historical next-work statement below records the architecture handoff at
the time it was written. Checkpoint 7.1 is now complete. The current next
authorized work is the combined migration `0005`, migration `0021` plus its
matching ORM constraint, guarded-runner, `0023`, and `0024` compatibility
correction governed by the six amendments, including the one-token raw
owner-backfill target correction; checkpoint 7.2 remains blocked.

The original next authorized work was exactly:

**7.1 Production Runtime Foundation and Managed PostgreSQL**
