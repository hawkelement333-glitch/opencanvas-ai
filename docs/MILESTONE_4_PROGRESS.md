# Milestone 4 Controlled Agents Progress Ledger

Last updated: 2026-07-21 (America/Chicago)

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
