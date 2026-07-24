# Milestone 4 Controlled Agents Progress Ledger

Last updated: 2026-07-23 (America/Chicago)

## Milestone 4.2 Terra checkpoint 1 — immutable grounded-draft application bridge

- Terra started from the clean, normally pushed Sol safety-core SHA
  `7b968146b413a1d0c09c42564915d06c2b5efc41` on
  `milestone-4-controlled-agents`; the protected tag peeled commit remains
  `b45b7763b65861f9dfb3be7edf9b5eb271950917`.
- Added an internal synchronous `ControlledGroundedDraftService`. It reserves the existing
  request identity, calls the existing authority preflight and approval consumption boundary,
  resolves immutable selected context once, records the closed lifecycle states, and accepts the
  result only through the existing late-result-suppression boundary.
- The bridge reuses the configured reasoning-provider interface and existing grounded-result
  validator. It introduces no provider, embedding, worker, queue, scheduler, delegation, or
  workspace mutation. The request contract now binds the bounded instruction into its existing
  idempotency digest.
- Exact selected chunk content is persisted as immutable execution evidence with citations,
  supported/insufficient-evidence claims, provider metadata, usage/cost metadata, and complete
  Trace start/completion/failure records. Trace metadata contains only identifiers, digests, and
  safe provider metadata; raw evidence remains in the authorized execution records.
- Focused validation: `apps/api/tests/test_agent_grounded_draft.py` — `3 passed`; Ruff format and
  lint passed; focused mypy for `grounded_draft.py` and `execution.py` passed; `git diff --check`
  passed before this ledger update.
- Defect corrected during focused testing: explicit flush ordering is required because execution
  snapshot models use scalar foreign keys rather than ORM relationships. A late provider result
  now retains the Sol rejection/audit path instead of attempting a new terminal state.
- Not started in this checkpoint: server-owned start contract creation, authenticated start/cancel
  routes, read-only UI, API tests, final Terra validation, or Luna work.
- Exact next Terra unit: add the narrow server-owned start contract builder and authenticated
  start/cancel boundary using this application service; do not add a worker, queue, scheduler,
  delegation, external provider, or workspace effect.

## Milestone 4.2 Sol final security gate

- Recovery started clean with local and remote SHA
  `9bb70e41269465daff314d7a27c43ec6ca1bb0ed`.
- Completed and normally pushed three bounded checkpoints:
  - `18b995e` — lifecycle transition validation and database compare-and-set guards.
  - `6cde6f6` — immutable selected-context resolution.
  - `87dd85a` — authoritative cancellation and late-result suppression.
- Complete focused Sol gate: `74 passed`.
- Migration cycle: upgrade `0009`, downgrade `0008`, re-upgrade `0009` passed.
- Ruff format: `19 files already formatted`; Ruff lint passed.
- Mypy passed for all controlled-agent service modules and the database model target.
- Repository hygiene and built-in secret scan passed for `216` source files.
- High-confidence secret scan found no matches; `git diff --check` passed.
- No dependency, provider, API, UI, worker, queue, scheduler, delegation, workspace-effect,
  Milestone 3.75, Terra, Luna, or later-milestone file was added.
- PostgreSQL: **NOT RUN**. Docker is unavailable and no PostgreSQL test URL is configured; the
  marked test reported one skip.
- Sol completion decision: **SOL SAFETY CORE COMPLETE — MILESTONE 4.2 NOT COMPLETE**.
- Exact next authorized action: a separately authorized Terra task may implement only the provider,
  grounded generation/citation/Trace, narrow API/UI, and remaining Milestone 4.2 tests listed in
  `docs/MILESTONE_4_2_SOL_HANDOFF.md`. This Sol task must stop after its final documentation commit
  and normal push.

## Milestone 4.2 Sol checkpoint 3D — cancellation and late-result suppression

- Starting local and remote SHA:
  `6cde6f6` (`Resolve immutable controlled-agent context`).
- Added an internal synchronous lifecycle boundary for authoritative, idempotent cancellation and
  result publication. Cancellation before start appends `proposed -> cancelled`; cancellation
  during execution creates one terminal successor; repeated cancellation cannot reopen or duplicate
  the transition; and cancellation after success is recorded as rejected without changing success.
- Result acceptance binds the authenticated user, execution, workspace, running-state identity,
  stored context snapshot/digest, immutable resolution digest, and result digest. A delivery UUID
  is the append-only audit identity, so exact redelivery is idempotent and conflicting reuse fails
  closed.
- Publication rechecks the consumed approval/policy binding, grant and approval expiry, and grant
  revocation at acceptance time. Missing consumption, altered authority, expired/revoked authority,
  cancelled/terminal state, stale running state, supersession, and lifecycle races reject the
  result without making it authoritative.
- Cancellation/result races use the checkpoint 3B database compare-and-set transition guard.
  Whichever terminal successor commits first remains authoritative; the loser reloads current state,
  suppresses its late outcome, and appends safe rejection evidence.
- Tests cover `cancel before start`, `start -> cancel -> result`, `start -> result -> cancel`,
  grant revocation before result, approval expiry before result, superseded execution, stale running
  state, exact duplicate result delivery, conflicting delivery reuse, repeated cancellation, and
  terminal-state preservation.
- Focused cancellation/lifecycle/context tests: `14 passed`.
- Ruff format/lint: passed. Focused mypy for `execution.py`: passed.
- No migration was required for this unit. No provider call, result body persistence, public API,
  UI, workspace effect, worker, queue, scheduler, delegation, Terra, Luna, or Milestone 3.75 work
  was added.
- Exact next unit: run the complete Sol contract/policy/persistence/authority/idempotency/lifecycle/
  immutable-context/cancellation/result gate, migration cycle, repository/security audits, update
  the Sol handoff to an evidence-backed completion decision, commit, push, and stop before Terra.

## Milestone 4.2 Sol checkpoint 3C — immutable selected context

- Starting local and remote SHA:
  `18b995e` (`Enforce controlled execution lifecycle`).
- Added an internal immutable selected-context resolver that accepts only a previously authorized,
  server-owned execution boundary. It reloads the stored append-only snapshot, verifies execution,
  user, workspace, canvas, snapshot identity, and stored digest, and rejects duplicate selections.
- Exact canvas revisions, node revisions, document-version rows, and chunk document versions are
  resolved through ownership-scoped joins. Unsupported resource kinds, missing versions, deleted
  resources, altered content, current-version substitution, and cross-scope access fail closed.
- Every resolved resource has a domain-separated canonical digest. The returned package has its own
  stable resolution digest bound to the stored context snapshot and exact ordered evidence.
- Uploaded/node text remains explicitly marked `untrusted_content`; prompt-injection text is
  preserved only as evidence and cannot alter authority, scope, action, or lifecycle decisions.
- Tests prove exact ordered resolution, stable returned content after later workspace mutation,
  rejection on a second resolution after a selected revision changes, altered-digest rejection,
  deleted-version rejection, authenticated-user mismatch denial, and prompt-injection isolation.
- Focused immutable-context/contract/authority tests: `19 passed`.
- Ruff format/lint: passed. Focused mypy for `execution.py`: passed.
- `git diff --check`: passed.
- No migration was required for this unit. No provider, API, UI, workspace effect, cancellation,
  result publication, worker, queue, scheduler, delegation, Terra, Luna, or Milestone 3.75 work was
  added.
- Exact next unit: add authoritative idempotent cancellation and result-acceptance guards that
  recheck current lifecycle, immutable context identity, grant revocation, and authority expiry at
  publication time; rejected late results must append safe audit evidence and never change a
  terminal outcome.

## Milestone 4.2 Sol checkpoint 3B — lifecycle transition safety

- Starting local and remote SHA:
  `9bb70e41269465daff314d7a27c43ec6ca1bb0ed`.
- Reconstructed the unavailable prior-task state from the branch, commits, tests, Sol handoff, and
  this ledger. The repository confirms checkpoint 3A was the latest completed unit; Terra and Luna
  implementation were not present and were not restarted.
- Added migration `20260723_0009` with an append-only lifecycle transition guard. Unique
  `(execution_id, sequence)` and `(execution_id, predecessor_token)` constraints provide a
  database-backed compare-and-set boundary so two successors cannot authoritatively follow the
  same prior state.
- Replaced unrestricted state appends with ownership-scoped, closed transition validation.
  Executions must begin in `proposed`; only declared successors are accepted; timestamps cannot
  regress; and `succeeded`, `failed`, `cancelled`, and `denied` are terminal.
- Added current-state reads ordered by validated transition sequence rather than caller timestamps.
- Added focused lifecycle and schema tests covering valid transitions, invalid initial/terminal
  transitions, terminal reopening, timestamp regression, ownership mismatch, current-state
  ordering, and database compare-and-set constraints.
- Focused lifecycle/persistence/schema/API/migration tests: `28 passed`.
- Migration validation: passed upgrade `0009`, downgrade `0008`, re-upgrade `0009`.
- Ruff lint: passed. Focused mypy for the persistence/model files: passed.
- `git diff --check`: passed.
- PostgreSQL execution: **NOT RUN**. The migration contains PostgreSQL-compatible constraints and
  append-only trigger wiring, but no configured PostgreSQL service is available in this checkpoint.
- No provider call, immutable-context resolver, cancellation controller, result publication, API,
  UI, worker, queue, scheduler, delegation, workspace effect, Milestone 3.75 integration, Terra
  work, or Luna work was added.
- Exact next unit: resolve the stored selected context to exact owned canvas/node/document-version/
  chunk identities and content digests without current-version substitution or broad search, then
  add focused tamper, deletion, ownership, and later-workspace-change tests.

## Milestone 4.2 Sol checkpoint 3A — database request idempotency

- Starting local and remote SHA: `8c4db0f023f00a6605c635cf85fbf70a08bd7f1e`; branch and
  protected tag were verified, and the working tree was clean.
- Added migration `20260721_0008` and an append-only request-identity model. Database uniqueness is
  scoped to authenticated user, workspace, canvas, closed action, and idempotency key. The stored
  canonical digest binds execution, context/plan IDs and hashes, grant, and approval while excluding
  transport-only metadata.
- Identical retries return the original request identity and logical execution without consuming an
  approval. Conflicting reuse appends a safe `execution.idempotency_conflict` audit event, does not
  reveal or mutate the original fingerprint, and consumes no approval.
- Uniqueness and nested-transaction handling are database-backed; no in-memory lock is used. The
  new identity is protected by ORM and SQLite/PostgreSQL append-only triggers.
- Migration validation passed: upgrade `0008`, downgrade `0007`, re-upgrade `0008`. Focused
  migration/idempotency tests: `12 passed`; idempotency tests alone: `6 passed`. The earlier focused
  idempotency/authority/persistence/policy run passed `38` tests. Changed-file mypy passed; Ruff
  format/lint passed after one exception-chaining correction.
- PostgreSQL: **NOT RUN**. The migration contains the PostgreSQL trigger, but authoritative
  PostgreSQL execution and concurrent PostgreSQL behavior were not run.
- Partial work: execution-state validation was not started because the low-usage trigger activated.
  Therefore the combined idempotency/state checkpoint is not complete.
- Exact next unit: implement closed append-only execution-state validation and terminal-state
  protection, then rerun the combined focused gate. Do not begin immutable-context resolution,
  cancellation, provider generation, API, or UI.
- Resume with the commands already recorded below, then inspect migration `0008`,
  `ExecutionRequestRegistry`, and `test_agent_request_idempotency.py` before editing.

## Milestone 4.2 Sol checkpoint 2 — trusted authority preflight

- Starting local and remote SHA: `4792c3c620e784752b7a194adfa42d25d25ed880` on
  `milestone-4-controlled-agents`; working tree was clean and the protected tag remained at
  `b45b7763b65861f9dfb3be7edf9b5eb271950917`.
- Added an internal `ExecutionAuthorityPreflight` for the closed `generate_grounded_draft` action.
  It compares the authenticated server principal to the request, verifies the active owned
  workspace/canvas, loads the owned stored execution and all stored authority records, verifies
  context/plan/grant/approval references and digests, enforces the canvas draft capability and R0/R1
  risk boundary, and delegates the final decision to the existing pure policy and atomic
  consumption repository.
- The approval is consumed only inside the existing nested transaction after stored contract
  parsing, canonical digest recomputation, ownership/resource/capability checks, expiry/revocation
  checks, and an `allow` policy result. The unique approval constraint converts races/replays into
  an append-only `approval_replayed` denial; no second consumption is written.
- The result contains only safe IDs, verified digests, action, correlation ID, decision ID, and
  consumption ID. It returns no raw authority payload, session/service data, or content.
- Files changed: `execution.py`, `agent_fixtures.py`, the existing contract tests, new authority
  preflight tests, and the two Milestone 4 handoff documents. No migration changed.
- Focused contract/preflight/policy/persistence suite: `38 passed`. The authority file alone:
  `9 passed`, including independent-connection parallel consumption. Ruff format/lint and focused
  mypy passed for four files. PostgreSQL: **NOT RUN**.
- Full backend, security, demo, frontend, production build, live-provider, deployment, and
  PostgreSQL suites were not run.
- Known limitation: reference failures before policy evaluation deny safely without creating a
  policy row; the request idempotency and transition checkpoint must decide whether a separate
  bounded preflight-denial audit record is required. No authorized execution state is created here.
- Exact next Sol unit: **Database-backed request idempotency and append-only execution-state
  validation.** Do not begin immutable-context resolution, cancellation, provider work, API, or UI
  in that checkpoint.

## Milestone 4.2 Sol checkpoint 1 — closed execution contracts

### Starting state

- Branch: `milestone-4-controlled-agents`.
- Starting local and remote SHA: `3ab717199470da6b82b36da559c1ccc5a84e8c29`.
- Protected tag object: `acbde89b6e2cc3e41c372887794726d393836716`.
- Protected tag peeled commit: `b45b7763b65861f9dfb3be7edf9b5eb271950917`.
- Working tree at start: clean.

### Sol safety-core scope and active unit

Milestone 4.2 has started only as a bounded internal safety-core implementation. The first safe
unit defines the closed action and immutable request/plan/idempotency contracts. It does not execute
an agent, call a provider, expose a public route, or create a workspace effect.

### Completed

- Defined the only action as `generate_grounded_draft` in an immutable closed registry.
- Bound the action to a fixed allowlist of read/draft capabilities, maximum `r1_draft` risk, and
  explicit prohibitions on workspace mutation, external effects, and delegation.
- Added a strict internal request contract containing server-resolved user scope, workspace,
  canvas, context/plan references and expected digests, stored grant/approval references,
  idempotency key, optional client request ID, and correlation ID.
- Added a fixed six-stage plan: validate authority, load immutable context, retrieve selected
  evidence, generate grounded draft, validate citations, and record/return.
- Added a canonical idempotency fingerprint scoped to user, workspace, canvas, action, key,
  immutable content, and stored authority. Transport correlation metadata does not change retry
  identity.
- Added focused tests proving the registry is closed, unknown actions and injected raw authority
  are rejected, plan order and digest are stable, conflicting content changes retry identity, and
  contracts are immutable.

### Partial and deferred

- Authority loading, policy orchestration, approval consumption, database idempotency, append-only
  transition validation, immutable source resolution, cancellation, and late-result suppression
  are not implemented in this first unit.
- Provider generation, citation generation, Trace completion, public execution/cancel routes, and
  UI are deferred to the Terra continuation and were not started.
- PostgreSQL status: **NOT RUN**. No migration changed in this unit.
- Low-usage recovery trigger activated after checkpoint 1. No second implementation unit was
  started; only the existing approval transaction and canvas fixture were inspected.

### Files changed

- `apps/api/opencanvas_api/services/agents/execution.py`
- `apps/api/tests/test_agent_execution_contracts.py`
- `docs/MILESTONE_4_PROGRESS.md`

### Focused validation

- Contract tests: `6 passed`.
- Changed-file Ruff format: passed.
- Changed-file Ruff lint: passed after correcting the test-only assertion style.
- Focused mypy: passed for two source/test files.
- `git diff --check`: passed.
- Full backend, security, demo, PostgreSQL, frontend, and production suites: not run for this narrow
  checkpoint.

### Checkpoint result

- Commit created: `daaa5106582929fd05d7f884eb11f9f31b801327` —
  `Define the controlled execution safety boundary`.
- Commit pushed normally only to `origin/milestone-4-controlled-agents`.
- Local and remote SHA after fetch: `daaa5106582929fd05d7f884eb11f9f31b801327`.
- Working tree after the implementation push: clean.
- Sol safety-core completion status: **partial**. Do not begin Terra provider integration.

### Exact next unit

Inspect the existing `ControlledAgentRepository.consume_approval` transaction and add the smallest
trusted preflight authority boundary that loads the stored execution/context/plan/grant/approval,
uses the pure deny-by-default evaluator, and reuses atomic one-time consumption. Design and test
database idempotency separately if the current schema cannot enforce it. Do not add a provider call,
public API, UI, tool/effect, worker, queue, scheduler, or delegation.

### Exact resume commands

```powershell
cd C:\Users\hawke\Documents\Codex\2026-07-18\referenced-chatgpt-conversation-this-is-untrusted\work\opencanvas-ai
git branch --show-current
git status --short
git fetch origin
git rev-parse HEAD
git rev-parse origin/milestone-4-controlled-agents
git show-ref --tags -d competition-demo-v1
Get-Content docs/MILESTONE_4_PROGRESS.md
```

## Milestone 4.1B documentation completion checkpoint

### Git state at checkpoint preparation

- Current branch: `milestone-4-controlled-agents`.
- Starting local and remote SHA: `3770782e3d4f46306bdbdf5fd2cdb55309767b25`.
- Protected `competition-demo-v1` peeled commit:
  `b45b7763b65861f9dfb3be7edf9b5eb271950917`.
- Working tree at start: clean.
- Milestone 4.2 work started: **No**.

### Documentation completed

- Added `docs/CONTROLLED_AGENT_DATA_POLICY.md` as an unapproved engineering policy proposal.
- Classified all ten append-only controlled-agent record families and their common identifiers,
  source references, hashes, timestamps, safe errors, and provider/model metadata.
- Proposed cautious retention defaults: 12 months for completed/failed execution history, grants,
  revocations, approvals, consumptions, and denied policy decisions; 90 days for context/plan
  snapshots and export-request records; 24 months for security audit events; and 30–90 days for
  operational logs. Every duration is explicitly subject to privacy, legal, security, and
  operations approval.
- Defined a future erasure model using access revocation, active-content deletion,
  pseudonymization, redacted projections, disposition evidence, and cryptographic erasure without
  rewriting immutable history or historical hashes.
- Defined the required legal-hold contract. No legal-hold API or approved process exists.
- Defined purpose-specific inspection, user, export, and security views. The current safe GET
  projection is only a partial foundation; a production redaction workflow is not implemented.
- Marked envelope encryption, per-user/workspace keys, and audited key destruction as required
  before production acceptance of sensitive snapshot payloads. They are not implemented.
- Completed the engineering enforcement gap table with current evidence, owners, target reviews,
  and production blockers.
- PostgreSQL trigger validation remains **NOT RUN** because PostgreSQL/Docker was unavailable. The
  authoritative integration test exists but is not represented as passed.

### Focused validation

- Changed-document Prettier: passed for `docs/CONTROLLED_AGENT_DATA_POLICY.md` and this ledger.
- `git diff --check`: passed.
- Repository hygiene and built-in secret scan: passed for `206` source files.
- Final scope audit: passed; exactly two Markdown files changed and no source, migration,
  configuration, dependency, UI, runtime, worker, queue, scheduler, provider, tool, or effect file
  changed.
- Full backend, frontend, migration, demo, and PostgreSQL suites: not run because this checkpoint
  changes documentation only.

### Remaining production blockers

- Policy approval by engineering, security, privacy, legal/compliance, and operations.
- Authoritative PostgreSQL trigger execution in a PostgreSQL-capable environment.
- Approved retention and deletion orchestration, pseudonymization, redacted/export/operator views,
  legal holds, per-user/workspace envelope encryption and key destruction, backup erasure, and
  controlled-agent incident-response operations.
- Reconciliation of restrictive append-only evidence with account and workspace deletion.

### Exact next step

Commit and normally push this documentation-only checkpoint, then stop. Milestone 4.2 remains
unstarted and requires separate explicit approval. Do not implement policy enforcement, retention
jobs, holds, encryption, mutation APIs, agent runtime behavior, or later-milestone work in this
checkpoint.

## Recovery checkpoint — PostgreSQL trigger test architecture

### Git state at checkpoint preparation

- Current branch: `milestone-4-controlled-agents`.
- Starting SHA: `567f1a82b90044488924ee5f31b3fa3a1a541137`.
- Current local SHA before the recovery commit:
  `567f1a82b90044488924ee5f31b3fa3a1a541137`.
- Current remote SHA before the recovery push:
  `567f1a82b90044488924ee5f31b3fa3a1a541137`.
- Completed recovery implementation SHA:
  `f0a744b9d496f7046c4bacb9242e176aaf770db0`.
- Current local and remote implementation SHA after the successful normal push:
  `f0a744b9d496f7046c4bacb9242e176aaf770db0`.
- The progress-ledger handoff commit follows that implementation commit; use the exact resume
  commands below to resolve its local and remote SHA without relying on a self-referential hash.
- Protected tag object: `acbde89b6e2cc3e41c372887794726d393836716`.
- Protected tag peeled commit: `b45b7763b65861f9dfb3be7edf9b5eb271950917`.
- Milestone 4.2 work started: **No**.

### Completed in this recovery unit

- Added an explicit `postgres` pytest marker and `pnpm test:postgres` command.
- Added fail-closed validation for `OPENCANVAS_POSTGRES_TEST_URL`. Local tests require a loopback
  PostgreSQL URL whose database name has a distinct test/CI segment and no development, staging, or
  production terminology.
- Added a fixture that creates a random disposable PostgreSQL database, upgrades it through Alembic,
  and drops it after the session.
- Added direct-SQL PostgreSQL coverage for all ten controlled-agent tables: trigger presence,
  rejected UPDATE/DELETE, composite execution/user/workspace scope, unique approval consumption,
  readable retained history, and unchanged hashes.
- Added an in-memory PostgreSQL 17 Compose test profile and CI wiring.
- Added exact local and CI run instructions in `docs/CONTROLLED_AGENT_POSTGRES_TESTING.md`.

### Partial or not started

- PostgreSQL execution result: **NOT RUN**. Docker is not installed, no listener exists on ports
  5432/55432, and `OPENCANVAS_POSTGRES_TEST_URL` is unset. The marked integration test reported one
  explicit skip; it is not recorded as passed.
- `docs/CONTROLLED_AGENT_DATA_POLICY.md`: not started.
- Retention/erasure/legal-hold/redaction/cryptographic-erasure policy: not started.
- Engineering enforcement gap table: not started.
- Full backend, security, migration-cycle, and demo smoke gates: not run for this recovery unit. The
  previous 4.1B results below remain historical evidence only.

### Files changed in this recovery unit

- `.github/workflows/ci.yml`
- `apps/api/pyproject.toml`
- `apps/api/tests/postgres_support.py`
- `apps/api/tests/test_agent_postgres.py`
- `apps/api/tests/test_postgres_support.py`
- `docker-compose.yml`
- `package.json`
- `docs/CONTROLLED_AGENT_POSTGRES_TESTING.md`
- `docs/MILESTONE_4_PROGRESS.md`

### Focused checks run

- Ruff format for the three PostgreSQL test files: passed.
- Ruff lint for the three PostgreSQL test files: passed.
- Focused mypy for the three PostgreSQL test files: passed; the initial missing `asyncpg` type-stub
  error was corrected with the existing project override mechanism.
- Safe PostgreSQL URL tests: `5 passed`.
- PostgreSQL integration marker without configured service: `1 skipped` — **NOT RUN**.
- Prettier for the changed YAML, JSON, and Markdown files: passed.
- Repository hygiene and built-in secret scan: passed for `205` source files.
- Prohibited-scope audit: passed. No agent runtime, execution stage, effect tool, queue, scheduler,
  delegation, durable workspace mutation, external AI/embedding call, production dependency, new
  UI, or later-milestone implementation was added.
- Known current failures: none in the focused runnable checks.

### Exact next implementation step

Resume the remaining Milestone 4.1B feedback with documentation only: create
`docs/CONTROLLED_AGENT_DATA_POLICY.md` covering data classification, proposed retention periods,
privacy erasure without history rewrites, legal holds, redacted projections, future envelope
encryption/key destruction, backups/replicas/logs/exports/test copies, required approvals, and the
engineering enforcement gap table. Do not begin Milestone 4.2 or implement retention workers,
deletion jobs, legal-hold APIs, encryption systems, mutation endpoints, or agent behavior.

### Exact resume commands

```powershell
cd C:\Users\hawke\Documents\Codex\2026-07-18\referenced-chatgpt-conversation-this-is-untrusted\work\opencanvas-ai
git branch --show-current
git status --short
git fetch origin
git rev-parse HEAD
git rev-parse origin/milestone-4-controlled-agents
git show-ref --tags -d competition-demo-v1
Get-Content docs/MILESTONE_4_PROGRESS.md
```

When Docker is available, run the authoritative PostgreSQL check separately:

```powershell
docker compose --profile test up -d postgres-test
$env:OPENCANVAS_POSTGRES_TEST_URL = "postgresql+asyncpg://opencanvas_test:local-test-only@127.0.0.1:55432/opencanvas_test_admin"
pnpm test:postgres
docker compose --profile test down
```

## Repository state

- Current branch: `milestone-4-controlled-agents`
- Branch point and completed Milestone 3.75 checkpoint:
  `ff34f22b6264f9a0e12b8fa5d8e66dcd2e7074a4`
- Starting remote branch: `origin/milestone-3.75-visual-redesign` at
  `ff34f22b6264f9a0e12b8fa5d8e66dcd2e7074a4`
- Protected `competition-demo-v1` tag object:
  `acbde89b6e2cc3e41c372887794726d393836716`
- Protected `competition-demo-v1` commit:
  `b45b7763b65861f9dfb3be7edf9b5eb271950917`
- Push target for future authorized pushes: `origin/milestone-4-controlled-agents` only.

## Milestone 4.0 objective

Define the controlled-agent architecture, permission and approval model, execution boundaries,
Trace/audit requirements, deterministic demo constraints, failure rules, prohibited behavior, and
4.1–4.4 implementation sequence before any agent behavior is implemented.

## Completed work

- Verified the clean Milestone 3.75 local/remote handoff and protected demo tag.
- Created `milestone-4-controlled-agents` directly from `ff34f22`.
- Inventoried the complete repository and documentation set.
- Inspected the existing system, security, Trace, provider, authorization, job, worker, usage, and
  deterministic-demo boundaries.
- Confirmed the existing document worker is ingestion-specific and must not become an agent runtime.
- Defined the controlled-agent architecture and safety contract.
- Defined role taxonomy, scope hierarchy, closed capabilities, risk classes, and server-minted
  grants.
- Defined structured plans, explicit approval binding, execution states, tool contracts, audit
  evidence, failure/rollback rules, and demo isolation.
- Defined queue/scheduler safety requirements without implementing either.
- Defined allowed/prohibited behavior and Milestone 4.1–4.4 gates.
- Pushed the Milestone 4.0 planning checkpoint to
  `origin/milestone-4-controlled-agents` and configured that branch as upstream.
- Added frozen, versioned control-plane contracts for executions, append-only execution states,
  immutable context and plan snapshots, capability grants, approvals, revocations, audit events,
  and policy decisions.
- Added canonical serialization and domain-separated SHA-256 hashing for plans, contexts, grants,
  and approvals.
- Added a pure, side-effect-free, deny-by-default policy evaluator with exact ownership, scope,
  resource, hash, validity, revocation, approval, and replay checks.
- Added deterministic unit coverage for contract immutability and policy denial boundaries.
- Completed Milestone 4.1B persistence mapping for every 4.1A security contract.
- Added append-only database and ORM enforcement, composite ownership constraints, and indexed
  scoped reads.
- Added atomic, unique approval consumption that revalidates stored canonical hashes and records
  policy outcomes.
- Added one bounded, authenticated, read-only execution-inspection endpoint that omits raw payloads
  and secret-bearing fields.
- Documented evidence retention, expiry-versus-deletion, future hold requirements, and the privacy
  policy work required before active production use.

## Current phase

- Milestone 4.1B persistence-boundary validation and handoff. Milestone 4.2 is unstarted.

## Files changed in this checkpoint

- `apps/api/alembic/versions/20260721_0007_controlled_agent_persistence.py`
- `apps/api/opencanvas_api/db/models.py`
- `apps/api/opencanvas_api/services/agents/persistence.py`
- `apps/api/opencanvas_api/api/agent_schemas.py`
- `apps/api/opencanvas_api/api/routes/agents.py`
- `apps/api/opencanvas_api/api/router.py`
- `apps/api/tests/agent_fixtures.py`
- `apps/api/tests/test_agent_persistence.py`
- `apps/api/tests/test_agent_persistence_schema.py`
- `apps/api/tests/test_agent_api.py`
- `apps/api/tests/test_migration.py`
- `scripts/validate_migrations.py`
- `docs/MILESTONE_4_CONTROLLED_AGENT_ARCHITECTURE.md`
- `docs/MILESTONE_4_PROGRESS.md`
- `docs/SECURITY_MODEL.md`
- `docs/TRACE.md`

## Runtime boundary confirmation

- No agent runtime, provider call, tool adapter, mutation API, dependency, or production service was
  added. The new migration and models persist inert control-plane evidence only; the new API route
  is GET-only inspection.
- No document-worker, queue, heartbeat, retry, or scheduler implementation was changed.
- No autonomous execution, recursive delegation, decision loop, or background behavior was added.
- No external AI or embedding call was added.
- No production service or configuration requirement was added.
- No canvas or deterministic demo code or fixture was changed.

## Validation status

- Focused 4.1A/4.1B contract, policy, persistence, schema, API, and migration tests: `40 passed`.
- Complete backend suite: `153 passed`.
- Security-marked backend suite: `26 passed`, `127 deselected`.
- Demo-mode regression suite: `10 passed`.
- Deterministic demo reset, isolation/provenance check, and startup smoke: passed; API readiness,
  replay runtime, and web page were ready without live providers.
- Migration validator: passed upgrade to `20260721_0007`, downgrade to `20260721_0006`, and
  re-upgrade to `20260721_0007`.
- Full backend Ruff: passed.
- Full backend strict mypy: passed for `51` source files.
- Focused Ruff formatting for all changed Python files: passed (`11` files already formatted).
- Focused Prettier for the four changed Markdown files: passed.
- Full backend Ruff formatting still reports the pre-existing untouched
  `apps/api/scripts/demo.py` backlog; that unrelated file remains unchanged.
- Repository hygiene and built-in secret scan: passed for `201` source files.
- Final staged `git diff --check`: passed.
- Staged scope: exactly 16 Milestone 4.1B migration, model, repository, read-only API, test,
  validation-script, and documentation files.
- Prohibited-scope scan found no provider/embedding integration, HTTP/network client, subprocess,
  task loop, background behavior, tool call, queue, scheduler, job, or delegation implementation in
  the new production source.
- Protected tag recheck: unchanged at tag object
  `acbde89b6e2cc3e41c372887794726d393836716`, resolving to
  `b45b7763b65861f9dfb3be7edf9b5eb271950917`.

## Milestone 4.1B completion confirmation

- Security-relevant tables reject UPDATE and DELETE; lifecycle, revocation, decision, and
  consumption history is append-only.
- Stored snapshot payloads retain the 4.1A canonical digest and consumption fails if the payload,
  digest, or execution binding changes.
- Approval consumption is transactionally paired with its allow decision and protected by a
  unique approval constraint; repeated consumption produces an auditable denial.
- Repository and API reads require the authenticated user, owned workspace, and execution scope.
- The only endpoint added is GET-only, bounded, and omits raw payloads and secret-bearing fields.
- No active agent execution, provider, tool, effect, worker, queue, scheduler, job, delegation,
  external call, or autonomous behavior was added.
- Demo fixtures and behavior remain unchanged, and Milestone 4.2 remains unstarted.

## Policy boundary confirmation

- Unspecified and malformed capabilities are rejected by the closed contract; absent authority is
  denied by default.
- Policy evaluation is deterministic and has no I/O or state mutation.
- Approvals bind to exact plan/context digests, capability/resource scope, user, workspace,
  execution, grant, policy version, and validity window; consumed approvals are denied as replayed.
- Security records are frozen value objects. Changes require a distinct record/digest, while
  revocation and execution-state changes use explicit append-only records.

## Known pre-existing limitations

- Full-repository Prettier has an existing untouched-file backlog recorded by Milestone 3.5/3.75.
- Docker/PostgreSQL/live-provider deployment validation remains outside this persistence-boundary
  checkpoint. The migration implements PostgreSQL append-only triggers, but this local gate
  exercised SQLite only.
- Existing document processing has a persisted database job and independent worker. It is not a
  dedicated agent execution platform.
- Restrictive audit-record deletion preserves evidence but requires a reviewed privacy-erasure,
  legal-hold, retention-duration, and cryptographic-erasure policy before active production use.

## Next exact implementation step

After this final Milestone 4.1B checkpoint is committed and pushed, stop. Milestone 4.2 requires a
separate approval. Its exact proposed scope is one synchronous, explicitly user-initiated,
cancellable, read-only execution over one owned canvas and selected immutable context, using the
existing provider configuration and limits. It may retrieve selected sources, generate a grounded
draft, and verify citations. It must add no durable workspace write, effect tool, agent job, queue,
scheduler, or delegation.

## Recovery prompt

```text
Resume Milestone 4 controlled-agent work from docs/MILESTONE_4_PROGRESS.md. Verify the current
branch, clean tree, latest commit, origin branch, and competition-demo-v1 at
b45b7763b65861f9dfb3be7edf9b5eb271950917 before changing anything. Continue only the exact next
action recorded in the ledger. Preserve APP_MODE=demo and do not add active behavior beyond the
approved Milestone 4 phase. Run focused validation, audit prohibited scope, commit a coherent
checkpoint, and push only to origin/milestone-4-controlled-agents when explicitly authorized.
```

## Scope confirmations

- No default branch change, merge, pull request, force push, or tag operation.
- No Milestone 5 or later work.
- No secrets, credentials, dependency directories, temporary files, test databases, or partial
  experiments intended for commit.
