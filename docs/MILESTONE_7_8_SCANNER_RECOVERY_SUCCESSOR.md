# Milestone 7.8 scanner recovery proposal

The signup successor accepted both synthetic signups in
`caj-m78p-a712b8c940-evidence-sjnkddp`. The private API returned its expected
readiness response before signup. Native bootstrap/migration, the private VPN
route and creation of both corrected alert rules were also verified. Cleanup job
`14b2901a-7754-4ebf-a04a-15536e109124` completed with all 48 residue counters
at zero and the reusable controller preserved. Those results and the earlier
unknown signup remain in the [regional execution record](MILESTONE_7_8_REGIONAL_REPLACEMENT.md#signup-recovery-execution-result).
PostgreSQL, D001 and D002 remain closed. Milestone 7.8 remains incomplete.

## Scanner evidence

| Question | Successful D001 continuation | Signup successor |
| --- | --- | --- |
| Decision policy and path | Retained workload binding uses private pull, 900 seconds and a 5â€“20 second retry range. The private journal shows both native sources matched the exact clean and harmless test versions before production consumption. | The signed release's worker template uses private pull, 900 seconds, the same retry cap, and the default 5-second base. Foundation deployment returned the worker user-assigned identity. The observed worker was polling and emitting scanner metrics. |
| Blob read | The D001 worker used scoped quarantine Blob property and tag reads. | The retained native quarantine role contains both actions. There is no worker-side property or tag receipt for this version. |
| Log Analytics read | The D001 worker had Log Analytics Reader. The clean decision took 679.10 seconds, and the harmless test decision took 689.42 seconds. | The native pilot role has workspace read and table-specific query for `StorageMalwareScanningResults`; app/security telemetry is excluded. An operator query returned the exact Defender clean row. No worker-specific Log Analytics response was recorded. |
| End-to-end result | D001 remains accepted. | Core execution `caj-m78p-a712b8c940-evidence-dtwpway` stopped when its probe treated the production quarantine `409 documents_not_ready` as unexpected. Follow-up observed the original upload pending at 892.6 seconds. The native destination recorded 43 worker `mobius.scanner.unavailable` signals. No in-window matching pair or clean promotion was accepted. |

The worker combines native read errors into a single metric. The Defender row
proves that the operator could read that row. It does not resolve worker
authorization, private DNS/transport, Blob tag availability or parsing. The
narrow Log Analytics role is a documented difference, not an established cause.
The worker diagnostic uses the signed release's existing readers and
correlator in the exact ready worker revision. It reads the original upload
and scan request in a read-only database transaction, checks that both readers
use the deployed worker identity and checks each source even if the other
fails. It records fixed error codes, a provider status when available, bounded
row counts, and the original correlation outcome. It exports no raw rows,
object paths, credentials or tokens. Post-expiry observations are diagnostic
only and cannot publish a result or change the first decision clock.

Private evidence is in `.runtime/milestone_7_8/objects-continuation-20261116/`
and `.runtime/milestone_7_8/full-closure-prerequisites/run-719a34d3/`. The most
relevant files are the D001 `final-journal.json` and `workload-bindings.json`,
and the pilot `proof-core/last-in-bounds-upload-observation.json`,
`proof-core/native-defender-exact-version-observation.json`,
`proof-core/native-scan-bridge-metric-readback.json`, `activation/application-terminal.json`,
and `retained-native-cleanup-bindings/{role-2,scanner-query-role}.json`.
The replacement package binds their hashes to a private retained-evidence index.

## Operator decision rules

1. Require exact native schedule and cleanup binding readback, successful
   signed-image deployment and private readiness before proof. New isolated
   database fixtures are setup for this run. Preserve both historical accepted
   signups as evidence.
2. Core verifies the exact quarantine response. If the exact immutable upload
   times out while still pending or with the terminal timeout outcome, retain
   its receipt and hold retrieval, index, capacity and recovery checks that
   need the clean core fixture. Keep the same deployment. Run the read-only
   worker diagnosis and independent native destination readiness on actual
   API and worker rows. An unresolved diagnostic read is an unproved scanner
   branch, while the initial native resource and identity bindings must pass.
3. Permit one repair only if the deployed worker's read demonstrates a
   Log Analytics authorization failure and native readback confirms absence
   of the original exact worker-to-workspace scanner-table assignment. Restore
   only that deterministic assignment using the existing custom role.
   The plan verifies role actions, exact scope, principal and resulting native
   assignment, then reads both sources again under the same worker identity.
   The operator requires the exact role readback and a matching Log Analytics
   row under the worker identity before allowing one fresh upload on the
   same fixture. The fresh upload has its own exact deadline, capped at 900
   seconds, and must pass both native sources through the production worker.
   Completed core steps are carried forward, with no further scanner retry.
   An already-present grant, a Blob-only or correlation error, or an
   inconclusive read leaves dependent checks held. Widening roles, changing
   peers/public access or replacing images requires separate review.
4. Finish core and destination readiness by +3h to run the existing dependent
   timetable. If a verified scanner hold remains, mark its dependent stages
   skipped at their original deadlines. Run independent observations within
   the original proof window. Keep each downstream acceptance duration intact.
5. Stop immediately and reconcile cleanup for a missing +2h infrastructure
   or private readiness gate, a missed +3h gate without a verified scanner
   hold, unsafe bindings, an unreconciled mutation, lost cleanup protection,
   exhausted approved limits, a privacy/integrity failure or a user stop.
   At +11h stop new proof and reconcile the armed Automation schedule without
   issuing a duplicate cleanup job. The existing exact-scope operator fallback
   is available after Automation expires at +12h. Complete the exact vault
   purge, tenant/VPN and credential disposition and verify all 48 counters by
   +13h. Preserve the reusable controller.

## Replacement boundaries

The isolated target, Canada Central services, private East US HA Balanced B0
Redis, VPN/private DNS and existing scoped fault interventions are unchanged.
Reuse all prior release endorsements and the signed API and frontend indexes.
The scanner repair uses the existing workspace role-assignment permission.
No new role definition, identity, infrastructure or public access is proposed.
The reserve for one additional HTTP attempt sequence is 160 requests within
the existing 1,800-request partition. Total limits remain 10,000 HTTP requests,
200 model attempts including retries, 160M embedding tokens, three Gmail
messages to the approved inbox and at most 20 minutes of exact-IP ACR access.

Keep the actual approval timestamp. Start at the first whole UTC minute strictly
after that timestamp. Infrastructure/private API readiness is due at +2h, core
and destination readiness at +3h, proof stop and scheduled cleanup at +11h,
Automation binding expiry at +12h and verified cleanup at +13h.

The retained 13-hour rate model forecasts **$40.8177**, or **$51.0221** with
its 25% contingency. The prior attempt occupied the target for 1h 53m 59s
from approved start to verified group absence. Two full hours at the retained
$1.404874 peak hourly rate and $7.652255 of fixed allowances produce a
conservative **$10.462003** estimate of additional unsettled exposure. Reserve
**$11** for it and retain the earlier **$31** reserve. The proposed
**$56.51** execution ceiling plus **$42** prior exposure reserve is **$98.51**
combined and **$449.40** cumulative, **$11** above the last approved cumulative
ceiling. This replaces the previous execution allowance. The prior **$0.878883**
posted amount spans reused resource IDs and overlaps the reserve. The latest
scoped cost query was throttled. Billing remains **unsettled**.

The review package and its execution instructions are private. Live admission,
the worker diagnostic and any corrective write remain unproved by local
rehearsal. A new Gmail credential is deferred to execution preparation after
the package is reviewed.

## Approved execution result

The successor ran on November 18, 2026 UTC under review
`814f87aea2d9ac5a72cf9c60ac55826d85771b294a188305e7650b8c4cbbf8aa` and
source `8ffc7f5ca971db100e5a40cfcd49b5a595c4bc3f`. Native schedule and
binding readbacks passed before workload provisioning. Both signed indexes
matched in the registry, and the exact-IP exception was closed. Bootstrap
`caj-m78p-a712b8c940-bootstrap-s6s2p8w`, migration
`caj-m78p-a712b8c940-migration-8prh1dj`, application activation, and the exact
creation readback for both corrected alert rules passed. The approved private
route, DNS and TLS passed. Private API readiness returned HTTP 200 at
18:25:39 UTC, before the initial synthetic signup POST. Both synthetic
accounts were accepted in `caj-m78p-a712b8c940-evidence-w724v3i`. During
setup, a changed consumed Entra input blocked activation before dispatch.
Restoring the original bytes passed complete revalidation without recreating
the native user or repeating the foundation.

### Stop and recovery disposition

The independent destination query first hit the local CLI ban on line breaks
before query dispatch. The operator preserved that receipt and submitted the
same read-only KQL on one line. The native query returned 16 worker rows
(14 metrics and two application logs) and zero API rows.

The [destination rule](../infra/milestone_7_8/pilot/core_proof_operator.py)
raises `CampaignError("destination privacy or integrity failure")` if the
native `SignalId` cannot be reproduced from the returned row or repeats an
already-seen ID. A reconstruction mismatch triggered the rule at
18:29:16 UTC. The [operator exception handler](../infra/milestone_7_8/pilot/core_proof_operator.py)
recorded `unreconciled-operation` and invoked cleanup. Offline replay
reproduced 13 IDs with the existing UTC timestamp normalization and the
remaining three after restoring an integral metric value from integer to
float. The native response had erased that JSON distinction, which the signed
gateway's canonical hash preserves. This explains the validator failure.
Destination readiness remains unproved because the read supplied no API rows.

The in-place path admits an exact terminal, exported
`scanner-paused` receipt for the unchanged deployment. A fresh upload also
requires verification of the approved scanner grant correction. The
destination ID failure met neither condition. Azure confirmed core execution
`caj-m78p-a712b8c940-evidence-6392297` stopped at 18:31:42 UTC. Its local
watcher encountered the already-written hard-failure marker after observing
the stop. The run produced no accepted scanner decision, and the prior
900-second result stays in the record. No second scanner upload or test
email was dispatched.

### Verified cleanup

Azure Automation rejected the first cleanup dispatch with HTTP 429 because
the free subscription's monthly job execution time quota was exhausted.
Native reconciliation found no new cleanup job. Under the user's separate
cleanup-only timing approval, the existing fallback verified the exact
subscription, executor, and campaign ownership before requesting deletion
of `rg-m78-a712b8c940-target`. Azure confirmed group absence at 19:08:38 UTC.
The named Canada Central vault purge was verified at 19:09:03 UTC. The
operator disarmed only this campaign's binding and schedule, leaving the
reusable controller intact.

All 48 cleanup counters were zero at 19:09:37 UTC, including the six
campaign-scoped custom roles. The temporary directory objects and VPN client
profile were removed, and the owner confirmed the restricted window was
closed and the temporary Gmail app password revoked. The bound operator
ledger is `cleanup-disarmed`. Billing remains unsettled. The $56.51 execution
ceiling and $449.40 cumulative ceiling describe approved bounds.

Private evidence stays in
`.runtime/milestone_7_8/full-closure-prerequisites/run-814f87ae/`.

| Receipt | SHA-256 |
| --- | --- |
| `proof-account/accepted.json` | `e743b71375b063d0950f182c518417bfafadfaaaa17d65a0d6839fc7bdde159d` |
| `destination-readiness/production-rows-00.native.json` | `12152fe04820075f815a5f01be90e3947411683091a9e1f1ac54bfaec6784ee4` |
| `destination-signalid-offline-diagnostic.json` | `c496dbd36975634be54a6a80eaaa43316bcb516673659b53fd00c71ceababccb` |
| `core-hard-stop/terminal.json` | `6de579097d559498bed4eb2d07f5b735b9c30131593d8d45e204dcc64604e75b` |
| `azure-cleanup-terminal.json` | `443629c1cba9a290d3d2e1869a031d475bdb2dcfcb87399b18b15945a2cf1071` |
| `early-named-vault/terminal.json` | `4d4e6fdf5e680ba2ec8d65a197b2664f6047ae9f6a0e1c6247ed965e6aea2b1c` |
| `verified-full-residue.json` | `ff01d643969c676bedd05d32b973a679dada942861ce3dd2477b0f01847a02da` |

Milestone 7.8 remains incomplete. PostgreSQL, D001, and D002 remain closed.

## Local destination and cleanup rehearsal

The readiness gate and final destination validator share the signed gateway's
SHA-256 reconstruction. When Azure returns an integer for an integral float,
the verifier tries the float representation only for a metric's numeric
`Payload.value` inside the IEEE-754 safe integer range. The complete digest
must still match. The existing source, privacy, schema, time window,
deduplication, and API-plus-worker requirements still apply. The readiness
query uses one line so it passes the existing Windows CLI argument check.

The retained native receipt from the approved run replayed with 16 of 16
matching IDs. The gate returned `destination-readiness-unproved` because the
receipt has zero API rows. A local two-source fixture passed the same gate.
Changed content, wrong sources, and duplicate IDs still entered the
hard-stop path in local checks.

The existing `pilot_cleanup fallback-plan --execute` command also accepts
`--quota-approval <private receipt>` for the early cleanup-only path. Use it
after a separate timing approval for the exact review and target. The
receipt binds `approved`, `approvedAt`, `reviewPackageSha256`,
`targetResourceGroup`, `automationBinding`, `cleanupDeadlineUtc`,
`stopProofSha256`, and `quotaResponseSha256`. Keep it in the private
`run-<review hash prefix>` directory. The operator checks the exact native
runbook dispatch and monthly execution-quota rejection, the original
deadline, current subscription and executor, and target ownership. It
requires a complete native job inventory before deletion. An earlier delete
intent requires reconciliation before another dispatch. Ordinary fallback
still starts at Automation expiry.

The local rehearsal substituted a fake Azure transport and replayed the
actual quota, subscription, ownership and job-inventory receipts. It admitted
one exact simulated deletion. Focused tests covered the normal expiry path,
unrelated throttling, missing consent, altered receipts, wrong scope or
executor, active or newly observed jobs, a paginated read, and an uncertain
delete. Private rehearsal receipt `.runtime/milestone_7_8/sq4/rehearsal.json`
has SHA-256
`7430c856a72674b111ed31505e69e8fea0d633f82240376a2323b0d137ad3ab6`.

## API telemetry emission and destination hold

The first `POST /api/v1/auth/signup` in the accepted account execution started
at 18:27:12.047320 UTC on November 18 and returned HTTP 201 at
18:27:12.577661 UTC. The versioned account export binds both step receipts.
The API was on the ready revision `ca-m78p-a712b8c940-api--yq7t2cf` with two
replicas and the signed API image listed above. The request journal does not
identify the serving replica or retain the response `traceparent`.

| Point in the path | API | Worker |
| --- | --- | --- |
| Source binding | Native revision template shows `mobius-api`, app mode `staging`, release `rc-dd3f882613d8`, and deployment `m78p-a712b8c940`. | All 16 verified native rows carry `mobius-worker` and the same environment, release, and deployment. The shared deployed template sets its exporter the same way. |
| Production emission | [API middleware](../apps/api/opencanvas_api/main.py) emits `api.request.completed`, request count and duration, and a sampled span, then calls `schedule_flush()`. The native API template does not override the default 64-signal batch size. The prior API lifespan had no time-based flush while serving. | The [worker polling loop](../apps/api/opencanvas_api/services/jobs.py) repeatedly emits queue metrics and state changes and schedules exports. Its admitted rows also include database and capacity measurements. |
| Export and destination | Native templates show the enabled HTTPS exporter, TLS verification, a five-second attempt timeout, and the vault-backed auth reference. The private gateway allows the exact API tuple and forwards validated rows through the DCR to Log Analytics. The receipts contain no API replica buffer observation or API-to-gateway response for this request. | The gateway allows the exact worker tuple. The worker rows establish that the private path through the gateway and workspace worked for that source in this window. |
| Query | The 18:29:16.736093 UTC read covers the request's timestamp. It starts at 17:15:00 UTC and filters the shared release, deployment and both service names. Each service has its own 16-row limit after deduplication. The native read found zero API rows. | It returned 16 worker rows timestamped 18:29:03.269036–18:29:05.380538 UTC. All 16 retain credit under full SignalId validation. |

The earliest demonstrated defect is at the API buffer-to-export boundary.
A quiet API replica can hold completion rows indefinitely below 64 signals,
while the worker crosses that threshold by polling. A local single-request
test timed out before any export while the API was still running. The receipts
do not show whether either managed API replica reached the threshold, whether
it obtained a gateway response, or whether its rows arrived after the last
query. They therefore support a concrete batching defect and leave the
historical attribution open.

The API now schedules a bounded partial flush every five seconds while
serving. Full batches still flush on demand. The timer shares the existing
single in-flight export, buffer bounds, retries, timeout and shutdown drain.
The private API console records the trace ID and gateway response status for
the newest liveness completion in a batch. It carries no payload, header or
credential. The local regression sends one HTTP request through the actual
middleware and exporter and validates the exported rows using the gateway's
schema, source and digest code. A mocked gateway returns 503 and then 202
under the existing retry policy. Both results correlate to the exact trace.

The operator saves `destination-readiness/unproved.json` after verified
worker-only evidence and binds it to the native receipt hash, destination
plan, window and deployment. At the core cutoff it revalidates that evidence
and native cleanup protection before returning
`destination-dependent-checks-held-independent-checks-may-continue`. An
independent core action remained admissible in the same deployment within
its original cutoff in the local test. A read-only follow-up timeout preserves
the last verified worker sample. A corrupt row takes `unreconciled-operation`
and an altered saved receipt takes `privacy-or-integrity-failure`; both
exercise the existing early cleanup dispatch with a fake subprocess.
`scheduled-proof-stop` still takes precedence at the cutoff and uses the
existing schedule. The replay of all 16 native rows is recorded privately in
`.runtime/milestone_7_8/destination-emission-rehearsal.json`, SHA-256
`e8a7c0b3a55e797a07073d9c9c506f16a4873c52acbd54c53d190ee8eebba5c8`.

### Proposed managed check for separate approval

Use the existing private Canada Central foundation and East US HA Redis
dependency with the preserved controller. Bind the corrected API candidate,
source and new endorsements before approval. The API and HTTP exporter
source changes affect the canonical API build inputs. Keep the retained
frontend artifact and its endorsements, the two accepted signups, the
historical worker rows, and the 48 verified cleanup counters. For the live
check use one private `GET /api/v1/health/live` and a fresh worker poll as the
control. The proposed check needs no signup, file upload, provider call,
fault injection, restore, or email.

1. Verify the approved private route and native API and gateway revision,
   runtime bindings, and cleanup protection. Capture the liveness HTTP
   status, UTC interval and server-returned `traceparent`. Read the private
   console for the serving API replica's exact `api.request.completed` and
   `telemetry_liveness_delivery` for that trace. Retain only the bounded
   trace, source fields and delivery status in the proof.
2. For at most 20 minutes and within the core cutoff, use at most 12
   read-only workspace queries. Look in `MobiusApplication_CL` for
   `Name == "api.request.completed"` and an exact
   `tostring(todynamic(Payload).trace_id)` match. Compare time, all four
   source fields and the complete SignalId under the existing validator.
   Reuse the production query for the worker control. Keep duplicate and
   privacy checks in force. A trace match under different bindings is
   diagnostic evidence of a routing or configuration mismatch.
3. Missing emission leaves the request-to-emitter boundary unproved. An
   emission without a delivery witness leaves replica scheduling or
   transport unproved. A delivery witness without an HTTP status narrows
   the gap to the attempted transport. A 401/413/422 records rejection at
   the HTTP hop. A 503 records unavailability at that hop; use native
   gateway evidence to distinguish ingress and destination failures. A 202 with the gateway in
   Azure Logs mode proves the gateway received a 204 from the DCR. If the
   bound row then remains absent, retain the first-seen time or last
   negative query to narrow the gap to delivery after acknowledgment, query
   visibility or filtering. Credit the API only when the exact row validates.

The retained full-foundation price model gives a conservative scope estimate
of **$40.8177** through the outer cleanup bound and **$51.0221** with its 25%
contingency. The proposed replacement execution ceiling is **$56.51**. Target
absence took under two hours in the latest attempt. Two hours at the retained
peak rate plus fixed allowances estimates **$10.462003** in unsettled exposure.
Reserve **$11** on top of the prior **$42** reserve. That yields a proposed
**$460.40 cumulative ceiling**, replacing the old execution allowance.
The historical posted target aggregate spans multiple runs. Billing remains
unsettled.

Use the first whole UTC minute strictly after the separate approval. The
private services are due by +2h, and the targeted result is due by +3h.
Request early cleanup once the check concludes. Scheduled cleanup still
triggers at +11h, Automation expires at +12h, and operator verification is
due at +13h. Before paid provisioning, require native schedule and exact
binding readback and resolve the recorded Automation quota blocker. If
Automation rejects an early cleanup dispatch with the same monthly-quota
429 and native inventory confirms no job, use the existing exact-target
fallback only with its separate timed approval. Verify all 48 counters,
the named vault purge and campaign disarm while preserving the controller.
This is a proposal pending a fresh signed API candidate and separate
execution and cleanup approval. The password reset flow is outside its scope.

The signed release artifacts and prior 48 zero-residue observations were
reused. The offline checks add no managed acceptance or Azure spending.
