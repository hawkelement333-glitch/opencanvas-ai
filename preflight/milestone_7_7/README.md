# Milestone 7.7 Checkpoint 6 scope contracts

This directory defines the local, non-executing contract for a later,
separately authorized Azure Topology Preflight. It does not authorize Azure
access, provisioning, deployment, workload execution, or Checkpoint 7.

## Artifacts

- `scope-contract.json` binds the approved account fingerprints, regions,
  intended future resource-group names, evidence policy, gates, failure rules,
  and deferred work.
- `operation-inventory.json` is the closed, default-deny operation inventory.
- `evidence.schema.json` defines sanitized future preflight evidence.
- `framework.py` validates the scope, inventory, and future evidence with the
  existing canonical JSON and domain-separated SHA-256 implementation.
- `verify.py` emits a bounded deterministic verification report and has no
  process or network client.

The inventory contains 18 required operation slots. Only
`current-account-context` has an exact repository-verified command template.
The other 17 slots are intentionally blocked because no exact safe command
template is established by repository sources. A blocked entry cannot be
executed or upgraded by assumption.

Checksums provide deterministic integrity only; they are not signatures.
Future evidence expires 24 hours after its earliest recorded UTC observation.
Raw Azure output, raw Azure identifiers, data-plane evidence, mutation,
private operational data, and topology-based resolution of runtime gates are
prohibited.

The separately authorized preflight later proved only
`current-account-context`. Its sanitized result is:

`complete-with-provisioning-blocked`

The complete canonical evidence object existed only in memory. The repository
preserves the sanitized report in the Checkpoint 6 handoff, not that object,
and documentation does not renew the recorded evidence expiry. The other 17
operation slots and all ten infrastructure gates remain blocked; all five
runtime gates remain unproved. Provisioning, Checkpoint 7, and Milestone 7.8
remain unstarted and require separate authorization.
