# Milestone 7.8 telemetry-first shared run

**Local preparation. The release scan blocks signing and spending approval.**
The next run combines the telemetry check with the compatible remaining proof
in one private deployment. All historical receipts retain their original
source, image, execution and acceptance bindings. PostgreSQL, D001 and D002
remain closed.

## API candidate and scan gate

The corrected API was built once from commit
`aacf8c566818006b4218deb62e75d9ea6e0a9383`, source tree
`c1d0bb1b919c3f74cdee7f96c3ac2bc744ce6579`, canonical input SHA-256
`eda2ed0cb8ac349c1684cfeccfa72f9cd31ac9a7fff5169c353f1d5b59e7159e`.
The Linux/amd64 OCI index is
`sha256:e0e6518e8f54c6151e598c6b591923dfade3e35c7b10a18dc0fc38bc22cc3c62`.
The runtime manifest is
`sha256:125d7594df891bd1bdbc5cfa36006084ab2913a17c313ce5fc740507d1adfb91`.
The non-root, read-only, network-none runtime check verified the installed API
source and minimal runtime. The OCI/SBOM check verified all 20 blobs, 14 layer
diff IDs, 44 Python distributions and 87 Debian packages.

The exact image's Docker Scout scan reported **0 Critical and 6 High**,
all in Debian OpenSSL `3.5.7-1~deb13u3`. They are CVE-2026-107496,
CVE-2026-124709, CVE-2026-88823, CVE-2026-95692, CVE-2026-107493, and
CVE-2026-95691. The signed Debian Trixie/security indexes list the installed
version as the current candidate. Debian reports all six open in both Trixie
and Bookworm security builds. A rebuild with the same inputs cannot remedy
this. Retain the failed scan and unsigned candidate in
`.runtime/milestone_7_8/a6/`. The published-project links and exact private
receipts are bounded to the scan. [Debian OpenSSL security tracker](https://security-tracker.debian.org/tracker/source-package/openssl)

The signed frontend index
`sha256:1ee742b604d406ad8cc4c3c53001853ad58a033b68f4d613251ea7fc088fdb3a`
keeps its locally reverified provenance and release-binding signatures
under the approved key. The earlier combined endorsement remains historical.
When a supported fix becomes available, verify the replacement's exact
installed package and scan, then sign its provenance, release binding and
new combined endorsement using the same encrypted key and key-only policy.
The key passphrase is entered locally at that point. No Gmail credential is
needed in this package.

## Order and continuation

Use the approved whole-minute start rule. Read back the signed image digests,
native schedule and exact binding, both corrected alert rules, and the
private route and TLS before proof. Keep the same target, identities, roles,
private topology, selected admission limit and workload budgets. The API
gets one liveness request as the first application proof, before any signup
or workload probe.

```powershell
$PY = '.venv/Scripts/python.exe'
& $PY -m infra.milestone_7_8.pilot.core_proof_operator telemetry-first --package $P --bound $B --execute
& $PY -m infra.milestone_7_8.pilot.core_proof_operator gate --package $P --bound $B --execute
```

The first command admits the actual ready API revision and image, issues one
private GET, and binds its returned trace and elapsed interval. It queries
the exact application log trace at most 12 times and reserves time for
native replica-console evidence. Acceptance requires the exact
`api.request.completed` GET 200 liveness row and the original SHA-256,
source, privacy, time-window and duplicate checks. The 16 verified worker
rows and both accepted signups from the earlier run remain credited.

| Result | Next admissible work in this deployment |
| --- | --- |
| Exact API row accepted | Continue to account fixture creation and core, then run the applicable remaining stages. A successful liveness check has no cleanup side effect. A fresh worker observation and all later telemetry assertions still require their own evidence. |
| Row missing | Preserve trace, replica emission and observed gateway response or their absence. Core and independent observations continue. Hold only claims requiring API destination observations, including API trace continuity, API-backed panels/alerts and API telemetry correlations. Independent capacity and other functionality can be measured, but rows requiring the held evidence remain open. |
| Scanner pauses | Keep verified independent work running. Reuse the exact bound diagnostic and role repair only when its existing evidence and remaining time admit it. One fresh upload gets its own 900-second clock and 20-second retry cap. Hold phases that require a clean core fixture. |
| Native integrity breach, unsafe binding, uncertain write, cost/usage limit or mandatory stop | Stop proof and reconcile pending operations under the existing rules. Take the bound cleanup path. |

Run the existing account, signup reconciliation if needed, and core entry
points next on the same `$P` and `$B`. Creating the synthetic fixtures in
the new database does not replace the prior accepted signup evidence. Where
the results admit them, continue with the inherited
[timed index and capacity commands](MILESTONE_7_8_SCANNER_RECOVERY_SUCCESSOR.md),
[private proof transport and downstream operation interfaces](MILESTONE_7_8_FULL_CLOSURE_EXECUTION_PACKAGE.md#concrete-entry-points)
and [existing acceptance validators](MILESTONE_7_8_FULL_CLOSURE_VALIDATORS.md).
Keep the existing authorization and clock checks for every operation.
When an original window cannot fit, retain the partial results and leave
the affected assertion open. A missed assertion provides no extension.

## Checklist coverage

| Ledger row | Work this run can close if accepted | What remains conditional or outside the package |
| --- | --- | --- |
| D003 signals, privacy, access and retention | Actual API/worker/outbox rows and trace links, production source rejection and absence, exporter outage/recovery, private access revocation/restoration and exact retention configuration | One liveness row alone proves only its request. A missing API row withholds API-dependent evidence. Operator revocation needs a fresh restricted Entra session. Physical expiry over long retention periods is outside this window. |
| D003 13 dashboards and 16 alert identities | Render and query all eligible panels. Apply only the prepared alert stimuli with native evidence and full catalog windows. | API-backed results depend on valid API rows. Evidence-integrity recovery needs authorized investigation, and backup/cost alerts need actual provider observations or the catalog's applicable missing-data branch. Unobserved firings or recoveries stay open. |
| D004 worker and activity-v1 | Real independent worker claim, scan, publication and polling. Actual private HTTP receiver durability, duplicate/lost ACK, fencing, bounded failure and drain from the accepted fixture. | Core-dependent work holds if the fresh scan fails. An unavailable API destination can leave telemetry parts open even with durable worker and activity effects. |
| D005 R1–R4 | One scoped current-release PITR copy, fresh roles, actual tenant denials, replay and nonterminal fencing, recovery and rollback with measured RPO/RTO and retained provider evidence. | Needs the accepted fixture, eligible restore point, available two-hour restore allocation and one-hour export allocation. Historical 0028→0029 compatibility remains separately credited. No second restore or fresh historical replay. |
| D006 capacity, release and controls | Existing 24 workload stages and pressure/recovery windows, scoped security checks, exact native digests and private route/egress/identity observations. | Capacity credit is limited to measured workload and recovery. API-dependent correlations can remain open. The current API scan failed and blocks the release portion. Local key-only endorsements give no CI identity or transparency-log assurance. Unresolved license or control dispositions remain open. |
| D007 infrastructure diagnostics | Native category observations and retention for deployed services; useful even with a held API trace. | Historical Firewall/VM categories remain unproved and are not applicable to this topology. No Firewall/VM resources are added. |
| Two editable-AI scenarios | Managed browser/provider observations for explicit save, edit, reload, immutable original citations and Trace, plus retained retrieval/refusal/deletion expectations. | Requires a clean scenario fixture, native provider response and access for actual browser evidence. |
| Password reset | No email testing in this request. The package uses inert mail settings and no live mail account. | End-to-end native inbox, single-use and unchanged expiry require a later email-specific path. Defer any Gmail input until that path is approved and ready to send. |
| Final exit and billing | Verify and record all 48 current cleanup counters, preserve the controller and review the existing milestone criteria. | Milestone 7.8 stays open while required evidence or decisions remain. Billing remains unsettled. |

The existing [closure ledger](MILESTONE_7_8_FULL_CLOSURE_LEDGER.md#existing-criteria-and-disposition)
retains the exact criteria and historical acceptance.

## Price, access and cleanup

The shared run uses the existing Canada Central private foundation, one
isolated PITR copy, and East US private HA Redis B0. It retains the seven
replicas across API/worker/frontend/gateway/outbox/activity, existing
ephemeral job slots, the temporary VPN/private DNS and restricted Entra
session, and the 20-minute exact-IP ACR publication bound. The original
10,000 HTTP, 200 model-attempt and 160M embedding-token limits stand. The
single liveness request consumes existing reserved headroom. No new hosting,
email, identities, roles or provider limits are added.

The retained line-item model for this shared scope forecasts **$40.8177 USD**
through +13h, including the restore, timed workloads, cross-region charges and
operator access. Its 25% contingency totals **$51.0221**. Proposed replacement
execution ceiling is **$56.51**. Reserve **$53** for unsettled prior exposure
including the latest attempt; the combined exposure bound is **$109.51** and
proposed cumulative ceiling **$460.40**. The latest reserve addition is **$11**
from less than two hours at the retained peak pricing and fixed allowances
($10.462003 estimate). Reserves and the overlapping historical posted amount
are distinct from actual charges. The estimate must still be checked against
the exact signed candidate package before spending approval.

From the eventual approval's first strictly later whole UTC minute, private
services and route are due by **+2h**, and the liveness result and core cutoff
are **+3h**. Proof ends by **+11h**, Automation authority expires at **+12h**,
and verified cleanup is due by **+13h**. Preserve the exact native schedule
and binding. The entitled executor must remain available through +13h; a
schedule readback gives no assurance that the monthly Automation quota
allows execution. For cleanup before +11h, the single package approval would
authorize direct deletion if the exact current runbook start returns the
recorded monthly-limit 429, proof has stopped, and the native job inventory
confirms no overlapping or newly started run. The operator rechecks the
subscription, executor and target ownership and journals one delete.

```powershell
& $PY -m infra.milestone_7_8.pilot_cleanup fallback-plan --runtime "$B/runtime.json" --config "$B/campaign.json" --use-execution-quota-approval --execute
```

If proof reaches +11h, use the scheduled path without a second runbook
dispatch. If it has not removed the target by +12h, the existing ordinary
fallback admits a scoped direct delete after the same ownership and native
inventory checks. Check the group and named Canada Central vault, purge only
that vault with the entitled operator, remove campaign tenant/VPN artifacts
and disarm only this schedule and binding. A failed read or ambiguous delete
requires reconciliation. Verify all 48 counters, including that no temporary
email credential was issued, and preserve the controller.

User input comes at local signing after the clean scan, separate execution
and cleanup approval for the sealed package, and the eventual Entra/VPN
sign-ins and any scoped integrity investigation. Cleanup may require current
operator reauthentication and closure of the restricted browser session.
The private draft package is
`.runtime/milestone_7_8/full-closure-prerequisites/telemetry-first-shared/`.
Its frozen review is marked blocked. The executable approval hash must be
derived again from the clean, signed candidate and the exact ready package.
