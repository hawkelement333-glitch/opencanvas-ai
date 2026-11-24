# Milestone 7.8 private staging successor

This successor covers one private deployment and one synthetic core attempt.
It reuses the exact retained unsigned staging API and signed frontend images.
The new staging-only exception covers the same six retained OpenSSL findings
and expires at the operator cleanup cutoff. The previous exception expired.
PostgreSQL, D001, D002, accepted signups and prior cleanup stay closed. The
providers and private-route prerequisites still require native readback on the
new deployment. Billing remains unsettled.

## Scanner observation during core

Use the sealed `core` route on the deployment's synthetic account fixture.
Before starting the upload job, capture the migration helper's original
configuration, apply the worker-identity overlay, and wait for Azure to report
`Succeeded`. Read back the intended identity, registry, configuration and
template before admitting the upload. When the primary version first passes
the quarantine check, the evidence job emits one execution-bound marker.
Pass its exact upload IDs and original cutoff in the diagnostic execution
template. Start only if more than 135 seconds remain at admission.
The database read uses the worker role in a read-only transaction. It
revalidates the exact session, document ID, version, checksum, original
deadline and pending state before reading storage and Log Analytics.

The migration helper and worker are separate resources in the same private
environment. The helper must be idle, use one replica, and have a verified
migration template and identity before its exact, temporary worker-identity
overlay. The worker app continues with its own identity and configuration.
The helper takes no scan-row lock. Wait for any outstanding native update and
diagnostic execution to settle before restoring the original configuration.
Verify the original configuration, template and migration identity with a
terminal native readback. Preserve five minutes before the proof hard stop
for cleanup. An unresolved update, execution or restoration is recorded with
the last native state and any differences from the original, and uses the
existing cleanup path. Deletion evidence does not verify restoration.

The receipt records request and cutoff times, each read's start and finish
relative to both, version and normalized ETag hashes, Blob tag identity and
verdict, and the bounded Log Analytics query and row evidence. Tag labels and
hashes preserve the distinction between unavailable data, a mismatched version
and a read that returned no exact result. The diagnostic has no mutation or
promotion path. The existing production 900-second and exact two-source gates
decide independently. If an in-window dispatch is infeasible and the primary
later holds, one `diagnose` action may collect a receipt labeled post-deadline,
provided the start-intent journal confirms no in-window dispatch was attempted.
Once a start has been attempted, there is no second diagnostic or upload retry
under this approval. Any individual read that finishes after expiry is late
evidence for that source. The diagnostic records agreement only when both
timed reads match the exact upload inside the original evidence window.

## Infrastructure baseline comparison

The three cases reproduced on the clean detached `53cfa007` tree. The
assertions now check the compiled template's actual shape. Template and image
inputs stay byte-bound to the retained deployment and artifacts.

| Case | Baseline result and operational impact |
| --- | --- |
| Foundation region | The template allows East US and Canada Central. The sealed inputs select Canada Central and East US Redis. The old assertion expected only East US. The geography assertion affected local verification only. |
| Runtime common environment | The generated ARM `common` variable is a concatenation expression. `commonBase` supplies the scanner settings and `common` adds the optional request limit. The old iteration failed before validating the settings. The corrected test checks both parts and the private deployment. Identity, helper restoration and evidence collection use their own native gates. |
| Vault purge protection | The compiled transient vault sets soft delete and omits the opt-in purge-protection field. The old assertion required an explicit false. The corrected test permits the omitted default or explicit false and rejects true. The prior live purge and terminal receipt establish that the same vault policy was purge-compatible. The successor verifies the live setting before provisioning dependent proof and checks exact purge at cleanup. |

The terminal verifier also handles the provider's canonical role-definition ID
and its deployment alias by requiring the same UUID, permissions, role name
and sole campaign assignable scope before deleting a surviving custom role.

## Same-deployment follow-through

Keep the fresh private readiness and one-request telemetry witness for the
new deployment. Preserve the prior accepted API request, 32 rows, five
retention settings, 13 workbook configurations, native infrastructure
categories, and 48 zero counters as historical evidence. Capture a new cleanup
receipt for this deployment.

Run the `transport` operator action once after the evidence job becomes idle.
Its probe requires HTTP 401 and 422 negative controls, HTTP 202 for the valid
batch, and all four exact SignalIds. Keep the previous failed-or-unknown
transport outcome. Render all 13 real workbooks and retain the authorized
operator's PNG review with exact workbook resource IDs and SHA-256. Capture
actual eligible alert firing and recovery against the corrected package query
and cadence. Native configuration, query output and local fixtures alone do
not count as a render or alert transition.

Use the `infrastructure` operator action for the exact PostgreSQL log and
Blob delete settings and native rows after authorized operations have had time
to arrive. Retain a missing-row outcome if there is no qualifying event.
This scope uses ordinary operations already authorized by the package and
excludes synthetic faults or discretionary deletions solely to generate a row.
These observations, workbooks, eligible alerts and the transport fixture can
continue while core is held and safety gates remain open.

On accepted current core, follow the existing activity-v1, isolated PITR,
capacity and editable-AI validators on the same deployment within the approved
bounds. Observe actual delivery and failure recovery, the isolated restore and
its fencing and rollback, the bounded workload envelope, and both managed
editable-AI scenarios. Keep the current release, identities and fixture bound
to every native receipt. Missing prerequisites or insufficient time leave
their assertions open. Email and password-reset proof remain out of scope.
