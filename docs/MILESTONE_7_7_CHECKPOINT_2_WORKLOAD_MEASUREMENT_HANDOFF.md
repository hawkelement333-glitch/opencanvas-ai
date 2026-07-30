# Milestone 7.7 Checkpoint 2 Workload and Measurement Handoff

Date: 2026-07-30

Status: Checkpoint 2 complete locally; Milestone 7.7 remains in progress;
Checkpoint 3 and Milestone 7.8 are unstarted

## Checkpoint

- Checkpoint: Milestone 7.7 — Checkpoint 2 Local Workload and Measurement
  Framework
- Branch: `milestone-7-7-implementation-local`
- Starting commit: `6a4bc94744919f28ff0286e543097fb96b8a1e89`
- Starting parent: `1aca65c4a1d131dd420154efbe36e2c2204c3903`
- Starting commit message:
  `Add Milestone 7.7 infrastructure policy manifest`
- Completion commit: this handoff's single local checkpoint commit; its exact
  SHA is reported after commit creation
- Commit message: `Add Milestone 7.7 workload measurement framework`
- Upstream: none
- Sole Alembic head: `20260726_0028`
- Migration `0028` Git blob:
  `55c203e669cace5be64fc25cdcf0eb8c05519198`
- Migration `20260726_0029`: absent

The restart boundary, protected `main` and `competition-demo-v1` references,
five stash identities, eight recovery artifacts, Checkpoint 1's 36-file
commit, 34-file infrastructure bundle, bundle checksum, and ten unresolved
gates matched before implementation. Checkpoint 1's checksum-closed
infrastructure directory was not changed.

## Implemented contract

The standard-library-only framework under
[`performance/milestone_7_7`](../performance/milestone_7_7/README.md)
provides:

- strict versioned workload and measurement-result schemas;
- a closed registry of nine routes verified against the current API source;
- deterministic manifests, synthetic entity tokens, weighted request plans,
  canonical serialization, and domain-separated SHA-256 integrity;
- nine workload-type definitions: baseline, sustained, spike, bounded stress,
  bounded soak, mixed, noisy neighbor, hostile authorized concurrency, and
  horizontal-scaling preparation;
- deny-by-default limits for runtime, request count, concurrency, arrival rate,
  timeout, retry, bytes, entities, tenants, series, and output size;
- exact integer measurement semantics for counts, throughput, error rate,
  latency, queue values, retries, saturation, and tenant/operation
  aggregation;
- nearest-rank p50, p95, and p99 independent of provider dashboards;
- deterministic stop and assertion contracts;
- a bounded stdout-only logical simulator; and
- focused permanent API test coverage.

The framework does not import application code or a network/process client.
It cannot call Azure, Git, the application, Redis, PostgreSQL, storage,
scanner, OpenAI, SMTP, alerts, or another external provider. It creates no
files or generated state during its dry run.

## Safety and privacy

The closed manifest requires isolated synthetic classification and explicit
prohibitions on production data, secrets, and external targets. Headers,
request bodies, raw identifiers, and external targeting are fixed off.
Validation rejects unknown or missing fields, floats, non-finite values,
duplicate JSON keys, non-NFC text, unsafe integers, negative values, unsupported
routes/outcomes, secret-like text, private user paths, contradictory phase or
load bounds, repeated operations, excess cardinality, and output plans that
cannot fit their declared budget.

The detailed hard-ceiling table is in the framework README. Notable outer
ceilings are four logical hours, 10,000 planned requests, concurrency 128, 100
arrivals/second, two retries, 16 synthetic tenants, 256 measurement series,
128 MiB total synthetic object bytes, and 4 MiB canonical output. These are
Checkpoint 2 contract ceilings, not tested managed capacity or promised
production limits.

## Measurement semantics

Measurements use integer microseconds from a logical monotonic clock. Warm-up
and cool-down are excluded. Timeout and other failure latencies use two
explicit inclusion flags. Throughput, error rate, and mean use integer half-up
rounding. Percentiles sort samples ascending and select the one-based
`ceil(p * n)` nearest rank, with p represented in basis points. Empty sets
return null summaries; a single sample is all six latency summaries.

Results sort observations by unique sequence, then operation and tenant rows
lexically. Results contain only bounded aggregates, safe logical run metadata,
manifest/plan identities, closed assertions, stop reason, validation status,
and a domain-separated integrity hash.

## Evidence boundary

Checkpoint 2 output is a deterministic local measurement contract only. It is
not:

- a live load, stress, soak, resilience, or failure-injection result;
- Azure or production-like capacity evidence;
- a production SLO, SLA, supported limit, or scale decision;
- a signed or independently stored evidence bundle;
- evidence-retention, publication, or approval state; or
- Checkpoint 3 implementation.

Checkpoint 3 may consume these schemas and deterministic hashes only after a
separate authorization. It must separately own any bounded runner, evidence
schema, signing, retention, provider collection, execution authorization, and
publication boundary.

## Validation

| Check                                                                                                          | Result                                                                              |
| -------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| Focused workload and measurement tests                                                                         | PASS — 64 tests                                                                     |
| Checkpoint 1 infrastructure, limiter, durable-job, and observability regressions                               | PASS — 121 tests                                                                    |
| Canvas and object-ingestion regressions                                                                        | PASS — 19 tests in the mixed command                                                |
| Indexer and authorization regressions using a short bounded Windows test path                                  | PASS — 12 tests                                                                     |
| Graph retrieval, controlled workflow, and Agent Studio regressions                                             | PASS — 38 tests                                                                     |
| Collaboration, health, and authorization regressions                                                           | PASS after the authorization test's short-path rerun                                |
| Complete marked backend security selection                                                                     | PASS — 77 tests; 801 deselected                                                     |
| Ruff formatting and lint                                                                                       | PASS                                                                                |
| Strict mypy for the two framework source modules                                                               | PASS                                                                                |
| Closed-schema and semantic validation                                                                          | PASS through the standard-library validator and focused tests                       |
| Independent external Draft 2020-12 validator                                                                   | UNAVAILABLE — no approved existing validator is installed                           |
| Deterministic dry run repeated twice                                                                           | PASS — byte-identical canonical output                                              |
| Checkpoint 1 preflight                                                                                         | PASS — 34 files, ten unresolved gates, provisioning false, original bundle checksum |
| Migration validation                                                                                           | PASS — upgrade `0028`, downgrade `0027`, re-upgrade `0028`                          |
| Repository hygiene                                                                                             | PASS — 468 source files                                                             |
| Targeted Markdown links, formatting, diff, whitespace, private-identifier, generated-residue, and scope audits | PASS                                                                                |

One broad mixed test command initially reported nine Indexer failures, and one
later collaboration/health/authorization command reported one authorization
failure. All ten failed at document storage with the repository-root
`--basetemp` path. The same nine Indexer tests and all three authorization
tests passed when rerun with a shorter bounded temporary path under the
workspace. No source correction was made: the failure was Windows path-length
pressure in the validation harness, not a Checkpoint 2 or application defect.
Both temporary paths were removed.

The focused tests cover schema closure, every workload type, limits, phase and
mix consistency, real-route binding, determinism, input/hash mutation,
canonicalization, external-target denial, percentile fixtures,
empty/single/duplicate/reordered samples, timeout/failure accounting,
throughput, plan-bound attribution, tenant/cardinality behavior, stop
conditions, output/secret restrictions, result integrity, residue-free dry
runs, Checkpoint 1 bundle immutability, and migration absence.

The full backend suite was not rerun. No frontend, browser, managed-provider,
deployment, live-load, failure-injection, long-running stress/soak, or
Checkpoint 3 evidence execution was authorized or claimed.

## Remaining gates

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

Checkpoint 3, later managed workload execution, exact production objectives,
published capacity limits, evidence signing/retention, failure runners, Azure
deployment, and Milestone 7.8 remain separately unauthorized and unstarted.

## Protected boundary

- No Azure operation occurred.
- No Git remote was contacted.
- No dependency or tooling was installed.
- No application, worker, frontend, migration, lockfile, infrastructure
  execution, or Checkpoint 1 contract changed.
- Migration `20260726_0029` was not created.
- Protected references, stashes, and recovery artifacts remained outside the
  write scope.
- Checkpoint 3 and Milestone 7.8 remain unstarted.
