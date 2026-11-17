# Milestone 7.8 bounded pilot managed-validation package

> Current follow-up: the [full-closure local ledger](MILESTONE_7_8_FULL_CLOSURE_LEDGER.md)
> and [revised execution proposal](MILESTONE_7_8_FULL_CLOSURE_EXECUTION_PACKAGE.md) supersede
> this historical pilot preparation for the new candidate. Its evidence and
> limitations remain history; its proposed budget is not execution authority.
> Full7.8 remains incomplete, closed campaigns stay closed, billing is unsettled.

Prepared locally for separate spending approval. **No Azure operation, paid
provider call, managed execution or deployment has occurred under this package.**
PostgreSQL, M78-D-001 and M78-D-002 remain closed. Billing is unsettled. The
[release candidate](MILESTONE_7_8_PILOT_RELEASE_CANDIDATE.md) and
[cost model](MILESTONE_7_8_PILOT_COST_MODEL.md) provide artifact and pricing
bindings; neither is spending authority. The [exact command sequence](MILESTONE_7_8_PILOT_EXECUTION_COMMANDS.md) binds target `rg-m78-a712b8c940-target`, resource names, staged deployment, private payload transport, probe roles, interventions and cleanup. The [local preparation record](MILESTONE_7_8_PILOT_PREPARATION.md) separates passed local results from managed assertions.

The pilot keeps authenticated canvas editing, secure document upload,
extraction, private-clean retrieval, citation navigation and grounded AI. Its
controlled-draft AI result remains read-only by the user's explicit decision.
Historical editable-AI-node acceptance remains a separate full-milestone gap.
The pilot-specific scanner settings are 900 seconds for a total decision and
20 seconds for new-request retry. Native agreement on the exact object/version,
quarantine, upload-capability expiry and late-result rejection are unchanged.

## Existing criteria and assertion boundaries

The source criteria remain the
[remaining-evidence table](MILESTONE_7_8_REMAINING_EVIDENCE_RECONCILIATION.md#requirement-by-requirement-reconciliation)
and the [four affected restore assertions](MILESTONE_7_8_HISTORICAL_EVIDENCE_RECOVERY.md).
No successful PostgreSQL, scanner/object or Redis component campaign is repeated.

| Operation / existing criterion | Managed observation and acceptance condition | Existing evidence retained / limitation |
| --- | --- | --- |
| D003 transport, privacy and source binding; plan 1132–1133/1163, deployment 305–309, observability architecture 215–221 | Actual deployed API/worker logs, metrics and spans reach the private queryable destination with exact release/deployment/source, approved fields and native query receipts. Reject unauthenticated, wrong-source and forbidden-content batches. | Local exporter/redaction tests and D001 scanner rows remain credited. A labelled transport fixture proves transport only; it cannot substitute for a missing production signal producer. |
| D003 dashboards / alerts | Run each of the 13 existing dashboard query definitions; preserve missing versus healthy zero. Validate the 16 catalog rules, with external-outbox rule disabled for this pilot. Capture native Fired/Resolved alert records through the private Event Hub and correlate the exact rule, destination, event sequence and test window. | Generated KQL and a Bicep build are local preparation. Native rule validation, actual query evaluation, rendering, delivery and recovery remain unproved until execution. Manual evidence-integrity closure is not automatic remediation. |
| D003 destination failure, retention and authorization | Temporarily revoke only the gateway's exact DCR publisher grant, observe exporter failure/backpressure/loss/readiness, restore that exact grant and observe recovery. Independently query native retention and test export-only/read/operator-revocation boundaries. | Existing bounded retry/buffer behavior is reused. The adapter adds no second retry loop; ambiguous successful ingestion is reconciled by stable signal IDs and query deduplication. |
| D007 usable infrastructure categories | Query actual emitted configured categories for PostgreSQL, Blob, registry, Key Vault, Container Apps and other resources used by this package. Retain the category, resource ID, generated stimulus and returned native rows. | Scanner `StorageMalwareScanningResults` is already accepted. Historical Firewall/VM category gaps remain full-7.8 items if those resources are absent from this isolated pilot; do not provision them merely to fill a heading. |
| D004 actual worker polling / wake-up | A real authenticated upload creates durable intent; the separately deployed database-polling worker claims and processes it. Correlate durable job/heartbeat, native scanner admission, current private-clean index publication and operational worker observations. | Local claim/lease/trigger tests and managed PG/object/Redis successes remain accepted. The worker already calls the scanner bridge; no duplicate scanner process is added. |
| D004 enabled external acknowledgment | Use the configured real SMTP provider and an explicitly approved recipient. Retain native provider submission/delivery and the actual received message binding for the application's password-reset flow. | The standalone SMTP probe records submission only and explicitly leaves final delivery unaccepted. External domain-event/outbox delivery is not enabled for the pilot and remains a full-7.8 gap; no application broker is introduced. |
| D006 combined workload / limits | Bound authenticated canvas/document/retrieval/grounded-AI traffic by declared requests, documents/bytes, concurrency and provider tokens. Record measured latency/errors, rate-limit or other bounded rejection, worker/DB/queue state and post-load recovery. | Accepted component measurements are not replaced. New measurements support only their actual tested envelope; no safe invited-user count or public SLA is invented. |
| Real AI/embedding and deployed configuration | Use the selected real configured providers, current candidate digest and complete staging settings. Retain request/usage identifiers and safe response assertions, never prompts/documents/credentials in telemetry. | Deterministic local provider results remain local evidence. Provider identity, credential access and exact model entitlement must be supplied before a paid call. |
| D005 affected restore assertion 1 | Restore/migrate the relevant database boundary to 0029; verify immutable creation-request/result identities and no repeated canvas/node/edge effect. | Reuse historical 7.6 and accepted managed component recovery. Do not repeat all historical Stage 3 exercises. |
| D005 affected restore assertion 2 | On the restored target, verify exact ownership, runtime/negative privileges, Entra principals and sessions before unlocking application access. | Original-target role tests are not restored-target evidence. |
| D005 affected restore assertion 3 | Reconstruct nonterminal worker/deletion work, fence pre-restore leases/effects, reconcile provider absence/version state and demonstrate no repeated durable effect. | An unchanged row hash alone does not prove fencing or behavior. Preserve unproved assertions if the fixture/behavior observation is absent. |
| D005 affected restore assertion 4 | Jointly reconcile upload-session event identity, exact object/version/checksum, eight scanner-provenance fields, event/outbox/activity and index publication on the restored target. | D001 object-version recovery stays accepted. This checks the affected current-release cross-resource relationship only. |

## Implemented destination and infrastructure

The retained 7.7 telemetry gateway previously acknowledged a batch hash/count
without preserving its signal values. The candidate's explicit `azure_logs`
mode now validates the existing signal catalog and exact allowed source tuples,
fetches a short-lived managed-identity token for Azure Monitor, and forwards to
the exact DCR through verified HTTPS. It returns success only after native
204 acceptance. It logs batch metadata only. Native ingestion is at-least-once;
stable per-signal SHA-256 IDs support query-side deduplication after uncertainty.
Historical `receipt_only` mode is retained for its original fixture and supplies
no managed-destination acceptance.

The gateway's total outbound budget is 4.5 seconds, with no redirects,
environment proxy, fallback sink or destination retry. This package sets the
existing application exporter timeout to 5 seconds; its bounded upstream
retry/buffer controls remain the owner of retry. Wrong release/deployment,
uncataloged metrics, additional private fields, malformed spans and stale/future
signals fail before requesting a destination token.

`infra/milestone_7_8/pilot_observability.bicep` adds a private DCE/DCR to the
shared isolated Log Analytics workspace/AMPLS, five Analytics tables with
30/90/30/14/365-day application/security/metric/span/incident retention,
DCR-scoped gateway publish authority, separate operator/evidence read authority,
13 workbooks and catalog-derived scheduled query rules. The worker's scanner
query role is limited to the scanner-results table; it does not grant broad
read access to operational tables. Workspace settings disable public ingestion
and query, and enable immediate 30-day purge behavior.

Azure Monitor supports table Analytics retention down to four days, so the
existing 14-day span limit can be configured directly. The new table is created
with that retention; this does not claim an eight-hour run observes fourteen
days of physical deletion. [Microsoft retention documentation](https://learn.microsoft.com/en-us/azure/azure-monitor/logs/data-retention-configure).

Alert delivery uses a dedicated Standard Event Hubs namespace with one
throughput unit, one partition, a one-day buffer, no local authentication and
a private endpoint. Its trusted-service exception permits native Azure Monitor
delivery with the scoped action-group identity. The private evidence consumer
receives through Entra authentication and records native partition/sequence,
enqueued time, exact rule/target and Fired/Resolved data. This is operational
alert transport, not the application's domain-event bus. Event Hubs is the
Action Group type supporting Private Link; private ACA webhook delivery is not
silently assumed. [Microsoft Action Group documentation](https://learn.microsoft.com/en-us/azure/azure-monitor/alerts/action-groups).

The separate evidence tool uses eight hash-pinned universal Python wheels in
`infra/milestone_7_8/pilot/probe-requirements.txt`. Raw wheels remain private in
`.runtime/milestone_7_8/pilot-rc-20261116/package/probe-wheels-universal/`.
They are outside the API image. The source-bound execution loader verifies and
extracts them to its disposable overlay; the candidate contains no runtime pip.

## Commands and evidence export

These entry points exist; `prepare` and `--help` perform no Azure operation:

```powershell
$bundle = '.runtime/milestone_7_8/pilot-rc-20261116/package/prepared'
.venv/Scripts/python.exe -m infra.milestone_7_8.pilot_validation prepare `
  --bundle $bundle --release $release --deployment $deployment --ceiling 50
.venv/Scripts/python.exe -m infra.milestone_7_8.pilot_validation --help
```

Preparation writes a source-bound manifest and the exact 13-workbook/16-rule
catalog. Fill `$release` from the verified candidate source binding and
`$deployment` from the isolated resource-name suffix before producing the final
approval hash. It does not produce an approval record or claim live success.

After separate spending approval, each private job uses the actual platform
`CONTAINER_APP_JOB_EXECUTION_NAME`, its exact planned bindings and retained
native resource readbacks. For example, the destination gate is:

```sh
python -m infra.milestone_7_8.pilot_validation telemetry \
  --bundle /tmp/m78-proof/package \
  --authorization /tmp/m78-proof/approval.json \
  --bindings /tmp/m78-proof/bindings.json \
  --runtime-readbacks /tmp/m78-proof/native-resource-readbacks.json \
  --execution-id "$CONTAINER_APP_JOB_EXECUTION_NAME" \
  --output /tmp/m78-evidence/telemetry-attempt-01.json --execute
```

`query` additionally requires `--query-file` whose SHA-256 is in the approved
query list. It records actual HTTP status/native query results; a denied query
is not silently treated as a successful query. `alerts` receives at most 256
native events/128 KiB each for at most ten minutes and writes immutable native
event files. `smtp` requires the exact approved host/port/TLS/sender/recipient
binding and credentials from secret environment variables. It never labels
SMTP submission as received delivery. `telemetry` sends one small labelled
four-kind fixture, tests authentication/privacy rejection and polls for its
exact signal IDs for at most ten minutes. These bounded tools run only within
the larger proof deadline; repeating a successful or uncertain operation is not
their default behavior.

The separate `pilot_application_probe.py` prepares actual core/mixed-workload and
four affected restore observations under the same authorization helper. Its
accepted/failed/unproved result ledger must be reconciled with the destination,
native provider and cleanup records. Do not close a milestone item from a
transport fixture, source inspection or generated query alone.

Each attempt preserves an exclusive-create dispatch intent and result file.
An existing intent/result blocks an automatic repeat. Raw provider responses,
query results, application identifiers and native alert payloads stay in private
runtime evidence. Export through the exact isolated `operational-evidence`
container with a bound manifest of file paths, sizes and SHA-256 values; verify
the downloaded export before resource cleanup. Only sanitized references and
per-assertion conclusions belong in Git.

## Approval-relative window and binding

The temporary forecast is **$25.5678 USD**. The proposed incremental ceiling is **$50 USD**, cumulative approved ceiling
would become **$400.89 USD** if approved. Prior billing remains unsettled; this
does not assert settled charges or reuse previous allowances. The linked cost
model separates temporary validation from recurring hosting/provider costs.

The window begins when the approval is recorded: begin provisioning by **+2
hours**, stop new proof/scheduled cleanup at **+8 hours**, finish cleanup under
the separately scoped cleanup allowance by **+10 hours**. No future wall-clock
start is imposed. Store the derived absolute UTC deadlines in the controller
binding and recovery checkpoint before provisioning.

The authorization record schema is `m78-pilot-destination-probe-v1-approval`.
It binds `approved: true`, manifest file SHA-256, planned-bindings file SHA-256,
`approvedAt`, exact target resource-group ID and the enumerated operations.
The plan binds source/image digest, release/deployment, exact resource IDs and
workload/cost bounds. The source hash guard rejects changed files or catalogs,
unknown operations, different scopes and expired/future proof authority.

Provider-assigned FQDNs, customer IDs and DCR immutable IDs are admitted from
six exact native ARM GET records after deployment. They do not require another
routine approval: the approved plan already names the resource IDs and allowed
derivation. The admission helper checks request method/version, response 200,
exact IDs, internal environment/domain, matching application/gateway image,
verified ingress, private workspace/DCE and the exact DCR-to-workspace/endpoint
relationship. Arbitrary runtime URL overrides are rejected. Readback requests
are limited to the named workspace, DCR, DCE, API, gateway and environment.

## Bounded recovery and cleanup

Arm and read back the reusable controller before paid workload provisioning.
Preserve its identity, Reader grant and bootstrap history. Admit only this
isolated target group, declared attached grants, source/image bindings, ceiling
and +8/+10-hour deadlines. A live failure preserves evidence, reconciles the
exact operation/provider outcome, and resumes only an affected authorized
operation. Successful assertions remain accepted.

Cleanup includes native alert rules/action group, Event Hub/private endpoint,
DCE/DCR/AMPLS attachments, workspace, application/jobs, source/artifact blobs,
registry, network/DNS, Redis, primary/restored PostgreSQL servers, identities and
grants. Include the exact Key Vault soft-deleted vault purge resource ID under
`Microsoft.KeyVault/locations/eastus/deletedVaults/<bound-vault-name>` and the
specific purge permission in the spending/cleanup scope; deleting its resource
group alone does not prove that residue absent. Do not grant an unbounded vault
purge capability or purge any other vault. Preserve any applicable provider
soft-delete state explicitly in cleanup results.

Verify the planned residue counters, target-specific grants, expired
binding/schedule and controller preservation. Finalize the ledger only after
the evidence export and cleanup verification succeed. No new milestone,
website deployment or public ingress enablement follows automatically.

## Current local versus managed status

The new gateway adapter has 18 focused passing checks (including the retained
receipt-only gateway case), strict mypy for both changed script files and Ruff.
The isolated Event Hub consumer imports locally. The observability Bicep module
compiles. The package guard/catalog checks pass locally. These are affected
preparation checks, not reruns of closed acceptance campaigns.

No managed assertion in this package is yet accepted. Native KQL validation,
actual provider credentials/entitlement, exact operator/signing identity,
frontend artifact/hosting-origin binding, current restore observations and
cleanup remain gated by their concrete prepared inputs and separate authority.
Several catalog metrics currently have no production emission call site:
database pool/timeouts, storage/scanner operation metrics, indexer freshness/
drift, evidence-integrity findings, provider backup freshness, supported capacity
and forecast cost. A labelled synthetic metric can test destination rendering
and alert transport but cannot close the corresponding actual workload or
infrastructure observation. Collect real native/provider/application
observations where the runner supports them; otherwise leave the exact assertion
unproved. No healthy zero is manufactured for an absent producer.


## Explicit preparation limitations

The package is ready for the named identity, credential, frontend-origin and
spending decisions. It is not currently dispatchable: approval-relative
controller admission/readbacks, secrets, frontend digest and signed artifact
verification must be bound before paid execution. Local Bicep compilation is
not provider validation; installed CLI/help, schema and candidate imports do
not prove native operations succeed. No managed assertion is relabelled passed.

The 13 dashboard/16 alert definitions are preserved, with external outbox alert
disabled only for the declared pilot restriction. Actual producer gaps and
Firewall/VM categories absent from this isolated topology remain full-7.8
requirements. There is no claim that running the tools alone closes all of D003,
D004, D005, D006 or D007. Each resulting assertion requires its native result,
source/image/execution binding and verified cleanup.

The new diagnostic category bindings follow Microsoft’s [registry reference](https://learn.microsoft.com/azure/container-registry/monitor-container-registry-reference),
[Blob reference](https://learn.microsoft.com/en-us/azure/storage/blobs/monitor-blob-storage-reference),
[PostgreSQL logging](https://learn.microsoft.com/en-us/azure/postgresql/monitor/concepts-logging),
and [Key Vault logging](https://learn.microsoft.com/en-us/azure/key-vault/general/logging).
These sources describe supported categories; they are not campaign receipts.
