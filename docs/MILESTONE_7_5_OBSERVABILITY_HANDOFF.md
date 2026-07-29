# Milestone 7.5 Observability and Operational Controls Handoff

Date: 2026-07-28

Status: complete locally; Milestone 7.6 remains unstarted

## Checkpoint

- Checkpoint: 7.5 — Observability and Operational Controls
- Branch: `milestone-7-5-implementation-local`
- Parent: `3a0a9c71ef518e3033d077dcc726683daaa52b1c`
- Completion commit: this handoff's local completion commit; the exact SHA is
  reported after commit creation
- Commit message: `Complete Milestone 7.5 production observability`
- Sole Alembic head: `20260726_0028`
- Migration `0028` Git blob:
  `55c203e669cace5be64fc25cdcf0eb8c05519198`
- Migration `20260726_0029`: absent
- Upstream: none

The exact Milestone 7.4 history remains: 19 focused passes; one PostgreSQL 17
concurrency/append-only pass; an affected matrix of 160 passes and one
failure; a stale-fixture correction followed by 23 passes; one broad campaign
of 652 passes, 19 failures, 14 skips, and 51 warnings in 1103.09 seconds; a
corrected affected run of 52 passes and one failure; and one final corrected
assertion pass. The broad campaign was not repeated.

The exact Milestone 7.3 record remains 619 passes and 34 failures followed by
focused corrections and passing affected suites. It is not represented as
“653 passed.”

## Implemented boundary

`OperationalTelemetry` is the centralized provider-neutral boundary for
closed structured application/security logs, OpenTelemetry-compatible metrics,
and W3C-compatible bounded operational spans. HTTP, limiter, worker, and
provider service boundaries submit through this layer. The versioned catalog
defines the database, storage, scanner, durable-work, Indexer, event/outbox,
evidence, backup-prerequisite, capacity, cost, and exporter-health signals
used by operational collectors and dashboards.

The implementation provides:

- schema-versioned allowlisted events, fields, span names, attributes, and
  metrics;
- source and exporter-boundary redaction for credentials, tokens, cookies,
  signed URLs, identifiers, raw IP/email, private paths, content, prompts,
  responses, provider payloads, SQL values, exceptions, and hidden reasoning;
- environment/deployment/scope-bound HMAC correlation and server-derived
  request IDs;
- W3C `traceparent`, bounded baggage, sampling, span depth, links, attributes,
  events, field sizes, batches, buffers, retries, timeouts, and shutdown;
- exact metric labels, closed values, histogram definitions, and per-signal
  plus runtime cardinality budgets;
- a bounded provider-neutral HTTPS exporter and explicit memory fake for
  development/test only;
- deterministic alert firing/recovery, lower- and upper-bound comparisons,
  missing-data policy, transition deduplication, and storm prevention;
- bounded integrity findings that detect but never rewrite or repair product
  evidence;
- minimal public liveness/readiness/worker health and existing-principal plus
  server-allowlist operator health;
- stopping or stale workers reported unavailable, and existing generation-
  fenced lease loss/stale-result suppression retained;
- deployed startup rejection for disabled, memory/no-op, unauthenticated,
  unverified, placeholder, or incomplete observability configuration.

## Product evidence boundary

Operational telemetry is non-authoritative. It may reference a request, job,
delivery, attempt, worker, execution, domain event, outbox delivery, audit
record, or product Trace only through a safe scoped operational correlation.
It cannot mutate or replace product Trace, audit, activity, domain events,
outbox, durable job evidence, or authority.

Exporter failure does not roll back an otherwise valid business transaction.
Mandatory audit, Trace, event, outbox, and security evidence remains inside
the existing protected transaction and still fails that transaction if it
cannot commit. No hidden disk spool, unbounded in-memory queue, or product
telemetry table exists.

## Versioned operational artifacts

- `mobius-signals-v1`: metric purpose, type, unit, aggregation, histogram
  bounds, labels, prohibited dimensions, cardinality, owner, objective,
  dashboard, and runbook.
- `mobius-dashboards-v1`: 13 bounded internal dashboards covering service/API,
  database, storage, scanner, durable work, limiter, Indexer, providers,
  events/outbox, evidence continuity, backup prerequisites, cost/capacity, and
  the telemetry pipeline.
- `mobius-slos-v1` with objective `mobius-internal-slos-v1`: 14 provisional
  internal indicators. These are unmeasured engineering targets, not public
  SLAs or contractual commitments. Review is triggered by the first approved
  staging telemetry campaign, material topology/signal changes, or Milestone
  7.7 measurements.
- `mobius-alerts-v1`: 16 alert definitions with exact query, threshold,
  comparison, window, firing/recovery, missing-data, severity, owner,
  escalation, grouping, objective, safe diagnostics, and runbook.
- `mobius-observability-runbook-v1`: on-call, escalation, evidence, recovery,
  privacy, and every required failure scenario.

## Health, failure, privacy, and access

Public liveness has no dependency call. Public readiness checks required
database/schema, storage, shared-limiter, worker, and telemetry states but
returns only a generic ready/not-ready result. Public health contains no
topology, versions, providers, credentials, raw exceptions, or identifiers.
Operator detail requires the existing authenticated principal and a
server-owned UUID allowlist; unlisted users receive not-found.

Exporter errors, timeout, backpressure, and buffer saturation are contained.
Dropped, rejected, timeout, and failure counts are bounded and safe. Sustained
loss moves telemetry health to unavailable and makes deployed readiness fail.

Default maximum retention is 30 days for application logs, 90 for security
logs, 30 for metrics, 14 for operational spans, and 365 for incident evidence.
Destination access is least-privilege platform-operations/incident access;
application identities receive export-only authority. Environment
destinations, secret references, and pseudonymization material remain
isolated. Product analytics, advertising, profiling, surveillance, session
replay, prompt/source capture, and chain-of-thought capture are excluded.

## Validation record

Focused implementation validation:

- final observability/health/jobs/limiter/provider/deployed-config core:
  74 passed;
- an overlarge combined affected command reached its 15-minute bound without
  a pytest summary and is recorded as timed out, not passed;
- first split API/storage/Indexer/durable-work group: 157 passed and one stale
  exact-error fixture failed; its focused correction passed;
- workflow/controlled-agent group: 306 passed and two failed. One was a real
  direct provider-factory signature defect; one was a stale exact-error
  fixture after response correlation was initially added to JSON bodies.
  Correlation was retained in the response header to preserve existing body
  contracts, the direct caller was corrected, and the four exact regression
  scenarios passed;
- event/outbox/Trace/collaboration isolation group: 43 passed;
- migration runtime, permanent identifier safety, and migration tests:
  51 passed with 15 Python 3.12 SQLite datetime-adapter warnings;
- the one bounded broad backend campaign: **694 passed, 1 failed, 14 skipped,
  and 51 warnings in 1067.67 seconds**;
- the broad failure was a Milestone 7.5 regression that removed the existing
  lowercase log-level normalization while closing the setting type. The
  validator was restored; the affected settings/deployed/observability group
  then passed 49 tests;
- final lower-bound alert and stopping-worker health correction group:
  30 passed;
- the broad campaign was not repeated.

The 51 broad warnings were one Starlette `HTTP_422_UNPROCESSABLE_ENTITY`
deprecation warning, 25 `aiosqlite` Python 3.12 datetime-adapter warnings, and
25 SQLAlchemy/SQLite datetime-adapter warnings. A focused `-m postgres -rs`
run proved the 14 skips individually in `test_agent_postgres.py`,
`test_durable_jobs_postgres.py`, `test_indexer_postgres.py`,
`test_migration_0005_postgres.py`, `test_migration_0021_postgres.py`, six
cases in `test_migration_0023_0024_postgres.py`, two cases in
`test_migration_runner_postgres.py`, and `test_object_ingestion_postgres.py`.
Every skip reports that `OPENCANVAS_POSTGRES_TEST_URL` was not set to an
explicit safe test URL. The focused result was 14 skipped and 695 deselected;
no pass is inferred for a skip.

Additional gates:

- changed production/test surface: Ruff formatting and lint passed;
- nine changed production files: strict mypy passed;
- compilation, imports, and SQLAlchemy mapper configuration passed;
- standalone migration upgrade to `0028`, downgrade to `0027`, and re-upgrade
  to `0028` passed;
- permanent PostgreSQL identifier-safety validation through `0028` passed;
- dashboard/alert cross-links, bounded windows, missing-data behavior, every
  alert firing/recovery, redaction, cardinality, W3C propagation, scope
  isolation, outage/backpressure, timeout, shutdown, and product-Trace
  separation passed local tests;
- final documentation, links, dependency consistency, startup/health/demo
  smoke, hygiene, whitespace, secret/private-path, prohibited-scope, migration
  immutability, and protected-state results are recorded in the completion
  report after their final execution.

Whole-package strict mypy retains the two pre-existing untouched Indexer-route
errors. The prior 7.4 handoff recorded 50 historical repository-wide Ruff
import-order findings. The current final Ruff run found two `I001` findings,
both in untouched 7.4 files: migration `0028` and
`test_durable_jobs_migration.py`. No historical file was changed to replace or
rewrite either record. Full Ruff formatting also reported one untouched
pre-existing formatting candidate in `scripts/validate_migrations.py`;
the changed Python surface passed formatting and lint. The repository still
has no Python dependency-resolution lockfile.

## Live destination and dependency limitations

No new dependency was added. The implementation uses the current `httpx`,
`structlog`, Pydantic, FastAPI, and Python standard-library stack. The absence
of a Python resolution lockfile remains unchanged.

`pip check` passed. The package-manager wrapper for `pnpm validate:demo`
stopped before the demo because its dependency guard rejected already-
installed `sharp` and `unrs-resolver` build scripts. No build was approved and
its unintended `pnpm-workspace.yaml` suggestion was removed. Running the
existing demo script directly then passed reset, persisted-provenance check,
API readiness/runtime smoke, and the web startup smoke.

No approved isolated telemetry destination or credential was locally
available. Synthetic memory and bounded HTTP-sink behavior was validated; no
live exporter, Azure Monitor, Log Analytics, dashboard rendering, alert
delivery/recovery, destination retention, destination access/revocation, or
application-to-Azure validation is claimed.

Before production enablement or Milestone 7.8, revalidate this release against
an approved isolated destination for authentication, TLS, schema ingestion,
batching, timeout/retry/loss, readiness, retention, role revocation, dashboard
queries, alert firing/delivery/recovery, and cleanup. The separate Redis
adapter/managed-identity application path also retains its approved isolated
staging revalidation trigger.

## Preserved boundaries

- No application migration was created or edited.
- Migration `20260726_0029` remains absent.
- `20260726_0028` remains the sole Alembic head and its Git blob remains
  `55c203e669cace5be64fc25cdcf0eb8c05519198`.
- No Azure or other external resource was queried or changed.
- No deployment, publication, production data/credential use, dependency
  installation, or Git remote operation occurred.
- Protected `main`, the competition tag, five stash objects, and eight
  external recovery artifacts remain unchanged.
- Milestones 7.6, 7.7, 7.8, 8.0, and later work remain unstarted.

The next authorized checkpoint is Milestone 7.6 — Backup, Restore, Rollback,
and Disaster Recovery — only after this local completion commit is accepted.
