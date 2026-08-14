# Milestone 7.8 fresh managed PostgreSQL campaign execution handoff

Date: 2026-08-13

Status: blocked during independent cleanup-controller deployment; direct cleanup
completed with zero residue

Terminal disposition:
`MILESTONE_7_8_MANAGED_POSTGRESQL_EVIDENCE_CAMPAIGN_BLOCKED_CLEANUP_COMPLETE`

## Outcome

The fresh campaign proved the corrected Windows Azure CLI process boundary,
repository and canonical-image boundary, AzureCloud account correlation, six
provider registrations, PostgreSQL regional SKU and ZoneRedundant capability,
quota, global names, collision absence, seven-resource unrelated inventory,
and the refreshed cost gate. It then stopped at the first failed invariant.

The subscription-scoped cleanup deployment created the two tagged resource
group boundaries, but Azure rejected the Automation account with `BadRequest`:
only one Automation account is allowed for this subscription per region, and
the committed `westus` cleanup region already contains an unrelated account.
The cleanup controller therefore never existed or armed. The target deployment,
image build, image scan, PostgreSQL deployment, managed evidence harness, and
failover did not start.

The operator immediately entered its exact-two-group direct cleanup fallback.
Both groups are absent, the unrelated subscription resource count remains
7 / 7, all 15 residue counters are zero, the billable clock never started,
and the best available actual campaign cost is USD 0.00. No proof gap is
closed. Milestone 7.8 remains incomplete, and the object-storage audit remains
unstarted.

The sanitized machine-readable receipt is
[`managed-postgresql-fresh-campaign-execution.json`](../evidence/milestone_7_8/managed-postgresql-fresh-campaign-execution.json).
The retired Windows-launcher-blocked receipt remains unchanged.

## Starting boundary

- branch: `milestone-7-8-production-readiness-audit-local`;
- starting HEAD: `15837918c9e17b0bc1ce9e49ebca7bc4f9ae9999`;
- subject: `fix(infra): support Windows Azure CLI launcher`;
- upstream: absent;
- starting tree/index: clean;
- protected stashes: exactly five and unchanged;
- Alembic sole head: `20260726_0029`;
- migration `0030`: absent;
- private runtime directory: absent before preparation;
- retained resource/image/scan generations: 0 / 0 / 0;
- retained campaign spend: USD 0.00; and
- object-storage audit: unstarted.

The frozen hashes matched exactly:

| Input        | SHA-256                                                            |
| ------------ | ------------------------------------------------------------------ |
| build input  | `533dc8d9a64f2d4b1a8a10d5ac769b11e1bc962741a7637da44c037e34c4dad7` |
| Dockerfile   | `1f914420f661e40bcc8e61d149115387042fd3948323b645b9a204390c90a82b` |
| API project  | `b826c6e415e5c836cda5c74696d69b61f517a86556b2fecb82201ca35540868c` |
| build lock   | `22f8b5d1f0b8521e28470f6097717ff64c9cccc7b6037db7a5c25962e32a7ccb` |
| runtime lock | `cdab59f073ff510ff6d8b951d178381650236662b488c06b2d6436063f336aa0` |

The corrected launcher smoke returned Azure CLI `2.88.0` through the batch
contract. The launcher, campaign, topology, and infrastructure starting shards
passed 162 tests.

## Fresh generation and account boundary

- campaign correlation: `7d3af05024f9604f`;
- generation correlation: `e7fe6e05df20bfca`;
- retired campaign/generation reused: no;
- Azure cloud/state: AzureCloud / Enabled;
- subscription correlation: `1164c8c17745a1f5`;
- tenant correlation: `03b6af3c6cec9bc7`;
- generated target/cleanup group collisions before mutation: false / false;
- campaign/generation tagged resources before mutation: 0 / 0; and
- unrelated resources before mutation: 7.

Raw subscription, tenant, resource-group, identity, and ARM identifiers remain
excluded from tracked evidence. The ignored runtime generation was removed
after zero-residue finalization and sanitized evidence capture.

## Preflight and refreshed cost gate

The exact ordered operator phases `preflight`, `correlate`, `capacity-check`,
and `cost-gate` passed in dry-run and execution forms. They proved all six
required providers registered, PostgreSQL `Standard_D2ds_v5` available in
`centralus`, ZoneRedundant zones 1 and 2, sufficient regional quota, and both
global names available. Docker Scout `1.23.1` was installed and available for
the one authorized digest scan, but the scan phase was never reached.

The Azure Retail Prices API was refreshed at `2026-08-14T03:10:00Z`. Current
meters still supported the complete conservative envelope:

| Component                                        |         USD |
| ------------------------------------------------ | ----------: |
| PostgreSQL two-node compute                      |      1.6080 |
| PostgreSQL storage and backup                    |      0.0835 |
| Premium ACR and one bounded build                |      2.0266 |
| VPN and public IP reserve                        |      0.8600 |
| DNS resolver reserve                             |      0.9863 |
| Private endpoints and DNS                        |      0.0882 |
| Peering and Private Link processing              |      1.8000 |
| Log Analytics                                    |      5.5200 |
| Container Apps                                   |      3.4240 |
| Automation and Key Vault reserve                 |      0.1500 |
| Azure Monitor reserve                            |      2.0000 |
| One image-security evaluation reserve            |      2.0000 |
| Subtotal                                         |     20.5466 |
| Required 25 percent contingency                  |      5.1366 |
| **Conservative maximum**                         | **25.6832** |
| **Margin below the immutable USD 50.00 ceiling** | **24.3168** |

The price and cost gates passed. They are not managed database evidence.

## First invariant failure

The lifecycle reached `scope-created` and invoked exactly one cleanup
deployment. Azure returned nested deployment codes `DeploymentFailed`,
`ResourceDeploymentFailure`, and `BadRequest`; the terminal sanitized message
was: `Only one account is allowed for your subscription per Region. If Deleted
recently, please restore the same account`.

This is an unrelated regional subscription limit on Azure Automation. It is
not an authentication, provider-registration, quota, role-assignment, source,
or Windows launcher failure. The authorization prohibited redesign,
replacement generation, cleanup-region substitution, and automatic correction
after the first uncontained invariant. No retry was attempted.

## Image and managed-proof disposition

| Surface                                 | Result                             |
| --------------------------------------- | ---------------------------------- |
| Azure target resource generations       | 0                                  |
| image builds / immutable digests        | 0 / 0                              |
| admission scans                         | 0                                  |
| principal manifest deployment           | blocked before target deployment   |
| bootstrap and migration 0029            | blocked before target deployment   |
| effective role/catalog proof            | blocked; `M78-PG-E02` remains open |
| 89-connection capacity proof            | blocked; `M78-PG-E01` remains open |
| failover and credential recovery        | blocked; `M78-PG-E03` remains open |
| four ambiguous-commit replay operations | blocked; `M78-PG-E03` remains open |
| two-tenant isolation                    | blocked; `M78-TI-E01` remains open |
| managed topology/configuration readback | blocked; `M78-PG-E04` remains open |

No image provenance or scan result exists because the first-failure rule
stopped execution before ACR and image creation. No digest was admitted.

## Cleanup and cost

The operator transitioned directly from `scope-created` to `cleaning` at
`2026-08-14T03:11:16.846216Z`. Its exact-two-group fallback removed the empty
target boundary and the failed cleanup boundary. Cleanup completed at
`2026-08-14T03:12:46.235139Z`; residue was verified at
`2026-08-14T03:12:57.940932Z`; finalization completed at
`2026-08-14T03:12:58.224615Z`.

| Residue counter             | Value |
| --------------------------- | ----: |
| target resource groups      |     0 |
| cleanup resource groups     |     0 |
| role assignments            |     0 |
| Automation accounts         |     0 |
| cleanup schedules           |     0 |
| managed identities          |     0 |
| PostgreSQL servers          |     0 |
| container registries        |     0 |
| Container Apps environments |     0 |
| Container Apps jobs         |     0 |
| virtual networks            |     0 |
| private endpoints           |     0 |
| private DNS zones           |     0 |
| diagnostic settings         |     0 |
| synthetic rows              |     0 |

Campaign- and generation-tag inventories are zero, both generated groups are
absent, and unrelated resources remain 7 / 7. The first billable mutation is
null, billable elapsed time is 0 seconds, and the best available actual cost is
USD 0.00.

## Local validation

All commands below were run after zero-residue finalization and private-runtime
removal. The inherited 904-second monolithic command was not repeated.

| Command or shard                                                    | Exact result                                                                                                                              |
| ------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| launcher, campaign, topology, and infrastructure pytest shard       | exit 0; 162 passed; one existing Starlette deprecation warning                                                                            |
| legacy idempotency, canvas, and document pytest shard               | exit 0; 19 passed; one existing Starlette deprecation warning                                                                             |
| database-remediation pytest shard                                   | exit 0; 7 passed                                                                                                                          |
| migration-chain pytest shard                                        | exit 0; 12 passed; existing SQLite adapter warnings                                                                                       |
| database-runtime and PostgreSQL-runner pytest shard                 | exit 0; 23 passed, 2 skipped because no local PostgreSQL fixture was used                                                                 |
| authorization and collaboration pytest shard                        | exit 0; 5 passed                                                                                                                          |
| agent, graph, workflow, and tenant-authority pytest shard           | exit 0; 99 passed; existing SQLite adapter warnings                                                                                       |
| `python scripts/validate_migrations.py`                             | exit 0; upgrade 0029, downgrade 0028, re-upgrade 0029 passed                                                                              |
| `python -m alembic -c alembic.ini heads`                            | exit 0; sole `20260726_0029 (head)`                                                                                                       |
| strict mypy over five API campaign files                            | exit 0; no issues in 5 files                                                                                                              |
| strict mypy over five infrastructure campaign files                 | exit 0; no issues in 5 files                                                                                                              |
| Ruff check over the same ten files                                  | exit 0; all checks passed                                                                                                                 |
| Ruff format check over the same ten files                           | exit 1; five unchanged `infra/milestone_7_8` files at the starting HEAD would be reformatted; no prohibited source-format change was made |
| centralized local Bicep build of both entry points and four modules | six exit-0 results                                                                                                                        |
| targeted Prettier check over both changed Markdown files            | initial new-handoff-only finding corrected with targeted formatting; final exit 0                                                         |
| machine receipt plus seven campaign-schema JSON documents           | parsed; 8 documents                                                                                                                       |
| local links in the two changed Markdown files                       | passed; 5 links                                                                                                                           |
| repository hygiene and secret guard                                 | exit 0; passed for 632 source files                                                                                                       |
| tracked private-identifier guard                                    | exit 0; 1 passed                                                                                                                          |
| `git diff --check` / `git fsck --full --no-reflogs`                 | exit 0 / exit 0; no integrity error                                                                                                       |

Across the seven bounded pytest shards, 327 tests passed and two
PostgreSQL-fixture tests skipped. No managed PostgreSQL test is represented as
passing. The Ruff format-only finding is inherited unchanged from the frozen
source HEAD and is outside this evidence-only diff; the authorization forbids
source correction during execution.

## Preserved boundaries and next action

No production or infrastructure source, migration, dependency, lockfile,
production data, retained Milestone 7.7 evidence, protected stash, object
storage, object-upload scanner, soak, or remote Git surface changed. No
replacement campaign, generation, image, or scan was created.

The five managed PostgreSQL evidence gaps remain open. The next action is a
separately authorized correction or execution plan for the cleanup Automation
regional-account limit, followed by a separately authorized fresh campaign.
It is not the object-storage audit and not a GitHub push. Milestone 7.8 remains
incomplete.

## Later regional-capacity correction cross-reference

The repository defect identified by this historical execution was later
recorded as M78-PG-007 and corrected locally. Preparation now chooses from a
closed candidate order only after provider, enforced-policy, active-account,
and soft-deleted-account reads, and `capacity-check` repeats that proof before
scope creation. The selected region and sanitized evidence hashes are bound
immutably through the campaign lifecycle; there is still exactly one cleanup
deployment and no post-mutation region retry. See the
[regional-capacity remediation handoff](MILESTONE_7_8_AUTOMATION_REGIONAL_CAPACITY_REMEDIATION_HANDOFF.md).

This cross-reference does not alter the outcome, identifiers, timestamps,
cost, or zero-residue evidence above. A new campaign remains separately
authorized work; all five managed evidence gaps remain open.
