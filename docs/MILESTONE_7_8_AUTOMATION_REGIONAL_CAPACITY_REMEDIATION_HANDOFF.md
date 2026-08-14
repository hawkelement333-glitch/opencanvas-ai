# Milestone 7.8 Automation regional-capacity remediation handoff

Date: 2026-08-14

Status: M78-PG-007 corrected locally; fresh managed PostgreSQL campaign not
executed; all five managed evidence gaps remain open

## Outcome

The cleanup Automation regional-capacity defect proved by the latest fresh
campaign is corrected in repository state. The independent Automation cleanup
architecture remains intact, but its location is no longer a caller-supplied or
hard-coded `westus` default. One closed candidate order is evaluated with
sanitized read-only Azure evidence before a generation directory exists and is
revalidated before `scope-create`.

A candidate is armable only when the Automation provider reports it as a known
supported location, applicable enforced location policy allows it, and both
active and discoverable soft-deleted Automation account counts are zero. The
first viable candidate, candidate dispositions, observation time, and four
domain-separated evidence hashes are persisted in a closed receipt. Its own
hash and the selected region are immutable across configuration, private
runtime, restart ledger, both Bicep parameter bundles, lifecycle tags, command
plan, Bicep outputs, cleanup-account readback, target deployment binding, and
terminal receipt.

No campaign or generation identity was created. No Azure mutation, live
database operation, image build, image publication, scanner invocation,
object-storage audit, soak, cleanup lifecycle, dependency operation, or remote
Git operation occurred. Current campaign spend remains USD 0.00.

## Authoritative starting boundary

- branch: `milestone-7-8-production-readiness-audit-local`;
- starting HEAD: `186ecfa1bd3bfb5fa1204859e25fd4050b93baa5`;
- subject: `docs(evidence): record fresh 7.8 database campaign blocker`;
- upstream: absent;
- starting tree/index: clean;
- protected stashes: exactly five, in unchanged order:
  - `9196c8d9f68c1af6251530f349fdf72638b57b82`;
  - `58ffed44184ea3450a80f5883681da988a196ae7`;
  - `d50c7020f9b9ce6add83f10d0b443510ccd33ba3`;
  - `9ea4ef5a89bf6d6b62cd7718180c893bf6b87604`;
  - `71b384404468fbfa6326a951ef063e99c9e11652`;
- Alembic sole head: `20260726_0029`; migration `0030`: absent;
- `.runtime/milestone_7_8`: absent;
- current task resource/image/scan generations: 0 / 0 / 0;
- current task billable mutations and spend: 0 / USD 0.00;
- seven unrelated Azure resources and zero campaign residue at entry;
- retired campaign/generation correlations retained only as evidence:
  `3939e43a719d9410` / `1e750d27c68233b3` and
  `7d3af05024f9604f` / `e7fe6e05df20bfca`; and
- object-storage audit: unstarted.

The immutable canonical API image hashes remained:

| Input        | SHA-256                                                            |
| ------------ | ------------------------------------------------------------------ |
| build input  | `533dc8d9a64f2d4b1a8a10d5ac769b11e1bc962741a7637da44c037e34c4dad7` |
| Dockerfile   | `1f914420f661e40bcc8e61d149115387042fd3948323b645b9a204390c90a82b` |
| API project  | `b826c6e415e5c836cda5c74696d69b61f517a86556b2fecb82201ca35540868c` |
| build lock   | `22f8b5d1f0b8521e28470f6097717ff64c9cccc7b6037db7a5c25962e32a7ccb` |
| runtime lock | `cdab59f073ff510ff6d8b951d178381650236662b488c06b2d6436063f336aa0` |

## Root cause and proved defect

`prepare.py` accepted `--cleanup-region` with default `westus`, copied it
directly to campaign configuration and cleanup Bicep parameters, and created no
regional-capacity evidence. `operator.py` checked only that
`Microsoft.Automation` was registered. It did not inspect the
`automationAccounts` resource type's supported locations, active regional
occupancy, soft-deleted occupancy, or applicable location policy before
`scope-create`.

The fresh campaign therefore reached one cleanup deployment with an unchecked
location. Azure rejected the Automation account because regional subscription
capacity was unavailable. The controller never armed; the exact-two-group
direct fallback restored zero residue. This was a repository defect rather
than authentication, provider registration, PostgreSQL, launcher, or cleanup
fallback failure and is recorded as M78-PG-007.

## Sanitized Azure evidence

Every command below executed through
`python -m infra.milestone_7_8.azure_cli`; raw subscription, tenant, policy,
resource, account, and ARM identifiers remained in process memory and were not
printed or tracked.

| Observation                                        | Result                                                        |
| -------------------------------------------------- | ------------------------------------------------------------- |
| cloud / account state                              | AzureCloud / Enabled                                          |
| Automation provider-supported locations            | 47                                                            |
| active Automation accounts                         | 0                                                             |
| discoverable soft-deleted Automation accounts      | 4                                                             |
| soft-deleted normalized locations                  | `eastus2`, `westus`, `eastus`, `northeurope`                  |
| enforced policy assignments                        | 1                                                             |
| policy definitions evaluated by the selector       | 57                                                            |
| candidate-denying enforced location policies       | 0                                                             |
| `eastus2` / `westus`                               | occupied by soft-deleted state                                |
| `southcentralus` / `westus2`                       | supported, policy-allowed, zero active/soft-deleted occupancy |
| deterministic selected location                    | `southcentralus`                                              |
| unrelated subscription resources                   | 7, unchanged                                                  |
| Milestone 7.8 tagged resources / `rg-m78-*` groups | 0 / 0                                                         |
| Azure mutations / campaign IDs / generation IDs    | 0 / 0 / 0                                                     |

The provider exposes the deleted-account collection but no reliable exact
regional Automation quota in this repository contract. The armable rule is
therefore deliberately conservative: provider support plus policy allowance
plus zero active and zero discoverable soft-deleted occupancy. This does not
claim reservation of future capacity.

## Candidate and failure contract

The exact candidate order is:

1. `eastus2`;
2. `southcentralus`;
3. `westus2`; and
4. `westus`.

Azure order, spacing, and case are normalized; caller override, duplicate
candidate, malformed location, unknown observed location, unregistered or
incomplete provider data, incomplete active/deleted inventory, unknown policy
binding, and an unevaluable deny-location rule fail closed. Failures are
machine-classified as:

- `automation-region-unsupported`;
- `automation-region-policy-disallowed`;
- `automation-region-occupied-capacity-unproved`;
- `automation-region-malformed-unknown`; or
- `automation-region-discovery-failed`.

There is no hard-coded fallback. If no candidate is viable, preparation creates
no output directory or ledger. `capacity-check` repeats the full read-only
contract and requires the same prepared location to remain the deterministic
first viable choice before scope creation.

## Immutable dataflow and no-hop behavior

| Surface                              | Bound value                                                                             |
| ------------------------------------ | --------------------------------------------------------------------------------------- |
| selection receipt                    | order, selected region, four candidate dispositions, counts, time, four evidence hashes |
| campaign configuration               | `cleanupRegion`, selection receipt SHA-256                                              |
| private runtime                      | region, receipt path, receipt SHA-256                                                   |
| restart ledger                       | region and receipt SHA-256 from `new` onward                                            |
| cleanup and target parameter bundles | region and receipt SHA-256                                                              |
| lifecycle tags                       | receipt SHA-256                                                                         |
| cleanup Bicep/controller outputs     | region and receipt SHA-256                                                              |
| cleanup readback                     | account location, deployment location, receipt SHA-256                                  |
| target deployment `campaignBinding`  | region and receipt SHA-256                                                              |
| terminal receipt                     | region and receipt SHA-256                                                              |

The static operator plan now contains 55 commands, including 49 Azure CLI
commands. `capacity-check` contains 15 Azure commands, five of which provide
the regional base discovery. Enforced assignment and deny-capable initiative
policy definitions are generated GETs. Container Apps polling, failure
cleanup, and exact-two-group direct cleanup remain generated paths through the
central launcher.

`cleanup-deploy` still produces exactly one deployment command in the prepared
region. No selector exists in or after a mutation phase. Failure starts the
existing runbook path when available, otherwise direct cleanup deletes only the
validated target and cleanup groups. It never hops regions, retries a cleanup
deployment, restores or reuses a soft-deleted Automation account, or names,
modifies, or deletes an unrelated account.

## Implementation and regression scope

The focused production change adds `infra/milestone_7_8/automation_region.py`
and updates campaign preparation, validation, lifecycle state, operator command
planning/readback, the cleanup and target Bicep parameter flow, three existing
schemas, and one new closed selection schema. It does not change PostgreSQL
topology, principal roles, runtime table grants, managed evidence probes,
durable idempotency, migration `0029`, image inputs, cost limits, or the
exact-scope cleanup script.

Synthetic regression coverage proves:

- occupied `westus` rejection and deterministic alternate selection;
- provider-order/case stability;
- supported, policy-allowed, zero-occupancy selection;
- duplicate, malformed, unknown, unsupported, policy-disallowed, occupied,
  capacity-unproved, and discovery-failure behavior;
- active and soft-deleted occupancy handling;
- immutable config/runtime/ledger/parameter/Bicep/readback/receipt bindings;
- substitution rejection after the ledger becomes armable;
- exactly one cleanup deployment and no post-mutation retry or region hop;
- exact-two-group direct cleanup and absence of unrelated account targets;
- no raw resource, account, subscription, or ARM identifier in the receipt;
  and
- unchanged native and Windows batch launcher behavior.

## Validation ledger

| Validation                   | Exact bounded invocation or scope                                                                             | Result                                                                                                |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| sanitized live selector      | `discover_automation_region(SubprocessRunner(), active_subscription)`; identifier held only in process memory | exit 0; `southcentralus`; 1 assignment / 57 definitions; `eastus2` and `westus` occupied; no mutation |
| regional contract            | `pytest ... test_milestone_7_8_automation_region.py`                                                          | exit 0; 21 passed                                                                                     |
| Azure CLI launcher           | `pytest ... test_milestone_7_8_azure_cli_launcher.py`                                                         | exit 0; 13 passed                                                                                     |
| campaign enablement          | `pytest ... test_milestone_7_8_campaign_enablement.py`                                                        | exit 0; 46 passed                                                                                     |
| runtime topology             | `pytest ... test_milestone_7_7_runtime_topology.py`                                                           | exit 0; 9 passed, 1 inherited Starlette deprecation warning                                           |
| infrastructure contracts     | `pytest ... test_milestone_7_7_infrastructure_contracts.py`                                                   | exit 0; 94 passed                                                                                     |
| database remediation         | `pytest ... test_milestone_7_8_database_remediation.py`                                                       | exit 0; 7 passed                                                                                      |
| private-identifier guard     | exact infrastructure-contract node                                                                            | exit 0; 1 passed                                                                                      |
| Ruff                         | `ruff check` and `ruff format --check` on the seven changed Python files                                      | exit 0; all passed / 7 formatted                                                                      |
| strict Mypy                  | `mypy --strict --explicit-package-bases` on four production files, then the regional test                     | exit 0; 4 + 1 files clean                                                                             |
| Prettier                     | installed `apps/web/node_modules/.bin/prettier.CMD --check` on seven Markdown and four JSON files             | exit 0; 11 files matched                                                                              |
| Bicep                        | centralized launcher `bicep build --file ... --stdout` for six Milestone 7.8 files                            | six exits 0                                                                                           |
| schema syntax                | PowerShell `ConvertFrom-Json -Depth 100` for every Milestone 7.8 schema                                       | exit 0; 8 parsed                                                                                      |
| cleanup script syntax        | PowerShell AST parser on `Remove-M78Campaign.ps1`                                                             | exit 0; 0 errors                                                                                      |
| migrations                   | `python scripts/validate_migrations.py`; `alembic heads` from `apps/api`; migration `0030` inventory          | exit 0; 0029 -> 0028 -> 0029; sole head `20260726_0029`; 0030 count 0                                 |
| Markdown links               | bounded relative-link resolver over seven changed Markdown files                                              | exit 0; 12 local links, 0 missing                                                                     |
| repository hygiene           | `python scripts/check_repository_hygiene.py`                                                                  | exit 0; 636 source files                                                                              |
| canonical API inputs         | `python -m infra.milestone_7_8.canonical_inputs --treeish HEAD`                                               | exit 0; all five retained hashes exact                                                                |
| retained Milestone 7.7 scope | `git diff --name-only -- docs/MILESTONE_7_7* evidence infra/milestone_7_7`                                    | exit 0; 0 files                                                                                       |

Corrected invocation-only failures were not hidden: an absent
`apps/api/.venv` path and absent root Prettier shim performed no work; the
managed `pnpm exec` probe stopped on `ERR_PNPM_IGNORED_BUILDS`; its generated
`pnpm-workspace.yaml` policy rewrite was detected and surgically removed, and
no dependency or lockfile changed. Mypy required `--explicit-package-bases`; Alembic
`heads` required the `apps/api` working directory; and neither installed Python
runtime includes `jsonschema`, so no package was added and the eight schemas
received syntax parsing plus contract-test coverage rather than an external
schema-engine pass. A selector attempt without `M78_SUBSCRIPTION_ID` stopped
before Azure; the successful retry derived the active subscription only in
memory through the centralized read-only launcher.

No local PostgreSQL server was required or started by this regional
infrastructure correction.

## Residual boundary and next action

M78-PG-007 is resolved only in repository state. A provider can still consume
regional capacity after preflight and before deployment; the one-deployment,
first-failure, exact-cleanup contract remains the safe response. No local test
or read-only observation is represented as managed PostgreSQL evidence.

M78-PG-E01, M78-PG-E02, M78-PG-E03, M78-TI-E01, and M78-PG-E04 remain open.
Milestone 7.8 remains incomplete. The next action is a separately reviewed and
authorized fresh managed PostgreSQL evidence campaign from the final clean
commit. It is not a GitHub push and not the object-storage audit.

## Later campaign execution cross-reference

The separately authorized fresh campaign from the final clean commit later
proved that this correction was necessary but incomplete. Preparation and the
repeated `capacity-check` selected `southcentralus` consistently, but Azure
rejected the one cleanup-controller deployment because Free Trial and Student
subscriptions cannot create Automation accounts in that location. The
subscription-offer allowed-region set was not represented by provider support,
Azure Policy, active occupancy, or soft-deleted occupancy.

That later result is M78-PG-008, not a rewrite of M78-PG-007's original
evidence. The campaign stopped at its first failed invariant and completed
direct zero-residue cleanup without a region hop, retry, image, target
generation, database, or managed proof. See the
[corrected regional-capacity campaign execution handoff](MILESTONE_7_8_MANAGED_POSTGRESQL_CORRECTED_REGIONAL_CAPACITY_CAMPAIGN_EXECUTION_HANDOFF.md).
