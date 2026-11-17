# Core-feature Mobius pilot preparation

Prepared 2026-11-16 CST from `5a6e6b5f3a043ff539caf7a1dbddb3fccf899f37` on
`milestone-7-8-production-readiness-audit-local`. PostgreSQL, M78-D-001 and
M78-D-002 stay accepted and closed. **Milestone 7.8 remains incomplete; this is
a local preparation checkpoint, not deployment readiness or managed acceptance.**

## Explicit pilot contract

The user selected the existing **read-only controlled draft**. Editable,
persisted AI canvas nodes are outside this pilot contract. The two historical
legacy browser scenarios remain failed/incomplete for their original editable
AI expectations; their full-7.8 acceptance conflict has not been erased.

The user approved pilot-only scan settings of **900 seconds total / 20 seconds
retry cap**. The overlay and deployed parameter composition use those values;
unrelated defaults remain 300/300. Upload capability expiry remains 300 seconds.
Objects stay quarantined until both native sources agree on exact object/version;
late results and expired capabilities remain rejected. The prior 300-second
campaign failures remain historical failures, not newly accepted evidence.

The pilot keeps authenticated canvas editing, secure upload, extraction,
private-clean retrieval, citation navigation and grounded AI. Assumptions are
invited authenticated users, non-sensitive evaluation data and operator
supervision. No safe cohort size, public SLA, residency exception for user data
or durability guarantee follows from the local fixtures.

## Completed local changes and evidence

| Surface | Correction / accepted local result |
|---|---|
| Secure website path | Runtime discovery selects secure upload sessions, client SHA-256, scoped capability PUT and exact completion/status. One persistent card is created idempotently. Reload fetches authorized security state; capability bytes are not retained in UI state. Uncertain writes receive one read reconciliation, not blind replay. |
| Pending and timeout UI | Distinguishes quarantine, accepted clean scan awaiting extraction, server timeout, overdue/unavailable decision and upload expiry. Only server-accepted clean plus ready extraction permits use. Card and bulk deletion preserve “Deletion requested” until server-confirmed deletion; preview/use remains blocked. |
| Production worker integration | Only an authorized promoted current object gets durable work. Private-clean index publication and lease completion share the transaction. Completion binds exact revision/publication; a lost lease rolls back publication. Revoked upload authority cannot create work. |
| Native PostgreSQL correction | The real browser found missing explicit retrieval-head timestamps: SQLite defaults had hidden the migrated-schema NOT NULL failure. Publication now binds creation/update timestamps to its actual publication time. The first candidate remains superseded history; this two-line API input change justified the replacement build. |
| Destination adapter | The explicit Azure Logs mode validates existing signal/source/privacy contracts and accepts only native DCR 204. Private managed identity, verified TLS, bounded timeout and stable deduplication IDs replace receipt-only acknowledgment for the proposed destination. Receipt-only history is preserved. |
| API validation | Eleven focused integration checks passed, including timeout, revoked authority and lost-lease rollback. After the timestamp correction, the two affected publication/lease cases passed again. Strict typing passed for the five changed API modules; destination adapter/gateway checks passed separately. |
| Browser / frontend | The existing current-contract journey in secure-pilot mode passed on actual FastAPI, PostgreSQL 17/schema 0029 and the database worker: quarantine reload, PDF extraction/publication, exact citation navigation, grounded answer/refusal and deletion fencing. **1 passed**, 24.6-second scenario / 28.8-second run. Local deterministic scanner/AI/embedding fixtures are explicitly not managed-native/provider acceptance. **21 affected UI tests**, TypeScript and frontend production build passed. |
| Execution inputs | The private composite Bicep compiles; focused infrastructure/privacy/identity/settings-name checks pass. Approval guards reject changed scope/source and expired authority. Probe tests cover scoped restoration comparison, uncertainty without replay, archive traversal/hash rejection and bounded mixed workload. The exact candidate imports both probes and eight pinned SDK wheels with networking disabled. No runtime pip or API rebuild for probe packaging. |

The new image includes the five earlier API corrections and subsequent secure
integration/telemetry/timestamp changes. Corrected frontend dependencies remain
source-bound web inputs. The [release record](MILESTONE_7_8_PILOT_RELEASE_CANDIDATE.md)
binds the current API index, runtime manifest, source snapshot/canonical inputs,
SBOM and scan. **0 Critical / 0 High**; 97 installed API sources, 54 copied
files, 44 Python distributions, 87 Debian packages, 20 OCI blobs and 14 layer
hashes verified. Unsigned BuildKit metadata is not trusted signed provenance.
No authorized signer was found in the bounded repository/tool inspection.

## One bounded managed package

Use the [approval package](MILESTONE_7_8_PILOT_MANAGED_VALIDATION_PACKAGE.md) and
its [command sequence](MILESTONE_7_8_PILOT_EXECUTION_COMMANDS.md). The proposed
East US scope is `rg-m78-a712b8c940-target`: private shared dependencies, two API
replicas, worker, gateway, web and sequential manual jobs. It reuses the
preserved controller and verified image. The four specifically uncovered
restore assertions share this isolated environment; historical PG/object/Redis
acceptance and the old health soak are not repeated.

| Cost class | Proposed amount and limits |
|---|---|
| Temporary validation | **$25.5678 forecast; $50 incremental ceiling; $400.89 cumulative ceiling if approved.** Includes ten resource hours, four hours of isolated restored PostgreSQL, private alert transport, logging/scanning and conservative provider bounds. Prior $350.89 is an unsettled historical ceiling, not reusable funding. |
| Recurring hosting | **$490.0444/month active fixed baseline** for 730 hours; hypothetical all-idle arithmetic floor **$365.8714**, not predicted worker behavior. Example usage adds $84.7320, totaling **$574.7764/month**. Neither figure authorizes hosting or proves capacity. |
| Remaining decisions | Trusted signer/policy; private frontend origin and future frontend image build/publication; SMTP sender/approved recipient and receiver evidence; OpenAI credentials/model entitlement; operator/private evidence-export route; exact vault purge permission; separate spending/execution approval. |

The [cost model](MILESTONE_7_8_PILOT_COST_MODEL.md) separates provider usage,
scanner, logs/retention, idle assumptions and optional public-hosting/network
charges. The window is approval-relative: provision by +2h, stop proof/scheduled
cleanup +8h, cleanup authority +10h. There is no future-start waiting period.
Secrets, actual account bindings and raw evidence remain private.

## What managed results would and would not establish

Successful core/native-provider integration, destination privacy/access and
operational recovery, actual alert and enabled SMTP delivery, bounded mixed
workload/rejection recovery, four current restore assertions, trusted artifact
verification and verified cleanup would supply the named evidence for the
defined pilot. The operator must still state the measured supported envelope
and explicit ingress/user/data commitments; no automatic deployment follows.

Full 7.8 additionally retains the historical editable-AI acceptance conflict,
disabled external outbox delivery, uncovered Firewall/VM diagnostic categories,
unproved catalog producers/alerts and any stress/saturation/failure combination
not actually observed. A labelled telemetry fixture, empty query, snapshot hash
or preparation script cannot close those requirements. The absent historical
signed 7.6 report/two 7.7 payloads remain disclosed evidence limitations; no
new broad search or whole recovery rerun was started.

## Private receipts and local cleanup

Private root: `.runtime/milestone_7_8/pilot-rc-20261116/`.

- `api/secure-integrated.xml` and `api/publication-corrected.xml`: accepted
  focused API results; earlier failures remain adjacent.
- `browser/core-final-server-state.json`: accepted secure browser journey.
  Previous timestamp and deletion-state assertion failures remain retained.
- `ui/final-tests.log`, `ui/final-types.log`, `ui/final-build.log`: current UI
  and build results. No web container was built or published.
- `image/`: superseded first candidate and original failures; `image-corrected/`:
  verified current candidate, fresh scan, original unsigned provenance and SBOM.
- `infra/` and `package/`: local compilation, guard/probe/SDK compatibility,
  command/source hashes and preparation inputs. Managed results remain unproved.

The isolated PostgreSQL container, owned API/worker/scanner processes and
listeners on 3000/8000/55432 were removed. Synthetic short-path storage was
archived privately and removed. The generated Next guidance file and build-only
type-path change were excluded from source. No Azure cleanup was necessary or
performed. All five protected stashes and prior images/receipts are preserved.
Billing remains **unsettled**.

Local preparation receipt: `local-preparation-receipt.json`, SHA-256
`ec0fab5d32afb94a4ff135305299d35c4452dcc2436cf758dc0eae925b9f1231`.
The exact SDK/source payload reconstructed to its expected full checksum and
imported in the candidate with networking disabled. The private `prepared/`
bundle contains 44 query files, 13 operation candidates, exact
resource/source/image bindings and an explicit `approved: false` template.
`parameters.partial.json` intentionally omits unsupplied identities, provider
credentials and approval-derived deadlines; it is not deployable as-is.
The cost correction preserves the original one-replica calculation as history.
