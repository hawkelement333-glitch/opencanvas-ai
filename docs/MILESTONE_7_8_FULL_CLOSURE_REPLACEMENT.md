# Milestone 7.8 replacement execution package

This companion corrects the cleanup admission failure in the
[previous checkpoint](MILESTONE_7_8_FULL_CLOSURE_ADMISSION_CHECKPOINT.md).
The approval for the previous hash remains historical. The replacement needs
its own approval timestamp and retains the same $50 incremental and $400.89
cumulative ceilings. The forecast remains $36.6423 and billing remains unsettled.

The fixed campaign is `m78-full-closure-a712b8c940`, generation
`g1-a712b8c94000`, in exactly `rg-m78-a712b8c940-target` in East US.
This pilot binds the already selected resource names explicitly. The retained
controller's historical campaign and generation identify its bootstrap evidence.
The new target, ledger and scheduled job use the new pilot identity.

## Approval and binding

The package review hashes the sealed input files. After separate approval,
record its `reviewPackageSha256`, `sourceHead`, `approved: true` and UTC
`approvedAt` at whole-second precision. Retain that record privately.
The binder derives readiness at +2h, proof stop and schedule at +10h,
Automation binding expiry at +11h and operator cleanup expiry at +12h.
The existing runbook remains byte-for-byte preserved. Its deadline-only
renewal must bind the new source and exact prior controller evidence and
cover the +11h binding. The separately authorized operator fallback owns +12h.

The preparation commands below derive the controller renewal plan and its
read and write records. The existing renewal CLI records the native snapshot,
dispatches the three deadline tag updates, and reconciles the resulting state.
Use a new private directory for the renewal and another for the bound runtime.

```powershell
.venv/Scripts/python.exe -m infra.milestone_7_8.pilot_cleanup renewal-inputs `
  --package $package --approval $replacementApproval --output $renewal
$prior = "$package/controller-prior-authority.json"
$plan = "$renewal/controller-renewal-plan.json"
$readApproval = "$renewal/controller-renewal-read-approval.json"
$before = "$renewal/controller-renewal-before.json"
$writeApproval = "$renewal/controller-renewal-approval.json"
.venv/Scripts/python.exe -m infra.milestone_7_8.controller_renewal `
  --operation before-snapshot --authority-evidence $prior --plan $plan `
  --read-authorization $readApproval --output $before --execute
.venv/Scripts/python.exe -m infra.milestone_7_8.pilot_cleanup renewal-write-approval `
  --package $package --approval $replacementApproval --output $renewal
.venv/Scripts/python.exe -m infra.milestone_7_8.controller_renewal `
  --operation execute --authority-evidence $prior --plan $plan `
  --approval $writeApproval --before-readback $before --journal-dir "$renewal/journal" --execute
.venv/Scripts/python.exe -m infra.milestone_7_8.pilot_cleanup renewal-reconcile-approval `
  --package $package --approval $replacementApproval --output $renewal
.venv/Scripts/python.exe -m infra.milestone_7_8.controller_renewal `
  --operation reconcile --authority-evidence $prior --plan $plan `
  --approval $writeApproval --read-authorization "$renewal/controller-reconciliation-approval.json" `
  --before-readback $before `
  --journal-dir "$renewal/journal" --output "$renewal/reconciliation" --execute
$reconciledController = "$renewal/reconciliation/02-completed-authority-evidence.json"
.venv/Scripts/python.exe -m infra.milestone_7_8.pilot_cleanup bind `
  --package $package --output $bound --approval $replacementApproval `
  --controller-authority $reconciledController
```

The binder writes `campaign.json`, `runtime.json`, `ledger.json`,
`cleanup.parameters.json`, `campaign.parameters.json`, the relative time
record and exact operating and probe authorizations. A bind with the retained
controller and omitted approval is an offline rehearsal. Its output is tagged
as simulation and the actual operator rejects its execution.

Run the existing operator with the exact files and approval from the bound
directory. The pre-mutation order is `preflight`, `correlate`,
`capacity-check`, `cost-gate`, `scope-create`, `cleanup-deploy`,
`cleanup-arm`, `cleanup-verify`, `billable-start`. Read back the schedule
and binding before creating tenant objects or deploying paid services.

```powershell
.venv/Scripts/python.exe -m infra.milestone_7_8.operator $operation `
  --config "$bound/campaign.json" --runtime "$bound/runtime.json" `
  --ledger "$bound/ledger.json" --authorization "$bound/operator-approval.json" --execute
```

The historical PostgreSQL deployment commands are excluded from this pilot
operator path. The compiled `compiled/pilot.json` supplies the actual
foundation, jobs and application stages. Use the
[operator access sequence](MILESTONE_7_8_OPERATOR_ACCESS_EXECUTION.md)
for the exact tenant objects and group-scoped deployment. Its source of
campaign IDs, lifecycle tags and cleanup identity is this bound directory.
Generate each private ARM parameter file as follows.

```powershell
.venv/Scripts/python.exe -m infra.milestone_7_8.pilot_cleanup stage-parameters `
  --package $package --directory $bound --stage $stage `
  --native-values $admittedNativeValues --output $privateParameters
```

The native file supplies the admitted VPN audience application ID,
restricted operator object ID and exact controller name/principal. The jobs
and application stages also supply the native bootstrap principal and
Defender scanner resource ID. The binder merges the sealed private secret
parameter file into those stages. No credential value belongs in arguments.

The proof transport uses the packaged `wheel-manifest.json` and `wheels/`
with the existing `pilot.pack_execution` CLI. Use `--bundle $package`,
`--authorization $bound/approval.json`, `--bindings $package/planned-bindings.json`,
`--wheel-manifest $package/wheel-manifest.json`, `--wheel-directory $package/wheels`,
an exact module, its `--arguments-json`, and a distinct private `--output`.
Index and capacity use the separately bound child files in the same approval.
The password-reset proof admits the frontend origin only from the matching
native Container App GET and signed frontend digest. Preserve the actual
request and native inbox receipts for confirmation and expiry.
Use the retained [full proof sequence](MILESTONE_7_8_FULL_CLOSURE_EXECUTION_PACKAGE.md)
for the existing workloads and interventions.

## Cleanup

At +10h stop proof and use the armed schedule. Reconcile its native job before
retrying or removing any binding. Through +11h the approved regular operator
can start the exact runbook if recovery requires it. From +11h to +12h the
separately bound fallback can delete only the exact campaign group, after
checking the current executor, target ownership, native group state and
outstanding Automation jobs. The fallback records an exclusive deletion intent.
If deletion is in progress, retain the state and wait for native absence.

```powershell
.venv/Scripts/python.exe -m infra.milestone_7_8.pilot_cleanup fallback-plan `
  --runtime "$bound/runtime.json" --config "$bound/campaign.json" --execute
```

Use `cleanup-verification-approval.json` for the operator's
`cleanup-wait` and `cleanup-disarm` through +12h. The approved signed-in
executor can perform the exact vault and tenant cleanup through the same
deadline. Verify the full pilot residue plan including the access counters,
Gmail credential disposition and retained controller. The legacy PostgreSQL
residue report cannot finalize this broader campaign.

The isolated resources, provider allowances, fault interventions and exact
cleanup permissions are the same as in the previously reviewed package.
The signed API and frontend OCI artifacts retain their original digests.
