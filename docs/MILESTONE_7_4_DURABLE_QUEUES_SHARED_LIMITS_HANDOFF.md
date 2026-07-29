# Milestone 7.4 Durable Queues and Shared Limits Handoff

Date: 2026-07-28

Status: complete locally; Milestone 7.5 remains unstarted

## Checkpoint

- Checkpoint: 7.4 — Durable Queues, Workers, Retries, and Shared Rate Limits
- Branch: `milestone-7-4-implementation-local`
- Parent: `b16bd1cdd461c2a3798d9cc256d665ed2210c2ec`
- Completion commit: this handoff's local completion commit; the exact SHA is
  reported after commit creation
- Commit message: `Implement Milestone 7.4`
- Alembic revision: `20260726_0028`
- Direct parent: `20260726_0027`
- Sole head: `20260726_0028`
- Migration Git blob:
  `55c203e669cace5be64fc25cdcf0eb8c05519198`
- Upstream: none

Milestone 7.3 remains accurately recorded as one broad run with 619 passed and
34 failed, followed by focused corrections and passing affected suites. It is
not represented as “653 passed.”

## Implemented boundary

The checkpoint extends existing systems rather than creating parallel
authority, evidence, or workflow infrastructure:

- `DurableJobService` owns idempotent create, claim, renew, complete, fail,
  cancel, recovery, deadline reconciliation, dead-letter, replay, and safe
  status.
- The PostgreSQL adapter extends document-processing jobs and uses
  `FOR UPDATE SKIP LOCKED`, bounded priority, per-workspace concurrency, and
  global concurrency.
- Request, job run, delivery, attempt, retry decision, outcome, dead letter,
  replay request, result, and publication identities remain distinct.
- Lease, cancellation, authority, and source generations plus exact deadline
  fence protected effects.
- Material transitions extend the existing Trace, job audit, domain event, and
  transactional outbox boundary in the same database transaction.
- Exact duplicate requests, completions, failures, and replays return existing
  durable identities or fail on contradictory reuse.
- Expired final attempts dead-letter once rather than entering an unclaimable
  retry state.
- The document worker renews leases in an independent transaction, commits
  document mutations only with the fenced terminal transition, and recovers
  abandoned claims.
- Ordinary APIs expose only safe scoped status and cancellation. Authorized
  workspace operators may inspect redacted dead-letter summaries and request
  replay with a new identity.

No generic workflow/agent queue table, second event outbox, browser lease
control, persistent rate-limit counter, unbounded replay, or provider receipt
payload was added.

## Migration and legacy behavior

Migration `20260726_0028`:

- evolves existing document job runs with exact user, membership, workspace,
  canvas, document, immutable version, request digest, authority,
  cancellation, source, lease, attempt, priority, deadline, result, and
  publication scope;
- creates append-only request, delivery, attempt, retry-decision, outcome,
  dead-letter, replay-request, and job-audit evidence;
- adds closed constraints, same-scope foreign keys, idempotency uniqueness,
  claim/fairness/recovery indexes, and PostgreSQL/SQLite append-only guards;
- extends the existing closed domain-event registry for durable job material
  events.

Existing rows become `legacy_backfill` job runs with one legacy attempt that
preserves the original ID, run order, status-derived outcome, safe error,
attempt count, and timestamps. The backfill does not invent a request,
delivery, worker, successful lease, authority snapshot, Trace, audit, domain
event, result, or publication.

Disposable downgrade refuses while any non-legacy durable job exists. When
only legacy rows remain, it restores the 0027 job shape and retains original
job identity and history. Historical migrations 0001–0027 were not edited.

## Shared limit contract

`SharedRateLimitService` applies one all-or-nothing decision across the
applicable network, user, workspace, resource, operation, provider, and global
dimensions:

- versioned HMAC-derived keys contain no raw IP address, user, workspace, or
  resource identifier;
- every key uses Redis hash tag `{limits}` for one atomic multi-key Lua
  operation;
- token-bucket windows implement sustained limits, bursts, refill, reset, and
  bounded TTL;
- the global dimension is a non-bypassable emergency ceiling;
- exceeded limits return safe `429`; unavailable or indeterminate state
  returns safe `503`;
- local memory is an explicit demo/development/test fake only;
- staging and production reject memory, require credential-free `rediss`,
  database zero, an exact Redis username, Microsoft Entra managed-identity
  token acquisition, a deployment-specific HMAC secret, and bounded
  connection/operation timeouts;
- no access-key, password-URL, public-network, or process-local production
  fallback exists.

In-process metric seams cover queue depth/age, claim latency, lease loss and
recovery, retries, cancellation, deadline expiry, poison/dead letter, replay,
stale-result suppression, limiter health/latency, denial, saturation,
unavailable decisions, `429`, `503`, and cost units. Milestone 7.5 owns
external telemetry, dashboards, alerts, and SLO wiring.

## Managed-store prerequisite evidence

The approved prerequisite proved an isolated non-production Azure Managed
Redis Balanced B0 in North Central US with `NoCluster`, `NoEviction`, private
endpoint/private DNS, TLS 1.3, public and access-key authentication disabled,
Microsoft Entra managed identity, an exact restricted ACL, two independent
clients, atomic Lua, 100 concurrent increments without lost updates, every
required dimension, TTL/reset/burst, `429`, simulated `503`, namespace
isolation, and no local fallback. Temporary access was revoked and all
temporary resources were removed.

No Azure operation occurred during this implementation. The local adapter and
managed-identity token path therefore require application-to-Azure
revalidation against an approved isolated staging resource before production
enablement or Milestone 7.8. The prerequisite proves the provider contract,
not a deployed application certification.

## Dependency

The production adapter adds `redis>=6.4,<7` through the existing Python
dependency declaration. The local environment resolved redis-py 6.4.0.
PyPI records its MIT license and Python support. The reviewed public advisory
records found the known redis-py async connection-cross-talk advisories fixed
in the 4.x line, so 6.4.0 is outside those affected ranges. The repository
still has no reproducible Python lockfile or built-in Python advisory command;
that pre-existing supply-chain limitation remains visible and exact resolved
production dependencies require a later reproducible audit.

## Validation record

Focused implementation validation completed before the bounded broad
campaign:

- 19 passed: durable queue/service/API, shared-limit, and SQLite migration
  scenarios;
- 1 passed: disposable PostgreSQL 17 `SKIP LOCKED` concurrency and append-only
  trigger proof;
- disposable PostgreSQL databases and roles: zero remaining after cleanup;
- initial affected backend matrix: 160 passed and 1 failed; the failure was a
  stale generic domain-event fixture that did not create a durable-job subject;
  after the test-only correction, the affected domain-event/durable-job group
  passed 23 tests;
- one bounded broad backend campaign: 652 passed, 19 failed, 14 skipped, and
  51 warnings in 18 minutes 23 seconds;
- the 19 broad failures were stale sole-head assertions/validator state and
  deployed-settings fixtures missing the new mandatory Redis configuration;
- after those bounded fixture/validator corrections, the affected groups
  passed 52 tests, exposed one remaining stale migration-count assertion, and
  that final corrected assertion passed separately;
- the broad campaign was not repeated merely to replace its accurate first-run
  result.

Additional gates:

- standalone migration validator: passed clean SQLite upgrade to 0028,
  downgrade to 0027, and re-upgrade to 0028;
- final disposable PostgreSQL 17 proof: 1 passed, with zero temporary
  databases and roles remaining;
- affected strict mypy, changed-surface Ruff lint, full Ruff formatting,
  compilation, imports, SQLAlchemy mapper configuration, dependency
  consistency, documentation Prettier, local links, migration hash/identifier
  validation, repository hygiene, whitespace, private-path, secret, and
  prohibited-scope checks: passed;
- deterministic demo reset, persisted-provenance check, API readiness,
  replay-runtime check, and web startup smoke: passed;
- frontend production files did not change, so frontend type, unit, lint,
  accessibility, production-build, and browser campaigns were not applicable
  and were not run.

One pre-existing limitation remains explicit: whole-package strict mypy found
two `str`-to-closed-`Literal` errors in the untouched Indexer route. The file's
working blob exactly matches the 7.3 parent, and no 7.4 file is implicated.
The unchanged Indexer issue was not broadened into this checkpoint. No result
is inferred from an earlier checkpoint.

Repository-wide Ruff lint also retains 50 pre-existing `I001` import-order
findings in historical migrations, migration tests, and support files. The
complete 7.4 production and new-test surface passes Ruff without an exception,
all changed Python files pass every non-`I001` rule, and all 213 API Python
files pass Ruff formatting. Historical files were not mechanically rewritten
outside this checkpoint.

## Concrete corrections during validation

- Added explicit parent-before-child flush ordering for durable requests,
  jobs, and deliveries.
- Corrected replay run ordinals to account for preserved legacy job attempts.
- Corrected disposable downgrade ordering so the request parent remains until
  the prior job schema is restored.
- Corrected expired-final-attempt recovery to dead-letter once instead of
  leaving an unclaimable retry.
- Added exact current-source fencing before claim and replay, and kept the
  replay response authorization check inside the committing transaction.
- Seeded the disposable PostgreSQL authority fixture and proved cleanup.
- Updated the generic domain-event fixture for exact durable-job subjects.
- Advanced the migration validator and historical sole-head assertions to
  0028 and completed deployed Redis settings fixtures.

## Operations

[`DURABLE_WORK_SHARED_LIMITS_RUNBOOK.md`](DURABLE_WORK_SHARED_LIMITS_RUNBOOK.md)
covers backlog, starvation, lost worker, lease loss, stale worker, graceful
and forced shutdown, retry storms, poison/dead-letter handling, replay,
cancellation, deadlines, limiter saturation, limiter outage, Redis
authentication/private-connectivity failure, safe disablement, recovery, and
escalation.

## Preserved boundaries and next checkpoint

- Server-derived user, membership, workspace, canvas, document, immutable
  version, action, and authority remain authoritative.
- Existing document, Indexer, malware, workflow, controlled-agent,
  collaboration, Trace, audit, activity, domain-event, and outbox contracts
  remain distinct.
- Rate-limit counters are ephemeral external operational state.
- No Azure resource, deployment, production data, or production credential was
  accessed or changed.
- No Git remote operation occurred.
- Milestones 7.5, 7.8, and 8.0 remain unstarted.

The next checkpoint is Milestone 7.5 — Observability and Operational Controls.
It may begin only from this committed, clean 7.4 checkpoint with sole Alembic
head `20260726_0028`.
