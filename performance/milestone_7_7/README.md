# Milestone 7.7 Local Workload and Measurement Framework

This package defines deterministic synthetic workloads and exact measurement
semantics for later authorized Milestone 7.7 capacity and resilience
exercises. It is a local contract, not a network client, load generator,
failure injector, Azure result, production benchmark, or service-level
objective.

## Boundary

`framework.py` uses only the Python standard library. It cannot contact an
application, Azure, Git, Redis, PostgreSQL, storage, a scanner, OpenAI, SMTP,
or another provider. `dry_run.py` expands one manifest and measures an inert
logical simulation consisting only of synthetic successful observations. It
writes canonical JSON to standard output and creates no result or evidence
file.

Checkpoint 3 may later implement a separately approved bounded runner and
evidence boundary. It must not interpret Checkpoint 2 output as managed
performance evidence, a signed evidence bundle, retained evidence, or a
publication artifact.

## Contracts

- `workload.schema.json` is the closed Draft 2020-12 workload manifest schema.
- `result.schema.json` is the closed local measurement-result schema.
- `operations.json` maps closed operation identifiers to routes that exist in
  the repository. No host, scheme, credential, or external target is accepted.
- `workload.example.json` is a small mixed-workload example.
- `framework.py` validates, canonicalizes, generates, aggregates, hashes, and
  verifies the contracts.
- `dry_run.py` is the inert logical simulator.

The supported workload-type registry is:

1. `baseline`
2. `sustained`
3. `spike`
4. `bounded-stress`
5. `bounded-soak`
6. `mixed`
7. `noisy-neighbor`
8. `hostile-authorized-concurrency`
9. `horizontal-scaling-preparation`

These names describe later workload shapes. Their presence does not mean an
exercise has run. `noisy-neighbor` requires the explicit
`weighted-noisy-neighbor` tenant distribution; every other type rejects it.

## Hard ceilings

Every manifest supplies all limits and remains below these immutable
Checkpoint 2 ceilings:

| Limit                        |            Hard ceiling |
| ---------------------------- | ----------------------: |
| Logical workload duration    | 14,400,000 ms (4 hours) |
| Planned requests             |                  10,000 |
| Concurrency                  |                     128 |
| Arrival rate                 |     100 requests/second |
| Request timeout              |              120,000 ms |
| Retries per request          |                       2 |
| Synthetic request bytes      |               1,048,576 |
| Synthetic object bytes       |              16,777,216 |
| Total synthetic object bytes |             134,217,728 |
| Generated entities           |                   4,096 |
| Synthetic tenants            |                      16 |
| Measurement series           |                     256 |
| Canonical plan or result     |         4,194,304 bytes |

The output ceiling must be identical in the limits and output contracts. A
manifest is rejected if its bounded request plan cannot fit that output
budget. Phase duration/request sums, arrival capacity, concurrency, identity
cardinality, object budgets, stop thresholds, operation mix, expected outcome
classes, and load-model fields are validated together. There is no override,
force flag, or environment-variable bypass.

Production data, secrets, headers, authorization material, request bodies,
private identifiers, absolute user paths, external targets, and non-synthetic
classification are prohibited.

## Determinism and integrity

JSON parsing rejects duplicate keys, floating-point and non-finite values,
unsafe integer ranges, unknown fields, and non-NFC strings. Canonicalization:

1. requires Unicode NFC;
2. sorts object keys ordinally;
3. preserves array order;
4. emits compact UTF-8 JSON with one terminal line feed; and
5. hashes a domain-separated canonical payload with SHA-256.

The generator uses a SHA-256-derived deterministic integer stream rather than
wall-clock time, operating-system randomness, or a vendor library. The same
validated manifest, seed, registry, and generator version produce the same
manifest hash, ordered request plan, plan hash, and local result. A material
seed or operation-mix change changes the appropriate hash.

Synthetic entity tokens are domain-separated hashes with closed kind prefixes.
They are not product identities and grant no authority.

## Measurement semantics

All durations and latency samples are non-negative integer microseconds from
the logical monotonic clock. Warm-up and cool-down observations are excluded
from every aggregate and series; only the measurement phase contributes.
Samples are ordered by unique integer sequence before aggregation.

- Request count includes every measured observation.
- Success count includes only `success`.
- Failure count includes every non-success outcome.
- Timeout count is a failure subset.
- Timeout and non-timeout failure latencies are included only when their two
  explicit manifest flags are true.
- Queue depth, queue wait, retry, and saturation values are aggregated only
  when supplied by a later bounded runner.
- Throughput is milli-requests/second, calculated with integer half-up
  rounding from measured requests and logical elapsed microseconds.
- Error rate is basis points, calculated with integer half-up rounding.
- Mean latency uses integer half-up rounding.
- p50, p95, and p99 use nearest rank: sort ascending, calculate
  `ceil(percentile_basis_points * sample_count / 10,000)`, and select that
  one-based rank. There is no interpolation.
- An empty set has sample count zero and null latency summaries. A
  single-sample set returns that value for minimum, maximum, mean, p50, p95,
  and p99.

Operation rows and tenant rows are lexically sorted. Their combined count plus
the aggregate row must remain within `maxMeasurementSeries`.

Stop-condition precedence is failures, timeouts, error rate, then assertion
failure. Thresholds stop only when exceeded, not merely reached. Result
validation rechecks schema closure, aggregate arithmetic, and the
domain-separated integrity hash.

## Safe local validation

From the repository root, using the existing virtual environment:

```powershell
$env:PYTHONDONTWRITEBYTECODE = "1"
.\.venv\Scripts\python.exe -B -m performance.milestone_7_7.dry_run `
  performance/milestone_7_7/workload.example.json
.\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider `
  apps/api/tests/test_milestone_7_7_workload_measurement.py
```

The dry run explicitly reports
`executionBoundary=synthetic-local-simulator` and
`validationStatus=valid-synthetic-local`. It does not report Azure,
production, external-provider, capacity, resilience, or failure-injection
evidence.
