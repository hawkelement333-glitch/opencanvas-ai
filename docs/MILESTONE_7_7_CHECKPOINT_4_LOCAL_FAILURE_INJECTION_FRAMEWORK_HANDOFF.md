# Milestone 7.7 Checkpoint 4 Local Failure-Injection Framework Handoff

Date: 2026-07-30

Status: Checkpoint 4 complete locally; Milestone 7.7 remains in progress;
Checkpoint 5 and Milestone 7.8 are unstarted

## Checkpoint

- Checkpoint: Milestone 7.7 — Checkpoint 4 Local Failure-Injection Framework
- Branch: `milestone-7-7-implementation-local`
- Starting commit: `996e969a1e80f70e8ded5668ca80207ecfe414f8`
- Starting parent: `032957cc6bf68dd0cf16b4971cdafb6624f0303a`
- Starting commit message: `Add Milestone 7.7 evidence framework`
- Completion commit: this handoff's single local checkpoint commit; its exact
  SHA is reported after commit creation
- Commit message: `Complete Milestone 7.7 Checkpoint 4`
- Upstream: none
- Sole Alembic head: `20260726_0028`
- Migration `0028` Git blob:
  `55c203e669cace5be64fc25cdcf0eb8c05519198`
- Migration `20260726_0029`: absent

The mandatory restart boundary passed before implementation. Checkpoint 1's
34-file infrastructure bundle remained checksum
`b4f5ebbe9158d0264460158a31454e1ebf63ac038e51296c33cdfcb77b088297`.
Checkpoint 2's manifest, request-plan, and result hashes reproduced as:

- `7d8832aae03e00ec93a6203a2360555ba19b030912a406b775fc7b20630c1c26`;
- `4c13cc8b536cef325a27a0a00b4d008d164ff5d955512e599df309f69c7f32b3`;
  and
- `a98e8122f5c16a448de69f17cc6b537ea03989843805bbb584dfc620ae5d5c79`.

Checkpoint 3's evidence package remained valid at
`e88ab17245804f26d535ee225de1042ebf20d1fb6acf66e4cc755262c8e94ad1`.

## Repository-defined scope

The governing implementation plan and architecture require Milestone 7.7 to
exercise load, capacity, resilience, recovery, and infrastructure security
only after bounded workloads, evidence, authorization, effect locking,
cleanup, and managed-environment gates are proved. The approved Phase 1
sequence identifies Checkpoint 4 as the local failure-injection framework and
Checkpoint 5 as the later local validation checkpoint.

Checkpoint 4 therefore implements only an inert planning and verification
contract. It does not implement a fault controller or authorize a live
exercise.

## Implemented contract

The standard-library-only
[`resilience/milestone_7_7`](../resilience/milestone_7_7/README.md) package
provides:

- one strict closed Draft 2020-12 failure-plan schema;
- a deterministic plan bound to the exact Checkpoint 1–3 identities;
- a closed 22-scenario catalog;
- domain-separated canonical catalog and plan hashes;
- local-only environment, execution, and claim classifications;
- fixed false execution, provisioning, network, and destructive authority;
- hard workload, duration, concurrency, evidence, lifetime, and cost ceilings;
- exact gate, evidence-state, limitation, safety, rollback, cleanup, and abort
  inventories;
- structural secret, private-identifier, endpoint, path, and resource-ID
  exclusion;
- one deterministic, bounded, network-incapable verifier; and
- focused permanent API tests.

The committed plan integrity is:

`3a424ef2435853e6974007b6174147bf92ac226a6fb2cf99f502bb88b3baafa9`

The scenario catalog integrity is:

`bf38c10982a5ed3e15fe27174f0b472b44fa0e44c23d9c62f1a2e68148fac8be`

## Required scenario catalog

The closed catalog defines:

1. ambiguous commit;
2. cleanup interruption;
3. database failover;
4. dependency network delay;
5. duplicate worker;
6. external-provider failure;
7. object-storage failure;
8. partial network loss;
9. partial provider response;
10. poison job;
11. PostgreSQL connection pressure;
12. queue delay;
13. queue outage;
14. reserved control-capacity exhaustion;
15. retry storm;
16. scaling event;
17. scanner delay;
18. scanner outage;
19. service restart;
20. shared-limiter failure;
21. stale worker; and
22. worker loss.

Every scenario fixes a target class, objective, injection-method identifier,
prerequisite gates, maximum duration, isolated-synthetic scope, effect-lock
safety boundary, expected outcomes, assertions, evidence classes, rollback,
cleanup, and fail-closed abort conditions.

These definitions are not commands, provider instructions, active
integrations, or evidence that a fault has run.

## Bounds and safety

The outer limits are:

| Limit                   | Bound                         |
| ----------------------- | ----------------------------- |
| Scenarios               | 22 required; 32 outer         |
| Concurrent faults       | 1                             |
| Attempts per scenario   | 1                             |
| Scenario duration       | 900 seconds                   |
| Total exercise duration | 7,200 seconds                 |
| Environment lifetime    | 86,400 seconds                |
| Cleanup reserve         | 5,400 seconds                 |
| Requests                | 10,000                        |
| Request concurrency     | 128                           |
| Arrival rate            | 100/second                    |
| Retries per request     | 2                             |
| Synthetic upload        | 134,217,728 bytes             |
| Scanner input           | 25 objects / 26,214,400 bytes |
| Evidence                | 104,857,600 bytes             |
| Modeled provisioning    | blocked above USD 120.00      |
| Absolute cost           | USD 150.00                    |
| Canonical plan          | 262,144 bytes                 |
| Verifier output         | 16,384 bytes                  |

Execution must remain isolated, exact-scope, single-fault, effect-locked,
independently cleanup-timed, manually recoverable, fail-closed, and
synthetic-data-only. The contract requires rollback, zero-residue cleanup, and
post-revocation denial before a later exercise could claim completion.

## Gate and evidence state

All ten Checkpoint 1 gates remain unresolved:

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

Checkpoint 4 adds five unresolved runtime gates:

- cleanup-supervisor runtime proof;
- effect-lock runtime proof;
- fault-controller shape;
- isolated environment; and
- live failure authorization.

The plan is complete only as a local planning contract. Execution readiness is
`blocked`; Milestone 7.7 evidence is `partial`; resilience, security, and
cleanup evidence is `pending`; Azure and provider evidence is `absent`; and
observability, alert, and capacity evidence is `unproved`.

No local schema, fixture, test double, or verifier can resolve a gate or
upgrade those classifications.

## Deliberately unimplemented

Checkpoint 4 did not:

- contact Azure, another provider, or a Git remote;
- provision, deploy, authenticate, query, upload, download, or mutate a remote
  resource;
- run load, stress, soak, failover, recovery, or failure injection;
- add a network, process, provider, database, application, deployment, or
  infrastructure mutation client;
- select a region, SKU, resource ID, endpoint, or live target;
- create a production capacity, SLO, SLA, resilience, security, cost, cleanup,
  signing, publication, or independent-retention claim;
- install or change a dependency;
- run a migration command or add migration `20260726_0029`; or
- begin Checkpoint 5 or Milestone 7.8.

## Validation

The focused framework tests passed with 113 tests. The first run reported two
test-harness expectation defects: a prohibited local path failed during
rehashing earlier than the test expected, and a dummy bearer string did not
match the inherited scanner's deliberately specific authorization-header
pattern. Only those test fixtures were corrected; the framework behavior did
not change.

The deterministic verifier returned byte-identical successful reports across
two runs with 22 scenarios, execution blocked, network and destructive flags
false, and Milestone evidence partial. Ruff lint/format, strict mypy, direct
installed Prettier, Checkpoint 1–4 regression, marked security tests,
repository hygiene, secret/path/scope checks, and protected-state checks are
reported in the final handoff after the commit gate.

An independent external Draft 2020-12 validator remains unavailable because no
approved validator is installed. No dependency was installed to add one. Live
failure, Azure, provider, signing, publication, external retention, and
migration tests were prohibited and were not run.

## Next boundary

Milestone 7.7 remains in progress. The smallest next action is a separately
authorized Checkpoint 5 local-validation pass. Azure topology preflight and all
live exercises remain later, independently gated work. Milestone 7.8 remains
unstarted.
