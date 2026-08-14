# Milestone 7.8 managed PostgreSQL campaign execution handoff

Date: 2026-08-13

Status: blocked in committed operator preflight; zero Azure mutation and zero
campaign residue

Terminal disposition:
`MILESTONE_7_8_MANAGED_POSTGRESQL_EVIDENCE_CAMPAIGN_BLOCKED_CLEANUP_COMPLETE`

## Outcome

The independently authorized managed PostgreSQL evidence campaign stopped at
the first uncontained invariant, before any Azure mutation. The committed
operator uses Python `subprocess.run` with the executable name `az`. On this
Windows operator host, Azure CLI is installed only through `az.cmd` and batch
launchers; no native `az.exe` exists. The exact committed `preflight --execute`
phase therefore returned `FileNotFoundError` with Windows error 2 before a
ledger file or lifecycle transition was created.

Authentication was valid and read-only Azure CLI commands run from PowerShell
proved an enabled AzureCloud account. The failure is not an authentication,
subscription, tenant, or permission failure. A direct subprocess control
resolved `git`, while the same process could not resolve `az`. No source,
infrastructure, lifecycle, or command substitution was attempted because this
authorization forbids production-source changes and bypassing the committed
lifecycle.

The campaign resource and cleanup groups were never created. Mandatory
read-only cleanup verification proved every campaign residue counter zero and
the unrelated subscription resource count unchanged at seven. The billable
clock never started, the best available actual cost is USD 0.00, no image was
built or scanned, and none of the five managed evidence gaps is closed.

The sanitized machine-readable receipt is
[`managed-postgresql-campaign-execution.json`](../evidence/milestone_7_8/managed-postgresql-campaign-execution.json).

## Starting boundary

- branch: `milestone-7-8-production-readiness-audit-local`;
- starting HEAD: `e683ab00626fac9a1ac5a483ed4107e4ae47c60f`;
- subject: `feat(infra): enable independent 7.8 database campaign`;
- upstream: absent;
- starting tree/index: clean;
- protected stashes: exactly five and unchanged;
- Alembic sole head: `20260726_0029`;
- migration `0030`: absent;
- existing campaign resource/image generations: 0 / 0;
- existing campaign spend: USD 0.00;
- campaign/topology contracts: 55 passed;
- infrastructure contracts: 94 passed; and
- repository hygiene: passed for 625 source files.

The frozen canonical Git-tree boundary matched exactly:

- build-input SHA-256:
  `533dc8d9a64f2d4b1a8a10d5ac769b11e1bc962741a7637da44c037e34c4dad7`;
- Dockerfile SHA-256:
  `1f914420f661e40bcc8e61d149115387042fd3948323b645b9a204390c90a82b`;
- API project SHA-256:
  `b826c6e415e5c836cda5c74696d69b61f517a86556b2fecb82201ca35540868c`;
- build-lock SHA-256:
  `22f8b5d1f0b8521e28470f6097717ff64c9cccc7b6037db7a5c25962e32a7ccb`;
  and
- runtime-lock SHA-256:
  `cdab59f073ff510ff6d8b951d178381650236662b488c06b2d6436063f336aa0`.

## Prepared generation and sanitized Azure correlation

Exactly one ignored local campaign bundle was prepared from the starting HEAD.
Its campaign and immutable generation are retained only as domain-separated
correlations:

- campaign correlation: `3939e43a719d9410`;
- generation correlation: `1e750d27c68233b3`;
- active account: enabled in AzureCloud;
- both derived campaign resource-group names: absent before and after the
  attempt;
- resources carrying the campaign tag: 0;
- resources carrying the generation tag: 0; and
- unrelated subscription resources: 7 before / 7 after.

Raw subscription and tenant UUIDs, complete ARM IDs, resource-group names, and
the ignored runtime bundle are not retained in tracked evidence.

## Exact blocker

The dry run completed and rendered the exact seven-command local preflight.
The execution form failed before result validation:

```text
.\.venv\Scripts\python.exe -m infra.milestone_7_8.operator preflight \
  --config .runtime\milestone_7_8\campaign.json \
  --runtime .runtime\milestone_7_8\runtime.json \
  --ledger .runtime\milestone_7_8\ledger.json --execute
exit 2: {"error":"[WinError 2] The system cannot find the file specified","status":"blocked"}
```

Independent no-mutation subprocess proof produced:

```json
{
  "azError": "FileNotFoundError:2",
  "azExecutable": false,
  "gitExecutable": true
}
```

Installed Azure CLI launchers were command or batch wrappers; no native
`az.exe` was present. Because the operator invokes `az` directly with
`shell=False`, the Windows process API could not start the CLI. The ledger was
not created and remained before `preflight`; `correlate`, `capacity-check`,
`cost-gate`, scope creation, cleanup deployment, and every later phase were not
executed.

A separately authorized correction must make the committed command runner
resolve the installed Azure CLI safely on Windows, with focused tests proving
unchanged argument boundaries and automatic cleanup behavior. Alternatively,
a separately reviewed operator platform containing a native executable named
`az` may be authorized. This campaign generation must not be reused after such
a source correction because its source HEAD binding would differ.

## Cost and image disposition

| Item                                | Result                                  |
| ----------------------------------- | --------------------------------------- |
| Authorized hard ceiling             | USD 50.00                               |
| Committed conservative maximum      | USD 25.6832 with 25 percent contingency |
| Cost gate reached                   | No; preflight failed first              |
| First billable mutation             | None                                    |
| Billable elapsed time               | 0 seconds                               |
| Best available actual campaign cost | USD 0.00                                |
| Resource generations                | 0                                       |
| Image builds / immutable digests    | 0 / 0                                   |
| Admission scans                     | 0                                       |
| Image source binding                | starting HEAD and frozen hashes above   |
| Digest or scan result               | absent; the image phase was not run     |

The repository contains a digest-bound admission receipt validator but no
Milestone 7.8 scanner executable, and neither Trivy nor Grype was installed on
the operator host. Under the first-failure rule, no later image-path action was
attempted and this observation is not represented as a managed scan result.

## Managed proof disposition

| Proof surface                                    | Disposition                                |
| ------------------------------------------------ | ------------------------------------------ |
| Principal object-ID bindings and catalog grants  | blocked before deployment; M78-PG-E02 open |
| API/worker prohibited operations                 | blocked before deployment; M78-PG-E02 open |
| Migration ownership, locking, and revision       | blocked before deployment; M78-PG-E02 open |
| 89-connection capacity and positive reserve      | blocked before deployment; M78-PG-E01 open |
| Forced failover and credential recovery          | blocked before deployment; M78-PG-E03 open |
| Four durable ambiguous-commit replay operations  | blocked before deployment; M78-PG-E03 open |
| Two-tenant pool-reuse/failover isolation         | blocked before deployment; M78-TI-E01 open |
| Live zone, maintenance, storage, backup, latency | blocked before deployment; M78-PG-E04 open |

M78-PG-002, M78-PG-003, M78-PG-004, M78-PG-005, and
M78-TI-001 remain locally remediated. This execution attempt neither reopens
them nor supplies their required managed proof.

## Cleanup and residue

No cleanup mutation was necessary because scope creation never ran. Read-only
Azure verification after the blocker proved:

| Residue counter                    | Value |
| ---------------------------------- | ----: |
| Target resource groups             |     0 |
| Cleanup resource groups            |     0 |
| Campaign role assignments          |     0 |
| Automation accounts / schedules    | 0 / 0 |
| Managed identities                 |     0 |
| PostgreSQL servers                 |     0 |
| Container registries               |     0 |
| Container Apps environments / jobs | 0 / 0 |
| Virtual networks                   |     0 |
| Private endpoints / DNS zones      | 0 / 0 |
| Diagnostic settings                |     0 |
| Synthetic application rows         |     0 |

Campaign-tag and generation-tag inventories were both empty, exact campaign
scope role assignments were absent, and the unrelated subscription resource
count remained 7 / 7.

## Validation ledger

| Command or check                                                  | Exact result                                               |
| ----------------------------------------------------------------- | ---------------------------------------------------------- |
| Repository branch, HEAD, upstream, status, stashes                | passed                                                     |
| `python -m infra.milestone_7_8.canonical_inputs --treeish HEAD`   | exit 0; all five frozen hashes matched                     |
| `python -m alembic -c alembic.ini heads`                          | exit 0; `20260726_0029 (head)`                             |
| migration `0030` inventory                                        | absent                                                     |
| campaign-enablement plus runtime-topology test shard              | exit 0; 55 passed                                          |
| infrastructure-contract shard                                     | exit 0; 94 passed                                          |
| legacy idempotency/canvas/document/remediation shard              | exit 0; 26 passed                                          |
| database runtime/migration/topology shard                         | exit 0; 40 passed, 2 PostgreSQL-fixture skips              |
| authorization/collaboration/graph/workflow shard                  | exit 0; 35 passed                                          |
| `python scripts/validate_migrations.py`                           | exit 0; upgrade 0029, downgrade 0028, re-upgrade 0029      |
| Ruff check plus targeted format check                             | exit 0; 9 production files                                 |
| strict mypy, split at the package boundary                        | exit 0; 5 API files plus 4 campaign files                  |
| six `az bicep build --stdout` commands                            | six exit-0 results                                         |
| targeted Prettier, JSON parse, and four-file local-link check     | exit 0; passed                                             |
| `python scripts/check_repository_hygiene.py`                      | initial 625 files; final 627 files; both exit 0            |
| private-identifier and secret-diff guards                         | exit 0; passed                                             |
| `git diff --check` / `git fsck --full --no-reflogs`               | exit 0 / exit 0; dangling objects only, no integrity error |
| ignored runtime-directory preflight                               | absent before preparation                                  |
| Azure account state                                               | exit 0; enabled AzureCloud account                         |
| derived-group and campaign/generation collision readback          | exit 0; all zero / absent                                  |
| operator `preflight` dry run                                      | exit 0; mutation authorization false                       |
| operator `preflight --execute`                                    | exit 2; `WinError 2` before ledger creation                |
| direct Python subprocess control                                  | Git resolved; Azure CLI launcher did not                   |
| post-blocker resource, role, tag, and unrelated-resource readback | exit 0; zero campaign residue; 7 / 7 unrelated resources   |

The operator did not reach the committed cost, provider, quota, SKU, name,
cleanup-controller, target-deployment, image, managed-evidence, failover, or
control-plane phases. They are not reported as passing.

Two nonfinal strict-mypy command shapes were rejected before the correct split
run: the first was launched from `apps/api` while also naming repository-level
`infra` files and returned four import/path errors; the second named all nine
files from the repository root without `--explicit-package-bases` and returned
one duplicate-module error. Running the five API files from `apps/api` and the
four campaign files from the repository root with
`--explicit-package-bases` produced two clean exit-0 results. The first
Prettier check also identified only the newly created handoff; targeted
formatting followed by the same five-file check passed. These were validation
command-boundary corrections, not production-source corrections.

## Preserved boundaries and next action

No production or infrastructure source, migration, dependency, lockfile,
production data, retained Milestone 7.7 evidence, canonical image input, or
protected stash was changed. No resource, role, database, image, scan, secret,
object-storage, soak, Milestone 7.7 lifecycle, dependency, or remote Git
mutation occurred.

The next action is a separately authorized repository-local correction of the
Windows Azure CLI launch contract, followed by a fresh managed PostgreSQL
campaign authorization from its reviewed clean HEAD. It is not the
object-storage audit and not a GitHub push. Milestone 7.8 remains incomplete.

## Later local correction cross-reference

This handoff remains the immutable historical receipt for the blocked
generation above. A later authorized repository-local change corrected the
Windows Azure CLI launch boundary and is recorded in the
[Windows Azure CLI launch-contract handoff](MILESTONE_7_8_WINDOWS_AZURE_CLI_LAUNCH_CONTRACT_HANDOFF.md).
That correction did not resume this source-bound generation, execute an Azure
operation other than a non-authenticated local version check, or close any of
the five managed evidence gaps.
