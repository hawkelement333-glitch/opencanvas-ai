# Milestone 7.8 remaining evidence reconciliation

Date: 2026-11-16. Reviewed source checkpoint:
`224fbf852dd8fbb7a6f23cd5b3dc19a0e53bf0a2` on
`milestone-7-8-production-readiness-audit-local`.

**Milestone 7.8 remains incomplete. PostgreSQL, M78-D-001 and M78-D-002
remain complete and closed, including their verified cleanup.** This record
narrows the remaining existing requirements; it does not reopen completed
checkpoints, add acceptance criteria, or authorize execution or deployment.
Only repository documents, retained artifacts and Git differences were read.
No tests, image builds, scanner runs, Azure queries or paid operations were run.

## Evidence classification and scope

- **Direct:** native retained artifact contents inspected in this reconciliation.
  Reading source or a test definition establishes its contract, not a new pass.
- **Historical:** a completed result reported by an inspected handoff or ledger;
  its original execution artifact was not independently inspected here.
  Historical acceptance is preserved.
- **Unlocated:** the relevant original artifact was not found in scoped repository
  evidence locations or the owning document did not identify its retained path.
  This means coverage cannot yet be mapped; it does not mean the exercise failed
  or must be repeated. Framework examples and blocked preflights are not results.

Line references below identify the criterion at the reviewed source checkpoint;
linked headings remain the navigation target when document edits shift lines.
The original nine-stage 7.7 terminal chain and the signed 7.6 report were not
located in scoped `.runtime`, `.tmp`, `evidence` and referenced validation
locations. No wider filesystem search or cloud retrieval was performed.

## Requirement-by-requirement disposition

| Requirement and exact existing criterion | Completed evidence already satisfying all or part | Specific assertion or evidence mapping still missing | Closure class and justification for any further execution |
| --- | --- | --- | --- |
| **D003: destination observability and privacy.** [Plan, Exact audit / Required final scenarios](MILESTONE_7_IMPLEMENTATION_PLAN.md#exact-audit), lines 1132–1133, 1163: logs, metrics, distributed traces, objectives, alerts, evidence integrity, privacy, dashboards and runbooks; no secret/private content in telemetry. [Deployment](DEPLOYMENT.md#operational-telemetry-deployment) lines 305–309 and [observability architecture](OBSERVABILITY_ARCHITECTURE.md#destination-evidence) lines 215–221 require exact-release authentication/TLS, every dashboard and alert, outage/backpressure, retention and revocation. | **Historical:** [7.5 handoff](MILESTONE_7_5_OBSERVABILITY_HANDOFF.md), lines 123–189: 74 core and 30 focused passes, including redaction, bounded cardinality, query/alert and outage behavior. **Direct:** observability service, tests and dashboard/alert catalogs have no Git difference from checkpoint `acca302`; D001 native results prove real Log Analytics scanner-result delivery. | Destination-bound application logs/metrics/spans and privacy observations; successful dashboard queries, alert delivery and recovery, bounded exporter outage/loss/readiness, configured retention, export-only versus operator-read access and revocation. Scanner-result rows alone do not establish these assertions. | **Documentation/local mapping first; targeted managed observations for genuinely uncovered destination behavior.** No unchanged local observability suite rerun is justified. The evidence limitation is that local HTTP/in-memory tests and scanner ingestion do not observe the required operational destination contract. Share telemetry observations with D004/D007. |
| **D007: infrastructure category-log delivery.** [Defect register](MILESTONE_7_8_DEFECT_REGISTER.md#evidence-debts-routed-to-later-audit-surfaces), original row 916; [recovery runbook](PRODUCTION_RECOVERY_RUNBOOK.md), lines 180–189: Stage 3 category-log rows absent before cleanup. | **Historical:** [7.6 handoff](MILESTONE_7_6_BACKUP_RESTORE_DISASTER_RECOVERY_HANDOFF.md), lines 154–164, records private metrics for compute, PostgreSQL, Key Vault and Firewall. **Direct:** later D001 `StorageMalwareScanningResults` records reached Log Analytics and matched native blob-tag decisions. | Usable records/queries for the configured infrastructure diagnostic categories (including the Stage 3 Firewall/PostgreSQL/Blob/registry/Key Vault/VM category evidence) and their retention. Later malware-scanner records are a different table/category. | **Documentation credit now; targeted managed observation only for still-unproved category delivery**, preferably alongside D003. Do not rerun Stage 3 recovery to obtain logs or describe all live logs as absent. |
| **D004: durable worker/provider path.** [Plan, Exact audit](MILESTONE_7_IMPLEMENTATION_PLAN.md#exact-audit), lines 1129–1130; [Required final scenarios](MILESTONE_7_IMPLEMENTATION_PLAN.md#required-final-scenarios), lines 1152, 1154–1160: leases, duplicate delivery, bounded retry, poison/dead-letter, replay, shutdown, revocation, stale suppression and atomic effects. Existing debt specifically names production wake-up, telemetry and external multi-service delivery. | **Historical:** [7.4 handoff](MILESTONE_7_4_DURABLE_QUEUES_SHARED_LIMITS_HANDOFF.md), lines 140–181: 19 focused passes and PostgreSQL claim/append-only proof; pre-expiry ledger: 63 durable-work/event/limiter/governance passes. **Direct:** PG failover/replay and D001 concurrent deletion, transaction rollback and replay are accepted. `durable_jobs.py`, `domain_events.py` and `scripts/worker.py` are unchanged from the 7.6 checkpoint. | A recorded production worker polling/wake-up observation with operational telemetry and an actual external delivery/acknowledgment path satisfying the existing fencing/retry/no-duplicate-effect contract. No provider receipt for that complete path was located. Source definitions alone do not prove it. | **Local artifact mapping first; targeted managed provider observation only if still absent.** The worker is a database-polling loop; no new broker is required. Later `services/jobs.py` changes add object-deletion execution and bounded database-disconnect recovery, already partly covered by D001/PG. Reuse those successes; do not repeat the durable-work suite or component failover. |
| **D005: consistent recovery and rollback.** [Plan](MILESTONE_7_IMPLEMENTATION_PLAN.md#exact-audit), lines 1134–1135 and 1161: backup/PITR/object recovery, index/queue/outbox reconstruction, rollback/DR and RPO/RTO; [recovery runbook](PRODUCTION_RECOVERY_RUNBOOK.md), lines 105–124, 139–177, 218–224. | **Historical accepted:** [7.6 handoff](MILESTONE_7_6_BACKUP_RESTORE_DISASTER_RECOVERY_HANDOFF.md), lines 81–127, 173–183: all Stage 3 results 14–24 passed, including managed PITR/full restore, portable recovery/failback and cleanup. RTO upper bounds 1,412/779/1,009/511 seconds; PITR marker exclusion interval 54.707716 seconds. **Direct:** PG failover 45.047397 seconds; D001 exact-version retention/recovery, original ETag/bytes, preserved scan/promotion bindings and continued API denial. | Current-release compatibility of **joint** database/object/index/queue/outbox recovery and rollback. Original signed report and per-result 14–24 receipts are unlocated, so their exact current coverage cannot be reconstructed from result numbers. Failover is not PITR; object-version recovery is not whole-system rollback. | **Local retrieval/compatibility mapping first; conditional affected managed proof.** Relative to the 7.6/7.7 recovery boundary, migration 0029, database ownership/roles/runtime, worker recovery/deletion and session-specific upload-event identities changed. Only a still-uncovered affected recovery path warrants execution. No production deployment or repeat of all Stage 3 exercises is required. |
| **D006: supported capacity and failure-under-load.** [Plan](MILESTONE_7_IMPLEMENTATION_PLAN.md#exact-audit), lines 1136–1137, 1164; [architecture sections 15.1–15.2](MILESTONE_7_ARCHITECTURE.md#151-workload-model), lines 1025–1060: tested workload limits, stress/soak/spike, bounded rejection and dependency recovery. | **Historical accepted:** [7.8 entry handoff](MILESTONE_7_8_ARCHITECTURE_SCOPE_AUDIT_HANDOFF.md), lines 29–35: nine validated 7.7 stages, 91 samples, 5,400 uninterrupted seconds and zero residue. **Direct:** PG peak connections 31, p95 592.259108 ms, failover 45.047397 s; D001 failure-closed object/transaction recovery; D002 independent-replica atomic limits, 429, dependency 503/no effect, degraded health/no fallback and restored decisions. | Supported application-wide workload/concurrency/data-volume ceilings; observed saturation or bounded rejection, latency/errors and recovery for stress/spike/mixed application load and the remaining required failure combinations. Locate original workload receipts before declaring particular scenarios unexecuted. | **Documentation of measured scopes now; artifact mapping before conditional managed work.** The 7.7 terminal soak schema measures readiness/DNS/TLS/bindings/cleanup/cost health, not throughput/percentiles/saturation. Inert performance/resilience examples are not live results. Subsequent application/database/jobs/object/dependency/topology changes limit transfer of old whole-system claims; no change justifies repeating the accepted health soak or PG/object/Redis assertions. |
| **D006: current image build and critical/high container/dependency scan.** [Architecture section 15.3](MILESTONE_7_ARCHITECTURE.md#153-infrastructure-security), lines 1064–1070; [final validation](MILESTONE_7_IMPLEMENTATION_PLAN.md#final-validation), lines 1168–1172. | **Direct, satisfied for the retained image:** `o1/build-receipt.json`, `scout.sarif.json`, image metadata: immutable image `f498e5aa…`, Scout 1.23.1, **0 critical / 0 high**, non-root composition under network-none/read-only conditions. Canonical image-input paths have no Git difference from retained source tree `2e4bccfe…` to the reviewed HEAD. | **None for this bounded build/scan assertion.** This is not a claim of zero findings at every severity or every infrastructure control. | **Documentation-only closure of this subcriterion.** Reuse the image and its retained scan. No image rebuild or unchanged scan rerun is warranted. |
| **D006: remaining security evidence inventory.** [Architecture section 15.3](MILESTONE_7_ARCHITECTURE.md#153-infrastructure-security), lines 1064–1076; plan lines 972–974: signed build provenance, image/dependency inventory, secret/license/configuration/privilege/egress/backup/runtime controls and scans. | **Direct:** immutable digests, source labels, dependency bindings and the current critical/high image scan; completed campaigns contribute private networking, least privilege, identity, bounded recovery and verified cleanup evidence. Historical infrastructure contracts and security reviews remain credited. | A located current-release mapping for the remaining named controls; specifically, no current-image cryptographic build-provenance signature or separate SBOM/signature-verification receipt was located. A hash or OCI source label alone is not signed provenance. Unlocated controls are not declared failed. | **Artifact retrieval and local validation/generation where actually missing.** Do not add a blanket cloud security campaign. A live observation is warranted only if an existing topology control remains unsupported after mapping. No image-byte change is implied by missing provenance metadata. |
| **Indexer and unchanged local application/frontend regressions.** [Plan](MILESTONE_7_IMPLEMENTATION_PLAN.md#exact-audit), lines 1127–1128, 1138–1139, 1153–1160: deterministic manifests/revisions/drift, fenced publication/provenance, authority and atomic effects; affected frontend/build validation. | **Historical:** [pre-expiry ledger](MILESTONE_7_8_PRE_EXPIRY_MAXIMUM_SAFE_PROGRESS_HANDOFF.md#exact-validation-ledger): Indexer/graph 24 passes; agent/workflow 317; collaboration/authority/Trace/idempotency 79; document/AI 33; web 75 tests, lint/type/format clean, nine-page build and eight mocked browser passes. No `apps/web` production changes since `7a99d297…`; unchanged successes remain valid. | No new whole-area assertion is inferred from these headings. The Indexer and agent/workflow PostgreSQL skips require identity/result mapping in the next row; two real browser workflows are separately unproved below. Later backend changes require only affected coverage mapping. | **Documentation reuse**, with bounded local evidence mapping below. No unchanged frontend build, Indexer suite or full Milestone 4–6 rerun is justified merely by an open summary. |
| **Skipped PostgreSQL fixtures and migration/final coverage.** [Plan, Final validation](MILESTONE_7_IMPLEMENTATION_PLAN.md#final-validation), lines 1168–1174. | **Historical:** pre-expiry ledger records 14 PostgreSQL fixture skips across five shards and otherwise passing results. **Direct:** completed PG 38 assertions and D001/D002 results cover many later provider contracts; a later source-review JUnit records 428 passes, no failures/errors/skips. Authorized migration 0029 supersedes the old assertion that it must be absent. | Exact test identities and dispositions for the aggregate historical fixture skips, and their mapping to later accepted results. The ledger does not identify all skipped node IDs; therefore it cannot support an invented list of 14 new managed gaps. Consolidate affected coverage for later role/runtime/jobs/workflow/object/migration changes. | **Local evidence reconciliation first; only uncovered affected assertions need local validation.** Raw historical skip receipts were not located. PG acceptance must not be rerun just to replace an aggregate skip count. The 428-test receipt is not assumed to cover every later production correction. |
| **Two real-stack browser scenarios.** [Plan](MILESTONE_7_IMPLEMENTATION_PLAN.md#final-validation), lines 1138–1139, 1168; [canvas test](../apps/web/e2e/canvas-workflow.real.spec.ts), lines 4–6, and [document test](../apps/web/e2e/document-workflow.real.spec.ts), lines 7–9. | **Historical:** eight mocked browser passes and unchanged frontend checks. **Direct source inspection:** the two tests are opt-in via `E2E_REAL_API`; retained aggregate ledger records both skipped. PG and object component proofs remain accepted. | A pass for “persists a connected graph and an editable AI response across reloads”; a pass for “uploads, retrieves, cites, navigates, and refuses unsupported claims,” including citation removal on deletion. No accepted real-stack browser result was located. | **Local real-stack validation**, scoped to these scenarios and their required fixtures. The limitation is prior explicit skipping/mocked API coverage, not a frontend code change. These tests alone would not certify a deployed website. No paid campaign is inherently required to resolve this local gap. |
| **Completion and Milestone 8 entry record.** [Plan](MILESTONE_7_IMPLEMENTATION_PLAN.md#documentation-commit-and-exit), lines 1178–1186; [architecture entry criteria](MILESTONE_7_ARCHITECTURE.md), lines 1374–1399. | Closed campaigns, historical checkpoints, focused correction receipts and this reconciliation supply parts of the final record. Their failed attempts remain history. | Consolidated exact results/skips/warnings, supported limits, RPO/RTO, migration and protected-Git evidence, remaining-control dispositions and `MILESTONE_7_COMPLETION.md` after the preceding requirements are supported and no unresolved critical/high readiness defect remains. | **Documentation after evidence closure.** An open completion heading is not a new execution requirement. No completion declaration, deployment or Milestone 8 start is authorized by this record. User-authorized normal pushes supersede historical local-only/no-upstream wording. |
| **D008: cost evidence disclosure.** [Defect register](MILESTONE_7_8_DEFECT_REGISTER.md#evidence-debts-routed-to-later-audit-surfaces), original row 917. | Prior cost-query limits and campaign ceilings are retained. This record preserves the disclosed distinction between forecasts/ceilings and posted charges. | Exact settled charges remain unavailable; **billing is unsettled**. This is a disclosed limitation, not an additional technical milestone exit test. | **Documentation-only disclosure satisfied.** Cumulative approved ceiling **$350.89 USD** is not settled spending or a new allowance. No billing query or execution is needed for this reconciliation. |

## Direct evidence bindings

Raw receipts remain private and outside Git. These are retained relative paths
and hashes, not copies of the raw payloads:

- PostgreSQL: `.runtime/milestone_7_8/p-eight/ca/final-results.json`,
  SHA-256 `e6105b6c03850ee01c09870bb8a1d68b59ccc9107f26f2e30802c3f858a35677`;
  terminal receipt `83a74d83b77751760156f2db968e98c719b23d081fdced9142e3e93ec4bb302d`.
  All five checks / 38 assertions accepted; all 14 cleanup counters zero.
- Objects: `.runtime/milestone_7_8/objects-continuation-20261116/final-results.json`,
  SHA-256 `f9a178ba95ee1d3a5a5e33370da6c93eaf4bada371f96954979d4ce23c1ab72e`;
  terminal receipt `b04b1d5abeeb78203a03059840b184d6d32cd069ca351b47671c91fc875f0b31`.
  All 24 assertions accepted; all 19 cleanup counters zero. Scanner execution
  `caj-m78o-1c96397e49-probe-r8gokki` matched native blob tags and Log Analytics
  under the separately approved one-proof 900-second/20-second amendment.
  The application default 300-second policy was not globally changed.
- Redis: `.runtime/milestone_7_8/redis-regional-20261116/final-results.json`,
  SHA-256 `fffa9b4269cd19d7694f729697b4652e36e83191cc9c68b22254a18c02f06238`;
  terminal receipt `ee626147e4f7a93eabf17b19e66e9ddcd815307cd1dd5fbb7ed0ca886fbd0b1f`.
  All 17 assertions accepted; all 18 cleanup counters zero. See the
  [regional campaign execution ledger](MILESTONE_7_8_MANAGED_REDIS_REGIONAL_PACKAGE.md#managed-campaign-reconciliation).
- Image: `.runtime/milestone_7_8/o1/build-receipt.json`, SHA-256
  `fc8f7938ceb21c13fc13ffffb13af4681ce83a534e86104a3c1dd9c78b996a43`;
  `o1/scout.sarif.json`, SHA-256
  `69933e606e8fc010c7d1df52993f413523163ac7ca1c3247fc26bdbc6c946878`.
  Image `sha256:f498e5aa0f5e44dc7becc92868e1bb989372ef09a3f30d694e89d172eaa66b0a`;
  canonical input hash `d94e350754821b1172a9b4452466391053e0221d3095e336e43379f6f33c312f`;
  retained source tree `2e4bccfe5e28df3e03775917dbc5b4ddc5f05c2f`.
- Local JUnit: `.runtime/milestone_7_8/source-review-4fc0c05/validation.xml`,
  SHA-256 `7c69749cf3dd68206b2ccdc344ece74577e7fb56b5ef8f3f6679f5d93dafea60`;
  428 tests, zero failures/errors/skips, dated 2026-11-13.

The 7.6 handoff reports signed report hash
`976b0b7e611f59c488e76ba04d054ddf8696f3910db22778318bd5439a0997b1`.
That is a **historical reported hash**, not a report inspected directly here.
Its result numbers must not be treated as a reconstructed per-assertion ledger.

## Invite-only pilot decision boundary

This is a conditional risk assessment from the existing criteria, **not a
deployment-readiness declaration or a pilot scope amendment**. Assume a small,
explicitly bounded cohort of authenticated invited users, synthetic/disposable
non-sensitive data, no customer/regulated/critical data, no public SLA or
durability promise, and named operator supervision. No safe user count or
throughput ceiling is inferred from the component measurements.

For an enabled website pilot, the unresolved destination privacy/access,
health/alert and operational evidence is a blocker to a supported readiness
claim. Real-stack canvas persistence and enabled document/AI browser behavior
also lack the recorded passes identified above. Current-release evidence for
the actual enabled configuration and remaining security controls must be
mapped; an unlocated artifact is an unresolved decision input, not proof of
an implementation vulnerability. Retaining valuable user data would additionally
require supported consistent restore/rollback and recovery expectations.

Explicit, **server-enforced and verified** restrictions could remove document
upload/retrieval/AI, index publication, workflow/agent execution and external
delivery from a pilot's enabled functionality. Hiding UI controls is insufficient.
No complete restriction set is implemented or validated by this reconciliation.
Synthetic disposable data can narrow recovery promises; low concurrency and
bounded admission can narrow scale claims. Neither makes an untested configured
limit safe by assertion, nor closes full-milestone recovery/capacity criteria.

The current production configuration itself requires Azure object storage,
database workers, Entra-backed Redis, real AI providers, authenticated HTTPS
telemetry and release/migration checks
(`apps/api/opencanvas_api/core/config.py`, lines 630–765). Index publication
has an explicit disabled mode. Feature restrictions must respect those startup
contracts; switching to demo mode or disabling required telemetry/Redis is not
an evidenced production-pilot alternative. D001's one-proof timing amendment
does not automatically authorize a changed scanner policy for a website pilot.

Full 7.8 completion still requires the unresolved assertions or evidence
mappings in the table, including disabled-for-pilot features. Locate the original
artifacts and complete documentation/local mappings first. Only then can a
specific uncovered managed observation justify a bounded execution proposal.
No next area, deployment, paid campaign or test run starts from this document.
