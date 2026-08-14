# Milestone 7.8 critical cleanup and retention remediation handoff

Date: 2026-08-14

Status: repository-local remediation complete; exact provider-retained
Automation-account residue remains nonzero; campaign armability blocked

## Scope and authoritative boundary

This work addressed only M78-PG-010 and M78-PG-011. It did not run a campaign,
create a generation, deploy cleanup or target resources, build or scan an image,
connect to PostgreSQL, start object-storage work, execute a soak, change a
dependency, or perform remote Git operations.

The starting repository boundary was:

- branch `milestone-7-8-production-readiness-audit-local`;
- HEAD `db2bafcb59342fbb38543b47461e629ad43f6c89`;
- no upstream and a clean tracked tree/index;
- exactly five protected stashes with inventory hash
  `cd85493086a145dee173ae333ad7d483bc7cb54df011266bdeb010e1d3df276e`;
- sole Alembic head `20260726_0029`, with no migration 0030; and
- unchanged canonical image inputs.

Seven ignored private runtime files were read and preserved. Their pre-change
SHA-256 values were:

| Private file                    | SHA-256                                                            |
| ------------------------------- | ------------------------------------------------------------------ |
| `blocked-cleanup-evidence.json` | `0b69fdcdd2c61e7935eeaf46648528e9f242a1f8b19db600f80b014f3d3645fa` |
| `campaign.json`                 | `f3742baf9c13336b4efb250266c603ab4493bcd29e10aa0dfa2f378442a95c8a` |
| `campaign.parameters.json`      | `8919ba298f9f494909ace885834144b1c7e658b123e33fdd84a93249ee19437d` |
| `cleanup-region-selection.json` | `2b39c8ec2f8bc100ee8b415d4d59b4b0f23c4392cd4ab06ff7a2332ed118d6f1` |
| `cleanup.parameters.json`       | `deef017c41c244c8924a45f2a21ffbf21ae0569ed1754cc4284408696b35f07b` |
| `ledger.json`                   | `6711846fd93dca15069dd3aebe08a9885c9accdea0ed3a8ff832a63d19efa29e` |
| `runtime.json`                  | `34f82cfb966a5b94f87fe0597419d05712878ba475c385b4d6e5134cdf6346f2` |

The private values remain ignored. No raw subscription, tenant, account,
object, principal, or developer-home identifier appears in tracked evidence.
The preserved ledger uses the disproved legacy 15-counter model and records the
historical `finalized` state. It remains immutable evidence, not resumable v4
state; the current operator rejects that old contract rather than silently
upgrading or re-finalizing it.

## Exact attribution and provider disposition

The campaign and generation correlations are `07e350df451c6bec` and
`599df8555c0781d9`; the bound cleanup region is `southeastasia`. Complete
one-page active and deleted inventories proved:

- zero active Automation accounts;
- five total soft-deleted Automation accounts;
- exactly one record matching the generated campaign account identity, region,
  expected account-resource binding, and preserved lifecycle evidence; and
- four unrelated deleted-account identity hashes unchanged.

The campaign account identity hash is
`9ddbb427b37f677c6c2fe9b649278e1aedf9e6e00a250cfe7c24df0df475ce4d`.
The unrelated identity hashes are recorded in the sanitized receipt, not as
cleanup targets.

Microsoft documents restoration during retention and states that an Automation
account is permanently removed 30 days after user deletion in
[Automation account management](https://learn.microsoft.com/en-us/azure/automation/delete-account)
and [Automation data security and retention](https://learn.microsoft.com/en-ca/azure/automation/automation-managing-data).
The current REST contract documents only
[deleted-account listing](https://learn.microsoft.com/en-us/rest/api/automation/deleted-automation-accounts/list-by-subscription?view=rest-automation-2024-10-23),
and live provider metadata exposed only
`Microsoft.Automation/deletedAutomationAccounts/read` among 135 Automation
operations. No documented permanent-delete operation exists, so no endpoint
was guessed and no Azure mutation occurred.

The provider deletion evidence is `2026-08-14T20:09:46Z`. Adding the documented
30-day period gives `2026-09-13T20:09:46Z` as the earliest expected provider
removal boundary. That date is an expectation, not absence proof. The private
runtime must remain preserved until independent, complete readback proves the
account absent. The single prior cost query returned HTTP 429 and was not
retried; actual cost therefore remains unavailable, not USD 0.00.

## Residue before and after reconciliation

The corrected 16-counter model produces the same truthful before/after state
because no Azure mutation was supported:

| Counter                         | Before | After |
| ------------------------------- | -----: | ----: |
| `targetResourceGroups`          |      0 |     0 |
| `cleanupResourceGroups`         |      0 |     0 |
| `roleAssignments`               |      0 |     0 |
| `automationAccounts`            |      0 |     0 |
| `softDeletedAutomationAccounts` |      1 |     1 |
| `cleanupSchedules`              |      0 |     0 |
| `managedIdentities`             |      0 |     0 |
| `postgresServers`               |      0 |     0 |
| `containerRegistries`           |      0 |     0 |
| `containerAppsEnvironments`     |      0 |     0 |
| `containerAppsJobs`             |      0 |     0 |
| `virtualNetworks`               |      0 |     0 |
| `privateEndpoints`              |      0 |     0 |
| `privateDnsZones`               |      0 |     0 |
| `diagnosticSettings`            |      0 |     0 |
| `syntheticRows`                 |      0 |     0 |

Disposition is `provider-retained`, not `zero-residue`. Finalization must fail
closed until a later pagination-complete active/deleted readback proves all 16
counters zero.

## M78-PG-010 publication and arming correction

The original Bicep created the draft runbook, schedule, and job-schedule binding
in one deployment. An ARM dependency could prove resource creation but not an
Automation publication operation. The corrected lifecycle is:

1. deploy the account, draft runbook, and exact two-scope RBAC with zero
   schedules and zero bindings;
2. read back deployment, system identity, and exactly two expected assignments
   on each generated resource-group scope;
3. replace content and publish the runbook;
4. require the exact runbook name, `Published` state, publication timestamp,
   and expected content hash;
5. PUT and GET the deterministic one-time schedule at the immutable deadline;
6. PUT the deterministic job-schedule binding only after schedule proof;
7. list and require exactly one expected binding with exact parameters; and
8. hash the complete proof and only then allow the ledger to transition to
   `cleanup-armed`.

All writes are deterministic and repeatable. Publication failure, draft/stale
readback, content mismatch, schedule drift, missing/duplicate binding, authority
drift, or proof substitution stops before the next mutation and cannot record
the armed phase. The schedule and job-schedule operations use the documented
[schedule](https://learn.microsoft.com/en-us/rest/api/automation/schedule/create-or-update?view=rest-automation-2024-10-23),
[runbook publication](https://learn.microsoft.com/en-us/rest/api/automation/runbook/publish?view=rest-automation-2024-10-23),
and [job-schedule](https://learn.microsoft.com/en-us/rest/api/automation/job-schedule/create?view=rest-automation-2024-10-23)
contracts rather than the unavailable Windows CLI extension command.

## M78-PG-011 cleanup and finalization correction

`residue` now reads six independent surfaces: both generated group-existence
flags, tagged resources, scoped role assignments, all active Automation
accounts, and all soft-deleted Automation accounts. Both account collections
follow provider `nextLink` values to completion with a 100-page safety bound.
Malformed pages, unsafe/repeated next links, malformed identities, ambiguous
name/region matches, duplicate campaign matches, unmodeled tagged resources, or
inventory disagreement fail closed.

The expected account is selected only through its domain-separated resource-ID
binding plus generated name and region. Unrelated deleted accounts are hashed
for preservation proof and are never targets. A matching soft-deleted account
sets `softDeletedAutomationAccounts=1`, persists a residue evidence hash and
`provider-retained` disposition, leaves the lifecycle at `cleaned`, emits a
blocked operator result, and prevents the v4 terminal receipt. The direct
cleanup fallback still targets only the two generated groups and now reports
complete active/deleted account counts immediately after starting deletion.

## Cleanup-controller architecture

No locally proved replacement satisfied all required properties at once:
survival of operator interruption, immutable four-hour enforcement, exact
two-group and campaign-RBAC deletion, no unrelated shared resource, least
privilege, and no provider-retained artifact. Choosing Logic Apps, Container
Apps, Functions, or another service without a deployed authoritative contract
would be a redesign, not evidence.

The Automation implementation is retained with M78-PG-010 fixed, but every new
runtime is marked `blocked-provider-retention`. Executable campaign phases from
`scope-create` through disposition reject that runtime before mutation. The
repository no longer labels this controller or campaign ready.

## Evidence gaps and next action

M78-PG-E01, M78-PG-E02, M78-PG-E03, M78-TI-E01, and M78-PG-E04 all remain open.
No managed PostgreSQL result was generated or reclassified. The bounded next
action is provider removal or quota relief for the exact retained account,
followed by a separately authorized, complete read-only active/deleted
inventory reconciliation against the sanitized receipt. That reconciliation
is not a resume of the frozen legacy ledger and cannot create a campaign. The
sanitized
[support-request draft](MILESTONE_7_8_AZURE_AUTOMATION_RETENTION_SUPPORT_REQUEST_DRAFT.md)
is prepared but not submitted. A new campaign is not authorized and cannot be
armed by the current repository. The object-storage audit remains unstarted,
and Milestone 7.8 remains incomplete.

## Validation ledger

All commands ran from the repository root unless the command says otherwise.
`PYTHONDONTWRITEBYTECODE=1` and pytest's `-p no:cacheprovider` prevented test
residue.

| Validation command                                                                                                                                                                                                                                                                                                | Exact result                                                                                                                                                                                                    |
| ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider apps/api/tests -q -k milestone_7_8`                                                                                                                                                                                                                     | exit 0; 116 passed, 0 failed, 0 skipped; one pre-existing Starlette/httpx deprecation warning                                                                                                                   |
| `.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider -q apps/api/tests/test_milestone_7_7_runtime_topology.py apps/api/tests/test_milestone_7_8_database_remediation.py apps/api/tests/test_database_runtime.py apps/api/tests/test_migration_runtime.py apps/api/tests/test_legacy_creation_idempotency.py` | exit 0; 53 passed, 0 failed, 0 skipped; the same warning                                                                                                                                                        |
| `.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider -q apps/api/tests/test_milestone_7_7_infrastructure_contracts.py`                                                                                                                                                                                       | exit 0; 94 passed, 0 failed, 0 skipped                                                                                                                                                                          |
| `.\.venv\Scripts\python.exe -m ruff check --config apps/api/pyproject.toml <five affected Python files>` and `ruff format --check` over the same files                                                                                                                                                            | exit 0; lint clean and 5 files formatted                                                                                                                                                                        |
| `.\.venv\Scripts\python.exe -m mypy --strict --explicit-package-bases infra/milestone_7_8/campaign.py infra/milestone_7_8/operator.py infra/milestone_7_8/prepare.py`                                                                                                                                             | exit 0; no issues in 3 source files                                                                                                                                                                             |
| centralized local Azure CLI launcher, `bicep build --stdout`, for `cleanup.bicep` and `modules/cleanup-controller.bicep`                                                                                                                                                                                          | exit 0; both templates compiled with no diagnostics                                                                                                                                                             |
| PowerShell AST parse of `Remove-M78Campaign.ps1` and `ConvertFrom-Json` over the three changed schemas plus the sanitized receipt                                                                                                                                                                                 | exit 0; 1 script and 4 JSON documents parsed                                                                                                                                                                    |
| already-installed Prettier 3.9.5 binary, `--check`, over the five changed Markdown files, three schemas, and sanitized receipt                                                                                                                                                                                    | exit 0; all 9 files matched                                                                                                                                                                                     |
| bounded Markdown H1/heading-order and relative-link resolver over the five changed Markdown files                                                                                                                                                                                                                 | exit 0; 5 documents and 12 local links passed                                                                                                                                                                   |
| `.\.venv\Scripts\python.exe scripts/check_repository_hygiene.py`                                                                                                                                                                                                                                                  | exit 0; 644 source files passed, including private-material guards                                                                                                                                              |
| `.\.venv\Scripts\python.exe scripts/validate_migrations.py`                                                                                                                                                                                                                                                       | exit 0; upgrade 0029, downgrade 0028, re-upgrade 0029                                                                                                                                                           |
| from `apps/api`, `..\..\.venv\Scripts\python.exe -m alembic -c alembic.ini heads` plus an exact 0030 filename count                                                                                                                                                                                               | exit 0; sole head `20260726_0029`; 0030 count 0                                                                                                                                                                 |
| `.\.venv\Scripts\python.exe -m infra.milestone_7_8.canonical_inputs --treeish HEAD`                                                                                                                                                                                                                               | exit 0; build input `533dc8d9a64f2d4b1a8a10d5ac769b11e1bc962741a7637da44c037e34c4dad7`, Dockerfile `1f914420f661e40bcc8e61d149115387042fd3948323b645b9a204390c90a82b`, and all three dependency hashes retained |

Corrected validation findings were not hidden. The first lint pass found one
import-order issue and one unused local; both were corrected and the final pass
is above. The managed `pnpm exec` wrapper exited 1 with
`ERR_PNPM_IGNORED_BUILDS` before Prettier ran and injected an out-of-scope
`allowBuilds` placeholder into `pnpm-workspace.yaml`; those three lines were
removed immediately, no lockfile changed, and the already-installed Prettier
binary then passed. Two Alembic head attempts from the repository root exited
nonzero because the script location is relative to `apps/api`; the corrected
working-directory command above passed. Final Git, runtime-hash, residue, and
stash checks are recorded after the intentional local commit.
