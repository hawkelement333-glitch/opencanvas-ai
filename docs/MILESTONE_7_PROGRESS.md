# Milestone 7 Production Hardening Progress

Date: 2026-07-30

Overall status: architecture and checkpoint 7.1 complete locally; combined
PostgreSQL historical-migration correction for `0005`, `0021`, `0023`, and
`0024` and its evidence complete locally at implementation SHA
`a88c6117f6b58137f1014cc8b389f44966c2918f`; Mobius Family Architecture
Constitution documentation checkpoint complete locally; checkpoint 7.2
complete locally; checkpoint 7.3 complete locally; checkpoint 7.4 complete
locally; checkpoint 7.5 complete locally; checkpoint 7.6 complete locally;
checkpoint 7.7 in progress with local infrastructure-policy,
workload-measurement, and evidence-framework checkpoints complete; checkpoint
7.8 unstarted

Architecture status history: in progress during repository inspection and
decision resolution; complete at this handoff.

Architecture:
[`MILESTONE_7_ARCHITECTURE.md`](MILESTONE_7_ARCHITECTURE.md)

Implementation plan:
[`MILESTONE_7_IMPLEMENTATION_PLAN.md`](MILESTONE_7_IMPLEMENTATION_PLAN.md)

Mobius Family Architecture Constitution:
[`MOBIUS_FAMILY_ARCHITECTURE_CONSTITUTION.md`](MOBIUS_FAMILY_ARCHITECTURE_CONSTITUTION.md)

Architecture handoff:
[`MILESTONE_7_ARCHITECTURE_HANDOFF.md`](MILESTONE_7_ARCHITECTURE_HANDOFF.md)

Checkpoint 7.1 handoff:
[`MILESTONE_7_1_PRODUCTION_RUNTIME_MANAGED_POSTGRESQL_HANDOFF.md`](MILESTONE_7_1_PRODUCTION_RUNTIME_MANAGED_POSTGRESQL_HANDOFF.md)

Checkpoint 7.2 handoff:
[`MILESTONE_7_2_DETERMINISTIC_INDEXER_HANDOFF.md`](MILESTONE_7_2_DETERMINISTIC_INDEXER_HANDOFF.md)

Checkpoint 7.3 handoff:
[`MILESTONE_7_3_OBJECT_STORAGE_UPLOAD_SECURITY_MALWARE_QUARANTINE_HANDOFF.md`](MILESTONE_7_3_OBJECT_STORAGE_UPLOAD_SECURITY_MALWARE_QUARANTINE_HANDOFF.md)

Checkpoint 7.4 handoff:
[`MILESTONE_7_4_DURABLE_QUEUES_SHARED_LIMITS_HANDOFF.md`](MILESTONE_7_4_DURABLE_QUEUES_SHARED_LIMITS_HANDOFF.md)

Checkpoint 7.5 handoff:
[`MILESTONE_7_5_OBSERVABILITY_HANDOFF.md`](MILESTONE_7_5_OBSERVABILITY_HANDOFF.md)

Checkpoint 7.6 handoff:
[`MILESTONE_7_6_BACKUP_RESTORE_DISASTER_RECOVERY_HANDOFF.md`](MILESTONE_7_6_BACKUP_RESTORE_DISASTER_RECOVERY_HANDOFF.md)

Checkpoint 7.7 Checkpoint 1 handoff:
[`MILESTONE_7_7_CHECKPOINT_1_INFRASTRUCTURE_POLICY_MANIFEST_HANDOFF.md`](MILESTONE_7_7_CHECKPOINT_1_INFRASTRUCTURE_POLICY_MANIFEST_HANDOFF.md)

Checkpoint 7.7 Checkpoint 2 handoff:
[`MILESTONE_7_7_CHECKPOINT_2_WORKLOAD_MEASUREMENT_HANDOFF.md`](MILESTONE_7_7_CHECKPOINT_2_WORKLOAD_MEASUREMENT_HANDOFF.md)

Checkpoint 7.7 Checkpoint 3 handoff:
[`MILESTONE_7_7_CHECKPOINT_3_LOCAL_EVIDENCE_FRAMEWORK_HANDOFF.md`](MILESTONE_7_7_CHECKPOINT_3_LOCAL_EVIDENCE_FRAMEWORK_HANDOFF.md)

Checkpoint 7.7 Checkpoint 4 handoff:
[`MILESTONE_7_7_CHECKPOINT_4_LOCAL_FAILURE_INJECTION_FRAMEWORK_HANDOFF.md`](MILESTONE_7_7_CHECKPOINT_4_LOCAL_FAILURE_INJECTION_FRAMEWORK_HANDOFF.md)

Checkpoint 7.7 Checkpoint 5 handoff:
[`MILESTONE_7_7_CHECKPOINT_5_LOCAL_VALIDATION_HANDOFF.md`](MILESTONE_7_7_CHECKPOINT_5_LOCAL_VALIDATION_HANDOFF.md)

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

PostgreSQL migration 0021 owner-backfill current-role compatibility amendment:
[`MILESTONE_7_POSTGRESQL_MIGRATION_0021_BACKFILL_CURRENT_ROLE_COMPATIBILITY_AMENDMENT.md`](MILESTONE_7_POSTGRESQL_MIGRATION_0021_BACKFILL_CURRENT_ROLE_COMPATIBILITY_AMENDMENT.md)

## Mobius Family Architecture Constitution checkpoint

Branch: `milestone-7-family-architecture-constitution`

Parent SHA: `7189f8770e35403a9f67c7b254a1b5bd2edd5b27`

This documentation-only checkpoint establishes the canonical
[Mobius Family Architecture Constitution](MOBIUS_FAMILY_ARCHITECTURE_CONSTITUTION.md),
including:

- the Mobius Family Security Constitution;
- the Mobius Family Release Readiness Constitution;
- the Same-Milestone Control Rule;
- the constitutional hierarchy and product-profile inheritance model;
- reusable product-profile, release-readiness, exception, and
  evidence-freshness templates; and
- explicit separation of binding requirements, current verified evidence,
  planned evidence, known limitations, and approved exceptions.

Milestone 7.8 owns the complete cross-family readiness audit. Milestone 8.0
must verify fresh evidence for the exact release candidate and make the
release decision; it is not a broad deferred implementation or defect-repair
phase.

This checkpoint implements no technical control, approves no exception or
release, and changes no code, tests, migrations, configuration, dependencies,
lockfiles, CI, infrastructure, credentials, or deployment files. Migration
`0026` remains absent and checkpoint 7.2 remains unstarted.

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
deny-all update/delete behavior. A later run additionally proved that
migration `0021` and the matching ORM constraint use bare textual
`current_role`, which PostgreSQL resolves as session `CURRENT_ROLE` and can
reject a valid initial owner transition. With that candidate correction
present, the newest run reached `_backfill_owner_memberships()` and proved a
second, independent migration `0021` failure: the raw transition `INSERT`
target list leaves `current_role` bare and PostgreSQL rejects the syntax. The
most complete combined work was restored from stash
`9196c8d9f68c1af6251530f349fdf72638b57b82` with `git stash apply`; the
stash remains present and undropped.

The six documentation amendments authorize one combined, separately
implemented, hash-ledgered correction checkpoint for migration `0005`,
migration `0021` plus its ORM metadata, the guarded runner, and migrations
`0023` and `0024`. The two `0021` amendments separately limit authority to
identical explicitly quoted role checks, one quoted raw transition-target
identifier, and focused role, owner-backfill, session-independence, atomicity,
SQLite-equivalence, and parity tests. UUID-null authority is limited to `0023`'s PostgreSQL resource
backfill. Trigger-function authority is limited to four exact references in
`0023` and `0024`. The combined implementation has now passed the complete
clean and focused PostgreSQL and SQLite migration cycles, cross-migration
registry, UUID-backfill, trigger identity, mutation-blocking, lock cleanup,
original-error preservation, and required regressions. Migration `0026`
remains absent and checkpoint 7.2 remains unstarted.

## Combined PostgreSQL correction closure

The local implementation branch is
`milestone-7-postgresql-historical-migrations-complete-local`.

Active migration hashes:

- `0005`: `79667acf61794c139b2cc27dcf8f2e0598162a5e`;
- `0021`: `43939e1652e052bbeb3b3de8fd20e052443273d3`;
- `0023`: `cb7138d9de806e1546c3853944b1816a98da1d67`;
- `0024`: `cc29d1280af1a4110ec42b7f0fa782f710dcfeb5`.

The original hashes and inactive candidates remain permanent evidence. The
validator accepts only the active hashes, preserves all 21 unrelated hashes,
and enforces PostgreSQL-sensitive identifier safety for migration raw SQL and
textual ORM constraints.

Validated evidence includes:

- all six required PostgreSQL downgrade/re-upgrade cycles and a clean empty
  schema through `20260725_0025`;
- PostgreSQL marker suite: 11 passed, 0 failed, 0 skipped, including the
  service-restart case;
- complete backend suite: 623 passed, 0 failed, 0 skipped, 61 known
  deprecation warnings;
- identifier guard: 31 passed with no failures, skips, or warnings;
- focused `0021` and ORM suite: 3 passed with 10 known SQLite datetime
  warnings;
- focused parser and UUID suite: 41 passed;
- focused trigger and mutation suite: 2 passed;
- focused SQLite migration suites: 9 passed;
- focused runner and locking suites: 14 passed;
- integration suite: 22 passed with one known Starlette deprecation warning;
- security suite: 38 passed with no warnings;
- frontend unit tests: 74 passed; strict frontend typecheck, lint, Prettier,
  production build, and browser smoke passed;
- strict backend typing, Ruff, compilation, imports, SQLAlchemy mapper
  configuration, migration validation, deterministic demo validation,
  repository hygiene, and static scope/secret/prohibited checks passed.

Implementation SHA: `a88c6117f6b58137f1014cc8b389f44966c2918f`.

Evidence commit: this documentation-only commit; its exact SHA is reported in
the final handoff after commit creation.

No remote operation, deployment, publication, or Milestone 7.2 implementation
is part of this correction checkpoint.

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

| Area                                               | Status                       |
| -------------------------------------------------- | ---------------------------- |
| Repository and gap inspection                      | Complete                     |
| 7.1 managed PostgreSQL/runtime architecture        | Complete                     |
| 7.2 deterministic Indexer architecture             | Complete                     |
| 7.3 object storage/upload/malware architecture     | Complete                     |
| 7.4 queue/worker/retry/rate-limit architecture     | Complete                     |
| 7.5 observability/operations architecture          | Complete                     |
| 7.6 backup/restore/rollback/DR architecture        | Complete                     |
| 7.7 load/capacity/resilience/security architecture | Complete                     |
| 7.8 final audit architecture                       | Complete                     |
| Migration allocation                               | Complete                     |
| Threat model                                       | Complete                     |
| Provider/configuration/secret strategy             | Complete                     |
| Test and runbook strategy                          | Complete                     |
| Milestone 8 entry criteria                         | Complete                     |
| 7.1 production runtime implementation              | Complete                     |
| Combined PostgreSQL compatibility correction       | Complete                     |
| Mobius Family Architecture Constitution            | Complete; documentation only |
| 7.2 deterministic Indexer implementation           | Complete locally             |
| 7.3 object-storage/upload/malware implementation   | Complete locally             |
| 7.4 durable-work/shared-limit implementation       | Complete locally             |
| 7.5 observability implementation                   | Complete locally             |
| 7.6 recovery implementation                        | Complete locally             |
| 7.7–7.8 implementation                             | Not started                  |
| 7.6 isolated infrastructure deployment             | Validated; fully removed     |
| Current 7.7 infrastructure                         | Absent                       |

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
| 7.2        | `20260726_0026`  | `20260725_0025` | Complete locally; sole head                      |
| 7.3        | `20260726_0027`  | `20260726_0026` | Complete locally; sole head                      |
| 7.4        | `20260726_0028`  | `20260726_0027` | Complete locally; sole head                      |
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
PostgreSQL migration compatibility defects are governed by the six focused
correction amendments, and their combined validation gate has passed locally.
Checkpoint 7.2 subsequently completed locally and established sole head
`20260726_0026`. The following operating values remain intentionally
determined from approved managed staging evidence during their owning later
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

## Checkpoint 7.4 closure

Checkpoint 7.4 extends the existing document jobs with durable request,
delivery, attempt, retry, outcome, dead-letter, replay, audit, Trace, and
domain-event identities. PostgreSQL `SKIP LOCKED`, workspace/global
concurrency, lease renewal/recovery, generation fencing, bounded full-jitter
retry, separately authorized replay, safe status/cancel APIs, and
fail-closed shared multi-dimensional limits are implemented. Migration
`20260726_0028` is the sole head and direct child of `20260726_0027`.

The one bounded broad backend campaign recorded 652 passed, 19 failed,
14 skipped, and 51 warnings. The failures were stale expected-head
assertions/validator state and deployed-settings fixtures. The affected
correction groups passed without repeating the broad campaign. Whole-package
strict mypy continues to expose two unchanged Indexer route annotation errors;
the affected 7.4 surface passes strict typing. Exact validation, defects,
skips, prerequisite evidence, dependency, and revalidation boundaries are in
the
[`MILESTONE_7_4_DURABLE_QUEUES_SHARED_LIMITS_HANDOFF.md`](MILESTONE_7_4_DURABLE_QUEUES_SHARED_LIMITS_HANDOFF.md).

## Checkpoint 7.5 closure

Checkpoint 7.5 — Observability and Operational Controls — is complete locally
on `milestone-7-5-implementation-local`. One centralized provider-neutral
layer supplies closed structured application/security logs,
OpenTelemetry-compatible bounded metrics and operational spans, scoped
pseudonymous correlations, cardinality enforcement, bounded export failure,
public/operator health separation, integrity findings, dashboards,
provisional objectives, alerts, privacy/retention, escalation, and operational
runbooks.

Operational telemetry remains distinct from product Trace, audit, activity,
domain events, and outbox evidence. No migration exists; `20260726_0028`
remains the sole head and its blob remains immutable. No approved isolated
live telemetry destination was available, so external exporter, Azure
Monitor/Log Analytics, dashboard rendering, alert delivery, destination
retention/access, and application-to-Azure validation remain explicit
pre-production/Milestone 7.8 revalidation triggers.

Exact implementation and validation evidence is in
[`MILESTONE_7_5_OBSERVABILITY_HANDOFF.md`](MILESTONE_7_5_OBSERVABILITY_HANDOFF.md).

## Checkpoint 7.6 closure

Checkpoint 7.6 — Backup, Restore, Rollback, and Disaster Recovery — is
complete locally on `milestone-7-6-recovery-adapter`. The recovery-only
Valkey authentication adapter and hardened immutable application image
supported an isolated managed exercise covering full restore, PITR, encrypted
portable recovery, failback, cross-resource integrity, private effect locking,
signed evidence, role revocation, and complete cleanup.

Results 14–24 passed and the final Stage 3 decision is
`DEPLOYMENT VALIDATED`. The exercise found one Azure-only NSG defect: a
`VirtualNetwork` service-tag allow rule reached a public destination through
the firewall route. Narrowing the rule to the exact recovery VNet CIDR made
Network Watcher and the final public-destination probes deny access. No
repository code, migration, or infrastructure-as-code changed for that fix.

The PITR, full-restore, portable-recovery, and failback RTO values are measured
exercise upper bounds, not production SLOs. Exact Stage 3 posted cost remains
unknown because Azure Cost Management returned `429` and usage posting is
delayed; the portal's `$0.08` overall subscription cost is not attributed to
Stage 3. Category-log rows did not arrive before cleanup, although private
metrics were confirmed. Both unknowns remain explicit revalidation triggers.

The recovery resource group, temporary access, identities, roles, keys,
evidence destination, restore targets, network, and local temporary files were
removed with zero recovery-environment residue. The protected Milestone 7.3
inventory was unchanged. No migration was added; `20260726_0028` remains the
sole head and migration `0029` remains absent.

Exact evidence and the exercised operating procedure are in
[`MILESTONE_7_6_BACKUP_RESTORE_DISASTER_RECOVERY_HANDOFF.md`](MILESTONE_7_6_BACKUP_RESTORE_DISASTER_RECOVERY_HANDOFF.md)
and [`PRODUCTION_RECOVERY_RUNBOOK.md`](PRODUCTION_RECOVERY_RUNBOOK.md).

## Checkpoint 7.7 local progress

Checkpoint 1 established the inert, resource-free Bicep and policy manifest at
commit `6a4bc94744919f28ff0286e543097fb96b8a1e89`. Checkpoint 2 establishes the
deterministic bounded local workload and measurement contract. Checkpoint 3
establishes the strict bounded local evidence-package schema, exact artifact
inventory and Checkpoint 2 bindings, claim/completeness controls, explicitly
unsigned and local-only retention metadata, and deterministic
network-incapable verification. A locally complete package remains only
synthetic-local contract evidence; it does not complete Milestone 7.7
evidence.

No checkpoint contacted Azure, authorized provisioning, executed a managed
workload, produced production performance/capacity evidence, signed or
published evidence, or provided independent retention. The previously
disclosed Checkpoint 2 migration-validation deviation used disposable SQLite;
Checkpoint 3 did not repeat the script or execute a migration command.

The Checkpoint 3 completion audit invoked the repository's `pnpm exec`
formatter wrapper. That wrapper attempted to retrieve pnpm metadata from the
npm registry and failed before installing or changing dependencies. The
installed local formatter subsequently passed, but the attempted network
operation violated that run's Checkpoint 3 commit gate. A separately authorized
recovery then repeated the applicable commit gates fully offline using
installed executables directly. The recovery installed nothing, contacted no
network or remote service, and all available gates passed. Checkpoint 3 is now
complete locally.

Checkpoint 4 establishes a strict, deterministic, non-executing local
failure-injection plan. Its closed 22-scenario catalog binds later isolated
resilience exercises to the Checkpoint 1–3 identities, one-fault concurrency,
hard workload and cost ceilings, prerequisites, expected outcomes, assertions,
evidence, rollback, cleanup, and abort conditions. Its verifier reports the
plan valid while preserving execution as blocked and Milestone evidence as
partial.

Checkpoint 4 contacted no network or provider, ran no live load or fault,
provisioned nothing, and cannot mutate application, database, deployment, or
infrastructure state. All ten Checkpoint 1 gates and five additional runtime
gates remain unresolved. No production capacity, resilience, security,
cleanup, signing, publication, or independent-retention claim was created.

Checkpoint 5 aggregates the public Checkpoint 1–4 validators into one strict,
bounded, deterministic report. It revalidates the exact infrastructure,
workload, evidence, failure-plan, and scenario-catalog bindings; preserves all
negative evidence and 15 unresolved gates; and requires fail-closed rejection
coverage for malformed, unknown, tampered, incompatible, incomplete,
secret-bearing, private, path-unsafe, out-of-bounds, or authority-strengthening
input.

Checkpoint 5 is local contract validation only. It contacted no network or
provider, ran no workload or fault, provisioned nothing, and resolved no
external gate. Milestone evidence remains partial and execution remains
blocked.

Checkpoint 6 scope definition is complete locally. It records only safe
account fingerprints, the two approved regions, exact intended future
resource-group names, a 24-hour evidence contract, all 15 unresolved gates,
and an 18-slot closed operation inventory. Seventeen operation slots remain
blocked because no exact safe command template is established by repository
sources.

The separately authorized read-only Azure Topology Preflight proved only
`current-account-context`. Its sanitized evidence ID is
`m7.7-cp6-20260730-195532z`, with integrity SHA-256
`f2af5b10703f0f0a88237e1e8f154b330b3f5a9c656aa900a3b397ed851f7a4a`,
and classification `complete-with-provisioning-blocked`. The complete
canonical evidence object existed only in memory; the repository preserves the
sanitized report, not that object, and this documentation does not renew its
recorded expiry. No Azure validation occurred during this documentation-only
reconciliation.

Milestone 7.7 remains in progress. The other 17 operation slots and all ten
infrastructure gates remain blocked; all five runtime gates remain unproved.
Provisioning remains blocked. Checkpoint 7 and Milestone 7.8 remain unstarted
and require separate authorization.
