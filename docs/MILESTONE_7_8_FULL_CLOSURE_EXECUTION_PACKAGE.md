# Milestone 7.8 compatible full-closure execution proposal

**Preparation only; not spending or execution authority.** This replaces the
current scope of the earlier pilot proposal. Prior campaign budgets are closed,
prior billing remains unsettled, and no new Azure operation, paid provider call,
publication or deployment has been performed. The prior $25.57 forecast/$50
proposal is not an allowance for this larger package.

The [finite ledger](MILESTONE_7_8_FULL_CLOSURE_LEDGER.md) identifies existing
criteria, credited evidence, completed local work and managed gaps. The
[validator interfaces](MILESTONE_7_8_FULL_CLOSURE_VALIDATORS.md) define accepted,
failed and unproved outcomes. PostgreSQL, D001 and D002 remain closed.

## Scope and artifact binding

Reuse the previously prepared, never-provisioned East US target
`rg-m78-a712b8c940-target`, prefix `m78p-a712b8c940`. No broader discovery,
subscription changes, Firewall, VM, public website or new architecture is included.

Foundation is the existing private Blob/Defender/Log Analytics/AMPLS, private
HA Redis B0, PostgreSQL General Purpose D2ds_v4 (2vCore/32GB) with one isolated
PITR copy, temporary Premium ACR, Key Vault, VNet/delegated subnet/private DNS,
six Private Endpoints and the reusable cleanup controller. Operational alert
delivery uses the already prepared private Standard Event Hub/action group.
Six application services run seven replicas: API two (0.5CPU/1GiB each),
worker one (0.5/1), frontend one (0.5/1), gateway one (0.25/0.5), activity-v1
receiver one (0.25/0.5) and outbox dispatcher one (0.25/0.5). Sequential temporary
bootstrap/migration/artifact/proof jobs share aggregate 0.5CPU/1GiB allocation.
The existing idle migration job is temporarily reused as a separately bound
fault-helper slot for at most 40 aggregate minutes overlapping the API proof
job. Peak allocation then becomes 3.75CPU/7.5GiB; no new job or identity is added.
Only terminal jobs may change identity/template; exact original configuration
is captured and restored before another phase.
The receiver and dispatcher reuse the existing worker identity and PostgreSQL.

`enableExternalDelivery=true` deploys the two independent services. Receiver
runs `python -m scripts.activity_receiver`, dispatcher runs
`python -m scripts.outbox_worker`. They use private HTTPS port8011 ingress and
exact `/v1/activity-deliveries`; only a dedicated secret authorizes delivery.
Only existing table INSERT privileges are added for activity and attempt rows.
No separate database, broker, new product integration or receiver payload store.
The durable existing PostgreSQL activity receipt is the deduplication boundary.

Use the exact API/frontend OCI index digests and source input bindings in the
[release ledger](MILESTONE_7_8_FULL_CLOSURE_LEDGER.md#release-bindings).
Preserve their unsigned provenance, inventory, scan and archive receipts.
Both images are built locally; neither is published. No build follows from
provider-assigned hostnames: frontend now validates the server-side public
`OPENCANVAS_PUBLIC_API_URL` and renders only that URL into HTML at runtime.
No secret or server credential is serialized to the browser.

The private preparation root is
`.runtime/milestone_7_8/full-closure-local/package/`. `manifest.json` binds exact
source files and full catalog; `planned-bindings.json` binds exact target IDs,
source commit, image digests, workload allocations, native query hashes,
operations and relative window. The final review-package hash is reported only
after those bytes are frozen. Unknown provider-created IDs enter only through
existing exact ARM readback admission. No `approved:true` record is created by
local preparation.

## Decisions that cannot be supplied by implementation

1. **Full editable-AI contract:** keep the historical editable-node criterion and
   authorize its product change, or explicitly amend that exact full-7.8
   criterion to the current controlled read-only draft with affected validation.
   The earlier pilot choice is not an amendment to full milestone acceptance.
2. **Trusted release endorsement:** identify an approved signing public key or
   exact certificate identity/issuer, and policy accepting an endorsement of
   locally generated provenance. Both artifacts currently remain unsigned.
   Existing detached signing commands are in the
   [release record](MILESTONE_7_8_PILOT_RELEASE_CANDIDATE.md#signing-decision).
3. **Actual provider and operator inputs:** existing SMTP TLS account/permitted
   sender plus one approved native inbox, OpenAI credential/entitlement for the
   previously selected models, exact operator principal and an existing private
   browser/export route. A bounded check found no configured environment keys or
   repository `.env` files; no credential vault was searched. Generate synthetic
   account/session/delivery secrets privately. No new integration or cheaper
   hosting topology is proposed. Without a private route the workbook screenshots
   and evidence export cannot be claimed; a VM/Firewall is not added implicitly.
4. **Historical Firewall/VM category evidence:** supply the missing original usable
   category receipts or explicitly decide their applicability to the final
   architecture. This environment contains neither; its other category rows do
   not close those two historical gaps.
5. **API admission ceiling:** choose the intended maximum in-flight requests per
   API replica for this proof. The existing ratio-valued saturation signal has no
   legitimate denominator today. Optional admission/counting is implemented; no
   limit is selected or inferred from CPU, test concurrency or invited-user count.
   `apiRequestConcurrencyLimit=0` in preparation means unresolved/disabled, not
   an accepted capacity ceiling.
6. **One separate spending/cleanup approval after bindings are complete:** include
   exact controller renewal, temporary exact-IP ACR access (at most20minutes),
   registry publication of the verified artifacts, bounded fault interventions,
   provider observations and exact Key Vault purge. No ongoing hosting authority.

The selected activity-v1 receiver decision is resolved and is not requested again.
Apart from the missing existing API admission bound, no new latency target or
safe user-cohort number is requested: retain existing
catalog objectives, report actual tested envelopes and leave saturation unproved
if it is not reached inside the approved finite workload.

## Execution sequence and actual observations

The existing [operator commands](MILESTONE_7_8_PILOT_EXECUTION_COMMANDS.md) remain
the reusable foundation/controller/transport/cleanup mechanics; the full-closure
bindings below supersede their historical pilot feature flags and digests.

1. Record separate approval and derived absolute UTC deadlines. Before billable
   resources, renew/read back preserved controller deadline and arm the exact
   target schedule/binding using existing restart-safe commands. The controller
   identity, Reader grant and bootstrap history stay intact. Read back the
   5,000-cent allowed ceiling; do not republish unchanged controller content.
2. Deploy foundation, reconcile the named deployment, admit exact native outputs
   and service identity; publish verified archives during the bounded exact-IP
   interval, verify digest equality and restore private ACR access. Deploy jobs,
   execute bootstrap and guarded migration once with actual execution IDs. Then
   deploy application stage with full catalog and external delivery enabled.
   Stop/reconcile the standalone dispatcher before creating unused core events.
3. Run `account`, then `core` through the production API/worker/consumer. Accounts
   are synthetic and independently authorized. Preserve accepted core fixture
   IDs and all intent/result files. The new managed integration retains native
   dual scanner agreement, quarantine and exact version/checksum. Package-specific
   900-second/20-second scanner policy must be explicitly included in approval;
   existing 300-second defaults are unchanged. Failed/late evidence is diagnostic.
4. Run actual activity happy/duplicate, lost ACK, stale claim, bounded receiver
   outage/terminal failure and final-claim recovery operations. Keep dispatcher
   stopped for controlled claims; restore receiver, start standalone dispatcher
   and observe durable drain afterward. Every status must come from native
   receiver/DB evidence, not a mocked provider. Exact 404/5xx transport retry is
   bounded; auth/schema failures remain terminal. Fourteen unused core outbox events
   are reserved, including one separate alert stimulus; all nine transport operations
   and a distinct post-retry recovery event are required; no invented event type or business effect is inserted.
5. Begin two distinct application password-reset requests for the approved inbox.
   Bind actual MIME Message-ID/recipient/sender/link token to the request and native
   inbox receipt. Confirm one reset once, reject reuse, old sessions and password,
   accept the new password. Validate the separate token after unchanged30-minute
   expiry while other observations proceed. Submission alone cannot pass.
6. Complete index-freshness ageing/recovery on the small core before adding the
   45 capacity documents, refreshing every then-active head within its existing
   recovery windows. This avoids an unbudgeted full large-fixture reindex.
   Collect actual API/worker/outbox telemetry and run integrity baseline/recheck.
   Query every catalog panel, capture13 native workbook renders and run all16
   native alert scenarios. Use actual operations/native provider observations;
   never send made-up production metric samples. Read exact backup/forecast
   provider responses only for planned resources. Preserve missing versus zero.
   Run bounded exporter failure/readiness, source/privacy rejection, fresh-session
   access revoke/restore and retention readbacks. Alert-specific sustained windows
   may overlap compatible load; do not truncate catalog timing to a10-minute
   intervention limit. Integrity recovery requires explicit authorized investigation.
7. Run source-bound synthetic capacity setup and phases, carrying the same global
   reservation ledger between jobs. Measure actual workload dimensions, ramp/spike,
   selected dependency faults, admission/rejection, operational correlations and
   recovery. Reuse component failover/health-soak evidence; do not rerun PG/D001/D002.
   A successful finite run without saturation reports only its measured envelope.
8. Restore only the affected current release. Stop source worker and dispatcher,
   create exact nonterminal fixture, take two complete quiescent snapshots, retain
   the actual final acknowledged mutation and choose a later valid restore point.
   Submit PITR to `pg-m78p-a712b8c940-restore`; keep original server. Admit terminal
   native Ready state and private bindings, reconcile identities/grants and run
   fresh `restore-role` jobs for API and worker. Temporarily point the private API
   only to the restored server, then `restore-verify`, `restore-fence`,
   `restore-resume` in order. Restore the API's original captured binding and run
   `restore-rollback` to reconcile shared provider effects and resume original
   exact work once. Only then unlock background writers. Record actual RPO marker
   exposure/RTO, not an invented zero-loss or performance target.
9. Export exact-version evidence with hashes, reconcile each existing assertion,
   then perform verified cleanup by the deadline. Preserve useful accepted results,
   failures and unproved assertions. Update/commit/push sanitized checkpoint under
   standing authority; no deployment or next milestone follows.

The current managed restore source is0029. The local seeded0028→0029 guarded
migration proves preservation and new identity fences separately. It does not
fabricate pre0029 idempotency identities or claim a managed0028 restoration.
No immutable migration is edited or a new migration introduced.

## Concrete entry points

Offline preparation/compilation (no Azure execution):

```powershell
.venv/Scripts/python.exe -m infra.milestone_7_8.pilot_validation prepare `
  --bundle $newPrivateBundle --release $boundRelease --deployment m78p-a712b8c940 `
  --ceiling 50 --full-closure
& "$env:USERPROFILE/.azure/bin/bicep.exe" build infra/milestone_7_8/pilot.bicep `
  --outfile $privateCompiledTemplate
```

After approval, all job entry points use the common exact arguments below;
`$OPERATION` is an enumerated operation, never an arbitrary shell command:

```sh
python -m infra.milestone_7_8.activity_delivery_validation "$OPERATION" \
 --bundle /tmp/m78-proof/package --authorization /tmp/m78-proof/approval.json \
 --bindings /tmp/m78-proof/bindings.json \
 --runtime-readbacks /tmp/m78-proof/native-resource-readbacks.json \
 --fixture /tmp/m78-proof/core.json \
 --execution-id "$CONTAINER_APP_JOB_EXECUTION_NAME" \
 --output /tmp/m78-evidence/delivery-operation.json --execute
```

Operations: `activity-delivery-happy`, `activity-delivery-lost-ack`,
`activity-delivery-stale`, `activity-delivery-outage`,
`activity-delivery-final-recovery`, `activity-delivery-network-delay`,
`activity-delivery-delay`, `activity-delivery-partial-response`, and
`activity-delivery-retry-load`. Use the same private pack/loader and exact
wheel archive; no runtime pip install or image rebuild.

`pilot_application_probe` operations add `integrity`, `telemetry-queue`, `capacity`,
`restore-snapshot`, `restore-fixture`, `restore-role`, `restore-verify`,
`restore-fence`, `restore-resume`, `restore-rollback` to existing `account/core`.
`--before` always names the actual retained phase receipt; no recreation after
uncertain writes. `password_reset_validation --help` defines the request,
confirm and expiry inputs; native inbox files remain private. Full schemas and
expected/observed comparisons are in the linked validator interface document.

Offline recovery reconciliation consumes actual exported native/probe files:

```powershell
.venv/Scripts/python.exe -m infra.milestone_7_8.pilot_recovery_acceptance `
  --plan $plannedBindings --manifest $nativeRecoveryManifest --output $newRecoveryResult
.venv/Scripts/python.exe -m infra.milestone_7_8.destination_acceptance `
  --plan $destinationPlan --manifest $nativeDestinationManifest --output $newDestinationResult
```

## Revised temporary cost boundary

Proposed **incremental ceiling $50 USD**, cumulative ceiling **$400.89 USD if
approved**. Prior approved ceiling remains $350.89; billing is unsettled. This
is not authority and does not reuse any earlier remaining allowance.

The retained public meter prices and quantities are in the
[prior cost model](MILESTONE_7_8_PILOT_COST_MODEL.md). Scope correction adds:

| Bound | Temporary USD |
|---|---:|
| Retained temporary scope, conservative10-hour allocation | 25.5678 |
| Two independent0.25CPU/0.5GiB activity services, active10hours | 0.5400 |
| All16 alerts at1-minute cadence instead of5-minute | 0.3288 |
| Embeddings increased from1M to160M worst-case token allowance | 3.1800 |
| Existing second job overlapping the proof job, at most40minutes | 0.0360 |
| **Revised temporary forecast** | **29.6526** |

Total ACA allocation is3.25CPU/6.5GiB including sequential probes. Existing
allowances remain:200 model attempts at15k input/1600 output (including reasoning
and retry reservations),1GiB logs,1GiB scanning,10GB stored Blob/version data,
10GB processed/egress,10k each storage read/write/list,1millionACA requests,
restored PostgreSQL4hours, full-day ACR and two DNS billing days. The45 clean capacity documents total9,176,064bytes and10,777,584UTF8chunkbytes
including overlap. With three SDK attempts and four durable worker attempts,
the conservative initial embedding bound is129,331,008tokens;160M reserves
scoped core/query/recovery headroom ($3.20), not expected usage. The concrete
24-stage generator reserves6,262 HTTP operations, four synthetic capacity users,
11workspaces/21canvases and12 logical model calls (at most36SDK attempts); core,
alert and recovery requests share the overall10,000 request/200provider-attempt
limits. Concurrent setup uploads are capped at4. No full45-document
reindex is included. Actual synthetic
capacity operation reservations must fit these allocations; stop or revise the
proposal before approval if they do not. No provider retry is a fresh allowance.
The ceiling includes headroom; it does not guarantee Azure stops billing at it.

For comparison only, adding the two permanent services and corrected alert
cadence to the same previously priced topology changes its active fixed monthly
illustration from$490.0444 to$553.4644, idle arithmetic floor from$365.8714 to
$401.6974, and example usage-inclusive total to$638.1964. These are **not ongoing
hosting approval**, new topology research, predicted charges or a safe cohort.

## Window and verified cleanup

Relative to separate recorded approval: begin provisioning by+2hours; stop new
proof and scheduled cleanup at+8hours; cleanup authority ends+10hours. Record
absoluteUTC deadlines before first paid operation. Long alert windows may run
in parallel with compatible workload/reset-expiry observations. Reserve restore
and cleanup time; failure to observe a rule before cutoff is unproved, not a
reason to extend the deadline silently.

Cleanup removes only this group's apps (including receiver/dispatcher), jobs,
environment, both PostgreSQL servers, Redis, Blob/artifact/evidence containers,
ACR, identities/target grants, VNet/endpoints/DNS, vault, workspace/AMPLS/DCE/DCR,
16alert rules/13workbooks/action group/EventHub, target schedule and binding.
Explicitly authorize and verify purge of only
`Microsoft.KeyVault/locations/eastus/deletedVaults/kv-m78p-a712b8c940` through an
existing entitled principal. Soft-deleted vault residue is not hidden by RG absence.
Preserve the reusable controller, identity, Reader grant and bootstrap history.

Reconcile named resource operations before retry. A timeout does not establish
failed deletion; use existing cleanup job/native inventory. Never reopen a group
whose deletion has begun. Private recovery checkpoint records operation/native
executionID, intent/result/export paths/hashes, accepted/failed/unproved ledger,
consumed reservations, exact next action and absolute proof/cleanup deadlines.
Finalize only after export verification and zero scoped residue counters.

## Provider cost measurement qualification

Actual returned input/output token counts now feed `mobius.provider.cost` using
existing server-owned estimate tariffs. Unconfigured zero tariffs, missing usage
and mock providers emit no cost observation. The proposal binds the selected
GPT-5.6 Terra short-context rates of$2/$12 per million input/output tokens,
verified against the [official model page](https://developers.openai.com/api/docs/models/gpt-5.6-terra).
This is a usage-based estimate, not settled billing; cache adjustments and
invoice reconciliation remain separate. The forecast already retains its
conservative cache-write contingency. No new price or tariff product is invented.

## Concrete workload and intervention bindings

The private `package/capacity-final/` preparation binds 24 exact stages: four
synthetic accounts, 11 workspaces, 21 canvases and 45 documents totaling
9,176,064 bytes; 6,262 reserved HTTP requests, 12 logical model calls and at
most 36 SDK attempts. The global bounds remain 10,000 HTTP requests, 200 model
attempts and 160 million embedding tokens. Test concurrency is capped at eight;
this is independent of the unresolved production API admission ceiling.

`capacity-07.json` runs an exact core canvas row lock under API identity for
130 seconds, 16 real production writes while held, guaranteed rollback and two
distinct recovery writes. It records PostgreSQL blocking observations and
remaining holder locks. It does not change a database timeout or assume the
existing 500ms/1,000ms alert thresholds will necessarily be reached.

The [bounded command manifest](../infra/milestone_7_8/pilot/full_closure_interventions.json)
contains exact target paths, native before/after collection, fault commands,
restoration limits and acceptance evidence for each intervention. All variable
values must come from the bound plan or the specified exact native readback;
no subscription-wide discovery or arbitrary command expansion is permitted.
The foundation has no NSG. Blob/scanner and Redis failures use their exact
existing scoped grants, with original grants retained and restored; propagation
that fails to demonstrate a real outage remains unproved. Provider failure
uses a new noncredential marker only, never a real session, SMTP or delivery
secret as a substitute API key.

The queue SELECT-grant helper uses only the existing migration identity and
`public.document_processing_jobs`, preserves the original grant option and
restores in `finally`. A follow-up restoration binds the captured same-campaign
receipt and actual execution, not an invented future hash. Independent worker
permission-denied/no-effect and restored readiness evidence is required.
The migration proof role receives only exact artifact-reader/evidence-writer
container grants and no application or provider secrets.

Native cost observation binds Usage/Custom, Daily PreTaxCost/Sum, forecast-only
requests to complete UTC calendar days intersecting this approved temporary
window. It never compares a whole-month forecast with a temporary ceiling.
Provider unavailability is unproved; a local forecast cannot replace native
evidence. The [native Forecast API contract](https://learn.microsoft.com/en-us/rest/api/cost-management/forecast/usage?view=rest-cost-management-2025-03-01)
defines these request fields.

The bounded second-job overlap adds $0.0360 (2,400 seconds at 0.5CPU/1GiB)
to the retained $29.6166 calculation, yielding **$29.6526 USD**. This is part
of the same proposed $50 incremental/$400.89 cumulative ceilings, not a new
authorization or a claim of settled cost.

## Observation classifications and remaining full-milestone limits

The source matrix records all 53 metric producers and three trace tuples.
Ordinary service measurements are distinct from actual production operations
invoked by a source-bound proof job. `telemetry-queue` waits the real configured
lease, recovers an exhausted attempt to a dead letter, performs authorized
replay and cancels the new job; both terminal histories remain. Its exporter
must acknowledge the actual measurements before a successful receipt is saved.

Incident-only signals remain conditional: real nondeterministic index output,
limiter guard rejection, native scan/storage failure and actual timeout cannot
be assumed from healthy traffic or replaced with synthetic provider results.
The destination plan lists their exact source and evidence limitation separately.
The proposed faults test applicable cases; any absent required observation is
reported unproved. An emitted metric by itself does not establish alert firing,
rendering, a supported load limit or full milestone closure.

This package can close the existing D003 destination assertions, D004 worker
and multi-service/reset delivery, D005 four affected recovery assertions, D006
current-artifact/security and measured capacity observations, and applicable
D007 native categories **only where their actual results are accepted and
cleanup is verified**. It cannot decide the editable-AI contract, authenticate
an unsigned artifact, supply operator/provider credentials, recover unlocated
historical Firewall/VM receipts or infer an unobserved saturation threshold.
These are explicit remaining dispositions, not a reason to reopen PG/D001/D002.
