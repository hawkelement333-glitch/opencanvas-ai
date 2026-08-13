# Milestone 7.8 managed PostgreSQL evidence campaign handoff

Date: 2026-08-13

Status: blocked at the mandatory pre-mutation cleanup gate; no Azure mutation,
billable resource, image build, managed PostgreSQL execution, or Milestone 7.7
execution occurred

Terminal disposition:
`MILESTONE_7_8_MANAGED_POSTGRESQL_EVIDENCE_CAMPAIGN_BLOCKED_CLEANUP_COMPLETE`

## Outcome

The separately authorized managed PostgreSQL campaign stopped before its first
mutation. The repository does not contain an independently armable Milestone
7.8 cleanup implementation or a Milestone 7.8 provisioning/probe executable.
The only executable deployment and cleanup lifecycle is integrity-bound to the
completed Milestone 7.7 generation. Reusing or editing that lifecycle would
contradict the campaign's requirements to leave Milestone 7.7 execution
untouched, use a campaign-only cleanup scope, avoid production-code changes,
and prove cleanup before provisioning.

No campaign resource existed, so immediate manual cleanup had no target. A
final read-only inventory proved every campaign residue counter remained zero.
The billable clock never started, the best available actual cost is USD 0.00,
and the object-storage audit remains unstarted.

## Authoritative starting boundary

The boundary was checked once before Azure access:

- branch: `milestone-7-8-production-readiness-audit-local`;
- HEAD: `b0b92c780a4afa2c4d1decfed4ebbd0b6ee7e87d`;
- upstream: absent;
- index and worktree: clean;
- protected stashes: exactly five and unchanged;
- sole Alembic head: `20260726_0029`;
- migration `0030`: absent;
- local infrastructure contracts: 94 passed;
- repository hygiene: green;
- Milestone 7.7: complete and immutable; and
- Milestone 7.8: incomplete.

The five protected stash object IDs were compared before work and were not
printed into this tracked record. No stash operation occurred.

## Reconstructed campaign and cleanup path

The database-only repository topology would use the existing pre-secret and
owner-bootstrap shapes:

- `southcentralus`: private Container Apps environment, Premium ACR, Key Vault,
  Log Analytics, VNet, VPN gateway, private DNS resolver, API/worker/admin/
  migration identities, bootstrap and migration jobs, API and evidence jobs;
- `centralus`: PostgreSQL 17 Flexible Server, `Standard_D2ds_v5`, 64-GiB P6
  storage, ZoneRedundant HA, delegated VNet, private DNS, seven-day backup
  retention, password authentication disabled, and Entra authentication; and
- `westus`: independently scheduled Azure Automation cleanup.

That design is locally coherent, and the checked-in subscription-scope Bicep
compiled with the installed Bicep CLI. It is not an executable Milestone 7.8
campaign for these reasons:

1. The command ledger in the
   [High-defect remediation handoff](MILESTONE_7_8_MANAGED_POSTGRESQL_HIGH_DEFECT_REMEDIATION_HANDOFF.md#bounded-managed-evidence-campaign)
   begins with `az containerapp job start` and requires an already deployed
   resource group, bootstrap job, migration job, and server. It defines no
   environment-creation or cleanup-control operation.
2. `infra/milestone_7_7/main.bicep`, its cleanup module, owner-bootstrap module,
   and lifecycle executor bind the exact completed 7.7 target, cleanup, and
   Container Apps infrastructure resource-group names. Their operation order,
   authorization identity, tags, receipts, and image-publication domains are
   Milestone 7.7-specific.
3. `infra/milestone_7_7/scripts/Remove-Mobius77Staging.ps1` accepts only the
   exact 7.7 target, embeds a 2026-08-09 cleanup launch time, and requires the
   deleted 7.7 cleanup principal's fingerprint. Recreating the system-assigned
   Automation identity would not satisfy that retained fingerprint.
4. `infra/milestone_7_7/scripts/managed_binding_lifecycle.py` retains a
   Milestone 7.7 cleanup deadline, a 30-hour historical maximum, fixed 7.7
   scopes, and 7.7 authorization/receipt domains. Running it would reopen a
   completed milestone and would not create a distinct 7.8 cleanup contract.
5. No repository-approved managed database probe exists for the required
   catalog ACL matrix, connection-ceiling load, credential recovery,
   ambiguous-commit interruption, or two-tenant failover sequence. The image
   contains the production bootstrap and migration programs, but not the
   evidence harness the handoff requires.

Generating altered runbook content, bypassing the lifecycle receipt gate,
copying the 7.7 Bicep into an unreviewed temporary deployment, or injecting an
untracked probe would redesign the campaign and make cleanup and evidence
claims depend on unreviewed code. The authorization expressly prohibited that
course. The mandatory rule therefore applied: if cleanup cannot be proved
before provisioning, stop without mutation.

## Sanitized Azure read-only gate

All commands were read-only. Raw account identifiers were held only in process
memory. The tracked correlation values are domain-separated truncated SHA-256
fingerprints:

| Assertion                                                          | Result                                                                                              |
| ------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------- |
| Active account                                                     | enabled in `AzureCloud`                                                                             |
| Subscription correlation                                           | `a5515b9214bab4b4`                                                                                  |
| Tenant correlation                                                 | `9991705a7c63b0c6`                                                                                  |
| Subscription resource count                                        | 7 total; none was adopted or changed                                                                |
| Existing unrelated Log Analytics workspaces                        | 1; name not recorded and untouched                                                                  |
| Flexible Servers / ACR / Container Apps environments / apps / jobs | 0 / 0 / 0 / 0 / 0                                                                                   |
| User-assigned identities / Automation accounts                     | 0 / 0                                                                                               |
| Private endpoints / private DNS zones / VNets                      | 0 / 0 / 0                                                                                           |
| Exact retained 7.7 target / cleanup / infrastructure groups        | absent / absent / absent                                                                            |
| Required providers                                                 | all nine registered                                                                                 |
| PostgreSQL region/SKU                                              | `centralus` exposes General Purpose `Standard_D2ds_v5` with `SameZone` and `ZoneRedundant` HA modes |
| Azure mutation count                                               | 0                                                                                                   |

The registered providers were `Microsoft.Resources`,
`Microsoft.Authorization`, `Microsoft.Network`, `Microsoft.ManagedIdentity`,
`Microsoft.Automation`, `Microsoft.ContainerRegistry`, `Microsoft.App`,
`Microsoft.DBforPostgreSQL`, and `Microsoft.OperationalInsights`.

Name availability and deployment quota were not promoted to passing claims.
The CLI exposes the regional SKU/capability inventory, but the campaign stopped
before a distinct 7.8 resource graph supplied names or a cleanup scope against
which to complete those gates.

## Conservative four-hour cost envelope

The cost calculation used USD pay-as-you-go retail meters returned by the
[Azure Retail Prices API](https://prices.azure.com/api/retail/prices) on
2026-08-13. It charges every declared resource for four full hours, includes HA
duplication and rollout/job overlap, treats ACR as a full day, uses the complete
2-GiB Log Analytics daily cap, bounds data transfer, and reserves amounts for
monitoring and one image-security evaluation.

| Component and conservative quantity                                                                    |         USD |
| ------------------------------------------------------------------------------------------------------ | ----------: |
| PostgreSQL `Standard_D2ds_v5`, two HA nodes, 4 hours at USD 0.201/node-hour                            |      1.6080 |
| 64-GiB PostgreSQL storage plus an additional full 64-GiB backup allocation                             |      0.0835 |
| Premium ACR full day plus 2-vCPU, 1,800-second build                                                   |      2.0266 |
| `VpnGw1AZ` plus one Standard public IP, 4 hours                                                        |      0.8600 |
| Private DNS resolver inbound endpoint, 4/730 of USD 180/month                                          |      0.9863 |
| Two private endpoints and three private DNS zones                                                      |      0.0882 |
| Forty GiB inter-region peering plus forty GiB Private Link processing                                  |      1.8000 |
| Log Analytics maximum 2-GiB ingestion                                                                  |      5.5200 |
| Container Apps: 4 API + 4 worker ceilings, one rollout overlap, bounded jobs, and one million requests |      3.4240 |
| Automation cleanup runtime and 10,000 Key Vault operations                                             |      0.1500 |
| Azure Monitor reserve                                                                                  |      2.0000 |
| One image-security evaluation reserve                                                                  |      2.0000 |
| Subtotal                                                                                               |     20.5466 |
| Required 25% contingency                                                                               |      5.1366 |
| **Conservative maximum**                                                                               | **25.6832** |
| **Margin below USD 50 ceiling**                                                                        | **24.3168** |

The price envelope passes. It does not authorize mutation by itself, and it
must be recalculated if a separately reviewed 7.8 executable changes the
resource graph, replica/job bounds, regions, SKUs, or meters.

## Image decision

No exact trusted image can be reused:

- source HEAD: `b0b92c780a4afa2c4d1decfed4ebbd0b6ee7e87d`;
- canonical API build-input SHA-256:
  `ed5ca8ad622f038686fcd7fe2b27049ce4604fec99d0635495778906883df582`;
- Dockerfile SHA-256:
  `94e4ae9a1a3e87a95285f80851cf058b5828dfeb20575e486abe4da6ab2e6ce6`;
- build-requirements lock SHA-256:
  `22f8b5d1f0b8521e28470f6097717ff64c9cccc7b6037db7a5c25962e32a7ccb`;
- runtime requirements lock SHA-256:
  `deb7551c4af27ce8d4e420bba568678fa3166e52c4ecbaaba8b9d869461e608f`;
- local Docker inventory: 31 images, 28 Mobius/OpenCanvas matches, none bound
  to the starting HEAD; and
- managed ACR inventory: zero registries.

The retained 7.7 image was built from a different source and build-input hash
and remains historical evidence only. A single new validation image would have
been required after cleanup and probe admission. No image was built, tagged,
published, admitted, or scanned. Image generation count is zero.

## Required proof disposition

| Proof                                                     | Disposition                                                  |
| --------------------------------------------------------- | ------------------------------------------------------------ |
| Managed catalog and positive/negative role matrix         | blocked before provisioning; M78-PG-E02 remains open         |
| Migration/admin identity separation in managed PostgreSQL | blocked before provisioning; local correction remains intact |
| Deployed connection budget and observed peak              | blocked before provisioning; M78-PG-E01 remains open         |
| Managed failover and credential recovery                  | blocked before provisioning; M78-PG-E03 remains open         |
| Four ambiguous-commit operations                          | blocked before provisioning; M78-PG-E03 remains open         |
| Two-tenant pool reuse/failover isolation                  | blocked before provisioning; M78-TI-E01 remains open         |
| Assigned zones, maintenance, storage, backup, and latency | blocked before provisioning; M78-PG-E04 remains open         |

M78-PG-002, M78-PG-003, and M78-PG-004 remain locally remediated. This
pre-mutation stop neither reopens them nor supplies the managed evidence needed
to close the database audit surface.

## Validation ledger

All commands were run from the repository root unless the row says `apps/api`.
The first combined launcher was terminated by its shell wrapper after 5.1
seconds with exit 124 and produced no usable subsystem result. It was replaced
with the bounded commands below; the inherited 904-second monolith was not run.

| Exact command                                                                                                                                                                                                                                                                          | Exit/result                                                                       |
| -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| `cd apps/api; ..\..\.venv\Scripts\python.exe -m pytest -q tests/test_legacy_creation_idempotency.py tests/test_canvas_api.py tests/test_document_api.py tests/test_milestone_7_8_database_remediation.py`                                                                              | 0; 26 passed; 41.5 s                                                              |
| `cd apps/api; ..\..\.venv\Scripts\python.exe -m pytest -q tests/test_database_runtime.py tests/test_migration_runner_postgres.py tests/test_milestone_7_7_runtime_topology.py tests/test_migration_runtime.py`                                                                         | 0; 40 passed, 2 skipped because no local PostgreSQL fixture was configured; 4.9 s |
| `cd apps/api; ..\..\.venv\Scripts\python.exe -m pytest -q tests/test_auth_authorization.py tests/test_collaboration_comments.py tests/test_collaboration_resources.py tests/test_graph_retrieval.py tests/test_controlled_workflows.py tests/test_shared_workflow_agent_governance.py` | 0; 35 passed; 82.1 s                                                              |
| `.\.venv\Scripts\python.exe scripts\validate_migrations.py`                                                                                                                                                                                                                            | 0; upgrade `0029`, downgrade `0028`, re-upgrade `0029`; 7.0 s                     |
| `cd apps/api; ..\..\.venv\Scripts\python.exe -m alembic -c alembic.ini heads`                                                                                                                                                                                                          | 0; `20260726_0029 (head)`; 0.6 s                                                  |
| `az bicep build --file infra/milestone_7_7/main.bicep --stdout`                                                                                                                                                                                                                        | 0; 6.4 s                                                                          |
| `.\.venv\Scripts\python.exe -m pytest -q apps/api/tests/test_milestone_7_7_infrastructure_contracts.py`                                                                                                                                                                                | 0; 94 passed; 12.2 s                                                              |
| `.\.venv\Scripts\python.exe scripts\check_repository_hygiene.py`                                                                                                                                                                                                                       | 0; 597 source files; 1.5 s                                                        |
| `cd apps/api; ..\..\.venv\Scripts\ruff.exe check -- <8 affected production files>`                                                                                                                                                                                                     | 0; 8 files                                                                        |
| `cd apps/api; ..\..\.venv\Scripts\ruff.exe format --check -- <8 affected production files>`                                                                                                                                                                                            | 0; 8 files already formatted                                                      |
| `cd apps/api; ..\..\.venv\Scripts\mypy.exe --strict <8 affected production files>`                                                                                                                                                                                                     | 0; no issues in 8 files                                                           |

The Azure read-only ledger used `az account show`, sanitized `az resource
list`, exact `az group exists` checks, `az provider show`, and `az postgres
flexible-server list-skus`. No token, credential, complete subscription/tenant
identifier, complete ARM ID, unrelated resource name, or raw account document
was written to the repository.

## Cleanup and zero residue

Because the first mutation never occurred, the campaign generation, image
generation, failover, credential rotation, and cleanup execution counts are all
zero. Final residue counters are:

| Counter                                                   |         Value |
| --------------------------------------------------------- | ------------: |
| Campaign resource groups                                  |             0 |
| Cleanup schedules / Automation accounts                   |         0 / 0 |
| Campaign role assignments                                 |             0 |
| Flexible Servers / application databases                  |         0 / 0 |
| Container registries / campaign artifacts                 |         0 / 0 |
| Container Apps environments / apps / jobs                 |     0 / 0 / 0 |
| Campaign managed identities                               |             0 |
| Private endpoints / campaign private DNS zones or records |         0 / 0 |
| Campaign VNets / peerings / public IPs / VPN gateways     | 0 / 0 / 0 / 0 |
| Campaign locks / diagnostic settings                      |         0 / 0 |
| Synthetic tenant or application rows                      |             0 |
| Live cleanup authorization residue                        |             0 |

The pre-existing unrelated seven subscription resources were not adopted,
read by name, changed, or deleted.

## Prohibited-operation confirmation

No Azure resource or role mutation, live or managed database connection,
secret creation/access/printing/rotation, production-data access, image build or
publication, image admission scan, object-upload scanner operation, object
storage audit, soak, cleanup-infrastructure creation, dependency or lockfile
change, remote Git operation, or Milestone 7.7 execution occurred. Retained
Milestone 7.7 evidence, canonical image inputs, and the five protected stashes
were not modified.

## Required next action

Do not retry provisioning from the 7.7 lifecycle. A separately bounded local
remediation must first add and test:

1. a Milestone 7.8-specific, parameterized deployment contract with one unique
   campaign generation and the resource graph priced above;
2. a Milestone 7.8 cleanup controller whose target, current subscription
   fingerprint, newly created principal fingerprint, deadline, and published
   content are bound and proved before billable resources;
3. one repository-reviewed database evidence harness covering every catalog,
   privilege, capacity, recovery, idempotency, and tenant assertion; and
4. a distinct 7.8 lifecycle ledger with exact operation receipts, four-hour
   limits, USD 50 ceiling, image-count enforcement, failure cleanup, and
   zero-residue validation.

After that local correction is committed, a new explicit authorization is
required for one managed PostgreSQL campaign. The next action is not an
object-storage audit, image retry, Git push, soak, or Milestone 7.7 execution.
Milestone 7.8 remains incomplete.

## Campaign-enablement resume disposition

The repository-local enablement task resumed on 2026-08-13 from clean HEAD
`89aafc6d65fbec376bd26796d1a1b74ee3bafd50`. It stopped before creating the new
`infra/milestone_7_8/` surface because production-path reconstruction proved a
new High defect, M78-PG-005.

The 7.8 campaign must use identities derived from its independent campaign and
generation and must contain no retained 7.7 identifier. The canonical API image
instead ships two database operational entry points whose fail-closed principal
contracts accept only the exact retained 7.7 names:

- `apps/api/scripts/bootstrap_postgres.py` lines 17-18 and 43-44 reject every
  migration, API, or worker principal outside `id-mobius77-*`; lines 148-149
  reject every bootstrap administrator except `id-mobius77-db-admin`.
- `apps/api/scripts/migrate_and_grant.py` lines 19-20 and 25-34 reject every
  migration, API, or worker principal outside the same exact name set before
  migration or privilege reconciliation.

This makes both possible infrastructure choices invalid: 7.8-derived names
cannot pass the production bootstrap/migration programs, while the accepted
names would bind the new campaign to retained 7.7 identifiers. The enablement
authorization expressly forbids changing already-remediated application or
database behavior and instructs the task to register and stop when harness
implementation proves such a change necessary. M78-PG-005 is recorded in the
[defect register](MILESTONE_7_8_DEFECT_REGISTER.md#managed-postgresql-and-tenant-isolation-findings).

No deployment, cleanup controller, lifecycle, ledger, evidence harness, or
operator runbook implementation was started after this proof. No managed
evidence gap was closed. A separately authorized minimal production-script
change must parameterize the principal-name contract without weakening its
role-separation and identifier-safety guarantees; campaign enablement can then
resume from the resulting clean HEAD. The managed Azure campaign remains
unauthorized and unexecuted, and the object-storage audit remains unstarted.
