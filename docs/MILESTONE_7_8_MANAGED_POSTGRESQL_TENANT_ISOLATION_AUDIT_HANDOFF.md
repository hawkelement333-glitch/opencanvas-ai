# Milestone 7.8 Managed PostgreSQL and Tenant-Isolation Audit Handoff

Date: 2026-08-13

Status: **BLOCKED**. The local audit and bounded corrections are complete, but
three unresolved High defects and four High managed-evidence gaps prevent the
Milestone 7.8 production-readiness completion rule from passing.

Terminal marker:

`MILESTONE_7_8_DATABASE_SURFACE_AUDIT_BLOCKED`

## Starting boundary

- branch: `milestone-7-8-production-readiness-audit-local`;
- entry HEAD: `621c414191843aedaa889b5802f2b4ada1b7c747`;
- entry parent: `b191a392922f94557e6ebf5914113b5e229ab00e`;
- required Milestone 7.7 completion ancestor:
  `b191a392922f94557e6ebf5914113b5e229ab00e`;
- upstream: none;
- starting index and worktree: clean;
- protected stashes: exactly five, unchanged;
- sole Alembic head: `20260726_0028`;
- migration `0029`: absent;
- canonical image-input SHA-256:
  `5f1a5b71c45e7b9183ed09205a5bd815b120e3c278026c4238c05834684b4c81`.

The retained Milestone 7.7 receipts recorded by the repository-local
[architecture and scope audit](MILESTONE_7_8_ARCHITECTURE_SCOPE_AUDIT_HANDOFF.md#starting-boundary)
were reloaded with repository validators. Their nine linked stages terminate
in `MILESTONE_7_7_COMPLETE` at the required completion HEAD. The soak contains
91 samples over 5,400 seconds with no interruption, and every defined residue
count is zero. The retained database evidence proves a PostgreSQL-authoritative
topology, one terminal successful migration execution to `0028`, TLS 1.3,
private DNS, and passing API/worker health. It contains no managed table-grant,
database-failover, ambiguous-commit, or cross-tenant campaign, so none is
inferred from the health soak.

Repository-safety correction, 2026-08-13: only the workstation-specific path
representation above was replaced by a repository-local evidence link; the
historical findings and conclusions are unchanged.

## Authority and exclusions

This is the second item in the implementation plan's ordered Milestone 7.8
audit list. It authorizes local inspection, exact classification, minimal fixes
for proved local defects, affected tests, documentation, and one local commit.
It does not authorize:

- Azure or other external-service access or mutation;
- a live database, secret value, image, scanner, soak, fault, restore, or
  cleanup run;
- dependency or lockfile changes;
- migration creation or modification, including `0029`;
- remote Git operations or protected-stash mutation;
- reopening Milestone 7.7; or
- continuing to the next Milestone 7.8 audit surface while this one is blocked.

No Azure CLI, browser, external connector, network client, database client, or
live service was invoked by this audit.

## Audit coverage

The audit traced configuration to Bicep, Bicep to process identities and
environment, environment to SQLAlchemy/asyncpg construction, runtime gates to
readiness behavior, the migration job to Alembic, API inputs to current
authorization and scoped SQL, and queued work to revocation fences and typed
constraints. The inventory includes:

- all 16 route modules and all 181 HTTP operations: 146 take a direct principal
  dependency; 25 canonical operations inherit the route-level path-workspace
  principal check; four public authentication operations are intentionally
  unauthenticated; two internal/upload operations use signed capabilities; and
  four health operations expose no tenant data;
- all 151 ORM tables: 120 have `workspace_id`, 54 have `canvas_id`, and the
  metadata contains 167 composite foreign keys;
- the four canvas-scoped tables without a direct `workspace_id` column
  (`nodes`, `edges`, `documents`, and `canvas_document_nodes`) and their typed
  canvas/document/node parent constraints;
- the central collaboration authorizer, membership generations, sharing,
  ownership transitions, revocation fences, graph retrieval, evidence bundles,
  workflows, agents, canonical objects, documents, secure ingestion, indexing,
  durable jobs, queues, and worker claim paths;
- all PostgreSQL settings, engine and managed-identity token code, runtime
  validation, migration environment/runner, current migration chain, database
  Bicep, identities, bootstrap SQL, deployment and recovery runbooks, Milestone
  7.1/7.6 handoffs, and retained Milestone 7.7 receipts.

The exact finding ledger is
[`MILESTONE_7_8_DEFECT_REGISTER.md`](MILESTONE_7_8_DEFECT_REGISTER.md).

## Classification summary

| Class                            | Count | Result                                                                                                                      |
| -------------------------------- | ----: | --------------------------------------------------------------------------------------------------------------------------- |
| Proved compliant control groups  |     6 | Retained as passing within the stated source/receipt limits                                                                 |
| Proved defects corrected locally |     2 | M78-PG-001 and M78-TI-001                                                                                                   |
| Proved defects unresolved        |     3 | M78-PG-002, M78-PG-003, and M78-PG-004; all High                                                                            |
| Unproved claims / evidence gaps  |     5 | Four High and one Medium                                                                                                    |
| Explicitly out of scope          |     5 | RLS amendment, migration `0029`, live managed reruns, topology mutation, and pre-existing Milestone 7.7 test-contract drift |

## Managed topology and connection construction

The source and retained receipt agree on the following proved controls:

- Azure Database for PostgreSQL Flexible Server, PostgreSQL 17;
- the database server and delegated VNet are fixed to `centralus`; application
  compute is fixed to `southcentralus` and reaches the database over reciprocal
  VNet peering and private DNS links;
- one authoritative primary with ZoneRedundant high availability and no
  application read-replica route;
- public network access disabled and private DNS/private endpoint routing;
- Entra authentication enabled and password authentication disabled;
- pgvector allowlisted and the runtime requires a compatible installed
  extension;
- credential-free URLs containing only the distinct principal name; a bounded
  managed-identity token provider supplies the short-lived password at connect;
- TLS `verify-full`, `READ COMMITTED`, pool pre-ping, ten-second connect,
  30-second statement, five-second lock, 30-second idle-transaction,
  15-second pool acquisition, and 1,800-second recycle settings;
- safe `database_unavailable` classification without connection details.

The Bicep also fixes seven-day backup retention, disables geo-redundant backup
and storage autogrow, and selects 64-GiB P6 storage. Those are observations, not
capacity or durability approvals. The repository has no explicit maintenance
window, exact provider-assigned zone placement, `max_connections`
configuration/evidence, or storage-growth rationale; that is M78-PG-E04.

## Pool and connection budget

Only API and worker processes now use a persistent pool. Their identities,
application names, and pools are separate. The declared per-replica values are
`pool_size=10` and `max_overflow=0`, with a maximum of four API and four worker
replicas:

| Consumer                         | Declared maximum  | Connection allocation proved from source |
| -------------------------------- | ----------------- | ---------------------------------------: |
| API service                      | 4 replicas x 10   |                                       40 |
| Worker service                   | 4 replicas x 10   |                                       40 |
| One-shot migration               | direct `NullPool` |                      1 active connection |
| API init gates during rollout    | up to 4 x 1       |                                        4 |
| Worker init gates during rollout | up to 4 x 1       |                                        4 |
| Static scenario subtotal         |                   |                                       89 |

Health checks share the process database object and add no independent pool.
The table is not an approved service budget: simultaneous old/new application
revisions, backup, observability, emergency, maintenance, and operator reserve
are absent or unbounded, and the deployed service ceiling was not retained.
Therefore the required `sum(all allocations) + reserve < max_connections`
inequality is unproved (M78-PG-E01).

## Database roles and least privilege

Runtime validation proves the process role matches the declared API/worker
role, the effective database principal matches the URL principal, API/worker
roles cannot create in `public`, and runtime principals are not superusers,
database creators, role creators, replication roles, or RLS bypass roles.

That does not prove table least privilege. The deployed bootstrap loops over
the API and worker principals and gives both the same CRUD access on every
table, sequence write access, and execution on every function, plus equivalent
default privileges. This directly violates the requirement that each receive
DML only on required tables (M78-PG-002).

The migration job uses `id-mobius77-db-admin`, the configured PostgreSQL Entra
administrator, to create both runtime principals, grant their privileges, and
execute Alembic. This violates the distinct least-privilege migration-credential
contract and combines provisioning with DDL authority (M78-PG-003). Backup,
observability, and emergency are closed application enum values but have no
deployed database identity/grant implementation or effective-grant evidence
(M78-PG-E02).

| Declared role              | Deployed principal          | Effective source-defined authority                                                                                   | Result                                   |
| -------------------------- | --------------------------- | -------------------------------------------------------------------------------------------------------------------- | ---------------------------------------- |
| Provisioning administrator | `id-mobius77-db-admin`      | PostgreSQL Entra administrator; creates Entra principals and grants                                                  | Explicit but excessive for migration use |
| Migration                  | Same `id-mobius77-db-admin` | Owns/runs the full Alembic DDL path and extension creation                                                           | High defect M78-PG-003                   |
| API                        | `id-mobius77-api`           | Connect/schema usage; CRUD all tables; write sequences; execute all functions; no dangerous role flags/schema create | High defect M78-PG-002                   |
| Worker                     | `id-mobius77-worker`        | Same grants as API                                                                                                   | High defect M78-PG-002                   |
| Backup                     | None defined                | Application enum only                                                                                                | Unproved, M78-PG-E02                     |
| Observability              | None defined                | Application enum only                                                                                                | Unproved, M78-PG-E02                     |
| Emergency                  | None defined                | Application enum only                                                                                                | Unproved, M78-PG-E02                     |

The bootstrap explicitly revokes `CREATE` on schema `public` from `PUBLIC`, but
the retained evidence has no complete `PUBLIC`, ownership, inheritance, or
effective catalog inventory. Those aspects remain in M78-PG-E02.

## Migration safety

The local chain remains linear with sole head `20260726_0028`; `0029` does not
exist. Startup never runs migrations. The one-shot job is manual, parallelism
one, completion count one, retry limit zero, timeout 1,800 seconds, and is
ordered before application readiness. The guarded Alembic environment:

- requires the migration process role;
- verifies the exact repository head and operator-declared current revision;
- opens a PostgreSQL session advisory lock and denies a competing runner;
- applies the exact target and verifies the final revision;
- rolls back and unlocks safely on failure; and
- now uses `NullPool`, correcting M78-PG-001.

No migration was executed, created, edited, upgraded, or downgraded in this
audit. The retained 7.7 execution is accepted only as proof that its one job
reached `0028`, not as proof of least privilege or failover behavior.

## Failure, recovery, and degraded behavior

Configuration and schema incompatibility fail startup/readiness. A transient
database dependency failure leaves liveness available but readiness false and
recovers through bounded reconnect behavior. Pool acquisition is bounded,
failed sessions roll back through the session context, and the primary remains
authoritative for protected reads and writes.

Milestone 7.6 proves isolated full-restore, point-in-time recovery, portable
restore, and failback exercises within that handoff's explicit limits. It does
not approve a production RPO/RTO, tenant rewind, or database failover claim.
The retained 7.7 soak is an uninterrupted health observation, not a fault
campaign. Managed failover, pool reuse after interruption, and ambiguous-commit
resolution remain unproved (M78-PG-E03).

The architecture requires every mutating API to resolve ambiguous outcomes by
durable idempotency identity. Canvas, node, duplicate-node, and edge creation
have no idempotency key or request digest and create server-random UUIDs. An
ambiguous committed response followed by retry can create a duplicate durable
object (M78-PG-004). Correcting that requires durable state and therefore a
separate migration amendment; it is not authorized here.

## Tenant-isolation path

The repository intentionally defines workspace, not a new `Tenant` entity, as
the data-isolation boundary. PostgreSQL RLS was deliberately rejected as a
Milestone 7 dependency; application authorization, current membership and
authority generation, typed parents, composite constraints, role separation,
and managed-provider isolation tests are authoritative.

The local path is fail-closed at the API and durable-work layers:

- user identity is server-derived; client workspace/object identifiers are
  selectors, never identity authority;
- current membership and authority generation are resolved by the central
  collaboration authorizer;
- sharing, ownership, comments, approvals, agents, and workflows use current
  permission ceilings and revocation evidence;
- ingestion, index publication, document jobs, queue deliveries, and worker
  claims persist workspace/user/membership scope and revalidate it at durable
  boundaries;
- typed composite foreign keys prevent cross-workspace/canvas parent binding;
  and
- pool sessions are transaction-scoped and roll back on exception.

The audit found that graph retrieval replay/readback, evidence-bundle readback,
and workflow creator-owned read/mutation helpers used stored creator/scope
columns without a current-authority check. M78-TI-001 is corrected by reusing
the current workspace/owner query and the centralized collaboration authorizer.
Focused tests delete the workspace after durable creation and prove retrieval
read, replay, bundle read, and workflow execution read all fail closed.

Local schema and test evidence cannot replace the required managed PostgreSQL
cross-user/workspace/canvas/resource, stale-membership, worker, pool-reuse,
retry, and failover campaign. That required proof is M78-TI-E01.

## Local corrections

1. `Database.from_settings` now selects a bounded persistent pool only for API
   and worker roles; migration and non-application roles use `NullPool`.
2. Graph retrieval validates the current owner/workspace/canvas scope before
   an idempotent replay lookup and every retrieval or bundle readback.
3. Workflow execution reads require current `workflow.view`; creator-owned
   definition/version mutation helpers require current `workflow.edit` through
   the existing central authorizer.
4. Focused regression tests cover the direct migration connection and stale
   workspace authority after durable records already exist.

No new abstraction, endpoint, table, migration, identity, dependency, or
infrastructure setting was added.

Exact changed files:

- `apps/api/opencanvas_api/db/session.py`;
- `apps/api/opencanvas_api/services/graph_retrieval.py`;
- `apps/api/opencanvas_api/services/workflows.py`;
- `apps/api/tests/test_database_runtime.py`;
- `apps/api/tests/test_graph_retrieval.py`;
- `apps/api/tests/test_controlled_workflows.py`;
- `docs/MILESTONE_7_8_DEFECT_REGISTER.md`; and
- `docs/MILESTONE_7_8_MANAGED_POSTGRESQL_TENANT_ISOLATION_AUDIT_HANDOFF.md`.

## Validation

All affected local validation passes. The command ledger is:

- `.venv\Scripts\python.exe -m pytest apps/api/tests/test_database_runtime.py apps/api/tests/test_migration_runtime.py apps/api/tests/test_milestone_7_7_runtime_topology.py -q`
  — exit 0, 40 passed, one pre-existing warning;
- `.venv\Scripts\python.exe -m pytest apps/api/tests/test_graph_retrieval.py apps/api/tests/test_controlled_workflows.py apps/api/tests/test_shared_workflow_agent_governance.py -q`
  — exit 0, 29 passed before the final two stale-authority assertions were
  added;
- `.venv\Scripts\python.exe -m pytest apps/api/tests/test_graph_retrieval.py apps/api/tests/test_controlled_workflows.py apps/api/tests/test_database_runtime.py -q`
  — exit 0, 51 passed with the final assertions.
- the three exact new regression node IDs — exit 0, 3 passed after the final
  deleted-workspace creation assertion;
- final controlled-workflow plus shared-governance rerun — exit 0, 18 passed;
- database, migration, health, PostgreSQL-support, identifier-safety, and
  topology group — exit 0, 138 passed;
- collaboration API, current authority, comments, resource sharing/ownership,
  membership service, shared workflow/agent governance, and agent authority
  group — exit 0, 24 passed;
- document API/extraction/retrieval/validation, durable jobs, indexer, object
  ingestion, knowledge graph, graph retrieval, and controlled workflow group —
  exit 0, 108 passed.

The three disjoint affected groups total 270 passing tests. The final focused
commands overlap those groups and are reported for chronological accuracy, not
added to the unique total.

- focused Ruff lint — exit 0, all checks passed;
- focused Ruff format check — exit 0, six files compliant;
- strict mypy from `apps/api` — exit 0, no issues in 94 production source
  files;
- focused `compileall` — exit 0;
- Markdown structure and local links — exit 0, two files passed;
- retained terminal-chain validator — exit 0, nine linked stages, 91 soak
  samples, 5,400 seconds, and ten zero-residue counters at zero;
- `alembic heads` — exit 0, sole head `20260726_0028`;
- migration `0029` absence, required-ancestor, no-upstream, five-stash,
  changed-scope, secret-assignment, and `git diff --check` guards — exit 0.
- `git fsck --full --no-reflogs` — exit 0; pre-existing unreachable objects
  are informational and were not modified by this audit.

An additional infrastructure-contract suite has a mixed result and is not
included in the passing totals:

- first run of `test_milestone_7_7_infrastructure_contracts.py` — exit 1,
  84 passed and 10 failed. Eight failures were secondary to two ignored
  `__pycache__` directories generated under the infrastructure bundle by this
  audit's local imports. Those exact cache directories were removed after
  their absolute paths were verified; they contain only reproducible bytecode;
- rerun with `PYTHONDONTWRITEBYTECODE=1` — exit 1, 92 passed and 2 failed. One
  assertion rejects `subscription().subscriptionId` in `main.bicep`; the other
  test's public-GUID allowlist omits the retained migration authorization ID in
  `observability_operator_bootstrap_adapter.py`;
- `git show` proves both failing source lines already exist at entry HEAD
  `621c414191843aedaa889b5802f2b4ada1b7c747`, and the audit diff changes
  neither the infrastructure bundle nor that test. The validated retained 7.7
  chain also depends on those records. They are classified out of scope for
  this database surface, not silently counted as passes or production database
  defects, and Milestone 7.7 is not reopened.

One attempted monolithic `.venv\Scripts\python.exe -m pytest apps/api/tests -m
"not postgres" -q` run reached its 904-second command ceiling with exit 124 and
no failure trace. It is not counted as a pass. The exact affected surface was
then split into the three bounded passing groups above.

`OPENCANVAS_TEST_POSTGRES_URL` is unset. The `postgres` marker was not run:
its fixtures start a live disposable PostgreSQL service, which this audit
explicitly forbids. No skipped managed-provider result is promoted to passing
evidence. An initial root-directory mypy diagnostic ignored the API's local
configuration and reported only missing `asyncpg` typing metadata; rerunning
from `apps/api` used the authoritative strict configuration and passed all 94
production files.

## Smallest future proof campaigns

These are rerun recipes, not present authority to execute them.

1. **Roles and budget.** After correcting M78-PG-002 and M78-PG-003, deploy the
   exact reviewed commit in one separately approved isolated environment.
   Record `SHOW max_connections`, effective catalog grants, activity by exact
   identity at declared replica ceilings, rollout overlap, all operator roles,
   and explicit reserve. Execute positive required operations and negative DDL,
   cross-role DML, function, schema, and database tests.
2. **Failover and ambiguous commits.** After correcting M78-PG-004, seed
   durable request identities, induce one bounded managed database failover
   during reads, writes, and worker claims, and prove readiness degradation,
   clean pool recovery, committed/unknown outcome resolution by request ID, and
   zero duplicate effects.
3. **Tenant isolation.** With two users, two workspaces, two canvases, and
   cross-linked candidate identifiers, exercise all protected resource classes,
   ingestion/index/worker paths, membership revocation, pool reuse, retry, and
   the failover window. Pass only with zero cross-scope read or mutation and
   catalog-backed constraint evidence.

The campaigns must use synthetic data, preserve secret redaction, record exact
commit/configuration identities and limits, and clean up only under their own
separate explicit authorization.

## Blocking exit

Milestone 7.8 cannot claim this surface complete while M78-PG-002,
M78-PG-003, and M78-PG-004 remain High and the managed role/budget/failover/
tenant proofs are absent. The next task must design and explicitly authorize
the durable idempotency amendment and database-role separation before any
managed proof campaign. This audit stops here and does not enter the next
ordered Milestone 7.8 surface.

The next unstarted ordered audit surface is object storage, upload
authorization, checksums, quarantine, scanner, promotion, retention, deletion,
and recovery. It remains unstarted because this database surface exits blocked.

`MILESTONE_7_8_DATABASE_SURFACE_AUDIT_BLOCKED`
