# Milestone 7.8 Managed PostgreSQL High-Defect Remediation Handoff

Date: 2026-08-13

Status: local remediation complete; managed PostgreSQL evidence remains open

This is a focused, unnumbered Milestone 7.8 remediation record. It does not
reopen Milestone 7.7, complete the managed database audit, begin the object
storage audit, or complete Milestone 7.8.

## Authoritative boundary

- Starting branch: `milestone-7-8-production-readiness-audit-local`
- Starting HEAD: `b1e3d7294f74152eac784e74b7e93cbe4dbae73b`
- Starting upstream: absent
- Starting tree/index: clean
- Protected stashes: exactly five, untouched
- Historical database-audit result:
  `MILESTONE_7_8_DATABASE_SURFACE_AUDIT_BLOCKED`
- Retained Milestone 7.7 evidence was immutable: nine linked stages, 91
  samples, 5,400 uninterrupted seconds, and all ten residue counters at zero.

The audit handoff remains historical evidence. This later authorized change
introduces revision `20260726_0029`; its statement that `0029` was absent was
correct at the historical audit boundary and was not rewritten.

## Defect dispositions

| Defect       | Local disposition                                                                                                                                                                  | Remaining proof                                                                                                                   |
| ------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| `M78-PG-002` | Resolved in repository state with independently defined API and worker grants, no runtime sequence/function access, no blanket grants, and fail-closed current/default revocation. | Effective managed catalogs and positive/negative execution through each deployed identity.                                        |
| `M78-PG-003` | Resolved in repository state with an administrator-only provisioning job and migration-only Alembic/grant job attached to `id-mobius77-db-migration`.                              | Entra principal creation, ownership transfer, execution ordering, and negative role behavior in the isolated managed environment. |
| `M78-PG-004` | Resolved in repository state with required durable keys on four legacy endpoints and transactionally atomic request/result identity in migration `0029`.                           | PostgreSQL concurrency and ambiguous-response replay across an induced managed failover.                                          |

## Privilege matrix

The executable source of truth is
`apps/api/opencanvas_api/db/role_privileges.py`. Every table is literal; a new
migration cannot silently widen either role.

| Role   | SELECT | INSERT | UPDATE | DELETE | Sequences | Functions |
| ------ | -----: | -----: | -----: | -----: | --------: | --------: |
| API    |    150 |    149 |     17 |      9 |         0 |         0 |
| Worker |     55 |     18 |      6 |      1 |         0 |         0 |

API `SELECT` covers the 149 preexisting route/service tables plus
`legacy_creation_request_identities`; it excludes migration-only
`application_errors` and `index_compatibility_projections`. API `INSERT` is
the same set except `worker_heartbeats`. API `UPDATE` is limited to:
`ai_requests`, `ai_responses`, `canonical_objects`, `canvases`,
`controlled_agent_executions`, `controlled_workflow_executions`,
`controlled_workflow_step_executions`, `document_processing_jobs`,
`document_versions`, `documents`, `domain_event_outbox`, `nodes`,
`user_sessions`, `users`, `workspace_authority_versions`,
`workspace_event_sequences`, and `workspaces`. API `DELETE` is limited to:
`ai_response_sources`, `canonical_objects`, `canonical_relationships`,
`canvases`, `citations`, `document_chunks`, `documents`, `edges`, and `nodes`.

Worker `SELECT` is limited to the 55 document-processing, durable-job,
authority-fence, scanner/object-reconciliation, domain-event, trace, and
heartbeat tables reached from `scripts/worker.py`. Worker `INSERT` is limited
to `document_chunks`, `document_embeddings`, `domain_event_outbox`,
`domain_event_provenance`, `domain_events`, `durable_job_attempts`,
`durable_job_audit_events`, `durable_job_dead_letters`,
`durable_job_outcomes`, `durable_queue_deliveries`,
`durable_retry_decisions`, `malware_scan_results`,
`object_ingestion_audit_events`, `object_promotions`,
`storage_object_lifecycle_transitions`, `trace_events`, `worker_heartbeats`,
and `workspace_event_sequences`. Worker `UPDATE` is limited to
`document_processing_jobs`, `document_versions`, `documents`,
`domain_event_outbox`, `worker_heartbeats`, and `workspace_event_sequences`.
Worker `DELETE` is limited to `document_chunks`.

Reconciliation first removes current database/schema/table/sequence/function
privileges, schema creation, and migration-role membership from API/worker,
then emits only the matrix grants. `PUBLIC` schema creation and function
execution are revoked. Migration-owner default privileges grant no tables,
sequences, or functions to API, worker, or `PUBLIC`. Runtime roles have no
role-creation, database-creation, superuser, replication, bypass-RLS, DDL,
ownership, grant, or migration-role authority.

## Role, ownership, and migration lifecycle

`id-mobius77-db-admin` is attached only to the manual principal-bootstrap job.
That job validates exact principal names/object IDs, creates missing Entra
database principals repeatably, rejects dangerous role flags, grants the
migration role only database `CONNECT`/`CREATE` and public-schema
`USAGE`/`CREATE`, assigns the migration role as schema owner, transfers existing
public relations/sequences/functions, and gives API/worker only database
`CONNECT` and schema `USAGE`.

`id-mobius77-db-migration` is attached only to the manual migration job and
receives ACR pull as its only Azure role in this topology. It cannot administer
Azure resources or create database roles. The migration job validates its
current database identity and non-dangerous flags, preserves `NullPool`,
checks the exact starting/final revision and sole repository head, uses the
existing PostgreSQL advisory lock, runs Alembic, verifies ownership, applies
the runtime matrix, and rejects API/worker migration-role membership. The
administrator identity/client ID is absent from this job and all API/worker
containers.

Operational order is fail-closed: deploy definitions, manually run and verify
the principal-bootstrap job, then manually run and verify the migration job,
then admit API/worker revision gates. A failed stage prevents the next stage;
jobs have one replica, zero retries, and bounded timeouts.

## Durable idempotency and transaction semantics

The affected inventory is exactly:

1. `POST /canvases`
2. `POST /canvases/{canvas_id}/nodes`
3. `POST /canvases/{canvas_id}/nodes/{node_id}/duplicate`
4. `POST /canvases/{canvas_id}/edges`

Every body now requires an 8-128 character `idempotencyKey`. The canonical
SHA-256 request digest excludes the key and includes the path-scoped canvas or
source-node identity. The database unique constraint on actor user, operation,
and key is the concurrent-claim authority. Each row records authoritative
workspace/canvas scope, digest, result kind/id, and creation time. The claim
and explicit-ID domain insert share one transaction. Rollback removes both;
commit preserves both across process/pool/worker restart and failover.

A completed replay validates digest and requested scope, re-evaluates current
workspace/canvas authority, loads only the stored scoped result, and returns
the same 201-compatible resource response. Different payload/scope reuse is a
generic 409. Deleted results return a generic unavailable conflict and cannot
be recreated with the same key. Error/log paths do not emit payloads or stored
resource identifiers. Records have no TTL and remain while their actor and
workspace exist, so retention cannot silently invalidate a legitimate retry.
The web client uses the required key and automatically retries one
transport-ambiguous create with the identical serialized request.

## Migration decision

No existing durable table could satisfy the four operations without widening
another domain's operation/result constraints. Exactly one authorized
migration was therefore created:

- revision: `20260726_0029`
- parent: `20260726_0028`
- active Git blob hash: `948282d7e6a3e0432dca814f79496c5cdf177359`
- upgrade: one expansion-only table, three indexes, three checks, two foreign
  keys, one uniqueness constraint, and database append-only guards
- downgrade: refuses when durable rows exist; otherwise removes only those
  guards and the new table
- sole head: `20260726_0029`; `0030` is absent

SQLite upgrade/downgrade/re-upgrade and deterministic hash validation pass.
No destructive rewrite or historical hash edit occurred.

## Evidence-gap dispositions

| Gap                                   | Locally proved                                                                                                                                                           | Still open                                                                                                                        |
| ------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------- |
| Managed role grants                   | Literal grants/revocations, principal split, dangerous-flag and membership checks, ownership expectations, and contract tests.                                           | Effective managed catalogs plus positive/negative execution through each identity.                                                |
| Connection capacity/reserve           | API and worker remain bounded at 10+0 per replica, four replicas each; migration and gates remain direct/bounded.                                                        | Deployed `max_connections`, rollout overlap, backup/observability/emergency allocations, and approved operator reserve.           |
| Failover/credential rotation          | Pool pre-ping, bounded timeouts, fail-closed readiness, direct migration pool, and durable replay logic/tests.                                                           | Provider failover, token expiry/revocation, stale pooled connection recovery, worker claims, and zero duplicates under the event. |
| Tenant isolation under reuse/failover | Server-derived authority, scoped identity rows, reauthorization on replay, forged-workspace tests, and existing collaboration/graph/worker fences.                       | Two-tenant managed pool reuse, revocation, retry, worker/indexer, and failover execution.                                         |
| Maintenance/storage/zones             | Declared PostgreSQL 17, ZoneRedundant HA, private/Entra-only access, seven-day retention, 64-GiB P6 storage, and disabled geo backup/autogrow remain locally verifiable. | Assigned zones, maintenance window, deployed capacity, storage-growth rationale, and production latency/capacity evidence.        |

No gap is marked closed by documentation or SQLite evidence.

## Bounded managed-evidence campaign

This plan is executable only after separate user authorization. Prerequisites:
an isolated approved resource group running the exact committed artifact, the
defined admin/migration/API/worker identities, synthetic tenant data only, a
user-approved dollar ceiling, and a cleanup authorization. Fail closed if the
commit, image digest, resource group, cost ceiling, or identities differ.

Use an operator with only resource read, Container Apps job execution/read,
PostgreSQL configuration/metric read, and log-evidence write access. The admin
identity is used only by the bootstrap job; migration only by the migration
job; API and worker tests execute as their own identities. Failover, credential
rotation, scaling, image publication, environment creation, and cleanup each
require explicit later authorization.

From the repository root, after setting non-secret resource names in the
current shell, execute these bounded stages (never print tokens or connection
strings):

```powershell
$campaign = "m78-pg-managed-$(Get-Date -Format yyyyMMdd-HHmmss)"
$evidence = Join-Path $PWD "evidence/$campaign"
New-Item -ItemType Directory -Path $evidence | Out-Null
git rev-parse HEAD | Set-Content "$evidence/commit.txt"
az containerapp job start --subscription $subscription --resource-group $resourceGroup --name $principalBootstrapJob --output none
az containerapp job execution list --subscription $subscription --resource-group $resourceGroup --name $principalBootstrapJob --query "[0].{name:name,status:properties.status,start:properties.startTime,end:properties.endTime}" -o json | Set-Content "$evidence/principal-bootstrap.json"
az containerapp job start --subscription $subscription --resource-group $resourceGroup --name $migrationJob --output none
az containerapp job execution list --subscription $subscription --resource-group $resourceGroup --name $migrationJob --query "[0].{name:name,status:properties.status,start:properties.startTime,end:properties.endTime}" -o json | Set-Content "$evidence/migration.json"
az postgres flexible-server parameter show --subscription $subscription --resource-group $resourceGroup --server-name $postgresServer --name max_connections -o json | Set-Content "$evidence/max-connections.json"
az postgres flexible-server show --subscription $subscription --resource-group $resourceGroup --name $postgresServer --query "{version:version,ha:highAvailability,storage:storage,backup:backup,maintenanceWindow:maintenanceWindow,zone:availabilityZone}" -o json | Set-Content "$evidence/postgres-configuration.json"
```

Then run repository-approved evidence containers as migration, API, and worker
identities. The migration-identity probe records catalog ownership, role flags,
memberships, database/schema/default/`PUBLIC` privileges, and per-object ACLs.
API/worker probes execute every matrix-positive operation inside synthetic
rollback-only transactions and require denial of schema/database DDL, role
creation/grant, migration-role assumption, all omitted table operations, every
sequence privilege, and direct function execution. Any unexpected allow or
required-operation denial stops the campaign.

At declared replica ceilings, record `pg_stat_activity` per identity during
steady state and one old/new rollout overlap. Assert:

```text
api + worker + rollout overlap + migration/gates + backup + observability +
emergency/operator reserve < deployed max_connections
```

The campaign fails if any term is absent or the inequality is not strictly
true. Do not infer unobserved allocations as zero.

Create two synthetic users/workspaces/canvases and unique foreign identifiers.
Exercise the four durable creations, protected reads/writes, ingestion,
indexer/worker completion, membership revocation, repeated pool reuse, and
same-key conflict cases. With the first response deliberately withheld, induce
exactly one approved managed failover, retry the same keys, and require the
original IDs with one row/object per operation. Perform exactly one approved
managed-identity credential/token revocation or rotation case; require
readiness degradation, bounded recovery, new authenticated connections, no
cross-scope result, no duplicate effect, and no stale worker claim.

Artifacts are the exact commit/image/config identity, redacted job execution
receipts, catalog/ACL JSON, positive/negative result matrix, connection-budget
worksheet and activity snapshots, failover/rotation timestamps, readiness and
worker traces, tenant-isolation assertions, duplicate-count queries, cost
receipt, and cleanup receipt. No payload, token, secret, or connection string
may enter an artifact.

Hard bounds: one isolated environment, declared 4 API + 4 worker replica
ceilings, one rollout overlap, one failover, one rotation case, synthetic data
only, and four elapsed hours. The dollar ceiling is deliberately not invented:
the campaign cannot start until the user supplies and authorizes it. On any
assertion failure, stop mutation, retain redacted evidence, and do not claim
the gap closed. Cleanup deletes only campaign-created synthetic data/resources
after separate authorization and verifies zero residue; otherwise leave them
intact and report the exact owner/cost state.

## Validation record

Commands below are repository-relative PowerShell commands. API pytest
commands were run from `apps/api`; web commands were run from `apps/web`. The
two prior broad categories were replaced by bounded shards; the inherited
904-second monolithic command was not repeated.

| Exact command                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          | Exit/result                                                                                                                                                                      |
| -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `$py = @(git diff --name-only b1e3d7294f74152eac784e74b7e93cbe4dbae73b HEAD -- '*.py'); .\.venv\Scripts\ruff.exe check --ignore I001 -- $py`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           | exit 0; 31 files; only inherited import-order checks were excluded                                                                                                               |
| `$strictPy = @($py \| Where-Object { $_ -notin @('apps/api/tests/test_agent_studio_migration.py','apps/api/tests/test_collaboration_6_2_migration.py','apps/api/tests/test_collaboration_6_3_migration.py','apps/api/tests/test_collaboration_6_4_migration.py','apps/api/tests/test_collaboration_migration.py','apps/api/tests/test_migration.py','apps/api/tests/test_milestone_7_7_observability_operator_bootstrap.py','apps/api/tests/test_milestone_7_7_runtime_topology.py','apps/api/tests/test_shared_governance_migration.py','apps/api/tests/test_workflow_migration.py') }); .\.venv\Scripts\ruff.exe check -- $strictPy` | exit 0; 21 remediation Python files under the full configured rule set; the excluded files retain preexisting import layout                                                      |
| `$py = @(git diff --name-only b1e3d7294f74152eac784e74b7e93cbe4dbae73b HEAD -- '*.py' \| Where-Object { $_ -notin @('scripts/validate_migrations.py','infra/milestone_7_7/observability_operator_bootstrap_adapter.py') }); .\.venv\Scripts\ruff.exe format --check -- $py`                                                                                                                                                                                                                                                                                                                                                            | exit 0; 29 files; the two retained-layout files were linted but not mechanically reformatted                                                                                     |
| `..\..\.venv\Scripts\mypy.exe --strict opencanvas_api/api/routes/canvases.py opencanvas_api/api/schemas.py opencanvas_api/core/config.py opencanvas_api/db/models.py opencanvas_api/db/role_privileges.py opencanvas_api/services/legacy_creation_idempotency.py scripts/bootstrap_postgres.py scripts/migrate_and_grant.py`                                                                                                                                                                                                                                                                                                           | exit 0; success on 8 production files                                                                                                                                            |
| `..\..\.venv\Scripts\python.exe -m pytest -q tests/test_legacy_creation_idempotency.py tests/test_canvas_api.py tests/test_document_api.py`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            | exit 0; 19 passed; 48.4 seconds                                                                                                                                                  |
| `..\..\.venv\Scripts\python.exe -m pytest -q tests/test_milestone_7_8_database_remediation.py`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         | exit 0; 7 passed                                                                                                                                                                 |
| `.\.venv\Scripts\python.exe scripts\validate_migrations.py`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            | exit 0; SQLite upgrade to 0029, downgrade to 0028, re-upgrade to 0029; deterministic hash passed                                                                                 |
| `..\..\.venv\Scripts\python.exe -m alembic -c alembic.ini heads`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       | exit 0; `20260726_0029 (head)`                                                                                                                                                   |
| `..\..\.venv\Scripts\python.exe -m pytest -q tests/test_migration.py`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  | exit 0; 12 passed; warnings only                                                                                                                                                 |
| `..\..\.venv\Scripts\python.exe -m pytest -q tests/test_database_runtime.py tests/test_migration_runner_postgres.py`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   | exit 0; 23 passed, 2 skipped because no PostgreSQL URL/fixture was available                                                                                                     |
| `..\..\.venv\Scripts\python.exe -m pytest -q tests/test_milestone_7_7_runtime_topology.py`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             | exit 0; 9 passed                                                                                                                                                                 |
| `..\..\.venv\Scripts\python.exe -m pytest -q tests/test_milestone_7_7_observability_operator_bootstrap.py`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             | exit 0; 38 passed                                                                                                                                                                |
| `..\..\.venv\Scripts\python.exe -m pytest -q tests/test_auth_authorization.py tests/test_collaboration_comments.py tests/test_collaboration_resources.py`                                                                                                                                                                                                                                                                                                                                                                                                                                                                              | exit 0; 10 passed                                                                                                                                                                |
| `..\..\.venv\Scripts\python.exe -m pytest -q tests/test_agent_reversible_effects.py tests/test_agent_studio_migration.py tests/test_collaboration_6_2_migration.py tests/test_collaboration_6_3_migration.py tests/test_collaboration_6_4_migration.py tests/test_collaboration_migration.py tests/test_knowledge_graph_foundation.py tests/test_shared_governance_migration.py tests/test_workflow_migration.py`                                                                                                                                                                                                                      | exit 0; 78 passed; 197.6 seconds                                                                                                                                                 |
| `$env:PYTHONDONTWRITEBYTECODE='1'; ..\..\.venv\Scripts\python.exe -m pytest -q tests/test_milestone_7_7_infrastructure_contracts.py`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   | exit 1; 93 passed, 1 inherited unrelated failure; no timeout                                                                                                                     |
| `.\node_modules\.bin\prettier.CMD --check src\components\open-canvas-app.tsx src\lib\api-client.ts src\lib\contracts.test.ts src\lib\contracts.ts`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     | exit 0                                                                                                                                                                           |
| `.\node_modules\.bin\tsc.CMD --noEmit`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 | exit 0                                                                                                                                                                           |
| `.\node_modules\.bin\eslint.CMD src\components\open-canvas-app.tsx src\lib\api-client.ts src\lib\contracts.test.ts src\lib\contracts.ts --max-warnings=0`                                                                                                                                                                                                                                                                                                                                                                                                                                                                              | exit 0                                                                                                                                                                           |
| `.\node_modules\.bin\vitest.CMD run`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   | exit 0; 17 files / 75 tests passed                                                                                                                                               |
| `.\node_modules\.bin\next.CMD build`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   | exit 0; generated `.next` residue removed afterward                                                                                                                              |
| `.\apps\web\node_modules\.bin\prettier.CMD --check docs\MILESTONE_7_8_DEFECT_REGISTER.md docs\MILESTONE_7_8_MANAGED_POSTGRESQL_HIGH_DEFECT_REMEDIATION_HANDOFF.md docs\DEPLOYMENT.md docs\MILESTONE_7_ARCHITECTURE.md`                                                                                                                                                                                                                                                                                                                                                                                                                 | exit 0                                                                                                                                                                           |
| `.\.venv\Scripts\python.exe scripts\check_repository_hygiene.py`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       | exit 1; only inherited Windows user-path text in the historical audit handoff; the historical record is outside this diff and remains assigned to the later governance surface   |
| `git diff --check`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     | exit 0                                                                                                                                                                           |
| `git fsck --no-dangling --no-reflogs`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  | exit 0                                                                                                                                                                           |
| local Bicep compilation                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                | not run; no Bicep executable was installed and downloads were prohibited                                                                                                         |
| PostgreSQL-marked/managed execution                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    | not run; no already-installed disposable PostgreSQL fixture and no managed access were available; the two PostgreSQL integration tests were reported as skipped, never as passed |

Elapsed time was not captured separately for commands whose rows do not state
it. No command timed out. A transient infrastructure-test run without
`PYTHONDONTWRITEBYTECODE` created two `__pycache__` directories and produced
spurious hygiene failures; those reproducible directories were removed, and
the final infrastructure result above was obtained with zero generated
residue.

The first inherited infrastructure failure, exact node
`test_post_secret_migration_output_uses_explicit_subscription_scope`, directly
overlapped the migration job output and is fixed. At remediation commit
`ce4543bc`, the remaining exact node was
`test_tracked_contract_text_has_no_private_arm_id_guid_or_user_path`; its
production surface was the unrelated retained observability operator bootstrap
adapter's embedded private authorization UUID. That gate and the historical
handoff path gate were subsequently cleared under separate, narrow local
governance authority as recorded below.

## Local governance gate correction

The adapter had redundantly embedded one retained authorization UUID even
though the exact historical authorization and complete prepared receipt were
already bound by fixed SHA-256 integrity values. The private literal was
removed. Historical adoption now requires a semantically valid authorization
UUID plus the unchanged exact authorization-integrity, receipt-integrity,
source-HEAD, execution, claim-time, private-URL, terminal-status, and live job
readback checks. A syntactically valid different authorization still changes
the receipt integrity and is rejected by the existing negative test.

The historical database audit handoff exposed the local workstation path from
which the retained receipts had been validated. That representation was
replaced with a repository-local link to the already recorded architecture and
scope evidence. Its historical findings, hashes, sample/duration counts, and
conclusions were not changed.

Focused results after correction:

| Exact repository-relative command                                                                                                                                                                                     | Result                             |
| --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------- |
| `cd apps/api; $env:PYTHONDONTWRITEBYTECODE='1'; ..\..\.venv\Scripts\python.exe -m pytest -q tests/test_milestone_7_7_infrastructure_contracts.py::test_tracked_contract_text_has_no_private_arm_id_guid_or_user_path` | exit 0; 1 passed                   |
| `.\.venv\Scripts\python.exe -m pytest -q apps/api/tests/test_milestone_7_7_infrastructure_contracts.py`                                                                                                               | exit 0; all 94 nodes passed        |
| `.\.venv\Scripts\python.exe -m pytest -q apps/api/tests/test_milestone_7_7_observability_operator_bootstrap.py`                                                                                                       | exit 0; 38 passed                  |
| `.\.venv\Scripts\python.exe scripts\check_repository_hygiene.py`                                                                                                                                                      | exit 0; 597 source files inspected |

The pre-correction reproduction used the exact recorded commands and produced
the expected 93-passed/1-failed infrastructure result and the single Windows
user-path hygiene finding. No canonical API container-image input was changed:
none of the governance correction files is in `API_IMAGE_BUILD_INPUTS`.

## Remaining blockers and next action

Managed catalog, capacity, failover/rotation, tenant isolation, and operational
configuration evidence remain absent. The database audit therefore remains
blocked from full completion and Milestone 7.8 remains incomplete. The object
storage audit is unstarted.

The next action is a separately authorized managed PostgreSQL evidence
campaign using the bounded plan above. It is not an object-storage audit, Git
push, or deployment implied by this handoff.
