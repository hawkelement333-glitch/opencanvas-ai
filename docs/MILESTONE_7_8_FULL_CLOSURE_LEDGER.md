# Milestone 7.8 finite closure ledger

Current result, 2026-11-19 UTC: **Milestone 7.8 remains incomplete.**
PostgreSQL, M78-D-001 and M78-D-002 remain closed with their acceptance,
failed-attempt history, finalized ledgers and verified cleanup preserved.

The [approved private staging execution](MILESTONE_7_8_PRIVATE_STAGING_PACKAGE.md#approved-staging-execution)
accepted the exact API liveness row, gateway acknowledgment and fresh worker
poll for the corrected image. It added 32 validated API/worker readiness rows,
all five native retention settings, and native configuration for all 13
workbooks. Core remained held after the 900-second scanner deadline with no
admitted repair. The checkpoint records the specific remaining proof and
terminal verification of all 48 cleanup counters. The corrected API evidence
is scoped to private staging. Production release acceptance remains open.

The [signup recovery execution](MILESTONE_7_8_REGIONAL_REPLACEMENT.md#signup-recovery-execution-result) accepted both synthetic signups after private API readiness.
The first core upload did not establish clean promotion within its unchanged
scan deadline. Core and destination acceptance remain unproved, and all 48
cleanup counters are verified zero. The reusable controller is preserved.

The [bootstrap successor execution](MILESTONE_7_8_REGIONAL_REPLACEMENT.md#bootstrap-successor-execution-result) credits exact normal bootstrap and migration, deployment
of both signed image digests, private operator routing and native creation of
both corrected alert rules. Signup timed out with an unknown write outcome. Core
and destination readiness missed the gate. All 48 cleanup counters are verified zero. The reusable
controller is preserved.
Billing is **unsettled**. The
[earlier alert-repair result](MILESTONE_7_8_REGIONAL_REPLACEMENT.md#alert-repair-execution-result)
retains its native alert admission and bootstrap failure.

The local preparation records below preserve their historical boundary. The
[original reconciliation](MILESTONE_7_8_REMAINING_EVIDENCE_RECONCILIATION.md)
retains historical receipt credit. The [full-closure package](MILESTONE_7_8_FULL_CLOSURE_EXECUTION_PACKAGE.md)
and later approved regional packages do not authorize an automatic successor.

## Selected decisions and local release update

See the [editable release checkpoint](MILESTONE_7_8_EDITABLE_AI_RELEASE_CHECKPOINT.md).
Explicit save creates an editable derivative while generation and original
response/citation/Trace evidence remain unchanged. Admission6/lock concurrency13
and final-topology Firewall/VM not-applicable are selected. The local release
key fingerprint/key-only policy is explicitly trusted. New0030 append-only
artifact identities and0029-to-0030 migration are locally validated; historical
0028-to-0029 proof remains credited. No managed requirement is accepted merely
from these local checks. Provider credentials, owner-confirmed entitlement, the
selected temporary VPN/DNS route and existing cleanup authority are now bound
privately. The selected restricted Entra test user preserves the query-revocation
assertion; a duplicate planned evidence query grant was removed. Scoped native
identity/permission reads and seven new offline access checks supported the
earlier +2/+10/+12 preparation. See [access execution](MILESTONE_7_8_OPERATOR_ACCESS_EXECUTION.md).
The approved private staging run used its separately recorded deadlines.

## Existing criteria and disposition

| Existing criterion and source | Evidence credited | Local implementation / validation now | Exact managed observation or decision still required |
|---|---|---|---|
| PostgreSQL five checks; [plan exact audit](MILESTONE_7_IMPLEMENTATION_PLAN.md#exact-audit) | PG-E01/E02/E03, TI-E01, PG-E04: 38 assertions; 14 zero cleanup counters | Closed; no rerun | None. Current-release role deltas are checked only on the new candidate/restore, not a reopened PG campaign. |
| D001 upload, scanner, promotion, exact-version deletion/recovery; [defect register](MILESTONE_7_8_DEFECT_REGISTER.md#evidence-debts-routed-to-later-audit-surfaces) | 24 assertions; 19 zero counters; six initial upload assertions retained | Closed; no rerun | None. New combined application traffic observes actual current integration; it does not recreate D001. The one-proof timing amendment is not a global application-default change. |
| D002 independent shared limits and recovery; same register | 17 assertions; 18 zero counters | Closed; no rerun | None. Application backpressure under mixed traffic is a different D006 observation. |
| D003 actual required logs/metrics/traces; [plan](MILESTONE_7_IMPLEMENTATION_PLAN.md#exact-audit), [signal catalog](observability/signals-v1.json), [destination contract](OBSERVABILITY_ARCHITECTURE.md#destination-evidence) | 7.5 local privacy/cardinality/exporter checks and D001 scanner native rows. Private staging accepted the exact API liveness trace, gateway acknowledgment, fresh worker control and 32 validated API/worker readiness rows. | All 53 catalog metric producer sites mapped: measured pool/lock/timeout/transaction, storage/scanner, queue outcomes, index coverage/freshness/drift/conflicts, limiter health/saturation/bypass, provider usage-based cost, exporter health/bounds, optional API admission, integrity and native backup/forecast observations. API-to-worker links use actual operations. Unknown or truncated evidence is not healthy zero. | Full required signal coverage, including actual outbox rows and API-to-worker operation linkage, with source and run bindings. One native backup record was observed. Forecast failed for insufficient provider cost history. Provider emission and remaining alert evidence are unproved. |
| D003 all 13 dashboards; [catalog](observability/dashboards-v1.json) | All 13 deployed configurations matched. The November 19 operator opened all 13 workbooks and recorded 14 visible charts across 27 panels. | Native expected/observed query validators and deployed screenshot/review binding | The other 13 panels returned no results. Their current-release signal and expected outcome still need evidence. |
| D003 all 16 alert firing/recovery; [catalog](observability/alerts-v1.json) | Two corrected native rule configurations. The [November 24 alert history](#november-24-alert-history) also credits native firing for 12 rules and native resolution for three. | Compiled thresholds, timing and window validators | Each remaining stimulus, evaluated source window, matching delivery and recovery needs its own receipt. Integrity requires authorized investigation and native manual closure. |
| D003 destination privacy/source rejection, outage, access and retention; [deployment](DEPLOYMENT.md#operational-telemetry-deployment) | Existing redaction and bounded exporter tests, prior gateway adapter checks, private VPN DNS/TLS, and restricted-user sign-in. Five native table retention settings and the 30-day purge flag were accepted. | Native rejection/absence, bounded drop/readiness/recovery, fresh-session revoke/restore and exact five-table retention validators | Actual 401/422/422 and destination absence, measured gateway outage and recovery, denied API/worker reads, operator revoke/regrant with fresh sessions. The staged transport probe is unproved. Long-term physical expiry requires its own observation. |
| D004 actual worker polling and telemetry; [plan final scenarios](MILESTONE_7_IMPLEMENTATION_PLAN.md#required-final-scenarios) | 7.4 claim/lease/retry tests; accepted PG and D001 effects | Production operation instrumentation; observation failure cannot turn a committed job success into a retry | Actual separately deployed worker claim/process/publication and destination observations for authenticated upload. |
| D004 multi-service delivery with durable ACK/dedup/retry/fencing; same plan | Existing activity-v1 outbox and claim/fence/retry; no new business integration | Separate HTTP activity-v1 receiver and production dispatcher, receipt/effect commit before HMAC ACK, independent receipt readback, final-claim recovery. Fourteen distinct local transport tests cover duplicate, lost ACK, actual TLS disconnect, bounded retry, terminal failure and stale claims. | Actual independent Container Apps processes over private HTTPS, same PostgreSQL durable receipt, 14 unused production events and all nine managed operation receipts plus post-fault recovery, standalone polling/drain and cleanup. User selected this boundary. No criterion located requires a third-party provider or independent datastore; this does not claim either. |
| Application password-reset external delivery/token contract; [local gap record](MILESTONE_7_8_LOCAL_GAP_COMPLETION.md) | Existing reset/token tests | Actual application-to-local SMTP/inbox integration plus separate native-inbox validator; Message-ID/Date binding; single-use, revoked old sessions/password, new password and expiry | Approved SMTP sender/recipient and actual received MIME/native inbox reference for two distinct requests, one unchanged 30-minute expiry. SMTP submission alone is insufficient. |
| D005 R1 creation identity/migration/replay; [four affected assertions](MILESTONE_7_8_HISTORICAL_EVIDENCE_RECOVERY.md) | Historical 7.6 managed recovery and PG replay; 14 formerly skipped local tests | Seeded real PostgreSQL 0028→0029 guarded migration preserves old graph rows, creates no fabricated historical creation keys, fences new identities. Restored snapshot/replay compares complete scoped row hashes, not one identity table. | Current candidate managed restore at 0030, immutable identity mutation denial and idempotent creation replay with no state/evidence changes. Existing 0028 compatibility remains explicit local evidence, not relabeled managed restoration. |
| D005 R2 fresh restored roles and scope; same recovery mapping | Original managed PG roles/tenant isolation | Two-account real application scope denial and exact ownership/positive-negative privilege validator; worker only gains two existing-table INSERT grants for receiver effects/attempts | Fresh API and worker identity sessions on exact restored server, current privileges plus denial of actual other-user canvas/file access. Original-target roles alone are insufficient. |
| D005 R3 nonterminal reconstruction/fencing/resumption; same recovery mapping | PG failover and D001 exact deletion ambiguity/rollback | Exact captured lease rejection, provider success/DB rollback, absence reconciliation, one deletion transition and actual restored-worker outcome; original rollback reconciliation prepared | Actual ordered managed fixture→quiescence→restore→fence→resume→original rollback; no duplicate durable effect; source kept and all writers bounded/stopped. |
| D005 R4 joint state and rollback/RPO/RTO; [recovery runbook](PRODUCTION_RECOVERY_RUNBOOK.md) | Historical 7.6 recovery; D001 exact object bytes/version and provenance | Full scoped DB/object/scanner/event/outbox/activity/index hash comparison; real stale/canceled publication rejection and file checksum/scope checks. Native/probe chain reconciler preserves exact operation/receipt bindings | Native PITR request/terminal server, exact restore point and acknowledged write marker, restored roles/serving, rollback to reconciled original; measure interval/RTO without inventing an RPO objective or zero-loss guarantee. |
| D006 all workload dimensions and stress/spike/failure recovery; [architecture 15.1–15.2](MILESTONE_7_ARCHITECTURE.md#151-workload-model) | 7.7 health soak, PG peak31/p95 592.26ms/failover45.05s, D001/D002 component failures | Four synthetic accounts, 11 workspaces, 21 canvases, 45 documents/9,176,064 bytes; 24 stages/6,262 reserved HTTP requests; ramp/spike, real scoped 130-second row-lock pressure, actual operation effects, bounded failure/recovery and persistent global reservations | Actual profile/data sizes, application-wide admission/rejection and saturation bound, each still-uncovered failure combination and post-failure recovery with operational correlations. A budget cap without observed saturation is a lower tested envelope, not a supported maximum or safe cohort. Admission6 per replica and13 only in lock stages are selected configurations to validate; unchanged catalog thresholds remain. |
| D006 immutable minimal images, inventory and critical/high gate; [architecture 15.3](MILESTONE_7_ARCHITECTURE.md#153-infrastructure-security) | Old retained image acceptance remains closed | Revised API and frontend artifacts built only after source corrections; zero critical/high findings, nonroot/read-only/network-none checks, exact OCI graph and independent inventory. Frontend Alpine failure retained; pinned security-corrected runtime passes. | **Exact managed deployment accepted.** Native API and frontend resource readbacks match the verified API5/web3 digests in the private environment. Application behavior and performance remain separate open requirements. |
| D006 trusted signed provenance; same architecture | Verified unsigned BuildKit provenance and inventories; historical 74 dependency alerts mapped/corrected | Current API5/web3 provenance, release bindings and combined endorsement signed and verified, including tamper rejection under explicitly trusted key-only policy | Local key-only release endorsements and exact native deployment of both signed indexes are accepted. Authenticated CI or transparency-log assurance remains outside that signed evidence. |
| D006 remaining security controls; same architecture | Existing scoped role/network/secret/bounds designs and retained focused tests | Narrow receiver secret/role bindings, private ingress, runtime frontend endpoint configuration; focused outgoing checks | Private environment ingress and operator routing are credited. Deployed egress/identity behavior, full secret access and privileged-access expiry/logging, protected restore, and remaining license/control dispositions are open. No blanket repository audit or automatic new security campaign. |
| D007 configured infrastructure categories/retention; [debt row](MILESTONE_7_8_DEFECT_REGISTER.md#evidence-debts-routed-to-later-audit-surfaces) | Historical private metrics and D001 scanner rows. The staging run observed both registry categories, Blob read/write, Key Vault AuditEvent, and three VPN gateway categories. | Existing PostgreSQL/Blob/registry/Key Vault diagnostic bindings reused | PostgreSQL log and Blob delete rows remain unproved. Preserve the native retention and category bindings. Historical Firewall/VM category evidence remains unlocated/unproved. User explicitly classified those categories not applicable to the final ACA topology; private networking, egress and deployed-resource category evidence remain mandatory. |
| Two original real-stack editable-AI scenarios; [local browser boundary](MILESTONE_7_8_LOCAL_GAP_COMPLETION.md#local-browser-environment-and-contract-boundary) | Actual graph/upload/controlled-draft local flows; unchanged regressions credited | Runtime public API endpoint binding removes frontend build-time-hostname dependency; 12 affected web tests/types/production build and native container smoke | User selected explicit save/edit/reload with immutable original evidence; affected local browser/API tests now pass. Native provider/browser observations on the signed selected release remain required; historical failures are retained. |
| Final results, limits and milestone exit; [plan exit](MILESTONE_7_IMPLEMENTATION_PLAN.md#documentation-commit-and-exit) | Prior accepted results and historical warnings/failures retained | This finite ledger and exact local receipts | Consolidate accepted managed observations, cleanup, limits, RPO/RTO, control dispositions and completion document only after preceding evidence/decisions. No Milestone8 start. |
| D008 billing disclosure; defect register | Current cumulative ceiling $460.40 and posting limitations | Private staging forecast $40.8177 and replacement execution ceiling $56.51 | None as an added technical exit requirement. Billing remains unsettled; the forecast and ceilings are separate from actual charges. |

## Release bindings

Current selected API5/frontend web3 and verified detached endorsements are in
the [signed local release checkpoint](MILESTONE_7_8_EDITABLE_AI_RELEASE_CHECKPOINT.md#selected-local-release).
Both were rebuilt for the explicit editable-artifact source changes. The
following API4/frontend records are **superseded history**, retained unchanged;
they are not the proposed deployment digests.


API index `sha256:70507729749dd0afbff32da505decad340c44cb205420d620d937e08fbd80b7b`,
runtime manifest `sha256:9224bb0db6e5b77ef83d192ab112e87082f1efe2ca557b7edf7906d5b4326a98`,
canonical input SHA-256 `dfd98e955bac2226e6d6a932124ee886fe2c7d58601ae9e0d6b7d9da18f68a1f`,
source tree `d8612aa3fbabbe4085ad9a04b3f27a4859ea36c6`.
Private `full-closure-local/api4/release-binding.json` SHA-256
`9d6b31ee7c767315498ffee170379fb9e8f373f0a4b6083190482bd55160d051`.
44 Python/87 Debian packages, 20 OCI blobs/14 layers independently reconciled.
The first full-closure API candidate is retained under `api-image/`; the later
measured exporter emission correction changed build inputs and required `api2/`.
A failed long Windows extraction path was corrected before that second build;
its partial archive/intent history remains under `api-image-exporter-corrected/`.
The remaining catalog producers and measured provider token cost then changed
API inputs and produced `api3/`. The focused review then proved that a receiver
waiting on a row lock could validate an expired claim using a pre-lock timestamp.
Fresh post-lock and pre-commit expiry checks now fence that race; five real local
PostgreSQL cases passed. The final `api4/` binds this correction. All superseded
candidates remain retained and are not offered for deployment.

Frontend index `sha256:5e56a9df246cfd5de75b8d13c5a3afb93b63c277d39f4da0389d8e377fbb993b`,
runtime manifest `sha256:e52039a690a6df77bc01bfda9c92f962339c5c5c20ada180b16979a6d9d3d516`,
canonical input SHA-256 `e52903523ac74f6d3215338f072b15a33c71820f36b021a71e1a3d2ca7cb4dfa`,
source tree `e9eda465ad71395c9f6e2b71076d9697062e9175`.
Private `full-closure-local/frontend-image/corrected/release-binding.json` SHA-256
`ffe541dba617bf141fa28d51da9c7818f92c8c216c1e9213009cdef74ad442f4`.
22 Node/79 Debian packages, 18 OCI blobs/12 layers reconciled. Initial Alpine
candidate's eight HIGH findings remain a failed attempt, not accepted evidence.

Paths above are under `.runtime/milestone_7_8/`, outside Git. Both artifacts are
unsigned. Source trees are isolated snapshots based on `e495cff19c46cc71fd34ee096f1f628105c4e2e9`;
canonical input verification binds the eventual commit without claiming that
commit was the builder's input or rebuilding for documentation/probe changes.

## Local results and evidence classification

Private receipts are under `.runtime/milestone_7_8/full-closure-local/`.
Telemetry: the initial 19 focused passes are retained. Catalog completion has
31 affected passing cases and all 53 required metric producers mapped; the
provider-cost slice adds five focused passes. Overlapping reruns are not added
together. Strict typing/Ruff passed; observer failure after a committed job has
a separate passing regression. Native managed observation is still required.
Delivery: 14 distinct transport cases and one password-reset integration,
with overlapping incremental receipts **not summed** into fictitious test counts.
Recovery: real local PostgreSQL seeded0028 compatibility, actual two-user scope
denial and stale-publication rejection; chain/normalizer tests remain local.
Destination/capacity validators use explicitly labeled local fixtures; they
cannot supply managed source, alert, saturation or recovery acceptance.
Frontend: 12 affected cases, type check, production build and exact artifact smoke.
All test data are synthetic. No raw inbox, account, provider, row or runtime
payload belongs in Git. Final local receipt hashes are recorded in the package.

## Finite alert identity inventory

The rows below give the catalog windows. Individual managed transitions are
credited in the dated history. Full scenario acceptance also requires its
stimulus, evaluated windows and delivery evidence.

- `api-latency-v1`: mobius.api.duration; 5 minute window.
- `readiness-v1`: readiness; 5 minute window.
- `database-saturation-v1`: mobius.database.pool.acquire; 5 minute window.
- `storage-outage-v1`: mobius.storage.failures; 5 minute window.
- `scanner-outage-v1`: mobius.scanner.unavailable; 5 minute window.
- `queue-backlog-v1`: mobius.queue.oldest_age; 5 minute window.
- `worker-stale-v1`: worker-heartbeat; 2 minute window.
- `limiter-outage-v1`: mobius.limiter.health; 2 minute window.
- `indexer-freshness-v1`: mobius.indexer.freshness; 15 minute window.
- `provider-degradation-v1`: mobius.provider.calls; 10 minute window.
- `outbox-backlog-v1`: mobius.outbox.oldest_age; 5 minute window.
- `evidence-integrity-v1`: mobius.evidence.integrity; 5 minute window.
- `telemetry-loss-v1`: mobius.telemetry.dropped; 5 minute window.
- `backup-freshness-v1`: mobius.backup.freshness; 1440 minute window.
- `capacity-v1`: mobius.capacity.utilization; 15 minute window.
- `cost-v1`: mobius.cost.estimated; 1440 minute window.

### November 24 alert history

Run `run-f5797e58` yielded 21 native instances across 12 rules. The workspace,
rule identities and creation times match the deployment. Each instance has a
retained Alerts Management history. Times below are UTC on November 24, 2026.

| Rule | Native firing | Native resolution |
|---|---|---|
| `readiness-v1` | 11:57:56 | Open |
| `backup-freshness-v1` | 11:57:41 | Open |
| `outbox-backlog-v1` | 11:59:19 | Open |
| `evidence-integrity-v1` | Ten instances, 11:57:25–12:42:21 | Manual investigation and closure open |
| `database-saturation-v1` | 11:55:35 | 12:51:33 |
| `queue-backlog-v1` | 11:57:48 | 12:48:50 |
| `worker-stale-v1` | 11:56:10 | 12:42:13 |
| `cost-v1`, `scanner-outage-v1`, `limiter-outage-v1`, `storage-outage-v1`, `telemetry-loss-v1` | One instance each | Open for all five |

The ten integrity evaluations ended at five-minute intervals from 11:56:49 to
12:41:49. In each native context, `timeAggregation=Count` and `metricValue=1`
refer to one row emitted by the final `where Firing`. The deployed query takes
the maximum `mobius.evidence.integrity` value in each five-minute bucket. A
positive maximum or absent signal rows can set the firing state. An earlier
breach can keep it set across later buckets. The retained contexts omit
`V`, `Presence`, `Missing` and the underlying rows. **All ten windows have
insufficient retained evidence to attribute the firing.** The three resolution
times above come from explicit `Fired` to `Resolved` history events. Landing
the cleanup or triggering an action group supplies no recovery credit.

The consolidated deployment captures release- and workspace-bound integrity
rows with signal IDs, values, event and ingestion times, plus native evaluation
cutoffs before teardown. Late, failed or truncated observations keep their
actual status. Settled billing and production release controls remain separate.
The private reconciliation receipt has SHA-256
`c4a8414b2d525403c94b058bb8f685cc5f25257a176420f96f375f89f26dbb53`.

## Final local checkpoint additions

The managed probe now preserves actual production telemetry context across
recovery, capacity and outbox fault operations, requires acknowledged export
before its success receipt, and identifies these as operational probes rather
than ordinary API/worker traffic. Nine focused context/real-lease cases passed.
The actual row-lock sampler exports only native pending-lock wait values;
its real PostgreSQL blocked-write/rollback test passed.

The source transport initially exceeded the unchanged 240,000-byte inline
limit. Lossless solid ZIP_LZMA preserves every source entry and all hash/path/
expansion checks; six focused transport/admission tests and an exact candidate
runtime decode passed. Failed preparation receipts remain private history.
No source binding was removed and no size limit was increased.

Useful receipt anchors under the private root:

- `telemetry/catalog-completion-receipt.json`: `4cae29a12900164397fff795f1fed031bbfe46def7a4c07cdb483c6b3c0f53a7`.
- `telemetry/operational-probe-context-receipt.json`: `702bbb2b14f2c384c70fb6218c3e55220b12cf085cd3fcca358d3d3cea1822e4`.
- `telemetry/transport/receipt.json`: `585c53c4762e7b70d04c7b69e1efd05579f92ec90fba63bda58e89c4925d328b`.
- `package/capacity-final/capacity-preparation.json`: `c5e564ddd6a5debcb4807b7c9ae1a35ff2085c48b7de492f6551de6b887cec3f`.

Owned local PostgreSQL containers were removed with verified zero residue.
No managed cleanup is claimed for a campaign that has not been provisioned.

- `delivery/intervention-final-summary.json`: `b7ceef8a20a94b77a74f702591eb703e370ffab746897a70bd0bd2b54c8d03c9`; exact existing-job template restoration, scoped grants and measured transport faults remain subject to native acceptance.
