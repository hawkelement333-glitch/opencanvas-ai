# Milestone 5.2 Living State and Event System Handoff

Status: complete locally on 2026-07-25

Branch: `milestone-5-living-knowledge-workflows-architecture-local`

Starting SHA: `b8113b3020a27a086aaef4318920869f0917447c`

Migration and sole Alembic head: `20260725_0017`

## Delivered boundary

Milestone 5.2 extends the completed canonical graph, Trace, audit, controlled
execution, effect, rollback, transaction, and scope patterns. It does not
create a parallel authority system. Meaningful supported mutations can now
commit immutable event provenance and a transactional outbox record with their
authoritative state.

The permanent product loop and Trace rule remain authoritative. Trace is
auditable provenance and execution evidence, never private model reasoning.

## Closed registry

Registry: `mobius-domain-events-v1`; envelope schema: `domain-event-v1`.

Emittable existing-feature contracts:

- `graph.relationship.created`
- `graph.relationship.superseded`
- `graph.relationship.deactivated`
- `canonical.resource.created`
- `canonical.resource.updated`
- `canonical.resource.historical`
- `controlled.execution.started`
- `controlled.execution.completed`
- `controlled.execution.failed`
- `controlled.execution.canceled`
- `controlled.effect.committed`
- `controlled.rollback.committed`

Reserved and deliberately non-emittable until their future producers exist:

- `evidence.bundle.requested`
- `evidence.bundle.generation_started`
- `evidence.bundle.completed`
- `evidence.bundle.failed`
- `evidence.bundle.accessed`
- `evidence.bundle.export_denied`
- `citation.rendering.completed`
- `citation.rendering.failed`

Unknown/free-text types and premature reserved events fail closed. No adaptive
agent, training, Academy, English, quarantine, rehabilitation, or tribunal
events were invented.

## Envelope, provenance, and transaction

The server derives event/outbox/provenance identities, registry and schema
versions, exact user/workspace/canvas scope, workspace sequence, timestamps,
payload/request/provenance digests, delivery policy, and activity status.
Evidence can link the authenticated actor, controlled execution, graph
relationship/history/revision, effect or rollback, audit event, Trace, subject,
related resource, and source idempotency identity.

Payload keys are type-specific and bounded. Credentials, raw grants, worker
secrets, hidden policy details, uncontrolled request content, and private chain
of thought are excluded.

Graph relationship state, append-only provenance/history, graph revision,
successful Trace, domain event, provenance, and outbox share one nested
transaction. Approved effects and rollbacks similarly add their events in the
existing atomic boundary. Injected event/provenance/outbox failures roll back
the authoritative mutation and success evidence. The established started and
failed Trace pair remains as failure evidence.

Exact replay returns the original event and outbox. Reuse of the same scoped
idempotency identity with different authoritative content fails closed.

## Outbox and activity

Outbox states are closed to `pending`, `delivering`, `retry_wait`, `delivered`,
and `terminal_failure`. Claims use server-owned eligibility, attempts,
maximum attempts, lease owner, expiry, and monotonically increasing generation.
Only the current unexpired generation can complete or fail. Expired work may
be recovered; stale completion fails. Retry timing and safe failure
classification are server-derived. Delivered and terminal records cannot
reopen.

Event, provenance, delivery-attempt, and activity rows are append-only.
Outbox identity, event/scope binding, maximum-attempt contract, creation time,
and deletion are protected while approved lifecycle fields remain mutable.

The sole consumer creates one deterministic `activity-v1` entry per event.
Repeated processing is idempotent; conflicting or unsupported projection
content fails closed. It cannot start agents/workflows, call models, grant
capabilities, generate evidence bundles, render citations, modify agent
versions, or mutate unrelated truth.

Bounded authenticated APIs expose recent workspace/canvas activity, graph
entity/relationship activity, controlled-execution activity, safe event
detail, and safe delivery status. Entity activity includes graph relationships
where the entity is either endpoint. Responses omit authority, policy, worker,
lease-owner, request-digest, and database internals. No browser dispatch or
claim endpoint exists.

## Migration and portability

Revision `20260725_0017` adds workspace sequences, events, provenance, outbox,
delivery attempts, activity entries, constraints, indexes, and database
protection triggers. Upgrade, downgrade to `20260725_0016`, and re-upgrade are
supported. Existing data is preserved and no historical event is inferred.

SQLite is the local correctness baseline. Its coarse writer locking means one
of two simultaneous writers may fail closed with a safe storage error while
the authoritative event commits exactly once. Claim contention returns at
most one owner. These results do not establish PostgreSQL locking behavior.
The new PostgreSQL DDL compiles offline; runtime concurrency remains pending a
configured PostgreSQL service.

## Preserved and deferred scope

No graph-aware retrieval, workflow system, evidence ZIP, source export, APA
renderer, English rewriting, agent creation/improvement, training, Academy,
quarantine, rehabilitation, tribunal, Agent Studio, Dynamic Universe,
recurring job, federation, external queue, or autonomous event-triggered agent
was implemented.

All Adaptive Agent Architect, Adaptive Training and Evaluation Agent,
governed-improvement, Adaptive English Communication Expert, Trace Evidence
Bundle, deterministic ZIP, APA 7, SolarPlexus Academy, School of Language,
Agent Justice, Quarantine Center, Rehabilitation Center, and Review Tribunal
requirements remain unchanged future acceptance criteria.

Milestone 5.3–5.7 and future Milestones 6–9 remain deferred. Milestone 5 is not
complete.

## Validation record

The affected backend validation passed 304 tests. Its post-commit focused
event/API/migration/graph subset passed 29 tests, including deterministic
idempotency, atomicity, append-only behavior, stale fencing, bounded retry,
terminal failure, projection replay, scope-safe reads, SQLite migration
triggers/cycle, and PostgreSQL offline DDL. Ruff passed; strict mypy passed all
66 source files; compilation, imports, mapper configuration, formatting,
whitespace, secret-pattern, prohibited-scope, migration-head/cycle, repository
hygiene, and Git object-integrity checks passed.

The final audit confirmed a clean tree, no upstream, unchanged protected refs,
and no remote operation.

Next authorized checkpoint:
`MILESTONE 5.3 STARTED LOCALLY — GRAPH-AWARE RETRIEVAL`
