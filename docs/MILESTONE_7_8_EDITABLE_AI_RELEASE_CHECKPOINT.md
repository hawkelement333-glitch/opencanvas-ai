# Milestone 7.8 editable artifact and signed local release checkpoint

November16,2026 CST. Authorized local implementation and release preparation
complete; **Milestone7.8 remains incomplete and managed execution is not
approved**. PostgreSQL, D001 and D002 remain closed. No Azure provisioning,
registry publication, paid provider request, test email or deployment occurred.
Billing remains **unsettled**. Historical failures and private evidence remain.

## Explicit product contract

The user selected **Save as editable canvas artifact**. Generation persists a
read-only response, citation evidence and Trace without changing the canvas.
The new explicit save creates one editable derivative, generated-from edges,
append-only original-evidence identity and canvas revision in one transaction.
Authorization binds the authenticated owner, workspace, canvas and completed
controlled execution. Duplicate saves return the current artifact, preserve
edits and original position, and cannot recreate a deleted artifact.

The node displays editable content separately from original text, original
validated citations and Trace. An edited label compares current text to the
original. Reload restores the saved node and provenance; it does not introduce
unsaved-draft history or panel hydration. Source deletion removes actionable
citation links according to existing policy while retaining immutable execution
citation snapshots, original response and Trace. Original citations never
claim to ground subsequent user edits.

The API is
`POST /api/v1/workspaces/{workspaceId}/agent-executions/{executionId}/artifact`,
body `canvasId` and `position`, returning the node with `draftProvenance`.
It does not accept client-supplied evidence. New append-only table
`controlled_draft_artifacts`, revision`20261116_0030`, has API SELECT/INSERT only
and no worker privileges. It preserves a tombstone after node deletion.
Historical0028/0029 migrations are untouched. Actual0029-to-0030 preservation,
concurrency and SQL append-only guards passed locally; managed fresh-role
validation remains required on the selected candidate.

This explicitly reconciles [README](../README.md),
[grounded answer architecture](ARCHITECTURE.md#grounded-answer-flow), the
historical [Milestone4 read-only result](MILESTONE_4_COMPLETION.md#later-explicit-save-contract-decision-milestone-78)
and the two original real-stack scenarios. Automatic generation-to-node behavior
is not required for the authenticated controlled flow; editing/saving/reloading
is retained through explicit materialization. Legacy deterministic demo behavior
is unchanged. Historical browser failures are not deleted or relabeled.

## Focused evidence

| Requirement | Fresh local evidence | Status/limit |
|---|---|---|
| Authorization, duplicate saves, atomic persistence, edits/reload, provenance, deletion |5 API tests including actual PostgreSQL four-way concurrent save, one node/mapping/edge/revision, injected rollback,0029-to-0030 preservation and SQL mutation denial | Confirmed locally; mock model is not managed provider acceptance. |
| Save UI, immutable evidence display, retry/error state, concurrent local edits |26 distinct frontend unit cases; TypeScript and scoped ESLint passed | Confirmed locally. |
| Existing graph persistence; retrieval/citation/refusal/deletion; explicit save/edit/reload |3 affected actual browser/API/worker/PostgreSQL scenarios passed across retained receipts | Local scanner/model fixtures; not native scanner/provider acceptance. |
| Current0030 recovery, historical0028-to-0029 compatibility, evidence rejection |36 distinct affected recovery-validator cases; exact original requests/responses, live and immutable citation snapshots, artifact identities and Trace hashes included | Validator/local evidence only; native restore/reconciliation remains unproved. |
| Managed save-probe expected versus actual API shape |4 actual local API probe cases, rejecting altered original text, missing citations or incorrect refusal state before editing | Local probe contract;7 extra core HTTP requests consume the existing1,800-request partition, no extra model call. |
| Selected window versus historical pilot default |1 focused package test; full closure uses+2ready/+10proof/+12cleanup while old pilot stays+2/+8/+10 | Preparation only, never execution authority. |
| Deployment template | Bicep compilation passed | Existing secure-input linter warning remains at managed_objects.bicep; no new warning or live validation. |

The browser initially exposed pending autosave between controlled prepare/run,
correctly rejected409 by the server. The client now flushes pending saves before
preparing immutable context. Only the affected document scenarios resumed; the
successful canvas result remained credited. A subsequent focused merge review
found that concurrent local additions could be omitted; the save admission now
adds only the returned artifact and generated edges, preserving other edits,
new nodes and removed edges. Seven focused flow cases cover that seam, including
two new cases. Earlier failures and the superseded intermediate frontend image
remain private history.

Private receipts under `.runtime/milestone_7_8/full-closure-prerequisites/`:
`draft-artifacts.xml`, `draft-artifacts-receipt.json`,
`editable-web-final-receipt.json`, `editable-release/browser/affected-browser.json`,
`editable-release/browser/documents-after-flush.json`, `recovery-0030-corrected.xml`,
`recovery-artifact-citations.xml`, `editable-artifact-probe.xml` and
`selected-window.xml`. The original successful browser scenario and resumed
scenarios are individually classified; the original failing report is retained.
Synthetic final browser database exported privately before owned process/container
cleanup. The separate concurrency-test database/container was also removed.

## Selected local release

Both API and frontend canonical inputs changed, so both were rebuilt after
their applicable corrections and focused checks. API preparation first hit a
Windows path-length limit before any image build; the shorter retained api5
layout resolved it. The intermediate web2 image predates the final merge fix
and is superseded. API4, prior corrected frontend and all older evidence remain
retained; no unaffected image was rebuilt for docs or control-plane changes.

| Binding | API5 | Frontend web3 |
|---|---|---|
| OCI index | `sha256:9ec275f46b587fde50aaf7e04f4ed93f30edac4efd45da9452790e5be91f1d12` | `sha256:1ee742b604d406ad8cc4c3c53001853ad58a033b68f4d613251ea7fc088fdb3a` |
| Runtime manifest | `sha256:f4fa88ce4c280e4e64d393df88decc09d876780935c2df4dcbb9a2c5567dce4e` | `sha256:7bdfb9a1407b5509f74cc6df37c32973f99f24021bf4037043557dccd7e53f00` |
| Canonical inputs | `b25925706b5daa0eca178c45f1bb1b1f9eaa2fd246b85736ff8d45dfbcb4eb98` | `ae50f0375d0fefb6364f292b3de0ffb251247f8ac9027fa44d69ef397bbf8051` |
| Source tree | `dd3f882613d8843724320dae1ac0c98d80433054` | `479b7f467b7a93fe6067fde2e9bd5d03a7877e13` |
| Archive SHA-256 | `3fdefc7bb0fadd255fd3b931bff9ed9f901f41bd19872ac62210f5f9c68163e3` | `df9b1d24ec0f67b2386be50eca12902d47c8cd2fc621e40e9514849531435ede` |

Both runtime checks used non-root, read-only, network-none containers. Exact
OCI graphs, inventories, SBOM bindings and source/migration copies were verified.
API inventory44 Python/87 Debian; frontend22 Node/79 Debian. Both current scans
have **zero Critical/High findings**. No registry publication occurred.

## Trusted local endorsement

Cosign3.1.4 binary hash verified against the exact approved release asset.
The encrypted local key uses the interactive passphrase; no passphrase was
placed in chat, arguments, logs or Git. User-trusted public-key SHA-256:
`856f48ad36a3f8787619c96b857cbad0e7583e768f76ec4ff653092f572ec789`.
Five detached signatures verified: both original BuildKit provenance files,
both original release-binding files, and the combined endorsement manifest.
That manifest binds exact OCI indices/runtime manifests, source inputs, image
archives, inventories, SBOMs and scan hashes. A modified-content negative was
rejected; the final combined signature was independently verified again.

This is trusted endorsement of locally built artifacts and their existing
provenance, **not authenticated CI build provenance**. Key-only verification
explicitly lacks transparency-log assurance. Original provenance is unchanged.
The inspected architecture15.3 requires signed build provenance/inventory and
minimal signed images; it does not explicitly mandate CI identity, certificate
issuer, transparency logging or a SLSA level. Exact digest-bound detached
endorsement satisfies this local release-signing portion under the user-selected
policy; native deployment/digest and remaining security controls stay open.

Private endorsement SHA-256 `c6c0dc03728c4b27b67ebcfee0a271cfa89ccdbf20addb82f89c4237c82771f9`;
signature receipt SHA-256 `2b86333370f01a396eb1fdda8bd45f0fd441349ddbda2afe5c3a65568d210370`.
Key, public key and bundles remain under the protected private `signing/`
directory. Local release-binding JSON retains its original unsigned-at-creation
status; detached verification is recorded separately without altering signed bytes.

## Selected package and remaining inputs

Admission6 per API replica,13 only in lock-pressure stages; aggregate10,000 HTTP,
200 model attempts and160M embedding tokens remain unchanged. Firewall/VM
categories are explicitly not applicable to the proposed ACA topology;
historical missing evidence remains unproved. Deployed-resource diagnostics,
private networking and egress still require actual observations.

The user selected **+2h ready/+10h proof stop/+12h verified cleanup** for
preparation. Restore gets2hours, export1hour and25minutes contingency, with
all catalog acceptance windows intact. Forecast **$31.1034**, proposed new
ceiling **$50**, proposed cumulative ceiling **$400.89 only if separately
approved**. Prior approved$350.89 remains unsettled spending history, not a
fresh allowance. The [window/access proposal](MILESTONE_7_8_WINDOW_ACCESS_PROPOSAL.md)
contains exact quantities, permissions and an unselected optional VPN/private-DNS
route (+$5.5389, total$36.6423). No access resource is silently included.

Remaining user-only inputs: project credential/entitlement; existing SMTP TLS
account/permitted sender/approved native inbox; Entra operator object ID and
existing private browser/export route/DNS; exact cleanup executor and
subscription-entitled purge/readback executor. Known tenant/subscription/models/
TLS/vault values are reused. Exact-vault operation scope does not imply that an
RG-level role can grant the required regional deleted-vault actions.

The private candidate package is assembled under
`full-closure-prerequisites/editable-release/package/` after the source checkpoint.
It binds the selected artifacts/signatures/source, selected schedule and fixed
capacity/index suballocations, but remains `approved:false` and non-executable
until unavailable secure access/provider inputs are bound. Child index and
capacity approval templates share one proposed spending/cleanup decision and
fixed partitions; they are not independent spending allowances. Absolute UTC
deadlines derive only from that later approval. No request for an incomplete
spending approval, deployment or next-area execution follows this checkpoint.
