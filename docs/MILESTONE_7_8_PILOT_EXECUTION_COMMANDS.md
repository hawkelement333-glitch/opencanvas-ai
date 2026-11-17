# Pilot managed-validation command sequence

> Current follow-up: the [full-closure local ledger](MILESTONE_7_8_FULL_CLOSURE_LEDGER.md)
> and [revised execution proposal](MILESTONE_7_8_FULL_CLOSURE_EXECUTION_PACKAGE.md) supersede
> this historical pilot preparation for the new candidate. Its evidence and
> limitations remain history; its proposed budget is not execution authority.
> Full7.8 remains incomplete, closed campaigns stay closed, billing is unsettled.

Prepared 2026-11-16. **Not execution authority.** This is the command companion
to the [single approval package](MILESTONE_7_8_PILOT_MANAGED_VALIDATION_PACKAGE.md).
It uses East US target `rg-m78-a712b8c940-target`, suffix `a712b8c940`, release
`rc-938deb080547`, deployment `m78p-a712b8c940`, and the corrected API index
`sha256:71f3ccb9a450a9773d3c904dd83fc8b6b97b98eccc7a1bdc890fd0633c5f6192`.
No command below that contacts Azure or a provider has been executed.

## Admission and inputs

The private package directory is
`.runtime/milestone_7_8/pilot-rc-20261116/package/prepared/`. The subscription and
preserved controller bindings come from the retained Redis controller authority,
not a new account query. `planned-bindings.json` binds the exact resource IDs,
source commit/image, fixture limits, approved query hashes and relative window.
The approval record must bind both that file and `manifest.json` by SHA-256.
Do not edit an approved binding silently. Provider-derived addresses are admitted
only through `pilot_validation.admit_runtime_bindings` and its exact six ARM
readbacks. No arbitrary API endpoint may replace them.

Before spending, supply the following missing external inputs together:

- Approved trusted release signer/issuer or public key and verification policy;
  see the [exact detached signing commands](MILESTONE_7_8_PILOT_RELEASE_CANDIDATE.md#signing-decision).
- Frontend origin decision: accept a second, **frontend-only** build after the
  isolated foundation supplies its private API FQDN, or supply an owned fixed
  API hostname and TLS/DNS authority. `NEXT_PUBLIC_API_URL` is a build input.
  The local API build authorization did not authorize this future web image
  build, registry publication or public website exposure.
- Existing SMTP TLS account, permitted sender and one explicitly approved
  recipient/inbox receipt; OpenAI credential/entitlement for `gpt-5.6-terra`
  and `text-embedding-3-small`; synthetic pilot account and operator principal.
  Put secrets only in the private secure parameter file/Key Vault.
- Controller deadline renewal/schedule/grant operations and exact Key Vault
  purge authority for `kv-m78p-a712b8c940`. Use an already authorized principal
  with the purge action; do not grant broad subscription purge access by inference.
- Separate $50 execution ceiling and approval-relative window. Prior billing
  remains unsettled. Stop new proof at +8h; cleanup authority ends +10h.

`applicationSecrets` requires the eleven names in `pilot_runtime.bicep` plus
`opencanvas-pilot-email` and `opencanvas-pilot-password`. Generate independent
random application secrets; never copy the illustrative defaults. Bootstrap
principal/object IDs, source/campaign/generation and subscription correlation
must match the existing six-slot principal manifest. No test bypass is enabled.

## Local commands already available

```powershell
$private = '.runtime/milestone_7_8/pilot-rc-20261116/package/prepared'
$rg = 'rg-m78-a712b8c940-target'
$prefix = 'm78p-a712b8c940'
$digest = 'sha256:71f3ccb9a450a9773d3c904dd83fc8b6b97b98eccc7a1bdc890fd0633c5f6192'
# Offline compile; never az deployment validate before spending approval.
& "$env:USERPROFILE/.azure/bin/bicep.exe" build infra/milestone_7_8/pilot.bicep --stdout
.venv/Scripts/python.exe -m infra.milestone_7_8.pilot_validation --help
.venv/Scripts/python.exe -m infra.milestone_7_8.pilot_application_probe --help
.venv/Scripts/python.exe -m infra.milestone_7_8.pilot.pack_execution --help
```

The image and eight-wheel overlay have also been imported together in a
read-only, network-disabled instance of the exact candidate. Source hashes,
wheel hashes, bounded archive extraction and actual API request schemas remain
separate from managed acceptance.

## After separate approval: protection, foundation and release

1. Record `approvedAt` and derive UTC deadlines: provision by +2h, proof/cleanup
   schedule +8h, cleanup authority +10h. Reuse the existing
   `controller_renewal.py` plan/before-snapshot/execute/reconcile sequence with
   the retained authority, current source SHA and +10h controller deadline.
   Do not republish the unchanged 5,000-cent-admitting runbook. Its preserved
   identity, Reader grant and bootstrap history must match the fresh readback.
2. Through the existing restart-safe operator, run only `scope-create`,
   `cleanup-arm`, `cleanup-verify` against the new config/runtime/ledger and
   recorded authorization. The schedule and binding must be read back before
   `billable-start`. These existing entry points take:

```powershell
.venv/Scripts/python.exe -m infra.milestone_7_8.controller_renewal `
  --operation plan --authority-evidence "$private/controller-prior-authority.json" `
  --source-head $sourceCommit --deadline $cleanupDeadline --output "$private/renewal-plan.json"
.venv/Scripts/python.exe -m infra.milestone_7_8.controller_renewal `
  --operation before-snapshot --authority-evidence "$private/controller-prior-authority.json" `
  --plan "$private/renewal-plan.json" --read-authorization "$private/renewal-read-approval.json" `
  --output "$private/renewal-before.json" --execute
.venv/Scripts/python.exe -m infra.milestone_7_8.controller_renewal `
  --operation execute --authority-evidence "$private/controller-prior-authority.json" `
  --plan "$private/renewal-plan.json" --approval "$private/renewal-approval.json" `
  --before-readback "$private/renewal-before.json" --journal-dir "$private/renewal-journal" --execute
.venv/Scripts/python.exe -m infra.milestone_7_8.controller_renewal `
  --operation reconcile --authority-evidence "$private/controller-prior-authority.json" `
  --plan "$private/renewal-plan.json" --approval "$private/renewal-approval.json" `
  --read-authorization "$private/renewal-read-approval.json" --before-readback "$private/renewal-before.json" `
  --journal-dir "$private/renewal-journal" --output "$private/renewal-reconciliation" --execute
.venv/Scripts/python.exe -m infra.milestone_7_8.operator cleanup-verify `
  --config "$private/campaign.json" --runtime "$private/runtime.json" `
  --ledger "$private/ledger.json" --authorization "$private/operator-approval.json" --execute
```

3. Validate then deploy the exact isolated template. The private ARM parameter
   file uses `stage=foundation`, suffix, tags, catalog, source/release, operator
   identity and the approved provider fields. No application jobs start here.

```powershell
az deployment group validate --resource-group $rg --name "$prefix-foundation" `
  --template-file infra/milestone_7_8/pilot.bicep --parameters "@$private/parameters.json"
az deployment group create --resource-group $rg --name "$prefix-foundation" `
  --template-file infra/milestone_7_8/pilot.bicep --parameters "@$private/parameters.json"
az deployment group show --resource-group $rg --name "$prefix-foundation" --output json
```

Record intent before each mutation and native result afterward. On timeout,
reconcile that named deployment before retrying. Native provider capacity is
not inferred from a local compile or the earlier East US Redis campaign.

4. Admit foundation outputs and the Defender service identity exactly as in the
   retained object foundation. Bind that identity in the same template. Use the
   existing exact-IP ACR admission mechanism for at most 20 minutes, publish the
   already verified API archive without rebuilding, verify registry digest
   equality, then restore private access. The same separately approved interval
   covers the source-bound frontend publication. Prepare the frontend only after
   its origin decision:

```powershell
docker buildx build --platform linux/amd64 --provenance=mode=max --load `
  --file apps/web/Dockerfile --build-arg "NEXT_PUBLIC_API_URL=$verifiedApiOrigin/api/v1" `
  --tag "mobius-m78-pilot-web:rc-938deb080547" .
```

Retain the web build input hash, lockfile, origin, inventory, scan and signature
results. A failed web build/scan blocks application activation; an API rebuild
is not justified by changing this frontend origin.

5. Set `stage=jobs`, API digest, exact bootstrap principal and private secrets;
   deploy the same template. Run manual bootstrap, then migration, once each:

```powershell
az containerapp job start --resource-group $rg --name "caj-$prefix-bootstrap" --output json
az containerapp job execution show --resource-group $rg --name "caj-$prefix-bootstrap" --job-execution-name $actualExecution --output json
az containerapp job start --resource-group $rg --name "caj-$prefix-migration" --output json
```

Record actual execution IDs; reconcile terminal state before advancing. Use the
existing bootstrap/migration guards, not a PG acceptance run. Set the verified
frontend digest and `stage=application`, then deploy the same template. Four
apps run five replicas: API two, worker one, gateway one, web one.

## Private proof payload and dispatch

`pilot/pack_execution.py` binds source files, approval, planned bindings, native
readbacks/fixture inputs and eight exact wheels. It emits a deterministic ZIP
hash and command/environment arrays. The compressed source is split into at
most eight 32-KiB environment chunks, 240,000 encoded bytes total; the complete
Blob archive stays below 2 MB. Raw payloads stay private. The manual
artifact job fetches only the eight exact hashed PyPI wheel URLs, reconstructs
that ZIP, and writes it with `If-None-Match: *` to the isolated private
`operational-artifacts` container. Reconcile a 412/uncertain PUT by exact version
and checksum; never blindly retry it. The proof loader reads that exact native
version and verifies the full ZIP hash before executing any source.

```powershell
.venv/Scripts/python.exe -m infra.milestone_7_8.pilot.pack_execution `
  --bundle $private --authorization "$private/approval.json" `
  --bindings "$private/planned-bindings.json" `
  --wheel-manifest '.runtime/milestone_7_8/pilot-rc-20261116/package/probe-wheels-manifest.json' `
  --wheel-directory '.runtime/milestone_7_8/pilot-rc-20261116/package/probe-wheels-universal' `
  --module infra.milestone_7_8.pilot_application_probe `
  --arguments-json $exactArgumentArrayJson --private-inputs-json $exactInputMapJson `
  --output "$private/core-transport.json"
```

The argument array is the following actual CLI interface; substitute the native
execution name inside the job, never a fabricated expected execution ID:

```sh
python -m infra.milestone_7_8.pilot_application_probe core \
  --bundle /tmp/m78-proof/package --authorization /tmp/m78-proof/approval.json \
  --bindings /tmp/m78-proof/bindings.json \
  --runtime-readbacks /tmp/m78-proof/native-resource-readbacks.json \
  --execution-id "$CONTAINER_APP_JOB_EXECUTION_NAME" \
  --output /tmp/m78-evidence/core.json --execute
```

Copy the emitted arrays to `artifactCommand`/`artifactEnvironment` and
`proofCommand`/`proofEnvironment` in the private parameters. Add exact storage
host/suffix, and to proof environment only the native staging version ID.
`proofRole=evidence` is for HTTP/telemetry; `proofRole=api` is for scoped restore
snapshots/role checks; `proofRole=worker` is for the restored worker fixture,
fencing and resumption. API/worker secret and Blob permissions retain their
existing identities; the evidence identity is not granted application SQL reads.
Run staging and evidence jobs sequentially with the same native start/show
commands above. Before `core`, run the explicitly approved `account` operation
once under the evidence identity to create the synthetic account through
`POST /api/v1/auth/signup`. A timeout or existing account requires sign-in/read
reconciliation; it never authorizes another signup. `replicaRetryLimit=0` prevents opaque platform replay; focused
recovery remains allowed after outcome reconciliation.

The loader exports only `/tmp/m78-evidence` to exact-version private
`operational-evidence/<execution>/` blobs plus a checksum manifest, including
failure intents. Verify the exported manifest/files from an approved private
operator route before cleanup; a workstation has no assumed private network
route. Do not open Blob publicly to download receipts. Lack of evidence export
never extends the cleanup deadline.

## Assertions, operations and bounded interventions

| Existing gap | Exact operation and acceptance boundary |
|---|---|
| Core/release/real provider | `core`: authenticated create/replay, notes/edge, three small synthetic TXT uploads through the production scanner and worker, exact file checksum, retrieval, real grounded draft/citation and unsupported-query refusal. Native scan deadline 900 seconds, retry cap 20; no local scanner substitute. This is current release integration, not a D001 campaign rerun. |
| D006 bounded combined observations | `workload --fixture core.json`, four stages with concurrency 1/2/4/8, at most 200 requests total per stage and 800 total, using read/search, ten note writes and at most two grounded-AI requests per stage. Preserve 429/503 and latency, then successful retrieval. This establishes only the measured envelope; it does not itself close saturation or all failure-under-load criteria. No safe cohort is asserted. |
| D003 destination | `pilot_validation telemetry`, `query --query-file`, `alerts`: exact source tuples, native signal IDs, private DNS/TLS, auth/privacy rejection, query output and native Fired/Resolved receipts. Run all catalog queries; absence is unproved, never healthy zero. Actual application signals must accompany the labelled transport fixture. |
| D003 outages/access | Capture exact gateway revision/config; stop only the isolated gateway using its ARM stop action, generate one bounded workload stage, observe bounded exporter loss/readiness, restart the same gateway and query recovery. Remove only the captured evidence-reader assignment, verify fresh-session query denial, restore the identical assignment and verify read recovery. API/worker must be denied operational table queries throughout. Never remove controller Reader/grants. Each intervention is capped at ten minutes within +8h. |
| D007 configured categories | Four diagnostic resources collect PostgreSQLLogs, registry login/repository, Blob read/write/delete, and Key Vault AuditEvent; require actual rows tied to exact resource/time plus retention readback. Scanner results are separately credited. Existing historical Firewall/VM category gaps are not closed by this environment, which contains neither resource. |
| Enabled delivery | `smtp` proves submission only; invoke the production password-reset endpoint for the approved synthetic account, bind native SMTP message/receiver receipt and validate reset token semantics. No arbitrary recipient is authorized. The absent/disabled external outbox dispatcher remains a full-7.8 gap. |
| D005 R1/R4 | Stop the exact source worker before `restore-fixture`; capture `restore-snapshot` under API identity. PITR only to `pg-m78p-a712b8c940-restore` in this group, same VNet/delegated subnet/private DNS. Retain restore point, start/completion and RPO/RTO. With restored API bound to that server, `restore-verify --fixture core.json --before snapshot.json` compares immutable graph/scan/event/outbox/activity/index bytes and creation replays/grounded serving. Run comparison before resuming mutable work. |
| D005 R2 | `restore-role` under separate fresh API and worker identity jobs against the restored server: exact 0029 head, table ownership and positive/negative table/function privileges. Neither original-target tests nor a successful observer connection close this assertion. |
| D005 R3 | `restore-fence --before nonterminal.json` uses the actual captured expired lease and exact deletion version; checks rejected stale completion, provider-delete/DB-rollback and absence reconciliation with one durable deletion transition. Then `restore-resume --before nonterminal.json` proves one actual worker completion/outcome. Source and restored workers stay stopped except this isolated explicit invocation until reconciliation. |

The installed Azure CLI exposes neither `containerapp stop` nor `start`.
Use the documented ARM actions, retaining the response and asynchronous-operation
URL, then read back `runningStatus`; a 202 is not completion:

```powershell
# Exact worker for restore, exact gateway for the bounded outage; never another app.
$appId = $planned.workerResourceId
az rest --method POST --url "https://management.azure.com${appId}/stop?api-version=2025-07-01"
az rest --method GET --url "https://management.azure.com${appId}?api-version=2025-01-01"
# Restart only after the affected observation is reconciled:
az rest --method POST --url "https://management.azure.com${appId}/start?api-version=2025-07-01"
```

This follows the [Container Apps stop action](https://learn.microsoft.com/en-us/rest/api/resource-manager/containerapps/container-apps/stop?view=rest-resource-manager-containerapps-2025-07-01).
The job-execution and PostgreSQL restore command flags were verified against
installed CLI help; no resource operation was used to validate them.

The restore source is never overwritten. Use `az postgres flexible-server
restore --resource-group $rg --name pg-m78p-a712b8c940-restore --source-server
$exactSourceServerId --restore-time $capturedUtc`; inspect its private network
and actual completion before binding it. Existing application identity/grant
reconciliation runs only on that restored target if required. `proofDatabaseHost`
must be its exact FQDN. Capture the API config before changing its database URL;
switch back to the original only after recording restored assertions. The
unchanged source server and retained object versions are the rollback boundary.

Native action/query failures do not justify unbounded retries. Each job saves
an exclusive dispatch intent. Reconcile a named execution before retry; resume
only its failed/unproved observation with remaining time/cost headroom.

## Cleanup and recovery checkpoint

At +8h, stop proof even with missing observations. The already-armed controller
deletes only this group. Reconcile its current job before any direct fallback:

```powershell
az group exists --name $rg
# Only if the recorded controller outcome requires the approved direct fallback:
az group delete --name $rg --yes --no-wait
az group wait --name $rg --deleted --timeout 1800
# Exact previously approved vault only, using the authorized existing principal:
$campaign = Get-Content -LiteralPath "$bound/campaign.json" -Raw | ConvertFrom-Json
az keyvault purge --name kv-m78p-a712b8c940 --location $campaign.targetRegion
```

A wait timeout is not failed deletion; inspect the exact existing job/group.
Do not create a fresh campaign or reopen one once deletion begins. Remove only
the two recorded target cleanup assignments and this campaign's schedule/binding
after target absence, preserve the controller, and verify the soft-deleted vault
is absent. Counters must separately show zero for target group/resources, API/
worker/web/gateway/jobs/environment, primary/restored PostgreSQL, Redis, Blob/
registry, vault/deleted vault, identities/target grants, network/endpoints/DNS,
workspace/AMPLS/DCE/DCR/tables, alerts/action group/Event Hub, schedule and binding.
Retain the controller identity/content/Reader/bootstrap preservation readback.

The compact private checkpoint records current operation/native execution ID,
intent/result/export paths and hashes, accepted/failed/unproved assertions,
remaining allowance, exact next action, +8h stop and +10h cleanup deadline.
Finalize the ledger only after verified cleanup. Billing remains unsettled.
