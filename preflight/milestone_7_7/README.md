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
result. They were executed once through the bounded production entry point in
the recorded Checkpoint 6 preflight. The other 15 slots are intentionally
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

On Windows, the adapter still keeps `shell=False`. It accepts only native
`az.exe` or the checksum-approved Microsoft MSI `az.cmd` wrapper. For the
approved wrapper, it rejects the command shell and invokes only the wrapper's
adjacent native `python.exe` with fixed `-IBm azure.cli` arguments followed by
the already approved Azure argument vector. An absent, altered, differently
named, oversized, or differently located launcher fails closed without
retaining its path.

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

The local hardening pass executed no Azure command.

The first separately authorized invocation failed before Azure CLI started
because the Windows installation exposed only `az.cmd`, while the original
shell-disabled adapter attempted to start bare `az` as a native executable.
The targeted local repair above was validated without retrying Azure. It does
not authorize another execution.

The earlier separately authorized preflight proved only
`current-account-context`; that historical in-memory evidence remains
non-authoritative for the revised inventory.

The later separately authorized production invocation executed the three
defined operations exactly once and in committed order. The account context
matched, both exact resource-group checks returned `false`, and the complete
sanitized evidence was atomically persisted as:

`evidence/m7.7-cp6-20260731-023407z.json`

Its classifier result is `complete-with-provisioning-blocked`. Schema,
integrity, deterministic-reproduction, privacy, freshness, completeness, and
tamper validation passed. No Azure mutation, data-plane access, retry, direct
additional Azure command, blocked operation, or raw-output persistence
occurred. Checkpoint 6 is complete under the committed exit rule. The other 15
operation slots and all ten infrastructure gates remain blocked; all five
runtime gates remain unproved. Provisioning, Checkpoint 7, and Milestone 7.8
remain unstarted and require separate authorization.
