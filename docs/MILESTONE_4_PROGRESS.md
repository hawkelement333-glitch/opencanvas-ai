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

## Current phase

- Milestone 4.0 documentation validation and checkpoint commit.

## Files changed in this checkpoint

- `docs/MILESTONE_4_CONTROLLED_AGENT_ARCHITECTURE.md`
- `docs/MILESTONE_4_PROGRESS.md`
- `docs/AGENT_UNIVERSE_ARCHITECTURE.md`
- `docs/ARCHITECTURE.md`
- `docs/SECURITY_MODEL.md`
- `docs/TRACE.md`

## Runtime boundary confirmation

- No agent runtime, provider call, tool adapter, API route, database model, migration, or dependency
  was added.
- No document-worker, queue, heartbeat, retry, or scheduler implementation was changed.
- No autonomous execution, recursive delegation, decision loop, or background behavior was added.
- No external AI or embedding call was added.
- No production service or configuration requirement was added.
- No canvas or deterministic demo code or fixture was changed.

## Validation status

- Focused Prettier write/check for all six changed Markdown files: passed.
- Documentation reference and fenced-block balance check: passed; six documents checked with no
  missing references or unbalanced fences.
- Repository hygiene: passed for `188` source files.
- `git diff --check`: passed before staging; final staged check required immediately before commit.
- Secret-pattern scan: no matches.
- Prohibited-scope audit: passed. All six changes are under `docs/`; no source, migration,
  dependency, configuration, worker, queue, scheduler, provider, service, demo, or fixture file is
  changed. No executable code fence was added.
- Protected tag recheck: unchanged at tag object
  `acbde89b6e2cc3e41c372887794726d393836716`, resolving to
  `b45b7763b65861f9dfb3be7edf9b5eb271950917`.

TypeScript, frontend lint, backend lint/types, unit tests, and builds are not required for a
documentation-only checkpoint unless validation reveals a non-document change.

## Known pre-existing limitations

- Full-repository Prettier has an existing untouched-file backlog recorded by Milestone 3.5/3.75.
- Docker/PostgreSQL/live-provider deployment validation remains outside this documentation-only
  checkpoint.
- Existing document processing has a persisted database job and independent worker. It is not a
  dedicated agent execution platform.

## Next exact implementation step

Begin Milestone 4.1 only after approval: turn the planning document into reviewed persistence and
policy contracts, starting with a deny-by-default capability matrix and migrations for immutable
execution, plan, context, grant, approval, and tool-audit records. Do not add provider calls, tools,
effects, agent jobs, schedulers, or delegation in the first 4.1 checkpoint.

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
