# Milestone 7.8 full-closure alert operation map

Preparation only. This map uses the 16 existing entries in
[alerts-v1.json](observability/alerts-v1.json), the actual production emitters,
and the [destination validator](MILESTONE_7_8_FULL_CLOSURE_VALIDATORS.md).
It grants no execution or spending authority. PostgreSQL, D001 and D002 stay
closed; these are current-candidate destination observations, not repeat
acceptance campaigns. Billing remains unsettled.

## Common operation and evidence contract

Bind every operation to the final full-closure source commit, API image digest,
release, deployment, existing target group and exact resource IDs in
`planned-bindings.json`. Retain API request intents/results, native ARM
request/response/readbacks, actual job execution IDs and UTC observation times.
All paths below are private under
`.runtime/milestone_7_8/full-closure-local/managed/alerts/<alert-id>/`.
They are future receipt locations, not claims that evidence exists.

Each alert has `stimulus.json`, `recovery.json`, `windows.json` and
`native-events.json`. The destination manifest maps these to the existing
`alert-scenarios`, `alert-windows-<id>` and `native-alert-events` keys, with
byte hashes. The scenario's `stimulusEvidence` names a bound artifact, not a
summary of expected behavior. `startedAt` precedes the actual stimulus and
`endedAt` includes the matching native Fired/Resolved delivery. Integrity
instead requires the separate authorized native closure described below.

Run the already implemented `pilot_application_probe capacity` operation with
the source-bound `--capacity-stage`, `--capacity-operations`, `--fixture` and
carried request budget. Operation records use the actual scoped API routes and
synthetic users/documents already in the accepted core fixture. Do not resend
an uncertain mutation. For paced observation, schedule distinct prebound
stages; do not loop one stage to obtain a fresh request allowance. The
provider/AI count and aggregate request/concurrency ceilings remain those of
the final package, including repeated healthy observations below.

For a listed app stop/start, use these existing exact ARM operations only
after separate approval; substitute the single approved ID and capture each
response before progressing:

```powershell
az rest --method POST --url "https://management.azure.com${exactAppId}/stop?api-version=2025-07-01"
az rest --method GET --url "https://management.azure.com${exactAppId}?api-version=2025-01-01"
# Reconcile the stop before the fault observation; a 202 is not completion.
az rest --method POST --url "https://management.azure.com${exactAppId}/start?api-version=2025-07-01"
az rest --method GET --url "https://management.azure.com${exactAppId}?api-version=2025-01-01"
```

The prepared foundation has **no NSG**. The exact bounded command template is
[full_closure_interventions.json](../infra/milestone_7_8/pilot/full_closure_interventions.json).
It selects existing Blob role assignments and the existing Redis API ACL for
reversible access faults. Capture the exact assignment ID, scope, principal,
role/access string and before bytes; restore only that same assignment.
Do not create an NSG, Firewall or VM. Permission propagation may prevent an
actual denial within ten minutes; restore on deadline and leave the assertion
unproved. Native deletion alone cannot establish application failure.

For a configuration intervention, retain the exact active revision/template
and patch only the named field using the existing Container Apps template
update route. Wait for actual revision readiness and restore the captured
reference/value. Never put secret values in commands, receipts or Git. No
configuration intervention authorizes an image build.

## Requirement-by-requirement operation map

`W` below is the unchanged catalog evaluation window. Counts are counts of
actual adjacent evaluation windows, not arbitrary polling attempts. Nominal
allocations allow complete windows; native observation timestamps and KQL
states determine acceptance. Add destination ingestion, five-minute evaluation
alignment and native delivery latency within the package's hard stop time.
Native stateful resolution additionally requires three clear evaluation periods
(fifteen minutes) after the catalog recovery condition; the table's existing
nominal stimulus/recovery times exclude that additional native delay. Integrity
still requires authorized investigation and manual closure. The
[prerequisite timing plan](MILESTONE_7_8_EXECUTION_PREREQUISITE_DECISIONS.md#timing-and-cost)
supersedes the previous one-minute proposal without changing catalog semantics.
An early missing-data alarm is never relabeled a measured threshold breach.

| Existing alert / producer | Actual stimulus and recovery operation | Existing timing and required receipt contents | Limitation / approval condition |
|---|---|---|---|
| `api-latency-v1`; API middleware `mobius.api.duration` | Run the bounded concurrent read/search/write mix against the real API. Use actual latency from server telemetry; no client sleep or fabricated metric. Stop the pressure and continue low-rate successful requests. | W=5m; p95 >=1000ms in two windows, then <750ms in two. Nominal 10m pressure +10m recovery. Bind request/status/latency receipts and actual p95 window values. | If allowed load never crosses 1000ms, this threshold scenario is **unproved**. Do not lower the threshold or silently increase requests/concurrency. |
| `readiness-v1`; `/api/v1/health/ready` completion logs | Reuse the gateway-outage scenario while API remains running. Make >=3 actual readiness requests after exporter failure changes dependency readiness; restore gateway, drain and obtain >=3 consecutive actual 200 responses. | W=5m; three failures, three consecutive successes. Preserve exact statuses in order and native Fired/Resolved. | Stopping API alone does not create its production 503 logs. If this dependency only reports degraded 200, select another already approved real dependency fault; do not assert failure from an operator report. |
| `database-saturation-v1`; `MeasuredAsyncQueuePool` | Reuse measured concurrent API database work. Actual pool acquisition >=500ms or a real pool timeout supplies the breach. Remove load; low-rate normal operations supply <250ms and no timeouts. | W=5m; two breach windows, three healthy windows; nominal 10m+15m. Retain connection/pool configuration and actual acquire/timeout records. | A dropped TCP connection is not automatically a pool timeout. No PostgreSQL acceptance rerun, server resizing or fabricated lock/sleep measurement. Unreached contention stays unproved. |
| `storage-outage-v1`; versioned storage operation decorator | Remove only the captured API download-role assignment on the isolated clean container. Issue bounded real exact-version reads, retaining failures and denominator. Restore the identical assignment and verify normal exact-version reads. | W=5m; failure ratio >=.05 in two adjacent windows; <.01 in three. Nominal 10m faulty samples +15m healthy; restore by ten minutes regardless. | Two native breach windows must contain actual failures; RBAC caching can leave this unproved. No mutation retry without exact object/version reconciliation. No new networking resource. |
| `scanner-outage-v1`; private scanner bridge / committed unavailable decision | With one approved harmless clean fixture quarantined, remove only the captured worker quarantine-container assignment. Let the actual consumer attempt the protected operation and record unavailable. Restore by ten minutes, then process three fresh clean fixtures through both native sources and production consumer. | W=5m; one unavailable verdict/bridge failure; then three actual healthy scan decisions and no unavailable samples in the recovery window. Preserve scan IDs, exact versions and dual-source receipt hashes. | Cached authorization or no actual unavailable producer outcome leaves this unproved. Preserve 900s decision/20s retry and expiry rejection. Late evidence cannot rescue an expired fixture; healthy scans may take additional elapsed time. |
| `queue-backlog-v1`; durable worker backlog metrics | Use the **missingData=breach branch** during the bounded worker stop already needed for recovery. Record absence of the rule's own signal. Restart the same worker; it measures actual queue age and drains only eligible work. | W=5m; two absent windows; then two measured windows <120s. Nominal 10m absence +10m recovery. Also retain actual pending/processing counts and queue ages. | Worker stop removes its metric producer, so it does not by itself prove a measured >=300s backlog. That threshold alternative requires a running observer and genuine old queued work; do not claim it from absence. |
| `worker-stale-v1`; worker polling heartbeat logs | Reuse the exact worker stop; verify provider Stopped and loss of fresh production heartbeat. Start it and observe two actual healthy poll heartbeats. | W=2m; two missing windows (nominal4m); >=2 fresh heartbeats in the recovery window. Retain actual poll timestamps and native pair. | No synthetic heartbeat or merely successful ARM start. Coordinate with source/restore fencing before resumption. |
| `limiter-outage-v1`; actual rate-limit dependency decisions | Remove only the captured existing Redis API ACL, issue bounded guarded API requests and retain actual fail-closed results. Restore the identical ACL by ten minutes and obtain three healthy decisions. | W=2m; one unavailable decision; last three healthy decisions. Retain health=0/1 sequence and native pair. | Existing connections/cached permissions can leave the denial unproved. D002 stays closed. Never authorize the request when shared limiter is unavailable. |
| `indexer-freshness-v1`; scoped publication-age observer | Keep one actual active publication unreplaced until age >=900s. Periodically finish a bounded real document processing job in that workspace to invoke the production observer while the old head remains. For recovery, use the existing `/api/v1/workspaces/{workspace}/canvases/{canvas}/documents/{document}/reindex` operation for **every active fixture head**, then complete an actual document job to observe the refreshed heads. Repeat refresh/observation before any head reaches300s throughout recovery. | W=15m; two >=900s/drift windows, two <300s/zero-drift windows. Allocate initial15m ageing, then30m breach +30m recovery. Preserve head/publication timestamps and job/reindex execution IDs. | This producer measures age of the **oldest active head**, not pending-job lag. An unchanged old head can fire. Reindex completion must actually advance all relevant heads; idempotent reuse cannot be assumed to refresh timestamps. If it does not, recovery is unproved. No backdating or immutable publication edit. |
| `provider-degradation-v1`; `ObservedAIProvider` | Prefer an approved exact provider-endpoint egress denial when an existing bounded rule can isolate that destination. Otherwise the package must explicitly bind a temporary API credential-reference substitution that causes a real provider authentication rejection, followed by exact reference restoration. Make one actual grounded draft attempt in each breached window; restore and make healthy grounded calls in three recovery windows. | W=10m; actual failure ratio >=.05 for two windows, <.01 for three; nominal20m+30m. Preserve real application/provider outcomes and native ratio denominator. | A ten-minute network denial cannot be extended to obtain20m. Credential-reference fault requires its own explicit scope/window and actual failed calls; no invalid endpoint, mock response or unbounded provider spend. Without a suitable approved fault this row is blocked. |
| `outbox-backlog-v1`; standalone `mobius-outbox` dispatcher | Reserve one additional actual pending product event after transport fixtures. Run the real dispatcher with only its independent receiver stopped; actual bounded retries reach one durable terminal attempt. Restore receiver; keep polling/draining remaining eligible rows. | W=5m; **one terminal-failure observation fires immediately**; two windows age<120s and zero new terminal-failure observations recover. Nominal5m+10m. Bind event/attempt IDs, native HTTP failure, terminal metric, live backlog gauge and native pair. | Probe-only dispatcher instances without telemetry do not supply this signal. Never erase/reopen the terminal row to obtain recovery; it remains history. Restore receiver within ten minutes. |
| `evidence-integrity-v1`; scoped reference-integrity observer | Exercise the explicit **missingData=breach branch** while the real observer is absent during the worker stop. Preserve native absence as the incident finding. Restore worker; complete genuine work and retain its actual integrity check. Authorized operator investigates the absence, binds that finding hash and closes the exact native alert. | W=5m; one absent window. Recovery is **authorized investigation + native alert Closed**, not healthy zero or automatic mitigation. `integrity-authorized-closure` must bind approved authority, operator, finding hash, fired alert ID and successful native state change/readback. | This closes absence/alert-routing behavior only; it does not claim an observed corrupt append-only row or all integrity classes. No evidence tampering. If the requirement reviewer requires a positive corruption finding, that specific assertion remains unproved and needs a separate non-destructive design decision. |
| `telemetry-loss-v1`; actual exporter outcomes | Stop only gateway, run bounded ordinary API requests until >=3 real export attempts fail and/or bounded buffer drops occur; capture readiness and actual counters. Restart gateway; continue low-rate real traffic until buffer drains and >=3 successful export outcomes reach destination. | W=5m; one dropped signal or three failures; recovery last three exports healthy and buffer maximum zero in the recovery window. Nominal5m fault+5m clean recovery, plus drain. Reserve at least four successful application export cycles to deliver the preceding three outcome observations. | Export observations are carried on the next application batch in a fixed32-signal reserve; they cannot export themselves. Application buffer remains configured-bounded; total wire batch <=512. Retain actual loss/delay, never infer an outage record arrived while destination was unreachable. |
| `backup-freshness-v1`; native provider observer | Before emitting the first real backup observation, capture the exact-source absence and native missing-data Fired. Collect the complete actual server backup list, bind its bytes, then run `pilot_validation provider-observation`; require latest completed backup age<86400s and recovery. | W=1440m; one missing-data breach, latest genuine fresh observation recovers. No24h wait is required for this branch. Native GET `<server>/backups?api-version=2025-08-01`, completion timestamp and byte-bound observer receipt. | A new server with no completed backups cannot recover yet. Provider empty/error/partial responses emit no healthy zero. This does not prove an observed >24h-old backup. |
| `capacity-v1`; actual database pool checkout utilization | Run the finite concurrent workload against the unchanged deployed pool size/overflow. Capture actual checked-out connections divided by that capacity. Remove pressure, retain low-rate traffic producing real checkouts, and observe utilization below.65. | W=15m; maximum >=.8 for three consecutive windows, then maximum <.65 for three; nominal45m+45m. Bind actual request phases, pool settings, native utilization samples and Fired/Resolved. | This producer measures pool occupancy, not CPU, memory or a supported user count. If the bound workload does not reach.8, keep the alert assertion unproved. Do not shrink the pool merely to manufacture the breach or change its denominator during recovery. |
| `cost-v1`; native provider forecast observer | Capture initial missing forecast and native Fired. Collect complete actual USD Forecast rows for the exact approved scope, emit through `provider-observation`, and require value<.7 of the bound server-owned operating ceiling. | W=1440m; one missing-data breach; latest genuine forecast below.7 ceiling recovers. Native POST `<scope>/providers/Microsoft.CostManagement/forecast?api-version=2025-03-01`, exact body/timeframe and rows required. | New/temporary scopes may lack usable forecasts. Local estimates, posted costs, approved ceilings and empty responses cannot substitute. Never lower/raise the operating ceiling to force acceptance. If native forecast is unavailable or not below threshold, recovery remains unproved; billing stays unsettled. |

## Execution grouping and blocking conditions

Run initial backup/cost missing-data observations before their first native
provider export. A genuine early missing-data integrity event can be retained
for authorized investigation. Keep the normal production-signal check separate:
these absences do not waive any required metric/trace producer observation.

Combine worker-stop queue/heartbeat/integrity observations with the already
planned quiescence period where timings and fencing permit. Combine narrow
Blob/scanner faults and gateway/readiness/exporter faults only when receipt
sources can still distinguish each actual failure. Keep the alert receiver and
cleanup controller live. Finish index freshness firing and its complete recovery
on the **small core workspace before adding the 45-document capacity profile**.
Refresh every then-active core head before300s, throughout the two15m recovery
windows. Do not repeatedly reindex the later45-document profile: that would
exceed the proposed160-million embedding-token envelope. Capacity/API/pool
pressure and their90m observation period follow this index phase; independent
provider/readiness collection can overlap only when it cannot contaminate
another recovery window. Record the dependency order in final stage
bindings; do not run mutually conflicting faults concurrently.

Existing capacity semantics can need45m breached plus45m recovered. This is
sustained bounded workload, not a90-minute network outage. A sampled maximum
must stay below.65 throughout each recovery window; one idle observation does
not erase prior high utilization. The index scenario can need75m including
natural ageing and repeated genuine reindex work. Recalculate request/provider
budgets and the temporary forecast with those stages before spending approval.

The exact package is not executable until all stage files, cumulative request
reservations, scoped grant/ACL/credential-reference interventions, restoration
receipts, operator closure authority, provider request bodies and source/query
hashes are bound. An unavailable controlled fault or provider observation is a
specific blocker, not permission to start another campaign hoping it appears.
The existing eight-hour proof hard stop and cleanup deadline remain upper
bounds of the proposal; no failure or delayed alert extends them.

No extra general-purpose fault framework is needed. The existing workload,
provider-observer, native query/alert collectors and exact ARM stop/start/
configuration commands cover these paths. Run `destination_acceptance` on
the manifest after collecting real windows and events. Report each absent or
failed scenario as unproved or failed; local generation/tests do not mark an
alert accepted. Full milestone closure still requires every applicable
existing assertion and verified campaign cleanup.

## Bounded client transport and concurrent retry fixtures

The existing `activity_delivery_validation` module now also implements these
four source-bound operations. They require the same exact private receiver,
separate stopped dispatcher, image/runtime native readbacks and actual
production-created pending events. No API image change or TLS trust weakening
is involved. Local tests use an ephemeral trusted local certificate only;
managed execution uses the platform's ordinary verified certificate trust.

| Operation | Actual bounded intervention and measured outcome | Capacity interpretation |
|---|---|---|
| `activity-delivery-network-delay` | Pre-resolve the exact approved receiver to a private IP. Within one exclusive proof job, redirect only that receiver hostname/port to a temporary loopback TCP relay. The relay forwards opaque TLS bytes to the pinned private endpoint and holds server-to-client bytes for11s, crossing the existing10s dispatcher timeout. Record actual received/forwarded offsets, byte counts and hold durations, reconcile zero or one existing durable effect, remove the relay/hooks, then retry normally to exactly one delivered effect. | Actual injected delay on the TCP path at the client boundary, with original production URL, SNI, certificate/hostname verification and consumer unchanged. No TLS termination, new trust authority or claimed server latency. At most3 connections,64KiB total read bytes,128 timing rows and20s lifetime; original resolver/connector restored and listener closed are acceptance conditions. Broader under-load closure still needs the independent workload interval and recovery correlation. |
| `activity-delivery-delay` | The unmodified production `HttpActivityConsumer` completes the real authenticated TLS request and verifies the ACK. The probe holds that ACK client-side for a requested11s; the existing dispatcher10s delivery deadline cancels it. Record actual request time, actual hold duration and cancellation. Require one committed receiver effect and source retry_wait before retry; the next normal request must acknowledge exactly that effect. | A measured **client ACK-processing delay**, not a server-latency measurement or proof of network propagation delay. The delay is below20s and inside the30s claim lease. Full capacity acceptance must bind a concurrent workload interval; this fixture alone is one delivery operation. |
| `activity-delivery-partial-response` | Send the exact claim over verified TLS, require real HTTP200 headers <=8KiB and canonical signed ACK length <=1KiB, read exactly32 actual body bytes matching the expected ACK prefix, then close without consuming the rest. The fault adapter raises uncertain transport to the unchanged dispatcher. Require durable effect reconciliation, one retry, delivered state and one effect. | Actual **client-side truncation of a real receiver response**; no fabricated provider body or acceptance of partial data. Report bytes read/unread, prefix hash and wall-clock duration. It does not claim the receiver emitted a malformed response. |
| `activity-delivery-retry-load` | Native receiver state must be Stopped. Select exactly three existing unused max-attempts3 events; invoke production HTTP delivery concurrently in three bounded rounds, preserving1s/2s retry eligibility. Record measured overlapping delivery-operation counts and per-operation times, actual HTTP/connection outcomes, exactly9 attempts, three terminal histories and zero effects. | Bounded concurrent retry load; no inferred population-scale storm. Restart receiver and use a distinct pre-existing pending event with normal `activity-delivery-happy` for post-restoration success. Retain terminal rows unchanged. Tie mixed application load and its recovery receipts to this exact interval before claiming broader failure-under-load closure. |

The original five transport operations consume six existing events; the new
four consume six more. Reserve one additional existing event for normal
post-retry-load recovery, and a separate one if the standalone dispatcher is
used for the outbox alert terminal stimulus. Thus the combined sequence needs
13 existing pending events, or14 with that alert stimulus, without fabricating
domain events or increasing per-event retry limits. Collect and verify available
event IDs before pausing consumers or starting faults. Each native job output
retains `transportFault`/`rounds`, observed state and `nativeHttpObservations`.

Use the same managed entry point shown for delivery in the execution package,
substituting only one approved operation name. The exact package must include
these names and source hashes. They do not imply that broader network-path,
partial-provider-response or high-load criteria have passed: the managed
evidence must support the precise scoped assertion and its workload/recovery
correlation. No test monkeypatch or local certificate is shipped into managed
execution.

The relay's exact-host resolver hook alone cannot select an ephemeral port:
the installed AnyIO connector deliberately keeps its original `remote_port`.
The probe therefore also routes **only the same exact hostname/port** through
an AnyIO TCP-connector hook, restored in `finally`. HTTPcore still performs
its original-host TLS handshake. Upstream connects directly to the pre-resolved
numeric private address, avoiding recursion. Cleanup cancels owned accepted
streams before awaiting listener closure, so an interrupted TLS handshake
cannot leave the relay waiting on the provider's handshake timeout. Neither
hook is installed in the production API or receiver.


## Existing helper-job overlap and restoration

The command template reuses the idle `caj-m78p-a712b8c940-migration` job after
initial migration completion. The evidence job retains its API identity during
mixed load. The queue helper keeps the migration identity and temporarily
removes only the worker's direct SELECT on `document_processing_jobs` for
120 seconds. It captures the grant before mutation and restores it in finally;
actual worker SQLSTATE42501, unchanged effects and restored polling/readiness
remain separate native observations. Local PostgreSQL tests passed all four
owner/scope/grant-option/restoration cases; this is not managed acceptance.

The transport helper uses only the worker identity, dedicated delivery and
telemetry secret references, and the unchanged candidate image. The local
`helper_job_patch` constructor creates exact apply/restore PATCH bodies from
native captures, rejects identity unions and arbitrary overrides, and requires
0.5 CPU/1 GiB. Mutations occur only between terminal executions. Native job and
execution receipts bind source, image, role and actual execution ID. Restore
original configuration, template, registry identity and empty secrets, then
compare the full captured mutable state before the next helper operation.

Proposed additional overlap is bounded to **2,400 seconds aggregate, $0.036**;
only actual concurrency adds cost. Ten activity executions capped at120s plus
one queue helper capped at660s total1,860s, leaving540s for bounded recovery
and export. Retries consume the same aggregate allowance. Combined prepared
peak is3.75 CPU/7.5 GiB; no new job, identity, NSG, Firewall or VM is introduced.
The queue grant must be restored before changing helper identity. Exact native
Blob and Key Vault grants must be verified before claiming artifact export.

The actual worker-role delivery probes now bind production telemetry and flush
it on successful completion. The focused real-transport retry test observed
nine actual failed delivery attempts and three terminal emissions from three
existing events. Destination receipt/alert acceptance remains unproved until
independent native evidence arrives. Original standalone outbox service
metrics are still required; worker probe signals do not impersonate that
independent service.
