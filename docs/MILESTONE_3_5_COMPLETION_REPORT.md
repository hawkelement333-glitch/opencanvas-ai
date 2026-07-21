# Milestone 3.5 Productization Bridge — Completion Report

Date: 2026-07-21

## Verified repository state

- Branch: `milestone-3.5-productization`
- Final Milestone 3.5 handoff local HEAD before this documentation correction:
  `bd488e57293f6996e5c9a505cb912d888235f199`
- Final Milestone 3.5 handoff remote `origin/milestone-3.5-productization` HEAD before this
  documentation correction: `bd488e57293f6996e5c9a505cb912d888235f199`
- Protected annotated tag: `competition-demo-v1` (tag object
  `acbde89b6e2cc3e41c372887794726d393836716`), unchanged and resolving to commit
  `b45b7763b65861f9dfb3be7edf9b5eb271950917`
- Working tree at handoff verification: clean
- Push method: normal push; no force-push or force-with-lease
- No merge, default-branch push, pull request, history rewrite, or Milestone 3.75/Milestone 4 work
  occurred

The documentation-correction commit necessarily follows `bd488e5`; its exact local/remote hash and
clean post-push state are reported after that commit is created and pushed because a commit cannot
contain its own hash.

## Outcome

The repository now has a production-capable foundation while retaining the deterministic
competition demonstration as an isolated, independently runnable `APP_MODE=demo` artifact. The
implementation stops at Milestone 3.5: it does not include the Milestone 3.75 redesign,
workspace-wide search, collaboration, billing, or autonomous-agent work.

## Repository audit findings

- Frontend: Next.js 16, React 19, TypeScript, TanStack Query, React Flow, Zod, and Playwright.
- Backend: FastAPI, async SQLAlchemy, Pydantic settings, Alembic, and an independent Python worker.
- Persistence: PostgreSQL/pgvector in deployed modes and isolated SQLite databases for demo/test.
- Original ingestion: private local files plus request/in-process processing; production gaps
  included temporary assumptions, incomplete states, and no durable worker ownership.
- Original identity boundary: single user/workspace assumptions and client-visible identifiers
  without a complete authenticated ownership boundary.
- Demo assets: fixed users/workspace/canvas/nodes/documents/chunks/executions/Trace identifiers,
  deterministic reasoning/embedding providers, synthetic files, and stable evidence outcomes.
- Deployment baseline: local web/API/database containers without an independent worker or complete
  staging/production operations guidance.

## Competition-demo preservation

- `competition-demo-v1` was verified repeatedly and never moved, recreated, force-updated, or
  rewritten.
- Demo startup forces deterministic providers, strips live credentials, and restricts database
  and file paths to `.runtime/demo`.
- Demo mode does not start the production worker or use S3, SMTP, OpenAI, or production data.
- The seeded supported answer, citations, Trace evidence, insufficient-evidence result, source
  versions, and stable identifiers remain reproducible.
- Demo reset/check/smoke and both mock browser workflows pass.

## Runtime and configuration architecture

The centralized `Settings` layer resolves `demo`, `development`, `test`, `staging`, and
`production`. Provider choice is explicit. Staging/production require authentication,
PostgreSQL, SMTP reset delivery, OpenAI reasoning and embeddings, private S3-compatible storage,
and database jobs. Missing or mock deployed providers fail closed.

`.env.example` documents runtime identity, URL/CORS, database pool, sessions/CSRF, password reset,
AI/embedding models, storage, jobs, uploads, request/rate/token limits, logging, telemetry, and
cost estimates. Only browser-safe values use `NEXT_PUBLIC_*`. A regression test loads the actual
template through typed settings.

## Authentication and authorization

- Account creation, sign-in/out, expiring database sessions, password reset, settings, deletion,
  and data-export request entry points are implemented.
- Session cookies are HTTP-only, secure in staging/production, SameSite-configured, rotated on
  authentication, and paired with CSRF validation for state changes.
- Authentication errors are generic and authentication endpoints are rate limited.
- Users may own multiple workspaces. Server-side ownership covers canvases, nodes, edges, notes,
  documents/versions/files/chunks, jobs, executions, claims, citations, Trace, reruns, usage, and
  settings.
- Cross-user/workspace tests use two users, multiple workspaces, and manipulated identifiers to
  prove private file, canvas, document, execution, Trace, and rerun denial.

## Database and migrations

- `20260718_0005_productization_bridge.py` adds users, sessions, ownership, document versions,
  durable jobs, claims, usage, errors, worker heartbeats, and export requests with indexes and
  foreign keys.
- `20260721_0006_immutable_rerun_snapshots.py` adds immutable node/document/chunk references used
  by exact original-context reruns.
- Migration validation upgraded to `20260721_0006`, downgraded one revision, and re-upgraded.

## Storage and document processing

- Storage providers cover isolated demo assets, memory tests, private local development files,
  and S3-compatible staging/production objects.
- Files have sanitized display names, MIME/extension/signature checks, size/archive limits,
  hashes, opaque storage keys, ownership, versions, timestamps, and authorized proxy access.
- Processing persists uploaded/queued/processing/extracting/chunking/embedding/indexing/ready,
  retryable/retrying/permanent-failure, deleting, and deleted states.
- Jobs have stable IDs, user/workspace/document ownership, idempotency keys, concurrency limits,
  exponential backoff, retry exhaustion, deletion cancellation, and worker heartbeats.
- Duplicate enqueue/execution does not duplicate chunks or embeddings; deleted documents are not
  resurrected and deleted retrieval data is removed.

## Providers and Trace

- Reasoning, embedding, storage, and job protocols have deterministic demo/test and explicit live
  implementations. Provider errors are recorded and never fabricated as successful mock output.
- Executions record provider/model/config version, timestamps, latency, token/cost usage, status,
  safe errors, selected sources, retrieval ranks/scores, included/excluded context, claims,
  citations, validation, and insufficient-evidence decisions.
- Original-context reruns use immutable snapshots and exact document versions. Current-context
  reruns resolve current source versions. Both create new linked executions and Trace lineage.
- Trace output excludes credentials, authorization headers, hidden system instructions, internal
  paths, unsafe stack traces, and private provider diagnostics.

## Security, observability, and cost controls

- Request schemas, explicit credentialed CORS, CSRF, secure headers, path/storage containment,
  upload/archive validation, prompt-injection boundaries, citation validation, secret redaction,
  safe errors, and ownership enforcement are implemented and tested.
- Structured request logs include correlation IDs without logging document bodies, cookies,
  authorization headers, or secrets.
- Liveness/readiness report database, storage, worker, and provider configuration. Worker
  heartbeats persist even when the queue is idle.
- Upload/file counts, question/context/output sizes, retrieval count, concurrent jobs, retries,
  per-IP/user/workspace request rates, and monthly workspace token budgets are configurable.
- Usage records include tokens and estimated cost inputs suitable for later billing without
  implementing billing.

## Deployment foundation

The portable reference topology contains PostgreSQL/pgvector, a one-shot migration task, non-root
API and worker services, a non-root web service, private development file volume, readiness, and
worker health checks. `docs/DEPLOYMENT.md` documents local production-shaped startup, explicit
staging/production requirements, release order, backup, restore test, rollback, and demo
separation without choosing a mandatory hosting vendor.

## Main files added or changed

- Runtime/security: `.env.example`, `core/config.py`, authentication/authorization dependencies
  and routes, security middleware, `SECURITY.md`, and `docs/SECURITY_MODEL.md`.
- Persistence: database models/session and Alembic revisions `0005` and `0006`.
- Providers/processing: AI, Trace, job, document processing/retrieval/storage/embedding services,
  `scripts/worker.py`, and `scripts/demo.py`.
- UX/contracts: sign-in, reset, account, workspace/canvas app, API client/contracts, restrained
  status/indicator styles, and browser fixtures.
- Operations: API/web Dockerfiles, `docker-compose.yml`, `docs/DEPLOYMENT.md`, architecture,
  limitations, progress ledger, and this report.
- Tests: release modes, demo, authentication/authorization, jobs, documents, AI/Trace/reruns,
  migration, health, security, web components, and E2E workflows.

## Validation results

Actually run on this branch:

- Full API: `118 passed`.
- Integration subset: `21 passed`.
- Security marker: `25 passed` before the final environment regression; the final complete API run
  includes the added security-marked test.
- Web unit/components: `24 passed` across `7` files.
- Mock E2E: `2 passed`; full E2E also skipped `2` real PostgreSQL workflows by their existing
  conditions.
- API Ruff lint/format and strict mypy: passed; mypy checked `45` source files.
- Web ESLint and TypeScript: passed.
- Next.js production build: passed.
- Alembic migration validation: passed through revision `20260721_0006`.
- Demo reset, isolation/provenance check, and API/web startup smoke: passed.
- Repository hygiene, changed-file formatting, whitespace, and credential-pattern review: passed.
- Typed `.env.example` parse and release-mode matrix: passed.
- JavaScript production advisory audit: no known vulnerabilities.
- Third-party Python advisory audit: no known vulnerabilities after updating the local audit
  environment's `pip`; the editable local project was correctly excluded from PyPI lookup.
- Compose YAML/service wiring: passed structural validation.

The full-repository Prettier check still reports the recorded pre-existing formatting backlog in
37 untouched files. Milestone 3.5 changed files pass their formatter checks.

## Validation not claimed

- Docker is not installed in the execution environment, so Compose CLI validation, image builds,
  and the local container stack were not run.
- A PostgreSQL service was unavailable, so the two real-service browser workflows did not run.
- No live OpenAI, SMTP, S3-compatible service, staging deployment, production deployment, backup,
  restore, or rollback was executed. Provider interfaces and production-shaped settings were
  tested without claiming live calls.

## Required deployed environment

At minimum: `APP_MODE`, `OPENCANVAS_APP_URL`, explicit `OPENCANVAS_CORS_ORIGINS`, PostgreSQL
`OPENCANVAS_DATABASE_URL`, a unique `OPENCANVAS_SESSION_SECRET`, SMTP password-reset settings,
`OPENCANVAS_AI_PROVIDER=openai`, `OPENCANVAS_EMBEDDING_PROVIDER=openai`, server-only
`OPENAI_API_KEY`, `OPENCANVAS_STORAGE_PROVIDER=s3` with private bucket credentials,
`OPENCANVAS_JOB_PROVIDER=database`, and build-time `NEXT_PUBLIC_API_URL`. Use separate resources
and secrets for staging and production.

## Startup instructions

Local development:

```powershell
Copy-Item .env.example .env
docker compose up -d db
pnpm db:migrate
pnpm dev:api
pnpm worker
pnpm dev:web
```

Deterministic competition demo:

```powershell
pnpm demo
```

Staging/production: configure the required managed services and secrets, run the migration command
(`alembic upgrade head`) as a one-shot task, start worker(s), require a fresh heartbeat, start API
instance(s), then deploy the web image with its environment-specific public API URL. Follow
`docs/DEPLOYMENT.md`.

## Known limitations and blockers before Milestone 3.75

- Run the container build/stack and real PostgreSQL E2E workflows in a Docker/PostgreSQL-capable
  environment.
- Validate live OpenAI, SMTP, private object storage, backup, restore, and rollback with dedicated
  non-production credentials before accepting real production data.
- Resolve or formally scope the pre-existing 37-file repository formatting backlog.
- Organizations/collaboration, distributed rate limiting, malware scanning, transactional outbox,
  broker administration, export artifact generation, formal retention/redaction, penetration
  testing, and compliance review remain intentionally deferred.

No Milestone 3.75 or Milestone 4 work has begun.
