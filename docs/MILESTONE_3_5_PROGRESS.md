# Milestone 3.5 Productization Bridge — Progress Ledger

Last updated: 2026-07-21 (America/Chicago)

## Protected repository state

- Branch: `milestone-3.5-productization`
- Latest local checkpoint: `16acba7` (`Establish Milestone 3.5 productization foundation`)
- Latest remote checkpoint: `b45b776`; the recovery push is awaiting explicit destination-trust
  confirmation after the execution guard disclosed the external-transfer risk.
- Protected tag: `competition-demo-v1`
- The protected tag was verified before implementation and has not been moved, recreated,
  force-updated, or otherwise modified.
- No default-branch merge or pull request has been created.

## Recovered productization foundation checkpointed locally

- Audited the repository, established the pre-change test/build baseline, and recorded the
  pre-existing full-repository Prettier failure.
- Added centralized typed runtime configuration for demo, development, test, staging, and
  production modes with fail-closed deployed validation.
- Isolated deterministic demo settings, providers, database, storage, user, and workspace.
- Added explicit AI, embedding, private file-storage, and database/inline job-provider
  abstractions; production providers never fall back to deterministic results.
- Added users, secure database sessions, password resets, SMTP reset delivery configuration,
  account settings, data-export requests, and account deletion foundations.
- Added explicit user/workspace ownership to canvases, documents, processing jobs, executions,
  usage, and Trace access, with server-side ownership checks.
- Added migration `20260718_0005` for identity, ownership, document versions, durable jobs,
  claims, usage, errors, worker heartbeats, and exports.
- Added durable local/demo/memory/S3-compatible private storage and authorized file proxying.
- Added durable document versions, duplicate detection, replacement, reprocessing, deletion,
  queueing, idempotency keys, retry/backoff/exhaustion state, worker claiming, and health.
- Expanded production-shaped AI execution/Trace metadata, safe provider metadata, token/cost
  usage, evidence claims, exact document-version snapshots, and secret-safe failures.
- Added request correlation headers, structured request logging, readiness/storage/worker checks,
  secure headers, configured CORS, request-size enforcement, CSRF validation, and configured
  per-user/per-workspace/auth rate limits and workspace token budgets.
- Added restrained sign-in, sign-up, password-reset, account settings/export/sign-out,
  workspace selection/creation, staging indicator, queued/retry/permanent-failure document UX,
  and credentialed CSRF-aware browser requests.
- Removed invented document progress percentages; the UI now reports measurable stages only.

## Files currently modified or added

The complete productization foundation working set below was reviewed and committed in local
checkpoint `16acba7`. Only this progress ledger is modified after that checkpoint:

- `package.json`
- `apps/api/alembic/versions/20260718_0005_productization_bridge.py`
- `apps/api/opencanvas_api/core/config.py`
- `apps/api/opencanvas_api/db/models.py`
- `apps/api/opencanvas_api/db/session.py`
- `apps/api/opencanvas_api/main.py`
- `apps/api/opencanvas_api/api/dependencies.py`
- `apps/api/opencanvas_api/api/router.py`
- `apps/api/opencanvas_api/api/schemas.py`
- `apps/api/opencanvas_api/api/trace_schemas.py`
- `apps/api/opencanvas_api/api/routes/auth.py`
- `apps/api/opencanvas_api/api/routes/canonical.py`
- `apps/api/opencanvas_api/api/routes/canvases.py`
- `apps/api/opencanvas_api/api/routes/documents.py`
- `apps/api/opencanvas_api/api/routes/health.py`
- `apps/api/opencanvas_api/api/routes/traces.py`
- `apps/api/opencanvas_api/services/ai.py`
- `apps/api/opencanvas_api/services/auth.py`
- `apps/api/opencanvas_api/services/authorization.py`
- `apps/api/opencanvas_api/services/email.py`
- `apps/api/opencanvas_api/services/demo.py`
- `apps/api/opencanvas_api/services/trace.py`
- `apps/api/opencanvas_api/services/jobs.py`
- `apps/api/opencanvas_api/services/canonical/repository.py`
- `apps/api/opencanvas_api/services/canonical/service.py`
- `apps/api/opencanvas_api/services/documents/__init__.py`
- `apps/api/opencanvas_api/services/documents/embeddings.py`
- `apps/api/opencanvas_api/services/documents/processing.py`
- `apps/api/opencanvas_api/services/documents/retrieval.py`
- `apps/api/opencanvas_api/services/documents/storage.py`
- `apps/api/scripts/demo.py`
- `apps/api/scripts/worker.py`
- `apps/api/tests/conftest.py`
- `apps/api/tests/test_ai_api.py`
- `apps/api/tests/test_canonical_schema.py`
- `apps/api/tests/test_canonical_service.py`
- `apps/api/tests/test_demo_mode.py`
- `apps/api/tests/test_document_api.py`
- `apps/api/tests/test_health.py`
- `apps/api/tests/test_migration.py`
- `apps/api/tests/test_release_settings.py`
- `apps/api/tests/test_trace_api.py`
- `apps/web/src/app/account/page.tsx`
- `apps/web/src/app/reset-password/page.tsx`
- `apps/web/src/app/sign-in/page.tsx`
- `apps/web/src/app/globals.css`
- `apps/web/src/components/canvas/document-node.tsx`
- `apps/web/src/components/demo-mode-banner.test.tsx`
- `apps/web/src/components/open-canvas-app.tsx`
- `apps/web/src/lib/api-client.ts`
- `apps/web/src/lib/api-client.test.ts`
- `apps/web/src/lib/contracts.ts`
- `scripts/validate_migrations.py`
- `docs/MILESTONE_3_5_PROGRESS.md`

## Validation already run

Baseline before changes:

- API tests: 106 passed.
- Web unit tests: 24 passed across 7 files.
- API lint, API format, strict API type check, web lint, and web type check: passed.
- Production web build: passed.
- E2E on an isolated port: 2 mock workflows passed; 2 real-service workflows skipped by
  their existing conditions. Port 3000 was occupied by an unrelated application.
- Full-repository Prettier check: pre-existing failure on 58 tracked files.

Recovered implementation checks run on 2026-07-21:

- Focused document retry regression: passed (`1` test).
- Full API suite: passed (`106` tests).
- Strict API type check: passed (`45` source files).
- Changed-file Ruff lint and format check: passed (`42` files).
- Web unit/component suite: passed (`24` tests across `7` files).
- Web type check: passed.
- Web lint: passed.
- Migration validation: passed upgrade `20260718_0005` → downgrade `20260717_0004` →
  re-upgrade `20260718_0005`.
- Secret/artifact scan: only the documented development-only secret and explicit test
  placeholders were found; no live credentials or generated artifacts were found.

## Known failures and incomplete scope

- No known recovery-foundation test failure remains. The full milestone validation gate has not
  yet been run.
- The recovered foundation is committed locally as `16acba7`.
- Two attempts to push only `milestone-3.5-productization` to the configured existing origin
  `https://github.com/hawkelement333-glitch/opencanvas-ai.git` were blocked by the execution
  guard because repository-code transfer requires fresh user confirmation that this destination
  is trusted. No alternate transfer was attempted.
- Original-context and current-context rerun endpoints still need implementation. The persistence
  columns exist, but immutable snapshot identifiers and rerun behavior are unfinished.
- Dedicated authentication/session-expiration, two-user/multi-workspace isolation, file access,
  job retry/exhaustion, quota, and account-lifecycle tests still need to be added.
- `.env.example`, deployment/container configuration, backup/restore/rollback runbooks, staging
  instructions, production instructions, and the final architecture/security documentation are
  unfinished.
- The post-change web unit/E2E/build gates, demo workflow, closest local production-shaped
  validation, migration gate, dependency review, and complete validation gate remain to run.
- Live OpenAI, SMTP, S3-compatible storage, PostgreSQL, and deployed worker calls have not been
  performed; no live-provider success is claimed.

## Exact next implementation step

1. Obtain fresh user confirmation that the configured origin
   `https://github.com/hawkelement333-glitch/opencanvas-ai.git` is trusted for this repository
   code transfer.
2. Push the local recovery commits only to `milestone-3.5-productization`, verify the remote
   branch resolves to the local checkpoint, and record the pushed commit.
3. Only after that recovery push succeeds, implement immutable original-context/current-context
   reruns as the next checkpoint, including
   preserved node/document/chunk IDs and source versions plus focused tests.
