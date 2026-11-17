# Milestone 7.8 full-closure validator interfaces

This source-bound local implementation extends the existing pilot package. It
does not authorize provisioning, provider calls, publication or deployment.
PostgreSQL, M78-D-001 and M78-D-002 remain accepted. No managed assertion below
has passed merely because its local validator passes fixture tests.

## Full catalog and unchanged semantics

```powershell
.venv/Scripts/python.exe -m infra.milestone_7_8.pilot_validation prepare `
  --bundle $newPrivateBundle --release $candidateRelease --deployment $deployment `
  --ceiling $separatelyProposedCeiling --full-closure
```

The full-closure flag enables all 16 existing alerts, including outbox backlog,
and binds the destination, capacity, recovery, provider-observer and delivery
implementations. Historical pilot preparation retains its original default of
15 enabled rules. Production queries filter the actual `mobius-api`,
`mobius-worker` and `mobius-outbox` sources; an evidence-tool synthetic metric
cannot populate these dashboard/alert results.

The compiler preserves each catalog's literal lookback, including 1,440-minute
backup/forecast windows. Rolling windows end at evaluation time, so an actual
latest provider observation can be evaluated without manufacturing historical
samples or waiting a whole day. Native evaluation uses a five-minute cadence:
the previous one-minute proposal is unsupported for these `union` queries.
Native stateful resolution requires three clear evaluation periods at this
cadence, adding fifteen minutes after the unchanged catalog recovery condition.
See the [timing decision](MILESTONE_7_8_EXECUTION_PREREQUISITE_DECISIONS.md#timing-and-cost). Outbox terminal failure fires on one
terminal observation; backlog still requires two breached windows.
Evidence-integrity rules disable automatic mitigation. An authorized
investigation and native alert closure are required; the monitor never repairs.

Every compiled rule contains `query` and `observationQuery`. The latter retains
the native aggregate windows and computed `Firing` state. The independent
Python validator checks those states against catalog thresholds, missing-data
behavior, hysteresis, window counts and terminal-failure behavior. Native KQL
validation/evaluation remains necessary; local string generation is not proof
that Azure accepts the expression.

An initial actual absence can exercise a catalog's `missingData=breach` branch,
followed by a genuine fresh provider observation and recovery. Record that
branch explicitly. This does not claim a native over-budget forecast or an aged
backup was observed. Missing forecast support/permission remains unproved,
never a substituted local estimate or zero. Billing remains unsettled.

## Native destination collection and reconciliation

Use the already-authorized source-bound `query`, `telemetry` and `alerts`
entry points after separate execution approval. Each `query` input must be in
the approved query-hash list. Include both compiled alert queries, every panel
query, exact source/trace queries and negative-request absence queries. The
native receiver preserves Event Hub sequence, partition and enqueue timestamps.

```sh
python -m infra.milestone_7_8.pilot_validation query \
  --bundle /tmp/m78-proof/package --authorization /tmp/m78-proof/approval.json \
  --bindings /tmp/m78-proof/bindings.json \
  --runtime-readbacks /tmp/m78-proof/native-resource-readbacks.json \
  --query-file /tmp/m78-proof/approved-query.kql \
  --execution-id "$CONTAINER_APP_JOB_EXECUTION_NAME" \
  --output /tmp/m78-evidence/query.json --execute
```

The offline acceptance entry point performs no network calls:

```powershell
.venv/Scripts/python.exe -m infra.milestone_7_8.destination_acceptance `
  --manifest $nativeEvidenceManifest --plan $exactDestinationPlan --output $newAcceptanceReceipt
```

The manifest schema is `m78-native-destination-evidence-v1`, with exact
`sourceCommit`, `imageDigest`, `release`, `deployment`, `executionIds`, UTC
`startedAt`/`completedAt`, `evidenceClass=managed-native`, and an `artifacts`
map. Every artifact entry contains a private relative `path` and its SHA-256.
Paths cannot escape the evidence directory. A `local-fixture` manifest is
rejected. This classification does not authenticate fabricated files: the
operator must retain native dispatch/response and execution/export bindings.

| Artifact key | Actual required evidence and expected comparison |
|---|---|
| `production-signals` | Native Log Analytics response (`status`, `result.tables[].columns/rows`) containing exact-source application logs/metrics/spans. Compare the plan's required service/kind/name tuples, approved schema/privacy, stable signal IDs and native window. API/worker continuity requires shared trace, direct span link or the same scoped opaque durable link. |
| `gateway-negative-requests`, `rejected-signal-absence` | Actual unauthenticated/wrong-source/private-field HTTP requests with body hashes and 401/422/422, plus exact native absence query returning Count=0. The plan binds their request hashes and destination. |
| `dashboard-<id>-<panel>` | Exact compiled panel query hash and successful native query values; missing samples cannot become healthy zero. |
| `render-<id>`, `workbook-render-review` | PNG from the real deployed workbook, bound workbook resource ID and screenshot hash, authorized operator's visual review that the panels render without errors. A successful query alone is insufficient. |
| `alert-scenarios`, `alert-windows-<id>`, `native-alert-events` | Actual operation/provider stimulus and recovery references, raw native observation-query frames, catalog-bound Fired/Resolved events for the same alert ID and target/window. All 16 rules are required. |
| `integrity-authorized-closure` | Finding hash, approved investigation authority, authorized operator and actual native change/readback showing the exact fired alert Closed. A zero metric is not closure authority. |
| `exporter-outage` | Exact gateway stop/start receipts, before/during/after readiness/operator responses, configured buffer bound, observed bounded drops, restoration and empty buffer. |
| `destination-access` | API/worker/gateway operational-query denials, operator/evidence read → revoked denial → restored read with distinct fresh sessions and identical scoped role-assignment restoration. |
| `retention-readbacks` | Native workspace and five table GET responses proving 30/90/30/14/365-day class retention and matching total retention, plus immediate 30-day purge configuration. Configuration is not a months-long physical expiry observation. |

The collectors do **not** automatically provide authenticated workbook browser
screenshots, operator investigation authority, native role-change/readbacks or
an inbox. Those are explicit operator/private-route collection steps, not
hidden successes or new product services. Actual request/response recording is
required when assembling the named artifacts; do not fill them with summaries
invented from expected behavior. The reconciler emits accepted/failed/unproved
per assertion and never closes the area without cleanup reconciliation.

## Actual provider and integrity observations

The `provider-observation` operation invokes the production
`scripts.operational_observer.observe` function with byte-bound native inputs.
The plan must list exact `providerObservationResourceIds` and
`providerObservationRequests`; no subscription discovery or arbitrary provider
operation is admitted. The observer only validates/emits retained readbacks;
the collection commands are separately scoped execution operations.

```sh
python -m infra.milestone_7_8.pilot_validation provider-observation \
  --bundle /tmp/m78-proof/package --authorization /tmp/m78-proof/approval.json \
  --bindings /tmp/m78-proof/bindings.json \
  --runtime-readbacks /tmp/m78-proof/native-resource-readbacks.json \
  --provider-readback /tmp/m78-proof/provider-observation.json \
  --provider-binding /tmp/m78-proof/provider-binding.json \
  --execution-id "$CONTAINER_APP_JOB_EXECUTION_NAME" \
  --output /tmp/m78-evidence/provider-observation.json --execute
```

The provider binding contains the exact `resourceIds`, `release` and
`deployment`. The observation envelope and native request/response schema are
validated by `services/operational_observations.py`. A provider error, partial
list, stale observation or missing forecast cannot emit a healthy substitute.
Run the job with the existing API identity/configuration so telemetry is
authenticated and source-bound.

`pilot_application_probe integrity` runs the bounded read-only production
integrity observer under API identity against the accepted fixture workspace.
Use `--fixture core.json`; the second observation also uses `--before` with
the first source/image-bound receipt. Its first sample explicitly leaves
append-only mutation unknown. Hash baselines stay private; findings/unknowns
remain separate and no repair or investigation closure is inferred.

## Capacity preparation and actual execution

`capacity_validation.prepare(deployed_settings, request_budget=..., concurrency_cap=...)`
produces finite synthetic small/median/large/abusive fixture specifications,
existing enforced settings, ramp/spike/failure/recovery phases and the complete
existing dimension list. Labels are test-fixture sizes, not inferred customer
population or supported cohort. The request/concurrency budget is a campaign
bound requiring separate approval, not a new performance target.

The actual `pilot_application_probe capacity` adapter uses authenticated
primary/secondary clients and the four prepared synthetic account clients. It compares capacity
settings to the native API environment (plus exact candidate defaults), checks
the immutable operation-template hash, records actual HTTP status, request ID,
Retry-After, elapsed time, response bytes/hash and returned effect IDs. It
records an exclusive intent before each request and never retries an uncertain
mutation. At most 900 operations per job fit the existing evidence-export bound.

```sh
python -m infra.milestone_7_8.pilot_application_probe capacity \
  --bundle /tmp/m78-proof/package --authorization /tmp/m78-proof/approval.json \
  --bindings /tmp/m78-proof/bindings.json \
  --runtime-readbacks /tmp/m78-proof/native-resource-readbacks.json \
  --fixture /tmp/m78-proof/core.json --capacity-stage 0 \
  --capacity-operations /tmp/m78-proof/capacity-stage-0.json \
  --execution-id "$CONTAINER_APP_JOB_EXECUTION_NAME" \
  --output /tmp/m78-evidence/capacity-0.json --execute
```

`capacityProof` in the approved plan is the prepared capacity specification.
`capacityStages` contains `phase`, `concurrency` and `operationsSha256` for
each stage. Each operation has `operation_id`, `actor_id`, `workspace_id`,
`kind`, `method`, exact relative API `path`, optional `payload`,
`expected_statuses` and `expected_rejection`. Approved symbolic slots
`${PRIMARY_USER}`, `${PRIMARY_WORKSPACE}`, `${PRIMARY_CANVAS}`,
`${PRIMARY_DOCUMENT}`, `${SECONDARY_USER}`, `${SECONDARY_WORKSPACE}`,
`${SECONDARY_CANVAS}` and `${EXECUTION_ID}` derive only from the accepted
core receipt and native job. Unknown slots and cross-scope operations fail.

Prepare the finite private fixture and exact stage files locally, using the
existing approved model and settings from the prepared runtime configuration:

```sh
python -m infra.milestone_7_8.capacity_fixtures \
  --capacity-plan .runtime/milestone_7_8/full-closure/capacity-plan.json \
  --output .runtime/milestone_7_8/full-closure/capacity \
  --namespace REPLACE_WITH_UNIQUE_BOUND_NAMESPACE --model gpt-5.6-terra
```

The preparation function is `prepare_stages(directory, capacity, namespace=...,
model=...)`. It writes `capacity-00.json` (private generated credentials and
bounded setup specification), subsequent exact operation templates, and the CLI
writes `capacity-preparation.json`. Copy its `capacityStages` and
`capacityFixturePackageSha256` into the single approved bindings file. The
setup stage is `capacity` stage zero with `kind: fixture`; it uses the same
source/authority/native-readback gate and the same `--capacity-operations` flag.

The existing settings produce four synthetic accounts, 11 workspaces, 21 canvases,
45 clean documents (9,176,064 bytes total), and 21 each of comments, workspace
shares, controlled workflows and bounded agents. The small/median/large profiles
use 1 KiB/64 KiB/256 KiB documents. Setup includes isolated agent validation and
explicit production activation requests/decisions in the prepared scope. It
creates two native canonical notes and a related-to edge per canvas for the
existing selected-context workflow/agent contracts. Setup makes zero model
calls; document embeddings are real provider operations during future execution.

Upload concurrency is four; each exact object keeps the existing 900-second
scanner/promotion and 1,200-second publication bounds, with ten-second polling.
The setup reserves 6,000 HTTP requests before any mutation, then maintains a
durable compact intent/result journal (including uncertain outcomes and returned
IDs). This preserves evidence under the existing 2,000-file export cap. It never
replays a failed/uncertain signup, workspace creation or upload. Later measured
jobs receive `--capacity-fixture` with the native setup receipt and
`--capacity-accounts` with the exact original private `capacity-00.json`; its hash
must match the approved fixture package. `${CAPACITY_0_USER}`,
`${CAPACITY_0_WORKSPACE}`, `${CAPACITY_0_CANVAS}`, `${CAPACITY_0_WORKFLOW}`,
`${CAPACITY_0_AGENT}`, `${CAPACITY_0_NOTE_0}` and
`${CAPACITY_0_DOCUMENT_0}` (and subsequent bounded indexes) resolve only from
that source/image/package-bound receipt.

The selected concurrency-eight preparation generates 24 stages: setup,
baseline, four ramp levels, spike, the scoped row-lock stage below, and eight
selected failure/recovery pairs. Baseline
also attempts the existing maximum-size-plus-one upload declaration and requires
413 without uploading bytes. There are twelve logical workflow/agent calls across
baseline/ramp/spike (at most 36 SDK attempts); a cumulative 48-logical-call cap
prevents unbounded repeated phases. A campaign request budget of 10,000 covers
the setup reservation and all generated stages. These are finite exploration
allocations, not supported cohort or performance targets.

For the separately approved database-pool/latency stimulus, prepare with
`--row-lock-seconds 130` (or `row_lock_hold_seconds=130`) and an approved capacity
concurrency above the actual API pool size plus overflow. With the current
runtime's pool 5/overflow 0, concurrency eight permits that observation. This
adds one same-job stage with `proofRole: api`; there is no additional deployed
job or resource. The stage binds `faultSource: postgresql-exact-core-canvas-row`
and exact accepted-core canvas/workspace/owner slots. A joined, parameterized
`SELECT ... FOR UPDATE OF c` locks only that synthetic row. The implementation
rejects another owner/row, non-PostgreSQL semantics, holds over 600 seconds, or
authority without the hold plus a 60-second recovery margin.

All pressure/recovery requests are reserved before acquiring the row lock.
At concurrency eight the stage makes 16 exact-canvas note writes, rolls back
the holder transaction, then makes two different idempotent recovery writes.
HTTP timeout is bounded by hold duration plus 30 seconds and the approval
deadline. It collects actual blocking counts/wait-event types from
`pg_blocking_pids`/`pg_stat_activity`, actual response status/latency and a native
zero-holder-transaction-lock check after rollback. Its timer releases the lock
even while requests are waiting; the `finally` path also rolls back on errors.
The result includes `rowLock` and `recoveryPhase`; retain both in reconciliation.
Native database blocking, API pool telemetry, actual alert windows and successful
recovery must all be observed before claiming a threshold or recovery pass.

Actual production extraction/chunking of the exact synthetic contents yields
10,777,584 UTF-8 chunk bytes including overlap. One UTF-8 byte per token is a
conservative upper bound, not measured billing. SDK `max_retries=2` and existing
`processing_retry_limit=3` (`max_attempts=4`) give an initial indexing upper bound
of 10,777,584 × 3 × 4 = **129,331,008 embedding tokens**. The consolidated package
reserves 160 million for those objects plus bounded query/core/recovery work;
full reindexing of all 45 objects is excluded. Actual accepted provider usage
must still be measured and billing remains unsettled.

Later jobs must receive `--capacity-budget` with the previous cumulative
`capacity-budget.json` and `--before` with the preceding native phase receipt.
The receipt's source/image/stage and hash bind the carried budget; no routine
approval amendment is needed for provider-assigned IDs. Reserved requests remain
consumed after uncertainty. Dropping this carry file is not a fresh allowance.

`validate_results` keeps every unmeasured architecture dimension and missing
fault/recovery observation unproved. It requires every prepared ramp concurrency,
actual successful recovery requests, retained native measurement/artifact hashes,
and actual observed profile sizes. A recovery made only of 429/503 responses
cannot pass. Fixture setup alone does not establish workload throughput,
operational correlation, support limits or fault recovery. Fault
application/restoration remains in the exact separately authorized controller
commands; recovery needs actual effect reconciliation and operational receipts.
Fault labels in generated stage files never establish that an intervention
occurred. The delivery probe's opaque TCP-byte delay, separately labeled
client-side ACK delay, truncated real TLS response and three-event retry load
must be correlated with the actual mixed workload. The TCP relay preserves the
production URL/SNI/certificate and records bounded received/forwarded timing;
client-side ACK sleep alone cannot be described as measured network latency.

There is no extra numerical latency/user-count target to invent. Publish only
the measured enforced limits and observed failure/recovery boundary. If the
approved exploration budget does not reach that boundary, mark it unproved;
do not extrapolate from a small successful run.

## Delivery and cleanup boundary

Password-reset request/confirm/expiry and `activity_delivery_validation` use
the same source-bound authority and private payload loader. The selected
receiver is the existing `activity-v1` contract, not SMTP or a new integration.
Their actual native receipts, two fresh identity scopes and receiver state
readbacks remain required. Their commands and detailed contracts are defined by
the modules' `--help` and the consolidated execution package.

All raw evidence remains private and exported by exact object version/checksum.
Local tests cannot establish native acceptance. End only after the existing
cleanup controller's scoped result, residue counters and preserved-controller
checks are reconciled. No next milestone or deployment is implied.

## Focused outgoing expiry correction

The outgoing production review found a specific outbox fencing defect: a
receiver or finalizer blocked on the outbox row could validate its lease against
time sampled before that wait. The corrected service samples its injectable
clock after acquiring the row lock. Production receiver and dispatcher callers
pass that clock provider rather than a frozen timestamp. The receiver also
revalidates after its transactional projection, before committing or returning
an acknowledgment; crossing expiry rolls back the effect.

Five focused local PostgreSQL cases verify blocked receiver/finalizer rejection,
clock injection and projection rollback. The affected capacity row-lock case
also passed with actual native wait observations. Private receipts are retained
under `.runtime/milestone_7_8/full-closure-local/destination/fencing-review/`.
These source corrections supersede API3. The final API4 artifact and exact
verified source/image bindings are in the finite closure ledger. They do not reopen closed PostgreSQL,
M78-D-001 or M78-D-002 acceptance and do not establish new managed acceptance.


## Selected editable-artifact release extension

The [local release checkpoint](MILESTONE_7_8_EDITABLE_AI_RELEASE_CHECKPOINT.md)
records explicit save, immutable original evidence and selected0030 schema.
Managed core now proves generation leaves the canvas unchanged, then explicit
save, duplicate save, edit/reload and exact original response/citation/Trace
binding. Its seven additional HTTP calls consume the existing1,800-request
core/access/recovery partition and add no model call. Current native recovery
requires0030 and complete hashes for the artifact mapping, original request/
response, live citations, immutable execution citations and existing Trace.
The historical0028-to-0029 path remains separate; no old receipt is relabeled.
Full-closure package deadlines use selected+2ready/+10proof/+12cleanup. Existing
pilot-default+2/+8/+10 and historical evidence remain unchanged.
