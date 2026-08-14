# Milestone 7.8 Windows Azure CLI launch-contract handoff

Date: 2026-08-13

Status: M78-PG-006 corrected and validated locally; managed PostgreSQL evidence
campaign not executed

## Outcome

The Windows process-boundary defect that blocked the independent managed
PostgreSQL campaign is corrected in repository state. Every executable Azure
CLI path in the Milestone 7.8 campaign now uses one centralized resolver and
launcher. The resolver supports a native CLI on Windows, Linux, and macOS and
the installed Windows `az.cmd`/`az.bat` form without enabling a shell or
hard-coding a machine path.

The only real CLI process run during this correction was the bounded local
`az version --output json` smoke through the new abstraction. It selected the
batch contract and returned sanitized version `2.88.0`. It did not read Azure
account, subscription, tenant, provider, resource, role, database, or data-plane
state.

No blocked generation was resumed. No Azure mutation, live-database operation,
image build, scan, object-storage audit, soak, cleanup lifecycle, dependency
change, remote Git operation, or Milestone 7.7 operation occurred. The five
managed evidence gaps remain open and Milestone 7.8 remains incomplete.

## Authoritative starting boundary

- branch: `milestone-7-8-production-readiness-audit-local`;
- starting HEAD: `a80643233d81d60f4b47b022cbfc66842eaf5cbd`;
- subject: `docs(evidence): record blocked 7.8 database campaign`;
- upstream: absent;
- tree/index: clean;
- protected stashes: exactly five and untouched;
- Alembic sole head: `20260726_0029`;
- migration `0030`: absent;
- `.runtime/milestone_7_8`: absent;
- retained blocked generation: zero resource/image generations, zero scans,
  zero billable mutations, zero elapsed billable seconds, USD 0.00 actual
  cost, all 15 residue counters zero, and seven unrelated Azure resources;
- object-storage audit: unstarted.

The retained canonical API image inputs were:

| Input        | SHA-256                                                            |
| ------------ | ------------------------------------------------------------------ |
| build input  | `533dc8d9a64f2d4b1a8a10d5ac769b11e1bc962741a7637da44c037e34c4dad7` |
| Dockerfile   | `1f914420f661e40bcc8e61d149115387042fd3948323b645b9a204390c90a82b` |
| API project  | `b826c6e415e5c836cda5c74696d69b61f517a86556b2fecb82201ca35540868c` |
| build lock   | `22f8b5d1f0b8521e28470f6097717ff64c9cccc7b6037db7a5c25962e32a7ccb` |
| runtime lock | `cdab59f073ff510ff6d8b951d178381650236662b488c06b2d6436063f336aa0` |

## Proved defect and disposition

M78-PG-006 was present at the starting HEAD. `operator.py` represented Azure
commands as exact argument tuples, but `SubprocessRunner` sent the symbolic
first element `az` directly to `subprocess.run(..., shell=False)`. The Windows
host exposed the installed CLI as `az.cmd`/batch, not `az.exe`, so the process
API returned Windows error 2 before the first preflight ledger write. This was
a repository launch-contract defect, not proof about authentication or Azure
authority.

The smallest complete correction is `infra/milestone_7_8/azure_cli.py` plus a
single dispatch point in `SubprocessRunner`. No machine path, copied launcher,
wrapper artifact, shell lookup, or credential mechanism was introduced.

## Resolver and process model

| Platform/discovery result                                        | Process contract                                                                                                             |
| ---------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| Windows `az.exe`                                                 | Canonical absolute file, strict native name, direct argument tuple, `shell=False`.                                           |
| Windows `az.cmd` or `az.bat`                                     | Canonical absolute file, strict batch name, absolute `GetSystemDirectoryW` plus `cmd.exe`, `/d /s /v:off /c`, `shell=False`. |
| Linux/macOS `az`                                                 | Canonical absolute executable, strict native name, direct argument tuple, `shell=False`.                                     |
| missing launcher                                                 | Fail closed with the checked forms; no operator result or new ledger is written.                                             |
| repository/current-directory/`.runtime`/`.git` launcher          | Reject before process creation.                                                                                              |
| relative path, wrong resolved name, non-file, or public override | Reject; no launcher override API exists.                                                                                     |

Native discovery is deterministic and precedes batch discovery. A batch launch
uses collision-resistant temporary process-environment names. Each nonempty
argument is Windows-quoted into one binding, referenced once in the
`cmd.exe /c` command, and the complete binding set is unset before the batch
child begins. Empty values use an explicit empty argument. Delayed expansion is
disabled. This preserves spaces, Unicode, literal quotes, backslashes,
trailing backslashes, JSON, and `&`, `|`, `<`, `>`, `^`, `%`, parentheses, and
`!` without executing them. NUL, CR, and LF fail closed.

Native and batch execution preserve caller working directory and environment,
UTF-8 text decoding, stdout, stderr, nonzero exit status, and timeout behavior.
Campaign-level process exceptions are converted to one non-secret error; the
CLI entry point likewise does not print the failed command or arguments.

## Complete call-site inventory

`command_plan` currently emits 50 planned commands. Forty-four are Azure CLI
commands across 14 phases:

| Phase                            | Planned Azure commands |
| -------------------------------- | ---------------------: |
| preflight / correlate            |                  1 / 1 |
| capacity-check                   |                     10 |
| scope-create / cleanup-deploy    |                  1 / 1 |
| cleanup-arm / cleanup-verify     |                  2 / 6 |
| deploy / bootstrap / migrate     |              1 / 1 / 1 |
| evidence                         |                     12 |
| cleanup / cleanup-wait / residue |              1 / 2 / 4 |

`cost-gate`, `billable-start`, `image-decision`, `dispose`, and `finalize` have
no planned Azure command. Generated Container Apps job polling, failure
cleanup, and direct exact-group cleanup also call the same `SubprocessRunner`.
The only other Python subprocess sites in this package run Git or Python; no
Python call site directly executes a literal `az`.

The current campaign README and operator runbook route their local Bicep,
image build, manifest readback, and PostgreSQL configuration readback through
`azure_cli invoke -- ...`. The historical blocked receipt retains its original
command evidence and only adds a cross-reference to this correction.

## Focused proof

The focused suite uses real temporary `.cmd` and `.bat` files launched through
the trusted system `cmd.exe`. It proves:

- native and both batch forms, including paths containing spaces;
- native preference when both forms exist;
- exact ordered arguments for spaces, empty strings, Unicode, quotes,
  backslashes, trailing backslashes, JSON, and every Windows metacharacter;
- a command-injection sentinel remains absent;
- stdout/JSON, stderr, nonzero status, working directory, environment, timeout,
  and process-independent behavior;
- temporary argument bindings are absent from the batch child;
- missing, repository-local, `.runtime`, relative, and arbitrary-name launcher
  rejection before a runtime artifact;
- `shell=False` for native and batch execution;
- one resolver call per runner and centralized operator preflight execution;
- safe error redaction and exact pass-through CLI exit/streams;
- no direct literal-`az` Python subprocess call and no `shell=True`,
  `Invoke-Expression`, or `Start-Process` campaign path.

## Validation ledger

| Command or check                                                 | Result                                                        |
| ---------------------------------------------------------------- | ------------------------------------------------------------- |
| focused Ruff check and format check                              | exit 0                                                        |
| strict mypy over launcher, campaign, operator, and focused tests | exit 0; no issues in 4 files                                  |
| `pytest -q tests/test_milestone_7_8_azure_cli_launcher.py`       | exit 0; 13 passed                                             |
| `pytest -q tests/test_milestone_7_8_campaign_enablement.py`      | exit 0; 46 passed                                             |
| `pytest -q tests/test_milestone_7_7_runtime_topology.py`         | exit 0; 9 passed; one existing Starlette deprecation warning  |
| `pytest -q tests/test_milestone_7_7_infrastructure_contracts.py` | exit 0; 94 passed                                             |
| `pytest -q tests/test_milestone_7_8_database_remediation.py`     | exit 0; 7 passed                                              |
| `python -m infra.milestone_7_8.azure_cli version`                | exit 0; batch launcher; Azure CLI `2.88.0`                    |
| `python scripts/validate_migrations.py`                          | exit 0; upgrade 0029, downgrade 0028, re-upgrade 0029         |
| `python -m alembic -c alembic.ini heads`                         | exit 0; sole `20260726_0029 (head)`                           |
| migration `0030` inventory                                       | zero files                                                    |
| `python -m infra.milestone_7_8.canonical_inputs --treeish HEAD`  | exit 0; all five retained hashes matched                      |
| targeted Prettier check over 6 changed Markdown files            | exit 0                                                        |
| local-link check over the same Markdown files                    | exit 0; 9 local links                                         |
| `python scripts/check_repository_hygiene.py`                     | exit 0; 630 source files                                      |
| bounded PowerShell array-forwarding probe                        | exit 0; spaces and argument order preserved                   |
| `git diff --check`                                               | exit 0                                                        |
| `git fsck --full --no-reflogs`                                   | exit 0; dangling objects only                                 |
| changed-file and generated-residue guard                         | exit 0; 9 intended files; no runtime, bytecode, or tool cache |

No local PostgreSQL fixture was required by this launch-boundary correction.
No Azure account or managed database proof is claimed from the local version
smoke.

## Changed files

- `infra/milestone_7_8/azure_cli.py`;
- `infra/milestone_7_8/campaign.py`;
- `apps/api/tests/test_milestone_7_8_azure_cli_launcher.py`;
- `infra/milestone_7_8/README.md`;
- `docs/MILESTONE_7_8_MANAGED_POSTGRESQL_CAMPAIGN_OPERATOR_RUNBOOK.md`;
- `docs/MILESTONE_7_8_DEFECT_REGISTER.md`;
- `docs/MILESTONE_7_8_MANAGED_POSTGRESQL_CAMPAIGN_EXECUTION_HANDOFF.md`;
- `docs/MILESTONE_7_8_MANAGED_POSTGRESQL_CAMPAIGN_ENABLEMENT_HANDOFF.md`; and
- this handoff.

No migration, canonical API image input, dependency, lockfile, retained
Milestone 7.7 evidence, canonical image evidence, or protected stash changed.

## Remaining boundary and next action

M78-PG-006 is resolved only in repository state. M78-PG-E01, M78-PG-E02,
M78-PG-E03, M78-TI-E01, and M78-PG-E04 remain open. The blocked source-bound
generation recorded in the execution handoff must not be resumed.

The next action is a separately reviewed and authorized fresh managed
PostgreSQL evidence campaign from the corrected clean commit. It is not a Git
push and not the object-storage audit. Milestone 7.8 remains incomplete.

## Later regional-capacity correction cross-reference

The fresh campaign that followed this launcher correction proved the launcher
and stopped later at the cleanup Automation account's unchecked `westus`
capacity boundary. M78-PG-007 subsequently added five static read-only
Automation-region commands to `capacity-check` plus generated enforced-policy
definition reads, all through this same centralized launcher. The current
static operator plan therefore contains 55 commands, 49 of them Azure CLI
commands; policy-definition reads, Container Apps polling, failure cleanup,
and exact-two-group direct cleanup remain generated paths through the same
process boundary.

See the
[regional-capacity remediation handoff](MILESTONE_7_8_AUTOMATION_REGIONAL_CAPACITY_REMEDIATION_HANDOFF.md).
The historical 50 / 44 inventory above remains accurate for this handoff's
source commit and was not rewritten.
