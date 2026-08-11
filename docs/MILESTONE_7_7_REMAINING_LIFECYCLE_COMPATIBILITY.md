# Milestone 7.7 Remaining Lifecycle Compatibility

## Local closure boundary

This document records a local-only closure pass. It does not refresh Azure
evidence, issue a live ledger, build or publish an image, run a scanner proof,
deploy, migrate, validate a live endpoint, start a soak, or execute cleanup.

The production entry point is
`infra.milestone_7_7.scripts.managed_binding_lifecycle`. The managed-binding
overlay exposes fourteen ordered lifecycle operations. Its terminal Azure
implementation is `infra.milestone_7_7.terminal_lifecycle_adapter`, which uses
the entry point's established clients, authorization, receipts, and attribution
rather than introducing another execution framework. Every terminal stage
writes `mobius.milestone-7.7.terminal-stage-evidence.v1`; the next stage loads
that exact file before any downstream action, validates its repository and
ledger bindings, and requires its integrity as the sole predecessor.

## Remaining execution graph

| Gate                | Production producer                                                          | Production consumer                       | Durable success                                                                        | Mutation and recovery                                                                                                             |
| ------------------- | ---------------------------------------------------------------------------- | ----------------------------------------- | -------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| Current-HEAD ledger | `materialize_ledger` and `build_authorization_ledger`                        | lifecycle receipt claimant                | integrity-bound one-run ledger                                                         | local producer; replay denied                                                                                                     |
| Image admission     | prebuilt image record v2, with separate `imageSourceCommit`                  | publication adapter and ledger validator  | source, build-input, config, and manifest identities separated from control-plane HEAD | one final build/publication only in a later authorized run                                                                        |
| Scanner evidence    | proof runtime success marker v2 plus authoritative recovery adapter readback | post-secret deployment-evidence v2 loader | `SCANNER_RESULT_BRIDGE_PROVED`, zero unresolved reasons                                | one later Proof #3; Proof #4 denied                                                                                               |
| Post-secret         | metadata-only Key Vault admission and subscription deployment readback       | migration stage                           | `POST_SECRET_FOUNDATION_READY`                                                         | PostgreSQL, Redis, environment, API, worker, telemetry, DNS, and migration definition reconciled; retry denied                    |
| Migration           | exact Container Apps migration job execution                                 | readiness stage                           | `MIGRATION_COMPLETED`, revision `20260726_0028`                                        | one start, bounded terminal polling, failure preserves environment                                                                |
| Readiness           | authoritative private revision and immutable-image readback                  | live validation                           | `READINESS_PASSED`                                                                     | read-only; unhealthy or nonterminal revision fails closed                                                                         |
| Live validation     | private DNS, TLS, HTTP health, cleanup, cost, image, and revision readback   | soak                                      | `VALIDATION_PASSED`                                                                    | read-only; exact private address and runtime contract required                                                                    |
| Soak                | real 90-minute state machine with ordered sample chain                       | successful closeout                       | `SOAK_COMPLETED`                                                                       | read-only; graph, DNS, TLS, health, cleanup, authority, or cost change invalidates the entire run and requires a fresh 90 minutes |
| Closeout            | residue inventory and temporary-authority revocation                         | cleanup-authorization v1 producer         | `READY_FOR_FINAL_CLEANUP`                                                              | exact revocation only; nonzero temporary residue fails closed                                                                     |
| Cleanup             | predecessor-bound, one-use cleanup authorization                             | zero-residue stage                        | `CLEANUP_COMPLETED`                                                                    | exactly three resource groups and the exact soft-deleted vault; authorization consumed; replay denied                             |
| Zero residue        | subscription/resource/role/identity/authorization inventory                  | completion producer                       | `ZERO_RESIDUE_PROVED`                                                                  | read-only; every defined count must equal zero                                                                                    |
| Completion          | zero-residue-bound terminal evidence producer                                | terminal evidence validator               | `MILESTONE_7_7_COMPLETE`                                                               | local evidence only; provisioning and Milestone 7.8 remain false                                                                  |

## Closed defect inventory

The closure corrected these locally proved defects:

- prebuilt image evidence used the ambiguous `repositoryHead` field for image
  source identity; v2 now records `imageSourceCommit`, while the lifecycle
  ledger continues to bind the current control-plane HEAD separately and keeps
  image-input drift checking enabled;
- post-secret authorization incorrectly required a retained Key Vault role at
  a checkpoint reached only after mandatory revocation;
- the managed-binding method omitted the required scanner deployment-evidence
  argument;
- subscription deployments and migration job starts were not attributed as
  mutations;
- post-secret deployment, migration execution, and readiness were collapsed
  into one operation with no durable handoff artifacts;
- live validation, the uninterrupted soak, successful closeout authorization,
  exhaustive zero-residue evidence, and explicit milestone completion lacked
  production producers/consumers;
- the former simulator appended markers and used a tautological duration check
  instead of exercising the production contracts.

## Scanner proof completeness

The next scanner runtime emits one integrity-bound success marker containing
the event-time URI, ETag, version, scan-request, content, completion,
correlation, blob-tag, Log Analytics, dual-source, DNS, TLS, and cleanup facts.
The production recovery adapter combines that marker with authoritative
provider, diagnostic, RBAC, consumer-identity, private-path, system-topic,
revocation, and residue readback. It writes
`mobius.scanner-result-bridge.deployment-evidence.v2`, which the real
post-secret loader accepts directly. Current observations are not relabeled as
historical proof, and no post-scan evidence patch is part of the path.
The one-use scanner recovery authorization is v2 and binds the only remaining
execution to ordinal 3; any ordinal 4 authorization is rejected before adapter
execution.

## End-to-end simulation boundary

`preflight.milestone_7_7.remaining_lifecycle_simulation` uses the real ledger
builder/validator, scanner evidence serializer/loader, Bicep parameter builder,
terminal evidence writers/loaders, cleanup authorization producer/consumer,
and soak state machine. A fake clock advances the full 5,400 seconds and
produces 91 samples. Every producer artifact is serialized before the next real
consumer loads it.

The simulated durable order is:

`IMAGE_PUBLISHED` -> `PUBLISHER_REVOKED` ->
`SCANNER_RESULT_BRIDGE_PROVED` -> `POST_SECRET_FOUNDATION_READY` ->
`MIGRATION_COMPLETED` -> `READINESS_PASSED` -> `VALIDATION_PASSED` ->
`SOAK_STARTED` -> `SOAK_COMPLETED` -> `READY_FOR_FINAL_CLEANUP` ->
`CLEANUP_COMPLETED` -> `ZERO_RESIDUE_PROVED` -> `MILESTONE_7_7_COMPLETE`.

Failure coverage rejects wrong image/control-plane identity or build inputs,
scanner schema/integrity/incomplete evidence, illegal proof count, missing Key
Vault authority at the only checkpoint that requires it, migration/readiness
failure, live validation failure, soak interruption or graph reset, insufficient
cleanup reserve, cost overflow, stale cleanup authorization, replay, and any
remaining residue.

## Ordered future live plan

No step below is authorized by this document. A later explicit run must use one
fresh one-run ledger and the existing exact scopes:

1. Build the frozen source once and publish its immutable manifest once.
2. Run Proof #3 exactly once; persist deployment-evidence v2; never create
   Proof #4.
3. Run `post-secret-provisioning`; require the fresh scanner artifact and
   authoritative foundation readback.
4. Run `migration-execution` once and require terminal success at `0028`.
5. Run `readiness-validation` and `live-validation` over the private path.
6. Run `soak` uninterrupted for 90 minutes with at least 90 minutes of cleanup
   reserve remaining after completion.
7. Run `successful-closeout`; revoke temporary authority and issue one cleanup
   authorization.
8. Run `cleanup` once, then `zero-residue-verification`.
9. Run `milestone-completion` and require the explicit terminal marker.

Ambiguous service responses are reconciled authoritatively within existing
bounded adapters. A failed one-run receipt is never replayed. Any need for a
second image, Proof #4, broader RBAC, public networking, a higher cost ceiling,
or migration `20260726_0029` is a terminal stop, not a fallback.
