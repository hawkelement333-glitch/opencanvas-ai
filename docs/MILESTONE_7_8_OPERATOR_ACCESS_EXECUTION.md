# Selected temporary operator access: execution and cleanup

Preparation only. The user selected this option; spending, tenant writes, client
configuration and deployment still require the final package approval. It
extends the existing full-closure package, not the completed PostgreSQL/D001/D002
campaigns. Signed API5/frontend web3 bytes and the key-only policy are unchanged.

## Bound scope and timing

East US target `rg-m78-a712b8c940-target`; VNet `vnet-m78o-a712b8c940`,
`10.79.0.0/16`. Existing three subnets are retained. Optional subnets are declared
in the foundation on every stage, avoiding their removal on a later redeploy:
`GatewaySubnet` = `10.79.9.0/27`, `operator-dns` = `10.79.9.32/28`, delegated only
to DNS Resolver. Static resolver address `10.79.9.36`; P2S pool
`172.31.240.0/24`. Both network ranges passed the captured workstation overlap
check; repeat that read-only check at execution admission if routes changed.

| Addition | Exact binding |
|---|---|
| VPN | `vpngw-m78p-a712b8c940`, VpnGw1AZ, Generation1, OpenVPN/AAD, route-based, no BGP, no active-active option |
| Public IP | `pip-m78p-a712b8c940-vpn`, Standard static IPv4, zones 1/2/3; VPN endpoint only |
| DNS | `dnsr-m78p-a712b8c940`, inbound endpoint `operator-inbound`; no outbound resolver/ruleset |
| Tenant audience | `m78p-a712b8c940-operator-vpn`, single tenant, dedicated app/service principal, assignment required, exactly one approved user/app-role assignment |
| Client | Installed Microsoft Azure VPN Client on the current workstation; one campaign profile, split route only to `10.79.0.0/16` |
| Export | Administrator gets Storage Blob Data Reader only on this campaign's `operational-evidence` container |
| Revocation user | One temporary unlicensed Entra member, `m78-a712b8c940-reader` in the bound verified initial tenant domain; one workspace Log Analytics Reader grant, no admin roles |

Microsoft's registered VPN client ID is reused, but a dedicated audience binds
operator access without changing a shared enterprise application. No client
secret or new tenant admin role is created. Current read-only evidence shows
the existing executor has subscription Owner and Global Administrator. These
are existing entitlements, not new grants. The user separately selected a
temporary restricted query user for the existing revocation assertion; the
administrator cannot satisfy its denial while retaining subscription Owner. Direct-user assignment avoids a new
group or licensing assumption. The final approval must explicitly include the
application, service principal, assignment, temporary query user and their
delete/purge operations. No licence purchase or assignment is authorized.

Services, core evidence and private access must be ready by +2 hours. Gateway
provisioning begins with the composed foundation once its VNet/workspace exist;
client import and interactive Entra sign-in occur within the same gate. There
is no promise that provisioning will finish in time. A missed gate stops new
proof and starts cleanup. Proof stops and scheduled cleanup begins at +10;
verified cleanup must finish by +12. Export completes before access removal.
No deadline is derived from preparation; all use the later actual approval time.

## Exact prepared operations

The private final package contains `access/plan.json`, one JSON body per Graph
request, the compiled ARM template, credentials in a separate secure parameter
file, and the inherited operator/probe commands. No command below is authority.
All stdout/stderr/native responses go to protected evidence, never chat or Git.

1. Admit the final source/package/signature hashes, fixed budgets and new
   approval-relative deadlines. Renew only the reusable controller's existing
   deadline/tags; preserve identity, Reader grant and bootstrap history. Arm
   and verify its exact +10 schedule and target-group binding before any paid
   workload. The controller deletes the Azure group; the confirmed operator
   performs the separately bound tenant/client/credential cleanup.
2. Create only the prepared temporary member using Graph `POST /v1.0/users`
   and the private `create-query-user.json` body. Its UPN uses the verified
   initial tenant domain, a generated private password requires change at
   first sign-in, and existing MFA/Conditional Access remains enforced. Native
   readback must match the exact UPN, return no assigned licences/admin roles,
   and bind its object ID. Use that ID for `operatorPrincipalId`; use the
   existing administrator for `operatorExportPrincipalId` and VPN assignment.
   Reconcile an uncertain create by the exact UPN before retrying.
3. Create the audience with `az rest --method POST --url
   https://graph.microsoft.com/v1.0/applications --body @access/create-audience.json`.
   Record the exclusive operation intent and native response. Before any retry,
   reconcile the exact display name AND campaign tags; zero matches permits
   resumption, one match must match the body, multiple matches stop admission.
   Bind the returned application object ID and appId, never an existing app.
4. Materialize the prepared `expose-audience` request from those exact IDs and
   PATCH only that application's `identifierUris` to its `api://<native-appId>`.
   POST `create-service-principal` with that appId and assignment required.
   POST `assign-only-operator` to that exact principal's `appRoleAssignedTo`.
   Bodies, URLs and the fixed principal/scope/app-role GUIDs are in the package.
   Each write requires an intent and native reconciliation before retry.
5. Read the exact app, service principal and complete assignment list. Reject
   a continuation page until followed, unexpected user/group, wrong audience,
   tenant-wide audience, changed scopes or disabled assignment enforcement.
   Run `operator_access_package.validate_audience` on these native JSON files.
   Bind only its accepted appId to `operatorVpnAudienceAppId`; set
   `enableOperatorAccess=true` in every foundation/jobs/application parameter set.
6. Use the existing staged `az deployment group create` commands with the
   compiled `pilot.bicep`, exact target group and private `@parameters` files.
   Secret values are never command arguments. Only the native audience ID and
   approval-derived tags/times may replace their named placeholders.
7. After gateway success, use `az network vnet-gateway vpn-client generate
   --resource-group rg-m78-a712b8c940-target --name vpngw-m78p-a712b8c940
   --processor-architecture Amd64` to obtain the
   native download reference. Preserve it privately, download only the generated
   VPN profile, and reconcile the downloaded profile against this gateway.
   Profile generation does not grant access. Use the native Entra/OpenVPN XML;
   reject a certificate-only profile rather than substituting authentication.
8. Run `configure_client_profile` with the accepted tenant/appId, native gateway
   FQDN and exact service suffixes. It preserves the server trust configuration,
   pins the Microsoft client application ID, adds `10.79.9.36`, and permits only
   the campaign VNet route. Include the native ACA environment domain plus the
   Blob, ACR, Monitor/OMS/ODS/agent, PostgreSQL, Redis, Key Vault and Event Hubs
   service suffixes bound by this deployment. Import the resulting XML using
   Azure VPN Client's Import action; authenticate interactively as the approved
   user. Do not put tokens/passwords in arguments or output.
9. Retain native connected-session evidence, `Get-NetRoute`,
   `Get-DnsClientNrptPolicy -Effective`, DNS results for exact application/query/
   export hosts, and TLS/browser/query/export results. NRPT is required because
   Azure VPN Client DNS settings need not appear in `ipconfig`. Every application,
   query and storage endpoint must resolve through the private route; the VPN
   endpoint is the only new public endpoint. Public service access stays disabled.
   Capture an authenticated private workbook render and hash-verified Blob
   export. Native runtime URLs still pass the existing six-resource admission.

The installed CLI command is prepared without an authentication-method override;
the gateway is configured for AAD/OpenVPN. Inspect the native generated profile
before import. If it does not match that configuration, stop access admission;
do not substitute certificate/password authentication or retry unchanged proof.

## Preserve the existing access-revocation assertion

`destination_acceptance.validate_access` still requires fresh sessions and
200/403/200 for both operator and evidence roles, with the same exact assignment
removed/restored. The restricted human query user supplies the operator role;
the administrator keeps the tunnel connected and may perform workbook review,
export and authorized integrity investigation. No admin role is revoked.
The user signs into a separate browser/CLI profile for each fresh query session;
never replace the administrator's CLI configuration or reuse an old bearer token.

Read complete direct/transitive/inherited assignments for the new user and
validate its sole workspace query grant before proof. Unexpected inherited
access is a stop condition, not authority to remove unrelated roles. The evidence
identity reuses its single foundation Log Analytics Reader grant; the duplicate
observability-module grant has been removed. Bind both assignment IDs from
native reads, capture original bodies, and restore those same scoped assignments.
The existing worker scanner-table grant is unchanged and must not grant access
to application/security telemetry. Each native query result is still unproved
until observed; local configuration does not imply successful revocation.

## Diagnostics and local evidence

The gateway enables GatewayDiagnosticLog, TunnelDiagnosticLog,
RouteDiagnosticLog, IKEDiagnosticLog and P2SDiagnosticLog plus AllMetrics in the
existing private workspace. Prove actual OpenVPN connection/disconnection with
native session and P2S evidence; configured unused protocol categories do not
become fabricated events. Logs remain inside the existing 1GiB campaign bound.
DNS Resolver metrics do not support diagnostic-settings export: retain exact
ARM metric GETs for InboundEndpointCount and QPS/QPSMdm plus actual client DNS
results. No unsupported resolver log category or new monitoring service is added.

Seven distinct new offline tests passed: exact-user audience, rejection of extra scope and
multi-tenant access, route overlap, preserved native profile trust with private
DNS/split routing, rejection of wrong identity/gateway/entities, and complete
zero-counter cleanup, and rejection of duplicate/inherited query authority. These are preparation evidence, not managed connectivity.
Composed Bicep compilation passed with only the retained managed-object
secret-input warning. No unchanged suite, image build or provider call ran.

## Cleanup and stop conditions

At proof stop, export first if still within its bounded phase, disable the exact
campaign service principal (`accountEnabled=false`), disconnect the campaign VPN
profile, and let the armed controller delete the isolated Azure group. On an
uncertain delete, reconcile the existing job/resource before direct fallback.
Never delete the reusable controller or pre-existing Owner/tenant assignments.

Disable the temporary query user after its observations, then delete and purge
only its recorded native ID; preserve unrelated users and all tenant admin roles.
Remove only the recorded campaign VPN user assignment, service principal and app.
Use exact returned object IDs for Graph DELETE operations; read live objects
and `directory/deletedItems/<id>`, purge only those campaign deleted objects
where present, then verify native absence. Do not search/delete by display name
alone. Remove only the campaign VPN client profile and its introduced NRPT/route
entries, preserving the preflight snapshot and unrelated profiles. Revoke the
specifically named temporary Gmail app password after message evidence export;
the account owner records that action without displaying the password.

In addition to existing campaign cleanup counters, require observed zero for
all 19 access counters defined by `ACCESS_COUNTERS`: gateway, public IP,
resolver, inbound endpoint, two subnets, diagnostic setting, container reader
grant, tenant user assignment, live/deleted service principal and application,
client profile, introduced routes and introduced NRPT entries, live/deleted
restricted query user and its dedicated browser/authentication profile. The temporary
Gmail app-password disposition is separately verified. Missing observations
remain unproved; parent absence may support child absence only with the exact
resource relationship retained. Named-vault purge/readback is unchanged and
uses the existing entitled account within +12. Complete cleanup evidence is
required before campaign ledger finalization.

Stop for unknown write outcome, unexpected resource/principal, unsafe routes,
public fallback, missing native evidence, inability to meet +2 readiness,
forecast/allowance exhaustion, or +10 proof deadline. Preserve successful
assertions and partial evidence; no silent retry allowance or time extension.

Forecast remains **$36.6423**, including **$5.5389** access cost for 12 hours.
Proposed incremental ceiling **$50**; cumulative **$400.89 only if approved**.
Estimates and ceilings are not actual charges; billing remains unsettled.

References: [custom VPN audience](https://learn.microsoft.com/en-us/azure/vpn-gateway/point-to-site-entra-register-custom-app),
[user assignment](https://learn.microsoft.com/en-us/azure/vpn-gateway/point-to-site-entra-users-access),
[client DNS and NRPT](https://learn.microsoft.com/en-us/azure/vpn-gateway/azure-vpn-client-optional-configurations),
[gateway log categories](https://learn.microsoft.com/en-us/azure/azure-monitor/reference/supported-logs/microsoft-network-virtualnetworkgateways-logs),
[resolver metrics](https://learn.microsoft.com/en-us/azure/azure-monitor/reference/supported-metrics/microsoft-network-dnsresolvers-metrics).
