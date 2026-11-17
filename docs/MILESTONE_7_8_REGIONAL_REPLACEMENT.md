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
