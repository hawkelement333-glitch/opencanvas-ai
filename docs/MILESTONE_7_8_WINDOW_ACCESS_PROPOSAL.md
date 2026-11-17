# Milestone 7.8 window and operator-access proposal

Local preparation only. No Azure resource mutation, role assignment, VPN client
change, paid provider call, message or deployment was executed. The scoped
read-only account/permission checks below are now authorized and retained. Public
unauthenticated retail-price reads are identified below. The user selected admission6
per API replica, lock-stage concurrency13, and Firewall/VM diagnostics as not
applicable to the proposed ACA topology. Historical missing evidence remains
unproved; networking, egress and deployed-resource diagnostics still apply.
The user selected the +2/+10/+12-hour window for preparation. Spending/cleanup
approval remains separate. The user selected the temporary VPN/private-DNS option for preparation only. Billing remains **unsettled**.

## Account and access resolution after the signed checkpoint

Preparation continues from source checkpoint
`80a9e6f6ab79bae92fcba95081ef0d3ec30d7f4f`. The signed API/frontend bytes,
accepted key policy, closed PostgreSQL/D001/D002 evidence and selected window
are unchanged. No passing test or image build was repeated.

Scoped read-only checks of the already-bound subscription established:

- The current Azure CLI account matches the bound subscription and tenant;
  native subscription read and signed-in Entra user lookup succeeded.
- The signed-in principal has existing unconditional subscription Owner
  assignments. The native role definition and current permission response
  include the three regional deleted-vault purge/readback actions, campaign
  resource-group deletion and role-assignment cleanup. The at-scope deny query
  returned no assignments and no continuation page. This is observed current
  permission evidence, not execution authority or a guarantee of future access.
- The same principal can be proposed for operator, cleanup and exact-vault
  purge duties without a new subscription-wide grant. Its identity and native
  evidence are retained privately; the user confirmed availability through the later
  approved cleanup deadline. Recheck permissions at
  execution admission and before cleanup. Purge remains restricted to the named
  campaign vault; preserve the reusable controller and pre-existing grants.
- No Windows VPN profile was returned, while Azure VPN Client is installed.
  This does not establish that its separately managed profile is absent or
  that an existing private route works. No existing gateway/host was identified; no broad network inventory was run. The user subsequently confirmed no existing route and selected the temporary option for preparation.

Private evidence lives in
`.runtime/milestone_7_8/full-closure-prerequisites/access-resolution/`:
`bound-account.json`, `subscription.json`, `signed-in-identity.json`,
`signed-in-role-assignments.json`, `assigned-role-definition-0.json`,
`subscription-effective-permissions.json`,
`subscription-deny-assignments-corrected.json`, `permission-evidence.json`,
and `workstation-network.json`. The permission receipt binds native file hashes.
An initial deny query failed in the Windows command wrapper before an Azure
request because of query-string escaping. The corrected direct CLI interpreter
query succeeded; retain the initial diagnostic rather than calling it a
permission denial. No token retrieval/output was used.

### Supply account values without inventing identifiers

Edit only missing fields in the protected `inputs.private.json`; text values
must be quoted JSON strings and confirmations must be booleans. Do not paste
secrets in chat or shell arguments. Preserve populated model/tenant/subscription,
STARTTLS, signing and window fields. Local syntax/presence checks do not prove
remote credential validity. A file being edited must not be overwritten by an
automated identity merge.

1. In the existing OpenAI Platform project, obtain the project credential from
   its API Keys settings and the project ID from General. Supply organization
   ID only where explicit organization selection is needed. The owner checks
   the prefilled models under Limits/Model usage before setting
   `openai.entitlementConfirmedByOwner` to true. Application calls use Responses
   and Embeddings; an admin API key is not required. Do not make paid calls to
   confirm entitlement during preparation.
2. Identify the existing email provider first. Copy its documented STARTTLS587
   host and account into `smtp.host`, `username` and `password`; use the exact
   permitted address in `fromAddress`. Select an inbox the operator can access
   for `approvedInbox`. Describe the native message export/receipt procedure in
   `nativeInboxReceiptMethod`. The existing password-reset validator requires
   received raw MIME, Message-ID, actual received time and approved receiver
   identity; SMTP acceptance alone is insufficient. No test message is sent.
3. The signed-in Entra object ID is already resolved privately; the user need
   not look up or invent it. If an existing private route is available, identify
   its Azure VPN connection/gateway or private workstation/host. Copy that
   specific resource's Resource ID from Azure Portal Properties, or supply its
   exact name and resource group for a scoped lookup. Record where the browser
   runs and the configured private DNS resolvers; derive those values from the
   route, not from example addresses. Selecting the optional route is a separate
   preparation decision before templates, client pool and cleanup are frozen.
4. Existing Owner permissions remove the need for a new purge-role proposal
   for the signed-in principal. Confirm it will remain available for the later
   approved cleanup window, or identify the alternate existing executor for
   a scoped permission check. Do not assign a new role during preparation.

The earlier retained candidate package remains unapproved and superseded by the final package assembly. Do not
reuse its hash as final spending approval after access bindings change. Provider credential format, Gmail fields, owner-confirmed model access, the
private-route choice and cleanup availability are now resolved. Final package
assembly binds these private inputs without exposing them in Git. Derive absolute deadlines from that later approval.

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

Selected for preparation only, scoped access addition in East US:

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
The Microsoft-registered VPN client is retained. A dedicated single-tenant
audience application and service principal are now included in the proposed
execution scope to restrict this gateway to the one approved operator. The
service principal requires assignment; only that user receives its app role.
The shared Microsoft application and pre-existing enterprise assignments are
not modified. This corrects the earlier assumption that the standard audience
alone established operator restriction. The required OpenVPN/Azure VPN Client
and tenant/audience/issuer settings follow the
[Microsoft P2S configuration](https://learn.microsoft.com/en-us/azure/vpn-gateway/point-to-site-entra-gateway).

For12hours the optional resource delta is **$5.5389**:
VpnGw1AZ$0.21/hour=$2.52, Standard IPv4$0.005/hour=$0.06,
DNS resolver inbound$180/month prorated by730hours=$2.9589.
The tenant application and direct-user assignment add no metered resource charge.
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

The selected templates, native-binding validators and exact command/cleanup
sequence are now prepared in [operator access execution](MILESTONE_7_8_OPERATOR_ACCESS_EXECUTION.md).
Six new offline boundary tests passed and the composed Bicep compiled.
The only compiler warning is the pre-existing managed-object secret-input warning.
Native delivery and private connectivity remain unproved until approved execution. Cleanup must remove the gateway, public IP, resolver,
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

## Resolved input status

The OpenAI key/project fields and Gmail app-password fields passed local syntax
checks. Owner-confirmed model entitlement is recorded; no provider authentication
or inference was attempted. The approved Gmail inbox supplies original received
MIME and native receipt evidence during execution, not a fabricated delivery
receipt. The user confirmed the signed-in account for VPN and cleanup through
the eventual +12-hour deadline. Native Entra membership additionally showed
Global Administrator, so no new tenant admin role is proposed. Its role evidence
is private in `access-resolution/signed-in-directory-roles.json`.

The protected JSON had duplicated/missing string quotes; only those delimiters
were corrected, preserving credential values. Missing known SMTP host/username,
native inbox method and observed identity/permission references were filled.
The optional organization ID remains unnecessary for this project credential.
Application-user IDs and native VPN application IDs are runtime-derived bindings,
not additional user inputs. No operational acceptance follows from these local
checks. The final spending/cleanup request remains a separate decision.

The existing destination-access validator requires operator and evidence
read/revoke/restore, with fresh sessions and an actual 403 after removal. The
user selected one temporary restricted Entra user because inherited Owner
authority would make that denial impossible for the administrator. It receives
only the campaign workspace query grant; the administrator retains VPN/export/
cleanup duties. The duplicate planned evidence query grant was removed so the
foundation grant is its sole read authority. This is a focused preparation
correction, not a rerun of a closed campaign. Seven distinct new offline tests
cover the selected access boundaries; all passed.
