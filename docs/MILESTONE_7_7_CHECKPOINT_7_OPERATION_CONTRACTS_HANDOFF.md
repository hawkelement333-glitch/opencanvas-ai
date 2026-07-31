# Milestone 7.7 Internal Checkpoint 7 Operation Contracts Handoff

Date: 2026-07-30

Status:
`complete-local-operation-contracts-with-provisioning-blocked`

## Decision

Internal Checkpoint 7 is complete locally. The implementation adds one
versioned, machine-readable, default-deny definition matrix for exactly the 15
operation identities that remained blocked after Checkpoint 6.

Repository evidence did not establish a complete executable method, parser,
minimum retained projection, and semantic read-only proof for any of those 15
operations. The approved Checkpoint 7 outcome is therefore a complete explicit
blocked disposition for every slot. No command or provider result was
invented.

This classifier does not mean that an Azure operation ran, an infrastructure
or runtime gate passed, provisioning became authorized, Milestone 7.7
completed, or Milestone 7.8 began.

## Restart and protected boundary

The implementation began from:

- branch: `milestone-7-7-implementation-local`;
- source HEAD:
  `39f6409a44e1e9219e001eda80adb126559c94f2`;
- source parent:
  `2dfb22e2ea1eb27737e9af76053d76dcab8dd494`;
- clean tree and index;
- no upstream;
- sole Alembic head: `20260726_0028`;
- migration `20260726_0029`: absent;
- protected `0028` blob:
  `55c203e669cace5be64fc25cdcf0eb8c05519198`;
- five protected stash identities and eight recovery artifacts unchanged; and
- Checkpoint 6 classified
  `complete-with-provisioning-blocked`.

No stash content was inspected and no Git maintenance ran.

## Contract artifacts

The matrix version is:

`mobius.milestone-7.7.azure-topology-operation-contracts.v1`

Its domain-separated integrity SHA-256 is:

`100293931dcc71bb069e4f6fe06228360e0953b3b756544a555941d81bf8d6bc`

It binds, without altering:

- Checkpoint 6 operation inventory SHA-256:
  `923cbf934040405fd1702b49bd79d876ee3e85fe88d68bbb3d94f980fa45b843`;
- Checkpoint 6 scope SHA-256:
  `a98776f4d2ea33f64e28514fc7c13d2e6160a79ea29247f79fc71f4ffe529e3e`;
- the 18-slot historical inventory;
- the historical scope contract; and
- the persisted Checkpoint 6 evidence.

An exact 15-row supersession map binds every prior blocked operation identity
to the same Checkpoint 7 identity with disposition `preserved-blocked`.
Historical inventory, scope, and evidence remain immutable and are not
reclassified.

The implementation adds:

- `operation-contracts.json`;
- `operation-contracts.schema.json`;
- `operation_contracts.py`;
- `verify_operation_contracts.py`; and
- focused fail-closed tests.

## Exact operation registry

The closed order is:

1. `regional-service-availability`;
2. `provider-registration-api-versions`;
3. `regional-sku-capabilities`;
4. `subscription-quota-bounded-usage`;
5. `private-endpoint-network-support`;
6. `private-dns-prerequisites`;
7. `managed-identity-support`;
8. `scoped-rbac-prerequisites`;
9. `telemetry-diagnostic-prerequisites`;
10. `evidence-retention-prerequisites`;
11. `scanner-result-bridge-prerequisites`;
12. `external-test-provider-prerequisites`;
13. `bounded-cost-budget-prerequisites`;
14. `provisioning-dependency-blockers`; and
15. `private-acr-source-prerequisites`.

No identity was renamed, added, removed, merged, split, or reordered.

## Fail-closed behavior

Every entry records:

- the supported infrastructure gate or gates;
- required inputs and prerequisites;
- approved future region and scope boundary;
- required authority level and denied current authority state;
- a future fresh sanitized minimum-projection evidence requirement;
- no-secret, no-private-data privacy policy;
- zero current Azure cost effect;
- one maximum future attempt, a 30-second timeout, and zero retries;
- exact stop and failure behavior; and
- a precise current blocker.

Every entry also fixes:

- `definitionStatus: blocked`;
- `proofStatus: unproved`;
- `executionAuthorized: false`;
- `mutationAuthorized: false`;
- `provisioningAuthorized: false`;
- `dataPlaneAllowed: false`;
- `semanticReadOnlyVerified: false`;
- `methodDefinition: null`;
- `parserDefinition: null`; and
- an empty retained projection.

Missing input, prerequisite, scope, authority, evidence, freshness, or
integrity denies execution. Unknown fields, operations, states, authority, or
transitions are rejected. Even a caller that claims every future condition is
present receives a denied decision because the operations remain blocked and
no execution authorization exists.

A contract definition is not execution evidence. Fabricated or incomplete
evidence cannot prove an operation. Contract validation cannot change an
infrastructure or runtime gate.

## Preserved gates and authority

All ten infrastructure gates remain `blocked`:

- alert destination;
- evidence retention;
- exact provider API versions;
- managed-identity environment mapping;
- OpenAI/SMTP test providers;
- private ACR source path;
- Redis custom ACL support;
- region and subscription availability;
- scanner-result bridge; and
- telemetry gateway.

All five runtime gates remain `unproved`:

- cleanup-supervisor runtime proof;
- effect-lock runtime proof;
- fault-controller shape;
- isolated environment; and
- live-failure authorization.

Azure access, external calls, execution, mutation, provisioning, data-plane
access, workloads, faults, deployments, and migration remain unauthorized.

## Validation

The focused Checkpoint 7 suite passed 37 tests. It covers exact identity and
order, schema and version closure, missing/duplicate/additional operations,
unknown fields, missing inputs and prerequisites, state and authority
strengthening, fabricated methods/parsers/evidence, gate upgrades, retry
changes, deterministic reproduction, integrity tampering, privacy, denied
execution, no external clients, and migration absence.

The complete affected internal Checkpoint 1–7 campaign covers 598 tests. Its
final result is 597 passed and one existing Windows symlink-permission skip.

The deterministic verifier reports:

- 15 operations;
- 15 blocked operation definitions;
- 15 unproved operation outcomes;
- ten blocked infrastructure gates;
- five unproved runtime gates;
- Azure access unauthorized;
- execution and mutation unauthorized; and
- provisioning unauthorized.

Strict mypy passes for both new source modules. Ruff lint and formatting pass
for the new source and test files. Direct installed Prettier passes for all
nine changed Markdown and JSON files. Repository hygiene passes for 519 source
files, and all 60 changed-document local links resolve.

`git diff --check`, trailing whitespace, secret patterns, raw identifiers,
private addresses, personal paths, generated residue, prohibited scope,
dependency and lock files, and historical-evidence checks pass. The sole
Alembic head remains `20260726_0028`, its protected blob remains
`55c203e669cace5be64fc25cdcf0eb8c05519198`, and migration
`20260726_0029` remains absent.

## Finite Milestone 7.7 closeout map

No later internal checkpoint number is defined. Exactly six work packages
remain, organized by the governing formal Milestone 7.7 exit requirements:

1. close the read-only topology, provider, cost, authority, and prerequisite
   evidence gates;
2. provision and secure one approved isolated synthetic environment;
3. prove monitoring, alerts, runbooks, effect lock, cleanup supervision,
   evidence retention, and supply-chain controls;
4. execute bounded stress, soak, spike, mixed, capacity, and recovery-under-
   load measurements;
5. execute the closed failure, resilience, isolation, revocation, limit,
   security, and cost-ceiling exercises; and
6. revoke access, clean synthetic data, delete all temporary infrastructure,
   prove zero residue, consolidate evidence and supported limits, resolve all
   critical/high findings, and complete the final Milestone 7.7 local audit.

Packages 1–3 are ordered prerequisites. Packages 4 and 5 may share the same
approved isolated environment after package 3 passes, but destructive faults
remain serialized and each exercise must restore its baseline. Package 6 is
last and is the only package that may close formal Milestone 7.7.

The detailed authorization, cost, evidence, cleanup, and acceptance boundary
for these six packages must be approved separately. This handoff grants no
such authority.

## Final boundary

- Internal Checkpoint 6:
  `complete-with-provisioning-blocked`.
- Internal Checkpoint 7:
  `complete-local-operation-contracts-with-provisioning-blocked`.
- Formal Milestone 7.7: in progress.
- Provisioning: unauthorized.
- Migration `20260726_0029`: absent.
- Milestone 7.8: unstarted.

No Azure access, Azure command, Git remote operation, package-manager action,
software installation, application, worker, service, browser, migration,
deployment, workload, fault, or probe occurred during this implementation.
