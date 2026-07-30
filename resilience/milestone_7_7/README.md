# Milestone 7.7 Local Failure-Injection Framework

This package implements Checkpoint 4's provider-neutral planning and
validation boundary. It defines which later failure exercises are required,
their hard limits, prerequisites, expected outcomes, assertions, evidence,
rollback, cleanup, and abort conditions.

It does not execute a fault. It has no network, process, Azure, provider,
database, application, deployment, or infrastructure mutation client.

## Contract boundary

The strict `mobius.m7.7.failure-plan.v1` plan binds:

- the clean Checkpoint 3 source commit;
- the immutable Checkpoint 1 bundle checksum;
- the Checkpoint 2 manifest, request-plan, and result hashes;
- the Checkpoint 3 evidence-package hash;
- the domain-separated scenario-catalog hash;
- local-only environment, execution, and claim classifications;
- fixed false execution, provisioning, network, and destructive authority;
- all workload, cost, lifetime, evidence, and concurrency ceilings;
- exact scenario, gate, evidence-state, limitation, and safety inventories;
- the verifier version; and
- a domain-separated semantic plan hash.

The package reuses Checkpoint 2 strict JSON, Unicode-NFC canonicalization,
duplicate-key rejection, non-finite/float rejection, safe-integer bounds, and
domain-separated SHA-256. It consumes Checkpoint 2 and Checkpoint 3 only
through their public validation contracts.

## Required scenarios

The closed catalog defines 22 future exercises:

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

Every definition has:

- a closed target and injection-method identifier;
- an objective;
- exact prerequisite gates;
- a maximum duration;
- exact isolated-synthetic scope and effect-lock safety boundary;
- expected outcome classes;
- required assertions and evidence classes;
- rollback and cleanup actions; and
- fail-closed abort conditions.

These are inert future-exercise definitions, not commands, provider
instructions, active integrations, or proof that any fault has run.

## Hard limits

The local plan fixes the following outer ceilings:

| Limit                            | Ceiling                      |
| -------------------------------- | ---------------------------- |
| Selected scenarios               | 22 required; 32 outer        |
| Concurrent faults                | 1                            |
| Attempts per scenario            | 1                            |
| Scenario duration                | 900 seconds                  |
| Total exercise duration          | 7,200 seconds                |
| Environment lifetime             | 86,400 seconds               |
| Cleanup reserve                  | 5,400 seconds                |
| Requests                         | 10,000                       |
| Request concurrency              | 128                          |
| Arrival rate                     | 100/second                   |
| Retries per request              | 2                            |
| Synthetic upload bytes           | 134,217,728                  |
| Scanner objects                  | 25                           |
| Scanner bytes                    | 26,214,400                   |
| Evidence bytes                   | 104,857,600                  |
| Provisioning block               | USD 120.00 modeled preflight |
| Absolute authorized cost ceiling | USD 150.00                   |
| Canonical plan                   | 262,144 bytes                |
| Verifier output                  | 16,384 bytes                 |

The local framework cannot spend money or execute these ceilings. They bind a
later separately approved exercise.

## Gate and claim control

All ten Checkpoint 1 gates remain unresolved. Checkpoint 4 also records five
runtime gates:

- fault-controller shape;
- isolated environment;
- live failure authorization;
- effect-lock runtime proof; and
- cleanup-supervisor runtime proof.

The local plan is complete only as a planning contract. Execution readiness is
`blocked`, Milestone 7.7 evidence is `partial`, resilience/security/cleanup
evidence remains pending, Azure/provider evidence is absent, and
observability/alert/capacity evidence remains unproved.

No schema, fixture, test double, or local verifier can resolve a gate or
upgrade those classifications.

## Safety and privacy

The schema and semantic validator require:

- isolated synthetic data only;
- exact scope and one fault at a time;
- effect lock, independent cleanup timer, manual cleanup fallback, rollback,
  zero residue, and post-revocation denial;
- fail-closed execution;
- no external target, production data, credential, network access, live
  execution, or destructive authority;
- closed evidence, assertion, scenario, gate, and limitation registries; and
- omission/rejection of secret-bearing fields, resource identifiers, local
  paths, raw bodies, endpoints, credentials, and private identifiers.

Text scanning is defense in depth, not comprehensive secret detection.
Omission and structural rejection remain required.

## Deterministic verification

From the repository root:

```powershell
$env:PYTHONDONTWRITEBYTECODE = "1"
.\.venv\Scripts\python.exe -B -m resilience.milestone_7_7.verify `
  resilience/milestone_7_7/failure-plan.example.json
```

The verifier emits one bounded canonical JSON record. It reports the plan as
valid and locally complete while keeping execution blocked and Milestone
evidence partial. Invalid input returns a closed error code without exception
text, paths, or sensitive content.

## Deliberately unimplemented

Checkpoint 4 does not implement or claim:

- Azure access, infrastructure, or provider capability;
- a load or fault-controller process;
- live load, stress, soak, failover, recovery, or failure injection;
- target discovery or resource identifiers;
- real effect-lock, rollback, cleanup, revocation, or zero-residue proof;
- alert, telemetry, provider, or managed-service evidence;
- production capacity, SLO, SLA, scale, or cost results;
- signing, publication, or independent retention; or
- any later Milestone 7.7 checkpoint or Milestone 7.8.

The next checkpoint remains separately authorized local validation. Azure
topology preflight and every live exercise remain later, independently gated
operations.
