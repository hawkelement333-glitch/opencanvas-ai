# Milestone 7.7 Checkpoint 3 Local Evidence Framework Handoff

Date: 2026-07-30

Status: Checkpoint 3 complete locally after a separately authorized fully
offline recovery; Milestone 7.7 remains in progress; Checkpoint 4 and
Milestone 7.8 are unstarted

## Checkpoint

- Checkpoint: Milestone 7.7 — Checkpoint 3 Local Evidence Framework
- Branch: `milestone-7-7-implementation-local`
- Starting commit: `032957cc6bf68dd0cf16b4971cdafb6624f0303a`
- Starting parent: `6a4bc94744919f28ff0286e543097fb96b8a1e89`
- Starting commit message:
  `Add Milestone 7.7 workload measurement framework`
- Completion commit: this handoff's single local checkpoint commit; its exact
  SHA is reported after commit creation
- Commit message: `Add Milestone 7.7 evidence framework`
- Upstream: none
- Sole Alembic head: `20260726_0028`
- Migration `0028` Git blob:
  `55c203e669cace5be64fc25cdcf0eb8c05519198`
- Migration `20260726_0029`: absent

The mandatory restart boundary passed before implementation. The Checkpoint 2
commit retained its reported 13-file, 2,950-insertion, 7-deletion scope,
standard-library-only implementation, nine route bindings, nine workload
types, deterministic identities/plans, domain-separated hashes,
network-incapable logical simulation, and bounded operation/tenant
aggregation.

The committed fixture reproduction returned the reported hashes:

- manifest:
  `7d8832aae03e00ec93a6203a2360555ba19b030912a406b775fc7b20630c1c26`;
- plan:
  `4c13cc8b536cef325a27a0a00b4d008d164ff5d955512e599df309f69c7f32b3`;
- result:
  `a98e8122f5c16a448de69f17cc6b537ea03989843805bbb584dfc620ae5d5c79`.

Checkpoint 1's 34-file infrastructure bundle remained checksum
`b4f5ebbe9158d0264460158a31454e1ebf63ac038e51296c33cdfcb77b088297`,
with provisioning false and all ten gates unresolved.

## Implemented contract

The new standard-library-only
[`evidence/milestone_7_7`](../evidence/milestone_7_7/README.md) package
provides:

- one strict closed Draft 2020-12 evidence-package schema;
- deterministic package construction from the committed Checkpoint 2 public
  manifest, plan, and result contracts;
- exact source-commit and workload/plan/result/generator/measurement/assertion
  bindings;
- a package-bound, size/hash-bound inventory containing exactly one workload
  manifest, request plan, and measurement result;
- closed environment, execution, claim, evidence-class, evidence-state,
  validation-state, completeness-state, retention, signature, and replacement
  contracts;
- domain-separated canonical semantic package hashing;
- explicit negative-state, limitation, and unresolved-gate preservation;
- structural privacy denial plus bounded sensitive-text/path scanning;
- deterministic network-incapable package verification and bounded
  machine-readable output;
- committed local synthetic plan/result fixtures and one exact package fixture;
  and
- focused permanent API test coverage.

The package does not import application code or a network/process client. It
does not collect, query, upload, publish, sign, retain externally, poll, or
execute provider or infrastructure state.

## Schema, classification, and claims

Package version `mobius.m7.7.evidence-package.v1` binds safe repository
identity, exact clean source commit, purpose/checkpoint, Checkpoint 2 semantic
identities and hashes, measurement configuration and assertions, logical
start/end, stop reason, artifact inventory, labels, evidence classes,
validation events, completeness, limitations, gates, retention/signature/
replacement metadata, verifier version, and package integrity.

The complete evidence-class registry is:

1. local deterministic validation;
2. synthetic workload evidence;
3. infrastructure-definition evidence;
4. external-provider evidence;
5. Azure execution evidence;
6. observability evidence;
7. alert-delivery evidence;
8. capacity evidence;
9. resilience evidence;
10. security evidence; and
11. cleanup evidence.

Each class records exactly one of `absent`, `pending`, `partial`, `complete`,
`invalid`, `blocked`, `unavailable`, `skipped`, `failed`, or `unproved`.
Schema validity alone never completes an evidence class.

The local fixture requires only local deterministic validation and synthetic
workload evidence to be complete. Stronger evidence classes cannot be
complete; provider/external source kinds are rejected; generated fixtures
cannot become observed provider output. Environment is fixed to
`synthetic-local`, execution to `local-deterministic-validation`, and claim
strength to `local-contract-validation-only`.

The package state `complete` therefore means only that the local evidence
package is internally valid and complete. The Milestone 7.7 evidence state is
`partial`. The framework cannot produce Azure, staging, managed-service,
production-like, production-capacity, SLO, SLA, deployed-infrastructure,
active-integration, alert-delivery, provider-observation, signed, published, or
independently retained evidence.

## Completeness and negative-state preservation

The package requires exactly six complete validations: schema, Checkpoint 2
binding, artifact integrity, classification, privacy structure, and package
integrity. A missing, unknown, failed, skipped, unavailable, blocked, partial,
or unproved required check prevents completion.

Completion also fails closed on:

- missing/extra/conflicting artifacts;
- source or integrity mismatch;
- failed or unverified Checkpoint 2 assertions;
- a stop reason other than `completed`;
- environment/claim misclassification;
- prohibited fields or values;
- exceeded inventory, metadata, or output bounds; or
- a stronger-evidence or independent-retention claim.

The fixture preserves `absent`, `partial`, `unavailable`, and `unproved`
evidence states, nine mandatory limitations, and all ten unresolved
infrastructure gates. Replacement is append-only by contract: a replacement
must bind the exact prior package hash, use a closed reason, and state that the
prior record remains preserved. The original fixture makes no replacement
claim.

## Integrity and artifact bounds

The framework reuses Checkpoint 2's Unicode-NFC, compact, sorted-key,
newline-terminated UTF-8 canonical JSON and its strict duplicate-key,
float/non-finite, unsafe-integer, and normalization rejection.
Package integrity uses the independent domain:

`mobius.m7.7.evidence-package.v1\0`

Registries whose order is semantically irrelevant are sorted before package
hashing. Any material binding, classification, assertion, state, artifact,
limitation, or gate change changes the semantic hash. The committed example
package hash is:

`e88ab17245804f26d535ee225de1042ebf20d1fb6acf66e4cc755262c8e94ad1`

Every artifact binds the package ID, unique artifact ID/role, logical path,
media type, byte size, content SHA-256, and Checkpoint 2 semantic hash.
Verification rejects modified, missing, duplicated, substituted, truncated,
stale/cross-package, unexpected, or semantically inconsistent files.

Enforced outer bounds are:

- canonical package: 512 KiB;
- metadata: 256 KiB;
- artifacts: 32, with exactly three required in v1;
- individual artifact: 4 MiB;
- total artifact bytes: 16 MiB;
- identifier: 128 characters;
- logical name: 240 characters and 12 path components;
- labels: eight outer, with five fixed in v1;
- validation events: 64 outer, with exactly six allowed in v1;
- assertions: 64;
- limitations: 32, with nine fixed in v1; and
- verifier output: 64 KiB.

Logical names reject absolute/drive/device/URI forms, traversal, backslashes,
ambiguous normalization, depth overflow, duplicate normalized names, symlinks,
and resolved escapes.

## Privacy, retention, and signing

The schema has no raw-header, cookie, request/response body, prompt, output,
user-content, credential, token, connection-string, private-key, signed-URL,
private Azure identifier, external target, or provider receipt field.
Structural denial and bounded pattern scans cover common secret, token,
authorization/cookie, connection-string, private-key, signed-URL, JWT-shaped,
Azure-resource-ID, and machine-user-path forms.

This is defense in depth, not comprehensive secret discovery or general
redaction. Omission and rejection remain required. The fixture contains only
isolated synthetic tokens and committed repository contract data.

Retention is fixed to local repository lifecycle only: no independent
protection, provider immutability, legal hold, or external reference.
Signatures are fixed to unsigned/none with no key or signature value. SHA-256
is described only as integrity, not signing. No signer test double, real key,
provider receipt, upload, publication, or external storage was created.

## Local verification

The deterministic verifier command is:

```powershell
$env:PYTHONDONTWRITEBYTECODE = "1"
.\.venv\Scripts\python.exe -B -m evidence.milestone_7_7.verify `
  evidence/milestone_7_7/evidence-package.example.json `
  --artifact-root .
```

It emits one compact bounded report with local-synthetic status, package and
milestone completeness, network/destructive flags, and a closed error code.
It does not expose paths or exception text on failure.

## Validation

| Check                                           | Result                                        |
| ----------------------------------------------- | --------------------------------------------- |
| Focused Checkpoint 3 tests                      | PASS — 66 passed, 1 symlink-permission skip   |
| Combined Checkpoint 1–3 tests                   | PASS — 214 passed, 1 symlink-permission skip  |
| Marked security/privacy tests                   | PASS — 77 passed, 868 deselected              |
| Deterministic example verification              | PASS                                          |
| Checkpoint 2 fixture reproduction               | PASS — all three reported hashes              |
| Checkpoint 1 preflight                          | PASS — original bundle and ten gates          |
| Ruff formatting and lint                        | PASS                                          |
| Strict mypy for evidence source modules         | PASS                                          |
| Installed local Prettier                        | PASS — no network wrapper used                |
| Repository hygiene                              | PASS — 479 source files                       |
| Independent external Draft 2020-12 validator    | UNAVAILABLE — no approved validator installed |
| Real signing/provider/external-retention checks | NOT RUN — prohibited and deliberately absent  |
| Migration execution/validation script           | NOT RUN — prohibited                          |

The first focused test command used pytest's default Windows temporary root
and reported nine setup errors because that root denied access. It also found
three focused test-expectation defects. The same coverage then used the
approved short workspace temporary path; the expectation defects were
corrected and the focused suite passed. The one remaining skip is the Windows
account's inability to create a test symlink; path-resolution and symlink
rejection remain implemented and statically covered.

The first marked security run exceeded the command-result window and left its
child process holding the short temporary SQLite files. An immediate retry in
that same directory reported 27 passes and 50 setup errors caused by the
locked files. A clean run in a fresh short directory passed all 77 selected
tests with 868 deselected. Both temporary directories were removed. The
separately authorized recovery repeated that selection successfully with
`77 passed, 868 deselected`. The full repository suite was not run and is not
claimed.

## Boundary deviation and offline recovery

During the completion audit, `pnpm exec prettier --check` attempted to retrieve
pnpm metadata from `https://registry.npmjs.org/pnpm`. The request failed, the
wrapper aborted, no tool or dependency was installed, and no package or lockfile
changed. The already-installed local Prettier executable then passed the same
format check without using the wrapper.

The attempted registry access is nevertheless a prohibited network operation
under the original Checkpoint 3 authorization. That run correctly withheld the
completion commit. A separate recovery authorization then verified the exact
13-file candidate and repeated every applicable commit gate fully offline. It
used the installed Python, pytest, Ruff, mypy, Node, and Prettier files
directly; it did not invoke `pnpm`, `npm`, `npx`, `corepack`, a package-manager
wrapper, Azure, a Git remote, or another network operation.

The recovery's first direct `pytest.exe` invocation did not put the repository
root on Python's import path and stopped at collection with
`ModuleNotFoundError: evidence`. The established installed-Python
`-m pytest` entry point then passed the unchanged focused suite. The first
Checkpoint 2 reproduction one-liner passed strings to a public loader that
requires `Path` objects; the corrected invocation reproduced all three
reported hashes. Neither invocation error changed source or dependencies.

Recovery validation returned:

- focused Checkpoint 3: `66 passed, 1 skipped`;
- combined Checkpoints 1–3: `214 passed, 1 skipped`;
- marked security/privacy: `77 passed, 868 deselected`;
- two byte-identical successful verifier reports with package integrity
  `e88ab17245804f26d535ee225de1042ebf20d1fb6acf66e4cc755262c8e94ad1`;
- Checkpoint 1 bundle preflight and Checkpoint 2 reproduction: pass;
- Ruff, strict mypy, direct installed Prettier, repository hygiene, local-link,
  diff, whitespace, residue, scope, and sensitive-content checks: pass.

## Prior Checkpoint 2 deviation

Checkpoint 2 previously ran the migration-validation script against disposable
SQLite state. That disclosed action is not reclassified or hidden. Checkpoint
3 did not repeat the script, execute a migration upgrade/downgrade, or use a
database. It verified only source state, the immutable `0028` blob, the absent
`0029` path, and the sole Alembic head through non-mutating inspection.

## Remaining gates and exclusions

All ten Checkpoint 1 gates remain unresolved:

1. region and subscription availability;
2. exact provider API versions;
3. managed-identity environment mapping;
4. Redis custom ACL support;
5. private ACR source path;
6. telemetry gateway;
7. scanner-result bridge;
8. alert destination;
9. OpenAI/SMTP test providers; and
10. evidence retention.

Checkpoint 4, live/managed workload execution, Azure/provider collection,
failure runners, exact capacity and production objectives, real signing,
external publication/retention, and Milestone 7.8 remain unauthorized and
unstarted.

## Protected boundary

- No Azure operation or authentication occurred.
- No Git remote was contacted.
- The original run's formatter wrapper attempted and failed an npm-registry
  request. The recovery made no internet request and invoked no package-manager
  wrapper. No dependency or tooling was installed, and no package or lockfile
  changed.
- No application, worker, frontend, runtime, migration, lockfile, or
  infrastructure-execution behavior changed.
- Migration `20260726_0029` was not created.
- Protected references, five stashes, and eight recovery artifacts remained
  outside the write scope.
- Checkpoint 1's bundle and Checkpoint 2's public contracts remain unchanged.
- No real signing, publication, provider collection, or independent retention
  occurred.
- Checkpoint 4 and Milestone 7.8 remain unstarted.

The next eligible action, only after separate authorization, is Checkpoint 4
from the exact Checkpoint 3 completion commit. This handoff does not authorize
it.
