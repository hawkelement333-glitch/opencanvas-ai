# Milestone 7.8 managed object-storage execution package

Current status: [M78-D-001 is complete](MILESTONE_7_8_MANAGED_OBJECT_STORAGE_CONTINUATION_PACKAGE.md#completed-continuation), with 24/24 assertions
accepted and all 19 continuation cleanup counters zero. Milestone 7.8 remains
incomplete for its other existing requirements; billing remains unsettled.

Historical disposition of the original 300-second campaign follows:

Status: the approved campaign preserved **6 of 24 accepted managed assertions**.
M78-D-001 remains **open**: timely dual-source scanner evidence was not obtained;
18 scanner, promotion, deletion and recovery assertions remain unproved. Cleanup
is verified: all 19 object-campaign residue counters are zero. This record does not reopen completed PostgreSQL acceptance.

## Requirement and reused proof

- [Implementation plan](MILESTONE_7_IMPLEMENTATION_PLAN.md): the managed
  object-storage/scanner checkbox and existing object-lifecycle, retention,
  recovery and failed-transaction scenarios.
- [Defect register](MILESTONE_7_8_DEFECT_REGISTER.md): M78-D-001 and the
  already-corrected M78-OS-001 exact-version deletion executor.
- [Prior progress handoff](MILESTONE_7_8_PRE_EXPIRY_MAXIMUM_SAFE_PROGRESS_HANDOFF.md):
  the local object audit, transaction rollback and concurrent-worker correction.
- [Object ingestion runbook](OBJECT_INGESTION_RUNBOOK.md): trusted upload,
  quarantine, current exact-version scanner evidence, promotion and deletion
  gates. The current bridge pulls private Blob tags and Log Analytics evidence;
  the older Event Grid bridge description is historical.

The previous local object tests remain valid. Only new execution-package and
probe behavior receives focused local checks. The PostgreSQL campaign's five
accepted checks, 38 assertions, 14 zero-residue counters, preserved controller
and finalized ledger remain closed.

The retained Linux/amd64 API image was admitted against the unchanged canonical
inputs at the recorded checkpoint:

| Binding                 | Value                                                                     |
| ----------------------- | ------------------------------------------------------------------------- |
| Repository checkpoint   | `73425f40b35f9b3dc925c78905d69ef7e27404eb`                                |
| Image build source      | `2f3f67ef7e2fec69856a5618e1e548c433bf2ed9`                                |
| Canonical input SHA-256 | `e9adf645cf1973dbf7d73ad99f3231af6fa4323670027e9965d18bc7e6dc1263`        |
| Retained image          | `sha256:c5cc6222656cdd097053c1278c9bf487963118d87d43638fab161b94106c7fde` |
| Linux runtime manifest  | `sha256:5257bc79abf3431e6a869a0442c4e25016aebba3685d6a66f10e7b356a9ad28c` |

The new probe and bootstrap sources are injected with independently verified
SHA-256 bindings. They are outside the Docker build inputs. Artifact source,
operator checkpoint, external source hashes and actual managed execution IDs
remain separate evidence fields. The managed run subsequently exposed missing
key-column UPDATE grants required by PostgreSQL row locks on immutable upload,
scan and deletion requests. The provisioning-SQL correction was separately bound
and applied externally; it did not change the running application behavior or
claim that the retained image contains the corrected grant generator. Its original
build provenance remains intact. A later demonstrated completion-event identity
collision required one corrected image, containing both production corrections:

| Corrected artifact binding | Value                                                                     |
| -------------------------- | ------------------------------------------------------------------------- |
| Source kind                | Exact Git tree snapshot; not a pre-completion commit                      |
| Source tree                | `2e4bccfe5e28df3e03775917dbc5b4ddc5f05c2f`                                |
| Canonical input SHA-256    | `d94e350754821b1172a9b4452466391053e0221d3095e336e43379f6f33c312f`        |
| Image index                | `sha256:f498e5aa0f5e44dc7becc92868e1bb989372ef09a3f30d694e89d172eaa66b0a` |
| Linux runtime manifest     | `sha256:241c55acd6e169546969b1c36f58806a146e3562f69011f5a3efc438a71eb769` |

The exact archive, labels, installed source, non-root Linux/amd64 runtime and
composition were verified. Scout reported zero high/critical findings. The
registry manifest was read back and the original private configuration restored.
Both exact-IP transfer windows totaled 96.60 seconds, below the approved
20-minute bound. The real Git index, branch history and all five stashes were
preserved during snapshot preparation and the build.

## Exact scope

Campaign `m78-object-0d00fe693263` uses the isolated Canada Central target
`rg-m78-0d00fe6932-target`. The private parameter files bind the existing
subscription and tenant; their identifiers are not published here.

The [deployment template](../infra/milestone_7_8/managed_objects.bicep) prepares:

- One private Standard LRS storage account, versioning and seven-day soft
  deletion, with quarantine, clean, rejected and retained containers.
- Account-scoped Defender on-upload scanning, a 1 GB monthly scan cap,
  private scan-result logging and the exact provider-managed scanner exception.
- One private Log Analytics workspace and AMPLS, three private endpoints,
  seven private DNS zones and the isolated virtual network.
- A temporary Premium ACR, one internal Consumption environment and two manual
  jobs using the retained image. Bootstrap and proof jobs use 0.5 vCPU/1 GiB.
- Four distinct managed identities for bootstrap, API storage operations,
  worker storage operations and isolated proof/recovery operations. Container
  grants exclude scanner-tag writes; API identities cannot delete or write clean
  objects. The normal worker performs exact-version deletion.
- One private PostgreSQL 17, two-vCore, non-HA, 64 GiB dependency for the existing
  application schema, row locks and rollback observations. This is object-lifecycle
  fixture setup, not another PostgreSQL acceptance campaign.

The existing reusable Automation controller is preserved. Its three matching
deadline tags are renewed to `2026-11-16T06:00:00Z`. Only its target-group cleanup
grants, campaign schedule and binding are added. The shared provider-managed
StorageDataScanner and unrelated resources are preserved.

## Prepared operations and boundaries

The concrete private package is
`.runtime/milestone_7_8/objects-20261115/`. Its original
`command-manifest.json` preserves the approved CLI arguments, ARM URLs, body-file
references and operation prerequisites as history. Later operation receipts and
source-bound full job templates record reconciled corrections; the original
manifest is not an instruction to replay stale bindings. Cleanup uses
`cleanup-job-body-v3.json` and its verified replacement binding. `controller-renewal-plan.json` binds
the three exact tag updates. `foundation.parameters.json`, the source-bound
workload parameters, registry network bodies and cleanup bodies supply the
deployment inputs. No file in this directory is staged in Git.

1. Record approval for this scope, allowance and window. Verify the existing
   controller renewal using its retained executor and readback validators.
   Verify the `Microsoft.EventGrid` prerequisite for Defender's automatic
   storage-bound system topic. This is separate from the historical Event Grid
   result-delivery bridge; current results still use private tags and logs.
2. Create the exact target group and its two controller cleanup grants. Arm and
   read back the one-time schedule, job binding, authority hash and target tags
   before any paid deployment.
3. Deploy the foundation. Reconcile its actual deployment state and output
   identities before a retry. Bind the exact provider scanner and bootstrap
   identity from those readbacks. Require successful scanner operation status,
   on-upload scanning enabled with cap 1, Blob index tags, and its storage-bound
   system topic. ARM deployment success alone does not establish these settings.
4. Transfer the retained image to the new ACR. Temporarily allow only the
   prepared operator IPv4 `/32`, with default-deny networking and no admin
   credentials. Limit this opening to 20 minutes; restore the original disabled
   network configuration in all outcomes and verify it before job execution.
5. Deploy the source-bound jobs. Run the existing guarded schema migrations and
   isolated fixture bootstrap. Record the returned execution IDs and completion
   states. Execute `setup`, then `all` for `upload`, `scan`, `delete` and
   `recovery` in dependency order within one execution. This preserves the
   existing 300-second scanner deadline without inter-job startup delays.
6. Capture accepted observation receipts before deleting the database. Preserve
   accepted phases and failed attempts. Reconcile uncertain provider operations
   against exact immutable versions and deployment/execution IDs before retrying
   only the affected operation.
7. Stop active jobs, run cleanup on completion or a stop condition, and verify
   absence. Remove only surviving campaign custom role definitions and the exact
   campaign binding/schedule. Preserve the reusable controller and shared scanner.

There is no arbitrary attempt limit. Azure job automatic retries are disabled
so uncertain operations can be reconciled before an explicit resume. Work is
bounded by scope, time and cumulative cost.

## Existing managed acceptance requirements

| Existing requirement                   | Managed observation                                                                                                                                                                                                             |
| -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Upload and object authorization        | Scoped upload capability; foreign workspace and forged capability denial; real API clean-container write denial; pending reads fenced.                                                                                          |
| Checksums and exact versions           | Substituted-byte rejection; exact quarantine and promoted version/ETag/checksum bindings; exact downloaded synthetic bytes.                                                                                                     |
| Quarantine and scanner decisions       | Actual Defender clean and EICAR decisions matched through private tags and Log Analytics; infected and indeterminate objects remain unreadable and unpromoted.                                                                  |
| Clean promotion                        | Current clean result promotes only its immutable source; target bytes and provenance match.                                                                                                                                     |
| Exact deletion, retention and recovery | Worker deletes only the requested version; retained source remains unchanged; deleted version remains recoverable; exact restored version, ETag and bytes verified, then deleted again.                                         |
| Failed transaction and concurrency     | A real provider deletion followed by injected lost response rolls back the database; exact absence reconciles on retry; one terminal transition; concurrent worker skips the locked request; replay performs no extra deletion. |

These observations must be accepted with actual execution IDs and hashes, then
cleanup verified, before M78-D-001 is marked complete. A successful local test
or deployment alone does not close it. The existing 300-second scanner decision
deadline is retained; waiting for delayed Log Analytics delivery does not extend
the accepted scan decision time.

## Approved allowance and execution window

The user approved the exact package SHA-256
`d3e19cfecf7812e13f19e2d97bc12a1aa37dbc493013b100c1a077a0facc3000`,
including scoped corrections and resumption within these ceilings and deadlines.
Original approved bytes and subsequent correction receipts remain private.

Prices were captured from Azure's public retail API on 2026-11-15. Private
`cost-estimate.json` records the quantities, rates and source snapshots. The
estimate reserves nine resource-hours, full-month allowances for storage,
Defender and DNS where conservative, 3 GB of logs including quota overshoot,
and 25% contingency. It does not rely on free grants or trial credits.

| Amount, USD                       | Status   |
| --------------------------------- | -------- |
| Incremental forecast              | 45.8955  |
| Approved new incremental ceiling  | 50.00    |
| Prior cumulative forecast         | 220.8836 |
| Prior cumulative approved ceiling | 220.89   |
| Cumulative forecast               | 266.7791 |
| Approved cumulative ceiling       | 270.89   |

Provisioning may begin only after approval and no later than
`2026-11-15T23:00:00Z`. New proof operations stop by
`2026-11-16T04:00:00Z` (22:00 CST on November 15). The independent cleanup
schedule fires at that deadline; cleanup/reconciliation authority expires at
`2026-11-16T06:00:00Z` (midnight CST). Cleanup begins earlier on completion or
when the remaining allowance cannot cover the cleanup reserve. The budget is an
authorization ceiling, not an Azure hard billing cutoff.

The unchanged cleanup runbook requires its binding expiry to equal the cleanup
deadline plus one hour. The active binding therefore expires at
`2026-11-16T05:00:00Z`; direct scoped cleanup/reconciliation authority continues
through `06:00:00Z`. The corrected binding and target tags were read back before
proof execution. Earlier mismatched binding attempts remain recorded as history.

Billing remains **unsettled**. Prior partial posted charges of
USD 9.82392726097545 are mixed historical observations, not settled campaign
charges or a fresh allowance. They are not subtracted from cumulative reserves.
The completed PostgreSQL budget is not reused.

## Recovery checkpoint and completion record

### Preserved execution history

- The first foundation deployment completed all 67 resource operations but
  failed its output expression. A read-only existing-resource deployment
  reconciled the result; the explicit-scope output correction reused the resources.
- Bootstrap `caj-m78o-0d00fe6932-bootstrap-9p5vkkt` succeeded once. Fixture
  executions `caj-m78o-0d00fe6932-probe-0vv29jm` and
  `caj-m78o-0d00fe6932-probe-f3aqjpk` failed because the existing canvas trigger
  had already created the collaboration resource. The corrected fixture reused
  those trigger-created records; `caj-m78o-0d00fe6932-probe-0jcjl0w` succeeded.
- Proof `caj-m78o-0d00fe6932-probe-drxd2fp` exposed missing request-row locking
  privileges. Diagnostic `caj-m78o-0d00fe6932-probe-35r8mmp` confirmed all three
  affected tables. Correction `caj-m78o-0d00fe6932-bootstrap-ksp3nx4` verified six
  immutability guards, granted only three key-column privileges and verified
  that table-wide UPDATE remained denied. Migrations were not rerun.
- Proof `caj-m78o-0d00fe6932-probe-ckxrn9t` preserved an accepted clean upload,
  then exposed a completion-event identity collision on the next upload.
  Completion event identities now include their upload session. Focused tests
  reproduced the failure and verified separate events and historical replay.
- Scanner preservation `caj-m78o-0d00fe6932-probe-54vpnqa` did not obtain an
  accepted result within its bounded window. Read-only diagnostic
  `caj-m78o-0d00fe6932-probe-bzmsi7h` found empty tags and no log rows. The actual
  HTTP 201 partial-success response identified an unregistered Event Grid
  provider. Registering that prerequisite and retrying only scanner enablement
  returned HTTP 200 / `Succeeded`; readback verified the cap, scanning and topic.
- Read-only inspections preserved expired upload identities, exact provider
  versions and journal hashes before explicit replacement fixtures. Accepted
  authorization evidence was reused; neither capability nor scan deadlines
  were extended. Failed requests and prior results remain in private receipts.

Microsoft documents partial success for this configuration API; the captured
provider response established the specific cause in this campaign.
[Defender for Storage REST contract](https://learn.microsoft.com/en-us/rest/api/defenderforcloud/defender-for-storage/create?view=rest-defenderforcloud-2025-06-01)

### Accepted results and exact remaining proof

The accepted upload phase contributes exactly six assertions:

- `cross-workspace-denied`
- `forged-capability-denied`
- `checksum-substitution-denied`
- `exact-quarantine-version-bytes`
- `pending-read-denied`
- `api-clean-write-denied-403`

Contributing execution `caj-m78o-0d00fe6932-probe-w6zxpn8` committed the accepted
upload phase before its scanner attempt was stopped after deadline reconciliation.
Successful read-only export `caj-m78o-0d00fe6932-probe-aipaqnl` recovered that
accepted phase without repeating assertions. Its canonical private phase receipt
SHA-256 is `dc061d35da32f266a4c7840b2c549bead7c0c6207bc2ad3795758c3a90cc168a`.
The phase binds probe source
`224d517f93baef21b2d75bd581c69fcb2a40fae1fa87a74f897c435da44f0200`
and corrected image index `f498e5aa0f5e44dc7becc92868e1bb989372ef09a3f30d694e89d172eaa66b0a`.
Its clean-upload substep retains the earlier contributing `ckxrn9t` execution
and original image/source binding in the journal; it is not relabeled as newly
executed by the export job.

Two admitted scanner cycles failed the unchanged 300-second decision contract:

| Attempt                | Actual execution                    | Observed Log Analytics delay after scan | Outcome                                                                        |
| ---------------------- | ----------------------------------- | --------------------------------------- | ------------------------------------------------------------------------------ |
| First admitted pair    | `caj-m78o-0d00fe6932-probe-w6zxpn8` | Clean 514.20 s; EICAR 514.74 s          | No accepted scanner result; stopped after deadline and database reconciliation |
| Warm scanner-only pair | `caj-m78o-0d00fe6932-probe-8kguopt` | Clean 483.85 s; EICAR 444.25 s          | Failed `managed-scan-windows-closed-without-results`                           |

Read-only diagnostics `caj-m78o-0d00fe6932-probe-3g42q7t` and
`caj-m78o-0d00fe6932-probe-14axd94` preserved the provider completion and ingestion
timestamps. The exact object URI and normalized ETag match the clean request;
late provider decisions do not constitute accepted application scanner results.
Both warm requests had zero accepted scanner-result rows after their deadlines.
The final probe source is
`c79d03385f60a62c3fa015fb736ded42e6ad404a8963e84a1323fb00c7502adb`.

Azure documents resource-log delivery commonly taking three to ten minutes.
There is no identified setting in the existing private tags-and-logs bridge that
makes these observed deliveries satisfy its five-minute acceptance contract.
The campaign did not extend deadlines, accept tags alone, substitute historical
Event Grid transport, or repeat unchanged attempts without an identified fix.
[Azure Monitor ingestion timing](https://learn.microsoft.com/en-us/azure/azure-monitor/logs/data-ingestion-time)

The exact outstanding assertions in the existing prepared inventory are:

| Phase                     | Unproved assertions                                                                                                                                                                                                                            |
| ------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Scanner and promotion (5) | `defender-dual-source-clean`; `defender-dual-source-eicar`; `clean-promotion-exact-bytes`; `infected-no-promotion-no-read`; `indeterminate-no-promotion-no-read`                                                                               |
| Deletion and rollback (8) | `concurrent-skip-locked`; `failed-transaction-rollback`; `authoritative-absence-reconciled`; `exactly-one-deleted-transition`; `delete-replay-noop`; `deleted-read-denied`; `soft-deleted-exact-version-retained`; `retained-source-unchanged` |
| Recovery (5)              | `retained-version-recovered`; `original-version-etag-bytes-restored`; `restored-provider-bytes-remain-api-denied`; `original-scan-promotion-binding-unchanged`; `recovered-version-soft-deleted-again`                                         |

Deletion and recovery depend on accepted scanning and clean promotion. Their
local tests remain valid, but no managed pass is claimed. Campaign resource
cleanup does not prove application exact-version deletion, retention or recovery.
M78-D-001 and Milestone 7.8 remain incomplete.

### Retained evidence and cleanup

Final read-only journal export `caj-m78o-0d00fe6932-probe-8dkpvwb` succeeded.
`private-journal-final.json` preserves 15 accepted/failed/substep rows, complete
private version identities and prior source/image bindings. Its SHA-256 is
`2494048a0c735a47e03b56fd01d1d6e65000a9fec24004e29a6b899bfcc8fffe`.
The export source SHA-256 is
`99b4290bf68c459f0b0396cfcd055771a62ec352b42c0cc643d283fb6c978afd`.
The accepted upload receipt hash was independently recomputed from that export.
All proof executions were verified terminal before cleanup was dispatched.

Cleanup job `907e04e3-bede-4474-a050-98610b374b31` completed. Independent
readback verified the target group and the automatically managed Container Apps
infrastructure group absent. All 19 object-campaign residue counters are zero,
including target resources, five exact custom-role IDs, target role assignments,
and the campaign cleanup binding/schedule. The five role definitions were read
by exact subscription-level GUID, avoiding scope-filtered list omissions. All
five were already absent after resource-group deletion; no separate role-definition
deletion was needed. The reusable controller's group, account, identity,
Reader grant, published runbook and renewed deadline tags were preserved, as
was the shared scanner. The completed PostgreSQL campaign's separate 14 counters
remain unchanged.

The ledger is finalized with partial proof and a verified cleanup disposition.
Private `recovery-checkpoint.json` records no active managed executions or
cleanup operation. Resource absence does not assert physical erasure or satisfy
the unproved application deletion, retention and recovery scenarios.

| Private evidence file       | SHA-256                                                            |
| --------------------------- | ------------------------------------------------------------------ |
| `final-results.json`        | `07f852b9fbeac01c7e5b1051aea2b04a0601afe14fd814536b12815404d53aef` |
| `terminal-receipt.json`     | `674ea9a33476c4a59b80de35d8055da3709ef2c852654187e06cdc5ad3d87109` |
| `cleanup-verification.json` | `e27fb1a572c06750c374da812d43829d576bb425f2ca6d5e6639781bd791b38c` |
| `campaign-ledger.json`      | `049da724e0f1c9d804ba74d0c987bdde1a70142e4990317ea290b966a0392778` |

Raw evidence, credentials, full object keys and runtime parameter files remain
ignored outside Git. Billing remains **unsettled**; forecasts and approved
ceilings are not settled charges. The five protected stashes and unrelated work
are preserved.

## Read-only scanner continuation decision - 2026-11-15

The [scanner gate investigation and decision](MILESTONE_7_8_SCANNER_GATE_DECISION.md)
traces all four retained rows to exact fixtures and distinguishes the failed
300-second dual-source gates from downstream unproved assertions. No new
managed assertion was accepted. It proposes an explicit 900-second timing
amendment for new requests; the existing 300-second requirement stays in force
until approved. This proposal does not modify the finalized campaign receipts,
ledger, cleanup disposition, or unsettled billing.

### Subsequent timing approval and bounded package

The user approved 900 seconds total and a 20-second retry cap for new requests
in the next managed proof only. The [continuation package](MILESTONE_7_8_MANAGED_OBJECT_STORAGE_CONTINUATION_PACKAGE.md)
was separately approved and executed. Its [completed continuation](MILESTONE_7_8_MANAGED_OBJECT_STORAGE_CONTINUATION_PACKAGE.md#completed-continuation)
accepted the 18 remaining assertions and verified all 19 cleanup counters zero,
preserving the six upload assertions and original 300-second failures. M78-D-001
is complete; Milestone 7.8 remains incomplete. The retained image was reused;
billing remains unsettled.
