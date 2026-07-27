# Milestone 7.1 Production Runtime and Managed PostgreSQL Handoff

Date: 2026-07-26

Status: complete locally; managed-provider runtime validation not performed;
checkpoint 7.2 not started

Post-handoff compatibility note: a later isolated local PostgreSQL 17.10 and
pgvector 0.8.5 run proved that clean migration fails at historical revision
`20260718_0005` because its `workspaces` table recreation conflicts with
`canonical_objects_workspace_id_fkey`. The guarded runner can then mask that
primary error by attempting advisory unlock in the failed transaction. The
[PostgreSQL migration 0005 compatibility amendment](MILESTONE_7_POSTGRESQL_MIGRATION_0005_COMPATIBILITY_AMENDMENT.md)
authorizes a separate focused correction and validation checkpoint. This note
does not revise the original 7.1 validation ledger or claim that the
correction has been implemented.

Subsequent clean-chain diagnosis proved that migrations `20260725_0023` and
`20260725_0024` cannot safely recover closed values from
PostgreSQL-canonicalized check expressions. The
[PostgreSQL migrations 0023 and 0024 compatibility amendment](MILESTONE_7_POSTGRESQL_MIGRATIONS_0023_0024_COMPATIBILITY_AMENDMENT.md)
authorizes corrections to exactly those two migration files in the same
future combined checkpoint. Provisional `0005` and runner work remains
preserved outside the working tree and is not active.

The first combined live attempt subsequently proved a distinct PostgreSQL
type-resolution failure in `0023`'s `_backfill_resources()` derived table:
untyped null placeholders become `text` before assignment to UUID
destinations. The
[migration 0023 UUID-null compatibility amendment](MILESTONE_7_POSTGRESQL_MIGRATION_0023_UUID_NULL_COMPATIBILITY_AMENDMENT.md)
authorizes only explicit UUID typing for those PostgreSQL placeholders and
focused regression coverage. This does not revise the original 7.1 ledger or
start checkpoint 7.2.

With that typing present, the next live attempt reached `0023` trigger
installation and proved that migrations `0023` and `0024` contain four
references to an undefined mutation function. The
[trigger-function compatibility amendment](MILESTONE_7_POSTGRESQL_TRIGGER_FUNCTION_COMPATIBILITY_AMENDMENT.md)
authorizes only replacement of those references with the already-existing
equivalent deny-all trigger function and focused trigger/mutation proof. The
original 7.1 validation ledger remains historical and unchanged; checkpoint
7.2 remains blocked.

## Implemented boundary

Milestone 7.1 extends the established configuration, SQLAlchemy, Alembic,
lifespan, worker, health, Compose, and documentation boundaries. It does not
add an application schema, a provider integration, or a parallel authority
system.

- `demo`, `development`, `test`, `staging`, and `production` remain explicit.
- Staging and production require `postgresql+asyncpg`, a complete managed
  PostgreSQL URL, verified-full TLS, the release schema revision, HTTPS,
  authentication, SMTP resets, live AI/embedding providers, private durable
  storage, and the database worker.
- Database URLs are `SecretStr` values and serialize redacted.
- API and worker engines use bounded transaction pools with pre-ping, zero
  default overflow, bounded acquisition and connection timeouts, connection
  recycling, `READ COMMITTED`, and server-side statement, lock, and
  idle-in-transaction timeouts.
- PostgreSQL readiness requires major version 17, pgvector `0.7.0` or newer,
  exact Alembic head `20260725_0025`, no active migration advisory lock, and a
  non-overprivileged deployed API role.
- Liveness is dependency-free. Readiness returns one bounded
  `database_not_ready` response without URL, host, user, SQL, extension,
  topology, secret, or tenant detail and recovers when the dependency recovers.
- Startup validates configuration and the process credential role, creates
  the engine, performs the capability probe before initialization, and never
  runs migrations. A transient dependency failure leaves the process live but
  unready. Shutdown disposes the engine.
- API, worker, migration, backup, observability, and emergency credential
  declarations are closed. Deployed API and worker startup rejects a migration
  credential declaration. Runtime role validation rejects superuser, database
  creation, role creation, replication, RLS bypass, and schema creation.
- The guarded migration command uses a direct `NullPool` connection, requires
  an explicit expected current revision in staging/production, resolves the
  sole repository target, acquires one PostgreSQL session advisory lock,
  verifies current and target revisions, and releases the lock after success,
  rejection, or failure.

Application authorization remains authoritative. No RLS policy was added.
Server-derived user, workspace, canvas, membership, resource, workflow, agent,
approval, and action scope is unchanged. Existing append-only evidence,
transaction, idempotency, Trace, audit, domain-event, and activity contracts
were not weakened, and no generic mutation retry was introduced.

## Migration and dependency decision

- Application migration: none.
- Alembic sole head: `20260725_0025`.
- Revisions `0021` through `0025`: not edited.
- Revision `20260726_0026`: not created.
- Dependencies and lockfiles: unchanged; SQLAlchemy, asyncpg, Alembic, and
  pgvector already provide the required boundary.

## Provider-neutral operations

No provider hostname, account, project, credential, or proprietary API was
added. Each deployed process receives one managed secret reference whose
value becomes `OPENCANVAS_DATABASE_URL`, plus its exact
`OPENCANVAS_DATABASE_ROLE`. Verified TLS certificate and hostname validation
is mandatory in staging and production.

Credential replacement is a rolling-restart operation, not claimed hot
rotation. A replacement credential is staged, the process secret reference is
updated, replacement instances must become ready, old instances dispose their
pools, and only then is the old credential revoked. Rollback restores the
prior reference and restarts. Migration credentials rotate independently and
are never injected into API or worker processes.

## Validation boundary

Focused configuration, pool, capability, migration-lock, health recovery,
secret-redaction, demo, and migration-cycle tests were added or extended.
Offline SQLite migration validation remains evidence only for migration
structure, never for PostgreSQL production behavior.

Docker and a local PostgreSQL executable were unavailable in this environment.
Therefore PostgreSQL 17 startup, live pgvector discovery, real TLS negotiation,
real role grants, advisory-lock concurrency across processes, PostgreSQL
upgrade/downgrade/re-upgrade, append-only triggers, tenant constraints,
connection interruption, and failover were not executed. No remote or managed
database was substituted. These are explicit staging-entry validations and
must not be reported as passed by this checkpoint.

PostgreSQL `alembic upgrade head --sql` was attempted and did not pass. The
unchanged historical migrations first require a PostgreSQL JSON literal
renderer and then use batch reflection that Alembic explicitly cannot perform
in offline mode without a live connection. Bypassing that would require
editing immutable migrations or synthesizing unsafe historical table shapes,
so neither was done. Live disposable PostgreSQL migration validation remains
the authoritative unexecuted boundary.

## Local validation ledger

- Pre-change configuration/health safety baseline: 15 passed.
- Final focused runtime, migration-lock, health, worker, demo, and migration
  suite: 60 passed; 20 known Python 3.12 SQLite adapter deprecation warnings.
- Full backend regression: 544 collected; 543 passed; 1 PostgreSQL-only skip;
  61 known warnings (60 SQLite adapter deprecations and 1 Starlette HTTP status
  deprecation).
- PostgreSQL marker: 1 skipped because the approved local PostgreSQL URL and
  runtime were unavailable.
- Strict API typing: 85 modules passed.
- Changed-file Ruff lint: passed.
- Complete Python Ruff formatting and lint: passed for 190 formatted files.
- Prettier formatting: passed.
- Frontend ESLint and strict TypeScript: passed.
- Frontend Vitest: 17 files and 74 tests passed.
- Next.js production build: passed; 9 routes generated or server-bound.
- Chromium: 8 passed; 2 real FastAPI/PostgreSQL scenarios skipped because
  their external local runtime was not configured.
- Deterministic demo: reset passed, isolation/provenance check passed, API and
  web startup smoke passed.
- SQLite migration validator: upgrade to `0025`, downgrade to `0024`, and
  re-upgrade to `0025` passed.
- PostgreSQL offline DDL: attempted and failed at the unchanged historical
  boundary described above; not reported as passed.
- Python compilation, imports, and ORM mapper validation: passed.
- Repository hygiene, secret-pattern, private/local-path, generated-artifact,
  whitespace, and Git diff checks: passed.
- Prohibited later-scope production-code scan: passed.

No newly introduced warning or test failure remains. Immutable migrations were
not reformatted or edited.

## Bounded limitations and next boundary

Milestone 7.1 does not certify a managed provider, failover, backup/restore,
capacity, or public deployment. It does not implement the deterministic
Indexer, object storage/quarantine/malware scanning, durable queue expansion,
shared rate limits, observability rollout, recovery exercises, or load tests.

Milestone 7.2 remains unstarted. Its planned migration
`20260726_0026` remains absent.

Milestone 7.2 must not restart until the migration `0005`, guarded-runner,
`0023`, and `0024` compatibility corrections; exact closed-registry and
cross-migration proof; exact `0023` UUID/null resource-backfill proof; live
PostgreSQL and SQLite migration cycles; migration hash exception ledger; and
required regressions all pass.
