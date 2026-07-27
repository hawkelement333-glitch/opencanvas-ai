# Milestone 3.5 deployment and operations guide

## Current production-readiness boundary

The documentation-only
[Milestone 7 Production Hardening architecture](MILESTONE_7_ARCHITECTURE.md)
and [implementation plan](MILESTONE_7_IMPLEMENTATION_PLAN.md) now own managed
PostgreSQL validation, deterministic production indexing, secure private
object ingestion and malware quarantine, durable work, shared rate limits,
observability, recovery exercises, capacity/resilience testing, and the final
production-readiness audit.

Checkpoint 7.1 is complete locally. It implements the provider-neutral runtime
contract, but no managed service was provisioned or contacted. This guide is
not evidence that a managed database, hostile-upload controls, failover,
restore, capacity, or production security have passed. Checkpoint 7.2 remains
unstarted. Live PostgreSQL 17 validation has proved clean-install failures in
historical migrations `20260718_0005`, `20260725_0023`, and
`20260725_0024`; no deployment or migration `0026` is authorized until the
[migration 0005 compatibility amendment](MILESTONE_7_POSTGRESQL_MIGRATION_0005_COMPATIBILITY_AMENDMENT.md),
the
[migrations 0023 and 0024 compatibility amendment](MILESTONE_7_POSTGRESQL_MIGRATIONS_0023_0024_COMPATIBILITY_AMENDMENT.md),
[migration 0023 UUID-null compatibility amendment](MILESTONE_7_POSTGRESQL_MIGRATION_0023_UUID_NULL_COMPATIBILITY_AMENDMENT.md),
and their combined focused correction checkpoint pass.

SolarPlexus Mobius has five explicit runtime modes: `demo`, `development`, `test`, `staging`, and
`production`. The API validates the selected mode and all mode-dependent provider configuration at
startup. Staging and production fail closed if authentication, PostgreSQL, SMTP password reset,
OpenAI providers, S3-compatible private storage, or the database-backed worker are missing. They
never fall back to deterministic providers.

## Service topology

- `web`: non-root Next.js standalone service.
- `api`: non-root FastAPI service; serves liveness, readiness, authorized application APIs, and
  private-file proxy responses.
- `worker`: independently scalable database-backed document processor with persisted jobs,
  retries, idempotency keys, and heartbeats.
- `api-migrate`: one-shot Alembic migration task run before API/worker rollout.
- PostgreSQL with pgvector: durable relational, vector, session, job, execution, and Trace state.
- S3-compatible object storage: private original uploads in staging and production.

The repository does not require one hosting vendor. Any platform is acceptable if it provides
these service roles, private networking, TLS, managed secrets, PostgreSQL/pgvector, and private
S3-compatible object storage.

## Local production-shaped stack

The checked-in Compose stack intentionally runs `APP_MODE=development` with explicit mock AI and
embedding providers, PostgreSQL, a separate worker, persistent private file volume, migrations,
and health checks. It is production-shaped but is not a production security configuration.

```powershell
Copy-Item .env.example .env
docker compose config --quiet
docker compose up --build
```

macOS/Linux:

```sh
cp .env.example .env
docker compose config --quiet
docker compose up --build
```

Open <http://localhost:3000>. Inspect:

- API liveness: <http://localhost:8000/api/v1/health/live>
- dependency readiness: <http://localhost:8000/api/v1/health/ready>
- worker health: <http://localhost:8000/api/v1/health/worker>

The development-only database password and session secret in Compose are placeholders. Never use
them on a shared host. `docker compose down --volumes` destroys the local database and file volume.

This Compose definition is production-shaped development, not production. Docker/Compose image
builds and startup, real PostgreSQL browser tests, and live OpenAI, SMTP, and S3-compatible service
calls were not run during the final Milestone 3.5 validation and remain unverified. Do not accept
production user data until those external validations, plus the documented backup/restore and
rollback exercises, pass with dedicated non-production resources.

## Staging and production configuration

Start from `.env.example`, inject secrets through the deployment platform, and set:

- `APP_MODE=staging` or `APP_MODE=production`
- `OPENCANVAS_APP_URL=https://...`
- `OPENCANVAS_CORS_ORIGINS=["https://..."]`
- `OPENCANVAS_DATABASE_URL=postgresql+asyncpg://...`
- `OPENCANVAS_DATABASE_ROLE=api` for API processes and `worker` for workers
- `OPENCANVAS_DATABASE_TLS_MODE=verify-full`
- bounded pool, acquisition, connection, statement, lock, idle-transaction,
  and recycle values from `.env.example`
- `OPENCANVAS_AUTH_ENABLED=true`
- `OPENCANVAS_AUTH_TEST_BYPASS=false`
- a unique `OPENCANVAS_SESSION_SECRET` containing at least 32 random bytes
- `OPENCANVAS_PASSWORD_RESET_PROVIDER=smtp` and SMTP host/from address/credentials
- `OPENCANVAS_AI_PROVIDER=openai`
- `OPENCANVAS_EMBEDDING_PROVIDER=openai`
- server-only `OPENAI_API_KEY`
- `OPENCANVAS_STORAGE_PROVIDER=s3` and private bucket credentials/configuration
- `OPENCANVAS_JOB_PROVIDER=database`
- a browser-safe `NEXT_PUBLIC_API_URL=https://.../api/v1` at web build time

Use separate databases, buckets/prefixes, session secrets, SMTP credentials, OpenAI projects, and
telemetry destinations for staging and production. Never mount the demo database or demo storage
into either environment. Never set `APP_MODE=demo` in a deployed user environment.

Inject exactly one database credential into each process. API, worker, and
migration tasks use distinct least-privilege database users. API and worker
users must not be superusers, database/role creators, replication or RLS-bypass
roles, or schema creators. The one-shot migration task receives
`OPENCANVAS_DATABASE_ROLE=migration`; its credential is never injected into
normal API or worker containers. Backup, observability, and emergency
credentials remain separately controlled and are not application credentials.

Cookies are HTTP-only for the session token and secure in staging/production. TLS must terminate
at a trusted proxy or the service. Preserve `X-Request-ID` across that proxy and do not log cookie,
authorization, CSRF, SMTP, storage, or OpenAI secrets.

## Release procedure

1. Build immutable API and web images from the reviewed commit and record their digests.
2. Back up the production database and verify object-store versioning/retention.
3. Run the migration image as a one-shot task:

   ```sh
   python -m scripts.migrate --expected-current 20260725_0024
   ```

4. Deploy worker instances and wait for a fresh worker heartbeat.
5. Deploy API instances and require `/api/v1/health/live`, `/ready`, and `/worker` to pass.
6. Deploy the web image built with the production API URL.
7. Exercise sign-in, workspace isolation, authorized file access, one document job, one grounded
   execution/Trace, and one insufficient-evidence response.
8. Keep the prior images available until the observation window closes.

Do not run multiple application revisions against an incompatible schema. Migrations must finish
before new API/worker instances accept traffic.

The guarded runner verifies the repository target `20260725_0025`, verifies
the operator-declared current revision (`base` for an empty database), obtains
one PostgreSQL session advisory lock, uses a direct non-pooled connection, and
verifies the final revision. A competing runner fails safely. API and worker
readiness stays false while the migration lock is held or the schema differs.

The current runner and historical migrations must not be used to claim a
successful clean PostgreSQL installation. After a migration error, runner
cleanup can execute inside the aborted transaction and mask the primary
exception; migrations `0023` and `0024` also misread PostgreSQL-canonicalized
check expressions, and `0023`'s resource backfill exposes independently typed
`text` nulls to UUID destinations. The combined compatibility correction must
preserve the original error, prove lock release on success and failure, prove
exact closed constraint registries, and prove exact UUID/null backfill values
through `0025` before deployment validation resumes.

## Database credential replacement

Credential replacement is restart-based; hot rotation is not claimed.

1. Create a new least-privilege credential for exactly one process role.
2. Validate it in an isolated staging process with verified TLS and readiness.
3. Replace the secret reference and perform a bounded rolling restart.
4. Removed instances stop receiving work and dispose their SQLAlchemy engine;
   disposal closes the old pool.
5. Require readiness on replacement instances before shifting traffic.
6. Revoke the old credential only after old pools are drained.
7. If validation fails, restore the prior secret reference and restart; do not
   broaden privileges or inject migration credentials as a fallback.

Migration credential rotation is a separate one-shot-task procedure and never
changes API or worker secret references.

## Backup

Database backups must include roles/ownership needed for restore and be encrypted at rest. A
portable logical example is:

```sh
pg_dump --format=custom --no-owner --file=mobius.dump "$DATABASE_URL"
```

Use the managed database provider's point-in-time recovery in addition to logical backups. Enable
private object-store versioning and lifecycle retention. Record the database backup timestamp and
object-store recovery point together so document metadata and bytes can be restored consistently.
Back up deployment configuration separately without embedding secret values.

## Restore test

1. Create an isolated restore database and private restore bucket/prefix.
2. Restore the database with `pg_restore --clean --if-exists --no-owner`.
3. Restore/copy object versions matching the recorded recovery point.
4. Run `alembic upgrade head` against the restored database.
5. Start one worker and one API against the isolated restore targets.
6. Verify readiness, authorized file reads, ready-document retrieval, execution Trace records, and
   account/workspace isolation.
7. Record recovery time and any missing objects; never test restore against live production.

## Rollback

Prefer application rollback over schema downgrade:

1. Stop new web/API/worker rollout and disable incompatible workers.
2. Redeploy the prior known-good image digests.
3. Keep additive schema changes in place when the prior revision can tolerate them.
4. If the migration is incompatible, restore the pre-release database backup into an isolated
   target, validate it, then switch traffic according to the platform's controlled recovery
   procedure.

Alembic downgrade commands are for disposable validation databases. Do not downgrade production
user data without a reviewed, rehearsed data-recovery plan.

## Demo isolation

The competition artifact remains separate:

```sh
pnpm demo
```

The demo command forces deterministic providers, a project-local demo database and storage root,
and no OpenAI credential. It does not start the production worker or write to deployed services.
Resetting demo state affects only the isolated demo paths and does not alter development, staging,
or production data.
