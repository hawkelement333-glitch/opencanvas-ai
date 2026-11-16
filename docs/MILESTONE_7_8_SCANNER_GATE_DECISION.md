# M78-D-001 scanner gate decision

Date: 2026-11-15 (America/Chicago). Current status: **900-second/20-second
policy amendment approved and executed for new requests in this proof only;
M78-D-001 complete with 24/24 accepted assertions and verified cleanup**.
The original 300-second failures remain failures.

The user subsequently approved a 900-second total decision window and a
20-second retry cap for new requests in the next M78-D-001 proof. Objects remain
quarantined until both native sources agree on the exact object/version; expiry
rejection and the six accepted upload assertions remain intact. The
[bounded continuation package](MILESTONE_7_8_MANAGED_OBJECT_STORAGE_CONTINUATION_PACKAGE.md)
implemented this decision without changing production image inputs. The
[completed continuation](MILESTONE_7_8_MANAGED_OBJECT_STORAGE_CONTINUATION_PACKAGE.md#completed-continuation) accepted all 18 remaining assertions
and verified 19 cleanup counters zero. The investigation and proposal below are
retained as the historical record preceding that approval.

Baseline: `c67b69c13c1678bb14969f9aed73e9f5ac7d6322` on
`milestone-7-8-production-readiness-audit-local`.
The [completed execution checkpoint](MILESTONE_7_8_MANAGED_OBJECT_STORAGE_EXECUTION_PACKAGE.md)
remains immutable evidence: six accepted upload assertions, verified cleanup,
finalized ledger and unsettled billing. PostgreSQL acceptance remains closed.
This investigation made no Azure calls, provisioned nothing, rebuilt no image
and reran no unchanged test suite.

## Finding and attribution

No supported configuration change was identified that makes the existing
private Blob-tags-plus-native-Log-Analytics evidence path satisfy the
300-second gate in these failed observations. An unchanged live retry would
not demonstrate a correction. This does not claim every future delivery must
exceed 300 seconds.

The four native log rows were independently matched to the retained fixtures by
exact object URI and normalized ETag; prior receipt hashes and all evidence-file
hashes bound by `final-results.json` were verified. The accepted upload receipt
hash was recomputed and unchanged. Request start times below are derived from
the saved immutable deadlines minus the recorded 300-second timeout.

| Cycle / fixture | Request to scan completion | Scan completion to native log ingestion | Ingestion after deadline |
| --------------- | -------------------------- | --------------------------------------- | ------------------------ |
| first / clean   | 0.769 s                    | 514.20 s                                | 214.97 s                 |
| first / EICAR   | 1.433 s                    | 514.74 s                                | 216.18 s                 |
| warm / clean    | 0.735 s                    | 483.85 s                                | 184.58 s                 |
| warm / EICAR    | 0.986 s                    | 444.25 s                                | 145.23 s                 |

`TimeGenerated` follows `ScanFinishedTimeUtc` by only 25-47 microseconds in these
rows. The measured delay therefore lies after scan/result generation and before
native log ingestion. The retained first clean-tag read succeeded at 16:44:15 CST,
inside its deadline, while the matching log query still returned no rows. That
establishes tag availability by that observation, not the exact tag-write time.

The receipts do not retain `_TimeReceived`. Consequently they cannot separate
Defender export/batching, service transport and Azure Monitor processing into
individual durations. `ingestion_time()` is an approximate ingestion timestamp.
No claim is made that AMPLS, private DNS, the scanner engine or a specific Azure
queue caused the whole delay. The first pair sharing one ingestion timestamp is
consistent with batching, but does not identify where batching occurred.

Azure documents resource-log delivery commonly taking 3-10 minutes and explains
how `_TimeReceived` separates receipt from ingestion. A later approved run should
retain that field if supplied, alongside query-start/end and both source-read
observation times; missing instrumentation must not be invented.
[Azure Monitor ingestion timing](https://learn.microsoft.com/en-us/azure/azure-monitor/logs/data-ingestion-time)

Actual contributing and diagnostic executions:

- First admitted pair: `caj-m78o-0d00fe6932-probe-w6zxpn8`.
- First late-log diagnostic: `caj-m78o-0d00fe6932-probe-3g42q7t`.
- Warm pair: `caj-m78o-0d00fe6932-probe-8kguopt`.
- Warm final diagnostic: `caj-m78o-0d00fe6932-probe-14axd94`.
- Accepted upload export: `caj-m78o-0d00fe6932-probe-aipaqnl`.

## Supported transport choices

| Path                                                                                          | Fit with the current contract                                                                                                                        | Required decision                                                             |
| --------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| Versioned Blob tags + native `StorageMalwareScanningResults`, queried privately through AMPLS | Preserves both current sources and network boundary; no documented setting supplies this category within 300 seconds reliably                        | Explicit timing amendment is the smallest identified change                   |
| Defender result custom Event Grid topic + downstream consumer                                 | Documented near-real-time route, but requires same-region custom topic accepting public-IP access; private-endpoint-only topics are unsupported      | Approve both a second-source contract change and a public-ingress exception   |
| Event Grid to queue/Event Hubs/Service Bus, privately polled by worker                        | Private consumer access does not make the producer/delivery leg private-only; managed-identity delivery uses public-IP space on Microsoft's backbone | Additional network exceptions, identities, delivery adapter and cleanup scope |
| Diagnostic results exported to Event Hubs or storage                                          | General diagnostic destinations exist; no retained proof or documented category-specific bound establishes a 300-second correction                   | New evidence-source/transport decision and validation; not a ready fix        |
| Tags alone, copied tags injected into logs, or security alerts                                | Tags alone/copies do not supply independent native corroboration; malicious-only alerts do not cover clean decisions                                 | Does not meet this gate                                                       |

Sources: [Defender result destinations](https://learn.microsoft.com/en-us/azure/defender-for-cloud/advanced-configurations-for-malware-scanning),
[Defender result topic restrictions and event schema](https://learn.microsoft.com/en-us/azure/defender-for-cloud/defender-for-storage-configure-malware-scan),
[Event Grid managed-identity delivery](https://learn.microsoft.com/en-us/azure/event-grid/deliver-events-using-managed-identity),
[diagnostic destinations](https://learn.microsoft.com/en-us/azure/azure-monitor/data-collection/diagnostic-settings),
[Event Grid delivery and retry](https://learn.microsoft.com/en-us/azure/event-grid/delivery-and-retry).
Near-real-time delivery is not a five-minute guarantee.

The current executable bridge is explicitly private tags plus AMPLS pull:
`infra/milestone_7_7/modules/scanner-result-bridge.bicep:318` reports no custom
result topic, subscription or queue. Historical Event Grid design prose does
not supply an existing supported implementation. The automatic system topic
that triggers scanning is separate from the custom topic for result delivery.

A transport change would require an authenticated result reader; strict
publisher/topic/event-type/schema allowlists; duplicate, conflict and replay
handling; bounded retries and dead-letter behavior; and new provenance fields
and validators. The documented event includes URI and ETag but does not give a
provider-version-ID field in its example. Its association with the exact stored
immutable version, pinned tag read, content hash and scan request must therefore
be proved. It cannot be inserted into a field claiming native Log Analytics
provenance. Application changes would change image inputs and justify a build
only after implementation and focused validation.

## Smallest proposed decision (historical proposal before approval)

**Approve a 900-second end-to-end scan-decision deadline for new requests in the
next M78-D-001 managed proof, with a 20-second maximum bridge retry delay.**
This explicitly amends the five-minute acceptance policy for that execution;
a future pass would prove the amended 900-second contract, not the original
300-second contract. The repository default remains 300. Until explicit approval,
the current 300-second requirement remains in force.

Proposed deployment bindings, not applied:

```text
OPENCANVAS_MALWARE_SCAN_TIMEOUT_SECONDS=900
OPENCANVAS_SCANNER_RESULT_BRIDGE_RETRY_BASE_SECONDS=5
OPENCANVAS_SCANNER_RESULT_BRIDGE_RETRY_MAX_SECONDS=20
OPENCANVAS_OBJECT_PROBE_SCAN_SECONDS=1000
```

The 900-second bound gives headroom beyond the observed 444-515-second log delay
and the documented 3-10-minute range, including querying and two fixture
admissions. The outer 1000-second probe bound cannot extend either request's
900-second deadline. This is a proposed latency tradeoff, not a delivery SLA or
an accepted observation. It permits a longer quarantine wait, including a scan
that itself finishes later than 300 seconds; it does not split scanning and
evidence arrival into separate clocks.

The current bridge defaults to exponential retries capped at 300 seconds.
Reducing that cap helps discovery after ingestion, but cannot correct provider
arrival after the original deadline. Both existing sources, private access,
exact version/ETag/content/correlation binding, disagreement rejection and
final wall-clock admission checks remain mandatory. Objects remain unreadable,
unpromoted and unavailable to parsing/retrieval/models/Indexer until both
sources agree and the production service accepts the result before deadline.
Missing or conflicting evidence at expiry remains a failure. Old requests and
old late evidence remain closed and diagnostic; their deadlines are not edited.

The existing implementation supports this through configuration:

- `apps/api/opencanvas_api/core/config.py:163`: timeout default 300, range 30-3600;
  retry settings at lines 182-183.
- `apps/api/opencanvas_api/services/object_ingestion.py:1331`: copies timeout and
  deadline into a new immutable request; line 1498 rejects late admission;
  lines 1952-2003 implement fail-closed expiry.
- `apps/api/opencanvas_api/services/scanner_bridge.py:739`: only open requests
  are consumed; lines 624-684 correlate both sources and exact bindings;
  lines 1006-1029 query the native table.

The corrected retained image can be reused:
`sha256:f498e5aa0f5e44dc7becc92868e1bb989372ef09a3f30d694e89d172eaa66b0a`,
canonical build inputs
`d94e350754821b1172a9b4452466391053e0221d3095e336e43379f6f33c312f`.
Environment bindings and the injected probe are outside the canonical image
inputs. No runtime default or production validator is changed by this proposal.

## Execution package work after the policy decision

Before any spend, the one bounded package must bind the approved policy, exact
commands and resource scope, retained image/source/config hashes, new incremental
and cumulative ceilings, actual start/proof/cleanup deadlines, and the reusable
controller's fresh authority. Prior authorization is not a fresh allowance.
Prior cumulative approved ceiling is USD 270.89; cumulative forecast is
USD 266.7791. Both remain distinct from **unsettled billing**. This read-only
investigation requests no new allowance or live window.

The first live proof is one fresh clean object and one harmless EICAR test
fixture. Preserve the six accepted upload assertions by receipt; setup/new
fixture creation must not be counted as re-executing those assertions.

One focused external-probe change is needed for the requested ordering:
`managed_object_probe.py:1164` currently invokes the consumer while waiting for
both fixtures, and production clean admission promotes immediately
(`object_ingestion.py:1530`). The new pair preflight must first correlate native
Blob and Log Analytics evidence for **both** fresh requests while their actual
deadlines are open, with no accepted-result writes or promotion. Only then
invoke the unchanged production consumer, which rechecks evidence and deadlines.
The same approved package may then continue promotion, deletion/rollback and
recovery. If the gate fails, preserve receipts and perform verified cleanup.
This probe change is outside image inputs and is not implemented before the
policy decision.

Reuse existing tests for correlation, private DNS, immutable version binding,
late-result rejection, pending-read denial and expiry. Focus new local coverage
on the approved timeout boundary and pair-before-promotion ordering. No full
repository audit or unchanged managed retry is justified by this investigation.

## Per-assertion result from retained managed evidence

Historical result for the original 300-second campaign: **6/24 accepted**.
The finer classification below marks the two
timely dual-source gates **failed**, because both managed pairs lacked accepted
results at deadline. Their later provider rows do not turn them into passes.
The remaining 16 assertions are **unproved**. This refines the earlier aggregate
18-unproved description without changing original receipts or the ledger.

| Assertion                                   | Result   |
| ------------------------------------------- | -------- |
| `cross-workspace-denied`                    | accepted |
| `forged-capability-denied`                  | accepted |
| `checksum-substitution-denied`              | accepted |
| `exact-quarantine-version-bytes`            | accepted |
| `pending-read-denied`                       | accepted |
| `api-clean-write-denied-403`                | accepted |
| `defender-dual-source-clean`                | failed   |
| `defender-dual-source-eicar`                | failed   |
| `clean-promotion-exact-bytes`               | unproved |
| `infected-no-promotion-no-read`             | unproved |
| `indeterminate-no-promotion-no-read`        | unproved |
| `concurrent-skip-locked`                    | unproved |
| `failed-transaction-rollback`               | unproved |
| `authoritative-absence-reconciled`          | unproved |
| `exactly-one-deleted-transition`            | unproved |
| `delete-replay-noop`                        | unproved |
| `deleted-read-denied`                       | unproved |
| `soft-deleted-exact-version-retained`       | unproved |
| `retained-source-unchanged`                 | unproved |
| `retained-version-recovered`                | unproved |
| `original-version-etag-bytes-restored`      | unproved |
| `restored-provider-bytes-remain-api-denied` | unproved |
| `original-scan-promotion-binding-unchanged` | unproved |
| `recovered-version-soft-deleted-again`      | unproved |

## Local verification and recovery record

The offline reconciliation verified the original terminal/journal hashes, the
bound final evidence-file hashes, all four exact URI/normalized-ETag joins,
original late-row bindings, the unchanged accepted upload hash, and timestamp
ordering. It executed no cloud client. Existing test receipts were reused;
source inspection is not presented as a new managed pass.

Private investigation artifacts remain ignored under
`.runtime/milestone_7_8/scanner-investigation-20261115/`:
`analyze_retained_timing.py`, `timing-analysis.json` and the recovery checkpoint.
`timing-analysis.json` SHA-256:
`b156af67e1354ecc648700e07265233610ff229bd358d639f270a53a89b01b0f`.

At the end of the original investigation, the next action was to obtain the
timing or transport decision and prepare a bounded package. The timing decision
was approved and the separately funded continuation completed. Its
[24/24 accepted result and verified cleanup](MILESTONE_7_8_MANAGED_OBJECT_STORAGE_CONTINUATION_PACKAGE.md#completed-continuation) close M78-D-001.
No active campaign operation or further execution is authorized. Both campaign
ledgers and failed-attempt histories remain preserved; billing is unsettled.
