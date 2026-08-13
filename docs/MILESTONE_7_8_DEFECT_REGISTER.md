# Milestone 7.8 Defect Register

Date: 2026-08-13

Status: active; architecture and checkpoint-scope findings are corrected; the
three managed PostgreSQL High defects are locally remediated; managed evidence
gaps still block completion of this audit surface

This register records defects proved by the Milestone 7.8 audit and, in a
separate section, the evidence gaps the audit contract requires it to preserve.
A historical deferral, known limitation, warning, or missing validation is not
silently promoted to a defect. Remediation is mandatory only where the
governing repository contract says so; otherwise validation is required first
and remediation remains conditional on proof.

## Architecture and checkpoint-scope findings

| Identifier | Source                                                                                                              | Description                                                                                                                                   | Severity    | Affected surface                       | Classification                      | Mandatory in 7.8 | Disposition                         |
| ---------- | ------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- | ----------- | -------------------------------------- | ----------------------------------- | ---------------- | ----------------------------------- |
| M78-AS-001 | Current status blocks in the implementation plan, architecture, progress, and roadmap; retained 7.7 terminal chain  | Current governance documents still presented 7.7 as incomplete and 7.8 as unstarted after the terminal chain proved `MILESTONE_7_7_COMPLETE`. | Not defined | Architecture and checkpoint governance | Audit finding; documentation debt   | Yes              | Corrected by this audit surface     |
| M78-AS-002 | Implementation-plan execution rule and final-validation no-upstream requirement; inherited 7.7 branch configuration | The inherited 7.7 branch tracked a remote branch, so it could not satisfy the required no-upstream 7.8 checkpoint evidence boundary.          | Not defined | Local Git checkpoint boundary          | Audit finding; operational/Git debt | Yes              | Corrected with a fresh local branch |

No finding in this table claims that Milestone 7.7 was materially false or
unsafe. Both findings concern the safe entry boundary for new 7.8 work.

## Managed PostgreSQL and tenant-isolation findings

The second ordered audit surface inspected the declared architecture, Bicep
topology, runtime configuration, connection construction, SQLAlchemy engine
creation, database runtime gates, PostgreSQL bootstrap, migration runner,
Alembic environment and chain, recovery records, all 181 API operations, all
151 ORM tables, central authorization and sharing services, durable workers,
indexing, ingestion, graph retrieval, workflows, and the affected local test
suites. A source defect is listed only when current code contradicts an
authoritative repository requirement or permits a concrete unsafe path.

| Identifier | Exact requirement and source evidence                                                                                                                                                                                                                                 | Affected production path                                                                                        | Severity | Classification and disposition                                                                                                                                                                                                                                                                 | Changed files and validation                                                                                                                                                                                                              | Residual risk                                                                                                                                                    |
| ---------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- | -------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| M78-PG-001 | Architecture section 9.2 requires direct non-pooled migration/maintenance connections; `alembic/env.py` used `Database.from_settings`, which constructed `QueuePool` for every PostgreSQL role. This contradicted the Milestone 7.1 `NullPool` record.                | Alembic migration job and non-application role connections                                                      | Medium   | Proved defect; corrected so only API and worker roles pool and migration, backup, observability, and emergency roles use `NullPool`.                                                                                                                                                           | `apps/api/opencanvas_api/db/session.py`; `apps/api/tests/test_database_runtime.py`. Direct-pool regression passes; affected database/migration group passes 138 tests.                                                                    | No known local residual for pool selection; managed execution under the corrected code remains part of M78-PG-E03.                                               |
| M78-PG-002 | The implementation plan requires API/worker DML only on required tables. The original Bicep bootstrap and `scripts/bootstrap_postgres.py` gave both principals identical CRUD on all tables, sequence write, all-function execution, and matching default privileges. | Every API and worker SQL path, including auth, collaboration, ingestion, indexing, jobs, and workflows          | High     | Proved defect; locally resolved. API and worker now consume distinct literal per-operation matrices; neither receives sequence or function privileges; current/default blanket grants and unsafe `PUBLIC` execution are revoked.                                                               | `db/role_privileges.py`, split bootstrap/migration scripts, compute/identity/registry Bicep, and focused contract tests. Local emitted-grant and prohibited-grant assertions pass; managed catalog/negative execution remains M78-PG-E02. | Effective deployed ownership, inheritance, and positive/negative managed-identity execution remain unproved until the managed campaign.                          |
| M78-PG-003 | Architecture sections 5 and 9.2-9.3 and `DEPLOYMENT.md` require a distinct least-privilege migration user. The original Bicep authenticated the job as the configured Entra administrator and combined principal provisioning, grants, and Alembic.                   | One-shot migration/bootstrap job and all schema/extension ownership                                             | High     | Proved defect; locally resolved. `id-mobius77-db-admin` is confined to a provisioning-only job; `id-mobius77-db-migration` alone runs the guarded migration/grant job and owns the application schema objects.                                                                                 | Identity, registry, compute, owner-bootstrap, main Bicep; `bootstrap_postgres.py`; `migrate_and_grant.py`; config and contract tests. NullPool, role exclusion, ordering, sole-head, and local migration-cycle checks pass.               | Actual Entra principal creation, ownership transfer, job ordering, and negative role behavior require the bounded managed campaign.                              |
| M78-PG-004 | Architecture section 9.4 requires every mutation to resolve ambiguous commits by durable idempotency key/digest. Canvas, node, duplicate-node, and edge creation originally accepted neither and created server-random UUIDs.                                         | Legacy create operations during disconnect, restart, DNS change, or zone failover                               | High     | Proved defect; locally resolved with required keys and one expansion migration. Database uniqueness serializes actor/operation/key claims; scope/digest/result identity and the domain object commit atomically; replay reauthorizes and returns the original identity; conflicts fail closed. | `20260726_0029`, ORM/service/schema/routes, first-party retrying client, and API/web tests. First, replay, conflict, concurrency, rollback, client replacement, forged workspace, and all four path cases pass locally.                   | PostgreSQL concurrency/failover behavior remains to be executed through managed identities; SQLite migration and API proofs do not substitute for that campaign. |
| M78-TI-001 | The implementation plan requires server-derived scope and stale-authority denial. Retrieval replay/read/bundle paths and workflow creator-owned read/mutation helpers trusted durable creator/scope columns without checking current workspace/member authority.      | Graph retrieval replay/readback, evidence bundles, workflow execution readback, and definition/version mutation | High     | Proved defect; corrected with current owner/workspace checks and centralized `workflow.view`/`workflow.edit` authorization.                                                                                                                                                                    | Graph/workflow services and their two test files. Three exact new regression nodes pass; the affected graph/workflow group is included in 108 passing tests.                                                                              | Local stale-workspace paths are closed; managed pool/revocation/failover isolation remains M78-TI-E01.                                                           |

All five proved defects on this surface now have coherent local corrections.
The managed-evidence gaps still prevent this audit surface and Milestone 7.8
from satisfying their completion rules.

## Authorized High-defect remediation plan

Disposition recorded before production implementation on 2026-08-13:

- **M78-PG-002 — correct locally.** Replace both blanket-grant emitters with
  one literal role matrix. The API role receives `SELECT` only on the 149
  current tables referenced by API routes/services plus the authorized 0029
  request-identity table; `INSERT` excludes the worker-only heartbeat table;
  `UPDATE` is limited to `ai_requests`, `ai_responses`, `canonical_objects`,
  `canvases`, `controlled_agent_executions`,
  `controlled_workflow_executions`,
  `controlled_workflow_step_executions`, `document_processing_jobs`,
  `document_versions`, `documents`, `domain_event_outbox`, `nodes`, `users`,
  `user_sessions`, `workspace_authority_versions`, `workspace_event_sequences`,
  and `workspaces`; and `DELETE` is limited to `ai_response_sources`,
  `canonical_objects`, `canonical_relationships`, `canvases`, `citations`,
  `document_chunks`, `documents`, `edges`, and `nodes`. The API receives no
  access to migration-only `application_errors` or
  `index_compatibility_projections`. The worker receives reads only for the
  document-processing, durable-job, scanner/reconciliation, current-authority,
  event/outbox, trace, and heartbeat tables reached from `scripts.worker`;
  writes are restricted to the exact job attempt/outcome/retry/audit, document
  chunk/embedding/state, scanner result/promotion/audit, event/outbox, trace,
  and heartbeat paths. Neither runtime role receives sequence or function
  privileges. Current and default `PUBLIC` function execution is revoked;
  default table/sequence/function privileges grant nothing to either runtime
  role. Literal table names, concrete source evidence, generated SQL, and
  prohibited SQL will be contract-tested.
- **M78-PG-003 — correct locally.** Add `id-mobius77-db-migration` as a distinct
  user-assigned identity. A provisioning-only job attached to
  `id-mobius77-db-admin` creates and verifies the migration/API/worker Entra
  principals, transfers the existing `public` schema objects to the migration
  principal, grants only database/schema DDL needed by Alembic, and proves no
  dangerous flags or runtime-to-migration membership. The migration job is
  attached only to the migration identity, preserves the direct `NullPool`,
  guarded sole-head/expected-revision/advisory-lock runner, and applies the
  literal runtime matrix after migration. No administrator identity or token
  enters the migration, API, or worker container.
- **M78-PG-004 — correct locally with exactly one migration 0029.** The existing
  durable identity tables are bound to collaboration, ingestion, graph,
  workflow, agent, queue, or object-lifecycle operation/result constraints;
  reusing any would require widening an unrelated domain and still would not
  provide a canvas result/scope contract. Create one expansion-only
  `legacy_creation_request_identities` table in direct child revision
  `20260726_0029`. A unique actor/operation/key constraint is the PostgreSQL
  concurrency authority. Each record stores authoritative workspace/canvas
  scope, a canonical payload digest, result kind/id, and an append-only
  creation time. Claim and domain-object creation share one transaction;
  rollback removes both, committed replay returns the stored identity after
  current authority is revalidated, conflicting payload/scope reuse fails
  closed, and deleted results remain non-recreatable. Retention is indefinite
  while the referenced actor/workspace exists; no TTL silently invalidates a
  legitimate retry. The required key is added to all four legacy create
  contracts and their first-party callers.

The legacy creation inventory is exactly `POST /canvases`,
`POST /canvases/{canvas_id}/nodes`,
`POST /canvases/{canvas_id}/nodes/{node_id}/duplicate`, and
`POST /canvases/{canvas_id}/edges`. The first-party web client invokes those
four methods directly; tests and callers may replay after a transport-ambiguous
response, while no repository code currently provides a durable replay key.
Document upload, AI response-node creation, demo seeding, and controlled-agent
reversible writes use different established operation contracts and are not
the four proved legacy counterexamples.

## Authorized High-defect remediation result

The planned disposition above was implemented without Azure or a live
database. The complete changed production surface is:

- runtime privilege authority: `apps/api/opencanvas_api/db/role_privileges.py`,
  `apps/api/scripts/bootstrap_postgres.py`, and
  `apps/api/scripts/migrate_and_grant.py`;
- identity/job topology: `infra/milestone_7_7/main.bicep` and the `compute`,
  `identities`, `owner-bootstrap`, and `registry` modules;
- durable creation identity: migration `20260726_0029`, ORM model, service,
  API schemas/routes, and the web contracts/client/callers;
- current-head, infrastructure, role/grant, API idempotency, and affected
  caller tests plus `scripts/validate_migrations.py`.

The privilege matrix is literal and fail-closed. It covers every ORM table
reached from API routes/services except the migration-only
`application_errors` and `index_compatibility_projections`. Worker privileges
are the strict subset traced from `scripts/worker.py` through document
processing, durable jobs, authority fences, scanner/object reconciliation,
domain events, trace, and heartbeat paths. API and worker have distinct
`SELECT`/`INSERT`/`UPDATE`/`DELETE` sets. Neither receives sequence access or
function execution. Reconciliation revokes current blanket table, sequence,
and function privileges before applying the exact grants, revokes schema
creation and migration-role membership, revokes unsafe `PUBLIC` function
execution, and gives future objects no implicit runtime or `PUBLIC` privilege.

The migration lifecycle is now two-stage: the administrator-attached,
provisioning-only job deterministically creates the three Entra database
principals, rejects dangerous role flags, assigns the migration principal only
`CONNECT`/database `CREATE` and `USAGE`/schema `CREATE`, makes it the `public`
schema owner, and transfers existing application object ownership. The normal
migration job is attached only to `id-mobius77-db-migration`; it retains direct
`NullPool`, exact revision checks, the existing advisory lock and ordering, and
then reconciles runtime grants. API and worker identities cannot inherit or
assume the migration principal. The migration identity receives only ACR pull
outside PostgreSQL; no Azure-administration role was added.

Revision `20260726_0029` directly descends from `20260726_0028` and creates
only `legacy_creation_request_identities`, its two scope indexes, actor index,
unique actor/operation/key authority, constraints, and append-only guards.
There is no `0030`; `0029` is the sole head. The downgrade refuses to discard
nonempty durable identity state. Local upgrade/downgrade/re-upgrade validation
passed. Historical Milestone 7.7 records and hashes still truthfully describe
their earlier state in which `0029` did not exist and were not rewritten.

Focused local validation passed: 19 canvas/document/idempotency tests; seven
role/identity/grant contracts; 12 general migration tests; migration validator
upgrade/downgrade/re-upgrade; 10 auth/AI/collaboration tests; 78 graph/agent
tests; strict mypy over eight affected production files; affected Ruff checks;
web TypeScript, ESLint, and 75 unit tests. The infrastructure contract suite is
not all green at remediation commit `ce4543bc`: it was 93 passed / 1 failed. The corrected
`test_post_secret_migration_output_uses_explicit_subscription_scope` directly
overlapped that work. The remaining
`test_tracked_contract_text_has_no_private_arm_id_guid_or_user_path` failure is
the inherited private retained-authorization UUID embedded in
`observability_operator_bootstrap_adapter.py`. A later, separately authorized
local governance correction removed that identifier-specific check. The exact
historical authorization remains bound by its fixed authorization and receipt
integrity hashes, while the receipt field is validated semantically as a UUID;
all other source-head, execution, timestamp, URL, terminal-status, and live
readback checks remain fail closed. The exact node and full 94-node
infrastructure suite now pass. The same correction replaced the historical
audit handoff's workstation-specific receipt path with a repository-local
evidence link; repository hygiene now passes. No managed evidence gap was
closed. A local Bicep executable was not installed, so Bicep compilation was
not claimed and no tool was downloaded.

## Managed PostgreSQL and tenant-isolation evidence gaps

An evidence gap is not silently labeled as a passing control or an
implementation defect. These gaps are nevertheless blockers because this
audit surface expressly requires the associated production-readiness proof.

| Identifier | Evidence inspected and exact missing proof                                                                                                                                                                                                                                                                                                                                       | Affected production path                                                     | Severity / classification             | Validation and smallest authorized rerun                                                                                                                                                                                           | Residual risk                                                                                                           |
| ---------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------- | ------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| M78-PG-E01 | Pool defaults, replica ceilings, init gates, job shape, and retained receipts prove 40 API + 40 worker + 1 migration + 8 rollout gates = a concrete 89-connection scenario. The deployed `max_connections`, old/new revision overlap, backup/observability/emergency allocations, and operator reserve are absent, so the required budget inequality is unproved.                | Scale-out, rollout, pool exhaustion, migration, and operator access          | High; unproved claim / evidence gap   | Local pool/topology tests pass. Separately record `SHOW max_connections`, per-role activity at ceilings, overlap, every non-application allocation, and explicit reserve; pass only when the full sum is below capacity.           | Connection exhaustion can make readiness and work fail despite individually bounded pools.                              |
| M78-PG-E02 | Bicep, bootstrap SQL, runtime flags, and a migration receipt do not inventory effective table/sequence/function/database/schema/PUBLIC/ownership privileges or run negative DDL/cross-role DML tests. Backup, observability, and emergency have no deployed principals/grants.                                                                                                   | Every managed database role                                                  | High; unproved claim / evidence gap   | Local role-flag tests pass. After M78-PG-002/003, inventory catalogs and execute positive/negative tests through every exact managed identity without exposing credentials.                                                        | Undocumented ownership, inheritance, PUBLIC grants, or missing operator identities can defeat least privilege/recovery. |
| M78-PG-E03 | Milestone 7.6 proves isolated restore paths; retained 7.7 proves migration/readiness and uninterrupted health. Neither induces failover/disconnect, preserves traffic across recovery, resolves an ambiguous commit, nor proves token expiration/revocation and stale pooled-connection handling.                                                                                | API/worker pools, readiness, managed-identity rotation, worker claims, retry | High; unproved claim / evidence gap   | Local pre-ping/timeout/readiness/idempotency tests pass. After M78-PG-004, induce one bounded failover and credential-rotation case; prove degradation, pool recovery, durable request resolution, and zero duplicate effects.     | Provider failover or revoked/stale authentication may produce unknown outcomes or prolonged unready state.              |
| M78-TI-E01 | Central authority, 167 composite FKs, local cross-scope/revocation tests, and managed health are insufficient: no managed campaign combines cross-user/workspace/canvas/resource reads/writes, stale membership, worker/indexer paths, pool reuse, retry, and failover.                                                                                                          | All protected API and background database paths                              | High; unproved claim / evidence gap   | Local collaboration and data-path groups pass 24 + 108 tests. In an approved isolated campaign use two users/workspaces, revoke membership, force pool reuse/failover, and require zero cross-scope results or mutations.          | Managed-driver, PostgreSQL, pooled-transaction, or background-path behavior could differ from local SQLite proofs.      |
| M78-PG-E04 | Bicep and retained topology prove PostgreSQL 17, pgvector, `centralus`, cross-region private peering to `southcentralus` compute, Entra-only auth, seven-day retention, ZoneRedundant HA, 64-GiB P6 storage, and disabled geo backup/autogrow. Exact assigned zones, maintenance window, connection ceiling, storage-growth rationale, and production capacity claim are absent. | Maintenance/restart, storage exhaustion, regional latency, backup durability | Medium; unproved claim / evidence gap | Focused PostgreSQL/runtime topology contracts pass; the handoff records the separate mixed infrastructure-suite result. Record the approved managed configuration and capacity rationale; no topology mutation is authorized here. | Maintenance timing, storage ceiling, exact zone behavior, and capacity remain operational unknowns.                     |

## Proved compliant controls on this surface

- The Bicep topology is a single authoritative PostgreSQL 17 Flexible Server
  with ZoneRedundant high availability, private access, public access disabled,
  Entra authentication enabled, password authentication disabled, pgvector
  allowlisted, and no application replica-read path.
- Deployed connection URLs contain a principal name but no stored password;
  short-lived managed-identity tokens are supplied at connect time. TLS
  `verify-full`, `READ COMMITTED`, connection/statement/lock/idle/acquisition
  timeouts, pool pre-ping, and safe dependency errors are explicit.
- API and worker each have a separate identity, application name, and bounded
  `10 + 0` pool per replica. The declared maximum is four replicas per service.
  Health checks reuse the service database object rather than adding another
  independent pool.
- Startup never applies migrations. The provisioning and migration jobs are
  manual, single parallel, zero-retry, and bounded. The migration runner
  verifies the expected current/target revision, sole repository head,
  PostgreSQL advisory lock, and final revision; authorized
  `20260726_0029` is now the sole head and `0030` remains absent.
- Liveness remains independent of a transient database outage, readiness fails
  closed, deployment init gates wait for the exact revision and runtime role,
  and runtime diagnostics do not expose connection details.
- The schema contains 151 ORM tables; 120 carry `workspace_id`, 54 carry
  `canvas_id`, and 167 composite foreign keys bind typed parents. The four
  canvas-scoped tables without direct `workspace_id` are constrained through
  their canvas/document/node parent chains. Current authorization is derived
  from the server principal and centralized membership authority; ingestion,
  indexing, durable jobs, workflows, agents, and object publication carry
  workspace scope and revocation fences.
- PostgreSQL row-level security remains out of scope by the deliberate
  architecture decision. It is neither required nor claimed as a passing
  control.

## Located Milestone 7.7 records that are not active defects

| Source                                                    | Exact record                                                                                                                                                                                                           | Evidence classification       | Mandatory remediation in 7.8 |
| --------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------- | ---------------------------- |
| `preflight/milestone_7_7/scope-contract.json`             | `azure-topology-preflight-execution`, `checkpoint-7`, `deployment`, `failure-injection`, `milestone-7.8`, `provisioning`, `runtime-validation`, `workload-execution`                                                   | Historical scope deferral     | No                           |
| `preflight/milestone_7_7/operation-contracts.json`        | `separately-authorized-read-only-azure-observation`, `isolated-infrastructure-provisioning`, `runtime-gate-validation`, `managed-workload-and-failure-execution`, `milestone-7.7-final-consolidation`, `milestone-7.8` | Historical operation deferral | No                           |
| `docs/MILESTONE_7_7_REMAINING_LIFECYCLE_COMPATIBILITY.md` | Seven grouped defects in image-source identity, post-secret authority, scanner arguments, mutation attribution, stage separation, terminal producers/consumers, and simulator behavior                                 | Closed defect inventory       | No; already corrected        |
| Retained nine-stage terminal lifecycle evidence           | Complete predecessor chain through soak, closeout, cleanup, zero-residue verification, and `MILESTONE_7_7_COMPLETE` at `b191a392922f94557e6ebf5914113b5e229ab00e`                                                      | Durable completion evidence   | No                           |

The two JSON `deferredWork` arrays are immutable historical scope records.
They do not prove that every named item is a defect, and the validated terminal
chain supersedes their pre-completion 7.7 execution status without rewriting
them.

## Evidence debts routed to later audit surfaces

These items are exact persisted debts or limitations. They are not yet proved
implementation defects, so this first audit surface does not fix them.

| Identifier | Source                                            | Description                                                                                                  | Classification                                      | 7.8 contract consequence                                                                                                     |
| ---------- | ------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ | --------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| M78-D-001  | `docs/KNOWN_LIMITATIONS.md`                       | File unlink and relational commit are not atomic; staged trash/outbox cleanup is deferred.                   | Architectural, reliability, and operational debt    | The object lifecycle and failed-transaction audit must validate it; remediation is conditional on a proved defect.           |
| M78-D-002  | `docs/KNOWN_LIMITATIONS.md`                       | The shared-rate-limit adapter lacks recorded end-to-end revalidation against approved isolated Azure Redis.  | Validation, reliability, and operational debt       | The shared-limit audit and final atomic-across-replicas scenario are mandatory; remediation is conditional on failure.       |
| M78-D-003  | `docs/KNOWN_LIMITATIONS.md`; `docs/DEPLOYMENT.md` | Full live telemetry destination, dashboards, alerts, retention, access, and revocation validation is absent. | Validation, operational, privacy, and security debt | The observability audit is mandatory; retained evidence must be assessed before any separately authorized Azure mutation.    |
| M78-D-004  | `docs/KNOWN_LIMITATIONS.md`                       | Production queue wake-up, operational telemetry, and external multi-service delivery require validation.     | Validation, reliability, and operational debt       | The durable-work audit is mandatory; remediation is conditional on a proved contract failure.                                |
| M78-D-005  | `docs/KNOWN_LIMITATIONS.md`                       | Backup/restore/rollback lacks validation against a managed production deployment.                            | Recovery and validation debt                        | The managed recovery scenario must be audited against retained evidence; production deployment remains excluded.             |
| M78-D-006  | `docs/KNOWN_LIMITATIONS.md`                       | No load/performance benchmarks or capacity claims are published.                                             | Capacity and documentation debt                     | The capacity audit and final documentation must record supported evidence and limitations; no unsupported claim is allowed.  |
| M78-D-007  | `docs/MILESTONE_7_ARCHITECTURE.md`                | Stage 3 category-log rows had not arrived before cleanup.                                                    | Observability validation debt                       | The observability/evidence audit must decide whether later retained evidence closes or preserves this limitation.            |
| M78-D-008  | `docs/MILESTONE_7_ARCHITECTURE.md`                | Exact Stage 3 posted cost was unavailable because of throttling and delayed usage posting.                   | Operational and cost-evidence debt                  | Final results must record the proved cost boundary and any exact-cost limitation; remediation is not automatically required. |

This routing authorizes no Azure operation, migration, image build,
publication, scanner execution, secret access, or Git remote operation.
