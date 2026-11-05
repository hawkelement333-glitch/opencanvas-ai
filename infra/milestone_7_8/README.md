# Milestone 7.8 managed PostgreSQL campaign

This directory is the independent, bounded infrastructure and lifecycle surface
for the still-unexecuted Milestone 7.8 managed PostgreSQL evidence campaign. It
does not invoke or import the retained Milestone 7.7 lifecycle, does not begin
the object-storage audit, and does not close any managed-evidence gap by its
existence.

## Scope and topology

- `main.bicep` creates one campaign target resource group, five
  campaign-derived workload identities, one private PostgreSQL 17 Flexible
  Server, one private Premium registry, one internal Container Apps
  environment, and the bounded API, worker, bootstrap, migration, recovery,
  and evidence jobs.
- `controller.bicep` is the separately authorized, one-time stable controller
  deployment. It creates one subscription-bound controller resource group,
  Automation account, runbook, and permanent Reader grant on that group.
  `controller.py` is dry-run by default and requires an exact expiring
  authorization artifact before bootstrap or live verification.
- `cleanup.bicep` can only adopt that controller through `existing` resources
  and grant its system identity Contributor plus Role Based Access Control
  Administrator on the exact campaign target group. It cannot create, replace,
  or delete an Automation account, controller group, or runbook.
- `modules/` contains the campaign resources, identities, cleanup controller,
  and exact-scope cleanup role assignments.
- `schemas/` closes the strict retention-absence admission artifact,
  configuration, private runtime, cleanup-region selection receipt, principal manifest,
  control-plane evidence, image admission, managed execution receipt, restart
  ledger, and zero-residue terminal receipt shapes.
- `prepare.py` creates one untracked `.runtime/milestone_7_8` generation from a
  clean, committed source tree. It refuses an upstream, a stash count other
  than five, a second output directory, a malformed campaign, or a mismatched
  target/PostgreSQL region. Before creating the directory it selects one
  cleanup region through `automation_region.py` from the closed order
  `eastus2`, `southcentralus`, `westus2`, `westus`, `eastus`, `northeurope`,
  `southeastasia`. The order includes every reviewed offer-safe region and is
  separately bound through every campaign artifact. Provider support,
  subscription-offer eligibility, enforced location policy, active occupancy,
  and discoverable soft-deleted occupancy are independent mandatory gates;
  discovery failure has no provider-only fallback. It first validates and
  copies one strict post-boundary absence artifact; its canonical hash is bound
  through selection, controller, campaign, runtime, parameters, authorization,
  cleanup authority, ledger, and terminal receipt.
- `operator.py` is dry-run by default. `--execute` advances one validated,
  persisted phase at a time and starts cleanup after any failure following
  scope creation. Every live phase requires a separate exact expiring execution
  authorization; phases that can enter failure cleanup must also authorize
  `cleanup`. Preparation refuses a bundle until the exact stable controller
  identity and authority are adoptable; `capacity-check` then proves its
  permanent Reader grant, published content, and empty schedule/binding
  inventories before `scope-create`. Live execution revalidates the copied
  absence artifact and rejects synthetic fixture evidence.
- `azure_cli.py` is the sole Azure CLI process boundary. It prefers a native
  launcher, safely supports trusted Windows `az.cmd`/`az.bat` launchers through
  the absolute system `cmd.exe` with `shell=False`, rejects repository-local or
  campaign-controlled launchers, and preserves exact arguments and process
  results.
- `campaign.py` enforces the USD 50 ceiling, at least 25 percent contingency,
  four-hour immutable deadline, one resource generation, at most one image
  generation, exactly one digest-bound admission scan, ordered resume,
  completely paginated active/deleted Automation inventory, an explicit
  provider-retained disposition, and zero-residue terminal receipt.
- `canonical_inputs.py` hashes the exact Git tree entries used by the API image;
  it does not depend on historical 7.7 image metadata.
- `retention.py` is a GET-only verifier for the one retained campaign account.
  It validates the authenticated subscription, completely paginates the
  documented deleted-account endpoint, binds the exact generated name,
  location, internal ARM-ID relationships, authoritative deletion instant,
  corrected target hash, and the four unrelated-record hashes, and emits no
  raw resource identifier. Normal absence verification refuses to contact
  Azure before the exact 30-day boundary.

The historical v2 absence format remains available only for audit parsing. Live
admission uses v3: it proves exact target absence while recording the complete
current paginated inventory as hashes. Each of the four historical unrelated
baseline hashes is therefore either `present-unchanged` or
`absent-unattributed`; v3 does not infer a deletion time or cause for an
absent baseline record. Unknown, duplicate, colliding, malformed, or
ambiguous current records fail closed. The inventory page chain, observed
baseline status set, and current-inventory digest are all included in the
domain-separated admission digest. A v2 artifact, authorization, or
controller tag cannot be used at a v3 live entry point.

The target and PostgreSQL regions must match because this campaign uses one
private VNet. Their default is `centralus`. The independent cleanup region has
no caller-controlled default: preparation selects and hashes the first viable
reviewed candidate, and `capacity-check` repeats the same proof before scope
creation. The cleanup deployment runs once in that immutable region; no
post-mutation retry or region hop is permitted. PostgreSQL is fixed to
`Standard_D2ds_v5`, PostgreSQL 17, 64 GiB P6 storage, zones 1 and 2,
ZoneRedundant HA, seven-day backup retention, disabled geo backup, and Sunday
07:00 UTC maintenance.

## Identity boundary

Preparation derives bootstrap, migration, API, worker, and evidence identity
names from the campaign and generation. Bicep constructs one closed principal
manifest from the deployed object IDs. Every database operational program
validates the campaign, generation, semantic role, name, and object-ID binding.
Names and object IDs must be distinct; there is no accepted retained 7.7 name.

The bootstrap identity is the Flexible Server Entra administrator and is used
only to create/verify database principals, ownership, and grants. The migration
identity owns the application schema and is the only ordinary DDL identity.
API and worker receive the existing literal per-table matrices, no sequence or
function privileges, no role assumption, and no schema creation. The evidence
identity receives `CONNECT` and `pg_monitor` but no database creation authority.
The cleanup identity is not a database identity.

## Local validation

From the repository root, using only installed tools:

```powershell
$env:PYTHONDONTWRITEBYTECODE = "1"
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider -q `
  apps/api/tests/test_milestone_7_8_automation_region.py `
  apps/api/tests/test_milestone_7_8_campaign_enablement.py `
  apps/api/tests/test_milestone_7_7_runtime_topology.py

function Invoke-M78LocalAz([string[]]$Arguments) {
  & .\.venv\Scripts\python.exe -m infra.milestone_7_8.azure_cli invoke -- @Arguments
  if ($LASTEXITCODE -ne 0) { throw 'local Azure CLI operation failed' }
}

Invoke-M78LocalAz @('bicep', 'build', '--file',
  'infra/milestone_7_8/main.bicep', '--stdout') | Out-Null
Invoke-M78LocalAz @('bicep', 'build', '--file',
  'infra/milestone_7_8/cleanup.bicep', '--stdout') | Out-Null
Get-ChildItem infra/milestone_7_8/modules -Filter *.bicep | ForEach-Object {
  Invoke-M78LocalAz @('bicep', 'build', '--file', $_.FullName, '--stdout') |
    Out-Null
}
```

These commands are local contract checks. They do not contact Azure or a live
database. The separately authorized operator procedure is in
[`docs/MILESTONE_7_8_MANAGED_POSTGRESQL_CAMPAIGN_OPERATOR_RUNBOOK.md`](../../docs/MILESTONE_7_8_MANAGED_POSTGRESQL_CAMPAIGN_OPERATOR_RUNBOOK.md).

## Retained-account verification

The authoritative deletion instant is `2026-08-15T01:09:46.307Z`; the earliest
expected boundary is `2026-09-14T01:09:46.307Z`. At or after that instant, run:

```powershell
.\.venv\Scripts\python.exe -m infra.milestone_7_8.retention `
  --runtime .runtime\milestone_7_8\runtime.json `
  --evidence evidence\milestone_7_8\automation-retention-live-reconciliation.json `
  --authoritative-deletion-time 2026-08-15T01:09:46.307Z `
  --expect absent
```

Success requires exit 0, a v3 `status=retained-account-absent`, zero target
candidates, a complete paginated inventory, zero current-only records, and
`azureMutationCount=0`. Each historical unrelated baseline hash must be
represented exactly once as `present-unchanged` or `absent-unattributed`.
Preserve only the sanitized JSON output as the separately reviewed admission
artifact. Any mismatch fails closed. This check proves only absence of the
prior target; it does not authorize controller bootstrap, deployment, arming,
a campaign, or any other Azure operation.

## Current boundary

A fresh campaign previously stopped when Azure proved that provider support,
policy permission, and empty account inventories do not establish
subscription-offer admission. M78-PG-008 is now corrected locally. M78-PG-009
also corrected the later contradiction between that offer-safe set and the
old four-region candidate order. The selector binds the reviewed restrictive
public-offer set
`eastus,eastus2,northeurope,southeastasia,westus`; it excludes the unresolved
`JapanWest2`/`japanwest` variant rather than guessing. Sanitized read-only
discovery now selects `southeastasia`: `eastus2`, `westus`, `eastus`, and
`northeurope` are soft-deleted-account occupied; `southcentralus` and `westus2`
are offer-ineligible.

The later critical cleanup reconciliation proved M78-PG-010 and M78-PG-011:
the original deployment bound a schedule before publication, and its residue
model omitted the exact soft-deleted Automation account. Publication is now an
imperative proof-gated sequence and soft-deleted accounts are explicit residue.
Microsoft exposes retention/readback but no documented self-service permanent
delete for `deletedAutomationAccounts`. The local architecture now uses one
separately provisioned reusable controller outside campaign deletion scope;
ordinary campaign cleanup cannot create another retained Automation record.
The reported local state is
`architecture-corrected-live-execution-not-authorized`. M78-PG-012 corrects the
sanitized identity binding and adds the deterministic post-boundary absence
verifier; it does not remove the current record or prove the corrected
controller live. M78-PG-013 now binds the eventual exact absence artifact into
every executable cleanup-admission surface and rejects synthetic evidence at
live entry. No passing managed-provider absence artifact exists yet. The exact retained private
runtime remains ignored and preserved. M78-PG-E01, M78-PG-E02, M78-PG-E03,
M78-TI-E01, and M78-PG-E04 remain open. No new campaign is authorized, and
Milestone 7.8 remains incomplete. The local object-storage audit has now found
and corrected M78-OS-001; managed-provider object proof remains outstanding.
