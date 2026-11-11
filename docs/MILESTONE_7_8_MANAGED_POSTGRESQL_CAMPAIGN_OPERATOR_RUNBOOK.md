# Milestone 7.8 managed PostgreSQL campaign operator runbook

Date: 2026-08-25

Status: `architecture-corrected-live-execution-not-authorized`

This runbook preserves the intended independent campaign path, but it is not a
readiness claim or execution authorization. The corrected path uses one stable
reusable Automation controller outside campaign deletion scope. Preparation
refuses a bundle until that exact controller identity is separately
provisioned and adoptable. Before `scope-create`, `capacity-check` proves its
permanent Reader grant, published content, and empty schedule/binding
inventories. Every controller or campaign Azure execution
requires a separate exact expiring authorization artifact. No new campaign is
authorized, and no controller is claimed live by this document.

## Prerequisites and authority

Run from the repository root on branch
`milestone-7-8-production-readiness-audit-local`, at the reviewed campaign
commit, with a clean tree/index and exactly five untouched stashes. Controller
configuration, bootstrap, and campaign preparation require the exact upstream
`origin/milestone-7-8-production-readiness-audit-local`. Campaign preparation
requires a new `--output` subdirectory, while existing private evidence under
`.runtime/milestone_7_8` remains untouched. For a
fresh replacement subscription, the exact planned controller must instead have
a complete, hash-bound `fresh-subscription-predeployment-inventory-clear`
artifact, and controller or campaign execution still requires a separate Azure
authorization. Elapsed time alone is never an admission fact.

This runbook applies only to a live, authenticated subscription. If the former
subscription is retired and cannot run the v3 authenticated-subscription and
deleted-account inventory reads, stop: do not mark the GET as passed and do not
substitute a deletion notice. A separately reviewed
`historical-subscription-retired` document may record that former scope only
when the sanitized authenticated-notice or authoritative-account-record hashes
are bound to its retained private runtime or authorization evidence. That
terminal historical disposition authorizes no controller bootstrap, deployment,
arming, cleanup, or campaign. Any replacement subscription is a fresh scope
with fresh bindings, authorization, and fresh predeployment evidence.

> **2026-11-08 fresh-subscription predeployment amendment:** an active
> replacement subscription may first use only the separate
> `fresh-subscription-predeployment-inventory-clear` read path. It requires a
> new ignored runtime, exact expiring read authorization, authenticated
> subscription read, and complete paginated deleted-account GET inventory bound
> to the exact planned reusable-controller account. A zero-record inventory is
> valid for that narrow check. It is not M78-PG-012 or
> `retained-account-absent`. Once locally hash-bound to the exact fresh scope,
> it is the required controller/bootstrap and campaign-preparation admission
> evidence; it is never Azure execution authority.

The interactive deployment operator needs only the Azure control-plane actions
required to create the generated target group and the resource types in
`infra/milestone_7_8/main.bicep`, plus temporary
`Microsoft.Authorization/roleAssignments/write/delete` on that exact target
scope. Stable controller bootstrap is a prior, separately authorized operation
through `controller.bicep` and `controller.py`. It must not receive database credentials. The
deployed identities are narrower:

Before any generation directory exists, preparation also needs read-only
access to the Automation provider metadata, active and soft-deleted Automation
account locations, applicable policy assignments/definitions, and the current
AzureCloud account correlation. Those reads return only locations, counts, and
sanitized hashes to persisted evidence; account names and ARM identifiers are
not retained.

| Identity  | Azure authority                                                                                                                                       | PostgreSQL authority                                                                                      |
| --------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| Bootstrap | ACR pull; Flexible Server Entra administrator binding                                                                                                 | create/verify the four non-cleanup database principals; transfer application ownership; reconcile grants  |
| Migration | ACR pull only                                                                                                                                         | `CONNECT`, database/schema creation needed by reviewed Alembic, and ownership of application objects      |
| API       | ACR pull only                                                                                                                                         | literal API table matrix: 150 SELECT, 149 INSERT, 17 UPDATE, 9 DELETE; no sequence/function/DDL authority |
| Worker    | ACR pull only                                                                                                                                         | literal worker table matrix: 55 SELECT, 18 INSERT, 6 UPDATE, 1 DELETE; no sequence/function/DDL authority |
| Evidence  | ACR pull only                                                                                                                                         | `CONNECT` and `pg_monitor`; no database/schema creation or application ownership                          |
| Cleanup   | Permanent Reader on its stable controller group; temporary Contributor plus Role Based Access Control Administrator on the exact campaign target only | none                                                                                                      |

The operator must use an approved synthetic tenant only. No production data or
production identity is permitted. `M78_SUBSCRIPTION_ID` and `M78_TENANT_ID`
are held only in process memory and the ignored private runtime file; do not
paste them into tracked evidence or terminal reports.

All Azure CLI execution in this runbook and the operator must pass through
`python -m infra.milestone_7_8.azure_cli`. Before preparing a generation, run
the bounded non-authenticated launcher check:

```powershell
.\.venv\Scripts\python.exe -m infra.milestone_7_8.azure_cli version
if ($LASTEXITCODE -ne 0) { throw 'trusted Azure CLI launcher unavailable' }
```

On Windows, the resolver prefers `az.exe`; otherwise it accepts only a
canonical installed `az.cmd` or `az.bat` and invokes it through the absolute
system `cmd.exe` with `shell=False`. Repository, current-directory,
`.runtime`, and arbitrary launcher substitutions fail closed before a new
ledger is written.

## Fresh subscription predeployment inventory

This is a separate, read-only prerequisite for a replacement scope. It creates
no campaign runtime, controller, resource group, ledger, schedule, role, or
deployment. Never copy `.runtime/milestone_7_8/runtime.json` or any former
retention evidence into this directory.

Set only actual, reviewed private values in process memory, then create the
new private binding and narrow read authorization. The values are intentionally
not supplied by this runbook:

```powershell
$env:M78_FRESH_SUBSCRIPTION_ID = '<active-subscription-uuid>'
$env:M78_FRESH_TENANT_ID = '<active-tenant-uuid>'
$env:M78_FRESH_CAMPAIGN_ID = '<reviewed-campaign-id>'
$env:M78_FRESH_GENERATION_ID = '<reviewed-generation-id>'
$env:M78_FRESH_REGION = '<reviewed-controller-region>'
$fresh = '.runtime/milestone_7_8/fresh-subscription'

.\.venv\Scripts\python.exe -m infra.milestone_7_8.predeployment initialize `
  --runtime "$fresh/fresh-subscription-runtime.json"
```

After separate review, issue one authorization expiring within one hour. This
is local proof of read scope only; it grants no Azure role or execution
authority:

```powershell
.\.venv\Scripts\python.exe -m infra.milestone_7_8.predeployment authorize-read `
  --runtime "$fresh/fresh-subscription-runtime.json" `
  --authorization "$fresh/predeployment-read-authorization.json" `
  --expires-at '<reviewed-rfc3339-utc-expiry>'
```

The only Azure-touching command in this path is the following verifier. It
performs the authenticated subscription read and exactly the paginated GET
inventory; its output is sanitized and written only beside the fresh private
runtime:

```powershell
.\.venv\Scripts\python.exe -m infra.milestone_7_8.predeployment verify `
  --runtime "$fresh/fresh-subscription-runtime.json" `
  --authorization "$fresh/predeployment-read-authorization.json" `
  --output "$fresh/predeployment-absence-evidence.json"
```

The fresh scope must pass this exact artifact to `prepare`; historical v3
M78-PG-012 evidence is rejected from that fresh path.

## Prepare one generation

**Separately authorized future step:** do not execute this section from this
handoff. The local `controller-config` writer first creates only a private
bootstrap configuration from the completed fresh-scope proof. It creates no
Azure resource, authorization, or campaign bundle. A separately authorized
controller bootstrap/verification must then finish with exact baseline readback
before campaign preparation can succeed. The predeployment read authorization
must still be current when the local config is written and when bootstrap starts;
it is proof freshness, not controller execution authority.

Set the exact later-authorized Azure identifiers in memory and choose one
campaign label matching `^[a-z][a-z0-9-]{7,47}$`:

```powershell
$env:M78_SUBSCRIPTION_ID = '<authorized-subscription-uuid>'
$env:M78_TENANT_ID = '<authorized-tenant-uuid>'
$campaign = 'mobius78-pg-evidence'
$generation = 'g1-aabbccddeeff'
$fresh = '.runtime/milestone_7_8/fresh-subscription/approved-scope'
$controllerRegion = '<reviewed-controller-region>'
$controllerConfig = "$fresh/controller-bootstrap.json"

$env:PYTHONDONTWRITEBYTECODE = '1'
.\.venv\Scripts\python.exe -m infra.milestone_7_8.controller controller-config `
  --campaign-id $campaign `
  --generation-id $generation `
  --controller-region $controllerRegion `
  --output $controllerConfig `
  --fresh-subscription-runtime "$fresh/fresh-subscription-runtime.json" `
  --fresh-subscription-authorization "$fresh/predeployment-read-authorization.json" `
  --fresh-subscription-evidence "$fresh/predeployment-absence-evidence.json"
if ($LASTEXITCODE -ne 0) { throw 'local controller config creation failed' }

# Obtain separate, exact controller-bootstrap authorization outside this command.
# The two commands below are not authorized by this handoff; each revalidates
# this config and the same fresh evidence before it can contact Azure.
.\.venv\Scripts\python.exe -m infra.milestone_7_8.controller controller-bootstrap `
  --config $controllerConfig `
  --authorization '<separately-authorized-controller-bootstrap.json>' `
  --fresh-subscription-runtime "$fresh/fresh-subscription-runtime.json" `
  --fresh-subscription-authorization "$fresh/predeployment-read-authorization.json" `
  --fresh-subscription-evidence "$fresh/predeployment-absence-evidence.json" `
  --execute
.\.venv\Scripts\python.exe -m infra.milestone_7_8.controller controller-verify `
  --config $controllerConfig `
  --authorization '<separately-authorized-controller-verify.json>' `
  --fresh-subscription-runtime "$fresh/fresh-subscription-runtime.json" `
  --fresh-subscription-authorization "$fresh/predeployment-read-authorization.json" `
  --fresh-subscription-evidence "$fresh/predeployment-absence-evidence.json" `
  --execute

.\.venv\Scripts\python.exe -m infra.milestone_7_8.prepare `
  --campaign-id $campaign `
  --generation-id $generation `
  --output '.runtime/milestone_7_8/campaigns/<new-generation-directory>' `
  --target-region centralus `
  --postgres-region centralus `
  --controller-region $controllerRegion `
  --fresh-subscription-runtime "$fresh/fresh-subscription-runtime.json" `
  --fresh-subscription-authorization "$fresh/predeployment-read-authorization.json" `
  --fresh-subscription-evidence "$fresh/predeployment-absence-evidence.json" `
  --controller-authority-evidence '<reviewed-private-controller-authority-evidence.json>'
if ($LASTEXITCODE -ne 0) { throw 'campaign preparation failed' }

$config = '.runtime/milestone_7_8/campaign.json'
$runtime = '.runtime/milestone_7_8/runtime.json'
$ledger = '.runtime/milestone_7_8/ledger.json'
$cleanupRegionEvidence = '.runtime/milestone_7_8/cleanup-region-selection.json'
$freshAdmissionCopy = '.runtime/milestone_7_8/predeployment-absence-evidence.json'
```

Preparation refuses missing, wrong-subscription/tenant, wrong-campaign or
generation, wrong-region/controller identity, incomplete pagination,
planned-account presence, nonzero mutation, malformed, or hash-mismatched
fresh evidence before regional discovery. The evidence is a completed GET-only
predeployment proof, not execution authorization. Preparation also refuses a dirty tree,
wrong branch, upstream, stash-count drift,
malformed UUID/campaign, mismatched target/PostgreSQL region, or an existing
output directory. It has no caller-supplied cleanup-region override. Before
creating the output directory, it evaluates the exact order `eastus2`,
`southcentralus`, `westus2`, `westus`, `eastus`, `northeurope`,
`southeastasia` against normalized provider support, subscription-offer
eligibility, enforced location policy, exact reusable-controller adoption or
unrelated active account occupancy, and discoverable soft-deleted occupancy.
When the exact controller exists, its established region is the only selectable
controller region. The order contains every reviewed
offer-safe region and is separately bound through configuration, runtime,
ledger, parameters, tags, Bicep outputs, readback, and receipt. A candidate is
armable only when all four independent admission dimensions pass. The
offer-safe baseline is `eastus,eastus2,northeurope,southeastasia,westus`; Free
Trial/Student and unclassified public offers cannot broaden it. The documented
`JapanWest2` token is not treated as the provider's `japanwest` token without
authoritative alias proof. There is no caller-supplied offer class, allowlist,
cleanup region, candidate order, or bypass. Discovery failure or an empty
intersection stops without a generation, ledger, or hard-coded fallback.

The first viable candidate and hashes of provider, offer eligibility, active,
soft-deleted, and policy evidence are written to the closed selection receipt.
The offer classification or restrictive-baseline disposition, normalized
eligible-region set, and source/version identifier are also bound. Its
domain-separated receipt hash is repeated in campaign configuration, private
runtime, both Bicep parameter files, lifecycle tags, and later ledger/readback
evidence. Preparation creates exactly one generation and a cleanup deadline
four hours in the future. It never prints either raw Azure UUID.

## Dry-run and execute phases

**Not currently authorized:** do not execute the phase sequence without one
exact execution-authorization artifact covering each requested mutation.

Every operator phase is dry-run unless `--execute` is present. Before each
mutation, inspect the redacted command plan:

```powershell
function Invoke-M78Phase([string]$Phase, [string]$Authorization, [string[]]$Extra = @()) {
  & .\.venv\Scripts\python.exe -m infra.milestone_7_8.operator $Phase `
    --config $config --runtime $runtime --ledger $ledger @Extra
  if ($LASTEXITCODE -ne 0) { throw "dry-run blocked: $Phase" }
  & .\.venv\Scripts\python.exe -m infra.milestone_7_8.operator $Phase `
    --config $config --runtime $runtime --ledger $ledger --execute `
    --authorization $Authorization @Extra
  if ($LASTEXITCODE -ne 0) { throw "execution blocked: $Phase" }
}

# Supply a separately reviewed artifact for each live phase. Read-only phases
# still require exact campaign execution authorization; mutation artifacts
# must name the requested operation and expire before cleanup authority. Any
# phase that can enter failure cleanup must also include `cleanup` in the same
# artifact; the operator rejects execution before Azure otherwise.
```

The `capacity-check` dry-run exposes 24 static Azure commands, including named
PostgreSQL regional core and SKU-family quotas and the Container Apps managed
environment count. Six are the
subscription context, subscription-policy metadata, Automation provider,
active-account, soft-deleted-account, and policy-assignment reads; enforced
policy definitions and deny-capable initiative members produce explicit
generated GETs. Execution repeats preparation's complete offer-aware selector
and requires the immutable region, ordered candidate-set binding, decision
hash, offer binding, and every evidence hash to match. Any change stops before
`scope-create`. Seven final reads also prove the exact controller group,
account, permanent Reader grant, published runbook content, and complete empty
schedule and binding inventories before any target mutation.

The operator plan also has bounded generated Container Apps job polling,
failure cleanup, exact-target direct cleanup, and deterministic controller
disarm. Preparation's regional selection
has six static Azure reads plus generated policy-definition GETs. Every Azure
path uses the centralized launcher; no unrelated Automation account name is a
command target.

The intended sequence proves local source/hash/Git state, Azure subscription/tenant
correlation, six provider registrations, PostgreSQL SKU, regional compute
quota, global names, USD 25.6832 estimate, at least 25 percent contingency,
the USD 50 ceiling, exact scope tags, cleanup deployment outputs, published
runbook content, one immutable schedule, one binding, actual cleanup identity,
and exact cleanup deadline before the billable clock starts. The campaign
cleanup deployment creates only exact target-scoped RBAC against the existing
controller; it creates zero schedules and zero job-schedule bindings.
`cleanup-arm` verifies deployment, identity, authority, previously published
state and exact content, reconciles or creates the immutable schedule, and
reconciles or creates the deterministic binding. A failure at any earlier step cannot advance the ledger to
`cleanup-armed`. The `deploy` phase is base infrastructure only; no application
job exists yet.

## One image decision

The canonical source changes in this implementation require one new validation
image. No retained image may be substituted. Under the later image/scanner
authorization, build once from the repository root and retrieve the immutable
digest:

```powershell
$rt = Get-Content -LiteralPath $runtime -Raw | ConvertFrom-Json
$imageName = "mobius-api:m78-$($campaign)"
& .\.venv\Scripts\python.exe -m infra.milestone_7_8.azure_cli invoke -- `
  acr build --registry $rt.registryName --image $imageName `
  --file apps/api/Dockerfile . --output json
if ($LASTEXITCODE -ne 0) { throw 'single campaign image build failed' }
$digest = (& .\.venv\Scripts\python.exe -m infra.milestone_7_8.azure_cli `
  invoke -- acr manifest show-metadata --registry $rt.registryName `
  --name $imageName --query digest --output tsv).Trim()
if ($LASTEXITCODE -ne 0 -or $digest -notmatch '^sha256:[a-f0-9]{64}$') {
  throw 'immutable image digest readback failed'
}
```

The separately authorized admission scanner must scan that exact digest and
write `.runtime/milestone_7_8/image-scan.json` conforming to
`infra/milestone_7_8/schemas/image-scan.schema.json`. The receipt must bind the
prepared source HEAD and canonical build-input hash and must report zero High
and zero Critical findings. Validate and deploy the workload only after the
receipt exists:

For a fresh private bundle, the local Scout entry point runs one digest-pinned
registry scan and writes the raw SARIF and receipt only in the private runtime
tree. It requires a clean checkout matching the prepared source and canonical
build inputs, registry access for Docker Scout, and new output paths. It rejects
an unsuccessful scan or nonempty High/Critical report:

```powershell
.\.venv\Scripts\python.exe -m infra.milestone_7_8.scout_admission `
  --runtime "$bundle/runtime.json" --digest $digest `
  --report "$bundle/image-scan.sarif" --receipt "$bundle/image-scan.json" --execute
if ($LASTEXITCODE -ne 0) { throw 'image admission scan failed' }
```

This command requires a separate live authorization and has not been proved
against the managed registry by local tests. The digest must come from the one
authorized campaign build and its registry readback.

```powershell
$scan = '.runtime/milestone_7_8/image-scan.json'
Invoke-M78Phase 'image-decision' @(
  '--image-digest', $digest,
  '--image-built',
  '--image-scan-evidence', $scan
)
```

The operator validates the receipt before issuing the workload deployment. It
records the receipt SHA-256, selected digest, one image generation, and exactly
one required scan. A second digest, build, or scan is rejected.

## Retained controller authority records

Campaign discovery must not derive the original controller deadline from current
tags. Preserve the previously verified config, its `controller-verify`
authorization, its sanitized successful result, and the seven retained command
results in order: group, account, Reader assignments, runbook metadata, exact
runbook content, schedules, and job-schedule bindings. Each command result is
`{"exitCode":0,"stdout":"...","stderr":"..."}`; `stdout` contains the actual
retained response, with content at index four preserved as text. Do not fabricate
responses or reuse a failed bootstrap result as a verification result.

The local-only assembler validates these inputs and refuses to replace an output:

```powershell
.\.venv\Scripts\python.exe -m infra.milestone_7_8.controller_admission `
  --verified-config '<preserved-verified-config.json>' `
  --verification-authorization '<preserved-verification-authorization.json>' `
  --verification-result '<preserved-successful-verification-result.json>' `
  --baseline-readback '<retained-seven-command-results.json>' `
  --output '<new-ignored-private-directory>/controller-authority-evidence.json'
```

For a renewed deadline the assembler additionally requires `--renewal` pointing
to a reviewed record conforming to
`controller-authority-evidence.schema.json#/properties/renewal`. It contains the
renewed config, exact approval, actual seven-command before/after readbacks,
start/completion times within the approval window, and completion receipt.
Only `sourceHead` and `controllerAuthorizedUntilUtc` may differ between configs.
The approval binds both configs, the original deadline, proposed deadline, and
before-readback digest. All preservation and completion hashes are independently
recomputed; the two success booleans are insufficient without the responses.
Approval of an exact old/new transition can explicitly cover an already-expired
old deadline, but historical approval never becomes current execution authority.

For the existing verified controller, one separately authorized first live
renewal attempt may use the locally tested executor and the read-only snapshot
and reconciliation paths below. This permission is limited to the three planned
deadline-tag Merge requests on that controller's group, Automation account, and
runbook. Validate the exact plan, current approval, protected private storage,
and seven-read baseline before dispatch; preserve the complete executor journal
and all before/after readbacks. The snapshot and reconciliation paths have
synthetic tests and a separately captured live baseline; successful Azure Merge
behavior and preservation remain unproved until the separately authorized
seven-read reconciliation passes and its completion evidence is validated.
Campaign admission remains blocked until then. Do not perform manual tag changes
using this assembler. Failed, indeterminate,
partial, or unrecorded renewals cannot enter campaign adoption. A lost final
response remains blocked until its actual dispatch journal and complete
preservation readback validate. Existing original artifacts remain immutable.
Raw responses belong only in ignored private storage.

After separate review, the following paths name private, ignored inputs and new
outputs. `snapshotAuth` is an exact current `controller-verify` authorization
bound to the plan's renewed config. `reconcileAuth` is the separately reviewed
GET-only reconciliation authorization produced by `build_reconciliation_approval`
from the exact original plan, mutation approval, before-readback and executor
journal. Supplying `--execute` below authorizes only the documented readbacks:

```powershell
.\.venv\Scripts\python.exe -m infra.milestone_7_8.controller_renewal `
  --operation before-snapshot --authority-evidence $anchor --plan $plan `
  --read-authorization $snapshotAuth --output $before --execute

.\.venv\Scripts\python.exe -m infra.milestone_7_8.controller_renewal `
  --operation reconcile --authority-evidence $anchor --plan $plan `
  --approval $mutationAuth --before-readback $before --journal-dir $journal `
  --read-authorization $reconcileAuth --output $newReconciliationDirectory --execute
```

Reconciliation reads the actual executor records and never repeats a mutation.
When reconciliation runs from a corrected clean source commit, its separate
approval must include that exact `reconciliationSourceHead`. The original plan,
mutation approval, and journal remain bound to the source that dispatched them.
This source transition applies only to GET-only reconciliation; it cannot
authorize a snapshot or mutation from a different source.
One separately authorized subsequent renewal of the existing controller may
use its validated first-renewal completion evidence as `$anchor`. The planner
binds that entire prior evidence and its final readback, including the previously
verified deadline, into the new plan. The new completion retains the unmodified
bootstrap and first-renewal evidence. A third renewal is not supported by this
contract. Choose the new deadline at execution and verify it extends at least
five hours past the actual campaign preparation time.
An early lost response, missing dispatch record, incomplete journal, nonzero
final response without a complete journal, or any changed unrelated field stays
blocked; matching tags do not reconstruct dispatch history. A process crash
after dispatch but before the dispatch record likewise needs manual investigation
and remains inadmissible. File contents are flushed and fsynced; directory-entry
crash durability has not been independently tested. The designated review
directory's current-user-only ACL and child inheritance were checked locally;
recheck the selected private output directory and its inherited ACL at execution.

Preparation copies and hash-binds this evidence in runtime v9. All subsequent
campaign execution authorizations use v5 and bind
`controllerAuthorityEvidenceSha256`; an authorization for another receipt is
rejected. Capacity checks reload the bound record and recheck live deadline
consistency on all three resources. The retained controller is not deleted.

## Bootstrap, migrate, and prepare observed inputs

```powershell
Invoke-M78Phase 'bootstrap'
Invoke-M78Phase 'migrate'
```

Each Container Apps job must reach terminal `Succeeded`. Bootstrap verifies
the closed semantic principal manifest and ownership/grant model. Migration
uses the migration identity, direct `NullPool`, advisory locking, expected
revision `20260726_0029`, sole-head ordering, and exact runtime-grant
reconciliation.

Before the combined managed-evidence phase, collect the following sanitized
numeric/configuration observations under the separately authorized campaign:

- actual primary/standby zones, HA mode, maintenance day/hour, storage
  GiB/tier, backup retention, and geo-backup setting from the deployed server;
- p95 private API latency in milliseconds from the bounded synthetic exercise;
- Azure/provider-reserved connections, declared API+worker pool ceilings,
  rollout overlap allocation, non-runtime operator consumers, observed peak,
  safety reserve, and deployed `max_connections`.

For the next campaign the approved connection safety reserve is at least 20;
the total budget must be strictly below observed `max_connections`. The current
template configures four API replicas and a manual worker job with parallelism
four; configuration alone does not prove that all replicas are running or
produce verified peak/overlap and p95 measurements. Do not label those
observations complete or start the campaign until a bounded collection and
replica/rollout verification path is implemented and reviewed.

The evidence job has a `--phase measurement-sample` diagnostic that performs
bounded private readiness requests, times the existing application exercise,
and samples API/worker PostgreSQL connection counts. It reports only aggregate
values and returns `blocked-unverified` with a nonzero exit: it cannot establish
replica ceilings or rollout overlap. Its output is not a valid operations
evidence input until those provider readbacks are bound to the sample window.
The changed four-replica configuration also requires a fresh cost-gate estimate.

The local `replica_readback.collect_worker_replicas` reads complete raw ARM
pages and keeps continuations within one exact job execution. Its window checks
correlate API `properties.runningState` observations with connection and
application-request timestamps. Worker admission remains blocked because the
running-state semantics of that execution's replica response are unverified.
During a separately authorized worker execution, capture the raw response to
`GET /subscriptions/{subscriptionId}/resourceGroups/{group}/providers/Microsoft.App/jobs/{job}/executions/{execution}/replicas?api-version=2023-11-02-preview`
and any same-scope continuation pages privately; do not infer running workers
from replica presence alone. `az containerapp job replica list` is insufficient
for this proof because the installed extension returns only `value`.

Bind those observations without credentials or resource UUIDs:

```powershell
$env:M78_LATENCY_P95_MS = '<observed-nonnegative-number>'
$env:M78_AZURE_RESERVED_CONNECTIONS = '<observed-nonnegative-integer>'
$env:M78_POOL_CEILINGS = '<declared-positive-integer>'
$env:M78_ROLLOUT_OVERLAP = '<bounded-nonnegative-integer>'
$env:M78_OPERATOR_CONSUMERS = '<observed-positive-integer>'
$env:M78_OBSERVED_PEAK = '<observed-positive-integer>'
$env:M78_SAFETY_RESERVE = '<approved-positive-integer>'
$env:M78_MAX_CONNECTIONS = '<observed-positive-integer>'

$serverJson = & .\.venv\Scripts\python.exe -m infra.milestone_7_8.azure_cli `
  invoke -- postgres flexible-server show `
  --resource-group $rt.resourceGroupName `
  --name $rt.postgresServerName --output json
if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL configuration readback failed' }
$server = $serverJson | ConvertFrom-Json
$control = [ordered]@{
  primaryZone = [string]$server.availabilityZone
  standbyZone = [string]$server.highAvailability.standbyAvailabilityZone
  haMode = [string]$server.highAvailability.mode
  maintenanceDay = [int]$server.maintenanceWindow.dayOfWeek
  maintenanceHour = [int]$server.maintenanceWindow.startHour
  storageGiB = [int]$server.storage.storageSizeGb
  storageTier = [string]$server.storage.tier
  backupRetentionDays = [int]$server.backup.backupRetentionDays
  geoBackup = ([string]$server.backup.geoRedundantBackup -eq 'Enabled')
  latencyP95Ms = [double]$env:M78_LATENCY_P95_MS
  azureReservedConnections = [int]$env:M78_AZURE_RESERVED_CONNECTIONS
  poolCeilings = [int]$env:M78_POOL_CEILINGS
  rolloutOverlap = [int]$env:M78_ROLLOUT_OVERLAP
  operatorConsumers = [int]$env:M78_OPERATOR_CONSUMERS
  observedPeak = [int]$env:M78_OBSERVED_PEAK
  safetyReserve = [int]$env:M78_SAFETY_RESERVE
  maxConnections = [int]$env:M78_MAX_CONNECTIONS
}
$controlPath = '.runtime/milestone_7_8/control-plane-evidence.json'
$control | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $controlPath `
  -Encoding utf8NoBOM
```

The file must satisfy
`infra/milestone_7_8/schemas/control-plane-evidence.schema.json`. Missing,
mistyped, negative, substituted, or capacity-unsafe values fail closed. The
operator does not accept preclaimed failover, credential-recovery, tenant, or
recovery-duration booleans. It derives those only after the corresponding
managed commands reach terminal success.

## Managed evidence and disposition

```powershell
Invoke-M78Phase 'evidence' @('--control-plane-evidence', $controlPath)
Invoke-M78Phase 'dispose'
```

The evidence phase executes, in order:

1. exact API and worker catalog probes;
2. evidence-role catalog/ownership/PUBLIC checks;
3. two-user application replay/isolation exercise for canvas, node,
   duplicate-node, and edge;
4. migration-role ownership/revision/lock/reconciliation probe;
5. API `NOLOGIN`, active-session termination, and catalog readback;
6. an API-role connection-denial probe;
7. API login restoration and positive API probe;
8. forced managed PostgreSQL failover;
9. post-failover replay, forged-scope, and two-tenant isolation; and
10. exact operational/capacity assertions with measured failover duration.

Every job must terminate `Succeeded`; its harness exits nonzero on one missing
assertion. The operator persists a sanitized, source/digest/control-bound
`.runtime/milestone_7_8/managed-evidence-execution.json` containing all 12
execution identities, terminal states, and domain-separated output hashes.
The full shape is closed by
`infra/milestone_7_8/schemas/evidence-execution.schema.json`. `dispose` records
the pass/fail campaign disposition before deletion.

The intended cleanup deployment remains exactly one command in exactly the prepared
region. A deployment failure never selects another candidate, retries in a
different region, restores or reuses a soft-deleted account, or modifies an
unrelated Automation account; it enters the existing cleanup path.

## Cleanup and zero residue

Cleanup is mandatory on success, failure, interruption, or deadline expiry:

```powershell
Invoke-M78Phase 'cleanup'
Invoke-M78Phase 'cleanup-wait'
Invoke-M78Phase 'cleanup-disarm'
Invoke-M78Phase 'residue'
Invoke-M78Phase 'finalize'
```

The cleanup runbook validates campaign, generation, sanitized subscription
correlation, exact resource-group names/tags, deadline, cost ceiling, and the
bound fresh-controller-admission hash; it deletes only the target group. The stable
controller group and Automation account are deliberately retained.
`cleanup-wait` requires authoritative target absence. `cleanup-disarm` then
deletes the exact one-use binding and schedule and proves both collections
empty before residue verification.
`residue` completely paginates both active and soft-deleted Automation-account
inventories, then proves the exact stable controller is active exactly once and
has no matching deleted record. Unrelated deleted-account identities are
hashed only as observations. Campaign zero residue requires target absence,
exact schedule/binding disarm, zero tagged campaign resources, zero
target-scoped role assignments, and all 14 campaign-owned residue counters at
zero. It never treats the retained controller as campaign residue and never
requires any deleted-account record to age out. Only that complete proof can
advance to `residue-verified` and print the v7 terminal receipt. If the runbook
cannot be started, the operator automatically falls back to deletion of only
the validated target resource group and immediately reports exact active and
soft-deleted account counts from complete inventories. It never broadens the
deletion target.

That phase behavior applies only to a future v7 bundle after fresh-scope
predeployment evidence is hash-bound, the controller is separately
bootstrapped or adopted, and execution is separately authorized. The preserved
private generation predates the retained-controller and campaign-only-residue
contracts; its legacy `finalized` state is retained as disproved historical
evidence. It must not be rewritten or passed to this operator as a resumable
lifecycle. The historical retained account may be reconciled only under its
historical audit contract; that read is not a campaign phase, does not mutate
the private files, and cannot become a fresh controller-admission gate.

## Failure and interruption recovery

After scope creation, every operator exception starts cleanup and advances the
ledger to `cleaning`. Resume by reading `ledger.json` and invoking only the
operation that maps to the next state:

| Ledger state              | Resume operation                                   |
| ------------------------- | -------------------------------------------------- |
| `new`                     | `preflight`                                        |
| `preflight`               | `correlate`                                        |
| `correlated`              | `capacity-check`                                   |
| `capacity-checked`        | `cost-gate`                                        |
| `cost-gated`              | `scope-create`                                     |
| `scope-created`           | `cleanup-deploy`                                   |
| `cleanup-deployed`        | `cleanup-arm`                                      |
| `cleanup-armed`           | `cleanup-verify`                                   |
| `cleanup-verified`        | `billable-start`                                   |
| `billable-started`        | `deploy`                                           |
| `infrastructure-deployed` | `image-decision` with the same digest/scan receipt |
| `image-decided`           | `bootstrap`                                        |
| `database-bootstrapped`   | `migrate`                                          |
| `migrated`                | `evidence` with the same control file              |
| `evidence-executed`       | `dispose`                                          |
| `disposed`                | `cleanup`                                          |
| `cleaning`                | `cleanup-wait`                                     |
| `cleaned`                 | `cleanup-disarm`                                   |
| `cleanup-disarmed`        | `residue`                                          |
| `residue-verified`        | `finalize`                                         |

If all managed evidence commands completed but the process stopped before its
ledger write, rerunning `evidence` validates and consumes the immutable local
execution receipt without rerunning the managed probes. A changed campaign,
generation, source, digest, control input, transition chain, deadline, or
receipt is rejected. Once cleanup starts, resume only cleanup, wait, disarm,
residue, and finalization; cleanup remains allowed after the deadline.

This resume table describes only a conforming v6 ledger. It does not reopen or
upgrade the preserved legacy finalized ledger described above.

## Bounded time, cost, artifacts, and stopping rule

The first billable mutation starts a maximum four-hour clock. The conservative
full-hour estimate is USD 25.6832 with 25 percent contingency and a hard USD 50
ceiling. Stop normal evidence work immediately on any assertion failure, cost
projection over USD 50, expired deadline, cleanup drift, or unready managed
service; enter cleanup and preserve the sanitized local files:

- `campaign.json`, `runtime.json`, parameter files, and `ledger.json`;
- the copied fresh-controller-admission artifact and its domain-separated hash;
- the sanitized cleanup-region selection receipt and its bound hashes;
- the digest-bound image scan receipt;
- the sanitized control-plane evidence input;
- the managed execution receipt; and
- the residue disposition and evidence hash; and
- only after complete absence proof, the finalized zero-residue terminal
  receipt.

These artifacts contain no secret values or raw tenant/subscription identifiers
other than the private ignored `runtime.json`, which must not be committed or
printed. A successful campaign may close only the five managed gaps actually
proved by the artifacts. It does not complete Milestone 7.8 and does not start
the object-storage audit.
