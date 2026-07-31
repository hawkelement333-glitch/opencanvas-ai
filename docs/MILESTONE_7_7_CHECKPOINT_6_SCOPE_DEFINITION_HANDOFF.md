# Milestone 7.7 Checkpoint 6 Scope-Definition Handoff

## Decision

The local scope-definition recovery pass remains complete. The separately
authorized Azure Topology Preflight produced a valid sanitized result:

`complete-with-provisioning-blocked`

That historical result proves only the earlier inventory's
`current-account-context` operation. Two exact resource-group absence
templates are now defined locally but have not been executed. The other 15
committed operation slots remain blocked, all ten infrastructure gates remain
blocked, and all five runtime gates remain unproved. Neither the historical
result nor these local definitions complete Milestone 7.7 or authorize Azure
execution, provisioning, Checkpoint 7, or Milestone 7.8.

No Azure command or validation was run while defining the two templates.

## Approved future scope

The contract records only safe SHA-256 fingerprints for the intended
subscription and tenant. It records `AzureCloud`, `southcentralus` as the
primary region, and `northcentralus` as the recovery/comparison region. The
future resource-group boundaries are:

- `rg-solarplexus-mobius-77-staging`;
- `rg-solarplexus-mobius-77-cleanup-control`.

These names are intended future scopes only. The contract does not claim that
either group exists and does not authorize either group to be created. No raw
tenant, subscription, principal, object, client, or resource identifier is
retained.

## Evidence and integrity contract

The evidence contract is
`mobius.milestone-7.7.azure-topology-preflight.v1`. Canonical JSON uses
`mobius.milestone-7.7.canonical-json.v1`, the established sorted-key,
compact-encoding, Unicode-NFC and trailing-LF behavior. Integrity uses the
approved domain
`solarplexus-mobius/milestone-7.7/checkpoint-6/azure-topology-preflight/v1`
and its artifact-specific subdomains with SHA-256.

A checksum is not a signature. Evidence must use RFC 3339 UTC timestamps with
second precision and expires exactly 24 hours after the earliest observation.
The verifier rejects stale, future-dated, malformed, mixed-scope,
over-projected, incomplete, duplicate, conflicting, sensitive, or tampered
evidence.

Allowed infrastructure-gate states are `proved`, `unproved`, `blocked`, and
`failed`. All ten infrastructure gates require an evidence-backed state and
explanation. The five runtime gates remain `unproved`; topology metadata
cannot resolve them.

## Sanitized topology preflight result

| Field                    | Recorded value                                                     |
| ------------------------ | ------------------------------------------------------------------ |
| Evidence ID              | `m7.7-cp6-20260730-195532z`                                        |
| Integrity SHA-256        | `f2af5b10703f0f0a88237e1e8f154b330b3f5a9c656aa900a3b397ed851f7a4a` |
| Classification           | `complete-with-provisioning-blocked`                               |
| Proved operation         | `current-account-context`                                          |
| Cloud                    | `AzureCloud`                                                       |
| Default context          | `true`                                                             |
| Account state            | `Enabled`                                                          |
| Subscription fingerprint | matched                                                            |
| Tenant fingerprint       | matched                                                            |
| User type                | `user`                                                             |
| Azure mutation           | `false`                                                            |
| Data-plane access        | `false`                                                            |
| Raw output retained      | `false`                                                            |
| Raw identifiers retained | `false`                                                            |
| Observed                 | `2026-07-30T19:55:32Z`                                             |
| Verified                 | `2026-07-30T19:55:33Z`                                             |
| Evidence expiry          | `2026-07-31T19:55:32Z`                                             |

Raw subscription and tenant identifiers existed only in process memory. They
were fingerprinted immediately, discarded, and never displayed or written.

The integrity SHA-256 identifies the validated in-memory canonical evidence
package. It is not the hash of this documentation file. The complete canonical
evidence object existed only in memory; the repository preserves this
sanitized report, not that complete object.

The record was produced against the earlier operation inventory with integrity
SHA-256
`6d8047c2a89bdbe96d3962db5dc2f66eda8e753a02be2d85591b4fa6fe061362`
and scope integrity SHA-256
`cc47f0d150953f1df026a40432573372ba41d4c84fb9a39a96dc0fda8ac20cb5`.
Defining the two resource-group operations changes those values to:

- operation inventory:
  `923cbf934040405fd1702b49bd79d876ee3e85fe88d68bbb3d94f980fa45b843`;
- scope:
  `a98776f4d2ea33f64e28514fc7c13d2e6160a79ea29247f79fc71f4ffe529e3e`.

The historical evidence remains unchanged, is non-authoritative for execution
under the revised inventory, and does not authorize reusing its result. A new
Azure preflight requires separate authorization. Provisioning remains blocked.

## Closed operation inventory

The versioned inventory is default-deny and contains 18 exact operation slots:

1. `current-account-context` — defined;
2. `regional-service-availability` — blocked;
3. `provider-registration-api-versions` — blocked;
4. `target-group-existence` — defined locally; not executed;
5. `cleanup-group-existence` — defined locally; not executed;
6. `regional-sku-capabilities` — blocked;
7. `subscription-quota-bounded-usage` — blocked;
8. `private-endpoint-network-support` — blocked;
9. `private-dns-prerequisites` — blocked;
10. `managed-identity-support` — blocked;
11. `scoped-rbac-prerequisites` — blocked;
12. `telemetry-diagnostic-prerequisites` — blocked;
13. `evidence-retention-prerequisites` — blocked;
14. `scanner-result-bridge-prerequisites` — blocked;
15. `external-test-provider-prerequisites` — blocked;
16. `bounded-cost-budget-prerequisites` — blocked;
17. `provisioning-dependency-blockers` — blocked;
18. `private-acr-source-prerequisites` — blocked.

The current-account context operation retains its exact established Azure CLI
template. The separately authorized historical preflight executed that
operation and it passed at the recorded verification time. It was limited to
`az account show`, a minimum six-field projection, and immediate
domain-separated fingerprinting of the two identifiers.

The two resource-group operations use only the official Microsoft Learn
[`az group exists`](https://learn.microsoft.com/en-us/cli/azure/group?view=azure-cli-lts#az-group-exists)
Core, GA command contract:

`az group exists --name {exact_resource_group_name} --subscription {verified_subscription_id} --only-show-errors --output tsv`

The operation identity binds each exact group name from the scope contract.
Before future execution, the raw subscription identifier must match the
committed fingerprint; it may exist only in process memory and is never
retained. An exact `false` is the sole proved-absence outcome and retains only
`exists=false`. An exact `true`, nonzero exit, timeout, blank, malformed,
mixed, duplicate, or unexpected output fails closed. The contract permits no
default subscription, group listing, broad discovery, alternate group name,
REST, SDK, PowerShell, portal, Resource Graph, or generic-resource fallback.

The remaining 15 operations lack safely committed command templates, were not
executed, and remain blocked. The contract deliberately does not invent
commands.

Every slot is control-plane-only, non-mutating, bound to approved scope, and
limited to 24-hour sanitized evidence. Unknown operations, mutating commands,
data-plane operations, token retrieval, account switching, broad discovery,
raw-output retention, and stronger authority claims fail closed.

## Exit gates

A separately authorized preflight can complete only when:

1. the active cloud and safe account fingerprints match;
2. every operation comes from the committed closed inventory;
3. every executed operation is semantically read-only verified;
4. every observation binds the same approved scope;
5. every observation is UTC and fresh;
6. only sanitized minimum-field evidence is retained;
7. schema, canonicalization, integrity, privacy, and deterministic checks pass;
8. all ten infrastructure gates have evidence-backed statuses and explanations;
9. no required observation is silently missing or replaced by assumption;
10. negative evidence and limitations remain visible;
11. all five runtime gates remain unresolved; and
12. no mutation, data-plane access, workload, fault, probe, deployment,
    migration, or service execution occurs.

Authoritative negative evidence may produce a complete preflight package with
provisioning still blocked. Missing, stale, conflicting, malformed, or
out-of-scope evidence leaves the preflight incomplete.

## Gate status

The following ten infrastructure gates remain `blocked`:

- alert destination;
- evidence retention;
- exact provider API versions;
- managed-identity environment mapping;
- OpenAI/SMTP test providers;
- private ACR source path;
- Redis custom ACL support;
- region/subscription availability;
- scanner-result bridge; and
- telemetry gateway.

The following five runtime gates remain `unproved`:

- cleanup-supervisor runtime proof;
- effect-lock runtime proof;
- fault-controller shape;
- isolated environment; and
- live-failure authorization.

No blocked or unproved gate was converted to passed, deferred, or not
applicable.

## Evidence limitations

- Exact validator command transcripts and full command output were not
  retained in the preceding response.
- No new Azure validation occurred while defining the two local templates.
- Exact cost attribution remains unproved.
- Independent post-operation Azure inventory proof remains unproved.
- The account-context evidence passed validation at its recorded verification
  time.
- Documentation after `2026-07-31T19:55:32Z` does not renew the evidence.
- The historical evidence was produced against the earlier inventory and
  cannot prove or authorize execution under the revised integrity bindings.
- A new preflight requires separate authorization.

## Local execution-path hardening

Checkpoint 6 now has one repository-native bounded execution path for the
three defined operations. It preserves the committed command templates and
default-deny inventory, accepts no caller-selected executable or command, uses
shell-free argument vectors, permits one attempt per operation, and enforces a
30-second timeout. The account operation has a 4,096-byte combined output
ceiling; each resource-group operation has a 16-byte combined ceiling.
Timeout, oversized output, blank or mixed output, nonzero exit, malformed
projection, collision, fingerprint mismatch, or ordering failure stops the
sequence without retry or partial evidence.

The strict account parser accepts only the committed six-source-field JSON
projection, fingerprints both raw identifiers immediately, exposes only the
six safe retained fields, and keeps the raw subscription identifier only in a
private short-lived materialization context. Errors, representations,
evidence, and persistent artifacts contain neither raw process output nor raw
Azure identifiers. Python-reference release is not claimed as physical memory
erasure.

The deterministic builder accepts only validated sanitized observations,
binds the current scope and inventory hashes, retains the other 15 operations
as blocked, preserves all five runtime gates as unproved, enforces the 24-hour
evidence window, and uses the existing canonical JSON and domain-separated
integrity rules. The orchestrator validates the complete package before an
atomic no-overwrite evidence write. Its dry-run path validates local contracts
without resolving or invoking Azure CLI.

This hardening pass used only controlled fake process adapters and local
validation. It ran no Azure command, contacted no network service, produced no
new Azure evidence, and did not change the scope contract, inventory,
historical evidence, application, worker, frontend, provider, migration,
dependency, lock, Bicep, or infrastructure state. Execution remains subject
to separate authorization.

## Local process-start diagnosis and repair

The first execution authorized against the revised inventory returned exactly:

`{"errorCode":"process-start-failed","evidenceWritten":false,"provisioningAuthorized":false,"status":"failed"}`

The runner invocation occurred once. Its child process did not start, neither
resource-group operation ran, no raw Azure output or identifier was obtained,
no evidence was written, and no retry occurred.

Sanitized local diagnosis then proved:

- harmless child-process creation succeeds with the adapter's Windows process
  flags and standard-stream configuration;
- `az` is present but resolves to a `.cmd` command wrapper;
- the installation exposes no `az.exe`;
- the wrapper matches the approved Microsoft MSI Azure CLI module-launch
  pattern and has checksum
  `f24c501b242614afa989acf22719c816be87e7ac1ff8ff84c5fa200751f30fe2`;
- its adjacent native `python.exe` exists; and
- the committed adapter attempted to pass bare `az` directly to Windows
  process creation with `shell=False`.

The cause was therefore a repository Windows-launcher defect, not a general
child-process, creation-flag, or permission failure. The repair keeps
`shell=False`, validates a closed launcher name, type, size, checksum, and
layout, rejects `.bat` and altered wrappers, and invokes only the adjacent
native runtime with fixed `-IBm azure.cli` arguments. The committed Azure
arguments and operation order, one-attempt rule, time and output limits,
non-interactive input, sanitized errors, and default-deny inventory are
unchanged.

The repair used only synthetic launchers, fake process adapters, and the
network-incapable dry run. The focused execution suite passed 51 tests. The
complete Checkpoint 1–6 suite passed 560 tests with one existing skip. Ruff
and strict mypy passed for the affected production path. Azure CLI was never
started during diagnosis, repair, or validation, and the preflight was not
retried. A new execution requires separate authorization.

## Local boundary

The scope-definition continuation changes only the isolated preflight
inventory, scope binding, local framework and closed execution path, focused
tests, and directly affected Checkpoint 6 documentation. It changes no
application, worker, frontend, provider, migration, dependency, lock, runtime
configuration, Bicep topology, or infrastructure resource.

Checkpoint 6 now has a valid sanitized preflight result classified
`complete-with-provisioning-blocked` only as historical evidence for the
earlier inventory. The revised inventory has not completed execution.
Checkpoint 6 remains incomplete pending a separately authorized retry.
Provisioning remains blocked, Milestone 7.7 remains in progress, and
Checkpoint 7 and Milestone 7.8 remain unstarted.
