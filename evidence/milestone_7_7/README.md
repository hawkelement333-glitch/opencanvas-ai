# Milestone 7.7 Checkpoint 3 Local Evidence Framework

This package binds approved Checkpoint 2 workload artifacts into a strict,
bounded, deterministic local evidence package. It is repository evidence, not
application state. It does not contact Azure, Git remotes, the application, or
any external service; execute infrastructure; collect live observations; sign
data; publish data; or provide independent retention.

The committed example is deliberately classified as `synthetic-local` with
claim strength `local-contract-validation-only`. Its package state is
`complete` only for the local package contract. Its Milestone 7.7 evidence
state remains `partial`.

## Files

- `evidence-package.schema.json` is the closed Draft 2020-12 package schema.
- `evidence-package.example.json` binds the committed Checkpoint 2 example.
- `fixtures/` contains exact request-plan and measurement-result outputs from
  the Checkpoint 2 logical simulator.
- `framework.py` validates, builds, canonicalizes, hashes, and verifies local
  packages.
- `verify.py` emits one bounded machine-readable verification report.

Checkpoint 2 remains the sole owner of workload validation, deterministic plan
generation, measurement semantics, assertions, and its three integrity
domains. This framework imports its public `validate_manifest`,
`generate_plan`, `validate_result`, `canonical_bytes`, and `integrity_sha256`
contracts. It does not duplicate or reinterpret the workload engine.

## Evidence package

Version `mobius.m7.7.evidence-package.v1` binds:

- the package/schema versions, purpose, checkpoint, safe repository identity,
  exact clean source commit, and package identity;
- the Checkpoint 2 manifest, plan, and result contract versions, workload
  identity, semantic integrity hashes, generator version, measurement
  configuration, assertion outcomes, logical execution interval, and stop
  reason;
- a package-bound inventory containing exactly one manifest, plan, and result;
- environment, execution, claim, evidence-class, validation, package, and
  milestone states;
- all known local limitations and all ten unresolved Checkpoint 1 gates;
- explicitly local-only retention metadata, explicitly unsigned signature
  metadata, replacement metadata, verifier version, and package integrity.

Unknown fields and unsupported registry values fail closed. JSON parsing is
inherited from Checkpoint 2 and rejects duplicate keys, floats, non-finite
values, non-NFC text, unsafe integers, its secret/path patterns, and ambiguous
normalized keys.

## Evidence classes and claims

Every package carries the complete closed class registry:

- local deterministic validation;
- synthetic workload evidence;
- infrastructure-definition evidence;
- external-provider evidence;
- Azure execution evidence;
- observability evidence;
- alert-delivery evidence;
- capacity evidence;
- resilience evidence;
- security evidence; and
- cleanup evidence.

Each class has one explicit state from `absent`, `pending`, `partial`,
`complete`, `invalid`, `blocked`, `unavailable`, `skipped`, `failed`, or
`unproved`. Schema validity never completes a class by itself.

The local v1 package requires only local deterministic validation and synthetic
workload evidence to be complete. Stronger classes cannot be complete, and
`provider-observation` or `external-delivery` source kinds are rejected.
Generated fixtures can represent only synthetic-workload evidence. Local
simulation cannot become Azure execution, repository definitions cannot become
deployed infrastructure, and interface metadata cannot become an active
integration.

## Completeness and validation

The package and milestone use the same explicit closed state vocabulary.
Validation additionally uses `valid`. A locally complete package requires all
six closed validations to be present and `complete`:

1. schema validation;
2. Checkpoint 2 binding;
3. artifact integrity;
4. classification validation;
5. privacy-structure scan; and
6. package integrity.

A package cannot be complete when an event is missing, unknown, failed,
skipped, unavailable, blocked, partial, or unproved; a required class is
incomplete; a Checkpoint 2 assertion is not true; or its stop reason is not
`completed`. Local evidence cannot set the milestone state to `complete`.

Prior negative evidence is not overwritten in place. A replacement package
must have a new package integrity hash, bind the exact prior package hash,
select a closed replacement reason, and state that the prior record is
preserved. The original example makes no replacement claim.

## Canonicalization and integrity

The framework reuses Checkpoint 2 canonical JSON: Unicode NFC, sorted object
keys, compact UTF-8, one terminal LF, no floats/non-finite values, and
deterministic integers. Package hashing uses the separate domain
`mobius.m7.7.evidence-package.v1\0`.

Artifact, evidence-class, validation-event, limitation, gate, and assertion
registries are sorted in semantic package content where order has no meaning.
Changing their order does not change the semantic package hash. Any material
value, binding, classification, state, inventory entry, assertion, or
limitation does.

Each artifact binds:

- the evidence package identity;
- a unique artifact identity and role;
- a safe repository-relative logical name;
- media type;
- exact byte size;
- SHA-256 content hash; and
- the applicable Checkpoint 2 semantic integrity hash.

Verification rejects missing, modified, substituted, truncated, duplicated,
conflicting, stale/cross-package, unexpected-role, or semantically inconsistent
artifacts. It rejects absolute paths, drive/device or URI forms, traversal,
backslashes, ambiguous normalization, more than 12 path components, and
symlinked paths or escapes.

SHA-256 is an integrity checksum, not a signature. The package never labels a
checksum as cryptographic signing.

## Bounds

| Surface                 | Ceiling                         |
| ----------------------- | ------------------------------- |
| Canonical package       | 512 KiB                         |
| Package metadata        | 256 KiB                         |
| Artifact count          | 32; v1 semantics require 3      |
| One artifact            | 4 MiB                           |
| Total inventoried bytes | 16 MiB                          |
| Identifier              | 128 characters                  |
| Logical artifact name   | 240 characters / 12 components  |
| Labels                  | 8; v1 uses 5 closed labels      |
| Validation events       | 64 outer; v1 schema requires 6  |
| Assertions              | 64                              |
| Known limitations       | 32; v1 requires 9 closed values |
| Verifier output         | 64 KiB                          |

Checkpoint 2’s stricter workload and result ceilings continue to apply.

## Privacy and rejection

The schema admits only bounded aggregates, synthetic tokens, hashes, safe
classification metadata, and repository-relative logical names. It has no
fields for raw headers, cookies, bodies, prompts, responses, user content,
credentials, connection strings, private keys, signed URLs, private Azure
resource identifiers, or external destinations.

Structural field denial and bounded pattern scanning reject common API-key,
token, authorization/cookie, connection-string, private-key, signed-URL, Azure
resource-ID, JWT-shaped, and local-user-path forms. This is defense in depth,
not a claim of comprehensive secret detection. Omission and rejection remain
the rule; broad substitution/redaction is not used.

The example contains only isolated synthetic identifiers. No production,
customer, personal, provider-operational, or protected recovery content is
copied into the package.

## Retention and signing boundary

The v1 schema is intentionally fixed to:

- `local-only` repository lifecycle retention;
- no independent protection;
- no immutable provider storage;
- no legal hold;
- no external location; and
- `unsigned` / `none` with no key reference or signature value.

This records the provider-neutral metadata boundary without simulating a
provider receipt, key custody, upload, independent administration, signing,
immutability, publication, or legal hold. A later separately authorized schema
version must define and validate any real provider, signer, trust root, key
lifecycle, external receipt, or independently retained destination.

## Local verification

From the repository root:

```powershell
$env:PYTHONDONTWRITEBYTECODE = "1"
.\.venv\Scripts\python.exe -B -m evidence.milestone_7_7.verify `
  evidence/milestone_7_7/evidence-package.example.json `
  --artifact-root .
```

Success emits one deterministic compact JSON object with `status=valid`,
`syntheticLocalOnly=true`, `networkAccess=false`, `destructive=false`,
`packageState=complete`, and `milestoneState=partial`. Failure emits the closed
code `package-verification-failed` without paths or exception details.

The command is read-only, network-incapable, non-destructive, and bounded. It
does not build, collect, upload, publish, poll, or replace evidence.

## Deliberately unimplemented

- Azure, staging, managed-service, or production-like execution;
- live load, capacity, stress, soak, resilience, or failure injection;
- provider polling or collection;
- application, database, queue, storage, Redis, scanner, OpenAI, SMTP, alert,
  or telemetry access;
- real signing or a signing test double;
- external publication or independently protected retention;
- production capacity/SLO/SLA claims;
- infrastructure gate resolution;
- Checkpoint 4 or Milestone 7.8.

All ten Checkpoint 1 gates remain unresolved. In particular, evidence retention
has not been selected or validated.
