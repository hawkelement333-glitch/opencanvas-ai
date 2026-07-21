# Milestone 3.5 Productization Bridge — Progress Ledger

Last updated: 2026-07-21 (America/Chicago)

## Protected repository state

- Branch: `milestone-3.5-productization`
- Recovered foundation checkpoint: `16acba7` (`Establish Milestone 3.5 productization foundation`)
- Verified recovery-ledger checkpoint: `f379b12` (`Record recovery push blocker`)
- Deployment/worker operations checkpoint: `484d2b3` (`Add deployment and worker operations
foundation`)
- Remote `origin/milestone-3.5-productization` was verified at `484d2b3` after normal,
  non-force pushes and contains every recorded checkpoint.
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
- Added linked original-context and current-context rerun endpoints. Original-context reruns use
  immutable note/chunk snapshots and exact document versions; current-context reruns resolve the
  current selected nodes and current document version.
- Added immutable node, document, chunk, and chunk-index snapshot identifiers in migration
  `20260721_0006`, plus parent execution and parent Trace linkage for comparison.
- Added real-session authentication and authorization tests with two independent users and
  multiple workspaces, covering CSRF, expiration, password reset, session revocation, generic
  credential failures, account settings/export/deletion, private files, Trace/rerun ownership,
  manipulated identifiers, and per-IP authentication rate limiting.
- Added durable-job reliability coverage for idempotent enqueue, workspace concurrency,
  exponential backoff, retry exhaustion, permanent failure, delayed deleted-document
  cancellation, worker heartbeat freshness, and workspace monthly token budgets.
- Added a portable web/API/worker/PostgreSQL Compose topology, independent worker healthcheck,
  startup migration task, complete environment template, deployment/backup/restore/rollback
  runbook, and updated as-built/limitations documentation.
- Fixed idle workers to commit their persisted heartbeat and added regression coverage.
- Updated the mock competition browser workflows for credentialed CORS, workspace ownership,
  runtime metadata, and required Trace identifiers.

## Files currently modified or added

After checkpoint `484d2b3` was pushed, only this progress ledger is modified. No source,
configuration, secret, generated dependency directory, temporary file, or test database is
uncommitted.

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

Rerun checkpoint checks run on 2026-07-21:

- Focused original/current note, document-version, Trace-lineage, authorization, and migration
  tests: passed (`9` tests).
- Full API suite: passed (`109` tests).
- Strict API type check: passed (`45` source files).
- Changed-file Ruff lint/format and whitespace checks: passed.
- Web unit/component suite: passed (`24` tests across `7` files).
- Web type check and lint: passed.
- Migration validation: passed upgrade `20260721_0006` → downgrade `20260718_0005` →
  re-upgrade `20260721_0006`.

Authentication and isolation checkpoint checks run on 2026-07-21:

- Focused real-session authentication/account/isolation tests: passed (`3` tests).
- Complete security-marked API gate: passed (`21` tests).
- Full API suite: passed (`112` tests).
- Strict API type check and focused Ruff lint/format check: passed.

Job reliability and quota checkpoint checks run on 2026-07-21:

- Focused job reliability and workspace token-budget tests: passed (`4` tests).
- Complete security-marked API gate: passed (`25` tests).
- Full API suite: passed (`116` tests).
- Strict API type check and focused Ruff lint/format check: passed.

Deployment and operations checkpoint checks run on 2026-07-21:

- Full API suite: passed (`117` tests).
- Explicit integration gate: passed (`21` tests).
- Complete security-marked API gate: passed (`25` tests; `92` deselected).
- API Ruff lint/format and strict type check: passed (`85` formatted files, `45` source files).
- Web lint and type check: passed.
- Web unit/component suite: passed (`24` tests across `7` files).
- Production web build: passed.
- Migration validation: passed upgrade `20260721_0006` → downgrade `20260718_0005` →
  re-upgrade `20260721_0006`.
- Repository hygiene and changed-file formatting/whitespace checks: passed.
- Deterministic demo reset, isolation/provenance check, and API/web startup smoke: passed with no
  paid provider or production credential.
- Focused mock browser workflows: passed (`2` tests); full E2E gate passed those same `2` tests
  and skipped the `2` tests that require a real PostgreSQL service by their existing conditions.
- Compose YAML and required service/dependency/worker-health wiring: passed structural validation.
- Docker Compose CLI/image validation was not run because Docker is not installed in this
  environment; no container-build success is claimed.

## Known failures and incomplete scope

- No known source test, lint, type, migration, build, demo, or runnable E2E failure remains.
- After the user explicitly confirmed the configured origin was trusted, recovery commits
  `16acba7` and `f379b12` were pushed only to `origin/milestone-3.5-productization` and verified
  on the remote. No force push, merge, default-branch push, tag change, or pull request occurred.
- The container topology could not be built or launched because Docker is unavailable locally.
- The two real-service browser tests remain intentionally skipped without PostgreSQL.
- A final dependency review, release-settings matrix confirmation, and completion audit remain.
- Live OpenAI, SMTP, S3-compatible storage, PostgreSQL, and deployed worker calls have not been
  performed; no live-provider success is claimed.

## Exact next implementation step

1. Run the final release-settings matrix and targeted production fail-closed checks, including
   refusal of deterministic providers and separation from demo data.
2. Complete the available dependency/security review and reconcile the requested completion
   report against code, migrations, docs, and every actually run validation result.
3. Fix any audit findings, run affected tests, then create and push the final Milestone 3.5
   checkpoint plus an exact final ledger record. Do not begin Milestone 3.75 or Milestone 4.
