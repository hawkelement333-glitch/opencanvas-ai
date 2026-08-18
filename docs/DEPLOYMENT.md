# Milestone 3.5 deployment and operations guide

## Current production-readiness boundary

The documentation-only
[Milestone 7 Production Hardening architecture](MILESTONE_7_ARCHITECTURE.md)
and [implementation plan](MILESTONE_7_IMPLEMENTATION_PLAN.md) now own managed
PostgreSQL validation, deterministic production indexing, secure private
object ingestion and malware quarantine, durable work, shared rate limits,
observability, recovery exercises, capacity/resilience testing, and the final
production-readiness audit.

Milestones 7.1 through 7.7 are complete. Milestone 7.8 is the active final
production-readiness audit and has no numbered internal checkpoints. Revision
`20260726_0029` is the sole Alembic head; 0030 is absent. The managed
PostgreSQL High defects are locally remediated. The independent 7.8 campaign
machinery is fail-closed and not executable: its Automation cleanup controller
cannot meet the zero-residue invariant while deleted accounts are provider
retained. The prior campaign's exact account remains present.
M78-PG-E01, M78-PG-E02, M78-PG-E03, M78-TI-E01, and M78-PG-E04 remain open.
This guide is not evidence that managed grants, capacity, failover, credential
recovery, tenant isolation, or operational configuration have passed.

The historical PostgreSQL compatibility amendments remain the audit trail for
the earlier 0005/0021/0023/0024 corrections; their combined validation passed
before later migrations proceeded. They are not active deployment blockers and
must not be rerun or rewritten as Milestone 7.8 evidence.

SolarPlexus Mobius has five explicit runtime modes: `demo`, `development`, `test`, `staging`, and
`production`. The API validates the selected mode and all mode-dependent provider configuration at
startup. Staging and production fail closed if authentication, PostgreSQL, SMTP password reset,
OpenAI providers, approved private Azure Blob storage, trusted object
ingestion, or the database-backed worker are missing. They
never fall back to deterministic providers.

## Service topology

- `web`: non-root Next.js standalone service.
- `api`: non-root FastAPI service; serves liveness, readiness, authorized application APIs, and
  private-file proxy responses.
- `worker`: independently scalable database-backed document processor with persisted jobs,
  retries, idempotency keys, and heartbeats.
- `api-bootstrap`: provisioning-only Entra administrator job that creates and
  verifies semantic database principals, ownership, and grants.
- `api-migrate`: one-shot migration-identity Alembic task run after bootstrap
  and before API/worker rollout.
- PostgreSQL with pgvector: durable relational, vector, session, job, execution, and Trace state.
- Azure Blob Storage: private, versioned quarantine, clean, rejected, and
  retained containers accessed by workload identity.
- Managed Redis: private TLS shared rate limits using Microsoft Entra workload
  identity; counters are ephemeral and never authoritative product evidence.

The repository does not require one hosting vendor. Any platform is acceptable if it provides
these service roles, private networking, TLS, managed secrets,
PostgreSQL/pgvector, and approved private versioned object storage.

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
- `OPENCANVAS_STORAGE_PROVIDER=azure`
- the Azure storage-account URL and four distinct private security-class
  containers
- workload-identity endpoint/header settings injected by the platform
- `OPENCANVAS_OBJECT_INGESTION_MODE=trusted`
- distinct server-only upload-capability and scanner-result secrets
- exact scanner identity/version and malware-policy version
- bounded capability TTL, active sessions, callback rate, scan deadline, and
  clean-evidence maximum age
- `OPENCANVAS_JOB_PROVIDER=database`
- `OPENCANVAS_SHARED_RATE_LIMIT_PROVIDER=redis`
- a private credential-free `OPENCANVAS_SHARED_RATE_LIMIT_REDIS_URL` using
  `rediss`, the exact restricted Redis ACL username, and managed-identity
  endpoint/header settings
- a distinct deployment-specific shared-limit HMAC secret, namespace,
  deployment identity, bounded connect/operation timeouts, and emergency
  ceiling
- a browser-safe `NEXT_PUBLIC_API_URL=https://.../api/v1` at web build time

Use separate databases, storage accounts/containers, session secrets, SMTP credentials, OpenAI projects, and
telemetry destinations for staging and production. Never mount the demo database or demo storage
into either environment. Never set `APP_MODE=demo` in a deployed user environment.

Before enabling trusted ingestion, verify private networking,
public/shared-key denial, versioning, encryption, workload identity, scanner
policy/result authentication, and all four distinct containers. A mutable blob
tag is not a standalone clean decision. Follow
[`OBJECT_INGESTION_RUNBOOK.md`](OBJECT_INGESTION_RUNBOOK.md).

Inject exactly one database identity into each process. API, worker, and
migration tasks use distinct least-privilege database principals. API and worker
users must not be superusers, database/role creators, replication or RLS-bypass
roles, schema creators, owners, or members of the migration role. The
administrator identity is attached only to the manual principal-bootstrap job.
The one-shot migration task is attached only to `id-mobius77-db-migration` and receives
`OPENCANVAS_DATABASE_ROLE=migration`; its credential is never injected into
normal API or worker containers. Backup, observability, and emergency
credentials remain separately controlled and are not application credentials.

Cookies are HTTP-only for the session token and secure in staging/production. TLS must terminate
at a trusted proxy or the service. Preserve `X-Request-ID` across that proxy and do not log cookie,
authorization, CSRF, SMTP, storage, or OpenAI secrets.

## Release procedure

1. Build immutable API and web images from the reviewed commit and record their digests.
2. Back up the production database and verify object-store versioning/retention.
3. Run the administrator-attached principal-bootstrap job and require a
   successful terminal execution. Then run the migration-identity job and
   require exact revision `20260726_0029` plus successful runtime-grant
   reconciliation. Do not start the migration job when bootstrap fails.

4. Deploy worker instances and wait for a fresh worker heartbeat.
5. Deploy API instances and require `/api/v1/health/live`, `/ready`, and `/worker` to pass.
6. Deploy the web image built with the production API URL.
7. Exercise sign-in, workspace isolation, authorized file access, one document job, one grounded
   execution/Trace, and one insufficient-evidence response.
8. Keep the prior images available until the observation window closes.

Do not run multiple application revisions against an incompatible schema. Migrations must finish
before new API/worker instances accept traffic.

The guarded runner verifies the repository target `20260726_0029`, verifies
the operator-declared current revision (`base` for an empty database), obtains
one PostgreSQL session advisory lock, uses a direct non-pooled connection, and
verifies the final revision. A competing runner fails safely. API and worker
readiness stays false while the migration lock is held or the schema differs.
The API and worker grants are reconciled from the literal per-operation table
matrix after the migration. Neither runtime principal receives sequence or
function privileges, and no current/default blanket grants are permitted.

The historical clean-install defects in 0005/0021/0023/0024 were corrected and
their combined PostgreSQL/SQLite validation passed before 0026-0029. That
evidence does not substitute for the still-required 7.8 managed campaign. A
migration failure must preserve the primary exception, release the advisory
lock, leave API/worker readiness closed, and be recovered by a reviewed forward
fix or restore procedure; never broaden a runtime role or run Alembic at API
startup.

## Milestone 7.8 managed PostgreSQL evidence campaign

The independent campaign surface is documented in
[`infra/milestone_7_8/README.md`](../infra/milestone_7_8/README.md) and the
[`MILESTONE_7_8_MANAGED_POSTGRESQL_CAMPAIGN_OPERATOR_RUNBOOK.md`](MILESTONE_7_8_MANAGED_POSTGRESQL_CAMPAIGN_OPERATOR_RUNBOOK.md).
It is dry-run by default and requires a separate execution authorization.

The campaign derives bootstrap, migration, API, worker, evidence, and cleanup
identities from one campaign/generation. The database manifest binds their
semantic roles to distinct stable object IDs; labels alone grant no authority.
Cleanup is armed in a different resource group before the first billable
resource, the first billable mutation starts an immutable four-hour clock, the
conservative estimate is USD 25.6832, and USD 50 is a hard ceiling. Workloads
cannot deploy until one reviewed source digest has one passing source/digest-
bound admission scan. Every later error enters exact-scope cleanup.

Managed execution must finish by proving both resource groups absent, no
campaign-tagged resource or role assignment, and every residue counter zero.
Local implementation and simulation do not close any managed gap. The local
object-storage audit corrected M78-OS-001 by connecting durable exact-version
deletion requests to the database worker; managed-provider deletion and
recovery proof remains outstanding.

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

## Operational telemetry deployment

Development and test may explicitly enable the bounded memory sink. Staging
and production require:

- `OPENCANVAS_TELEMETRY_ENABLED=true`;
- `OPENCANVAS_TELEMETRY_EXPORTER=http`;
- one isolated verified-HTTPS endpoint;
- an `env://...` authentication secret reference whose value is available only
  to the server process;
- distinct pseudonymization material;
- explicit service, release, environment, and deployment identities;
- bounded batch, buffer, timeout, retry, sampling, span, cardinality, and
  shutdown settings;
- at least one server-owned operator identity.

The API and worker fail startup when required deployed telemetry
authentication is unavailable. They never place telemetry credentials in
client bundles. Public health remains minimal; authorized operator health is
`GET /api/v1/health/operator`. Operational telemetry destinations need
environment-isolated export/write and operator/read roles, configured
retention, audited access, and tested revocation.

No live destination was used during local Milestone 7.5. Before production or
Milestone 7.8, validate the exact release against an approved isolated
destination, render every dashboard, fire and recover every alert, prove
bounded outage/backpressure, verify retention and access revocation, and
remove all synthetic evidence.
