# Milestone 3 architecture: Trace and the canonical knowledge foundation

## Status and compatibility boundary

Milestone 3 adds two backend architectural primitives without replacing the working spatial
canvas, document-ingestion, retrieval, or grounded-answer paths:

1. The **Trace Foundation** is a durable, subsystem-neutral record of operation attempts and
   outcomes. It was implemented and validated before canonical domain mutations were introduced.
2. The **canonical knowledge foundation** is an additive workspace-scoped object registry with
   typed detail records, controlled relationships, lifecycle/version rules, domain events, and a
   consistent service/repository boundary.

Existing `Canvas`, `Node`, `Document`, chunk, edge, AI execution, and citation tables remain the
Phase 1/2 compatibility layer. Existing canvases are backfilled to one canonical `Workspace` each,
using the canvas ID as the stable workspace ID and retaining an explicit legacy-canvas reference.
This preserves saved canvas data and public Phase 1/2 APIs while allowing later milestones to
adopt canonical identities incrementally.

Milestone 3 is backend-first. It intentionally adds no Trace UI, canvas redesign, production
ingestion replacement, semantic search, graph reasoning, or AI orchestration.

## Trace architecture

`TraceEvent` is an immutable append-only record with:

- stable event and trace IDs, plus an optional parent trace ID;
- a timezone-aware event timestamp and deterministic `(timestamp, event ID)` ordering;
- actor identity and actor type (`user`, `system`, or `service`);
- optional workspace and logical object associations;
- an event type, operation, and status (`started`, `succeeded`, or `failed`);
- detached JSON-safe metadata; and
- structured error code, message, and details for failed events.

The reusable `TraceService` starts, records, completes, and fails traces and provides filtered,
bounded reads by trace, parent trace, workspace, object, event type, actor type, and status. It
participates in the caller's transaction and flushes without committing. A successful canonical
mutation and its success evidence are therefore committed atomically. When a domain operation
fails, the canonical service rolls back the failed unit of work before persisting a structured
failure event in a clean transaction.

Trace associations are intentionally logical rather than foreign keys to mutable domain rows.
Deleting or migrating a domain object must not destroy its audit history. Query routes are
read-only:

- `GET /api/v1/traces/{trace_id}`
- `GET /api/v1/trace-events`

### Trace versus application logging

Application logs are operational diagnostics: they may be sampled, shipped, rotated, and include
runtime detail that is inappropriate for product history. Trace is durable product provenance with
validated structure, stable IDs, workspace/object association, and query semantics. A log entry is
not evidence that a Trace event was committed.

### Trace versus domain events

Domain events communicate an in-process fact to replaceable subscribers after domain behavior
occurs. They are useful for decoupled reactions but are not the durable audit record. Trace events
are persisted execution/provenance evidence. The canonical service emits both, and a dedicated
`TraceEventRecorded` marker may notify subscribers after Trace persistence. The in-memory event bus
isolates handler failures and suppresses recursive Trace marker publication.

## Universal canonical object model

All first-class knowledge objects share one `canonical_objects` registry row:

| Field                      | Meaning                                                                  |
| -------------------------- | ------------------------------------------------------------------------ |
| `id`                       | Stable immutable UUID.                                                   |
| `workspace_id`             | Explicit ownership and isolation boundary.                               |
| `object_type`              | Controlled type discriminator.                                           |
| `version`                  | Deterministic revision, starting at 1 and incremented once per mutation. |
| `lifecycle_state`          | `created`, `active`, `archived`, or `deleted`.                           |
| `metadata`                 | Detached JSON-safe structured metadata.                                  |
| `created_at`, `updated_at` | Database timestamps for creation and last mutation.                      |

Typed detail tables use the registry ID as their primary key:

- **Document** — display name, source type, processing status, source metadata, and an optional
  legacy Phase 2 document reference.
- **Chunk** — parent canonical document, ordered position, bounded content, and source-location
  metadata.
- **Note** — title and user-authored content.
- **Execution** — operation type/status, start and completion times, associated trace ID, structured
  inputs/outputs, and structured failure information.
- **Relationship** — directional source/target IDs, controlled relationship type, creator, and
  associated trace ID.

`Workspace` is the ownership root rather than a child of its own object registry. It has a stable
ID, name, optional description/owner, version, lifecycle, metadata, timestamps, and optional legacy
canvas association.

External and persistence-bound payloads are strictly validated. IDs are never mutable through an
update. Workspace IDs and object types cannot be changed after creation. Metadata is copied through
JSON serialization so callers cannot retain mutable Python references or persist custom objects,
NaN, or infinity.

## Workspace isolation

Every object lookup and mutation requires a workspace ID. A mismatched workspace is exposed as
not-found so object existence is not leaked across isolation boundaries. Relationships use
workspace-aware referential validation and database constraints: source, target, and relationship
must all belong to the same workspace. Cross-workspace relationships are rejected by default.

Authentication is not present in the existing application and remains out of scope. `owner_id` and
actor fields are architectural hooks, not an authorization system.

## Lifecycle and versioning

The shared lifecycle graph is deliberately small:

```text
created  -> active
created  -> deleted
active   -> archived
active   -> deleted
archived -> active
archived -> deleted
deleted  -> (terminal)
```

Transitions outside this graph are rejected with a structured conflict. Every successful update or
lifecycle transition increments `version` exactly once, refreshes `updated_at`, records previous
state/version information in Trace metadata, and emits a domain event. Deletion is a lifecycle
transition, not physical removal. Archived objects remain readable but reject ordinary updates;
deleted objects are terminal and excluded by default from active lists.

## Relationship semantics

Relationships are first-class canonical objects, not arrays embedded in another record. Direction
is explicit:

| Type           | Semantics                                                 |
| -------------- | --------------------------------------------------------- |
| `contains`     | Source is a containing aggregate for target.              |
| `part_of`      | Source is a component of target.                          |
| `references`   | Source explicitly refers to target.                       |
| `derived_from` | Source was produced from target.                          |
| `related_to`   | Source has a directional general association with target. |

The controlled vocabulary is centralized. Relationship creation validates both endpoints, rejects
self-relations and cross-workspace links, and handles duplicates deterministically. Queries may
filter by workspace, source, target, and type. Removal is a traced soft lifecycle deletion so audit
history remains intact. Deleting an endpoint is rejected while it has live incoming or outgoing
relationships, requiring each relationship to be removed through its traced mutation first. A
canonical document likewise cannot be lifecycle-deleted while live canonical chunks still depend
on it.

## Repository and service conventions

The canonical repository owns storage mechanics:

- workspace-scoped create, read, update, list, and lifecycle transition operations;
- stable-ID and object-type enforcement;
- deterministic version increments;
- typed detail persistence and hydration;
- same-workspace relationship filtering; and
- translation of database failures into structured canonical storage errors.

The canonical service owns business orchestration:

- strict create/update payload validation;
- lifecycle and relationship rules;
- Trace start/success/failure recording around every significant mutation;
- transaction commit/rollback behavior; and
- post-persistence domain-event publication.

API handlers are intentionally thin adapters over this service. They translate domain errors into
the existing API error envelope and never accept an unrestricted cross-workspace operation.

## Domain events and extension points

The process-local event bus supports typed subscription/unsubscription, base-type subscriptions,
ordered publication, isolated handler failures, and recursion protection. Initial events cover
workspace/object creation and update, lifecycle/deletion, relationship creation/removal, execution
start/completion/failure, and Trace persistence.

The bus implements a small publisher protocol, so a transactional outbox or broker can replace it
later without changing domain models. Likewise, the canonical repository can be adapted behind the
service boundary, and controlled object/relationship registries can grow without scattered string
literals.

## Compatibility strategy

- The migration backfills a canonical workspace for each existing canvas and keeps a nullable
  unique `legacy_canvas_id` mapping.
- Canonical documents may reference existing Phase 2 documents without changing their ingestion,
  embedding, retrieval, citation, or deletion behavior.
- Existing spatial notes remain canvas nodes. New canonical notes are available through the
  canonical API; a later migration can attach existing note nodes once product ownership and
  synchronization rules are defined.
- Existing canvas edges remain presentation relationships. Canonical relationships model durable
  knowledge semantics and do not silently reinterpret old visual edges.
- Phase 1/2 endpoints and browser behavior are preserved; canonical endpoints are additive.

This explicit adapter boundary avoids maintaining two competing sources of truth while also
avoiding a risky destructive rewrite of working user data.

## Known limitations and deferred work

- No authentication or authorization policy is enforced yet.
- Existing canvas notes and visual edges are not bulk-converted into canonical notes and semantic
  relationships.
- The in-memory event bus is process-local and non-durable; critical reactions will require an
  outbox before multi-replica operation.
- Domain events are published after persistence flush but before the API transaction's outer
  commit. Handlers must remain side-effect-safe until a transactional outbox replaces this timing
  boundary.
- Canonical optimistic concurrency currently relies on deterministic server-side versions; a later
  API revision should expose conditional writes for multiple concurrent editors.
- Trace retention, redaction policy, replay, comparison, evaluation, and final UI are deferred.
- Canonical ingestion adapters, embeddings, vector/hybrid search, graph traversal/reasoning, and AI
  workflows are intentionally deferred.
- Hard purge and compliance-retention policy are not part of lifecycle deletion.

The recommended next step is to adopt canonical IDs at the Phase 2 ingestion boundary, then build
workspace-wide hybrid retrieval and semantic-memory discovery on canonical documents, chunks,
notes, relationships, and Trace provenance.
