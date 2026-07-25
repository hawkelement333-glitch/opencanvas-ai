# Milestone 5 Implementation Plan

Status: architecture complete; all implementation checkpoints pending.

This plan implements
[`MILESTONE_5_ARCHITECTURE.md`](MILESTONE_5_ARCHITECTURE.md) sequentially.
Every checkpoint starts from the preceding clean local commit, extends existing
patterns, preserves all Milestone 4 contracts, and uses additive,
resumably-backfillable migrations. SQLite remains the correctness baseline;
PostgreSQL-specific concurrency and plans require marked tests. No event,
projection, client, workflow, import, or AI output may grant authority.

Dependencies: 5.2 requires 5.1; 5.3 requires 5.1–5.2; 5.4 requires 5.1–5.3
and Milestone 4; 5.5 may begin after 5.1 but requires 5.2/5.4 to complete; 5.6
requires 5.4; 5.7 requires 5.1–5.6.

## 5.1 — Knowledge Graph Foundation

Start: `MILESTONE 5.1 STARTED LOCALLY — KNOWLEDGE GRAPH FOUNDATION`

Complete: `MILESTONE 5.1 COMPLETE LOCALLY — READY FOR LIVING STATE AND EVENT SYSTEM`

Model/reasoning: `gpt-5.6-sol`, xhigh.

Deliver canonical type extensions, graph revision, temporal canvas bindings,
relationship assertions, graph services/APIs, and reviewed graph resource/
capability contracts. Preserve visual edges.

Migration `2026xxxx_0016`: additive graph types/subtypes, graph state,
bindings, and relationship evidence. Backfill only deterministic facts, record
origin, infer no visual-edge semantics, and retain legacy tables.

Gate: mapper/constraint/index tests; concurrent/stale revisions; duplicates;
cross-workspace failures; tombstone provenance; empty/legacy and
upgrade/downgrade/re-upgrade/resumed-backfill cycles; PostgreSQL lock and
uniqueness tests.

## 5.2 — Living State and Event System

Start: `MILESTONE 5.2 STARTED LOCALLY — LIVING STATE AND EVENT SYSTEM`

Complete: `MILESTONE 5.2 COMPLETE LOCALLY — READY FOR GRAPH-AWARE RETRIEVAL`

Model/reasoning: `gpt-5.6-sol`, xhigh.

Deliver transactional events/outbox, workspace sequences, post-commit
dispatch, checkpoints/replay, projections, poison-event handling, retries,
stale-claim fencing, and observability. Preserve event/audit/Trace separation.

Migration `2026xxxx_0017`: events, outbox evidence, sequences, checkpoints, and
initial projections. Seed only reconstructable facts.

Gate: mutation/event/Trace atomicity; rollback has no event; duplicate delivery
applies once; deterministic replay; safe gap handling; stale projector fencing;
events cannot grant/start execution; PostgreSQL outbox/sequence concurrency.

## 5.3 — Graph-Aware Retrieval

Start: `MILESTONE 5.3 STARTED LOCALLY — GRAPH-AWARE RETRIEVAL`

Complete: `MILESTONE 5.3 COMPLETE LOCALLY — READY FOR CONTROLLED AI WORKFLOWS`

Model/reasoning: `gpt-5.6-sol`, xhigh.

Deliver connected-context opt-in, closed traversal, immutable resolved
path/context, deterministic graph/vector ranking, exact citations, conflict
handling, and insufficient-evidence results by extending grounded drafts.

Migration `2026xxxx_0018`: graph-context/path evidence and traversal indexes.

Gate: exact roots and all budgets/allowlists; scope/lifecycle/version/evidence
checks; revoked/altered/missing/stale/cross-scope failures; deterministic
ranking/path/citations; conflicts; cancellation/deadline/lease/stale result;
seeded query and latency bounds.

## 5.4 — Controlled AI Workflows

Start: `MILESTONE 5.4 STARTED LOCALLY — CONTROLLED AI WORKFLOWS`

Complete: `MILESTONE 5.4 COMPLETE LOCALLY — READY FOR DYNAMIC UNIVERSE INTERFACE`

Model/reasoning: `gpt-5.6-sol`, max.

Deliver immutable definitions/digests, closed DAG steps/branches, user-started
runs, append-only transitions, one Milestone 4 execution per executable step,
authority intersection/revalidation, layered idempotency, bounded failure, and
immutable saga compensation.

Migration `2026xxxx_0019`: definitions, versions, steps, branches, runs,
transitions, M4 bindings, and compensation plans/items.

Gate: digest/cycle/limit validation; exact version binding; typed branches;
duplicate start/resume/step/result/compensation; retry succeeds once; stale,
canceled, or expired workers cannot commit; invalid authority fails closed;
compensation order/approval/conflict/partial state; no partial success evidence
after transaction failure.

## 5.5 — Dynamic Universe Interface

Start: `MILESTONE 5.5 STARTED LOCALLY — DYNAMIC UNIVERSE INTERFACE`

Complete: `MILESTONE 5.5 COMPLETE LOCALLY — READY FOR BOUNDED AGENT STUDIO`

Model/reasoning: `gpt-5.6-terra`, high, plus `gpt-5.6-sol` xhigh security/data
contract review.

Deliver viewport/boundary/selection/activity/workflow/MiniMap APIs, portable
tiling, normalized cache, visible rendering, prefetch/eviction with pinned
selection, editing/conflict preservation, and accessible navigation/status.

Migration `2026xxxx_0020`: layout tiles, summaries, portable indexes. Optional
PostgreSQL spatial indexes require measured proof.

Gate: stable revision cursors; no duplicates/omissions; boundary/off-screen
selection; cache bounds; no full-snapshot regression; projection lag; keyboard,
screen reader, focus, contrast, motion; browser smoke/build; large-workspace
budgets.

## 5.6 — Bounded Agent Studio

Start: `MILESTONE 5.6 STARTED LOCALLY — BOUNDED AGENT STUDIO`

Complete: `MILESTONE 5.6 COMPLETE LOCALLY — READY FOR FINAL COMBINED AUDIT`

Model/reasoning: `gpt-5.6-sol`, xhigh.

Deliver template/agent identities, immutable versions/digests, proposal
evidence, activation, declarative bounds, and effective-authority review.
Runtime authority remains Milestone 4. Prohibit delegation, descendants,
arbitrary code/tools/connectors, agent creation, and policy changes.

Migration `2026xxxx_0021`: templates, agents, versions, proposals, activation.

Gate: schemas/digests/immutability; malicious data confinement; no
self-activation/standing grant; strict runtime authority intersection;
revocation/replacement/stale/prohibited capability; accessible browser smoke.

## 5.7 — Final Combined Milestone 5 Audit

Start: `MILESTONE 5.7 STARTED LOCALLY — FINAL COMBINED MILESTONE 5 AUDIT`

Complete: `MILESTONE 5.7 COMPLETE LOCALLY — READY FOR MILESTONE 6 ARCHITECTURE`

Model/reasoning: `gpt-5.6-sol`, max.

Audit 5.1–5.6 together and fix only proved defects. Run affected backend and
frontend suites; controlled exact-citation/effect/rollback scenarios; retry,
recovery, stale, cancel, deadline, and invalid-authority cases; failure
injection; event replay; migration cycles; concurrency; PostgreSQL-marked
tests; browser/accessibility; typing, lint, formatting, build, mappers,
compilation, imports, hygiene, secrets, whitespace, diff, and prohibited scope.

Create the completion document only after the combined gates pass. Milestone 6
still requires explicit authorization.

## Deferred

- 6. Multi-Workspace Collaboration
  - Nested and Federated Mobius Workspaces
- 7. Production Hardening
- 8. Public Portfolio and Product Release
- 9. SolarPlexus Agent Ecosystem
