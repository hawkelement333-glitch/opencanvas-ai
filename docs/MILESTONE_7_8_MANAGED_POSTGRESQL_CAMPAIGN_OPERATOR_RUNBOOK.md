# Milestone 7.8 managed PostgreSQL campaign operator runbook

Date: 2026-08-13

Status: executable repository contract; managed execution requires a separate
authorization

This runbook is the exact independent path from zero campaign resources to
zero residue. It does not reuse Milestone 7.7 infrastructure, identifiers,
deadlines, receipts, or lifecycle state. Do not run it until the managed
PostgreSQL campaign, one image build/publication, and one image admission scan
are separately authorized.

## Prerequisites and authority

Run from the repository root on branch
`milestone-7-8-production-readiness-audit-local`, at the reviewed campaign
commit, with a clean tree/index, no upstream, and exactly five untouched
stashes. The output directory `.runtime/milestone_7_8` must not exist.

The interactive deployment operator needs only the Azure control-plane actions
required to create the two generated resource groups and the resource types in
`infra/milestone_7_8/main.bicep` and `cleanup.bicep`, plus
`Microsoft.Authorization/roleAssignments/write/delete` on those exact two
generated resource-group scopes. It must not receive database credentials. The
deployed identities are narrower:

Before any generation directory exists, preparation also needs read-only
access to the Automation provider metadata, active and soft-deleted Automation
account locations, applicable policy assignments/definitions, and the current
AzureCloud account correlation. Those reads return only locations, counts, and
sanitized hashes to persisted evidence; account names and ARM identifiers are
not retained.

| Identity  | Azure authority                                                                                          | PostgreSQL authority                                                                                      |
| --------- | -------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| Bootstrap | ACR pull; Flexible Server Entra administrator binding                                                    | create/verify the four non-cleanup database principals; transfer application ownership; reconcile grants  |
| Migration | ACR pull only                                                                                            | `CONNECT`, database/schema creation needed by reviewed Alembic, and ownership of application objects      |
| API       | ACR pull only                                                                                            | literal API table matrix: 150 SELECT, 149 INSERT, 17 UPDATE, 9 DELETE; no sequence/function/DDL authority |
| Worker    | ACR pull only                                                                                            | literal worker table matrix: 55 SELECT, 18 INSERT, 6 UPDATE, 1 DELETE; no sequence/function/DDL authority |
| Evidence  | ACR pull only                                                                                            | `CONNECT` and `pg_monitor`; no database/schema creation or application ownership                          |
| Cleanup   | Contributor plus Role Based Access Control Administrator on the two exact generated resource groups only | none                                                                                                      |

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

## Prepare one generation

Set the exact later-authorized Azure identifiers in memory and choose one
campaign label matching `^[a-z][a-z0-9-]{7,47}$`:

```powershell
$env:M78_SUBSCRIPTION_ID = '<authorized-subscription-uuid>'
$env:M78_TENANT_ID = '<authorized-tenant-uuid>'
$campaign = 'mobius78-pg-evidence'

$env:PYTHONDONTWRITEBYTECODE = '1'
.\.venv\Scripts\python.exe -m infra.milestone_7_8.prepare `
  --campaign-id $campaign `
  --output .runtime/milestone_7_8 `
  --target-region centralus `
  --postgres-region centralus
if ($LASTEXITCODE -ne 0) { throw 'campaign preparation failed' }

$config = '.runtime/milestone_7_8/campaign.json'
$runtime = '.runtime/milestone_7_8/runtime.json'
$ledger = '.runtime/milestone_7_8/ledger.json'
$cleanupRegionEvidence = '.runtime/milestone_7_8/cleanup-region-selection.json'
```

Preparation refuses a dirty tree, wrong branch, upstream, stash-count drift,
malformed UUID/campaign, mismatched target/PostgreSQL region, or an existing
output directory. It has no caller-supplied cleanup-region override. Before
creating the output directory, it evaluates the exact order `eastus2`,
`southcentralus`, `westus2`, `westus` against normalized provider support,
subscription-offer eligibility, enforced location policy, active account
occupancy, and discoverable soft-deleted occupancy. A candidate is armable only
when all four independent admission dimensions pass. The offer-safe baseline
is `eastus,eastus2,northeurope,southeastasia,westus`; Free Trial/Student and
unclassified public offers cannot broaden it. The documented `JapanWest2`
token is not treated as the provider's `japanwest` token without authoritative
alias proof. There is no caller-supplied offer class, allowlist, cleanup region,
or bypass. Discovery failure or an empty intersection stops without a
generation, ledger, or hard-coded fallback.

The first viable candidate and hashes of provider, offer eligibility, active,
soft-deleted, and policy evidence are written to the closed selection receipt.
The offer classification or restrictive-baseline disposition, normalized
eligible-region set, and source/version identifier are also bound. Its
domain-separated receipt hash is repeated in campaign configuration, private
runtime, both Bicep parameter files, lifecycle tags, and later ledger/readback
evidence. Preparation creates exactly one generation and a cleanup deadline
four hours in the future. It never prints either raw Azure UUID.

## Dry-run and execute phases

Every operator phase is dry-run unless `--execute` is present. Before each
mutation, inspect the redacted command plan:

```powershell
function Invoke-M78Phase([string]$Phase, [string[]]$Extra = @()) {
  & .\.venv\Scripts\python.exe -m infra.milestone_7_8.operator $Phase `
    --config $config --runtime $runtime --ledger $ledger @Extra
  if ($LASTEXITCODE -ne 0) { throw "dry-run blocked: $Phase" }
  & .\.venv\Scripts\python.exe -m infra.milestone_7_8.operator $Phase `
    --config $config --runtime $runtime --ledger $ledger --execute @Extra
  if ($LASTEXITCODE -ne 0) { throw "execution blocked: $Phase" }
}

Invoke-M78Phase 'preflight'
Invoke-M78Phase 'correlate'
Invoke-M78Phase 'capacity-check'
Invoke-M78Phase 'cost-gate'
Invoke-M78Phase 'scope-create'
Invoke-M78Phase 'cleanup-deploy'
Invoke-M78Phase 'cleanup-arm'
Invoke-M78Phase 'cleanup-verify'
Invoke-M78Phase 'billable-start'
Invoke-M78Phase 'deploy'
```

The `capacity-check` dry-run exposes 16 static Azure commands. Six are the
subscription context, subscription-policy metadata, Automation provider,
active-account, soft-deleted-account, and policy-assignment reads; enforced
policy definitions and deny-capable initiative members produce explicit
generated GETs. Execution repeats preparation's complete offer-aware selector
and requires the immutable region, decision hash, offer binding, and every
evidence hash to match. Any change stops before `scope-create`.

The complete static operator plan contains 56 commands, 50 of them Azure CLI
commands. It also has bounded generated Container Apps job polling, failure
cleanup, and exact-two-group direct cleanup. Preparation's regional selection
has six static Azure reads plus generated policy-definition GETs. Every Azure
path uses the centralized launcher; no unrelated Automation account name is a
command target.

The sequence proves local source/hash/Git state, Azure subscription/tenant
correlation, six provider registrations, PostgreSQL SKU, regional compute
quota, global names, USD 25.6832 estimate, at least 25 percent contingency,
the USD 50 ceiling, exact scope tags, cleanup deployment outputs, published
runbook content, one immutable schedule, one binding, actual cleanup identity,
and exact cleanup deadline before the billable clock starts. The `deploy`
phase is base infrastructure only; no application job exists yet.

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

The cleanup deployment remains exactly one command in exactly the prepared
region. A deployment failure never selects another candidate, retries in a
different region, restores or reuses a soft-deleted account, or modifies an
unrelated Automation account; it enters the existing cleanup path.

## Cleanup and zero residue

Cleanup is mandatory on success, failure, interruption, or deadline expiry:

```powershell
Invoke-M78Phase 'cleanup'
Invoke-M78Phase 'cleanup-wait'
Invoke-M78Phase 'residue'
Invoke-M78Phase 'finalize'
```

The cleanup runbook validates campaign, generation, sanitized subscription
correlation, exact resource-group names/tags, deadline, and cost ceiling; it
deletes the target group and then its own cleanup group. `cleanup-wait` requires
both groups absent. `residue` separately requires zero tagged resources and
zero role assignments plus all defined residue counters at zero. `finalize`
prints the sanitized terminal receipt. If the runbook cannot be started, the
operator automatically falls back to deletion of only the same two validated
resource groups. It never broadens the deletion target.

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
| `cleaned`                 | `residue`                                          |
| `residue-verified`        | `finalize`                                         |

If all managed evidence commands completed but the process stopped before its
ledger write, rerunning `evidence` validates and consumes the immutable local
execution receipt without rerunning the managed probes. A changed campaign,
generation, source, digest, control input, transition chain, deadline, or
receipt is rejected. Once cleanup starts, resume only cleanup, wait, residue,
and finalization; cleanup remains allowed after the deadline.

## Bounded time, cost, artifacts, and stopping rule

The first billable mutation starts a maximum four-hour clock. The conservative
full-hour estimate is USD 25.6832 with 25 percent contingency and a hard USD 50
ceiling. Stop normal evidence work immediately on any assertion failure, cost
projection over USD 50, expired deadline, cleanup drift, or unready managed
service; enter cleanup and preserve the sanitized local files:

- `campaign.json`, `runtime.json`, parameter files, and `ledger.json`;
- the sanitized cleanup-region selection receipt and its bound hashes;
- the digest-bound image scan receipt;
- the sanitized control-plane evidence input;
- the managed execution receipt; and
- the finalized zero-residue terminal receipt.

These artifacts contain no secret values or raw tenant/subscription identifiers
other than the private ignored `runtime.json`, which must not be committed or
printed. A successful campaign may close only the five managed gaps actually
proved by the artifacts. It does not complete Milestone 7.8 and does not start
the object-storage audit.
