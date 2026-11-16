# M78-D-001 bounded continuation package

Completed 2026-11-16 UTC under separate user spending approval. **M78-D-001 is
complete: 24/24 assertions accepted, including the six preserved upload assertions.**
All 19 cleanup residue counters are zero; controller preserved and ledger finalized.
Milestone 7.8 remains incomplete for its other existing requirements.
See the [completed continuation](#completed-continuation). The preparation scope
and commands below are retained for provenance; they do not authorize another run.

This package continues the [completed checkpoint](MILESTONE_7_8_MANAGED_OBJECT_STORAGE_EXECUTION_PACKAGE.md)
on `milestone-7-8-production-readiness-audit-local` at
`c67b69c13c1678bb14969f9aed73e9f5ac7d6322`. It implements the user's subsequent
timing decision recorded in the [scanner investigation](MILESTONE_7_8_SCANNER_GATE_DECISION.md).
The original campaign, failures, cleanup and ledger remain unchanged. PostgreSQL
acceptance remains closed. The five protected stashes remain preserved.

## Approved policy and exact change

Only new requests in this next proof receive a **900-second total decision
window**, measured from their recorded request time, and **20-second maximum
production bridge retry delay** (base delay 5 seconds). Existing request
deadlines and the application default of 300 seconds remain unchanged. Neither
the native source contract nor expiry rejection changes. Late rows remain
diagnostic evidence and cannot become accepted results.

The external probe adds a continuation mode that carries the six accepted upload
assertions as separately bound historical evidence. It creates one clean fixture
and one harmless standard EICAR fixture in the new campaign. Read-only preflight
uses the production native readers and correlator for both fixtures while both
remain `scan_pending`; it requires exact immutable version, URI/ETag, content
hash, request binding and expected verdict. It records source read times and
hashes without writing scanner acceptance or promoting anything.

Only after **both fixtures have matching native Blob tags and native Log
Analytics evidence before their actual deadlines** does the unchanged production
consumer run. That consumer independently reads, correlates and applies expiry
checks again. Clean promotion is part of that production admission. A preflight
pass alone is not acceptance. The probe records production `received_at`, request
and deadline timestamps. A missing, conflicting or expired result fails closed.
If the gate fails, capture diagnostics and clean up; do not initiate another pair.

The external probe orchestration changes; no production image input changes.
The retained image is reused without a build. The 1,000-second outer probe wait
is an orchestration bound, **not** an extension of any 900-second request deadline.

## Source, image and retained evidence bindings

| Binding                           | Exact value                                                               |
| --------------------------------- | ------------------------------------------------------------------------- |
| Probe source SHA-256              | `2faa6215a0228b2876d3d28bff2d15be749b39e3b49e56d554c0f069c20dd922`        |
| Bootstrap source SHA-256          | `e51c4e2295197f5eb01cac7addde7203f1d42a727789c7751e87f87a89905804`        |
| Retained OCI index/image          | `sha256:f498e5aa0f5e44dc7becc92868e1bb989372ef09a3f30d694e89d172eaa66b0a` |
| Runtime manifest                  | `sha256:241c55acd6e169546969b1c36f58806a146e3562f69011f5a3efc438a71eb769` |
| Canonical image inputs            | `d94e350754821b1172a9b4452466391053e0221d3095e336e43379f6f33c312f`        |
| Artifact source tree              | `2e4bccfe5e28df3e03775917dbc5b4ddc5f05c2f`                                |
| Artifact base commit              | `73425f40b35f9b3dc925c78905d69ef7e27404eb`                                |
| Retained image archive SHA-256    | `25d46785b855429dccdb7a6877976fb6874407a8ddab17ee8124a5c3c168e7c1`        |
| Accepted upload receipt SHA-256   | `dc061d35da32f266a4c7840b2c549bead7c0c6207bc2ad3795758c3a90cc168a`        |
| Original final journal SHA-256    | `2494048a0c735a47e03b56fd01d1d6e65000a9fec24004e29a6b899bfcc8fffe`        |
| Original terminal receipt SHA-256 | `674ea9a33476c4a59b80de35d8055da3709ef2c852654187e06cdc5ad3d87109`        |

Accepted upload contribution: `caj-m78o-0d00fe6932-probe-w6zxpn8`; successful
receipt export: `caj-m78o-0d00fe6932-probe-aipaqnl`. These are historical IDs,
not new campaign executions. New execution IDs must come from actual start
responses and terminal readbacks. No IDs or managed passes are predicted.

Private package: `.runtime/milestone_7_8/objects-continuation-20261116/`.
Its `package-review.json` contains the canonical package SHA-256, exact file
inventory, source/test bindings, protected stashes and validation receipts.
`continuation-manifest.json` binds the original normalized upload export and
original journal/terminal hashes. Secrets, operator IP, raw object keys, tenant
bindings, runtime bodies and provider receipts stay ignored outside Git.

## Resource scope and dependencies

One isolated Canada Central group, **`rg-m78-1c96397e49-target`**, campaign
`m78-object-1c96397e49c3`, using the existing managed object-storage template:
private Blob storage with versioning/soft deletion, Defender on-upload scanning
with a 1 GB monthly cap, native scan diagnostic logs, Log Analytics/AMPLS,
private endpoints/DNS/networking, temporary Premium ACR, one Consumption
environment, two 0.5-vCPU/1-GiB jobs, four identities and minimal PostgreSQL
(2 vCore, 64 GiB, no HA) solely for object transactions. Maximum one active
execution per job. No new PostgreSQL acceptance, Redis, telemetry, broad DR,
capacity campaign or Milestone 8 work.

Reuse the existing cleanup controller and unchanged published runbook. Renew
only its three deadline tags to the proposed cleanup-authority end, then grant
its two existing cleanup roles at the exact new target scope. Arm and read back
the exact schedule/binding before paid foundation provisioning. Preserve the
shared provider scanner and provider registration. Check Event Grid registration
before provisioning; register only if absent, then wait for actual registration.

Foundation and workload admission require actual successful deployments,
on-upload enabled with cap 1, native tag output, exact source system topic,
native diagnostic destination, private Blob/PostgreSQL/Monitor settings and
AMPLS private-only modes. An HTTP success with disabled scanning is insufficient.
Actual managed-identity IDs and workload parameters derive from verified
foundation outputs; they are not fabricated in advance.

Retained-image transfer permits only the privately recorded current operator
IPv4 `/32`, at most 20 minutes, with a transfer cutoff and restoration reserve.
Verify digest and restore the original disabled/default-deny registry network
in `finally`, including failure or uncertain push. No public Blob, PostgreSQL
or Log Analytics exception. If restoration cannot be confirmed within the
bound, stop proof and begin scoped cleanup; do not claim network restoration.

## Approved forecast, ceilings and time bounds

| Item                                            | Proposed bound                           |
| ----------------------------------------------- | ---------------------------------------- |
| Incremental forecast, including 25% contingency | **USD 47.8160**                          |
| New incremental ceiling                         | **USD 50.00**                            |
| Prior cumulative approved ceiling               | USD 270.89                               |
| Proposed cumulative ceiling                     | **USD 320.89**                           |
| Cumulative forecast, not settled charges        | USD 314.5951                             |
| Earliest paid start                             | Nov 15, 10:00 pm CST / Nov 16, 04:00 UTC |
| Latest provisioning start                       | Nov 16, 1:00 am CST / 07:00 UTC          |
| Stop new proof; scheduled cleanup               | Nov 16, 5:00 am CST / 11:00 UTC          |
| Existing runbook binding expiry                 | Nov 16, 6:00 am CST / 12:00 UTC          |
| Direct cleanup/recovery authority ends          | Nov 16, 7:00 am CST / 13:00 UTC          |

Maximum priced resource window is nine hours, including cleanup reserve. Costs
include both jobs for the full window, provider-managed network costs, private
endpoints/DNS, logs, ACR, PostgreSQL, Defender, storage and controller execution.
Five fresh public retail snapshots bind 27 meters and 17 forecast lines in
`cost-estimate.json` (SHA-256
`63142c3b4e6121b3306ad37989b9bcd7b411964ed1b41c8e40e56cdb14459bed`).
The estimate takes no credit for free grants, unused old allowances or posted
costs. **Billing remains unsettled.** Ceilings and forecasts are not charges.
Time/cap monitoring and cleanup bound the plan; Azure billing is not a real-time
hard spending switch. No start after the latest-start time without a newly
reviewed window. No work beyond the approved scope or ceilings.

## Approved execution order (retained package)

From the repository root, use the Azure CLI's bundled Python and private package:

```powershell
$m78Python = 'C:\Program Files\Microsoft SDKs\Azure\CLI2\python.exe'
$m78Package = '.runtime/milestone_7_8/objects-continuation-20261116'
& $m78Python "$m78Package/activate_controller.py"
& $m78Python "$m78Package/scanner_admission.py" provider
& $m78Python "$m78Package/arm_cleanup.py"
& $m78Python "$m78Package/deploy_foundation.py"
& $m78Python "$m78Package/scanner_admission.py" foundation
& $m78Python "$m78Package/transfer_retained_image.py"
& $m78Python "$m78Package/prepare_workload.py" --foundation "$m78Package/foundation-verified-response.json" --scanner "$m78Package/scanner-verified-response.json"
& $m78Python "$m78Package/deploy_workload.py"
& $m78Python "$m78Package/scanner_admission.py" workload
```

Execute commands individually and inspect each receipt. Do not paste them as
an unattended chain. At preparation, `execution-approval.json` did not exist. The user's subsequent
explicit approval created the authority record for package
`acf45345e4126adc2b4e08c6dab6e93bcd73db0ff15cfafb03ac220adc2d0a11`.
This execution is now closed; do not rerun the commands.
`command-manifest.json` contains exact underlying CLI arguments and body files.
Do not bypass wrapper admission checks by dispatching its low-level commands.

Start `bootstrap`, then `setup`, then `continue`, using this command form for
each phase and waiting for its actual terminal result before the next phase:

```powershell
& $m78Python "$m78Package/job_observation.py" start bootstrap --attempt 1
& $m78Python "$m78Package/job_observation.py" status bootstrap --attempt 1
& $m78Python "$m78Package/job_observation.py" logs bootstrap --attempt 1
```

Substitute `setup` and then `continue` for `bootstrap`. The continuation runs
the pair gate, production admission and the 18 remaining assertions in sequence;
a failure prevents later phases. Preserve each accepted phase and reconcile
uncertain operations before any retry. Focused recovery may resume unfinished
work within this same scope, budget and window; no new pair after gate failure,
no automatic replay and no repetition of successful phases.

The start guard reserves the observed job timeout plus 120 seconds for dispatch
inside the proof window. With the existing 4,200-second probe timeout, no new
probe execution starts after 09:48 UTC (3:48 am CST). This bounds a new dispatch;
it does not shorten existing request deadlines or authorize work after 11:00 UTC.

After a terminal proof result, run `receipts` with attempt `1` using the same
start/status/logs commands. Export the raw private journal before deletion when
time permits, including on gate failure:

```powershell
& $m78Python "$m78Package/private_journal_receipt.py" prepare
& $m78Python "$m78Package/job_observation.py" start receipts --attempt journal-1
& $m78Python "$m78Package/job_observation.py" status receipts --attempt journal-1
& $m78Python "$m78Package/job_observation.py" logs receipts --attempt journal-1
& $m78Python "$m78Package/private_journal_receipt.py" verify
& $m78Python "$m78Package/start_final_cleanup.py"
& $m78Python "$m78Package/poll_cleanup.py"
& $m78Python "$m78Package/verify_final_cleanup.py"
```

Poll existing IDs; never redispatch to solve a timeout. Cleanup does not depend
on successful proof or export. Its helper reconciles/stops exact active jobs,
adopts an existing matching cleanup job when present, records the provider's
managed infrastructure group before deletion, and verifies final absence.
If the runbook is failed or stuck, the prepared `start_final_cleanup.py --direct`
fallback reconciles that exact job and the target tags before deleting only this
target group, within the 13:00 UTC cleanup authority. It retains the runbook
failure as history; verification records the actual cleanup route rather than
claiming a failed runbook completed. The fallback must also reconcile an earlier
direct deletion before retrying it.
Use `verify_final_cleanup.py --direct` for that route. The fallback requires the
recorded or adopted exact cleanup job; final verification requires the saved
provider infrastructure-group attribution. Missing evidence remains a blocker
to declaring cleanup verified.

## Acceptance, cleanup and recovery checkpoint

The [per-assertion retained results](MILESTONE_7_8_SCANNER_GATE_DECISION.md#per-assertion-result-from-retained-managed-evidence)
remain authoritative until superseded by new accepted evidence:

- Preserve six accepted upload assertions and their original execution/source/image bindings.
- Prove five scanner/promotion assertions: clean and EICAR native dual-source
  decisions, exact clean promotion, infected denial and indeterminate denial.
- Then prove eight deletion/rollback assertions: concurrent lock behavior,
  rollback, authoritative absence, one deleted transition, replay no-op, read
  denial, exact soft-deleted retention and unchanged retained source.
- Then prove five recovery assertions: retained-version recovery, original
  version/ETag/bytes restored, API denial despite restored provider bytes,
  unchanged scan/promotion binding and repeat exact-version soft deletion.

Classify each as accepted, failed or unproved from actual managed evidence.
Local tests and cleanup are not substitutes. New scanner acceptance requires
both native sources and production admission inside each 900-second deadline.

Verify all **19 existing residue counters** are zero, including the provider's
managed infrastructure group. Check exact campaign custom-role GUIDs by
authoritative GET/404; scope-filtered role lists alone are insufficient. Remove
only surviving target-exclusive unassigned roles. Disarm the exact campaign
binding/schedule after deletion. Verify controller identity, Reader grant,
published runbook/content and shared scanner preserved. Physical erasure is
not claimed; application retention/recovery acceptance is separate.

`recovery-checkpoint.json` holds active operations, exact execution IDs, receipt
paths, accepted assertion counts, next action and deadlines. An uncertain write
must be reconciled with provider evidence before another dispatch. No second
campaign or wider retry allowance is implied. Finalize a new ledger/terminal
receipt without altering the prior ledger. After accepted evidence and verified
cleanup, update the existing checklist/defect register, inspect only outgoing
changes for private data, commit relevant corrections and sanitized documents,
normally push the existing branch and verify its remote commit under the user's
standing completion authorization. Do not declare all of Milestone 7.8 complete
unless its existing checklist supports that conclusion.

Focused preparation validation: 27 affected probe tests passed (22 new
continuation cases and five affected recovery cases), Ruff and diff checks
passed. Existing valid image, infrastructure and unchanged tests are reused.
Private helper validation and package/reference/hygiene results are bound in
`package-review.json`; no managed acceptance is claimed by those local checks.

## Completed continuation

Completed 2026-11-16 UTC. **M78-D-001 complete; 24 accepted, zero failed and
zero unproved assertions in the combined accepted proof.** Six upload assertions
come from the original immutable receipt; all 18 remaining assertions passed in
`caj-m78o-1c96397e49-probe-r8gokki`. No upload acceptance suite was repeated.

| Phase | Accepted assertions | Actual contributing execution |
| --- | ---: | --- |
| Preserved upload | 6 | `caj-m78o-0d00fe6932-probe-w6zxpn8` |
| Scanner/promotion | 5 | `caj-m78o-1c96397e49-probe-r8gokki` |
| Exact deletion/rollback | 8 | `caj-m78o-1c96397e49-probe-r8gokki` |
| Retention/recovery | 5 | `caj-m78o-1c96397e49-probe-r8gokki` |

Bootstrap `caj-m78o-1c96397e49-bootstrap-9iq2q9m` and setup
`caj-m78o-1c96397e49-probe-y0n6pau` succeeded. Successful public receipt export:
`caj-m78o-1c96397e49-probe-o2j3746`. Successful private journal export:
`caj-m78o-1c96397e49-probe-hwiwnq6`, 59 rows, five chunks, 143,639 raw bytes;
chunk completeness and full SHA-256 verified before deletion.

Both native evidence pairs were observed by **04:32:33.203439 UTC**, before either
request expired and before production consumption. The private journal verifies
the exact immutable versions, source evidence hashes, both pending quarantines
and absence of acceptance/promotion at the pair gate. Production consumption
independently revalidated native evidence and expiry.

| Fixture | Request UTC | Production decision UTC | Request to decision | Time remaining before expiry |
| --- | --- | --- | ---: | ---: |
| Clean | 04:21:18.838765 | 04:32:37.942322 | 679.103557 s | 220.896443 s |
| Harmless EICAR | 04:21:19.547990 | 04:32:48.963077 | 689.415087 s | 210.584913 s |

These results satisfy the explicitly approved **900-second total window and
20-second retry cap for new requests in this proof only**. They do not prove
300-second delivery or change the application default. Original 300-second
failures remain failures; their late rows remain diagnostic evidence.

The production path promoted exact clean bytes, denied infected and indeterminate
objects, proved concurrent lock exclusion and transaction rollback/reconciliation,
recorded exactly one deleted transition with replay as a no-op, and retained the
exact soft-deleted version. Recovery restored the original version/ETag/bytes
while API access remained denied and the original scan/promotion binding stayed
unchanged; the recovered version was soft-deleted again.

Cleanup job `67eaa7fd-f709-40d3-82d5-92cd624e662a` completed. All **19 existing
residue counters are zero**, including the provider-managed infrastructure group.
Exact campaign role GUIDs were reconciled by authoritative reads; the campaign
schedule/binding are absent. The reusable controller, identity, Reader grant,
published runbook/content and shared scanner are preserved. Ledger finalized.
No direct cleanup fallback was needed. This proves active resource absence, not
physical erasure; application retention/recovery proof is recorded separately.

The retained image was reused with **zero new builds**. Temporary exact-IP ACR
access lasted **68.63 seconds** before exact private-network restoration was
verified. Source/image/bootstrap bindings above remain the actual execution
bindings. The approved input snapshot is retained privately in `approved-inputs/`.

Three local control-path issues were preserved and corrected without replaying
managed proof: canonical UTF-8 versus CRLF export-source hashing (before export
dispatch), Windows receipt filename length (before cleanup dispatch), and the
bundled Python helper import path (before polling the existing cleanup job).
Their private correction receipts record affected checks and unchanged image/probe
bindings. The previous campaign's failed attempts, final receipts and ledger are
unchanged. Focused source/test review found no actionable issues; 27 affected
tests and scoped Ruff checks passed. Unchanged suites were not repeated.

| Saved evidence | SHA-256 |
| --- | --- |
| `final-results.json` | `f9a178ba95ee1d3a5a5e33370da6c93eaf4bada371f96954979d4ce23c1ab72e` |
| `terminal-receipt.json` | `b04b1d5abeeb78203a03059840b184d6d32cd069ca351b47671c91fc875f0b31` |
| `cleanup-verification.json` | `06690b44925eaa99a5d500ae9f44691bc142a49c0c151ebb98c64c0df92da70e` |
| `campaign-ledger.json` | `44fa084c765507c35a49df78f497f5b0670ed62931b338fe7616f0c67b384eac` |
| `final-journal.json` | `8bec8385576d6dc552cddfe5b856b6c42d60edb45a18fd8f8db8ee2058b9f770` |
| Accepted scanner phase | `5ea0a1298f3ed8722ae126db0938e43656280aa866616a92e8751eeb63363f8b` |
| Accepted deletion phase | `bcf0b517cf3b3355926815b82ae13c0cec81801954fd2e5e3f788bd49b0b30e3` |
| Accepted recovery phase | `ca72ef8361947ece4de80bf92d61ffa1853909cb927006859f755eba6e5be5ce` |

All evidence remains under the private continuation folder identified above;
`final-results.json` binds contributing executions, source/image identity, exact
per-assertion disposition and evidence-file hashes. Raw artifacts, credentials,
object keys and provider bindings remain outside Git. All five stashes are
preserved. **Billing remains unsettled:** forecast USD 47.8160, new approved
ceiling USD 50 and cumulative approved ceiling USD 320.89 are not settled charges.

No M78-D-001 requirement remains open. [Other existing Milestone 7.8 requirements](MILESTONE_7_IMPLEMENTATION_PLAN.md#78-completion-checklist-reconciliation--2026-11-15)
remain open; this result does not close Redis, telemetry, broader recovery,
capacity or final milestone validation. No next milestone is authorized.
