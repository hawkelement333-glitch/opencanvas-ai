# Milestone 7.8 managed PostgreSQL campaign-enablement handoff

Date: 2026-08-13

Status: repository-local campaign enablement ready; managed campaign unexecuted

## Outcome

M78-PG-005 is locally remediated and the independent Milestone 7.8 managed
PostgreSQL campaign is implemented, locally compiled, simulated, tested, and
documented. The implementation contains no executable dependency on a retained
Milestone 7.7 identity, resource, deadline, receipt, or lifecycle.

No Azure or database command was executed. No resource, image, or scan was
created. Campaign spend remains USD 0.00, resource generations remain zero,
and image generations remain zero. M78-PG-E01, M78-PG-E02, M78-PG-E03,
M78-TI-E01, and M78-PG-E04 remain open until a separately authorized campaign
executes this machinery. Milestone 7.8 remains incomplete, and the
object-storage audit remains unstarted.

## Authoritative starting boundary

- branch: `milestone-7-8-production-readiness-audit-local`;
- starting HEAD: `9e4b12c04f3882d4530be0e6318e9a46c4ccce12`;
- upstream: absent;
- starting tree/index: clean;
- protected stashes: exactly five, untouched;
- Alembic sole head: `20260726_0029`;
- migration 0030: absent;
- campaign resource/image generations: 0 / 0;
- campaign spend: USD 0.00;
- future hard ceiling: USD 50.00;
- conservative four-hour estimate: USD 25.6832, including 25 percent
  contingency.

The retained Milestone 7.7 terminal chain, its nine stages, 91 samples, 5,400
seconds, ten zero residue counters, images, deleted scopes, principals,
deadlines, receipts, and hashes were not executed or changed.

## M78-PG-005 root cause and correction

The bootstrap and migration/grant entry points compared environment-provided
principal labels to four fixed `id-mobius77-*` strings. A valid campaign-only
7.8 identity therefore failed before principal creation or Alembic, while
using one of the accepted labels would have coupled the new campaign to a
retained milestone. The label itself was also being treated as more authority
than its stable object binding.

`apps/api/opencanvas_api/db/principal_manifest.py` now owns one closed
`m7.8-principal-manifest-v1` contract:

- exact semantic slots: bootstrap, migration, API, worker, evidence, cleanup;
- one validated campaign and one generation;
- one sanitized subscription correlation;
- exact `role`, safely quotable `name`, and nonzero UUID `objectId` per slot;
- all names and all object IDs distinct;
- no missing, unknown, duplicated, swapped, malformed, stale, or conflicting
  field accepted; and
- active bootstrap/migration/evidence probes must match both the semantic name
  and `OPENCANVAS_DATABASE_CURRENT_PRINCIPAL_ID`.

`bootstrap_postgres.py` and `migrate_and_grant.py` consume the same manifest.
The bootstrap program creates migration, API, worker, and evidence principals,
checks role flags/membership, transfers ownership to migration, gives evidence
only `CONNECT` and `pg_monitor`, and applies the unchanged literal runtime
matrices. The migration program verifies its own manifest binding before the
existing direct-`NullPool`, expected-head, advisory-lock runner and then
reconciles the same runtime grants. There is no retained-name exception,
fallback, allowlist, or compatibility bypass.

The directly related executable couplings corrected are the fixed-name checks
in those two shipped scripts and the corresponding topology contract. No other
executable campaign path contained a fixed 7.7 principal, resource, deadline,
or receipt dependency. Historical documents retain their original names as
evidence and are not runtime inputs.

## Role, privilege, and ownership model

| Semantic identity | Purpose                                       | Database authority                                                                             | Explicit denial boundary                                                      |
| ----------------- | --------------------------------------------- | ---------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| Bootstrap         | Entra administrator and provisioning-only job | create/verify non-cleanup principals, transfer ownership, reconcile grants                     | no application, worker, or migration runtime attachment                       |
| Migration         | reviewed Alembic and grant job                | owns application schema/objects; exact `CONNECT`/database `CREATE` and schema `USAGE`/`CREATE` | cannot create Azure resources or database roles; no runtime can assume it     |
| API               | application service                           | 150 SELECT, 149 INSERT, 17 UPDATE, 9 DELETE tables                                             | no sequence/function, DDL, role, grant, migration, or bootstrap authority     |
| Worker            | durable worker job                            | 55 SELECT, 18 INSERT, 6 UPDATE, 1 DELETE tables                                                | no sequence/function, DDL, role, grant, migration, or bootstrap authority     |
| Evidence          | managed proof job                             | `CONNECT`, `pg_monitor`, and catalog visibility                                                | no database/schema creation, ownership, runtime DML grant, or role assumption |
| Cleanup           | independent Automation controller             | none                                                                                           | no PostgreSQL identity or application access                                  |

Current blanket grants are revoked before exact grants. Default runtime table,
sequence, and function grants remain absent; unsafe current/default `PUBLIC`
function execution is revoked. API and worker receive no sequence or function
privileges. M78-PG-002 and M78-PG-003 remain intact.

## Independent deployment and cleanup

`infra/milestone_7_8/main.bicep` and its modules define a subscription
deployment with two campaign-only resource groups and no 7.7 import. The target
contains five campaign-derived user-assigned identities, one private
PostgreSQL 17 Flexible Server (`Standard_D2ds_v5`, 64 GiB P6, zones 1 and 2,
ZoneRedundant HA, seven-day retention, disabled geo backup, Sunday 07:00 UTC
maintenance), a private Premium ACR, private VNet/subnets/DNS, Log Analytics,
an internal Container Apps environment, one internal API, and the bounded
worker/bootstrap/migration/evidence/probe/recovery jobs. Workloads are created
only in the digest-pinned workload deployment stage.

`cleanup.bicep` deploys first to a distinct cleanup group. One Automation
account system identity receives Contributor and Role Based Access Control
Administrator only at the exact target and cleanup group scopes, permitting
resource and scoped RBAC-extension removal without a persistent custom role.
One published runbook, one one-time schedule, and one
binding are derived from the campaign/generation. Readback validates the
actual identity, exact deadline, names, binding count, published state, content
hash, group tags, campaign/generation, subscription correlation, and USD 50
ceiling. The runbook deletes the target and then its own group; the operator has
an exact-two-group fallback. Deadline, target, identity, and generation
substitution fail closed.

## Lifecycle, cost, and image gate

The restart ledger contains 20 ordered states from `new` through `finalized`.
It rejects phase skipping, a discontinuous transition chain, resume under
another campaign/generation, deadline change, a second resource generation, a
second image generation/digest/scan, negative residue, and actual cost over USD 50. Full hours are rounded up. The first billable transition binds the original
four-hour deadline. Cleanup is permitted after the deadline so an expiry can
never prevent recovery.

Every error after scope creation starts cleanup. The terminal sequence requires
both resource groups absent, no campaign-tagged resource, no scoped role
assignment, and every defined residue counter at zero before finalization.
Simulation covers a successful zero-to-zero run and failure at every state.

The source changes alter canonical API image inputs. One new 7.8 validation
image and exactly one admission scan are therefore required by the later
campaign. The operator validates the scan receipt before workload deployment;
it binds version, final source HEAD, canonical build-input hash, immutable
digest, scanner/version/time, passing result, and zero High/Critical findings.
No image or scan was performed here.

## Managed evidence design and transaction semantics

`apps/api/scripts/managed_postgres_evidence.py` emits only sanitized,
domain-separated assertion hashes and counts. It never emits credentials or
synthetic payloads. The campaign uses two synthetic users/clients and
deterministic, process-independent idempotency keys bound to campaign,
generation, tenant, operation, and mutation identity.

The harness proves:

- actual role flags, membership, schema/object ownership, `PUBLIC` schema and
  function ACLs, and exact API/worker table privileges for every public table;
- absence of runtime sequence/function privileges and positive/negative
  migration/bootstrap separation;
- migration `20260726_0029`, `NullPool`, advisory lock, ordering, and exact
  reconciliation;
- deployed `max_connections`, allocations, observed peak, safety reserve,
  zones, HA, maintenance, storage, backup, latency, and recovery duration;
- first, replay, conflict, process-independent replay, and exactly one durable
  identity/result for canvas, node, duplicate-node, and edge;
- same-key cross-tenant isolation, forged workspace denial, current-authority
  readback, evidence-bundle/workflow scope denial, and two-user separation;
- API login revocation, active-session termination, negative connection,
  restoration, forced failover, stale-pool recovery, and post-failover replay
  and tenant isolation.

The existing 0029 transaction semantics are unchanged: request claim and
domain object share one transaction and PostgreSQL uniqueness authority;
rollback removes both, replay reauthorizes and returns the original result,
conflicting payload/scope returns 409, and no TTL invalidates an ambiguous
commit retry. No migration was added or changed in this task.

The operator accepts only sanitized configuration/capacity observations. It
does not accept preclaimed recovery success. It derives credential recovery,
failover, post-failover tenant isolation, and measured recovery duration only
after the corresponding jobs/control command succeed. It persists 12 terminal
execution observations in a closed, source/digest/control-bound receipt and
can consume that receipt after a crash between evidence completion and ledger
transition without rerunning mutations.

## Evidence-gap disposition

| Gap        | Repository-local disposition                                                                                                                                                     | Managed proof still required                                                                           |
| ---------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| M78-PG-E01 | capacity schema, exact inequality, catalog query, observed-peak/reserve gate implemented                                                                                         | execute at deployed ceilings and retain actual max/reserved/peak/overlap/operator/reserve observations |
| M78-PG-E02 | effective catalog inventory and exact positive/negative API, worker, migration, ownership, membership, sequence, function, schema, database, and `PUBLIC` assertions implemented | execute through the five exact managed database identities                                             |
| M78-PG-E03 | credential revoke/terminate/deny/restore and forced-failover orchestration plus four-operation replay implemented                                                                | execute managed disruption and retain terminal/recovery evidence                                       |
| M78-TI-E01 | two-user, cross-workspace, forged-scope, current-authority, pool-reuse, replay, and post-failover assertions implemented                                                         | execute against managed PostgreSQL/pools and retain zero-cross-scope proof                             |
| M78-PG-E04 | exact Bicep settings and closed control-plane observation schema implemented                                                                                                     | retain actual zones, maintenance, storage, backup, latency, and recovery observations                  |

No gap is closed by local code or documentation. The bounded campaign in the
[operator runbook](MILESTONE_7_8_MANAGED_POSTGRESQL_CAMPAIGN_OPERATOR_RUNBOOK.md)
is the separately authorizable next action.

## Canonical image boundary

The frozen final canonical inventory and hashes are:

- input inventory:
  - `apps/api/Dockerfile`;
  - `apps/api/Dockerfile.dockerignore`;
  - `apps/api/pyproject.toml`;
  - `apps/api/build-requirements.lock`;
  - `apps/api/requirements.lock`;
  - `apps/api/opencanvas_api`;
  - `apps/api/alembic.ini`;
  - `apps/api/alembic`;
  - `apps/api/scripts`;
  - `LICENSE`;
  - `COPYRIGHT`;
  - `NOTICE`;
  - `THIRD_PARTY_NOTICES.md`;
- build-input SHA-256:
  `533dc8d9a64f2d4b1a8a10d5ac769b11e1bc962741a7637da44c037e34c4dad7`;
- Dockerfile SHA-256:
  `1f914420f661e40bcc8e61d149115387042fd3948323b645b9a204390c90a82b`;
- `apps/api/pyproject.toml` SHA-256:
  `b826c6e415e5c836cda5c74696d69b61f517a86556b2fecb82201ca35540868c`;
- `apps/api/build-requirements.lock` SHA-256:
  `22f8b5d1f0b8521e28470f6097717ff64c9cccc7b6037db7a5c25962e32a7ccb`;
- `apps/api/requirements.lock` SHA-256:
  `cdab59f073ff510ff6d8b951d178381650236662b488c06b2d6436063f336aa0`.

These values are calculated from the staged final Git tree after all canonical
source changes. Dependency and lock files were not modified. The retained 7.7
image does not match this source; the later campaign requires exactly one new
image build/publication and exactly one digest-bound admission scan.

## Changed files

- `apps/api/opencanvas_api/db/principal_manifest.py`
- `apps/api/scripts/bootstrap_postgres.py`
- `apps/api/scripts/credential_recovery_probe.py`
- `apps/api/scripts/managed_postgres_evidence.py`
- `apps/api/scripts/migrate_and_grant.py`
- `apps/api/tests/test_milestone_7_7_runtime_topology.py`
- `apps/api/tests/test_milestone_7_8_campaign_enablement.py`
- `docs/DEPLOYMENT.md`
- `docs/MILESTONE_7_8_DEFECT_REGISTER.md`
- `docs/MILESTONE_7_8_MANAGED_POSTGRESQL_CAMPAIGN_ENABLEMENT_HANDOFF.md`
- `docs/MILESTONE_7_8_MANAGED_POSTGRESQL_CAMPAIGN_OPERATOR_RUNBOOK.md`
- `docs/MILESTONE_7_8_MANAGED_POSTGRESQL_EVIDENCE_CAMPAIGN_HANDOFF.md`
- `docs/MILESTONE_7_ARCHITECTURE.md`
- `infra/milestone_7_8/README.md`
- `infra/milestone_7_8/__init__.py`
- `infra/milestone_7_8/bicepconfig.json`
- `infra/milestone_7_8/campaign.py`
- `infra/milestone_7_8/canonical_inputs.py`
- `infra/milestone_7_8/cleanup.bicep`
- `infra/milestone_7_8/main.bicep`
- `infra/milestone_7_8/modules/campaign-resources.bicep`
- `infra/milestone_7_8/modules/cleanup-controller.bicep`
- `infra/milestone_7_8/modules/cleanup-rbac.bicep`
- `infra/milestone_7_8/modules/identities.bicep`
- `infra/milestone_7_8/operator.py`
- `infra/milestone_7_8/prepare.py`
- `infra/milestone_7_8/schemas/campaign.schema.json`
- `infra/milestone_7_8/schemas/control-plane-evidence.schema.json`
- `infra/milestone_7_8/schemas/evidence-execution.schema.json`
- `infra/milestone_7_8/schemas/image-scan.schema.json`
- `infra/milestone_7_8/schemas/ledger.schema.json`
- `infra/milestone_7_8/schemas/principal-manifest.schema.json`
- `infra/milestone_7_8/schemas/runtime.schema.json`
- `infra/milestone_7_8/scripts/Remove-M78Campaign.ps1`

No dependency, lockfile, historical migration, retained 7.7 evidence, or
canonical image input was modified after the frozen hash calculation.

## Local validation

- `python -m pytest -p no:cacheprovider -q
apps/api/tests/test_milestone_7_8_campaign_enablement.py
apps/api/tests/test_milestone_7_7_runtime_topology.py`: 55 passed, exit 0;
- `python -m pytest -p no:cacheprovider -q
apps/api/tests/test_milestone_7_7_infrastructure_contracts.py`: 94 passed,
  exit 0;
- legacy creation/canvas/document/database-remediation shard: 26 passed, exit
  0;
- database runtime/migration runner/topology/migration-runtime shard: 40
  passed, 2 PostgreSQL-fixture tests skipped, exit 0;
- auth/collaboration/graph/workflow shard: 35 passed, exit 0;
- `python scripts/validate_migrations.py`: upgrade 0029, downgrade 0028,
  re-upgrade 0029 passed, exit 0;
- `alembic heads`: exactly `20260726_0029 (head)`, exit 0; no 0030 file;
- strict mypy over nine affected production Python files: no issues, exit 0;
- Ruff check and format-check over the affected Python surface: passed, exit 0;
- Bicep build of `main.bicep`, `cleanup.bicep`, and all four modules: passed
  without compiler warnings, six exit-0 results;
- targeted Prettier check over seven affected Markdown files: passed, exit 0;
- JSON parsing of all seven schemas and local-link validation of all seven
  affected Markdown files: passed, exit 0;
- cleanup PowerShell parser validation: no syntax errors, exit 0;
- repository hygiene: passed for 625 source files, exit 0;
- private identifier guard: 1 passed, exit 0;
- `git diff --check`: passed, exit 0;
- generated campaign bytecode was removed; no campaign cache remains.

Three nonfinal validation iterations were corrected transparently: the first
Ruff pass found three import-order issues and one tuple-style issue; the first
Bicep pass emitted two type-shape warnings; and the first campaign rerun found
that a prose reference to the existing topology suite was included in an
executable-coupling scan. Scoped fixes produced the final green results above.
The initial Markdown command used a nonexistent root Prettier shim, and the
first valid targeted check found three files needing formatting; the installed
web-workspace shim formatted only those files and the final check passed.
One later Bicep compile caught the new cleanup-label parameter on the identity
module instead of the campaign-resource module; moving that one parameter to
its intended module produced the final six warning-free compilations.
An optional Draft 2020-12 meta-schema check could not start because the local
virtual environment does not contain `jsonschema` (`ModuleNotFoundError`, exit
1). No dependency was installed. The seven schema documents parse locally and
their closed fields, types, bounds, and substitution behavior remain exercised
by the focused contracts.

No local PostgreSQL fixture was started. PostgreSQL-specific behavior remains
represented by source contracts and fake adapters until the authorized managed
campaign. Validation used installed tooling only and no dependency or network
installation.

## Remaining boundary

M78-PG-005 is resolved in repository state. The managed campaign remains
unexecuted and separately authorized; the five managed gaps remain open. The
next action is that bounded campaign, not an object-storage audit and not a Git
push. Milestone 7.8 remains incomplete.
