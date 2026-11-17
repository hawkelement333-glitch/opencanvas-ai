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
