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
