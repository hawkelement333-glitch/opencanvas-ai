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
