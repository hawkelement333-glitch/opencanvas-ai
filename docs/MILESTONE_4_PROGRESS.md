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

## Current phase

- Milestone 4.1 first control-plane contract checkpoint validation and handoff.

## Files changed in this checkpoint

- `apps/api/opencanvas_api/services/agents/__init__.py`
- `apps/api/opencanvas_api/services/agents/contracts.py`
- `apps/api/opencanvas_api/services/agents/policy.py`
- `apps/api/tests/test_agent_contracts.py`
- `apps/api/tests/test_agent_policy.py`
- `docs/MILESTONE_4_CONTROLLED_AGENT_ARCHITECTURE.md`
- `docs/MILESTONE_4_PROGRESS.md`
- `docs/SECURITY_MODEL.md`
- `docs/TRACE.md`

## Runtime boundary confirmation

- No agent runtime, provider call, tool adapter, API route, database model, migration, or dependency
  was added. A migration was intentionally deferred until table ownership, retention, transaction,
  and read-repository designs are reviewed against these contracts.
- No document-worker, queue, heartbeat, retry, or scheduler implementation was changed.
- No autonomous execution, recursive delegation, decision loop, or background behavior was added.
- No external AI or embedding call was added.
- No production service or configuration requirement was added.
- No canvas or deterministic demo code or fixture was changed.

## Validation status

- Focused contract/policy tests: `17 passed`.
- Complete backend tests, including relevant authentication, workspace-isolation, Trace, demo-mode,
  canonical persistence, and provider regressions: `135 passed`.
- Full backend Ruff: passed.
- Full backend strict mypy: passed for `48` source files.
- Focused Prettier and Ruff formatting checks: passed.
- Repository hygiene and secret-pattern scan: passed for `193` source files.
- Final staged `git diff --check`: passed.
- Prohibited-scope scan of the new Python package and tests found no provider, HTTP/network,
  subprocess, task/loop, worker, queue, scheduler, delegation, or tool-call implementation.
- Staged scope: exactly five contract/test source files and four controlled-agent documentation
  files; no migration, dependency, configuration, demo, fixture, UI, route, worker, or provider
  file.
- Protected tag recheck: unchanged at tag object
  `acbde89b6e2cc3e41c372887794726d393836716`, resolving to
  `b45b7763b65861f9dfb3be7edf9b5eb271950917`.

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
- Docker/PostgreSQL/live-provider deployment validation remains outside this documentation-only
  checkpoint.
- Existing document processing has a persisted database job and independent worker. It is not a
  dedicated agent execution platform.

## Next exact implementation step

After this first Milestone 4.1 checkpoint is committed and pushed, review the frozen contracts as
the persistence boundary. The next separately approved 4.1 checkpoint should design append-only
tables, constraints, approval-consumption transactions, retention/deletion semantics, ownership-
checked read repositories, and read-only inspection APIs. It must still add no provider calls,
tools, effects, agent jobs, schedulers, or delegation. Milestone 4.2 must not start automatically.

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
