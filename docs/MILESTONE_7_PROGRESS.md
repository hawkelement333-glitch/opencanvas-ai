# Milestone 7 Production Hardening Progress

Date: 2026-07-27

Overall status: architecture and checkpoint 7.1 complete locally; PostgreSQL
migration compatibility amendments for `0005`, `0021`, `0023`, and `0024`,
including the `0021` migration/ORM current-role, `0023` UUID-null, and
`0023`/`0024` trigger-function boundaries, recorded; combined focused
correction pending; checkpoint 7.2 not started

Architecture status history: in progress during repository inspection and
decision resolution; complete at this handoff.

Architecture:
[`MILESTONE_7_ARCHITECTURE.md`](MILESTONE_7_ARCHITECTURE.md)

Implementation plan:
[`MILESTONE_7_IMPLEMENTATION_PLAN.md`](MILESTONE_7_IMPLEMENTATION_PLAN.md)

Architecture handoff:
[`MILESTONE_7_ARCHITECTURE_HANDOFF.md`](MILESTONE_7_ARCHITECTURE_HANDOFF.md)

Checkpoint 7.1 handoff:
[`MILESTONE_7_1_PRODUCTION_RUNTIME_MANAGED_POSTGRESQL_HANDOFF.md`](MILESTONE_7_1_PRODUCTION_RUNTIME_MANAGED_POSTGRESQL_HANDOFF.md)

PostgreSQL compatibility amendment:
[`MILESTONE_7_POSTGRESQL_MIGRATION_0005_COMPATIBILITY_AMENDMENT.md`](MILESTONE_7_POSTGRESQL_MIGRATION_0005_COMPATIBILITY_AMENDMENT.md)

PostgreSQL migrations 0023 and 0024 compatibility amendment:
[`MILESTONE_7_POSTGRESQL_MIGRATIONS_0023_0024_COMPATIBILITY_AMENDMENT.md`](MILESTONE_7_POSTGRESQL_MIGRATIONS_0023_0024_COMPATIBILITY_AMENDMENT.md)

PostgreSQL migration 0023 UUID-null compatibility amendment:
[`MILESTONE_7_POSTGRESQL_MIGRATION_0023_UUID_NULL_COMPATIBILITY_AMENDMENT.md`](MILESTONE_7_POSTGRESQL_MIGRATION_0023_UUID_NULL_COMPATIBILITY_AMENDMENT.md)

PostgreSQL migrations 0023 and 0024 trigger-function compatibility amendment:
[`MILESTONE_7_POSTGRESQL_TRIGGER_FUNCTION_COMPATIBILITY_AMENDMENT.md`](MILESTONE_7_POSTGRESQL_TRIGGER_FUNCTION_COMPATIBILITY_AMENDMENT.md)

PostgreSQL migration 0021 current-role compatibility amendment:
[`MILESTONE_7_POSTGRESQL_MIGRATION_0021_CURRENT_ROLE_COMPATIBILITY_AMENDMENT.md`](MILESTONE_7_POSTGRESQL_MIGRATION_0021_CURRENT_ROLE_COMPATIBILITY_AMENDMENT.md)

## PostgreSQL migration compatibility gate

An isolated Ubuntu 24.04.4/WSL 2 environment with PostgreSQL 17.10 and
pgvector 0.8.5 proved a clean-install failure in historical migration
`20260718_0005`. Its unconditional `workspaces` table recreation attempts to
replace `workspaces_pkey` while `canonical_objects_workspace_id_fkey` depends
on that key. The guarded runner then attempts advisory unlock inside the
failed transaction and can mask the primary exception.

With provisional `0005` and runner corrections applied only for diagnosis,
the clean chain then failed in `0023`; repository inspection and a live
SQLAlchemy probe proved that both `0023` and `0024` use the same unsafe
comma-splitting parser for PostgreSQL-canonicalized check expressions.

The first combined live attempt then proved a separate `0023` failure:
`_backfill_resources()` wraps untyped null UUID placeholders in a derived
table, PostgreSQL resolves them as `text`, and assignment to UUID destinations
fails. After that correction was added, the next live attempt reached
append-only trigger installation and proved that `0023` and `0024` contain
four references to an undefined
`reject_controlled_agent_security_mutation()` function. The existing
`reject_controlled_agent_mutation()` function supplies the exact required
deny-all update/delete behavior. The newest run additionally proved that
migration `0021` and the matching ORM constraint use bare textual
`current_role`, which PostgreSQL resolves as session `CURRENT_ROLE` and can
reject a valid initial owner transition. The most complete combined work is
preserved outside the working tree in stash
`58ffed44184ea3450a80f5883681da988a196ae7`.

The five documentation amendments authorize one combined, separately
implemented, hash-ledgered correction checkpoint for migration `0005`,
migration `0021` plus its ORM metadata, the guarded runner, and migrations
`0023` and `0024`. New `0021` authority is limited to identical explicitly
quoted role checks and focused role, owner, session-independence, and parity
tests. UUID-null authority is limited to `0023`'s PostgreSQL resource
backfill. Trigger-function authority is limited to four exact references in
`0023` and `0024`. Migration `0026` and checkpoint 7.2 remain blocked until
the complete clean and focused PostgreSQL and SQLite migration cycles,
cross-migration registry, UUID-backfill, trigger identity, mutation-blocking,
lock cleanup, original-error preservation, and all required regressions pass.
No implementation, migration, or production-code change is part of these
amendments.

## Baseline

- source branch:
  `milestone-6-7-final-collaboration-security-audit-local`;
- source HEAD: `b355cdeac98e866e2de06bde650fff3c21f4c63d`;
- source parent: `fd8b625bcf0f7650e15efdfba329d33153c59c21`;
- source commit: `Complete Milestone 6 collaboration security audit`;
- architecture branch:
  `milestone-7-production-hardening-architecture-local`;
- baseline working tree: clean;
- upstream: none;
- Alembic sole head: `20260725_0025`;
- no migration after `0025`;
- migrations `0021`–`0025` retained their verified immutable Git blob hashes;
- Milestone 6 completion and 6.7 handoff were present and committed;
- protected local branches, tags, main, and history were unchanged;
- no remote operation was required or performed.

## Architecture status

| Area                                               | Status      |
| -------------------------------------------------- | ----------- |
| Repository and gap inspection                      | Complete    |
| 7.1 managed PostgreSQL/runtime architecture        | Complete    |
| 7.2 deterministic Indexer architecture             | Complete    |
| 7.3 object storage/upload/malware architecture     | Complete    |
| 7.4 queue/worker/retry/rate-limit architecture     | Complete    |
| 7.5 observability/operations architecture          | Complete    |
| 7.6 backup/restore/rollback/DR architecture        | Complete    |
| 7.7 load/capacity/resilience/security architecture | Complete    |
| 7.8 final audit architecture                       | Complete    |
| Migration allocation                               | Complete    |
| Threat model                                       | Complete    |
| Provider/configuration/secret strategy             | Complete    |
| Test and runbook strategy                          | Complete    |
| Milestone 8 entry criteria                         | Complete    |
| 7.1 production runtime implementation              | Complete    |
| 7.2–7.8 implementation                             | Not started |
| Live infrastructure/provisioning/deployment        | Not started |

## Formal implementation checkpoints

1. **7.1 Production Runtime Foundation and Managed PostgreSQL**
2. **7.2 Deterministic Indexer and Ingestion Pipeline**
3. **7.3 Object Storage, Upload Security, and Malware Quarantine**
4. **7.4 Durable Queues, Workers, Retries, and Shared Rate Limits**
5. **7.5 Observability and Operational Controls**
6. **7.6 Backup, Restore, Rollback, and Disaster Recovery**
7. **7.7 Load, Capacity, Resilience, and Infrastructure Security**
8. **7.8 Final Production-Readiness Audit**

Each checkpoint is sequential, locally committed, migration-complete where
required, and closed before the next begins.

## Migration allocation

| Checkpoint | Planned revision | Direct parent   | Status                                           |
| ---------- | ---------------- | --------------- | ------------------------------------------------ |
| 7.1        | None             | N/A             | Complete; runtime/configuration only             |
| 7.2        | `20260726_0026`  | `20260725_0025` | Planned, not created                             |
| 7.3        | `20260726_0027`  | `20260726_0026` | Planned, not created                             |
| 7.4        | `20260726_0028`  | `20260726_0027` | Planned, not created                             |
| 7.5        | None             | N/A             | External telemetry + existing evidence           |
| 7.6        | None             | N/A             | External recovery evidence + existing references |
| 7.7        | None             | N/A             | Test/evidence artifacts only                     |
| 7.8        | None             | N/A             | Audit only unless amended for a proved defect    |

No revision is reserved empty. No migration was created or edited by this
architecture pass.

## Resolved decisions

### Deterministic Indexer

- The Indexer is deterministic technical infrastructure, not an agent.
- Exact bytes plus an exact versioned manifest determine structural output.
- External vector output is immutable on first successful materialization;
  contradictory recomputation under the same manifest fails closed.
- Index revisions and publication history are immutable.
- Retrieval visibility is a separate short, authorized, atomic publication.
- Deduplication and near-duplicate diagnostics stay within one workspace.
- No autonomous titles, tags, taxonomy, archival, deletion, sharing, access,
  relationships, or self-approval.
- The governed Librarian remains Milestone 9.

### Tenant and database boundary

- The current workspace is the repository's tenant-isolation domain; no
  speculative `Tenant` entity is added.
- Server-derived membership/workspace/canvas/resource scope, centralized
  authorization, composite constraints, and least-privilege database roles
  remain authoritative.
- Managed PostgreSQL 17 plus compatible pgvector is the initial version policy.
- API/worker traffic uses bounded transaction pools; migrations use one direct
  advisory-locked task and a separate role.
- RLS is not a Milestone 7 dependency because the current multi-workspace
  pooled schema cannot safely support a second unproved authorization engine.

### Object and hostile-upload boundary

- Physical keys are opaque and contain no user/workspace/title/checksum data.
- Upload capabilities can write only one quarantine object for a short time.
- Only a verified `clean` scan result permits checksum-verified promotion.
- Unknown, unavailable, timeout, suspicious, infected, unsupported, malformed,
  encrypted, active, or over-limit input fails closed.
- Legacy objects backfill as `legacy_unscanned`, never inferred clean.

### Work and rate-limit boundary

- PostgreSQL is the first durable queue adapter behind a provider-neutral
  interface, extending the current document-job model.
- Queue delivery is not job truth, authority, result, or publication.
- Request, job run, delivery, lease, attempt, retry, result, and publication
  remain distinct.
- Lease, authority, cancellation, and source generations fence stale work.
- Retries are classified, bounded, jittered, and dead-lettered.
- Production rate limits are shared and atomic; protected paths do not fall
  back silently to per-process limits.

### Evidence and recovery boundary

- The existing event/outbox, Trace, audit, and activity systems are extended,
  not copied.
- Telemetry is minimized operational evidence and never replaces audit/Trace.
- Backup/restore proof is stored independently of the database being recovered,
  with existing application evidence references after authorized actions.
- Tenant-level point-in-time rewind is not claimed.

## Provider strategy

Providers remain behind explicit contracts. The reference directions are:

- managed PostgreSQL 17 with compatible pgvector;
- private versioned S3-compatible object storage;
- a contract-tested isolated or managed malware scanner;
- a hardened PostgreSQL durable queue first;
- a Redis-compatible atomic shared limiter;
- OpenTelemetry-compatible telemetry;
- managed secret references/workload identities;
- existing approved model and embedding provider protocols.

Local deterministic substitutes remain available for demo and tests.

## Implementation parameters still to measure

The production architecture remains resolved. The proved historical
PostgreSQL migration compatibility defects are governed by the five focused
correction amendments and block checkpoint 7.2 until their combined
validation gate passes. The following operating values remain intentionally
determined from approved managed staging evidence during the owning
checkpoint:

- exact provider/vendor selection;
- connection, worker, queue, upload, parser, token, concurrency, and cost
  ceilings;
- service-level objective and alert threshold numbers;
- backup retention and numeric RPO/RTO;
- documented supported tenant/workspace/document load limits.

They are controlled implementation and operating values, not permission to
change the architecture.

## Required runbooks

The plan assigns runbooks for upload/quarantine/malware, scanner/parser
failure, Indexer drift/backlog/publication, queue/worker/retry/dead-letter,
shared limits, database/object/provider outage, migration/deployment failure,
backup/restore/rollback/DR, outbox/evidence integrity, secret/key/dependency
compromise, tenant isolation, capacity, and cost.

## Milestone 8 gate

Milestone 8 remains unstarted. It may begin only after 7.8 proves managed
PostgreSQL, secure private storage, malware quarantine, deterministic Indexer,
durable bounded work, shared limits, observability, backup/restore/rollback/DR,
capacity and resilience limits, infrastructure security, runbooks, tenant
isolation, evidence integrity, and no critical/high unresolved
production-readiness defect.

## Explicit later boundaries

- Milestone 8 Controlled Public Release and Guided Onboarding: not started.
- Milestone 8.5 Advanced Collaboration, simultaneous editing, presence,
  cursors, CRDT/OT, and offline merge: not started.
- Milestone 9 Mobius Society and governed Librarian: not started.
- Worlds, Spatial, Federation, and Continuity: not started.
- No autonomous Indexer judgment, deployment, provider provisioning, or public
  release is authorized by this architecture pass.

## Next authorized work

The combined PostgreSQL migration `0005`, migration `0021` plus matching ORM
metadata, guarded-runner, `0023`, and `0024` correction checkpoint, including
the narrowly authorized quoted `0021` role check, `0023` UUID-null typing, and
four `0023`/`0024` trigger-function reference replacements, is the only next
authorized implementation work.
Checkpoint 7.2 — Deterministic Indexer and Ingestion Pipeline — remains
unstarted and may restart only after the combined compatibility gate passes.
