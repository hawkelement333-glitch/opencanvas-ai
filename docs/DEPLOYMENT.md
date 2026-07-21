# Milestone 3.5 deployment and operations guide

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

## Staging and production configuration

Start from `.env.example`, inject secrets through the deployment platform, and set:

- `APP_MODE=staging` or `APP_MODE=production`
- `OPENCANVAS_APP_URL=https://...`
- `OPENCANVAS_CORS_ORIGINS=["https://..."]`
- `OPENCANVAS_DATABASE_URL=postgresql+asyncpg://...`
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

Cookies are HTTP-only for the session token and secure in staging/production. TLS must terminate
at a trusted proxy or the service. Preserve `X-Request-ID` across that proxy and do not log cookie,
authorization, CSRF, SMTP, storage, or OpenAI secrets.

## Release procedure

1. Build immutable API and web images from the reviewed commit and record their digests.
2. Back up the production database and verify object-store versioning/retention.
3. Run the migration image as a one-shot task:

   ```sh
   alembic upgrade head
   ```

4. Deploy worker instances and wait for a fresh worker heartbeat.
5. Deploy API instances and require `/api/v1/health/live`, `/ready`, and `/worker` to pass.
6. Deploy the web image built with the production API URL.
7. Exercise sign-in, workspace isolation, authorized file access, one document job, one grounded
   execution/Trace, and one insufficient-evidence response.
8. Keep the prior images available until the observation window closes.

Do not run multiple application revisions against an incompatible schema. Migrations must finish
before new API/worker instances accept traffic.

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
Resetting demo state affects only the isolated demo paths.
