# Milestone 7.7 Remaining Lifecycle Compatibility

## Local closure boundary

This document records the local-only compatibility closure for the existing
Milestone 7.7 lifecycle. It does not refresh Azure evidence, issue a ledger, or
authorize an Azure operation.

| Existing stage | Producer and consumer | Contract boundary | Local result |
| --- | --- | --- | --- |
| Already-pushed publication | `api_image_publication.py` reconciliation to immutable handoff | canonical publication record, receipt, immutable digest | CONNECTED_COMPATIBLE |
| Scanner proof | `scanner_result_bridge.py` collector/resolver to post-secret request | versioned typed deployment evidence; no boolean override | CONNECTED_COMPATIBLE |
| Post-secret deployment | `managed_binding_lifecycle.py` to `main.bicep` | explicit evidence-integrity parameter vector | CONNECTED_COMPATIBLE |
| Bicep gate | `main.bicep` to scanner bridge, storage, and compute modules | all proof hashes, `RESOLVED`, zero unresolved reasons | CONNECTED_COMPATIBLE |
| Deployment outputs | `main.bicep` to migration/runtime reconciliation | enabled flag, bridge state/integrity, migration-job name and ID | CONNECTED_COMPATIBLE |
| Migration and runtime | existing lifecycle migration and private revision checks | immutable image, migration `20260726_0028` | CONNECTED_COMPATIBLE |
| Readiness through cleanup | existing lifecycle readiness, validation, soak, cleanup, and residue checks | existing durable-marker and inventory contracts | CONNECTED_COMPATIBLE |

## Typed scanner-bridge extension

`ScannerResultBridgeDeploymentEvidence` is the sole bridge extension. It binds
the current control-plane head and sanitized SHA-256 aliases for provider,
producer, Event Grid/queue transport, consumer/idempotency, identity/RBAC,
private endpoint/DNS/TLS path, correlation, revocation, cleanup inventory, and
the existing resolver evidence. The builder rejects stale, future, malformed,
unresolved, or incomplete evidence.

The post-secret executor loads this evidence only from outside the repository,
binds it to the ledger head, and serializes every required proof explicitly.
The existing `main.bicep` derives bridge resolution itself; callers cannot pass
an independent `scannerResultBridgeResolved` parameter. Post-secret deployment
is therefore disabled until the version, state, freshness value, evidence
integrity, all proof integrities, and zero unresolved-reason count agree.

## Remaining-path simulation boundary

The local campaign exercises production contract builders and validators for
publication handoff, bridge admission, Bicep parameter construction, migration
output shape, and preserved existing lifecycle stages. It deliberately replaces
only Azure boundary adapters. The modeled durable order is:

`IMAGE_PUBLISHED` -> `PUBLISHER_REVOKED` -> `RUNTIME_DEPLOYED` ->
`MIGRATION_COMPLETED` -> `READINESS_PASSED` -> `VALIDATION_PASSED` ->
`SOAK_STARTED` -> `SOAK_COMPLETED` -> `CLEANUP_PROVED`.

Negative coverage rejects absent/stale/unresolved bridge evidence, malformed
deployment outputs, missing proof parameters, incorrect migration handoff, and
non-private or non-immutable deployment input before Azure execution.

## Future live-Azure boundary

Only live service capability, propagation, and execution behavior remain
unproved. A future separately authorized run must supply a fresh complete bridge
evidence artifact outside the repository, preserve the existing immutable image
and cleanup controls, and execute the established single lifecycle path. It must
not create a bridge-only publisher, deployment, migration, readiness, soak, or
cleanup workflow.
