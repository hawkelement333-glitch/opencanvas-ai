# Milestone 7.7 Checkpoint 6 scope contracts

This directory defines the local contract and closed execution path for a
later, separately authorized Azure Topology Preflight. The presence of the
runner does not authorize Azure access, provisioning, deployment, workload
execution, or Checkpoint 7.

## Artifacts

- `scope-contract.json` binds the approved account fingerprints, regions,
  intended future resource-group names, evidence policy, gates, failure rules,
  and deferred work.
- `operation-inventory.json` is the closed, default-deny operation inventory.
- `evidence.schema.json` defines sanitized future preflight evidence.
- `framework.py` validates the scope, inventory, and future evidence with the
  existing canonical JSON and domain-separated SHA-256 implementation.
- `execution.py` is the only production entry point for the three defined
  operations. It fixes their order, executable, argument vectors, timeout,
  output limits, parsers, privacy projection, evidence builder, and atomic
  evidence write.
- `verify.py` emits a bounded deterministic verification report and has no
  process or network client.

The inventory contains 18 required operation slots. Three have exact
repository-verified command templates: `current-account-context`,
`target-group-existence`, and `cleanup-group-existence`. The two group
operations bind exact names from the scope contract and use only Microsoft
Learn's Core, GA
[`az group exists`](https://learn.microsoft.com/en-us/cli/azure/group?view=azure-cli-lts#az-group-exists)
contract. They require an explicit in-memory subscription binding that must
match the committed fingerprint and retain only the exact boolean absence
result. They have not been executed. The other 15 slots are intentionally
blocked because no exact safe command template is established by repository
sources. A blocked entry cannot be executed or upgraded by assumption.

Checksums provide deterministic integrity only; they are not signatures.
Future evidence expires 24 hours after its earliest recorded UTC observation.
Raw Azure output, raw Azure identifiers, data-plane evidence, mutation,
private operational data, and topology-based resolution of runtime gates are
prohibited.

## Bounded execution path

The runner accepts only `current-account-context`,
`target-group-existence`, and `cleanup-group-existence`, in that order. Every
operation has one attempt and a 30-second timeout. The account projection is
limited to 4,096 combined stdout/stderr bytes; each group result is limited to
16 combined bytes. It uses argument vectors with shell execution disabled,
closed process-local Azure CLI telemetry and dynamic-extension settings,
in-memory output, no interactive input, and sanitized error codes.

The account parser requires exactly one JSON object with the committed fields,
an enabled default `AzureCloud` user context, and both approved fingerprints.
It drops the tenant identifier after fingerprinting and keeps the subscription
identifier only in a private execution context until both exact group commands
have been materialized. Releasing Python references is not represented as
physical memory erasure.

The orchestrator stops on the first failure, never retries, never chooses
alternate groups, and writes no partial evidence. After all three operations
pass, the deterministic builder retains only the committed projections,
preserves 15 blocked observations and five unproved runtime gates, validates
canonical integrity, then publishes the evidence through an atomic
no-overwrite file link.

The local-only path can be verified without resolving or invoking `az`:

```text
python -m preflight.milestone_7_7.execution --dry-run
```

A later separately authorized Azure pass must use exactly:

```text
python -m preflight.milestone_7_7.execution --execute-authorized-preflight
```

The local hardening pass executed no Azure command. Checkpoint 6 remains
blocked pending that separate authorization and execution.

The separately authorized preflight later proved only
`current-account-context`. Its sanitized result is:

`complete-with-provisioning-blocked`

The complete canonical evidence object existed only in memory. The repository
preserves the sanitized report in the Checkpoint 6 handoff, not that object,
and documentation does not renew the recorded evidence expiry. That evidence
binds the earlier inventory and is non-authoritative for the revised
inventory. A new Azure preflight requires separate authorization. The other
15 operation slots and all ten infrastructure gates remain blocked; all five
runtime gates remain unproved. Provisioning, Checkpoint 7, and Milestone 7.8
remain unstarted and require separate authorization.
