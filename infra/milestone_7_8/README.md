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
  The shared config and live execution source check requires the clean audit
  branch, its exact `origin/milestone-7-8-production-readiness-audit-local`
  upstream, and five protected stashes. Bootstrap also rechecks the config's
  source HEAD and cleanup-script digest.
- `cleanup.bicep` can only adopt that controller through `existing` resources
  and grant its system identity Contributor plus Role Based Access Control
  Administrator on the exact campaign target group. It cannot create, replace,
  or delete an Automation account, controller group, or runbook.
- `modules/` contains the campaign resources, identities, cleanup controller,
  and exact-scope cleanup role assignments.
- `schemas/` closes the historical retention-audit artifact, fresh-controller
  admission, configuration, private runtime, cleanup-region selection receipt, principal manifest,
  control-plane evidence, image admission, managed execution receipt, restart
  ledger, and zero-residue terminal receipt shapes.
- `prepare.py` creates one untracked generation from a clean, committed source
  tree with the exact approved audit-branch upstream. Its `--output` selects a
  new private subdirectory under `.runtime/milestone_7_8`, preserving existing
  evidence; it refuses an existing output directory, an unexpected upstream,
  a stash count other than five, a malformed campaign, or a mismatched
  target/PostgreSQL region. Before creating the directory it selects one
  cleanup region through `automation_region.py` from the closed order
  `eastus2`, `southcentralus`, `westus2`, `westus`, `eastus`, `northeurope`,
  `southeastasia`. The order includes every reviewed offer-safe region and is
  separately bound through every campaign artifact. Provider support,
  subscription-offer eligibility, enforced location policy, active occupancy,
  and discoverable soft-deleted occupancy are independent mandatory gates;
  discovery failure has no provider-only fallback. It validates and copies the
  exact fresh-scope predeployment artifact for the planned controller; its
  canonical hash is bound through selection, controller, campaign, runtime,
  parameters, authorization, cleanup authority, ledger, and terminal receipt.
- `operator.py` is dry-run by default. `--execute` advances one validated,
  persisted phase at a time and starts cleanup after any failure following
  scope creation. Every live phase requires a separate exact expiring execution
  authorization; phases that can enter failure cleanup must also authorize
  `cleanup`. Preparation refuses a bundle until the exact stable controller
  identity and authority are adoptable; `capacity-check` then proves its
  permanent Reader grant, published content, and empty schedule/binding
  inventories before `scope-create`. Live execution revalidates the copied
  fresh-controller admission artifact and rejects any unbound or mismatched
  evidence.
- `azure_cli.py` is the sole Azure CLI process boundary. It prefers a native
  launcher, safely supports trusted Windows `az.cmd`/`az.bat` launchers through
  the absolute system `cmd.exe` with `shell=False`, rejects repository-local or
  campaign-controlled launchers, and preserves exact arguments and process
  results.
- `campaign.py` enforces the USD 50 ceiling, at least 25 percent contingency,
  four-hour immutable deadline, one resource generation, at most one image
  generation, exactly one digest-bound admission scan, ordered resume,
  completely paginated active/deleted Automation inventory, a retained stable
  controller disposition, and a campaign-only zero-residue terminal receipt.
- `canonical_inputs.py` hashes the exact Git tree entries used by the API image;
  it does not depend on historical 7.7 image metadata.
- `retention.py` is a GET-only verifier for the one retained campaign account.
  It validates the authenticated subscription, completely paginates the
  documented deleted-account endpoint, binds the exact generated name,
  location, internal ARM-ID relationships, authoritative deletion instant,
  corrected target hash, and the four unrelated-record hashes, and emits no
  raw resource identifier. Normal absence verification refuses to contact
  Azure before the exact 30-day boundary.

The historical v2 and v3 absence formats remain available only for audit
parsing and historical-scope reconciliation. They are not fresh-scope live
admission contracts. Each of the four historical unrelated
baseline hashes is therefore either `present-unchanged` or
`absent-unattributed`; v3 does not infer a deletion time or cause for an
absent baseline record. Unknown, duplicate, colliding, malformed, or
ambiguous current records fail closed. The inventory page chain, observed
baseline status set, and current-inventory digest are all included in the
domain-separated audit digest. A historical artifact, authorization, or
controller tag cannot be used at a fresh-scope live entry point.

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

## Fresh subscription predeployment inventory

`predeployment.py` is a separate path for one replacement subscription before
anything has been deployed there. It takes an ignored private runtime binding
for the exact subscription, tenant, campaign/generation, region, and derived
reusable-controller account identity; a distinct expiring read authorization;
then performs only the authenticated-subscription read and complete paginated
`deletedAutomationAccounts` GET inventory. It saves a sanitized record with
the full inventory hash, page/request hashes, zero planned-account candidates,
and zero mutation counters.

A one-page inventory with zero deleted accounts is valid evidence for this
separate predeployment check. It is named
`fresh-subscription-predeployment-inventory-clear`, never
`retained-account-absent`, and is not a v3 retention artifact. Once it is
locally hash-bound to the exact fresh scope, it is the required controller and
campaign admission evidence; it is not Azure execution authority. Existing v3
M78-PG-012 rules remain unchanged for historical scopes that require
post-deletion retention verification.

The private runtime is initialized only from actual operator-held values in a
new ignored directory, never by copying the retired runtime. The read
authorization is hash-bound to that same runtime and permits exactly
`authenticated-subscription-read` and `deleted-automation-inventory-read` for
at most one hour. Raw subscription and tenant IDs remain only in that ignored
runtime. The verifier output, authorization, and runtime use the three
`fresh-subscription-predeployment-*.schema.json` contracts.

`controller.py controller-config` is the only local pre-bootstrap writer. It
validates that fresh proof and writes one closed private controller config for
the reviewed controller region; it creates neither an Azure resource nor an
execution authorization. It requires the proof's read authorization to still be
current when the config is written, and bootstrap rechecks that same freshness.
A separately authorized bootstrap and verification use that config first. Only
then can `prepare.py` recheck exact controller adoption and produce a campaign
bundle. This order prevents a bootstrap/config cycle without allowing target
deployment before controller proof.

The controller is retained for the entire fresh-scope campaign lifecycle.
Campaign cleanup removes only campaign-owned target resources, schedules,
job-schedule bindings, temporary grants, and runtime bindings; zero-residue
proof requires the controller to remain active exactly once and not appear in
the deleted inventory. Controller deletion is not a Milestone 7.8 campaign
operation. If it is separately designed and authorized later, provider-confirmed
deletion or a matching soft-deleted disposition is terminal controller evidence
immediately; no completion path may wait for provider retention to expire.

## Retired historical subscription

`historical-subscription-retired` is a separate, terminal historical
disposition for a former subscription that can no longer authenticate or expose
the deleted-account inventory. It is not `retained-account-absent`, is not a
v3 provider GET result, and cannot enter any controller, deployment, arming,
cleanup, or campaign admission path.

It may be recorded only as a document conforming to
`schemas/historical-subscription-retirement-evidence.schema.json`. A reviewer
must verify either an authenticated Microsoft notice or an authoritative account
record, then bind its sanitized document and authentication hashes to the exact
former subscription using retained private runtime or authorization evidence.
Raw subscription identifiers, notice contents, and account records are never
committed. Unknown, unauthenticated, or unbound notices fail closed.

The historical v3 artifact remains mandatory only for a scope whose accepted
contract actually requires post-deletion retention verification. A replacement
subscription is a new scope: it needs fresh private bindings, separate
authorization, and fresh predeployment evidence; it inherits neither this
historical disposition nor any former-subscription admission state.

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
the original deployment bound a schedule before publication and confused the
stable controller with campaign residue. Publication is now an imperative
proof-gated sequence. The stable controller is retained throughout Milestone
7.8; campaign residue covers only campaign-owned schedules, bindings, grants,
identities, jobs, and target resources. Microsoft retention behavior is never
a completion wait for that retained controller. The local architecture uses one
separately provisioned reusable controller outside campaign deletion scope;
ordinary campaign cleanup cannot create another retained Automation record.
The reported local state is
`architecture-corrected-live-execution-not-authorized`. M78-PG-012 corrects the
sanitized identity binding and adds the deterministic post-boundary absence
verifier; it does not remove the current record or prove the corrected
controller live. The fresh-scope admission binds the exact predeployment
inventory proof into every executable cleanup-admission surface and rejects
unbound evidence at live entry. No controller bootstrap, campaign, or managed
execution has occurred. If the former subscription is independently verified
retired, only the separate non-authorizing historical disposition may be
recorded; it cannot replace fresh-scope evidence. The exact retained private
runtime remains ignored and preserved.
M78-PG-E01, M78-PG-E02, M78-PG-E03,
M78-TI-E01, and M78-PG-E04 remain open. No new campaign is authorized, and
Milestone 7.8 remains incomplete. The local object-storage audit has now found
and corrected M78-OS-001; managed-provider object proof remains outstanding.
