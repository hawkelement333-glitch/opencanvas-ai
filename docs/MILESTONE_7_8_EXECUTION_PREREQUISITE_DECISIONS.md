# Milestone 7.8 execution prerequisite decisions

Preparation checkpoint, November 16, 2026 CST. **Not executable; no spending,
publication, deployment or trusted-identity creation authorized.** PostgreSQL,
D001 and D002 remain closed; full 7.8 remains incomplete. This updates the
[execution proposal](MILESTONE_7_8_FULL_CLOSURE_EXECUTION_PACKAGE.md) and
[finite ledger](MILESTONE_7_8_FULL_CLOSURE_LEDGER.md), preserving prior history.

## Decision sheet

| Decision/input | Recommendation | Exact unresolved input and consequence |
|---|---|---|
| Full editable-AI contract | Keep a persisted editable canvas artifact, created by an explicit user save action; preserve the generated response, citations and Trace as immutable evidence. | Choose this product contract before implementation, or explicitly amend full milestone acceptance to the current read-only panel. The recommended choice requires focused implementation/validation and reevaluation of changed image inputs before signing. |
| Trusted signing | Use a user-approved existing Cosign key to endorse the retained artifacts and their provenance. If none exists, explicitly authorize an encrypted local release key and the key-only verification policy below. | Supply an approved public key/fingerprint and private key location securely, or authorize key creation and later approve its fingerprint. No identity is currently trusted. This is local release endorsement, not authenticated CI build provenance. |
| Provider accounts | Reuse the selected model/embedding and an existing SMTP STARTTLS account. | Fill the protected local input form with the project credential/entitlement, SMTP host/account/permitted sender, approved inbox and native receipt method. No test calls/messages now. |
| Operator/access/cleanup | Reuse an existing operator and private browser/export route, plus an already entitled exact-vault purge executor. | Entra object ID, existing route/DNS/browser details and effective permission evidence are unavailable. Cached login and an ACR public /32 do not prove them. No VM, Firewall, VPN or broad grant is implied. |
| Firewall/VM diagnostics | Apply D007 to resources in the final deployed topology; classify Firewall/VM categories as not applicable to this ACA topology. | Explicit applicability decision required. Preserve the historical missing-category result as unproved; do not relabel it accepted. |
| Admission | Six in-flight API requests per replica; thirteen concurrent requests only in the scoped lock-pressure stages, all others at most eight. | Select this proposed configuration, not a safe user count. Acceptance requires measured overlap, application rejection and recovery; no threshold is guaranteed. |

The separate activity-v1 receiver decision is already resolved. The following
sections make the choices reviewable; none is treated as an approval.

## Editable AI: exact behavior and affected acceptance

[README](../README.md), lines7/34, specifies editable connected AI response
nodes. [Architecture](ARCHITECTURE.md), line120, specifies atomic persistence of
node/response/citations/edges. The original
[canvas real-stack test](../apps/web/e2e/canvas-workflow.real.spec.ts), lines75–81,
edits an AI-node textarea, saves, reloads and expects the exact edited text.
The original [document real-stack test](../apps/web/e2e/document-workflow.real.spec.ts)
requires upload/retrieval/citation navigation/refusal; its AI-node assumptions
also require explicit reconciliation, without dropping those assertions.

The later [Milestone4 contract](MILESTONE_4_COMPLETION.md), lines38–42/63,
instead requires a controlled read-only result without automatically adding a
canvas node. Today authenticated UI selects that panel in
[open-canvas-app.tsx](../apps/web/src/components/open-canvas-app.tsx), lines1811–1828.
The server persists `AIResponse(node_id=None)`, citations, Trace and usage in
[grounded_draft.py](../apps/api/opencanvas_api/services/agents/grounded_draft.py),
lines729–805; duplicate execution can reconstruct the stored result at line827.
Server persistence does **not** imply reload restoration in the UI.

[controlled-draft-panel.tsx](../apps/web/src/components/controlled-draft-panel.tsx),
lines59–93/217–248, keeps displayed state in memory. Reload clears that display;
there is no draft-history hydration, save-to-canvas action, application copy
button or editor. Users can select/copy rendered text with browser controls,
but this has not been proved as an application copy feature. Existing ordinary
canvas nodes still support editing. The retained current browser receipt
`.runtime/milestone_7_8/pilot-rc-20261116/browser/core-final-server-state.json`
(SHA-256 `511fc6c6507b063ff5a60652d0454e092d9f3343a8aab6957ae13d300e13f2c2`)
passed one core scenario; its reload checks concern quarantine/deletion, not
AI-result restoration. Existing server persistence tests are credited unchanged.

Recommended explicit save/materialize preserves the original editable product
intent and the later prohibition on automatic canvas mutation. It needs a
clearly separated editable derivative, server authorization/transaction and
idempotency rules, reload/save/edit verification, and preservation of original
citation/Trace provenance. Affected checks are the two real-stack scenarios
above, [controlled panel tests](../apps/web/src/components/controlled-draft-panel.test.tsx)
and focused API persistence/scope/provenance tests. Keep the existing no-node
assertion before explicit save. No such workflow has been implemented or its
criteria amended in this checkpoint. Choosing read-only instead requires an
explicit full-7.8 amendment that discloses the absent reload/history/save/edit
features; it cannot be inferred from the earlier pilot decision.

## Signing preparation and policy

Current [CI](../.github/workflows/ci.yml) has read-only contents permission and
no signer, `id-token: write`, attestations or approved trust policy. Neither
Cosign nor Notation is installed on the inspected path. No key store was
searched and no identity was created. API4 and corrected frontend are unchanged,
unsigned and unpublished; exact digests, archives, provenance and canonical
input hashes remain in the [release ledger](MILESTONE_7_8_FULL_CLOSURE_LEDGER.md#release-bindings).
A private `release-endorsement.unsigned.json` binds both retained releases.

Proposed identity if a new key is explicitly selected: local release key alias
`opencanvas-m78-release`, encrypted ECDSA P-256 Cosign key, no certificate issuer.
The identity is its user-approved SHA-256 public-key fingerprint, not the alias.
Prefer an existing approved key if available. Permissions: read the exact
artifacts/provenance, use that private key, write private detached bundles. No
Azure role, GitHub write/id-token grant, Key Vault or registry operation is
needed for local signing. Incremental Azure/provider/CI cost is $0. The user
must authorize creating/trusting this key and verified tool installation if
no existing key/tool is supplied. No fingerprint can be invented beforehand.

Pinned tool proposal: [Cosign v3.1.4](https://github.com/sigstore/cosign/releases/tag/v3.1.4),
`cosign-windows-amd64.exe`, SHA-256
`cbe953787074611f1334cbf37dc1cf953995bb8c45398eb4fc7bb781d29c1f2a`.
Release metadata and tagged command documentation are retained privately. After
explicit authorization, download that exact release asset to the protected
preparation directory, verify its hash before execution, and use an approved
existing key or generate the authorized encrypted pair with an interactive
passphrase. Never place a passphrase in arguments or Git.

Proposed key-only policy: sign the exact release-binding/provenance blobs and
endorsement manifest; pin the approved public-key hash outside the signature
bundle; verify each signature and all transitive artifact hashes, and reject a
modified-byte negative case. Use the v3 empty signing-service configuration to
avoid public identity/provenance publication. Proposed commands, only after
key/tool/policy authorization:

```powershell
# Variables are exact private paths; no secret values on the command line.
$config = & $cosign signing-config create
[IO.File]::WriteAllText($emptyServiceConfig, ($config -join "`n"), [Text.UTF8Encoding]::new($false))
& $cosign sign-blob --key $approvedPrivateKey --signing-config $emptyServiceConfig --bundle $bundle $exactBlob
& $cosign verify-blob --key $approvedPublicKey --bundle $bundle --insecure-ignore-tlog $exactBlob
```

`--insecure-ignore-tlog` means explicitly **no transparency-log assurance**;
signature, key pin and content verification remain mandatory. This policy needs
user acceptance. See [tagged sign command](https://github.com/sigstore/cosign/blob/v3.1.4/doc/cosign_sign-blob.md)
and [verify command](https://github.com/sigstore/cosign/blob/v3.1.4/doc/cosign_verify-blob.md).
A trusted person/key endorsing a locally built artifact does not establish an
authenticated CI builder. The retained BuildKit builder identity is empty;
original provenance remains unchanged. If the criterion is interpreted to
require authenticated CI build provenance, an endorsement is insufficient and
that requires a separate workflow/trust decision; do not rewrite local history.
Finalize the chosen AI implementation before signing any changed candidate.

## Secure local input setup

The existing private directory is
`.runtime/milestone_7_8/full-closure-prerequisites/`.
Its Windows ACL disables inherited access and grants only the current Windows
user and SYSTEM. Git ignores it. Open `inputs.private.json` in a local editor;
do not paste credentials into chat, terminal arguments, screenshots or Git.
The form is input staging, not an application-loaded environment file. After
choices/authority are bound, values map into private ARM parameters and exact
Key Vault/application secret references; no plaintext source configuration is
committed. Internal synthetic session/delivery secrets can then be generated
privately without asking the user to invent them.

Direct bounded inspection found named process/User/Machine provider/signing
variables empty, documented `.env`, `apps/api/.env` and `apps/web/.env.local`
absent, and prepared SMTP parameters unset. No broad credential search or live
entitlement/role query occurred. The cached default Azure account matches the
prepared subscription; cached tenant/subscription are already copied to the
private form and are not requested again. Cached login is not proof of an
Entra object ID, current effective role or private network access.

Fill only these unavailable fields:

| Form fields | Required setup / binding |
|---|---|
| `openai.apiKey`, project/organization identifiers if applicable, `entitlementConfirmedByOwner` | Use an existing project credential allowed for `/v1/responses` and `/v1/embeddings`; owner confirms `gpt-5.6-terra` and `text-embedding-3-small` (1536 dimensions). Maps to `OPENAI_API_KEY`; no entitlement call during preparation. Model selection is already resolved. |
| `smtp.host`, `username`, `password`, `fromAddress`, `approvedInbox`, `nativeInboxReceiptMethod` | Existing account supports STARTTLS on port587 and permits this exact sender. Supply an inbox whose actual MIME/native receipt can be exported securely. Maps to the existing `OPENCANVAS_SMTP_*` settings. Implicit TLS465 is not the implemented transport. No email is sent during setup. |
| `operator.entraObjectId`, `privateRoute.*` | Obtain the existing user's Entra object ID from the tenant owner/account record. Identify existing VPN/peered operator host, browser location, private DNS and route evidence. The prepared operator workspace-query role is `73c42c96-874c-492b-b04d-ab87d138a893`; verify actual access after approval. An ACR exact-IP allowance is not this route. |
| `operator.applicationOperatorUserIds` | Bind actual synthetic application operator UUIDs after account creation. These differ from Entra object IDs; no existing production user is invented. |
| `cleanup.executorObjectId`, `purgeExecutorObjectId`, `effectivePermissionEvidenceFile` | Existing entitled executors and a current exact-scope permission record from the owner/admin. Controller Reader/bootstrap history is retained, but a prior expired binding grants no new window. |
| `signer.*`, `decisions.*` | Record the explicit choices above; key material remains in its protected local location. Blank values are unresolved, not defaults or consent. |

Exact vault: `kv-m78p-a712b8c940`, East US, seven-day soft delete, purge
protection disabled in the prepared template. Required purge action is
`Microsoft.KeyVault/locations/deletedVaults/purge/action` on the exact regional
deleted-vault resource under the bound subscription. An RG Contributor grant
does not cover that resource after group deletion. Use an existing entitled
principal; do not automatically create a subscription-wide grant. After separate
cleanup approval the exact operation is:

```powershell
az keyvault purge --name kv-m78p-a712b8c940 --location eastus --subscription $boundSubscription
```

Require native terminal absence of that exact deleted vault plus all other
scoped residue counters. [Key Vault recovery/purge rules](https://learn.microsoft.com/en-us/azure/key-vault/general/key-vault-recovery?tabs=azure-portal)
distinguish soft deletion from purge. If no existing private route or purge
principal exists, report that concrete access decision before spending; this
package does not silently provision one.

## Firewall/VM disposition

Directly inspected retained bounded-search result:
`.runtime/milestone_7_8/local-gap-20261116/historical/findings.json`.
No original signed7.6 report/per-result category artifact was recovered. The
[historical retrieval record](MILESTONE_7_8_HISTORICAL_EVIDENCE_RECOVERY.md),
lines60–89, and [7.6 handoff](MILESTONE_7_6_BACKUP_RESTORE_DISASTER_RECOVERY_HANDOFF.md),
lines155–163, report routing/private metrics but no AzureDiagnostics category
rows before cleanup. The latter is historical reporting, not a newly inspected
accepted category receipt. No specific additional usable artifact is known;
no new open-ended search was performed.

[D007](MILESTONE_7_8_DEFECT_REGISTER.md), line927, records this debt. The final
[pilot topology](../infra/milestone_7_8/pilot.bicep) uses ACA and PostgreSQL,
Blob, registry and Key Vault category bindings; it creates no Firewall or VM.
[Architecture](MILESTONE_7_ARCHITECTURE.md), line1066, requires private networking
and explicit egress controls, not those particular SKUs. Recommended explicit
disposition: retain the historical gap, scope current category acceptance to
actually deployed applicable resources, mark Firewall/VM not applicable to this
topology. Their absence must not waive private-network/egress proof or fabricate
historical acceptance. User decision remains pending.

## Admission and finite workload

[API middleware](../apps/api/opencanvas_api/main.py), lines34–80, counts and
rejects actual in-flight requests when configured. The prepared runtime has
two API replicas, each0.5CPU/1GiB, pool5 and overflow0. Recommend limit6 per
replica: five potential database borrowers and one bounded waiting request,
with earlier application rejection rather than an unbounded pool queue. This is
a test configuration, not a validated throughput/user limit.

The old client cap8 cannot guarantee exceeding aggregate admission12. The new
unselected variant uses13 only for exact scoped row-lock pressure, with16
writes and two recovery writes per wave; all other stages remain at most8,
ramp1/2/4/8 unchanged. Real distribution/overlap still must be observed. Separate
application `api_capacity_exhausted`503 from rate-limit429, infrastructure
throttling, database timeout and transport failure. Keep existing p95 objectives;
no safe cohort or guaranteed saturation is inferred.

Private `admission-proposed/manifest.json` SHA-256:
`cbe5f737d35f4918e03340ce9051b29999b0534da067d3b11da2a29ac78c11c1`.
It binds both the admission-only comparison (same24 operation files) and a
separate timed proposal with48 capacity stages and15 index stages. Distinct
stages carry not-before/hard-stop gates and fixed reservations; repeating a
stage never renews an allowance. Nine distinct130-second lock waves span45
minutes; this does not claim continuous45-minute pressure. Sixteen low-rate
stages span60 recovery minutes. These are proposed future
observations, not repeated unchanged tests or managed acceptance.

Hard HTTP partitions total10,000: capacity7,800, index400, remaining core/access/
recovery1,800. Capacity reserves6,438 operations plus200 authentication calls;
index reserves258 including15 actual reprocess mutations,150 bounded polls and
15 auth requests. No new generation call is added; the existing200 model-attempt
and160M embedding-token ceilings remain. Core102-byte fixture reindex/reprocess
adds at most66,096 conservative embedding tokens, leaving30,602,896 after the
129,331,008-token large-fixture bound, before other query/recovery consumption.
Those activities consume the remaining allowance, never a new budget.

Reindex does not itself emit freshness: production observation runs after a
real document-processing job. Timed descriptors bind
`POST /api/v1/documents/{exactCoreDocumentId}/reprocess` and actual job readiness/
publication receipts. The route lacks an idempotency contract: record intent,
submit once, reconcile uncertain outcomes before any retry. Refresh all three
active core heads before300s throughout recovery; do not assume unchanged
reindex advances a timestamp. New probe-only slots resolve queued/deletion
IDs exclusively from the admitted fixture and reject mismatched scope/duplicate
IDs. Secure operator execution and final source/authority bindings remain
prerequisites; generic route guards were not weakened.

## Timing and cost

A demonstrated control-plane correction changes evaluation from PT1M to PT5M.
Every compiled query uses `union`, which the
[Azure one-minute optimization does not support](https://learn.microsoft.com/en-us/azure/azure-monitor/alerts/alerts-create-log-alert-rule).
The same provider documentation requires three clear evaluation periods for
stateful resolution at five-minute frequency: fifteen additional minutes after
the unchanged catalog recovery condition. Integrity still requires authorized
investigation and manual closure. No KQL native acceptance is claimed locally.

Nominal serial index work is90minutes (15age+30breach+30healthy+15native).
Capacity is105minutes (45breach+45healthy+15native), plus fixture/setup. Provider
alert work needs65minutes; DB/storage40, API/queue35, outbox30, plus ingestion,
evaluation alignment and delivery. Compatible shorter faults/reset30-minute
expiry/dashboard observations must overlap without contaminating required
healthy windows. Daily lookbacks do not themselves require waiting24hours for
a genuine latest native provider observation.

| Hard relative gate proposed | Required state / stop consequence |
|---|---|
| +2h | Foundation, services, core fixtures and destination ready; stronger than merely beginning provisioning by+2h. |
| +3h35 | Core-only index native recovery accepted; no large capacity setup before that. |
| +4h05 / +4h45 | Capacity fixtures ready / other finite capacity phases complete. |
| +5h30 / +6h35 |45-minute pressure observed /60-minute healthy/native recovery collected. |
| +7h30 | Current-release restore, reconciliation and original-target rollback complete. |
| +7h55 | Evidence export and validators complete. |
| +8h / +10h | Stop proof and begin scheduled cleanup / verify cleanup within authority. |

This is nominal fit, **not a confirmed completion guarantee**. It leaves only
55minutes for restoration and25minutes for final export. Native backup/forecast
availability, three healthy scanner decisions in one5-minute window, RBAC
propagation within10minutes, threshold attainment, index refresh/job duration,
manual integrity investigation and native PITR/export latency are unproved and
can exhaust these allocations. Late-start provisioning cannot fit the full
sequence. Missed gates preserve partial evidence and begin cleanup; no window
compression, fabricated result or silent extension. Fully binding the package
must explicitly accept partial-result risk or separately revise scope/window
before any spending. No necessary managed observation is guaranteed by a local
schedule.

Current forecast **$29.3238 USD**, removing the previous unsupported one-minute
alert increment of$0.3288 from$29.6526. All resources retain the conservative
10-hour allocation, existing activity services, helper40-minute overlap and
provider/log/storage bounds. Timed requests stay within those bounds; no new
paid resource is added. Proposed incremental ceiling remains$50 and proposed
cumulative ceiling$400.89 **only if separately approved**. Prior approved
cumulative ceiling$350.89 is not a reusable allowance or actual charges.
Billing remains **unsettled**. No ongoing-hosting estimate or approval is added.

## Focused verification and release consequences

One affected alert-catalog test passed for supported cadence with unchanged
literal windows/manual integrity behavior. Six new retained-document slot tests
passed; Ruff and focused mypy passed for the slot change. Private receipts are
under `full-closure-prerequisites/alert-cadence.*` and
`admission-proposed/focused-check-receipt.json`. Timed operation hashes and
reservations are locally checked. No unchanged suite, image build or provider
operation was repeated. Only control-plane compiler/probe/tests/docs changed;
retained API/frontend canonical build inputs are unaffected.

After decisions and secure inputs: implement only the chosen AI delta, run its
focused checks, rebuild only artifacts whose canonical inputs actually change,
obtain authorized signatures, then freeze source/image/signature/command/input/
private-access/cleanup/timing bindings into one new review package. Keep old
unapproved packages immutable. Present its exact hash and absolute deadlines
for separate spending/cleanup approval. Until then the campaign is not
executable and no full-7.8 closure is claimed.
