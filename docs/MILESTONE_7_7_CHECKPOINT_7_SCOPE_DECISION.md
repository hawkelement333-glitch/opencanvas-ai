# Milestone 7.7 Internal Checkpoint 7 Scope Decision

Date: 2026-07-30

Status: architecture contract defined locally; implementation later completed
with every operation blocked and unproved; Azure access and provisioning
unauthorized

Decision baseline:

- branch: `milestone-7-7-implementation-local`;
- source HEAD: `2dfb22e2ea1eb27737e9af76053d76dcab8dd494`;
- source parent: `bf1b346187d3d2ce7f66cbfddde10cc675f2e7a6`;
- sole Alembic head: `20260726_0028`;
- migration `20260726_0029`: absent;
- internal Checkpoint 6:
  `complete-with-provisioning-blocked`;
- other operation slots: 15 blocked;
- infrastructure gates: 10 blocked;
- runtime gates: 5 unproved; and
- Milestone 7.8: unstarted.

This decision changes documentation only. It does not implement or execute
internal Checkpoint 7, authorize Azure access, authorize provisioning, resolve
a gate, refresh historical evidence, or begin Milestone 7.8.

## 1. Numbering and sequence

The formal Milestone 7 sequence has eight checkpoints: 7.1 through 7.8. Its
seventh formal checkpoint is **Milestone 7.7 — Load, Capacity, Resilience, and
Infrastructure Security**.

Milestone 7.7 also uses an internal implementation sequence. To avoid treating
the two meanings of “Checkpoint 7” as interchangeable, this decision uses:

- **formal checkpoint 7.7** for the seventh checkpoint in Milestone 7; and
- **internal Checkpoint 7** for the seventh implementation checkpoint inside
  formal checkpoint 7.7.

The currently defined internal sequence is:

1. Infrastructure and Policy Manifest;
2. Workload and Measurement;
3. Local Evidence Framework;
4. Local Failure-Injection Framework;
5. Local Validation;
6. Azure Topology Preflight Scope Definition and bounded evidence closure; and
7. Azure Topology Operation-Contract Completion.

Internal Checkpoints 1–6 are complete locally under their recorded boundaries.
Internal Checkpoint 7 exists, is next, and is unstarted.

No authoritative total number of internal Milestone 7.7 checkpoints is
defined. Later internal checkpoints remain intentionally undefined until
internal Checkpoint 7 closes and reports the exact remaining gates. Internal
Checkpoint 7 is therefore **not** the final Milestone 7.7 checkpoint and
cannot complete formal checkpoint 7.7.

## 2. Selected design

### Exact title

**Milestone 7.7 Internal Checkpoint 7 — Azure Topology Operation-Contract
Completion**

### Purpose

Complete the local, versioned, default-deny contracts needed to evaluate the
15 currently blocked Checkpoint 6 operation slots. For every slot, internal
Checkpoint 7 must either:

1. establish an exact, semantically read-only, control-plane-only operation
   definition with bounded sanitized evidence; or
2. retain the slot as blocked with a precise, evidence-backed reason and an
   explicit later authorization boundary.

Internal Checkpoint 7 prepares a later separately authorized read-only Azure
preflight. It does not run that preflight.

### Why this design fits

Checkpoint 6 proved the approved account context and absence of the two
intended future resource groups, while correctly leaving 15 operations
without safe command templates. The Same-Milestone Control Rule, default-deny
operation inventory, privacy contract, and fail-closed classifier prohibit
skipping from that state to provisioning or live workload execution.

Completing the local operation contracts is the smallest next boundary that
can reduce ambiguity without granting Azure authority or weakening negative
evidence.

## 3. Rejected alternatives

### Repeat or broaden Checkpoint 6 execution

Rejected. Checkpoint 6 is complete under
`complete-with-provisioning-blocked`. Its other 15 slots have no approved
templates, and direct or invented Azure commands remain prohibited. Repeating
the three proved operations would not resolve a gate.

### Provision isolated infrastructure

Rejected. All ten infrastructure gates remain blocked, exact provider and SKU
contracts are incomplete, the isolated-environment runtime gate is unproved,
and provisioning authorization is false.

### Run live workload, resilience, or security exercises

Rejected. No approved isolated environment exists. Effect-lock,
cleanup-supervisor, fault-controller, and live-failure authority remain
unproved. Local workload and failure frameworks are inert planning contracts,
not live authority.

### Make internal Checkpoint 7 the final Milestone 7.7 consolidation

Rejected. Managed capacity, resilience, security, alert, cleanup, provider,
cost, and runtime evidence remains blocked, absent, pending, partial, or
unproved. Formal checkpoint 7.7 cannot close before that evidence is produced
and evaluated.

### Define every later internal checkpoint now

Rejected. The number and shape of later checkpoints depends on which of the
15 operations can be safely defined and what their later read-only evidence
proves. Pre-numbering provisioning, exercise, or consolidation checkpoints
would turn unproved assumptions into architecture.

## 4. Prerequisites and entry conditions

Internal Checkpoint 7 may begin only under separate authorization and only
when all of these conditions are reverified:

1. internal Checkpoint 6 is committed and its current handoff records
   `complete-with-provisioning-blocked`;
2. the repository branch, HEAD, parent, clean tree, clean index, no-upstream
   state, protected references, five stash identities, eight recovery
   artifacts, dependency files, and lock files match the authorized restart
   boundary;
3. `20260726_0028` is the sole Alembic head with its protected bytes
   unchanged and migration `20260726_0029` is absent;
4. the versioned 18-slot Checkpoint 6 inventory, scope contract, evidence
   schema, classifier, verifier, README, focused tests, and historical
   evidence are intact;
5. the three previously proved operation identities remain historical
   evidence only;
6. the other 15 operation slots remain blocked;
7. all ten infrastructure gates remain blocked;
8. all five runtime gates remain unproved;
9. provisioning remains unauthorized; and
10. Milestone 7.8 remains unstarted.

Checkpoint 6 evidence expiration does not block local contract work, but
expired evidence cannot support a current Azure fact or later execution.
Internal Checkpoint 7 must not refresh, rewrite, or reclassify historical
Checkpoint 6 evidence.

## 5. Authorized implementation scope

A separately authorized internal Checkpoint 7 implementation pass may change
only:

- `preflight/milestone_7_7/**`, excluding historical evidence bytes;
- focused tests for the Milestone 7.7 topology-preflight contracts;
- this decision record and directly affected Milestone 7 architecture,
  implementation-plan, progress, README, and handoff documentation.

For each of the 15 operation slots, the implementation must record:

- the stable operation identity;
- the exact authority level and supported infrastructure gate or gates;
- the exact command or non-command method, if one is safely definable;
- authoritative source and review time;
- semantic proof that the operation is read-only, non-mutating, and
  control-plane-only;
- exact scope binding;
- fixed minimum-field projection;
- output byte limit;
- parser and allowed result grammar;
- timeout, attempt, and retry contract;
- raw-output disposal rule;
- privacy transforms;
- success, negative, blocked, malformed, timeout, and failure behavior; and
- whether later Azure execution is possible without an extension, token
  retrieval, account switch, broad discovery, data-plane request, or wider
  authority.

An operation may change from `blocked` to `defined` only when every field
above is complete and focused fail-closed tests pass. A slot that cannot meet
that rule remains blocked with its exact reason. Unknown or partially defined
operations remain denied.

The inventory and scope contract must receive new versions and integrity
values if their semantic content changes. Earlier inventories, scopes, and
evidence remain immutable historical records. A mapping must preserve all 18
stable operation identities and identify which definitions supersede earlier
blocked definitions.

## 6. Permitted source research

The separately authorized implementation pass may use:

- committed repository sources; and
- unauthenticated, read-only official Microsoft documentation needed to prove
  Azure CLI or ARM control-plane semantics.

Any public documentation access must be stated explicitly in that later
authorization. It must not use the signed-in portal session, Azure CLI
authentication, Azure PowerShell, access tokens, subscription-specific APIs,
Resource Graph, an Azure control plane, or any Azure data plane.

Official-source review evidence is current for at most 30 calendar days.
Earlier invalidation occurs when the command surface, Azure CLI version,
provider API contract, source URL, operation projection, inventory, scope,
privacy policy, or authority boundary changes. A later Azure execution must
also satisfy its own 24-hour observation-evidence limit.

## 7. Prohibited work

Internal Checkpoint 7 does not authorize:

- executing an Azure CLI, Azure PowerShell, ARM, REST, Resource Graph,
  control-plane, or data-plane operation;
- authentication, token retrieval, credential refresh, account switching,
  identity enumeration, or use of the signed-in portal session;
- provisioning, deployment, registration, role assignment, quota change,
  budget change, policy change, network change, what-if, validation, start,
  stop, restart, tag, lock, move, or deletion of an Azure resource;
- application, API, worker, frontend, Bicep, workload, fault, probe,
  deployment, runtime, provider-adapter, data-model, or migration changes;
- creating migration `20260726_0029`;
- changing dependencies or lock files;
- installing a package, extension, tool, or runtime;
- executing load, stress, soak, spike, failure, resilience, browser,
  application, worker, service, deployment, or migration tests;
- defining a live resource, SKU, identity, role, address, endpoint, or cost as
  approved from an assumption;
- changing an infrastructure or runtime gate to proved;
- changing `provisioningAuthorized` to true;
- altering historical evidence, protected Git state, stashes, or recovery
  artifacts; or
- beginning Milestone 7.8.

## 8. Azure and system boundaries

Internal Checkpoint 7 inherits the Checkpoint 6 scope:

- cloud: `AzureCloud`;
- account binding: the committed domain-separated subscription and tenant
  fingerprints, never raw identifiers;
- primary region: `southcentralus`;
- recovery-comparison region: `northcentralus`;
- intended future target resource group:
  `rg-solarplexus-mobius-77-staging`;
- intended future cleanup-control resource group:
  `rg-solarplexus-mobius-77-cleanup-control`; and
- default decision: deny.

These are scope contracts, not resource or provisioning approval. Internal
Checkpoint 7 authorizes no Azure subscription, resource group, resource, SKU,
identity, role, network, API version, provider, or operation for execution.

Application, worker, frontend, product data, database, object, queue, limiter,
workflow, agent, retrieval, upload, scanner, parser, and Indexer behavior is
outside this checkpoint. No synthetic or production data is created or
processed. There is no migration.

## 9. Cost, time, cleanup, and rollback

### Cost

- Azure spend authorized: USD 0.
- Billable resource lifetime: none.
- Subscription budget or role change: none.
- The Milestone 7.7 target of USD 100, provisioning block above USD 120,
  absolute ceiling of USD 150, and minimum 25 percent contingency remain
  inherited future-exercise ceilings, not spending authority.

### Time and retries

- No Azure operation may run.
- Every newly defined future operation must retain one attempt, a 30-second
  timeout, and no retry.
- Official-source evidence expires after 30 calendar days or an earlier
  revalidation trigger.
- Later Azure observations retain the separate 24-hour evidence maximum.

### Cleanup

There is no cloud cleanup because no cloud resource or data may be created.
Local temporary validation output must remain outside tracked paths and be
removed before completion. Generated caches, credentials, identifiers,
transcripts, raw provider output, and machine-specific paths must not remain
in the tree.

### Rollback

There is no external effect to compensate. A failed pass makes no commit and
leaves the prior committed contracts authoritative. A later correction uses
a focused forward commit or an explicitly authorized revert while preserving
all historical inventory, scope, evidence, and integrity records.

## 10. Privacy and secret handling

Raw tenant, subscription, principal, role-assignment, resource, endpoint,
hostname, address, token, credential, connection, signed-URL, private-path,
provider-receipt, or data-plane values must not enter repository artifacts,
test fixtures, logs, command output, or documentation.

Only committed fingerprints, fixed public region and intended future
resource-group names, stable operation IDs, public command grammar, bounded
projections, and non-sensitive integrity values may be retained.

Checksums prove deterministic integrity, not identity or signature. Private
reasoning, credentials, model chain of thought, and raw Azure output are never
evidence.

## 11. Gate and operation effects

Internal Checkpoint 7 may change only the **definition state** of the 15
currently blocked operation slots under the complete-definition rule in
section 5. It may not claim that any operation ran.

The rule applies individually to:

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

Each starts `blocked`, may become `defined` only under section 5, and otherwise
remains explicitly blocked. None may become `proved`, because internal
Checkpoint 7 performs no Azure observation.

The ten infrastructure gates remain `blocked` throughout internal Checkpoint
7:

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

The five runtime gates remain `unproved`:

- cleanup-supervisor runtime proof;
- effect-lock runtime proof;
- fault-controller shape;
- isolated environment; and
- live-failure authorization.

Topology metadata and local contracts cannot resolve a runtime gate.

If a slot remains blocked at closure, its dependent infrastructure gate
remains blocked and the later Azure execution boundary must exclude it.
Internal Checkpoint 7 cannot weaken, defer without explanation, or convert a
blocked or unproved state to passed or not applicable.

Provisioning remains blocked regardless of how many operation definitions are
completed.

## 12. Evidence, validation, and classifiers

Required completion evidence is:

1. one versioned operation-definition matrix covering all 15 slots;
2. new deterministic inventory and scope integrity values for every semantic
   change;
3. an exact supersession map that preserves the prior 18-slot inventory and
   historical Checkpoint 6 evidence;
4. focused tests for allowed command grammar, read-only semantics, default
   deny, exact scope, projections, parsers, output bounds, timeouts, no retry,
   privacy, integrity, negative results, and blocked dispositions;
5. deterministic verifier output that contains no raw identifier or private
   operational data;
6. documentation formatting, local-link, whitespace, secret-pattern,
   private-identifier, generated-residue, and prohibited-scope checks;
7. complete diff review proving only the authorized local contract boundary
   changed; and
8. a focused internal Checkpoint 7 handoff with exact limitations and next
   authorization boundary.

Allowed internal Checkpoint 7 completion classifiers are:

- `complete-local-operation-contracts-with-provisioning-blocked`; or
- `blocked-local-operation-contracts-incomplete`.

The complete classifier requires every one of the 15 slots to have either a
fully defined operation or a complete explicit blocked disposition, with no
unknown or partial definition. It does not mean that an Azure observation,
infrastructure gate, runtime gate, deployment, workload, or Milestone 7.7
evidence class passed.

## 13. Stop and failure conditions

Stop without broadening scope when:

- the restart or protected-state boundary differs;
- a required source is missing, stale, conflicting, unofficial, or
  ambiguous;
- a safe operation requires an extension, dependency, provider registration,
  token, account switch, raw identifier retention, broad discovery, mutation,
  data-plane access, or wider authority;
- a command has an unbounded or mixed projection;
- command semantics cannot be proved read-only;
- a slot would need to be silently removed, renamed, split, or substituted;
- a test or verifier can execute a process or network request;
- a secret, private identifier, raw output, machine path, or generated residue
  appears;
- a gate would need to be upgraded without live evidence;
- migration `20260726_0029` or an application/infrastructure change appears;
  or
- the exact documentation and local-validation boundary cannot close.

## 14. Acceptance and exit

Internal Checkpoint 7 closes only when:

- every prerequisite and entry condition passes;
- all 15 operation slots have complete defined or explicit blocked
  dispositions;
- all changed contracts are versioned, deterministic, integrity-bound,
  privacy-safe, and fail closed;
- every available authorized local validation passes;
- no Azure command, authentication, mutation, data-plane request, workload,
  fault, deployment, service, or migration ran;
- Azure spend remains USD 0;
- all ten infrastructure gates remain blocked;
- all five runtime gates remain unproved;
- provisioning remains unauthorized;
- historical Checkpoint 6 evidence is byte-for-byte unchanged;
- migration `20260726_0029` remains absent;
- protected Git and recovery state remains intact;
- one focused local completion commit exists; and
- Milestone 7.8 remains unstarted.

If any condition fails, the checkpoint classifier is
`blocked-local-operation-contracts-incomplete`, no completion commit is
created, and the blocker is preserved without inventing an operation.

## 15. Relationship to Milestone 7.8

Internal Checkpoint 7 cannot begin or complete Milestone 7.8. Formal
checkpoint 7.7 remains in progress after internal Checkpoint 7 because managed
topology evidence, provisioning, workloads, failure exercises, capacity,
security, cleanup, and final consolidation remain independently gated.

Milestone 7.8 may begin only after formal checkpoint 7.7 is complete and
committed under the governing implementation plan. No internal checkpoint
number is inferred for the remaining work by this decision.

## 16. Smallest next separately authorizable action

The smallest next action is one local internal Checkpoint 7 implementation
pass that creates the versioned 15-slot operation-definition matrix and its
focused fail-closed tests without executing Azure.

That action requires a separate prompt. This decision does not execute or
authorize it.

## 17. Implementation outcome

The separately authorized local implementation completed after this decision.
It added the versioned
`mobius.milestone-7.7.azure-topology-operation-contracts.v1` matrix and
focused fail-closed validation. Repository sources did not establish any
complete executable method and parser for the 15 slots, so every slot closed
through the decision's approved complete explicit blocked disposition.

The matrix does not supersede or rewrite the historical Checkpoint 6
inventory, scope, or evidence. It binds their current integrity values, keeps
all 15 operations blocked and unproved, keeps all ten infrastructure gates
blocked and five runtime gates unproved, and leaves provisioning unauthorized.
The implementation result is recorded in
[`MILESTONE_7_7_CHECKPOINT_7_OPERATION_CONTRACTS_HANDOFF.md`](MILESTONE_7_7_CHECKPOINT_7_OPERATION_CONTRACTS_HANDOFF.md).
