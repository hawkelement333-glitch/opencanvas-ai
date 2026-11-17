# Milestone 7.8 window and operator-access proposal

Local preparation only. No Azure resource, role assignment, VPN client change,
paid/authenticated provider call, message or deployment was executed. Public
unauthenticated retail-price reads are identified below. The user selected admission6
per API replica, lock-stage concurrency13, and Firewall/VM diagnostics as not
applicable to the proposed ACA topology. Historical missing evidence remains
unproved; networking, egress and deployed-resource diagnostics still apply.
The user selected the +2/+10/+12-hour window for preparation. Spending/cleanup
approval remains separate. Optional access additions remain unselected. Billing remains **unsettled**.

## Recommended window

Revise the prior +2/+8/+10-hour proposal to **+2/+10/+12 hours**: services/core
ready by+2, stop proof and scheduled cleanup at+10, verified cleanup by+12.
Merely beginning provisioning at+2 cannot satisfy the ready gate. Retain all
existing alert windows and workload caps. The unchanged early sequence reaches
capacity/native recovery by+6h35. Give current-release restoration/reconciliation
**two hours** until+8h35, final evidence export/validation **one hour** until+9h35,
and retain25minutes contingency before the+10 stop. Cleanup keeps two hours.

This replaces the previous55-minute restore and25-minute export allocations.
It is an engineering recommendation, not a provider completion guarantee or
accepted RTO. Actual PITR, source/restore fencing, rollback, grants, exports and
native delivery still need measured evidence. If a gate is missed, retain
partial results and enter cleanup; never compress acceptance windows or extend
authority implicitly. Bind absolute UTC deadlines only after approval.

| Relative gate | Required state |
|---|---|
| +2h | Services, core fixtures, private operator route and destination ready |
| +3h35 | Core-only index recovery and native resolution complete |
| +4h05 | Capacity fixtures ready |
| +4h45 | Other finite capacity phases complete |
| +5h30 |45-minute pressure observation period complete |
| +6h35 |60-minute healthy/native capacity recovery complete |
| +8h35 | Current-release restore, reconciliation and original rollback complete |
| +9h35 | Exact-version evidence export and final validators complete |
| +10h | Stop proof; scheduled cleanup starts |
| +12h | Cleanup verified within authority |

Restore-copy allocation increases from4 to6hours: a copy requested around+6h35
may remain until cleanup finishes at+12. Main resources are conservatively
charged for12hours. Earlier proof phases,200 model attempts,160M embedding
tokens,10,000 application HTTP requests,40-minute helper overlap,1GiB logs,
1GiB scanning and10GB stored/processed/egress bounds remain unchanged. Time is
not permission to increase request or provider allowances. Core/index/capacity
reservations retain their fixed partitions.

## Cost reconciliation

Reusing the retained [cost model](MILESTONE_7_8_PILOT_COST_MODEL.md), the longer
window adds **$1.7796**, changing the current full-closure forecast from$29.3238
to **$31.1034 USD**. No fresh subscription billing query was made.

| Extended allocation | Incremental USD |
|---|---:|
| ACA3.25vCPU/6.5GiB, additional2hours |0.7020|
| Primary and restored PG, each2vCore for additional2hours |0.7120|
| PG32GB storage, combined additional4server-hours |0.0202|
| Main PG32GB excess-backup allowance, additional2hours |0.0083|
| Redis two HA B0 nodes, additional2hours |0.0640|
| Blob10GB storage, additional2hours |0.0006|
| Defender account, additional2hours |0.0268|
|16five-minute alert rules, additional2hours |0.0658|
| Six private endpoints, additional2hours |0.1200|
| Event Hubs1TU, additional2hours |0.0600|
| **Total calculated before rounding individual rows** | **1.7796** |

ACR remains one full day and DNS two billable days; fixed request/data/provider
allowances remain unchanged. Proposed incremental ceiling **$50**, proposed
cumulative ceiling **$400.89 only if approved**. Prior approved$350.89 is not
settled charges or reusable authority. The existing controller's allowed ceiling
is not approval. No ongoing-hosting proposal is included.

Private arithmetic and input hashes:
`.runtime/milestone_7_8/full-closure-prerequisites/selected-preparation/window-cost-proposal.json`.
The proposed schedule is `operator-schedule-proposed.json`; it preserves old
private manifests and binds the selected admission decisions separately from
the still-unapproved longer window. Source/image/signature/absolute-time
bindings remain the root package's finalization responsibility.

## Short secure-input checklist

Fill only missing values in the protected local
`.runtime/milestone_7_8/full-closure-prerequisites/inputs.private.json`.
No values belong in chat, Git or command arguments. Tenant/subscription,
selected model names, embedding model, STARTTLS587, exact vault and East US are
already known. Presence-only inspection found the following inputs unavailable;
no credential store or live Entra/role inventory was searched.

1. `openai.apiKey`: existing project credential; project/organization IDs if
   applicable. Owner confirms `gpt-5.6-terra` and `text-embedding-3-small`
   entitlement. No paid validation now.
2. `smtp.host`, `username`, `password`, `fromAddress`: existing permitted
   STARTTLS account/sender. `approvedInbox` and `nativeInboxReceiptMethod` must
   identify how the actual received MIME and native receipt will be obtained.
3. `operator.entraObjectId`: exact existing user object ID. It differs from
   application operator UUIDs, which are bound to the actual synthetic accounts
   after creation. Cached login is not current permission evidence.
4. `operator.privateRoute.*`: existing gateway/peered-host resource ID, browser
   location, route evidence and private DNS resolver IPs. An ACR public /32 is
   not a private route. If none exists, explicitly say so and select or reject
   the optional route below; nothing is created by entering a preference.
5. `cleanup.executorObjectId`, `purgeExecutorObjectId`,
   `effectivePermissionEvidenceFile`: existing entitled executors and current
   permission evidence, or identify the subscription administrator who will
   perform the exact purge. An RG Contributor grant alone is insufficient.

## If no existing private operator route exists

The concrete blocker is browser/workbook/native query and private evidence
export access from the operator workstation. Existing in-VNet proof jobs do
not prove that interactive route, and public Blob/Log Analytics access must not
be opened as a substitute.

Optional, **unselected** scoped access addition in East US:

- One **VpnGw1AZ** route-based P2S gateway using OpenVPN and Microsoft Entra
  authentication, one Standard static IPv4 public IP, one permitted operator
  connection, and the Microsoft Azure VPN Client on the existing workstation.
- One Azure DNS Private Resolver with one inbound endpoint; no outbound
  endpoint/ruleset is needed for resolution of zones already linked to the
  campaign VNet. The client uses that inbound private address.
- Reuse the campaign VNet `10.79.0.0/16`. Proposed free subnet allocations are
  `GatewaySubnet=10.79.9.0/27` and resolver `10.79.9.32/28`; confirm exact scope
  against final native readback. An operator client pool must be selected only
  after the existing workstation/VNet routes are checked for overlap.
- Names would be `vpngw-m78p-a712b8c940`, `pip-m78p-a712b8c940-vpn`,
  `dnsr-m78p-a712b8c940`, inbound endpoint `operator-inbound`, all only in the
  isolated target group. No VM, Firewall, public application ingress, NAT or
  permanent hosting component is added.

VpnGw1AZ is the smallest suitable current AZ gateway in this prepared option;
new non-AZ VpnGw1 creation is no longer supported. This is an operator-access
option, not new hosting-topology research. [Microsoft gateway SKU policy](https://learn.microsoft.com/en-us/azure/vpn-gateway/secure-vpn-gateway).
The Microsoft-registered VPN application avoids creating a new app identity;
access still must be limited to the approved operator/group by the tenant
administrator and client configuration. The required OpenVPN/Azure VPN Client
and tenant/audience/issuer settings follow the
[Microsoft P2S configuration](https://learn.microsoft.com/en-us/azure/vpn-gateway/point-to-site-entra-gateway).

For12hours the optional resource delta is **$5.5389**:
VpnGw1AZ$0.21/hour=$2.52, Standard IPv4$0.005/hour=$0.06,
DNS resolver inbound$180/month prorated by730hours=$2.9589.
One P2S connection is included; VPN data consumes the same existing10GB total
egress allowance, not an additional allowance. Current public Retail responses
for gateway/IP and the retained DNS meter are private evidence; the
[VPN pricing terms](https://azure.microsoft.com/en-us/pricing/details/vpn-gateway/)
and [DNS hourly proration](https://azure.microsoft.com/en-us/pricing/details/dns/)
explain the quantities. Combined forecast with this option **$36.6423**, still
under the proposed$50 ceiling, but the resources and access permissions require
explicit scope approval and cleanup bindings regardless of that headroom.

Required permissions: target-group Network Contributor or the equivalent exact
`Microsoft.Network` gateway/public-IP/subnet/DNS-resolver create/read/delete
and join actions; a tenant administrator authorized to restrict VPN enterprise
application access to the operator; local permission to install/configure the
Azure VPN Client. Existing application/workspace query and evidence-container
read roles remain separately required. No subscription-wide discovery or
permission grant is inferred. Setup can take substantial time: validate the
route before the+2h readiness gate, or stop with partial results. If an existing
route is supplied, this entire optional scope and cost are excluded.

Before selection becomes executable, compile the exact additional resources,
name/address bindings, gateway diagnostics, restricted tenant/client settings
and cleanup counters. Cleanup must remove the gateway, public IP, resolver,
inbound endpoint, dedicated subnets, temporary grants/client configuration and
any exact dedicated enterprise assignment, while preserving pre-existing tenant
objects. Do not add an unverified networking path to an approved manifest.

## If no entitled purge executor exists

The required operation targets only
`/subscriptions/<bound>/providers/Microsoft.KeyVault/locations/eastus/deletedVaults/kv-m78p-a712b8c940`.
However Microsoft documents subscription-level permissions for soft-deleted
vault operations: `Microsoft.KeyVault/locations/deletedVaults/read`,
`Microsoft.KeyVault/locations/deletedVaults/purge/action`, and
`Microsoft.KeyVault/locations/operationResults/read`. A promise of a new
resource-only grant would be unsupported. [Key Vault recovery permissions](https://learn.microsoft.com/en-us/azure/key-vault/general/key-vault-recovery?tabs=azure-portal).

Smallest no-new-grant option: an **existing subscription-entitled administrator**
performs only the separately approved named-vault purge and native terminal
readback, preserving the operation ID/activity evidence. This adds no resource
or license cost. That person's object ID, confirmed availability within cleanup,
and exact permissions must be bound before spending. If no such principal can
act, an administrator must explicitly authorize suitable time-bounded access;
Key Vault Purge Operator is a possible built-in role but has broader
subscription scope and is not silently granted here. Its assignment/removal
would require `Microsoft.Authorization/roleAssignments/write/delete` from an
entitled administrator and separately reviewed scope/expiry. Existing PIM
licensing/eligibility must not be assumed. Until resolved, cleanup authority is
blocked, so provisioning is blocked.

## Signed provenance criterion

The exact existing [architecture15.3](MILESTONE_7_ARCHITECTURE.md#153-infrastructure-security)
criterion is “signed build provenance and image/dependency inventory.” The
runtime threat-model row additionally refers to minimal signed images and
SBOM. The inspected criterion does not explicitly require a named CI builder,
certificate issuer, public transparency log or SLSA level. This permits proposing
trusted local endorsement of the retained build-provenance/image/inventory
bindings; it does not make local provenance authenticated CI provenance.

The user subsequently approved fingerprint
`856f48ad36a3f8787619c96b857cbad0e7583e768f76ec4ff653092f572ec789`
for local release endorsement under this key-only policy.
A key-only policy must still pin the explicitly trusted public key, verify the
exact signed content and transitive image/inventory hashes, and disclose absence
of transparency-log assurance. No criterion is weakened and no signature is
accepted merely because a key was generated.
