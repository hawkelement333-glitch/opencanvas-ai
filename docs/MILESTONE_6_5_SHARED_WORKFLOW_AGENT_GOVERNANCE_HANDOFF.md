# Milestone 6.5 Shared Workflow and Agent Governance Handoff

Date: 2026-07-26

Status: complete locally; ready for Milestone 6.6

Branch: `milestone-6-5-shared-workflow-agent-governance-local`

Migration: `20260725_0025`

Direct parent: `20260725_0024`

## Completion boundary

Milestone 6.5 implements secure listing, inspection, and invocation of shared
workflow and agent identities. It does not implement the Milestone 6.6
collaboration interface, sharing administration UI, workspace navigation,
Advanced Real-Time Collaboration, Milestone 7 Indexer work, Mobius Society, or
the governed Librarian.

Visibility and invocation remain distinct. A user may see a workflow or agent
only through current typed-resource visibility. Invocation additionally
requires an active exact membership and the closed `workflow.invoke` or
`agent.invoke` permission. Neither path grants ownership, editing, version
creation, activation, approval, capability creation, suspension, retirement,
transfer, export, publication, or management authority.

## Persistence and migration

Revision `20260725_0025` is the sole Alembic head and direct child of
`20260725_0024`. It makes no changes to migrations `0021` through `0024` and
creates no later revision.

The migration:

- adds `definition_owner_user_id`, `invoking_membership_id`, and
  `authority_snapshot_id` to controlled workflow executions and bounded agent
  invocations;
- reinforces workflow-version to workflow-identity/owner scope and
  agent-version to agent-identity/owner scope with composite uniqueness and
  foreign keys;
- binds workflow executions to the exact immutable version, parent identity,
  definition owner, invoking user, membership, workspace, canvas, and
  authority snapshot;
- binds agent invocations to the exact agent version, definition owner,
  invoking user, membership, workspace, canvas, authority snapshot, workflow
  version, and resulting workflow execution;
- adds invoker/authority indexes for both invocation paths;
- preserves append-only SQLite guards after table recreation and emits valid
  PostgreSQL offline DDL; and
- provides downgrade to `0024` and deterministic re-upgrade.

The workflow execution snapshot reference is nullable at the physical insert
boundary only to break the execution/snapshot composite foreign-key cycle. The
service flushes the execution, creates the snapshot, assigns its identifier,
and flushes both inside the same nested transaction. No successful service
result can retain a missing snapshot. Agent invocation snapshots are non-null
at insertion.

## Deterministic legacy backfill

For each legacy execution and invocation, the recorded user remains both the
definition owner and authenticated invoker. The migration derives the
invoking membership only when append-only membership transitions prove
exactly one membership was active for that exact user and workspace at the
row timestamp. It also requires reconstructable historical resource ownership
at that timestamp.

Zero matches, more than one match, inactive-only evidence, cross-workspace
evidence, missing ownership evidence, or an agent/workflow membership mismatch
aborts the migration atomically. The migration never invents a membership,
rewrites actor identity, or retroactively treats a later 6.1 owner-membership
backfill as historical authority. The unresolved attribution count for a
successful migration is therefore zero.

Derived snapshots preserve the exact role, invocation permission, authority
generation, typed resource and ownership basis, workflow execution, Trace,
and capture time. Existing execution, invocation, request-idempotency, Trace,
event, outbox, activity, effect, retry, cancellation, compensation, export,
and publication identities remain unchanged.

## Definition owner, invoker, and immutable version

Workflow and agent identities retain their original owner. Immutable versions
remain children of the parent identity and owner scope; they cannot be shared
or authorized independently. The server resolves the requested version inside
the exact workspace and canvas and verifies its parent, digest, and current
lifecycle.

Workflow executions and bounded agent invocations store the authenticated
invoking user separately from `definition_owner_user_id`. They also store the
exact active `invoking_membership_id`. Invocation does not mutate the identity,
version, ownership, or lifecycle of the shared definition.

Agent invocation stores a defensive composite link to the workflow execution
created for the same invoking user, membership, workflow version, workspace,
and canvas. Agent authority evidence references that resulting workflow
execution.

## Shared visibility and safe inspection

The workflow API adds bounded shared-definition listing and permits exact
shared definition inspection. Agent list/get operations use the same current
typed visibility evaluator. Hidden and revoked resources are omitted rather
than enumerated.

Shared agent inspection excludes other users' invocation/evaluation records,
proposals, activation evidence, workflow bindings, capability requirements,
and private authority details. API serializers do not expose raw authority
snapshots, grants, approval internals, policy structures, hidden prompts,
credentials, or private reasoning.

## Invocation governance

`SharedInvocationGovernanceService` centralizes:

- exact authenticated user and current active membership resolution;
- exact membership generation validation;
- typed workflow/agent resource visibility and current share/ownership state;
- separate `workflow.invoke` or `agent.invoke` collaboration permission;
- current workspace authority generation; and
- immutable authority-snapshot capture through the existing revocation-fence
  service.

Workflow invocation also requires an active supported immutable version and
exact currently visible selected context. Agent invocation additionally
requires active identity/version state, a valid approved activation request,
an exact persisted workflow binding and digest, and all existing controlled
workflow context and execution checks.

Collaboration role and permission are only eligibility ceilings. They do not
replace Milestone 4 capabilities, grants, risk classification, approvals,
policy decisions, one-time consumption, effect authority, or compensation
authority. The collaboration `approver` role does not approve a controlled
action.

## Revocation, stale authority, and cache behavior

The authority snapshot records the invoker, membership, role, permission,
typed resource, ownership/share basis, authority generation, and workflow
execution linkage. Existing revocation fences re-evaluate current authority at
claim, provider/service call, tool call, retry, effect, continuation,
compensation, export, publication, and result-commit boundaries.

Membership suspension/removal, role reduction, share revocation, ownership
transfer, lifecycle change, capability or approval expiry/revocation, and
authority-generation change deny stale continuation. Definition ownership
cannot preserve an invoker's lost authority. Existing lease generations and
stale-result suppression prevent a recovered or superseded worker from
committing.

No new cache infrastructure was added. Current visibility is evaluated from
authoritative state and captured decisions are generation fenced. Frontend
cache state is never authority.

## Evidence integration

The implementation extends existing evidence systems:

- workflow execution and bounded agent invocation rows preserve exact owner,
  invoker, membership, version, request, execution, and snapshot linkage;
- Trace roots attribute the authenticated invoker and retain parent version
  traces;
- successful invocations add bounded `CollaborationAuditEvent` records with
  action `workflow.invoke` or `agent.invoke`;
- the requested/started domain event links the audit identifier and records
  the authenticated invoker as `actor_user_id`;
- the existing transactional outbox and activity projector consume those
  domain events; and
- idempotent replay returns the existing execution/invocation without
  duplicate mutation, Trace, audit, event, outbox, or activity evidence.

Audit and event metadata contains identifiers and digests only. It does not
contain selected context contents, raw grants, approval internals, authority
snapshots, prompts, tokens, secrets, credentials, or model chain of thought.

## API and service changes

- Workflow routes expose bounded shared definition listing and exact safe
  inspection while keeping route handlers thin.
- Agent Studio routes use shared visibility for list/get and preserve
  owner-only management operations.
- Workflow and Agent Studio services resolve immutable versions by exact
  server-derived scope and persist truthful invocation identities.
- `SharedInvocationGovernanceService` composes collaboration visibility,
  permission, membership, generation, ownership/share, and snapshot behavior.
- Domain-event scope permits exact active non-owner actors only when the
  workflow execution, workflow step, or agent invocation belongs to that
  actor and workspace; established owner-emitted event producers remain
  compatible.
- Controlled execution claim converts a missing collaboration fence into the
  established bounded `authority_not_found` denial.

The frontend and dependencies are unchanged.

## Tests and validation

Focused tests prove shared owner/member workflow and agent invocation,
truthful definition owner/invoker/membership/snapshot attribution, workflow
execution linkage, audit/event actor linkage, and safe visibility behavior.
Migration tests prove sole head, SQLite upgrade/downgrade/re-upgrade,
PostgreSQL offline DDL, exact parent/scope columns and constraints, append-only
guards, and historical membership cases for exact, missing, inactive,
ambiguous, and cross-workspace evidence.

Final results:

- complete backend: 518 passed, 1 skipped, 0 failed;
- focused shared governance: 2 passed, 0 failed;
- focused migration matrix: 6 passed, 0 failed, 25 Python datetime-adapter
  deprecation warnings;
- integration: 22 passed, 0 failed, 1 Starlette deprecation warning;
- security marker: 38 passed, 0 failed;
- PostgreSQL runtime marker: 1 skipped because no configured PostgreSQL test
  URL was available;
- mypy strict: 83 source files, 0 issues;
- compilation/import: passed; API title/version import returned
  `SolarPlexus Mobius API`; mapper configuration covered 121 tables;
- migration validator: upgrade `0025`, downgrade `0024`, re-upgrade `0025`;
- PostgreSQL offline DDL: passed in the focused migration suite;
- repository hygiene: 347 source files passed;
- frontend ESLint and TypeScript: passed;
- frontend Vitest: 15 files and 66 tests passed;
- production Next.js build: passed with 8 generated routes;
- Chromium: 6 passed, 2 expected real FastAPI/PostgreSQL scenarios skipped;
- isolated demo reset, persisted-provenance check, and startup smoke: passed;
  and
- pnpm dependency wrapper: blocked before project execution by the known
  ignored-build policy for `sharp@0.34.5` and `unrs-resolver@1.12.2`; locked
  workspace executables were run directly without changing dependency policy.

The repository-wide Ruff command also reports pre-existing formatting/import
ordering differences in two unchanged utility scripts and historical
Alembic/test files. Protected migrations cannot be reformatted. All new and
modified 6.5 production, service, migration, and focused-test files pass
targeted Ruff formatting and lint checks. The broad baseline difference is
recorded rather than hidden or repaired outside checkpoint scope.

The principal validation commands were:

```text
python -m pytest apps/api/tests -q --tb=no --disable-warnings
python -m pytest apps/api/tests -m security -q --tb=short
python -m pytest apps/api/tests -m postgres -q --tb=short
python -m pytest apps/api/tests/test_shared_workflow_agent_governance.py apps/api/tests/test_shared_governance_migration.py -q --tb=short
python -m mypy apps/api/opencanvas_api
python -m compileall -q apps/api/opencanvas_api
python scripts/validate_migrations.py
python scripts/check_repository_hygiene.py
eslint . --max-warnings=0
tsc --noEmit
vitest run
next build
playwright test
prettier --check ../.. --ignore-path ../../.gitignore
python apps/api/scripts/demo.py reset
python apps/api/scripts/demo.py check
python apps/api/scripts/demo.py smoke
git diff --check
git fsck --no-dangling
```

## Security and scope decisions

- Server-derived user, workspace, canvas, membership, parent identity,
  version, and authority generation are authoritative.
- Unknown roles, permissions, lifecycle states, versions, ownership/share
  states, grants, approvals, and policy outcomes fail closed.
- Visibility cannot escalate to invocation or management.
- Invocation cannot transfer ownership or modify immutable definitions.
- Cross-user, cross-membership, cross-workspace, cross-canvas, cross-version,
  and unrelated execution linkage are constrained in services and composite
  foreign keys.
- Selected context stays exact, currently visible, and source-grounded;
  comments, activity, and proposals are not trusted source evidence.
- Failed nested transactions leave no successful execution, invocation,
  snapshot, audit, event, outbox, activity, or Trace completion evidence.

## Bounded limitations and next checkpoint

Configured PostgreSQL runtime tests remain environment-dependent; PostgreSQL
offline DDL passed. SQLite contention tests prove local deterministic behavior,
not production isolation or performance. RLS, managed infrastructure, load
testing, distributed caches, and real-time collaboration remain future work.

Milestone 6.6 owns the multi-workspace collaboration interface. It may build
on the exact server-derived identity and authority seams completed here but
must not weaken them. No collaboration interface, workspace switcher, sharing
administration UI, comments UI expansion, live presence, cursor, CRDT/OT,
offline merge, Indexer, Librarian, Society, or later-milestone work was
started.
