# Milestone 7.8 regional replacement

The East US full-closure attempt stopped at PostgreSQL subscription eligibility.
Its target group, schedule and binding were absent. Only the preserved
controller's deadline was renewed. The prior receipts and approvals remain
historical. PostgreSQL, M78-D-001 and M78-D-002 remain closed.

## Regional admission

Read-only observations on November 17, 2026 used the bound subscription.
The screen began with East US 2. East US PostgreSQL was excluded based on
the recorded regional restriction.

| Candidate | Subscription and quota | No-write validation |
|---|---|---|
| East US 2, West US 2, South Central US | PostgreSQL returned no editions with a subscription regional restriction. | South Central US also rejected HA Balanced B0 with RequestDisallowedByAzure. |
| Central US | PostgreSQL listed version 17 and GP Ddsv4. Quota showed 0/16 regional and 0/6 Ddsv4 vCores. | HA Balanced B0 rejected with RequestDisallowedByAzure. |
| Canada Central | PostgreSQL listed version 17 and GP Ddsv4. Quota showed 0/16 regional and 0/6 Ddsv4 vCores, with 4 needed across the primary and one restore. ACA showed 0/1 managed environments. Network showed 0/1,000 VNets, 0/3 Standard IPv4 addresses and 0/65,536 private endpoints. | The exact foundation, including PostgreSQL and internal ACA, passed ARM Provider validation. Local HA Balanced B0 failed with CacheCapacityUnavailable. |
| Canada Central with East US Redis | Exact HA Balanced B0 in East US is supported by the registered Redis provider. Canada Central metadata advertises the network resource types. | The East US cache passed ARM Provider validation. The Canada Central VNet, VpnGw1AZ, Standard public IPv4, DNS resolver inbound endpoint and private endpoint targeting the East US cache passed as a second subset with a fixture audience ID. |

Validation did not reserve capacity. Per-environment ACA Consumption limits, live
Redis allocation and private DNS/TLS connectivity, PostgreSQL restore-point
availability and timing, actual VPN client authentication and live per-resource
diagnostic categories still require native readback. The prepared peak is
3.75 vCPU and 7.5 GiB including the bounded one-off helper. The screen did not
count Sandbox quota as available Consumption compute.
[ARM validation](https://learn.microsoft.com/en-us/rest/api/resources/deployments/validate-at-scope?view=rest-resources-2025-04-01)
[ACA quotas](https://learn.microsoft.com/en-us/azure/container-apps/quotas)
[Same-region PostgreSQL restore](https://learn.microsoft.com/en-us/azure/postgresql/backup-restore/concepts-backup-restore)

## Target and prerequisites

Use Canada Central for the target group rg-m78-a712b8c940-target and its
workload, with the HA Balanced B0 Redis cluster and its database in East US
inside the same group. Redis stays private with TLS 1.2, managed identities
and public access disabled. Its private endpoint and DNS zone link are in the
Canada Central network. The output uses the Azure-assigned East US Redis
hostname. The existing action group and AMPLS use their established global
locations and the reusable Automation controller stays in East US. Controller
scope is the exact resource group and its deadline renewal only. The controller
uses management-plane calls across regions and group deletion covers both
locations. The existing cleanup allowance covers those calls. This proof uses
synthetic data and Redis rate-limit state crosses the Canada–US boundary via
Private Link.
[Cross-region private endpoints](https://learn.microsoft.com/en-us/azure/private-link/private-endpoint-overview/)
[Redis private DNS and connectivity](https://learn.microsoft.com/en-us/azure/redis/private-link)
[Global action group processing](https://learn.microsoft.com/en-us/azure/azure-monitor/alerts/action-groups)

| Scope | Exact shape and remaining check |
|---|---|
| PostgreSQL 17 | General Purpose Standard_D2ds_v4, 2 vCores, 32 GiB, 7-day backup retention, private delegated subnet and Entra authentication. One same-region point-in-time restore of this shape. This campaign exercises the remaining restore contract. Its source server uses the original single-server full-closure configuration. |
| Runtime | Internal Container Apps Consumption, signed and unchanged API/frontend, existing job allocations and private ACA DNS. Premium ACR in Canada Central and the prior 20-minute exact-IP maximum for publication. Package retains the selected six in-flight per replica and scoped thirteen-request lock stages. |
| Private access | VpnGw1AZ Generation 1, Standard static regional IPv4 with zones 1/2/3, OpenVPN with the campaign audience and existing entitled interactive operator. Private DNS resolver inbound 10.79.9.36, 10.79.0.0/16 route and 172.31.240.0/24 client pool. No peering or additional endpoint. VPN logs and resolver-native metrics remain in the proof. |
| Storage and monitoring | Standard_LRS Blob and Defender, PerGB2018 workspace, private AMPLS, DCE/DCR, dashboards, alerts and diagnostic routing. Registered providers advertise the regional resource types and native foundation validation covered Blob, Defender and the workspace. Live ingestion, rejection, rendering, alert and recovery behavior remain unproved. |
| Event Hubs and Key Vault | Event Hubs Standard one throughput unit, Key Vault Standard and private endpoints. Native provider metadata advertises Canada Central. Microsoft.EventHub and Microsoft.KeyVault are NotRegistered in this subscription, so these parts did not receive provider-level validation. Confirm registration through scoped reads and validate the omitted resources before asking for execution approval. A principal with existing /register/action at the bound subscription can register these two providers if separately authorized. No provider registration or role change is included here. |

The operator capacity check requires both provider registrations for this
replacement. Use the exact-vault Canada Central deleted-vault path and
entitled executor already selected. The count remains 48 cleanup counters.
The target inventory covers both locations, including the exact Redis cluster
and Canada Central private endpoint. Global DNS links, detailed access
residue, Automation schedule/binding, tenant objects and temporary Gmail
credential remain covered. The controller keeps its original code and identity.
[Resource provider registration](https://learn.microsoft.com/en-us/azure/azure-resource-manager/management/resource-providers-and-types)
[DNS resolver metrics](https://learn.microsoft.com/en-us/azure/dns/monitor-dns-reference)

## Cost and timing

The regional retail forecast is **$39.4128** with **$49.2660** after the
existing 25% contingency. It includes the VPN option and $0.20 allowance for
10 GB of North American inter-region transfer. The existing same-zone DNS
resolver and DNS query allowances are carried forward where exact regional
meters were unavailable. Main changes are Canada Central ACA, PostgreSQL and
Log Analytics retail rates. Billing is unsettled. The replacement proposes
the same $50 incremental ceiling and $400.89 cumulative approved-history
ceiling. It would replace the unused campaign allowance. Limits remain
10,000 HTTP requests, 200 model attempts including retries, 160M embedding
tokens and at most three messages to the approved inbox.
[Azure bandwidth rates](https://azure.microsoft.com/en-us/pricing/details/bandwidth/)
[Azure DNS prices](https://azure.microsoft.com/en-us/pricing/details/dns/)

Fresh deadlines derive from any future replacement approval. Services, core
and private access must be ready by +2h. Stop proof and trigger cleanup at
+10h. Automation binding expires at +11h. Operator cleanup and verification
expire at +12h. Azure documents 45 minutes or more for VPN gateway creation,
and point-in-time restore duration varies. The preserved sequence places the
gateway after the foundation. Read-only checks did not demonstrate a timing
incompatibility or prove this window achievable. Keep the readiness stop
and cleanup deadlines. If readiness slips, stop, preserve evidence and clean up.
[Azure VPN creation timing](https://learn.microsoft.com/en-us/azure/vpn-gateway/create-routebased-vpn-gateway-cli)
[PostgreSQL restore timing](https://learn.microsoft.com/en-us/azure/postgresql/backup-restore/concepts-backup-restore)

## Evidence and execution

Protected directory .runtime/milestone_7_8/full-closure-prerequisites contains
regional-screen-20261117 for subscription, provider, validation and meter
receipts, and regional-v3 for the sealed package. Follow the regional
EXECUTION.md after prerequisites and replacement approval. The bound review
reuses the approved signatures, API and frontend digests, protected provider
inputs, transport and acceptance validators. No image build or managed
acceptance ran during regional preparation.

## Approved regional attempt stopped at cleanup admission

The user approved the provider-admitted package with SHA-256
`c8eb76c719a4c686e1ef8d2f4caa95e83659d8003ed53631b79613a3ae59c566`
at source `885abca6cbf45f327982a8ff54de11c7b4c6a290`. The approval clock was
2026-11-17 15:04:37 UTC. The resulting deadlines were 17:04:37 UTC for
readiness, 2026-11-18 01:04:37 UTC to stop proof and schedule cleanup,
02:04:37 UTC for Automation expiry, and 03:04:37 UTC for operator cleanup.
The $39.4128 forecast, $50 replacement ceiling and $400.89 cumulative ceiling
remain recorded. Billing is unsettled.

All package hashes, the five retained endorsements, the provider registration
and validation receipts, controller renewal, live capacity and cost admission
passed. The first target creation command stopped in the local source-staging
check when Windows could not extract a generated path at 260 characters.
Native readback proved the target group absent. A shorter protected runtime
passed the same check and retained the admitted ledger, authority and
deadlines. The target group and cleanup grants were then created.

The actual `cleanup-arm` command stopped with
`cleanup schedule readback drifted: startTime`. The approved schedule start
was 2026-11-18 01:04:37 UTC. Azure returned 01:04:00 UTC for both
`startTime` and `nextRun`. The exact job-schedule binding was absent. The
failure-cleanup runbook job
`8b05068d-fa5b-402e-8e16-e9d1ce5b0f00` reached Failed with
`cleanup-binding-parameter-set-mismatch:parameters-shape`. No application,
data service, tenant object, registry publication, provider attempt or email
was dispatched. The ledger recorded no billable start and no managed
assertion was accepted.

After verifying the runbook job was terminal and the target inventory was
empty, the operator's scoped direct failure-cleanup path removed the target
group. Cleanup wait and disarm passed. Native readback found no target
resources, grants, schedule or binding and verified the retained controller's
identity, Reader grant and runbook. The exact Canada Central deleted-vault
readback returned absence. The vault was never created, so there was nothing
to purge. The Gmail account owner removed the campaign app password and
confirmed its absence. All 48 cleanup counters are zero. The broad campaign
terminal receipt records the full evidence. The underlying operator ledger is
at cleanup-disarmed.

Protected evidence is under
`.runtime/milestone_7_8/full-closure-prerequisites/run-c8eb76c7/`.
The terminal receipt SHA-256 is
`5f41c4e47ec735f319d585a7875abc2be61663443959b54a2966dd8dcbff6384`.
Schedule and failed-job native receipt hashes are
`1c149c99ca6ca243a149422f49a97cf81dac3da50a1a4f71ee95b7386006b89a` and
`cc795fe874f7dedf7a1fbadd742bef7eee8f7997c6b15edee0f9bdfaaf062d9c`.

The attempt is terminal and Milestone 7.8 remains open. A later package needs
an explicitly approved whole-minute clock or an explicitly approved separate
provider schedule time, validated against native schedule behavior before
workload provisioning. The pre-binding failure path must also select the
scoped direct cleanup path when the exact binding is absent. Retain the
signed images and valid regional admission evidence. PostgreSQL, M78-D-001
and M78-D-002 remain closed.

## Successor cleanup repair

The successor explicitly requires approval of the first whole UTC minute
strictly after receipt of execution approval. Record the actual receipt time
and the derived execution start separately. For example, a receipt at
15:04:37 UTC yields a start at 15:05:00 UTC. A receipt at exactly 15:05:00 UTC
yields 15:06:00 UTC. An omitted, earlier or later execution start is rejected.
The successor derives readiness, proof stop, Automation expiry and operator
cleanup expiry at +2h, +10h, +11h and +12h from that start. Probe authorizations
use the same start. The Automation schedule must return the exact +10h
timestamp and the exact binding must pass readback before workload provisioning.
The rule applies to the successor and preserves the original approved times
and native failure receipt.

The operator journals intents before target, schedule, binding and runbook
writes. For an admission failure, it reads complete schedule and binding
inventories. With confirmed absent binding and no unresolved arming write, it
uses the existing ownership-checked direct deletion of the campaign group.
A valid binding uses the existing runbook path. An incomplete read, a possible
unobserved write or a conflicting binding stops dispatch. Reconcile the native
state before retrying any operation. A failed admission blocks further proof.
After target absence, cleanup disarm clears the exact campaign schedule and
binding and verifies the retained controller. The published controller is
unchanged.

The protected runtime uses the same directory depth as the successful
short-path recovery. Use .runtime/milestone_7_8/c8s for the new bound runtime.
The package rehearsal stages the canonical source at that depth and drives
the actual operator CLI through fixtures based on the retained native schedule
and failed attempt. Local acceptance covers the control flow. Execution still
requires native Azure schedule and binding readback.

The successor retains the signed OCI images, credentials other than the
revoked Gmail password, the Canada Central/East US split topology, the
controller, and the provider validation receipts for the unchanged compiled
template. The new Gmail app password is bound privately under the label
OpenCanvas M78 successor. Only local format and difference from the revoked
value were checked. Revoke the successor password after execution and verify
its absence under the existing 48-counter cleanup plan.

A scoped ActualCost query for the prior target group and exact Automation
account returned no posted rows. The native job receipt shows one failed
Automation job and no prior workload or email dispatch. The public
Automation Basic Runtime rate is $0.002 per job minute. Reserve $0.25 for
possible later attribution inside the same $50 ceiling. The successor
workload forecast remains $39.4128, with $49.75 available for successor
execution. The combined conservative admission estimate is $49.5785 including
25% contingency on the forecast and reserve. The cumulative ceiling stays
$400.89. If the prior attributable cost exceeds the reserve or fresh forecasts
exceed the remaining allowance, stop before paid dispatch and reconcile.
Billing remains unsettled.
[Azure Automation pricing](https://azure.microsoft.com/en-us/pricing/details/automation/)
[Azure Cost Management Query](https://learn.microsoft.com/en-us/rest/api/cost-management/query/usage?view=rest-cost-management-2025-03-01)

## Whole-minute successor native execution and terminal cleanup

The user approved successor review SHA-256
`71f5361b92b3530d0978d8b38e8b305270c8c9679d5231cc476f33f2da036444`
at source `34e913adef538f9b594d8f911adc4dd6a32ba4f1`. The approval receipt
was 2026-11-17 15:54:07 UTC, recorded separately from execution start at
15:55:00 UTC. The CST gates were 11:55 a.m. readiness, 7:55 p.m. proof stop,
8:55 p.m. Automation expiry and 9:55 p.m. verified cleanup, all November 17.

The $39.4128 forecast and $49.75 successor allowance remained inside the
existing $50 combined allowance with $0.25 prior-charge reserve. The cumulative
ceiling remained $400.89. Fresh pre-execution scoped ActualCost queries returned
no posted rows. The terminal query was throttled. Billing remains unsettled,
with charges for provisioned resources still awaiting reconciliation.

All five endorsements, package hashes, source, provider receipts, short-path
source staging, controller renewal, live capacity and cost admission passed.
Real cleanup-arm and cleanup-verify passed. The native schedule returned
2026-11-18 01:55:00 UTC, matching proof stop exactly. Its exact job binding
passed validation before any workload deployment. The schedule receipt hash
is `cc4b25c8039792e01836e9d5b0a1d96a93bc1c12d0a5209607685102f4829e2a`.
This supplies native evidence for the minute-start scheduling repair.

The temporary restricted member, dedicated VPN application, service principal
and exact operator assignment were created. The local script encountered the
opaque Graph assignment ID and reordered application tags. Retained successful
responses were reconciled, and these writes were not repeated. No VPN profile
was generated or imported. The account owner confirmed the temporary browser
window was closed or unused.

### Vault correction and preservation of successful resources

The root deployment `m78p-a712b8c940-root-foundation` started. Its nested
`m78p-a712b8c940-foundation` completed, and East US Redis reached Succeeded
with HA enabled and public access disabled. These configuration observations
do not close any application assertions or reopen the closed component proofs.

The root vault operation failed with BadRequest because the submitted
`enablePurgeProtection: false` property is rejected by the Key Vault API.
The vault and its deleted-vault record were absent. The user separately
approved correction review
`9bdac3a7110224bbbaf0fa820124b3e771c9850cda9f551b8c009f6a87f78ec7`,
omitting only that property without adding cost or time authority.
A targeted six-resource projection preserved successful resources and passed
Provider validation and what-if. Deployment
`m78p-a712b8c940-vault-correction` succeeded. At 16:20:15 UTC, native readback
verified the private RBAC-enabled vault, seven-day soft delete, purge-compatible
state and Approved exact private endpoint. The retained Bicep compile matches
the approved corrected template after normalization of generated hashes and
dependency ordering. The source now omits the rejected property.

### Exact unresolved alert blocker

The independent observability deployment
`m78p-a712b8c940-observability` failed. Azure returned BadRequest with
`Unknown function: 'percentileif'` for both required scheduled query rules,
`m78p-a712b8c940-api-latency-v1` and
`m78p-a712b8c940-database-saturation-v1`.
Fourteen other scheduled query rule creation operations succeeded.
Rule creation supplies configuration evidence only. Alert behavior, application
core, delivery, capacity and recovery remained unproved. No signed image was
published, application job executed, model call made or test email sent.
The failed operations receipt hash is
`16a2f3123916c253f2a7361583bd90d15de463135625eae74061c45620a0c812`.

New proof stopped at 16:22:37 UTC. The original root deployment was canceled
after recording its state and failed operations. The existing schedule and
binding remained exact. The normal runbook path dispatched the cleanup.
The next focused correction is in the two percentile expressions in
`infra/milestone_7_8/pilot_alerts.py`. Preserve the catalog thresholds,
population filters, evaluation timing and native alert requirements.
Validate the affected queries and rules in a separately approved continuation
before relying on those destination assertions. This record adds no spending
authority and does not create another campaign.

### Verified terminal disposition

Cleanup Automation ARM job name
`16947125-05bd-47e1-b6eb-079e438166b7`, with returned jobId
`4d6457af-85bb-4041-ac6f-d0e5a0742d0f`, reached Completed.
Azure confirmed target group absence at 17:03:52 UTC. Cleanup-wait and
cleanup-disarm passed, and the terminal inventory completed at 17:04:29 UTC.
All 48 counters are zero, including the managed environment infrastructure
group, target grants, campaign schedule and binding, exact tenant objects and
assignment, client/temporary browser disposition and the revoked successor
Gmail credential. Five subscription-level custom role definitions were removed
only after native readback proved their exact retained IDs and sole assignable
scope to the absent campaign group. The reusable controller, identity,
permanent Reader and published runbook passed preservation readback.

The operator purged only the exact Canada Central vault after matching its
deleted-vault record to the recorded campaign vault. Native readback verified
its absence. The successful group deletion was reconciled throughout its
network-resource wait. No repeated deletion or provisioning was dispatched.

The protected run directory is
`.runtime/milestone_7_8/full-closure-prerequisites/run-71f5361b/`.
The terminal receipt SHA-256 is
`2f55ae448ec6719dc4ee641a8943d3ae2726921a7b1fea32aa128efbbf1ac98d`.
The full residue receipt SHA-256 is
`b1f83863c20938bde33d548b3868750aaf195ebfd1f4d59d299dcd800a82f1d7`.
The exact approved packages, original failure receipts, signatures and raw
private evidence remain outside Git. The underlying operator ledger is
cleanup-disarmed. Milestone 7.8 remains incomplete, with zero new managed
assertions accepted by this attempt. PostgreSQL, M78-D-001 and M78-D-002
remain closed.

## Percentile alert repair and successor proposal

This section preserves the pre-execution proposal. The [execution result](#alert-repair-execution-result) below supersedes its pending native-creation and cleanup status.

The local compiler now uses the supported percentile aggregate with an iff
expression that passes through only the rule's signal values and supplies
real(null) for other signals. The API rule selects mobius.api.duration.
The database rule selects mobius.database.pool.acquire while retaining its
independent sumif of mobius.database.timeouts. The exact old-to-new catalog
comparison permits only these two substitutions in the rule query and its
observation query. The other 14 rules and every workbook retain their content.

The five-minute populations, sample deduplication, source filters and signal
presence checks are preserved. API latency still fires after two windows at
or above 1,000 ms and recovers after two below 750 ms, holding on missing data.
Database saturation still fires after two windows at or above 500 ms or with
a positive timeout count and recovers after three windows below 250 ms with
zero timeouts. Its missing-data breach policy and five-minute evaluation
frequency are preserved.

Microsoft's Kusto.Language 12.4.1 parser and semantic analyzer reproduced
the unknown-function failure for both retained queries. Both corrected
complete queries have zero diagnostics against the deployed table schemas.
This is local language validation. Native rule creation, alert firing and
recovery remain unproved until managed execution. The next package keeps
skipQueryValidation false and requires native admission of the two rules
before starting application proof. The prior Provider validation alone did
not establish successful query creation and will not be treated as such.
[Microsoft Kusto language service](https://github.com/microsoft/Kusto-Query-Language)
[Percentile aggregate](https://learn.microsoft.com/en-us/kusto/query/percentiles-aggregation-function?view=azure-data-explorer)

The November 17 scoped ActualCost read returned no posted rows for the exact
campaign group and shared Automation account, without another page. Billing
remains unsettled. The recorded campaign lifetime from 15:55:00 to 17:04:29 UTC
is covered by a two-hour occupancy allowance. A conservative retained-rate
estimate is $8.9280, including daily ACR and DNS allowances, the existing
maximum diagnostic/scan/transfer allowances, and control-plane reserve.
There were no application replicas, application job executions, restore copy, model calls
or test emails to charge from this attempt. The proposal rounds the exposure
reserve to $9. This reserve is an estimate and must be reconciled against
later posted usage.

The successor forecast remains $39.4128, or $49.2660 with 25% contingency.
Propose a $49.75 ceiling for successor execution plus the $9 prior-cost reserve.
The combined allowance would become $58.75 and the cumulative ceiling would
be $409.64. This requires an explicit $8.75 increase from the existing $50
combined allowance. Local preparation authorizes none of that spending.
The package binds the cost calculation and rejects inconsistent reserve,
successor allowance, net increase or cumulative total.

The scope remains the temporary Canada Central campaign with East US private
HA Redis, existing signed API/frontend images, selected VPN/DNS and temporary
Entra access. The approved vault property correction is included. The
first-whole-UTC-minute-after-approval rule and +2/+10/+11/+12 deadlines remain.
The private runtime uses the same successful short directory depth, with
canonical source staging exercised before requesting execution approval.
Successful historical regional/component evidence is credited. Native
allocation, route, two alert rules, application observations and 48-counter
cleanup are still required during a future separately approved execution.
PostgreSQL, M78-D-001 and M78-D-002 remain closed.

The new temporary Gmail app password is named OpenCanvas M78 alert successor.
It is bound only in protected files, checked for format and difference from
the revoked predecessor, and awaits actual provider acceptance. Its cleanup
requires owner revocation and absence confirmation. The old packages and
terminal receipts remain immutable.


## Alert repair execution result

**Milestone 7.8 remains incomplete.** The November 17 execution of approved
package `d129f0c9810a3b7da589a066c846702e366f40e3a55a4c52dadfadb8192b8daa`,
source `d2c3285053603a80060dd1c9129c52a92129eef8`, stopped at bootstrap admission.
PostgreSQL, M78-D-001 and M78-D-002 remain closed. Their acceptance and cleanup
are unchanged. No application proof was started by this attempt.

The approval receipt is `2026-11-17T18:00:59Z`; the first strictly subsequent
whole-minute start is `2026-11-17T18:01:00Z`. The unchanged deadlines were
readiness `2026-11-17T20:01:00Z`, proof stop/scheduled cleanup
`2026-11-18T04:01:00Z`, Automation expiry `2026-11-18T05:01:00Z`, and operator
cleanup verification `2026-11-18T06:01:00Z`. There was no extension.

| Existing observation / operation | Actual result |
|---|---|
| Cleanup admission | Exact native schedule and binding accepted before billable provisioning; controller renewal preserved published content, identity and permanent Reader authority. |
| Repaired alert creation | **Accepted:** `api-latency-v1` and `database-saturation-v1` were created successfully and exact native query/criteria readback matched, with `skipQueryValidation=false`. Catalog thresholds, timing and recovery requirements were preserved. This closes the demonstrated query-creation failure; it does not accept firing/recovery. |
| Retained signed images | API index `sha256:9ec275f46b587fde50aaf7e04f4ed93f30edac4efd45da9452790e5be91f1d12` and frontend index `sha256:1ee742b604d406ad8cc4c3c53001853ad58a033b68f4d613251ea7fc088fdb3a` published and verified. Five retained endorsements reverified under the approved key-only policy. Exact-IP ACR access restored to private within its 20-minute bound. No image build. API image used by the bootstrap jobs; frontend application deployment remains unproved. |
| Foundation / jobs | Native root foundation and jobs deployments succeeded. Migration and application deployment were not started. |
| Normal bootstrap | **Failed:** `caj-m78p-a712b8c940-bootstrap-89iuxe9`, stage `configuration`, `RuntimeError`. Bicep supplied `OPENCANVAS_DATABASE_ROLE=migration`; the existing script requires `provisioning`. Failure occurred before database-client initialization. |
| Guarded retry | **Failed:** `caj-m78p-a712b8c940-bootstrap-69rtnif`, stage `retry-inspection`. The operator selected the existing guarded retry after the role correction; its validator rejects initial schema owner `azure_pg_admin`. No validator was relaxed. |
| Catalog diagnosis | `caj-m78p-a712b8c940-bootstrap-qsmh9q0` succeeded as a **read-only diagnostic**. It found zero application roles, relations, functions, revisions, other bound bootstrap/migration sessions and migration locks. This is not application acceptance. The normal bootstrap already transfers initial schema ownership; a fresh normal execution needs the provisioning-role correction, not a weakened retry validator. Managed success of that corrected normal path remains unproved. Cleanup had begun and this attempt was not reopened. |
| Private access | Native gateway/profile generation succeeded. The downloaded profile uses the native DataContract XML namespace. The local adapter originally rejected that layout; the focused correction preserves the namespace, server trust, identity/gateway checks, private DNS and split route. No VPN client connection profile was saved or connected; the unused forms were cancelled and the native connection list was empty. Private browser/query/export acceptance remains unproved. |
| Application and destination acceptance | **Unproved:** all 16 required alert firing/recovery pairs, actual required API/worker/outbox signals, 13 dashboard renders, privacy/rejection/outage/access/retention, delivery/password reset, recovery, capacity, remaining infrastructure categories and real-stack editable-AI observations. No SMTP message, model request, embedding token or ordinary application HTTP request was used. Prior evidence stays credited. |
| Cleanup | **Verified:** Automation ARM job `38640cf9-db05-455b-9967-42729b1c9387` completed; returned jobId `1a4fe8d5-ef64-4d5e-9dbb-930d2e2574fe` is recorded separately. Exact target absence observed at `2026-11-17T19:24:59.229923Z`; all **48 counters zero** at `2026-11-17T19:27:39.018129Z`. Canada Central named vault purged, managed infrastructure group absent, five scoped role definitions removed, exact schedule/binding/grants disarmed, temporary tenant objects purged, VPN route/NRPT/profile absent, and owner confirmed Gmail credential removal and closed/unused restricted-user window. Controller preserved. The initial CLI wait timeout was reconciled by native job/group readback, without another deletion dispatch. Operator ledger is `cleanup-disarmed`; the legacy PostgreSQL finalizer was not used for this broader 48-counter campaign. |

The local checkpoint corrects only the bootstrap role and native profile
namespace handling, with three new regression tests and two affected legacy
profile regressions passing, plus focused lint and Bicep compilation. The applied
bytes match that evidence. Normal bootstrap keeps its original command and
separate bootstrap identity; migration retains its migration role/identity.
The retry validator and signed API/frontend build inputs are unchanged. No
whole application suite, image rebuild or completed component campaign ran.

The terminal scoped ActualCost query succeeded with complete pagination and
**no posted rows**. This does not establish zero charges. Billing remains
**unsettled**. Approved forecast $39.4128, successor ceiling $49.75, prior
reserve $9, combined allowance $58.75 and cumulative ceiling $409.64 remain
as approved. No fresh campaign allowance or successor execution is implied.
Any future package must reconcile this exposure and obtain its own execution
approval; do not automatically restart or reset deadlines.

Private evidence remains outside Git in
`.runtime/milestone_7_8/full-closure-prerequisites/run-d129f0c9/`; the exact
operator bundle is `.runtime/milestone_7_8/c9s/`. The approved sealed package,
prior failures, local image archives, encrypted release key and five protected
stashes are preserved. These sanitized references disclose no credentials,
tenant/subscription identifiers or private endpoints.

| Receipt relative to the private evidence root | SHA-256 |
|---|---|
| `verified-full-residue.json` | `a975113ecae64fae6a7d8a50dfe957cab679e8a5d395a9f1238a9f9e9a4bc706` |
| `corrected-alert-native-admission/accepted.json` | `e431cfdba412bd21cd9ad94036099aaeda077fc9b1611da9b2dae29f5c6db849` |
| `signed-publication/private-network-restored.json` | `b25fe53fbb3cb8d39b6af6f059de632054e98945b0f15598442b53858644d67c` |
| `native-admission-readbacks/cleanup-protection-accepted.json` | `0686237672da906807b72f51ba1589331332064cde4512191ff377dcb72ac53a` |
| `bootstrap-reconciliation/configuration-diagnosis.json` | `fceee6b65de0b0831293df6a1889cbdff556dabff6ca451fdd0788ee1ebbefe9` |
| `activation/bootstrap-terminal.json` | `1b26481a23a81d80b405492329d7869297eeb61537d2a2e22fe2de989ae44e81` |
| `bootstrap-reconciliation/retry/terminal.json` | `5e83281a56f0a6d76bcab002ba2736694bec898ef14d205098e3f8d671b0f22a` |
| `bootstrap-reconciliation/catalog-diagnostic/catalog-result.json` | `c5e01f4c6f61f60bad8f3f478b35e89651ea8efa0a751a31ed085b557722c615` |
| `bootstrap-reconciliation/catalog-diagnostic/terminal.json` | `fe735357e9981a272267b1c6b5ec8b766d5aac520f9f13583c307c78ed82c6e3` |
| `local-control-validation/accepted-v2.json` | `fccb78529a25ed18ab96b7c59b8edd82e95e3bdfa75b8649ba63de89d65c4a9f` |
| `local-control-validation/applied-byte-check.json` | `9acb556e64be85ddc3fe3888e597a03ffe4f0f6d71ad93e0efcfeb86f9a0ffa0` |
| `owner-terminal-access-receipt.json` | `7afa15848db0e6e3fac0324b648a45ad139766f16ef6a3c900b545cf4a1b8a8c` |
| `terminal-cost-summary.json` | `f2ac54b48a1d8dec265902a45e89eb1abe36a37cd33007b1e65b0d21c4ebd3a6` |
| `terminal-cost-native-response.json` | `49eb58f0f576089ce619b53ad467264b2050a5274201c727416629a65fc59f5a` |
| `terminal-results.json` | `00d38aedbd1099b86311c2d46c2dffd16b7e884c12edd97a042d60419e768919` |

## Bootstrap successor preparation

The compiled pilot job supplies the provisioning role to the existing normal
bootstrap command. Before dispatch, the activation driver checks the exact
signed API digest, command, role and empty execution inventory. Only the
specific known pre-I/O failure can qualify for the role-only recovery path.
The exact sole terminal execution, native console and current job must agree.
An ambiguous start, later-stage failure, template drift or incomplete
inventory stops that path. The existing database retry validator is unchanged.

The retained API image ran the shipped bootstrap entry point against isolated
PostgreSQL 17, starting with an empty schema owned by azure_pg_admin. The
wrong role stopped before client initialization. The corrected normal path
installed vector, set the migration schema owner, provisioned four
nonprivileged roles and verified schema privileges and evidence monitoring.
The local fixture supplies Entra mappings and substitutes local authentication
and transport. Native Entra, TLS, migration and application acceptance remain
open. The pre-I/O recovery validator consumed the retained native failure
and rejected six conflicting or incomplete variants.

The scoped ActualCost refresh returned 36 target rows totaling $0.8227223512
and one shared-controller row showing $0. The target ID was reused on the
same UTC day, so the query does not allocate charges by attempt. Billing
remains unsettled. Retain the previous $9 exposure reserve and add $10 for
the bootstrap attempt, whose bound resource lifetime finished within two
hours. At retained rates, the same conservative dependency allowance plus
three maximum-duration bootstrap jobs estimates $9.0414. Use the posted
total as reconciliation evidence, without deducting it from this reserve.

The successor forecast is $39.4128, or $49.2660 with 25% contingency, against
a proposed $49.75 execution ceiling. The $19 exposure reserve brings the
combined proposal to $68.75 and cumulative ceiling to $419.64. The requested
increase is $10 over the last approved cumulative ceiling. Any execution
requires separate approval of the sealed package and fresh deadlines.

## Bootstrap successor execution result

**Milestone 7.8 remains incomplete.** Package
`15305be1354ee6898baa400e88b4c09275e7c7f1a9c36d450e41ce1af6dfc13f`
used source `73023ec797dc883b073b11411e736a27c360f467`. PostgreSQL,
M78-D-001 and M78-D-002 remain closed. Earlier failed attempts and accepted
observations remain in the record.

Approval was recorded at `2026-11-17T23:41:41Z` and execution started at the
first strictly subsequent whole minute, `2026-11-17T23:42:00Z`. The sealed
deadlines were readiness `2026-11-18T01:42:00Z`, proof stop and scheduled
cleanup `09:42:00Z`, Automation expiry `10:42:00Z` and operator cleanup
`11:42:00Z` on November 18. Core and destination readiness were unproved at
the first deadline. The operator stopped new proof and invoked early cleanup
under the existing authority. No deadline was extended.

| Existing observation or operation | Native result and limits |
|---|---|
| Cleanup admission and foundation | **Accepted.** The exact schedule and runbook binding were read back and armed before workload provisioning. The native foundation, jobs and application deployments succeeded. The private Canada Central vault passed the purge-compatible readback. |
| Corrected alert creation | **Accepted.** Exact native readback matched `api-latency-v1` and `database-saturation-v1` queries and criteria with `skipQueryValidation=false`. The 16 firing/recovery pairs remain unproved. |
| Signed images | The retained API and frontend indexes were published and verified. Native API and frontend resource readbacks matched both sealed indexes in the private environment. Five detached endorsements were reverified. The bounded ACR exception was closed and the registry returned to private access. No images were rebuilt. |
| Normal bootstrap and migration | **Accepted.** `caj-m78p-a712b8c940-bootstrap-491oyxk` completed with the provisioning role. `caj-m78p-a712b8c940-migration-52kfosq` completed with the migration role. The guarded bootstrap retry was unused. |
| Private operator route and initial application readback | **Accepted for connectivity.** The native VPN client connected after the native XML layout was preserved. The exact split route and 12 DNS suffix bindings were observed, with private TLS to API, frontend, storage and Log Analytics. The frontend returned HTTP 200 with HTML and the API returned HTTP 200 for the staging runtime. Restricted-user sign-in and MFA were owner-confirmed. Workbooks, query revoke/restore and destination export remain unproved. |
| Application account artifact | The initial archive exceeded the unchanged 2,000,000-byte limit before job dispatch. A lossless compact representation of the native bindings fit. `caj-m78p-a712b8c940-artifact-v06ewvl` then failed the reconstructed ZIP hash check before Blob PUT because Windows and Linux supplied different ZIP platform metadata. With deterministic metadata, `caj-m78p-a712b8c940-artifact-v1riik8` staged successfully, with exact version and hash retained. |
| Account signup and API readiness | **Signup outcome unknown.** `caj-m78p-a712b8c940-evidence-qpfnqo1` timed out on the initial signup POST. Native console and replica observations tied startup failure to an empty operator allowlist in the staging configuration. An explicitly approved change supplied one reserved UUID outside the generated user ID space, with no operator grant. The new vault secret version was read back, affected revisions refreshed and private API readiness returned HTTP 200. |
| Signup reconciliation | The first job-start override was rejected before execution because it included `volumes: null`. Omitting that field allowed one read-only execution, `caj-m78p-a712b8c940-migration-sw49nqc`. The operator's query counted all rows, including the migration's known seed ID, and returned one. That count did not establish the identity of the row or absence of a signup effect. The retry guard held. A corrected filtered observation and signup retry were never dispatched. |
| Remaining application proof | **Unproved.** No accepted account or core receipt. Destination signals/privacy, dashboards, alert delivery/recovery, worker and external delivery, password reset, restore and rollback, capacity/faults, remaining infrastructure diagnostics and the real-stack editable-AI scenarios remain open. No email or model request was sent, and no embedding usage was incurred. See the [finite closure ledger](MILESTONE_7_8_FULL_CLOSURE_LEDGER.md#existing-criteria-and-disposition) for exact remaining observations. |
| Cleanup | The exact Automation ARM job `823f3b34-8777-44fd-9f3f-a430920b8e9f` completed and its target group was verified absent. The operator ledger is `cleanup-disarmed`. The Canada Central vault and the temporary Entra objects were purged. The managed infrastructure group, five scoped roles, schedule and binding, and campaign VPN profile, routes, DNS policy and import files are absent. The reusable controller was preserved. **All 48 cleanup counters are verified zero.** The final two counters were closed by the owner confirming that the restricted Entra window was closed and that the campaign Gmail app password was revoked and absent. |

The checkpoint stabilizes ZIP metadata across Windows and Linux in the host
packer and runtime reconstructor. It preserves native VPN XML serialization
outside the bound DNS, split-route and client identity fields. Five focused
tests and lint passed, including paired archive staging and resolved VPN
namespace and trust cases. These are local controls. A future package would
need to stage bounded compact bindings, validate the initial operator
allowlist against the signed runtime and reconcile signup against the exact
migration seed before authorizing a retry. No timeout or assertion was relaxed.

Billing remains **unsettled**. The complete scoped ActualCost read returned 43 posted rows and a target-scope total of $0.878883172874073911 USD. The exact target ID was reused, so the query cannot allocate this total to the successor attempt. The $39.4128 forecast, $49.75 execution ceiling, $19 prior exposure reserve, $68.75 combined ceiling and $419.64 cumulative ceiling remain as approved. No additional execution or allowance is implied.

Private evidence and the unchanged approved package remain outside Git under
`.runtime/milestone_7_8/full-closure-prerequisites/`. Run evidence is in
`run-15305be1/`, with the exact operator bundle in
`.runtime/milestone_7_8/cbs/`. The retained signatures, image archives,
controller and all five protected stashes are preserved.

| Receipt relative to the private run directory | SHA-256 |
|---|---|
| `azure-cleanup-terminal.json` | `220b955d691e8c6e3a223b62e4b5acd51fb9eb34c55a960a185bead006e11851` |
| `bootstrap-migration-accepted.json` | `4e286cf069fa156797c96b8d1a93765b4139abfad7805b4b500ee63251e242ce` |
| `corrected-alert-native-admission/accepted.json` | `5499d828a17a216a0e0ca79051b36fa2df7131cfd0289c645689cdc7ab69bc22` |
| `native-admission-readbacks/cleanup-protection-accepted.json` | `e340e9476b3be417871f4531c9406ff86f2d853f430fa78c7adbe8370d87121b` |
| `native-image-deployment-readback.json` | `06ce29cd3d0a0291e24fb0bf500f5e7cfd7eaea80cfacad3e78183662cb997cd` |
| `operator-list-reconciliation/correction-review.json` | `d4a26ed34c50b75050e24beb659f94bfee4c2a604bd5d2cf1b41c9b8c306c535` |
| `operator-list-reconciliation/native-ready.json` | `37da7b9d73932a40661e187adb9cd9c846ee0151c2fbc189624dc89ec8337353` |
| `operator-list-reconciliation/native-user-count.json` | `35dca123fbbe60bdc3d937d4c77bc3945f0d05c2be4aed21198c067fd2e0573e` |
| `operator-list-reconciliation/signup-count-correction-review.json` | `67ab600db9f6c75769d7774f1a03da4a8b0597e5864e0a6361b5271672a3dc3d` |
| `private-frontend-readback.json` | `77f8135eb94188d71cc650bbbfc19a07ea455dec24eb7ac8bd9a8c6eae014637` |
| `proof-account-linuxzip/artifact-version-binding.json` | `a482e56680dfdcd23bbe464cbdff9f93fe7c5b67196621843da4be1eb9e588df` |
| `proof-account-linuxzip/failure-export/export-manifest.json` | `44c44fe7f70aceb5b521ef706fd2527b54de52b04143a2efeb1ee22c0d9aca5e` |
| `proof-account/artifact-terminal.json` | `48588d9d015aa7f59d1c72e206609cf0acf58eb6eda2b789e53b8a3d9d8700f8` |
| `proof-account/minified-pack-measure.json` | `383ebaad8e22d94d0e293204cf9aeb30fd1a9a627949213e0a802b5a66b6d78f` |
| `signed-publication/private-network-restored.json` | `9885de42538820a7901512a5680457d4e4a655b232b1e33fc612e9d0ccfe32ef` |
| `stop-proof-intent.json` | `ad7f6e890a1bd1553ab09385430a4db1e9250f73f6d2040659fa571c5291433c` |
| `terminal-cost-summary.json` | `91f52058e1218606aacc156c00868c4db1cf414d4a1e8f852e6ceb892e6e97b7` |
| `verified-residue-owner-pending.json` | `b5d514620742a048ca7e376dfa1ce7d5eeb32db346cb81a7eb963c6fb532f77b` |
| `vpn/private-route-admission/accepted.json` | `33b0d6d2748630d1e4b21b7edc615f612459ba1541f878a29054dddcb780235a` |
| `terminal-results.json` | `acdf5ca22024f2c877b1cdb9ff6e8ebab8c6a1e4dc0b33a968f40f628a548855` |
| `owner-terminal-access-receipt.json` | `ad7d9490e2f0ac9b5886af959d255dec3a3d40823a815dc291042a88ea368fcd` |
| `verified-full-residue.json` | `03800163293644dfc1702a2b657d8c014f2ecf2bda5e98d98f272bab01504b50` |
| `terminal-results-cleanup-complete.json` | `85bab905a547062209540bc0606eb5ff75c71925b36bbbb80ea4ec2bd009859d` |

## Prepared signup recovery successor

The successor stages the approved deny-all operator allowlist from the first
deployment. The account probe must receive HTTP 200 and the expected service
and readiness fields from the bound private API before issuing a signup.
The signed API and frontend images are reused. Accepted bootstrap, migration,
VPN and corrected alert creation remain credited. A fresh isolated target
still needs its normal startup and private route readbacks.

After a new signup POST times out, preserve its intent and verify that the
exact evidence execution is terminal. The scoped recovery stops the isolated
API and worker with the dispatcher paused. The retained migration job reads
one consistent, read-only PostgreSQL snapshot. It checks the migration seed
and exact bound primary and secondary account identities, plus the committed
session, workspace, membership and owner transition, authority, audit and
trace records, domain event, provenance and outbox row. A partial or
contradictory record, an unexpected identity or an unfenced writer blocks
continuation. When the snapshot has only the migration seed and the writers
are fenced, the absent signup may be retried. A complete existing account is
reused through sign-in and exact ID comparison. A complete primary and absent
secondary permit sign-in to the primary and creation only of the secondary.
The old POST remains unknown because its original database was cleaned up.

The prior run admitted bootstrap and migration at +43m56s, application
activation at +48m31s, private VPN at +48m50s, and private API readiness at
+78m09s. The old +120m gate then left under 42 minutes. The three sequential
core scans may consume up to 45 minutes before account, indexing, provider
and export work. The proposed gate keeps infrastructure and private readiness
at +2h and moves core and destination readiness to +3h. It shifts the later
proof phases one hour, preserving their durations and the two-hour cleanup
window. New proof stops at +11h, Automation expires at +12h and operator
cleanup is due at +13h. These are bounds for a new approval. A missed gate
still triggers cleanup.

At the retained November 17 retail rates, the extra hour adds **$1.4049**.
The new forecast is **$40.8177** or **$51.0221** with 25% contingency. Three
hours of peak occupancy and retained data/operation caps estimate
**$11.8669** for the last attempt, which deleted its Azure group at +150m31s.
Adding a **$12** reserve to the carried **$19** leaves **$31** for unsettled
prior exposure. The **$0.878883** posted against the reused target cannot
be attributed to one attempt and is included in the exposure reconciliation.
Propose an execution ceiling of **$56.51**, a combined ceiling of **$87.51**
and a cumulative ceiling of **$438.40**. Billing remains unsettled.
[Azure Retail Prices API](https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices)
