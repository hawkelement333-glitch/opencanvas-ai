# Milestone 5 Progress — Living Knowledge Graph and AI Workflows

Last updated: 2026-07-25

Branch: `milestone-5-living-knowledge-workflows-architecture-local`

Baseline: `dadf114cfb33c557d6d1be7d8f98a4bb3ba36818`

Milestone 5 architecture and checkpoint 5.1 are complete locally. The next
checkpoint is 5.2, Living State and Event System.

`MILESTONE 5 ARCHITECTURE COMPLETE LOCALLY — READY FOR KNOWLEDGE GRAPH FOUNDATION`

| Checkpoint                        | Status           | Dependency               |
| --------------------------------- | ---------------- | ------------------------ |
| Architecture                      | Complete locally | Completed Milestone 4    |
| 5.1 Knowledge Graph Foundation    | Complete locally | Architecture             |
| 5.2 Living State and Event System | Not started      | 5.1                      |
| 5.3 Graph-Aware Retrieval         | Not started      | 5.1–5.2                  |
| 5.4 Controlled AI Workflows       | Not started      | 5.1–5.3 and M4           |
| 5.5 Dynamic Universe Interface    | Not started      | 5.1; 5.2/5.4 to complete |
| 5.6 Bounded Agent Studio          | Not started      | 5.4                      |
| 5.7 Final Combined Audit          | Not started      | 5.1–5.6                  |

Only checkpoint 5.1 is complete. Milestone 5 is not complete.

## Permanent traceability contract

Approved data
→ grounded questions
→ traceable workflows
→ adaptive agent proposals
→ governed agents
→ traceable results

> Every answer, workflow, agent definition, approval, action, retry, failure,
> and result must remain connected to the authority and evidence that produced
> it. Trace means auditable provenance and execution evidence, not private model
> chain of thought.

This contract amendment does not reopen 5.1 or start 5.2. The completed 5.1
implementation already provides stable canonical scoped identities,
reconstructable relationship direction/endpoints/provenance/history,
authenticated user attribution, same-scope controlled-execution provenance,
source/rule origin records, evidence-preserving lifecycle transitions, and
safe operational graph API provenance. Later records can reference those
identities without rewriting history.

Later checkpoint acceptance now requires:

- 5.3 traces selected context, traversed relationships, passages, citations,
  inclusion/exclusion decisions, conflicts, insufficient evidence, and
  traversal/context-budget limits.
- 5.4 traces the versioned workflow, approved inputs, steps, models/tools/APIs,
  evidence, approvals, retry/recovery/cancellation, mutations,
  compensation/rollback, and final result.
- 5.6 traces the source framework, served workflow/job, proposed roles,
  approved sources/tools, bounds, creator/approver, provider/model, validation,
  activation, and the full definition/execution lifecycle.
- 5.7 proves approved data through canonical graph provenance, grounded
  citations, a versioned workflow, an adaptive proposal, human activation,
  governed execution, and a traceable result.

The Adaptive Agent Architect may propose specialized definitions from approved
frameworks, data structures, and workflows. It cannot activate agents, grant
authority, assign private data, install unreviewed tools, or increase limits;
policy validation and human approval are mandatory for activation.

## 5.1 completion evidence

- Canonical entity kinds: document, note, execution.
- Relationship types: references, derived_from, related_to, cites, supports,
  contradicts, produced_by, affected_by.
- Append-only provenance and relationship history.
- User/workspace/canvas composite scope and server-derived authority fields.
- Workspace graph revision and canonical/request/provenance digests.
- Migration and sole head: `20260725_0016`.
- Complete non-PostgreSQL backend suite: 423 passed.
- PostgreSQL-marked suite: 1 skipped; no runtime was configured.
- Handoff:
  [`MILESTONE_5_1_KNOWLEDGE_GRAPH_HANDOFF.md`](MILESTONE_5_1_KNOWLEDGE_GRAPH_HANDOFF.md).

## Closed decisions

- Extend canonical graph truth; keep canvas edges as presentation.
- Add temporal bindings, relationship assertions, transactional events/outbox,
  and a workspace graph revision.
- Freeze exact server-derived graph paths/evidence before provider invocation.
- Bind each workflow step to a separate Milestone 4 execution.
- Use freshly approved reverse-order saga compensation.
- Use viewport queries, portable tiling, normalized cache, pinned selection,
  and accessible workflow state.
- Keep Agent Studio declarative, human-activated, and unable to grant authority.

## Planned migration outline

| Placeholder     | Scope                                                  |
| --------------- | ------------------------------------------------------ |
| `20260725_0016` | Complete: graph state, bindings, relationship evidence |
| `2026xxxx_0017` | Events/outbox, sequences, projector checkpoints        |
| `2026xxxx_0018` | Context paths and traversal indexes                    |
| `2026xxxx_0019` | Workflow versions/runs/transitions/compensation        |
| `2026xxxx_0020` | Viewport tiles and summaries                           |
| `2026xxxx_0021` | Agent versions/proposals/activation                    |

The 5.1 identifier is now an implemented Alembic revision. Later identifiers
remain placeholders. Migrations remain additive, reversibly tested, resumably
backfillable, and retain legacy tables.

## Preserved Milestone 4 contracts

Deny-by-default authority; append-only evidence; user-started exact selected
context and citations; approved reversible effects and exact rollback;
request/effect idempotency; leases, recovery, retry, cancellation, deadlines,
stale suppression; and no partial mutation or success evidence on failure.

## Risks and deferred scope

Active risks are visual/canonical divergence, pre-commit event leakage, graph
explosion, provenance volume, stale graph writes, partial compensation,
PostgreSQL behavior differences, viewport selection loss, and trusted-looking
AI configuration. The architecture assigns explicit gates to each.

Deferred:

- 6. Multi-Workspace Collaboration
  - Nested and Federated Mobius Workspaces
- 7. Production Hardening
- 8. Public Portfolio and Product Release
- 9. SolarPlexus Agent Ecosystem

Next authorized start:
`MILESTONE 5.2 STARTED LOCALLY — LIVING STATE AND EVENT SYSTEM`
