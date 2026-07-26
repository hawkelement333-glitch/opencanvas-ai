# Milestone 6.7 Final Collaboration Security Audit Handoff

Date: 2026-07-26

Branch: `milestone-6-7-final-collaboration-security-audit-local`

Starting commit: `fd8b625bcf0f7650e15efdfba329d33153c59c21`

Starting parent: `ef074bc1a38dd63f24dfdca46ec334fc29ea68d1`

Commit message: `Complete Milestone 6 collaboration security audit`

Status: complete locally

## Completion boundary

This checkpoint audited Milestones 6.1–6.6 as one collaboration system,
including their composition with Milestone 4 controlled-agent authority and
Milestone 5 graph, retrieval, workflow, Agent Studio, Trace, domain-event,
transactional-outbox, and activity contracts.

All 14 required audit areas were completed. Two concrete defects were proved
and corrected. No new product feature, dependency, API, database field,
migration, deployment behavior, Milestone 7 implementation, Advanced
Real-Time Collaboration behavior, Indexer, governed Librarian, Mobius Society,
or later product-family behavior was added.

## Audit method

The audit:

1. verified the exact clean, no-upstream starting commit and protected refs;
2. verified all completed Milestone 6 checkpoints and amendments were
   reachable;
3. verified the sole Alembic head, migration ancestry, immutable blob hashes,
   and absence of a later revision;
4. reviewed the Milestone 4–6 authority, persistence, API, frontend, evidence,
   migration, and roadmap contracts;
5. inspected the 89-file Milestone 6.1–6.6 change surface;
6. ran the untouched complete backend regression before applying a product
   correction;
7. reproduced each defect with a focused deterministic check;
8. applied the smallest correction and added a permanent regression guard;
9. ran focused, affected, complete, browser, migration, demo, static,
   hygiene, and Git validation.

## Proven defects and corrections

### M6.7-01 — authenticated-user scope missing from visible-canvas cache key

Severity: medium.

Contract violated: frontend collaboration query data must be partitioned by
authenticated user, workspace, authority generation, and resource or
automation identity. The browser is not an authority source, and cached data
from one authenticated session must not be reusable by another.

Proof: the collaboration console used
`["canvases", workspaceId, authorityGeneration]` for the visible-canvas list.
Every other collaboration query family included the authenticated user. A
focused contract regression failed with one failed and three passed tests
because no user-scoped `collaborationKeys.canvases` family existed.

Root cause: the canvas list used an older direct key instead of the closed
collaboration key factory.

Correction:

- added `collaborationKeys.canvases(userId, workspaceId,
authorityGeneration)`;
- changed the automation canvas query to use that key;
- retained existing cancellation/removal by the user/workspace collaboration
  prefix.

Regression: the cache-key contract now asserts the exact key and proves that
different authenticated users cannot share it. The focused cache and
collaboration-console suite passes 8 tests; the complete frontend suite passes
74 tests.

### M6.7-02 — tracked absolute user-home paths in historical command examples

Severity: low.

Contract violated: repository validation must not retain local workstation
paths or user identity in portable documentation.

Proof: the repository-wide path scan found four tracked Milestone 4 command
examples containing an absolute Windows user-home path.

Root cause: historical handoff commands recorded the local checkout location
instead of a repository-root placeholder.

Correction:

- replaced the four path instances with `<repository-root>` without changing
  any historical milestone fact;
- extended `check_repository_hygiene.py` to reject Windows, macOS, and Linux
  user-home paths in tracked source files.

Regression: repository hygiene passes for 357 source files, and the
independent tracked-path scan reports no user-home paths.

## Audit areas with no product finding

### 1. Tenant and workspace isolation

Exact authenticated user, workspace, canvas, resource, membership, share,
owner, lifecycle, and authority-generation scope remains server-derived.
Cross-tenant/workspace/resource substitutions fail closed, and public missing
or unauthorized behavior remains non-enumerating. No backend defect was found.

### 2. Memberships and invitations

Invitation and membership identities remain separate. Exact-recipient
binding, HMAC-only persisted credentials, rotation, expiry, replay,
concurrency, owner backfill, membership limits, atomic acceptance, and
evidence rollback passed. No secret is returned by list operations.

### 3. Roles, permissions, and approval authority

The closed six-role and 36-permission registries, role ceilings, centralized
deny-by-default evaluator, owner protections, role transitions, and exact
reviewer eligibility remain intact. Collaboration authority does not create a
Milestone 4 capability or approval.

### 4. Sharing, visibility, and ownership

Typed resource/audience/access/visibility registries, direct and inherited
visibility, share limits, revocation, ownership, transfer acceptance, exact
recipient checks, single-owner preservation, and immutable-version
parent-sharing rules passed.

### 5. Authority snapshots and revocation fencing

Monotonic workspace, membership, share, and approval authority generations
remain enforced. Claim, service-call, retry, effect, compensation, export, and
publication boundaries revalidate current invoker authority. Stale snapshots
cannot restore access.

### 6. Comments and collaboration activity

Plain-text validation, unsafe markup/control rejection, 5,000-code-point
limit, four-level replies, 500-comment threads, rate limiting, immutable
revisions, tombstones, moderation, resolution, current visibility, bounded
activity, and replay deduplication passed. Comment content is not source
evidence or activity payload.

### 7. Shared workflows and agents

Visibility and invocation remain separate. Immutable versions inherit the
parent identity and cannot be shared independently. Definition owner,
authenticated invoker, exact active membership, version, authority snapshot,
Trace, audit, event, outbox, activity, and execution linkage remain distinct.

### 8. Frontend authority and cache safety

One user-partition defect was corrected as M6.7-01. After correction, every
collaboration query family includes authenticated user, workspace, authority
generation, and the applicable resource/canvas/automation identity.
Workspace changes and revocation cancel and remove prior-scope state.
Malformed closed-registry responses fail Zod validation.

### 9. API, serialization, and error safety

Schemas use closed registries, bounded strings/lists/pages, CSRF-protected
mutation dependencies, optimistic/idempotent command fields, and safe public
error translation. No raw database error, stack, prompt, grant, approval,
authority snapshot, invitation hash/token, or internal denial reason is
exposed.

### 10. Events, outbox, Trace, audit, and activity

Milestone 6 mutations retain atomic state/evidence behavior and exact actor
attribution. Failed transactions roll back state, domain events, outbox,
activity projection inputs, Trace, collaboration audit, and request identity.
Replay remains deduplicated.

### 11. Concurrency and replay

The existing deterministic invitation, role, approval, sharing, transfer,
comment, workflow/agent invocation, controlled execution, revocation, retry,
effect, compensation, and publication cases passed. One-winner, idempotent
replay, no duplicate evidence, and no partial state remain enforced.

### 12. Migration and database integrity

Migrations `0021`–`0025` retain one direct parent each and one sole head.
SQLite upgrade to `0025`, downgrade to `0024`, and re-upgrade to `0025`
passed. The focused migration suites compiled PostgreSQL offline DDL and
validated composite scope, closed checks, append-only guards, successor
states, backfills, indexes, and deterministic legacy invocation handling.

### 13. Accessibility and interface safety

Semantic landmarks, tabs, tables/lists, native keyboard workspace switching,
live mutation status, visible focus, responsive wrapping, and narrow layouts
passed unit and Chromium checks. No redesign was required.

### 14. Documentation and roadmap consistency

README, architecture, implementation plan, progress, this audit handoff, and
the separate completion report now agree that Milestone 6 is complete locally
and Milestone 7 Production Hardening architecture is next. Advanced
Collaboration remains optional Milestone 8.5 work. Later product-family work
remains unstarted.

## Validation record

### Backend and security

- complete backend: 518 passed, 1 skipped, 0 failed, 61 warnings in 734.73
  seconds;
- expected skip: PostgreSQL runtime validation because
  `OPENCANVAS_POSTGRES_TEST_URL` was not configured;
- security marker: 38 passed, 481 deselected, 0 failed;
- established integration: 22 passed, 0 failed, 1 dependency warning;
- focused Milestone 6: 31 passed, 0 failed, 35 dependency warnings;
- production Ruff formatting: 86 files formatted;
- production and literal repository-wide Ruff: 0 findings;
- strict mypy: 83 source files, 0 issues;
- compilation and production import: passed;
- ORM mapper configuration: 121 tables.

Warnings are dependency deprecations from the Python 3.12 SQLite adapters,
one FastAPI/Starlette status alias, and SQLAlchemy's SQLite adapter. No
repository warning or newly introduced failure remains.

### Frontend and browser

- focused cache/console: 8 passed;
- complete Vitest: 17 files, 74 passed, 0 failed;
- ESLint: passed with no warning;
- TypeScript: passed;
- Prettier: passed;
- Next.js production build: passed;
- Chromium: 8 passed, 2 expected real-service skips, 0 failed.

The two browser skips require configured real FastAPI/PostgreSQL services and
do not affect deterministic collaboration, accessibility, responsive, canvas,
retrieval/citation, Agent Studio, or Dynamic Universe coverage.

### Migration, demo, hygiene, and Git

- Alembic sole head: `20260725_0025`;
- migration validator: upgrade `0025`, downgrade `0024`, re-upgrade `0025`;
- PostgreSQL offline DDL: passed in focused migration tests;
- PostgreSQL runtime: not run because no approved test URL was configured;
- deterministic demo reset: passed;
- demo isolation and persisted provenance: passed;
- API/runtime/web startup smoke: passed;
- repository hygiene: 357 source files passed;
- secret patterns: passed through repository hygiene;
- tracked local user-home paths: none;
- dependency and lockfile diff: none;
- prohibited production scope: none;
- whitespace and `git diff --check`: passed after final formatting;
- Git object and protected-reference verification: passed in the final local
  gate.

## Migration decision and immutable hashes

No migration was required or created. No migration after `0025` exists.
Migrations `0021`–`0025` were not modified.

| Revision | Git blob hash                              |
| -------- | ------------------------------------------ |
| `0021`   | `3baeb7d4deeb5dbf13b230de49ea6a787ce3a0c4` |
| `0022`   | `d4a3bfc1bd32b3df9a886645fba318a51d2ed3a0` |
| `0023`   | `01c9b28d7b2875a7cfe7041fc846f79d7c672aa5` |
| `0024`   | `fb4e8e264a5a73f2ab543d9cb0fc920ace4fbefb` |
| `0025`   | `b5c71452728cf5c473a017679ebb6f2903a5f9f6` |

## Local-only and future-work boundary

The branch has no upstream. No fetch, pull, push, remote inspection, remote
branch/tag change, deployment, publication, release, merge, rebase, or
protected-reference rewrite occurred.

Milestone 7 Production Hardening, deterministic production Indexer work,
Advanced Real-Time Collaboration, Mobius Society, the governed Librarian, and
all later product-family work remain unstarted.

Milestone 6 is complete locally. This is not a production-readiness claim;
Milestone 7 owns production architecture and hardening.

MILESTONE 6.7 COMPLETE LOCALLY — MILESTONE 6 COMPLETE — READY FOR MILESTONE 7 PRODUCTION HARDENING ARCHITECTURE
