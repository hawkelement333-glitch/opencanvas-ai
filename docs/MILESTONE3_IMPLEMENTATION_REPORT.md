# Milestone 3 implementation report

## Outcome

Milestone 3 is complete. OpenCanvas AI now has a durable Trace Foundation and an additive,
workspace-scoped canonical knowledge model for documents, chunks, notes, executions, and semantic
relationships. The existing spatial canvas, Phase 2 ingestion, selected-document retrieval,
grounded answers, citations, persistence, and mock/live provider behavior remain intact.

The required sequencing was enforced: Trace persistence, service operations, query APIs,
migration, and focused tests were completed first. The Trace-only gate passed before canonical
tables or domain behavior were introduced.

## Architecture decisions

- **Additive compatibility boundary.** Existing canvases, nodes, documents, chunks, AI execution
  evidence, citations, and visual edges remain the working Phase 1/2 data path. Each legacy canvas
  is mapped to a canonical workspace without rewriting user content.
- **Universal identity plus typed detail.** Shared canonical identity, ownership, lifecycle,
  version, metadata, and timestamps live in `canonical_objects`; subtype-specific fields live in
  one-to-one Document, Chunk, Note, and Execution tables.
- **Trace is durable provenance.** Trace events are append-only logical associations rather than
  foreign keys to rows that may be lifecycle-deleted. Application logs remain operational, while
  domain events remain transient extension notifications.
- **Transactional evidence.** A successful canonical mutation and its succeeded Trace event share
  one savepoint/transaction. A rejected or failed mutation is rolled back before a structured
  failure event is persisted by the API transaction.
- **Explicit isolation.** All canonical object operations require a workspace. Relationship source,
  target, and relationship ownership must match, with composite database constraints as defense in
  depth.
- **Controlled lifecycle.** Objects use `created`, `active`, `archived`, and terminal `deleted`.
  Archived objects reject ordinary updates; deleted objects are hidden by default. Every mutation
  advances the deterministic version once.
- **First-class graph relationships.** Directional relationships use a centralized vocabulary,
  mandatory Trace correlation, deterministic duplicate handling, and traced soft removal.
- **Replaceable extension points.** Repository, Trace, event-publisher, and controlled-vocabulary
  boundaries support later storage, outbox, and graph/retrieval implementations without changing
  API contracts.

## Milestone steps completed

1. Inspected the Phase 2 repository, architecture, database layer, API, services, tests, and build.
2. Established a fully green baseline.
3. Implemented and independently validated Trace Foundation.
4. Added canonical persistence and compatibility backfill migrations.
5. Added lifecycle, versioning, validation, repositories, services, relationships, and events.
6. Added strict canonical and Trace APIs.
7. Added focused and full-stack automated coverage, including failure atomicity.
8. Ran the complete validation suite and clean PostgreSQL migration cycle.
9. Updated architecture, checklist, README, and release documentation.

## Database migrations

- `20260717_0003_trace_foundation.py`
  - Creates append-only `trace_events` storage and filtered-query indexes.
  - Records stable event/trace IDs, parent traces, actor/workspace/object associations, operation,
    status, safe metadata, timestamps, and structured error fields.
- `20260717_0004_canonical_persistence.py`
  - Creates `workspaces`, `canonical_objects`, `canonical_documents`, `canonical_chunks`,
    `canonical_notes`, `canonical_executions`, and `canonical_relationships`.
  - Backfills one workspace for each existing canvas using the stable canvas ID and records the
    explicit legacy-canvas mapping.
  - Adds same-workspace composite relationship foreign keys and mandatory relationship `trace_id`.

A clean PostgreSQL/pgvector database upgraded from the base revision through `0004`; revision
`0004` was then downgraded to `0003` and upgraded again successfully. Schema inspection confirmed
all canonical tables, mandatory relationship Trace correlation, and the expected relationship
foreign keys.

## Files added

- `apps/api/alembic/versions/20260717_0003_trace_foundation.py`
- `apps/api/alembic/versions/20260717_0004_canonical_persistence.py`
- `apps/api/opencanvas_api/api/trace_schemas.py`
- `apps/api/opencanvas_api/api/canonical_schemas.py`
- `apps/api/opencanvas_api/api/routes/traces.py`
- `apps/api/opencanvas_api/api/routes/canonical.py`
- `apps/api/opencanvas_api/services/trace.py`
- `apps/api/opencanvas_api/services/canonical/__init__.py`
- `apps/api/opencanvas_api/services/canonical/events.py`
- `apps/api/opencanvas_api/services/canonical/lifecycle.py`
- `apps/api/opencanvas_api/services/canonical/repository.py`
- `apps/api/opencanvas_api/services/canonical/service.py`
- `apps/api/tests/test_trace_api.py`
- `apps/api/tests/test_trace_schema.py`
- `apps/api/tests/test_trace_service.py`
- `apps/api/tests/test_canonical_api.py`
- `apps/api/tests/test_canonical_contract.py`
- `apps/api/tests/test_canonical_lifecycle_events.py`
- `apps/api/tests/test_canonical_repository.py`
- `apps/api/tests/test_canonical_schema.py`
- `apps/api/tests/test_canonical_service.py`
- `docs/MILESTONE3_ARCHITECTURE.md`
- `docs/MILESTONE3_CHECKLIST.md`
- `docs/MILESTONE3_IMPLEMENTATION_REPORT.md`

## Files modified

- `README.md`
- `pnpm-workspace.yaml`
- `apps/api/opencanvas_api/db/models.py`
- `apps/api/opencanvas_api/api/dependencies.py`
- `apps/api/opencanvas_api/api/router.py`
- `apps/api/tests/test_migration.py`

No frontend feature code was replaced or redesigned for this backend-first milestone.

## Validation commands and results

Run from the repository root with the Python virtual environment activated:

```powershell
python -m pip install -e "apps/api[dev]"
$env:CI = "true"
pnpm install --frozen-lockfile
pnpm format:check
pnpm lint
pnpm typecheck
pnpm test
pnpm test:security
pnpm --filter @opencanvas/web test:e2e -- --reporter=list
pnpm build
```

Results:

- Dependency installation: passed. Workspace policy now explicitly permits the required `sharp`
  and `unrs-resolver` install scripts for reproducible non-interactive installation.
- Pre-change baseline: green; there were no pre-existing test, lint, type-check, migration, or
  production-build failures to carry forward.
- Mandatory Trace prerequisite gate: 10/10 focused tests passed before canonical implementation
  began; the backend suite was 60/60 at that boundary.
- Final focused canonical gate: 28/28 contract, API, lifecycle/event, repository, schema, and
  service tests passed.
- Formatting: Prettier and Ruff passed.
- Linting: ESLint and Ruff passed.
- Strict typing: TypeScript and mypy passed across 39 Python source files.
- Frontend tests: 22/22 Vitest tests passed.
- Backend tests: 89/89 pytest tests passed.
- Security tests: 12 passed (77 non-security tests deselected by the marker expression).
- Browser tests: 2 passed; 2 real-API tests skipped by their explicit opt-in condition.
- Production build: Next.js 16.2.10 optimized build passed.
- PostgreSQL migration: clean upgrade, downgrade, re-upgrade, and schema inspection passed.

There are no implementation-caused failing checks and no completion blocker. An initial aggregate
format wrapper encountered the Windows Store Python shim, so validation was rerun with the project
virtual environment activated. An initial non-interactive pnpm install rejected undeclared native
build scripts; the explicit workspace allow-list fixed the reproducibility policy rather than
bypassing it.

## Environment and startup

Milestone 3 adds no environment variables. Existing server/database configuration remains valid.
For a local PowerShell startup:

```powershell
Copy-Item .env.example .env
docker compose up -d db
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e "apps/api[dev]"
$env:CI = "true"
pnpm install --frozen-lockfile
pnpm db:migrate
```

Then run `pnpm dev:api` in the activated terminal and `pnpm dev:web` in a second terminal. Open
`http://localhost:3000`. Leave `OPENAI_API_KEY` empty to use the deterministic mock providers.

## Risks and known limitations

- No authorization policy exists yet; workspace ownership is a data-isolation hook, not access
  control.
- Domain events are process-local and are published before the API's outer transaction commits.
  External side effects require a transactional outbox before multi-replica production use.
- Direct service callers must commit retained failure evidence after catching a failed mutation;
  the shipped API routes do this consistently.
- Repository rules enforce subtype and chunk-parent invariants, while privileged raw SQL could
  bypass those application checks.
- JSON values are structurally sanitized but do not yet have independent byte-size/depth quotas.
- Existing visual notes and edges are not silently reinterpreted as canonical knowledge objects.
- Trace UI, replay, comparison, retention/redaction policy, and evaluation are intentionally
  deferred.

## Deferred work and recommended next milestone

Do not begin Trace UI work yet. The next milestone should attach Phase 2 ingestion identities to
canonical Document and Chunk records, then implement **semantic memory, hybrid search, and
workspace-wide knowledge discovery**. That milestone should combine vector, lexical, and graph
signals while preserving canonical source identity and Trace provenance for every retrieval and
answer operation.
