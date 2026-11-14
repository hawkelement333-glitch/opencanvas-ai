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

All nine Container Apps job names must be 2 to 32 characters, start with a
lowercase letter, end with a lowercase letter or digit, and contain only
lowercase letters, digits, and single hyphens. Preparation and the template
use `job-m78-<10-hex-generation-suffix>-probe-migrate` for the migration probe
(32 characters). Runtime admission rejects invalid names before any operator
Azure request. Historical bundles and receipts are never renamed in place.

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
generated GETs. Execution repeats preparation's complete offer-aware selector.
The original selection receipt must still match its immutable prepared hash.
The refresh must preserve the entire admitted decision: selected region,
ordered candidate set, provider support and status for every candidate, offer,
policy, occupancy, and controller bindings. A global provider-location hash
change alone may pass only when those complete validated decisions are equal;
it cannot hide a capability change within the admitted candidate set. Both
full inventory hashes and captured responses remain audit evidence. No receipt
or hash is substituted or rewritten. Any other change stops before
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
quota, global names, a current itemized estimate, at least 25 percent contingency,
the USD 50 ceiling, exact scope tags, cleanup deployment outputs, published
runbook content, one immutable schedule, one binding, actual cleanup identity,
and exact cleanup deadline before the billable clock starts. The campaign
cleanup deployment creates only exact target-scoped RBAC against the existing
controller; it creates zero schedules and zero job-schedule bindings.
`cleanup-arm` verifies deployment, identity, authority, previously published
state and exact content, reconciles or creates the immutable schedule, and
reconciles or creates the deterministic binding. A failure at any earlier step cannot advance the ledger to
`cleanup-armed`. The `deploy` phase is base infrastructure only; no application
job exists yet. Check `Microsoft.Network` registration separately before
`scope-create` because the base template creates virtual networking and the
operator's six-provider check does not cover it.

The base `deploy` command alone may wait up to 3,600 seconds, bounded further
by the actual time remaining before the campaign cleanup deadline. The operator
rechecks that window inside its failure-cleanup boundary immediately before
constructing the deployment runner. An exhausted window dispatches no base
write and enters cleanup. Other commands, including failure cleanup and workload
deployment, keep the ordinary 900-second command timeout. A timeout is an
ambiguous provider outcome, not proof that ARM stopped: preserve the attempt,
pause dependent work while cleanup protection, budget, and authority remain valid.
Never retry the deployment or promote a failed ledger from a later successful
readback; this path has no deployment redispatch recovery mode. The observed CLI failure near 900 seconds while
ARM continued is consistent with the previous timeout; its underlying
`TimeoutExpired` exception was not retained, so that diagnosis is not proven.
New CLI timeouts retain their exception cause and report only the sanitized
`Azure CLI process timed out` diagnostic. This does not establish termination
of an Azure operation or change Windows child-process handling. If fallback
cleanup finds the exact ownership-checked group already `Deleting`, it sends
no second delete request. The ledger remains in cleanup until the normal wait
and residue checks establish absence; matching ownership tags alone cannot
establish completion.

After the base deployment, read the exact Container Apps environment's
`ManagedEnvironmentConsumptionCores` usage before building the image or
deploying the workload. Require at least 14 vCPUs of available quota for the
eight API replicas, four workers, and one sampler during revision overlap.
An absent, incomplete, or insufficient quota readback requires campaign cleanup.

### Deployment and cleanup failure review

The finalized Canada Central attempt at source `4610daa` is unsuccessful, not
resumable. Its retained operations show the server creation completing before
the Entra administrator and `azure.extensions` writes started together. The
administrator failed with `AadAuthOperationCannotBePerformedWhenServerIsNotAccessible`;
the configuration write succeeded. The template now orders server creation,
administrator, extension configuration, and application database serially.
This removes a demonstrated parallel-write hazard without adding sleeps,
retries, public PostgreSQL access, identities, or network resources. A similar
concurrency failure is recorded in the
[Azure PostgreSQL issue](https://github.com/Azure/azure-postgresql/issues/127).
That report supports the ordering correction, not a claim that it proves the
sole cause of this attempt's provider failure.

The retained later server read reported `Ready`. The subnet had no NSG or route
table, used a Storage service endpoint, and had no explicit NAT gateway. There
is no retained server-state observation at the failed administrator dispatch,
or server-side Entra DNS/egress trace. Do not treat the later `Ready` read as
proof of earlier readiness or add a NAT gateway based only on this error.
[Microsoft's Entra requirements](https://learn.microsoft.com/en-us/azure/postgresql/security/security-entra-configure)
still apply. If a separately approved future deployment fails after serialized
writes, preserve its operation records and follow cleanup; do not silently
retry the administrator or relax networking.

The failed cleanup job's 17 saved parameters and exact binding parameters match
offline. These are CLI-captured records, not the exact bytes or bound variable
types seen by `Invoke-AzRestMethod` inside Automation. The failing field is
therefore unproved. The runbook now emits only a trusted parameter name and
fixed reason (`value`, `type-*`, `expected-type`, `missing`, or `duplicate`);
unknown provider keys and all parameter values remain private. Exact strings,
parameter-set checks, authority hashes, identity, ownership, and roles remain
mandatory.

Full-runbook synthetic replay also covers the actual ARM jobSchedule shape:
when top-level `name` is absent, require both the exact full resource `id` and
`properties.jobScheduleId`; reject any supplied conflicting identity. Cast a
JSON-coerced schedule DateTime directly to DateTimeOffset to preserve UTC,
rather than round-tripping through a local-culture string. These local tests
do not establish Azure Automation's live behavior. The old terminal receipt,
publication evidence, and failed-job records remain immutable. Publishing this
new runbook needs a new reviewed source/content transition using the accepted
predecessor evidence, as documented below. Offline replay is not live admission.

The later pre-billable attempt identified `CleanupAuthorized:value`. Its saved
invocation, job, and binding all contain the string `true`; the runbook's
in-memory argument and its own binding response were not captured. Do not infer
a live type conversion from those records. Full-runbook local replay does prove
that PowerShell's existing affirmative parameter validation accepts `True` (and
an affirmative Boolean converted to a string), while the subsequent exact
comparison rejected it. After that validation, the expected binding value is
now the canonical string `true`. The binding must still contain that exact
string; false, malformed or non-string binding values remain rejected. Other
parameters, authority hashes and ownership checks are unchanged. The field-only
diagnostic distinguishes an unexpected binding value without exposing it.
The ownership-checked fallback, disarm, residue and finalization records for the
failed attempt remain historical evidence; they do not prove this correction
has executed successfully in Automation.

## One image decision

Use the build route when the canonical image inputs changed or no exact retained
image and provenance are available. The retained-image route applies when a
separately approved image has the same canonical build inputs as the prepared
execution source. The template creates a Premium registry with public access
disabled and a private endpoint. A hosted
`az acr build` is not an established access path for that configuration; neither
the retained records nor the template establish a private build agent or a
workstation route. Docker Scout's `registry://` path also needs authenticated
registry data-plane access. Do not run a build merely because ARM reads work.

The executable local path uses the installed Linux Docker engine and Scout on
the workstation. It requires separate approval for temporary registry network
access, the chosen image operation, one push, one digest read, one scan and
network restoration. No VM, agent pool, VPN,
role, or trusted-task bypass is added. Before requesting that approval:

1. Bind a fresh private registry GET to the new bundle's subscription, group,
   registry ID, Premium SKU, disabled public access, and disabled admin/anonymous
   access. Save its exact network settings. Verify existing operator push/pull
   permission; otherwise stop and request that exact missing permission.
2. Verify the workstation and Docker Desktop proxy's public IPv4 egress again.
   The old matching observation is historical. Require the same single `/32`,
   and preserve it only privately. Check current policy permits this change.
3. Review two exact registry PATCH bodies at
   `https://management.azure.com/subscriptions/{runtimeSubscription}/resourceGroups/{targetGroup}/providers/Microsoft.ContainerRegistry/registries/{registryName}?api-version=2025-11-01`.
   The first atomically sets `publicNetworkAccess: Enabled` and
   `networkRuleSet: {defaultAction: Deny, ipRules: [{action: Allow, value: <verified-/32>}]}`.
   Never enable public access while the default is Allow. Preserve Private Link,
   trusted-service bypass, identities, roles, tags, and all other settings.
   The second restores the saved network settings and disabled public access.
4. Require successful provisioning/readback of the first PATCH before push or
   scan. The opened readback may serialize the exact approved single IPv4 `/32`
   as its bare address; only those two spellings of that one Allow rule are
   equivalent. All other fields remain exact, raw responses remain unchanged,
   and completion replays the same check. Restoration still requires the exact
   saved network settings. Restore and verify the second on success, scan
   rejection, interruption, or deadline failure. A lost PATCH response needs GET
   reconciliation, not an automatic mutation retry. A restoration failure blocks
   workload admission and requires the already approved ownership-checked cleanup.

These are supported
[Premium IP access controls](https://learn.microsoft.com/en-us/azure/container-registry/container-registry-access-selected-networks)
and [registry update operations](https://learn.microsoft.com/en-us/rest/api/container-registry/registries/update?view=rest-container-registry-2025-11-01).
They are a proposed temporary public-IP exception, not unchanged private-only
networking. This correction does not apply or authorize either PATCH.

After the 14-vCPU gate, save the reviewed exact registry response as a private
JSON object (`$registryBefore`) and the verified single IPv4 in process memory
(`$verifiedEgress`). The local planner starts no approval window. All paths below
must be inside the protected ignored runtime directory; the output directory
`$bundle/local-image` and marker `$bundle/local-image-attempt.json` must not exist.
Use the same cost config and ledger as every campaign phase:

Before `scope-create --execute` can issue an Azure command, the operator probes
the complete committed canonical source at the actual
`$bundle/local-image/source` staging paths. It checks source bytes and file modes
using the same archive/extraction path as the builder, then removes only the
probe's own staging files. An existing staging directory or attempt marker is
preserved and blocks this probe. Extraction or probe-removal failure leaves the
ledger at `cost-gated`, without dispatching resource creation or failure cleanup.
Use a short, ignored private output directory on Windows; checking only the
bundle directory length does not establish that every generated path works.
No Windows long-path or security setting is changed by this check.
The archive command disables automatic newline conversion for that invocation
only (`git -c core.autocrlf=false -c core.eol=lf ... archive`). Otherwise a
Windows checkout with `core.autocrlf=true` can archive CRLF bytes that differ
from the bound Git blobs. The repository's Git configuration is unchanged;
every extracted file must still match its exact Git blob hash and executable
mode. Do not normalize archive contents or substitute a different input hash
to make this validation pass.

```powershell
$imagePlan = "$bundle/local-image-plan.json"
# For the retained route, append --retained-image with the approved private
# retained-image.json path. Leave that argument absent to plan a new build.
.\.venv\Scripts\python.exe -m infra.milestone_7_8.local_image plan `
  --runtime $runtime --config $config --ledger $ledger --plan $imagePlan `
  --registry-before $registryBefore --egress-ipv4 $verifiedEgress
if ($LASTEXITCODE -ne 0) { throw 'local image plan validation failed' }
# Stop here for approval of the exact plan. At execution readiness only:
$imageApproval = "$bundle/local-image-approval.json"
.\.venv\Scripts\python.exe -m infra.milestone_7_8.local_image approve `
  --runtime $runtime --config $config --ledger $ledger --plan $imagePlan `
  --approval $imageApproval --expires-at $reviewedImageExpiry `
  --restore-until $reviewedRestorationExpiry
# Image expiry is at most one hour, within the campaign deadline. Restoration
# may continue only through its separately approved cleanup-authority deadline.
if ($LASTEXITCODE -ne 0) { throw 'local image approval validation failed' }
.\.venv\Scripts\python.exe -m infra.milestone_7_8.local_image execute `
  --runtime $runtime --config $config --ledger $ledger --plan $imagePlan `
  --approval $imageApproval --cleanup-authorization $failureCleanupAuth --execute
if ($LASTEXITCODE -ne 0) { throw 'image attempt failed; inspect cleanup ledger and private results' }
$imageResult = Get-Content -LiteralPath "$bundle/local-image/completed.json" -Raw | ConvertFrom-Json
$digest = $imageResult.imageDigest
$scan = "$bundle/local-image/image-scan.json"
# Separately authorized image-decision consumes $digest/$scan and deploys the
# workload using the existing operator. local_image itself never deploys it.
```

For a new build, the executor archives only canonical tracked inputs from the
exact clean source commit, verifies those bytes, builds Linux/amd64 once, and
checks source/input labels and the 2-GiB size cap before push.

For a retained image, the plan binds its original image build source, immutable
image ID, canonical build input hash, Linux manifest digest and the private
provenance file hashes. The original build source and the prepared execution
source must independently yield the same canonical build input hash. Review and
approve the retained-image operation for that exact plan. Before changing
registry access, the executor inspects the exact Linux/amd64 image ID on the
workstation and verifies its original source and input labels and size. It tags
that immutable ID with the approved registry reference and pushes once. The
pushed digest must be the verified retained index ID or Linux manifest digest,
and both the local RepoDigest and the registry manifest read must confirm it.
The retained route performs zero builds. Its completion records the executing
source HEAD, original image build source and original retained image ID
separately. Keep the original private provenance available and unmodified for
completion validation, which recomputes its hashes.

Both routes require a fresh assessment of the exact pushed digest. Scout uses
`--platform linux/amd64`, including on Windows hosts. Raw command responses,
image provenance, SARIF, approvals and network snapshots stay private.
Completion is written only after verified network restoration. The normal
`image-decision` entry point validates that completion whenever the local attempt
marker exists; a pending scan or failed restoration cannot advance this route.
Within this same authorized image attempt, the executor permits at most one
additional Scout command for an observed transport failure: exit code 1, no
SARIF file, and an explicit connection reset, TLS handshake timeout, I/O timeout,
or unexpected EOF in retained stderr. The image digest, Linux platform, severity
filter, network scope and existing approval remain unchanged. It checks expiry
immediately before dispatch. The first command response stays private and intact;
the second command uses the separate `scout.retry.sarif.json` output.

Exit code 2 never qualifies. Any existing report, findings, malformed or
contradictory report/exit status, unknown failure, missing response, or failed
response persistence stops this path. Deterministic flag, platform and
authentication errors are not repeated unchanged. A second failure proceeds to
restoration and a protected stage pause; there is no third command, rebuild, repush, new approval,
or restart of an earlier image attempt. Completion replay requires both exact
command/response records, an admissible first transport failure, a clean final
report and verified restoration. One successful assessment is recorded in the
campaign scan ledger; both command attempts remain in the private history.
This bounded recovery does not increase the existing time, transfer or budget
allowances and cannot admit the historical image with reported vulnerabilities.
There is no automatic build, push or PATCH retry. With verified registry
restoration and valid cleanup protection, budget and authority, scan/build
failures pause the stage and block image admission. High/Critical findings
remain failed and never cause an unchanged automatic scan retry. Unproved
restoration, expiry, established budget exhaustion or other established
terminal failure uses the existing cleanup path through verified residue. A process crash can prevent local restoration/cleanup dispatch; retain
the intents, inspect the exact registry under separate read authority, and use
the already armed deadline cleanup. Matching state cannot invent missing history.
Windows ACL and directory crash-durability limitations remain those documented
below; Unix file modes alone do not establish Windows privacy.

The local routes have zero incremental Azure build compute/resource cost. Keep
the existing build allowance as contingency rather than claiming a saving
before execution. Public Azure pricing refreshed November 12, 2026 lists incoming
transfer as free and North American internet egress at USD 0.087/GB before
volume discounts, ignoring the free tier. A 2-GiB image cap and 4-GiB external
retrieval allowance contribute USD 0.3737 to the shared USD 2 network allowance.
Together with one endpoint for five hours (USD 0.05), 100 GB private processing
(USD 1), 20 GB cross-region traffic (USD 0.40), and 100,000 DNS queries (USD 0.04),
the network estimate is USD 1.8637. Actual image size and all campaign transfers
must fit that allowance before push. Otherwise revise the itemized estimate
and rerun the cost gate. The refreshed offline replacement estimate is USD
49.4083 including 25% contingency; apply its cost fields to the new prepared
bundle and run the actual gate. It covers this campaign and one hour of cleanup
overrun, not prior attempts or retained-controller standing costs. It is an
estimate, not a billing guarantee. No Docker subscription purchase is authorized; use existing Scout
entitlement or stop if unavailable.
[Bandwidth pricing](https://azure.microsoft.com/en-us/pricing/details/bandwidth/).

The separately authorized admission scanner must scan that exact digest and
write a private receipt in the fresh bundle, conforming to
`infra/milestone_7_8/schemas/image-scan.schema.json`. The receipt records the
prepared execution source HEAD and canonical build input hash and must report
zero High and zero Critical findings. For a retained image, the original
build source is verified separately in the plan, image labels and provenance.
Validate and deploy the workload only after the receipt exists.

The local-image route already performs that scan; do not scan again. For a
different separately approved access route, the existing Scout entry point runs one digest-pinned
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

This command requires separate live authorization. Managed registry execution
remains to be verified. The digest must come from the one authorized campaign
push and its registry readback.

```powershell
# Restore disabled registry access and verify its readback before admission.
$scan = "$bundle/image-scan.json"
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
before-readback digest. Newly planned renewals also bind the exact plan hash
(`approvalBinding: exact-plan-v1`, `renewalPlanSha256` in the approval), including
the immediate predecessor evidence and executing source identity. Retained
approvals without these fields remain valid under their original contracts.
All preservation and completion hashes are independently
recomputed; the two success booleans are insufficient without the responses.
Approval of an exact old/new transition can explicitly cover an already-expired
old deadline, but historical approval never becomes current execution authority.

For the existing verified controller, each separately authorized
renewal attempt may use the locally tested executor and the read-only snapshot
and reconciliation paths below. This permission is limited to the three planned
deadline-tag Merge requests on that controller's group, Automation account, and
runbook. Validate the exact plan, current approval, protected private storage,
and seven-read baseline before dispatch; preserve the complete executor journal
and all before/after readbacks. The snapshot and reconciliation paths have
synthetic tests and retained live evidence; a new attempt's Azure Merge
behavior and preservation remain unproved until its separately authorized
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
Separately authorized subsequent renewals of the existing controller may
use the immediately preceding validated completion evidence as `$anchor`. The planner
binds that entire prior evidence and its final readback, including the previously
verified deadline, into the new plan. The new completion retains the unmodified
bootstrap and complete preceding transition evidence. Publications and renewals
may repeat in either order; neither resets the history. Choose the new deadline
at execution and verify it extends at least
five hours past the actual campaign preparation time.

When the current checkout contains a corrected, not-yet-published script, the
renewal plan may separately bind its `sourceCleanupScriptSha256`. This is the
executing source file, not a claim that those bytes are deployed. The renewed
config retains the previously accepted deployed script hash, and both baseline
and reconciliation must still read exactly that content. The plan and approval
bind both identities. This permits renewal before publication from the same
clean commit without weakening the source check or changing deployed tags.

```powershell
$head = (git rev-parse HEAD).Trim()
$sourceScriptHash = (Get-FileHash infra/milestone_7_8/scripts/Remove-M78Campaign.ps1 -Algorithm SHA256).Hash.ToLowerInvariant()
.\.venv\Scripts\python.exe -m infra.milestone_7_8.controller_renewal `
  --operation plan --authority-evidence $anchor --source-head $head `
  --source-cleanup-script-sha256 $sourceScriptHash --deadline $reviewedNewDeadline `
  --output $plan
# After explicit baseline-read approval, use before-snapshot above. Build the
# mutation artifact with build_approval(anchor, plan, before, issued_at=...,
# expires_at=..., now=...) only after approval; do not start a window in planning.
.\.venv\Scripts\python.exe -m infra.milestone_7_8.controller_renewal `
  --operation execute --authority-evidence $anchor --plan $plan `
  --approval $mutationAuth --before-readback $before --journal-dir $journal --execute
# Separate GET-only approval and reconciliation above must pass before adoption
# or using its 02-completed-authority-evidence.json as the next $anchor.
```
An early lost response, missing dispatch record, incomplete journal, nonzero
final response without a complete journal, or any changed unrelated field stays
blocked; matching tags do not reconstruct dispatch history. A process crash
after dispatch but before the dispatch record likewise needs manual investigation
and remains inadmissible. File contents are flushed and fsynced; directory-entry
crash durability has not been independently tested. The designated review
directory's current-user-only ACL and child inheritance were checked locally;
recheck the selected private output directory and its inherited ACL at execution.

### In-place cleanup runbook publications

Use the last validated authority evidence as `$anchor` and keep it intact. The
publication plan binds the entire prior record, the old script hash, the corrected
source and script hash, and exactly two subscription-scoped commands on
`Remove-M78Campaign`. Create the plan from the clean approved branch into a new
file under an ACL-checked, ignored private directory. Its location is part of the
plan hash and fixes the attempt directory. Plan generation makes no Azure
requests and starts no approval window.

```powershell
$publicationRoot = '<new-directory-under-the-protected-private-runtime-root>'
$plan = "$publicationRoot/plan.json"
.\.venv\Scripts\python.exe -m infra.milestone_7_8.controller_publication plan `
  --evidence $anchor --output $plan
```

After explicit approval of that plan and its expiry, run the following from the
repository root. Set `$planSha256` to the reviewed plan hash, `$expiresAtUtc` to
the approved expiry at or before the retained controller deadline, and leave the
attempt directory absent until dispatch. Recheck the five-hour horizon at actual
campaign preparation. Publication cannot extend the controller deadline.

```powershell
$approval = "$publicationRoot/approval.json"
$attempt = "$publicationRoot/$($planSha256.Substring(0, 24))"
.\.venv\Scripts\python.exe -m infra.milestone_7_8.controller_publication authorize `
  --evidence $anchor --plan $plan --plan-sha256 $planSha256 `
  --expires-at-utc $expiresAtUtc --output $approval
if ($LASTEXITCODE -ne 0) { throw 'runbook publication authorization failed' }
.\.venv\Scripts\python.exe -m infra.milestone_7_8.controller_publication execute `
  --evidence $anchor --plan $plan --plan-sha256 $planSha256 `
  --approval $approval --output $attempt --execute
if ($LASTEXITCODE -ne 0) { throw 'runbook publication or verification failed' }
```

Execution takes the existing seven scoped reads before either write. It requires
the old published bytes and complete empty schedule and binding inventories.
It then runs `az automation runbook replace-content` once using the bound source
file, followed by `az automation runbook publish` once for the same runbook.
The same seven reads must succeed afterward. The published content GET must hash
to the corrected script. The group, account, identity, roles, tags, deadline,
and runbook configuration must be preserved, allowing only runbook publication
metadata to change. The original script-hash tags remain the bootstrap binding.

Use the resulting `$attempt/controller-authority-evidence.json` for campaign
preparation or the next renewal/publication. Every new publication retains the
entire immediately preceding accepted record in `priorAuthorityEvidence`;
the root bootstrap fields remain identical and its root `renewal` is null.
New renewal records retain the prior publication or renewal in the same way.
The retained legacy publication overlay and original bootstrap/direct-renewal
records are validated unchanged. Each transition binds its plan, source,
approval, attempts, before/after readbacks and proof. Publication can use the
same source commit as the preceding renewal but must change published content.
Discovery checks the exact current published content again even if a later
publication returns to the bootstrap bytes. A failed or ambiguous
dispatch, an incomplete readback, or a preservation mismatch produces no admitting
record. Keep the attempt and investigate using scoped reads before considering
any further write. Fake-provider integration exercises publication → renewal →
publication → renewal through the production planners, executors, reconciler,
discovery and campaign admission. Retained live publication evidence does not
prove a future publication. Directory-entry crash durability remains unproved.
There is no automatic retry or publication lost-response reconciliation writer;
an incomplete publication remains blocked pending a separately reviewed recovery.

Preparation copies and hash-binds this evidence in runtime v9. All subsequent
campaign execution authorizations use v5 and bind
`controllerAuthorityEvidenceSha256`; an authorization for another receipt is
rejected. Capacity checks reload the bound record and recheck live deadline
consistency on all three resources. The retained controller is not deleted.

Within one top-level historical authority validation, an identical complete
canonical evidence record may reuse its successfully validated immutable
configuration. Every distinct predecessor and its preservation checks still
validate; changed content cannot reuse the prior result. The cache is discarded
when that call ends, including on failure. It never caches current time, source
checks, campaign admission, or live readbacks across calls, and it never replaces
the required scoped Azure observations.

### One corrected image in the existing startup attempt

The retained-image route verifies the complete canonical Git archive without
extracting an unused build context. New image builds still require extraction.
For the specifically retained pre-push Windows path failure at operator
`ba7308dd0bbae01564b20fdb974fea876b370eea`, one separately approved continuation
may use `--previous-plan "$bundle/image-continuation/plan.json"` and
`--plan "$bundle/image-continuation-r1/plan.json"` with the plan command below.
The predecessor validator requires its exact nine command outcomes, complete
canonical archive, original approval, verified registry restoration, and pause.
It rejects missing, altered, or additional dispatch history. All predecessor
artifacts remain in place; the new attempt uses its own plan, approval, and
journal. No old intent is replayed. Only accepted replacement admission resolves
that exact historical image pause for normal bootstrap. Missing completion,
another pause, partial workload updates, and uncertain registry restoration
remain blocked. This exception extends neither the campaign deadline nor costs.

For the separately approved empty-response interruption after the API image
PATCH, `--completed-image-plan "$bundle/image-continuation-r1/plan.json"`
selects the exact retained completed image and eleven-request workload prefix;
write its new plan to `$bundle/image-continuation-r2/plan.json`. Do not push or
scan again, rewrite the prior approval, or repeat the API PATCH. An empty
successful PATCH response is only acknowledgement: exact GET readback must prove
the new digest and complete preservation. The continuation verifies the saved
API GET and original dispatch authority, then freshly reads all ten workloads.
Only the nine still-old jobs may receive their first image PATCH under new bound
authority. Combined completion keeps the original source and dispatch history
separate from the corrected executing source. Missing or contradictory history,
drift, another attempted update, or any uncertain request blocks continuation.
The existing operator `image-decision` command accepts the new continuation plan
and the original r1 scan path. All subsequent phases use that same new plan.

The retained r2 attempt updated only the worker job before its preservation
comparison rejected `resources.ephemeralStorage` changing from an empty string
to absent. This field is provider-read-only in the 2024-03-01 API. Only that
empty/absent representation is equivalent; nonempty changes, CPU, memory, and
all other fields remain exact. Original request bodies and raw responses are
never rewritten. A separately approved `--prior-jobs-plan
"$bundle/image-continuation-r2/plan.json"` writes the new r3 plan, retaining the
exact thirteen-request history and its completed worker readback. It requires
fresh observations of the already updated API and worker, then permits only the
eight untouched jobs under new source-bound authority. It cannot repeat the API
or worker PATCH, image admission, a job start, or an uncertain request. This
continuation needs explicit post-dispatch approval; the pre-dispatch correction
allowance does not grant it.

The seven-argument Entra catalog correction has one explicit same-bundle
continuation. This does not authorize another campaign, base deployment, image
build, controller renewal, or a later Milestone 7.8 evidence phase. Its image
build source is `3e451e87b1f572b0ead310bb55c31063dc22e34f`; the executing operator
commit is recorded separately. Canonical inputs must remain
`11b16bc8f40915461dc358aeed64e5b4635565b4eb5af9d8637036926d5c4805`, and the
retained Linux/amd64 image must remain
`sha256:446eb66272d63682d70a6eac89a1ce7e6f279a4a75d5fa6751d7ac99a2cc1210`.
Use `image_continuation` only after explicit approval of the exact plan and
corrected clean operator checkpoint. Preparation of a plan is local and issues
no expiring authorization:

```powershell
$bundle = '.runtime/milestone_7_8/p-run/ca'
$continuation = "$bundle/image-continuation/plan.json"
$replacementCost = '.runtime/milestone_7_8/p-run/signature-correction/proposed-cost-config.json'
$retained = '.runtime/milestone_7_8/p-rec/image-3e451e8/retained-image.json'
python -B -m infra.milestone_7_8.image_continuation plan `
  --runtime "$bundle/runtime.json" --config "$bundle/campaign-cost.json" `
  --ledger "$bundle/ledger.json" --cost $replacementCost `
  --retained-image $retained --plan $continuation
```

The closed plan binds the original ledger, runtime/configuration, failed
prerequisite, original admission and underlying raw evidence, retained corrected
image, new operator source and cumulative cost history. It preserves all earlier
files. The cost input retains every original allowance and adds both consumed
extra diagnostics and one corrected prerequisite (each 900 seconds at 0.5 vCPU /
1 GiB). With 25% contingency the reviewed forecasts are $49.1807 per bundle and
$93.1843 cumulative. The unchanged limits remain $50/$94. Approval must explicitly
cover the existing fixed $2 installed-Scout reserve across both admissions; no
purchase or Azure builder is included. A second full $2 reserve instead exceeds
both limits. No actual billing claim or spending reset follows from these estimates.

After separate live approval, use the existing registry baseline, exact-egress
and local-image approval procedure with `--image-continuation $continuation` on
each `local_image plan`, `approve`, and `execute` command. Select `$retained` at
plan time. Use a new plan/approval/output beneath `$bundle/image-continuation`.
The replacement executor writes `local-image`, its own attempt marker and an
immutable effective Scout runtime there, leaving the original directory intact.
It performs zero builds, verifies pushed digest/platform/provenance, performs a
fresh digest-pinned Scout scan, and verifies registry restoration before admission.
Existing v5 phase/cleanup authorizations use the effective runtime returned by
`image_continuation.load_context(..., operation='image')`, preserving all scope
fields except the separately approved operator source and canonical input binding.
Do not edit the original runtime or reuse an old source-bound authorization.

With that completed image proof, the normal operator performs image-only updates:

```powershell
python -B -m infra.milestone_7_8.operator image-decision `
  --runtime "$bundle/runtime.json" --config "$bundle/campaign-cost.json" `
  --ledger "$bundle/ledger.json" --image-continuation $continuation `
  --image-digest $verifiedPushedDigest `
  --image-scan-evidence "$bundle/image-continuation/local-image/image-scan.json" `
  --authorization $imageDecisionAndCleanupAuthorization --execute

python -B -m infra.milestone_7_8.operator bootstrap `
  --runtime "$bundle/runtime.json" --config "$bundle/campaign-cost.json" `
  --ledger "$bundle/ledger.json" --image-continuation $continuation `
  --authorization $bootstrapAndCleanupAuthorization --execute

python -B -m infra.milestone_7_8.operator migrate `
  --runtime "$bundle/runtime.json" --config "$bundle/campaign-cost.json" `
  --ledger "$bundle/ledger.json" --image-continuation $continuation `
  --authorization $migrationAndCleanupAuthorization --execute
```

Image admission first validates all ten exact existing workload GETs, then PATCHes
only the sole container image in the API and nine job templates, with durable
per-request intents and preservation readbacks. It never invokes Bicep, provisions
base resources, starts a job or changes roles. All identities, other template
fields, settings and tags remain bound to the prior observations. Provider-owned
revision/timestamp fields have explicit, shape-preserving comparisons. The ledger
then records both image/scan identities and the old/new estimates, truthfully
requires two admission scans, and rejects a second replacement. Raw history and
the continuation completion must validate again before dependent phases.

The new bootstrap prerequisite is recorded under
`image-continuation/prerequisites`; the original failed intent is never replayed
or overwritten. Only its accepted marker unlocks the still-unused normal
bootstrap. Migration retains its existing prerequisite and guarded-retry rules.
Use the reviewed private startup helper adapted to this continuation for the one
four-worker execution and bounded private API readiness/heartbeat probe. Its
approval binds the continuation plan/admission, original runtime file, corrected
build/image and fresh scan. Startup success is partial evidence, not a completed
managed campaign.

Pass `--image-continuation $continuation` to the existing `cleanup`, `cleanup-wait`,
`cleanup-disarm`, `residue`, and `finalize` commands with their exact current
authorizations. Cleanup remains available if replacement admission is incomplete
or its new receipt is missing. Preserve the controller and require all fourteen
observed residue counters before finalization. Do not reset the cleanup deadline
or expand the original cleanup-only authority.

An interrupted PATCH, lost response, failed persistence, preservation drift, or
incomplete corrected prerequisite leaves admission blocked and preserves healthy
infrastructure under scheduled cleanup while its limits hold. Mutation attempts
are never automatically replayed. This implementation does not reconcile partial
image updates or retry the corrected prerequisite: retain the exact attempt for
scoped investigation and any separately required recovery decision. Existing
mandatory expiry, exhausted-budget and lost-protection cleanup still applies.
Directory crash-durability and Windows ACL limitations remain as previously
documented; offline tests do not establish Azure behavior or eliminate those limits.

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

Role-membership revocation remains in the privileged bootstrap. The migration
identity must not receive `CREATEROLE` or an `ADMIN` option to reconcile object
grants. Its reconciliation rejects inherited migration membership and rolls back
the grant transaction if that check fails; it does not attempt a role-membership
REVOKE that PostgreSQL denies to the unprivileged migration identity.

Before dispatching each database mutation job, the operator runs its
`--diagnose-prerequisites` branch once under the same job identity and admitted
image. A one-time token binds the diagnostic to the exact execution and console
marker. The closed marker drives admission. The gated cost config must include
`database-prerequisites` with at least USD 0.0567 for the two provider-timeout
allocations. An uncertain diagnostic dispatch is preserved for review. It
does not consume the guarded mutation retry.

Bootstrap verifies its Entra administrator mapping, runs the read-only listing
in `postgres`, and checks EXECUTE on the exact creation signature. The
diagnostic uses read-only transactions and inspects vector packaging, allowlist,
and installer privileges in `opencanvas`. Actual principal creation and ACL
application still require the authorized bootstrap. Existing role mappings
must match the declared object identities. Identity changes commit in
`postgres` before schema and grant work in `opencanvas`. Recovery rechecks
the durable state after a partial bootstrap.

The listing reader projects provider rows as JSON before selecting the bound
role names. It accepts the documented `rolename` and the reported `rolname`
field, with case-insensitive field spelling. It rejects duplicate or conflicting
aliases, malformed identity/flag fields and duplicate roles before filtering;
an unsupported response must never look like an empty, safe-to-create state.
The selected mappings retain the exact object-ID, tenant-consistency, service
principal, administrator and MFA checks. See the
[Microsoft return contract](https://learn.microsoft.com/en-us/azure/postgresql/security/security-manage-entra-users#list-microsoft-entra-roles-using-sql)
and the [reported provider output](https://github.com/Azure/azure-postgresql/issues/117).
These sources support local compatibility tests; they do not establish the
installed function's output on a particular managed server. Any further catalog
diagnosis remains a scoped read-only operation under its execution approval.
The normal managed prerequisite must pass before principal writes.

Bootstrap installs and verifies `public.vector`. Migration retains the
historical revisions and verifies the installed extension before DDL. Bootstrap
manages the extension member ACL separately from migration-owned application
routines. API and worker have SELECT-only access to `public.alembic_version`.
The API can invoke cosine distance and the vector typmod cast. The worker
can invoke the typmod cast for typed vector inserts.

Migration's diagnostic authenticates its actual identity in both databases.
An authenticated listing ACL denial can admit ordinary migration with
`listingRead=false`. Guarded migration retry requires a positive,
invocation-bound listing observation and repeats the mapping check before
writes. Connection, token, and transport failures block diagnostic admission.
Recovery retains the exact table inventory, ownership, and inherited privilege
checks. PostgreSQL's internal relation kind is projected as text for asyncpg.

Local rehearsal with separate synthetic identity functions verifies application
behavior. Managed caller permissions, extension packaging, install/ACL
authority, managed networking, and failover require live evidence. A successful
bootstrap, migration, and runtime startup checkpoint leaves PG-E01, PG-E02,
PG-E03, TI-E01, and PG-E04 open until their complete managed criteria pass.

Before the combined managed-evidence phase, collect the following sanitized
numeric/configuration observations under the separately authorized campaign:

- actual primary/standby zones, HA mode, maintenance day/hour, storage
  GiB/tier, backup retention, and geo-backup setting from the deployed server;
- Azure/provider-reserved connections, declared API+worker pool ceilings,
  rollout overlap allocation, non-runtime operator consumers, safety reserve,
  and deployed `max_connections`.

The approved connection safety reserve is at least 20 and the total budget
must be strictly below deployed `max_connections`. Include four extra API
replicas in the overlap allocation. The evidence operator supplies measured
peak connections and application p95 from its worker and API readbacks and
the two bounded sampler executions. The campaign workspace must support
execution-scoped Container Apps console log queries. Include the worker,
temporary API revision, and both sampler executions in the execution
approval and current cost estimate.

Bind those observations without credentials or resource UUIDs:

```powershell
$env:M78_AZURE_RESERVED_CONNECTIONS = '<observed-nonnegative-integer>'
$env:M78_POOL_CEILINGS = '<declared-positive-integer>'
$env:M78_ROLLOUT_OVERLAP = '<bounded-nonnegative-integer>'
$env:M78_OPERATOR_CONSUMERS = '<observed-positive-integer>'
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
  azureReservedConnections = [int]$env:M78_AZURE_RESERVED_CONNECTIONS
  poolCeilings = [int]$env:M78_POOL_CEILINGS
  rolloutOverlap = [int]$env:M78_ROLLOUT_OVERLAP
  operatorConsumers = [int]$env:M78_OPERATOR_CONSUMERS
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

The evidence phase first starts the campaign worker and verifies four running
replicas. It samples the bounded private application exercise at steady state,
then copies the approved API revision and repeats the measurement while four
replicas of each revision are running. The operator binds each sampler log to
the exact execution and its dispatch token. It checks the timestamps against
complete worker and API inventories before deriving peak connections and
application p95. It restores traffic to the original revision, deactivates the
temporary revision, and stops the worker before running the remaining probes.

The remaining evidence steps execute in order:

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

The sampler and proof jobs must terminate `Succeeded`. The worker is stopped
after measurement. Incomplete, stale, or mismatched observations block admission
and pause dependent work while cleanup protection, budget and authority remain
valid. Expiry or an established terminal condition uses failure cleanup.
The operator persists a sanitized,
source/digest/control-bound `managed-evidence-execution.json` beside the ledger,
including both measurement-window hashes and the 12 proof execution records.
An attempt marker without a completed receipt blocks another evidence start.
An interrupted attempt without a completed receipt requires investigation;
there is no automatic evidence-job redispatch. Preserve the armed cleanup
schedule and use the existing cleanup procedure when the attempt is abandoned
or its protection limits require it.
The full shape is closed by
`infra/milestone_7_8/schemas/evidence-execution.schema.json`. `dispose` records
the pass/fail campaign disposition before deletion.

The intended cleanup deployment remains exactly one command in exactly the prepared
region. A deployment failure never selects another candidate, retries in a
different region, restores or reuses a soft-deleted account, or modifies an
unrelated Automation account; it enters the existing cleanup path.

## Cleanup and zero residue

A failed or timed-out bootstrap, migration, or managed probe execution preserves
its exact start/last execution responses before any subsequent cleanup. The operator makes
best-effort, exact-execution replica and console reads into a new private
`job-failure-*` directory beside the ledger: at most six read operations,
a 60-second admission budget with a 15-second command timeout and 10 seconds
reserved for local timeout termination, never dispatching beyond the campaign
deadline. ARM execution/replica reads are GETs; the scoped Log Analytics query is
semantically read-only and may use HTTP POST. The opt-in Windows-only diagnostic launcher writes stdout/stderr to private
files and, on timeout, asks the trusted system taskkill utility to terminate only
its exact owned process tree before killing the parent. A real local synthetic
batch/child/grandchild timeout test covers this path; OS termination failure,
filesystem stalls, hard crashes, and Windows ACL/directory-durability guarantees
remain unproved. Ordinary Azure mutation and wait commands do not opt in. Replica
continuation links retain the exact execution scope. Console reads require a
complete, validated set of exact replica names (not an execution-prefix match)
and are skipped if that scope is unavailable. Console capture is bounded to
1,001 rows over the preceding 30 minutes and is diagnostic,
not complete-inventory or admission evidence. Missing, denied, expired, malformed,
or unpersistable diagnostics never replace the original job error, retry a job,
or require deletion while the stage remains protected. They also cannot
prevent mandatory cleanup after protection, authority, budget or deadline is lost. Bootstrap emits only static stage,
allowlisted error class, and a syntactically valid SQLSTATE; it never prints SQL,
exception text, principal identifiers, or credentials. These records do not
establish the cause of a historical attempt whose logs were not retained. The
existing private-directory ACL and directory-durability limitations still apply.

Cleanup is mandatory after campaign completion, explicit abandonment, established
terminal failure, lost cleanup protection or authority, budget exhaustion, or
cleanup-deadline expiry. A recoverable or undiagnosed protected stage failure
first pauses dependent work; a missing diagnostic alone is not a deletion trigger:

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

Before cleanup is verified, setup failure uses the existing failure-cleanup
path. After cleanup verification, a recoverable or undiagnosed failure preserves
healthy infrastructure and the existing cleanup schedule while budget, authority
and deadline remain valid. Immutable stage intents precede writes, and per-stage
pause records bind the exact source, runtime, cost config, image, original
approval, attempt, ledger phase and cleanup-arm hash. The ledger stays at its
prior phase. Missing/corrupt pause records or lost responses block retries and
dependent work; they do not justify deleting an otherwise protected scope.
Established expiry/cost/protection loss takes precedence over missing diagnostics.
Failure cleanup still requires current cleanup authorization immediately before
runbook start and, after ownership reads, immediately before fallback deletion.
An expired approval blocks dispatch and preserves the original stage error;
dry-run inspection never dispatches cleanup.

Only bootstrap and migration have a supported guarded mutation retry in this
correction. There is at most one additional existing-job start for each, within
15 minutes of the initial failure; diagnostic collection consumes that dispatch
window. The reviewed sibling cost config must include
`database-recovery-job-allowance` of at least USD 0.0567 before contingency for
both starts. Exact job and failed-execution template readbacks must establish one
container, one parallel replica/completion, zero automatic retries, at most
0.5 vCPU/1 GiB, and server timeout at most 900 seconds for bootstrap or 1,800 for
migration. Init containers and any template change except the approved argument
are rejected. These server bounds and the existing campaign deadline remain in
force; the 15-minute dispatch window is not a claim that a job finishes within
15 minutes.

```powershell
# Same existing source/runtime/image/cost config; current phase+cleanup approval.
Invoke-M78Phase 'bootstrap' $bootstrapAuthorization @('--resume-database-job')
# Or, only when the paused operation is migration:
Invoke-M78Phase 'migrate' $migrationAuthorization @('--resume-database-job')
```

The normal operator rechecks the exact terminal previous execution and all nine
cleanup-protection observations, then starts the same existing job using its
reviewed execution-template YAML with only `--retry-after-execution=<previous>`
changed. The actual script performs SELECT-only identity/OID, privilege,
ownership, revision, active-writer and migration-lock checks before any SQL
mutation. Bootstrap permits only a safe base-state catalog; migration permits
base/empty or the exact current head with owned schema and privilege
reconciliation. Unknown, mixed, conflicting or incomplete state cannot mutate.
Admission requires the distinct retry execution to succeed and the matching
safe-state marker from its exact validated replica logs. No new job, identity,
resource, image, migration or permission is created by this recovery wiring.

If successful-job logs arrive late, repeating the same resume command validates
the original immutable dispatch/start records and performs only read-only
completion observation of that recorded retry. It never starts another job and
may observe it after the dispatch window under current authorization, while the
campaign deadline, budget and protection still hold. Missing dispatch/start
history cannot be reconstructed from matching state. A source/config/image change
cannot retrospectively rebind a live attempt. The explicitly approved bootstrap
source transition below adds new evidence; it never edits or replaces those
historical bindings. Other paused stages have no new
redispatch mechanism; retain evidence and investigate within their bounded window
or explicitly abandon/clean up. Once cleanup has started, it cannot be reversed.

### Explicit bootstrap operator-source transition

For the specifically reviewed failed bootstrap, an explicit transition approval
may admit the tested operator correction without rewriting the prepared bundle.
Keep the original runtime, cost config, admitted image digest, source identity,
phase authorization, failed execution, stage intent, pause and private diagnostics
unchanged. The new closed transition authorization binds that exact history and
controller/campaign scope, the original and corrected source commits, the reviewed
patch and validation evidence, and the actual user approval. The corrected clean
commit is the executing **operator** source; it does not become the historical
runtime or image source. Missing or mismatched transition evidence fails closed.

Prepare this artifact through the validated transition builder and existing
serializer only after the correction passes its focused checks and is committed.
Do not issue it during development or alter an expired authorization. The existing
v5 phase authorization remains separately required and retains its original
runtime bindings; the transition artifact supplements it rather than replacing
it. Both approvals must be current at dispatch.

The approved exception can open one new dispatch window for the **unused**
bootstrap retry: at most 15 minutes from issuance, capped by the existing campaign
cleanup deadline and authority. It neither extends that deadline nor replenishes
the retry allowance. Any retained retry intent or dispatch must be reconciled;
it cannot be discarded to obtain another start. The exact previous execution must
remain terminal, cleanup protection must still verify, and the original
`database-recovery-job-allowance` must still cover the bounded retry. The existing
single-container, one-replica, 0.5-vCPU/1-GiB maximum, zero automatic retries and
900-second bootstrap timeout checks remain mandatory. No new resource, identity,
image, role, permission, resource allocation or spending reset is authorized.

```powershell
# New closed transition approval; original runtime/config/image and v5 approval.
Invoke-M78Phase 'bootstrap' $bootstrapAuthorization @(
  '--resume-database-job',
  '--bootstrap-source-transition', $bootstrapSourceTransition
)
```

Dispatch requires all existing operator retry checks; the job's safe database
inspection must pass before any SQL mutation. Preserve the transition and
resulting attempt records privately. After a recorded retry, the same supported
resume path may perform later execution-completion GETs under current required
authorization without starting another job; it cannot reconstruct missing
dispatch history. Any scoped
Log Analytics query needed for the safe-state marker is semantically read-only
and may use HTTP POST, as described above. Normal migration and remaining campaign
phases stay blocked until the existing bootstrap completion validator accepts
the exact successful execution and its matching safe-state evidence. Later
phases still require their own existing approvals and valid cleanup protection.
Every subsequent operator invocation must carry the same transition path because
the original runtime source remains unchanged. After accepted bootstrap
completion, use the normal next phase and its operation-specific authorization:

```powershell
Invoke-M78Phase 'migrate' $migrationAuthorization @(
  '--bootstrap-source-transition', $bootstrapSourceTransition
)
Invoke-M78Phase 'evidence' $evidenceAuthorization @(
  '--bootstrap-source-transition', $bootstrapSourceTransition,
  '--control-plane-evidence', $controlPath
)
Invoke-M78Phase 'dispose' $disposeAuthorization @(
  '--bootstrap-source-transition', $bootstrapSourceTransition
)
Invoke-M78Phase 'cleanup' $cleanupAuthorization @(
  '--bootstrap-source-transition', $bootstrapSourceTransition
)
```

Cleanup may run before accepted bootstrap completion under its existing exact
authorization when cleanup is required; the transition does not block cleanup
or extend cleanup authority. Carry the same flag through `cleanup-wait`,
`cleanup-disarm`, `residue` and `finalize`, each with its existing required
authorization. Passing this flag to later phases never permits a second
bootstrap retry or a dispatch outside the approved retry window.

For an unpaused conforming ledger, invoke only its next operation:

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
When protected-stage records exist, receipt recovery also reconciles the original
attempt and pause into a separate immutable completion record. Missing or altered
history and an unrelated paused stage remain blocked; original records are retained.

This resume table describes only a conforming v6 ledger. It does not reopen or
upgrade the preserved legacy finalized ledger described above.

## Bounded time, cost, artifacts, and stopping rule

Preparation fixes a cleanup deadline at most four hours away. Before scope
creation, replace the template's cost inputs with the reviewed regional
estimate using the sibling `--config` path. Include both API revisions, four
workers, both sampler executions, the remaining jobs, and cleanup overrun.
The estimate requires at least 25 percent contingency and a hard USD 50
ceiling. Stop normal evidence work immediately on any assertion failure, cost
projection over USD 50, expired deadline, cleanup drift, or unready managed
service. Preserve the sanitized local files and pause recoverable/undiagnosed
protected failures; enter cleanup for established terminal failure or loss of
budget, deadline, cleanup protection or authority:

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

## Late closure of the already removed failed campaign

`infra.milestone_7_8.late_cleanup` is the separate, narrowly scoped path for
adopting the retained scheduled cleanup after the original execution authority
has expired. It applies only to the retained paused `image-decided` campaign.
The original runtime, v5 authorization, controller deadline, stage history and
provider captures remain unchanged. The expired v5 authorization is checked at
the scheduled job's actual historical start time; it never becomes current
permission to mutate Azure.

The local plan requires the exact completed scheduled job, its matching cleanup
receipt, original authorization and ledger snapshot. It binds their file hashes,
the exact subscription/controller scope, the two disarm targets, current reviewed
infrastructure code content and the five protected stashes. Execution additionally
requires a clean reviewed checkpoint with the same code content, canonical image
inputs and cleanup-script hash, plus a passing validation receipt and a new
explicit plan-bound approval. That approval lasts at most 30 minutes and is
independent of the expired campaign/controller window. It authorizes only the
exact job-schedule binding DELETE, exact schedule DELETE, scoped verification and
local failed-campaign closure. It cannot start a runbook, delete a resource group,
create a resource, renew the controller, resume a campaign or claim a managed
observation passed.

For an already admitted replacement image, pass the exact retained continuation
plan with `--image-continuation "$bundle/image-continuation-r3/plan.json"` to
`late_cleanup plan`. Continue passing the original runtime and original config;
the accepted continuation supplies its bound replacement cost config and ledger
history. Planning and execution replay its original source-bound image, scan,
workload preservation and admission receipts. The optional closed plan binding
retains the exact continuation and completion file hashes. The scheduled job and
its historical authorization remain checked against the original runtime/config.

A cleanup-only source checkpoint may be a descendant of that historical
continuation commit, provided its canonical image inputs match the admitted
replacement and its cleanup script is unchanged. Clean branch/upstream, protected
stashes, reviewed executable content, current closure authorization and exact
readbacks remain mandatory. This does not rebind historical artifacts or enable
any workload operation. Wait for the scheduled cleanup to complete and prove the
target absent; do not invoke immediate cleanup merely to advance the ledger while
scheduled cleanup is pending. The closure then adopts the completed job and
removes only its exact binding and schedule before zero-residue finalization.

Prepare only the local plan first. This example uses the retained private
`p-rec/ca` captures; choose a new nonexistent closure directory and keep all
outputs under the existing protected, ignored parent:

```powershell
$bundle = '.runtime/milestone_7_8/p-rec/ca'
$capture = "$bundle/post-deadline-status-20261113T1530Z"
$closure = "$bundle/late-cleanup-closure-01"
New-Item -ItemType Directory -Path $closure -ErrorAction Stop | Out-Null
& .\.venv\Scripts\python.exe -B -m infra.milestone_7_8.late_cleanup plan `
  --runtime "$bundle/runtime.json" --config "$bundle/campaign-cost.json" `
  --ledger "$bundle/ledger.json" `
  --job-result "$capture/05-job-result.json" `
  --output-result "$capture/06-output-result.json" `
  --original-authorization "$bundle/failure-cleanup-authorization.json" `
  --output-directory "$closure/attempt" --output "$closure/plan.json"
if ($LASTEXITCODE -ne 0) { throw 'late cleanup plan blocked' }
```

Stop for review of the exact plan. Record the actual approval privately; do not
manufacture approval by setting `approved` to true. Its allowed operations must
be exactly `adopt-scheduled-cleanup`, `delete-exact-binding`,
`delete-exact-schedule`, `verify-residue` and `finalize-failed-campaign`, with the
reviewed plan hash and `maximumMinutes: 30`. After the required local checks and
clean checkpoint, retain the validation receipt binding that same plan, code and
checkpoint. It must record passing tests, Ruff, strict mypy, schema and hygiene
checks completed no later than issuance. Only when execution is ready and the
explicit approval exists, issue the separate local authorization:

```powershell
$issuedAt = [DateTimeOffset]::UtcNow
$expiresAt = $issuedAt.AddMinutes(30)
& .\.venv\Scripts\python.exe -B -m infra.milestone_7_8.late_cleanup authorize `
  --plan "$closure/plan.json" --approval "$closure/explicit-approval.json" `
  --validation-receipt "$closure/validation-receipt.json" `
  --issued-at ($issuedAt.ToString('o')) --expires-at ($expiresAt.ToString('o')) `
  --output "$closure/authorization.json"
if ($LASTEXITCODE -ne 0) { throw 'late cleanup authorization blocked' }

& .\.venv\Scripts\python.exe -B -m infra.milestone_7_8.late_cleanup execute `
  --plan "$closure/plan.json" --authorization "$closure/authorization.json" --execute
if ($LASTEXITCODE -ne 0) { throw 'late cleanup stopped; preserve the attempt' }
```

The executor reads back the exact completed job and its output, proves the target
group is already absent, validates the exact binding and schedule, and persists
intent before either DELETE. It checks the new authorization immediately before
dispatch. A failed or ambiguous response stops the invocation; no automatic
retry occurs. With the same still-current approval, re-entry must use GET
readbacks to prove an already-attempted target absent and must never repeat its
DELETE. If that target remains present, closure stays blocked even when the prior
response reported failure. Re-entry may delete only the remaining target that
has no prior dispatch intent, under the same exact approval. Thus an invocation
that continues an unattempted DELETE is not GET-only. Expired approval blocks
execution; any further closure requires a separately reviewed approval without
discarding the retained attempt history.

Only complete disarm readbacks and all 14 zero residue counters permit local
adoption and finalization. Preserve `attempt/original-ledger.json` before writes;
the actual campaign ledger is updated only after the verified final ledger is
persisted. Completion evidence records the scheduled job's historical start/end
times separately from the present adoption timestamps, with raw readbacks and
hashes kept private. The terminal receipt establishes zero residue for a
**failed** campaign; it does not assert that PG-E01, PG-E02, PG-E03, TI-E01 or
PG-E04 passed. Existing Windows ACL and parent-directory crash-durability
limitations remain unchanged and must not be described as newly proven.
