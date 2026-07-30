# Milestone 7.7 Aggregate Local Validation

This package implements Checkpoint 5's fully local validation boundary. It
revalidates and binds the public Checkpoint 1–4 contracts in one deterministic,
strict, bounded report.

It does not execute a workload or fault. It has no network, process, Azure,
provider, database, application, deployment, or infrastructure-mutation client.

## Contract boundary

The `mobius.m7.7.local-validation-report.v1` report binds:

- the clean Checkpoint 4 source commit;
- Checkpoint 1's infrastructure bundle checksum;
- Checkpoint 2's manifest, request-plan, and result hashes;
- Checkpoint 3's evidence-package hash;
- Checkpoint 4's failure-plan and scenario-catalog hashes;
- the Checkpoint 5 validation-requirement catalog hash;
- five actually performed aggregate contract checks;
- thirteen fail-closed rejection requirements;
- all ten infrastructure and five runtime gates as unresolved;
- the Checkpoint 3–4 evidence-state classifications;
- fixed false network, process, fault, workload, provisioning, destructive,
  external-service, and credential-use capabilities;
- the verifier version; and
- a domain-separated semantic report hash.

Local completion means only that the repository's Checkpoint 1–4 contracts
reproduce and validate together. Milestone evidence remains partial and
execution readiness remains blocked.

## Aggregate checks

The builder performs:

1. Checkpoint 1 bundle validation;
2. Checkpoint 2 fixture reproduction;
3. Checkpoint 3 evidence-package validation;
4. Checkpoint 4 failure-plan validation; and
5. cross-checkpoint binding validation.

Any mismatch fails closed before a report can be built.

## Required rejection coverage

The closed requirement catalog covers:

- absolute local paths;
- bounded output;
- claim strengthening;
- incompatible versions;
- incomplete reports;
- execution authority;
- invalid input;
- private identifiers;
- schema closure;
- secret or authorization material;
- tampering;
- traversal; and
- unknown input.

Focused tests provide the local rejection-path evidence. The report does not
claim those tests are provider observations or live execution.

## Determinism and integrity

The package reuses Checkpoint 2's Unicode-NFC, compact, sorted-key,
newline-terminated canonical JSON, strict duplicate-key handling, float and
non-finite rejection, and safe-integer bounds.

Semantic report integrity uses:

`mobius.m7.7.local-validation-report.v1\0`

The validation-requirement catalog uses:

`mobius.m7.7.validation-requirements.v1\0`

Order-insensitive registries are normalized before hashing. A material
binding, classification, capability, check, requirement, gate, evidence state,
limitation, completion state, or verifier change changes the report hash.
SHA-256 provides integrity only; it is not a signature.

## Safety and privacy

The closed schema and semantic validator reject:

- unknown or malformed fields;
- credentials, authorization material, private keys, tokens, signed URLs, and
  connection strings;
- private Azure resource identifiers and local user paths;
- request or response bodies, production content, and external targets;
- unknown, ambiguous, incomplete, tampered, or incompatible input;
- any true execution capability;
- resolved external gates or stronger evidence claims; and
- oversized reports or verifier output.

Pattern scanning is defense in depth, not comprehensive secret discovery.
Omission and structural rejection remain required.

## Deterministic verification

From the repository root:

```powershell
$env:PYTHONDONTWRITEBYTECODE = "1"
.\.venv\Scripts\python.exe -B -m validation.milestone_7_7.verify `
  validation/milestone_7_7/validation-report.example.json
```

The verifier emits one bounded canonical JSON result. It reports local
validation complete while keeping Milestone evidence partial and execution
blocked. Invalid input returns one closed error code without exception text,
paths, or sensitive content.

## Deliberately unimplemented

Checkpoint 5 does not implement or claim:

- Azure or provider access;
- topology, SKU, API-version, price, or regional validation;
- live load, stress, soak, capacity, failover, recovery, or failure injection;
- a workload or fault-controller process;
- real effect-lock, rollback, cleanup, revocation, or zero-residue proof;
- alert delivery, managed telemetry, or managed-service evidence;
- production capacity, SLO, SLA, scale, cost, or security results;
- real signing, publication, or independent retention;
- resolution of any infrastructure or runtime gate; or
- Checkpoint 6, a later Milestone 7.7 checkpoint, or Milestone 7.8.

The next checkpoint remains separately authorized Azure topology preflight.
