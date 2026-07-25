# Milestone 5 Architecture — Living Knowledge Graph and AI Workflows

Status: architecture complete locally; implementation not started

Baseline: `dadf114cfb33c557d6d1be7d8f98a4bb3ba36818`

Branch: `milestone-5-living-knowledge-workflows-architecture-local`

Start:
`MILESTONE 5 ARCHITECTURE STARTED LOCALLY — DESIGNING LIVING KNOWLEDGE AND WORKFLOWS`

Complete:
`MILESTONE 5 ARCHITECTURE COMPLETE LOCALLY — READY FOR KNOWLEDGE GRAPH FOUNDATION`

## Scope and repository constraints

Milestone 5 adds a living knowledge graph, graph-aware retrieval, controlled
multi-step workflows, a scalable Universe interface, and a bounded Agent
Studio. It preserves every completed Milestone 4 authority, persistence,
execution, rollback, lease, retry, cancellation, deadline, and stale-result
contract. This pass contains architecture and planning only.

Repository inspection established:

- `CanvasNode` and `Edge` are canvas-local presentation models.
- `CanonicalObject` and `CanonicalRelationship` are the versioned,
  workspace-scoped semantic foundation. Relationships already enforce closed
  types, same-workspace endpoints, uniqueness, and no self-edge.
- Existing migrations correctly avoid inferring semantics from legacy visual
  edges.
- Trace records describe operation lifecycle/provenance; Milestone 4 audit
  records describe authority/accountability; process-local domain events
  describe facts but currently publish before the outer commit.
- Controlled grounded drafts are user-started, bind exact immutable selected
  context, enforce scope/version checks and budgets, and retain exact source
  and citation snapshots.
- The Milestone 4 action registry is closed. Approved mutation, effect,
  idempotency, and rollback paths already exist and must be reused.
- The React Flow client currently loads a full canvas and lacks viewport
  paging, spatial indexing, incremental hydration, and bounded eviction.
- Canonical services flush while the API owns the outer transaction.
  Ownership, path scope, CSRF, and optimistic versions are established.
  Milestone 5 remains owner-only and single-workspace.

## Permanent product loop and Trace contract

Milestone 5 and every later milestone preserve this product loop:

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

`Trace` therefore records safe operational provenance, lifecycle, and
execution evidence. It does not store or expose private model chain of thought.
Authority remains in the established policy, grant, approval, audit, and
execution contracts; a Trace reference describes those decisions without
becoming authority.

The completed 5.1 foundation is stable for this contract:

- graph entities resolve to canonical resources in an exact user, workspace,
  and canvas scope;
- relationship type, direction, endpoints, scope, provenance, and append-only
  lifecycle history are reconstructable;
- user-created relationships record the authenticated actor;
- execution-created provenance requires the responsible same-scope controlled
  execution;
- imported, citation-derived, and deterministic relationships record their
  actual source reference or named rule and version;
- supersession and deactivation append history while preserving original
  identity and evidence;
- graph APIs expose bounded operational provenance without private reasoning,
  grants, policies, or hidden authority details; and
- later answers, workflows, and agents can reference stable graph and
  provenance identities without rewriting historical records.

## Decisions

### Canonical graph and identity

Extend `CanonicalObject` and `CanonicalRelationship`; do not replace them.
Keep legacy canvas nodes/edges as presentation compatibility. Add temporal
canvas-to-canonical-object bindings so geometry is not semantic identity and
removing a presentation never erases provenance.

Canonical UUID plus workspace remains identity. Add typed subtypes only where
needed for answer, citation, project, repository resource, agent, workflow
definition, and workflow run. Authoritative fields do not live only in
free-form metadata.

Immutable facts include identity/type/workspace, document versions/chunks,
answers/citations, execution evidence, relationship endpoints/type/evidence,
definition versions/digests/steps, events, and binding evidence. Editable
current state, lifecycle, presentation, activation pointers, and rebuildable
projections change through optimistic versions. Deletion is a tombstone.

Rejected: a replacement graph database (parallel transaction/authority
boundary), legacy `Edge` as semantic truth (insufficient evidence), metadata-
only graph state (weak integrity), mutable relationship endpoints, and
physical deletion.

### Relationship provenance

Add append-only relationship assertions binding relationship ID, source and
target versions, closed origin kind, applicable actor/Trace/execution/workflow
step/citation/source version, and evidence digest. Confidence is stored only
when supplied or produced by a named versioned algorithm. Tombstones retain
assertions; relationship types remain closed.

Rejected: overwriting creation provenance, arbitrary predicates, and
unsupported model-generated confidence.

### Living events

Persist append-only domain events and an outbox atomically with canonical
mutation and successful Trace state. Allocate monotonic workspace sequences
and deduplicate event identity plus aggregate/version/type. Dispatch only after
commit. The in-memory bus may remain only as a post-commit adapter.

Activity and current state are idempotent, rebuildable projections with
checkpoints. Domain event (business fact), audit (security/accountability), and
Trace (operation lifecycle/diagnostics/provenance) remain distinct.

Events may mark work eligible but never grant authority or start an AI
workflow. Explicit authenticated user start/resume remains mandatory.

Rejected: the process-local pre-commit bus as truth, audit/Trace as an event
stream, and autonomous event-triggered workflows.

### Graph concurrency

Add a monotonic workspace graph revision. Semantic commands require expected
graph revision, affected object versions, workspace-scoped idempotency key, and
payload digest. Lock or compare-and-swap the revision and atomically commit
graph state, event facts, audit evidence, and successful Trace state. A stale
command fails without partial success. Context snapshots bind graph revision,
objects/versions, relationships, and assertion evidence.

Rejected: timestamp ordering, client-controlled revisions, and last-write-wins.

### Graph-aware retrieval

Exact selected resources are roots. Connected context requires explicit user
choice, then server resolution before provider invocation. Freeze exact paths,
assertions, object/document/chunk versions, and graph revision into immutable
context.

Initial hard envelope: same active owned workspace; reviewed types/directions;
depth default 2/max 3; max 50 roots, 250 objects, 500 relationships, 200
candidate chunks; existing top-k default 8/max 50 and 60,000-character limit.
Ordering is deterministic.

Traverse only visible active endpoints with qualifying evidence. Ranking may
combine vector score, bounded distance, relationship type, and a named source
quality rule. Preserve the path to each exact citation; do not invent edges or
average away conflicts. Missing, stale, unsupported, or uncitable evidence
returns insufficient evidence. New graph resource/capability contracts require
an explicit reviewed Milestone 4 contract version/digest change.

Every retrieval result must trace selected context, relationships traversed,
retrieved passages, citations, inclusion and exclusion decisions, conflicts,
insufficient-evidence outcomes, and applied traversal and context-budget
limits.

Rejected: provider-directed recursion, whole-component loading, client-supplied
expansion, and citations without immutable evidence.

### Controlled workflows and rollback

Use stable workflow registry identities with immutable definition versions and
digests. Normalized steps have closed type, schemas, capability/resource
selector, risk, approval, branch, and compensation fields. The initial
contract is an acyclic graph of at most 32 steps, one active step at a time,
with server-evaluated closed branch operators. No loops, arbitrary code,
dynamic insertion, or self-modification.

A run binds exact definition/digest, user, workspace, initial graph/context
revision, idempotency key, and root Trace. Run and step transitions are
append-only. Every executable step has a distinct Milestone 4 controlled
execution. Effective authority is the intersection of workflow, step, exact
resources/versions, current user/workspace, live grant/policy, and matching
approval. Resume only at durable boundaries after full revalidation.

Idempotency applies to definition digest, run request key/digest,
run-step-branch identity, and existing Milestone 4 request/effect identities.

Rollback is a saga: freeze forward work, create an immutable reverse-effect
plan, skip read-only steps, and route each reversible effect through existing
rollback review, fresh approval, version checks, idempotency, and execution.
Stop on conflict/failure and retain truthful partial state.

Every workflow run must trace workflow identity and version, approved inputs,
every step and outcome, models, tools, and APIs used, evidence and outputs,
approvals, retries, recovery, cancellation, proposed and completed mutations,
compensation or rollback, and the final result.

Rejected: script runners, a standing workflow grant, reusing one controlled
execution across steps, transactions spanning providers/approvals, and blind
inverse writes.

### Universe interface

Add a server viewport API accepting bounds, graph revision, and cursor and
returning visible node projections, interior edges, boundary stubs, versions,
selection hydration, and a stable continuation marker. Use portable fixed
coordinate integer tiles and B-tree indexes for correctness; PostgreSQL
spatial indexes are optional after measurement.

Use normalized client caches keyed by ID/version, visible rendering, neighbor
prefetch, bounded LRU eviction, pinned selection/context, and a server-derived
MiniMap summary. Workflow states need text/icon equivalents, keyboard/list
navigation, announcements, reduced motion, and safe errors.

Rejected: continued full snapshots, PostgreSQL-only correctness, client-derived
scope, and color-only state.

### Bounded Agent Studio

Templates and agents have stable identity, immutable versions/digests, typed
purpose/sources/closed tools/limits/approvals/exact workflow version, and
explicit activation transitions. AI output is an untrusted proposal. Server
policy validates and displays effective bounds; a human activates it.
Activation grants no runtime authority—every run uses Milestone 4.

The Adaptive Agent Architect may propose specialized agent definitions from
approved frameworks, data structures, and workflows. It cannot activate
agents, grant authority, assign private data, install unreviewed tools, or
increase limits. Activation requires policy validation and human approval.

Every Agent Studio lifecycle must trace the source framework, workflow or job
being served, proposed specialist roles, approved sources and tools,
capabilities and limits, creator and approver, provider and model, validation
and activation, and all revisions, executions, suspensions, retirements, and
replacements.

Prohibit agent-initiated creation, delegation, descendants, arbitrary
connectors/tools/code, and policy modification. These belong to Milestone 9.

## Logical model, service, and API outline

Planned records:

| Area         | Records/invariants                                              |
| ------------ | --------------------------------------------------------------- |
| Graph        | workspace graph state, typed subtypes, temporal canvas bindings |
| Provenance   | immutable relationship assertions with endpoint versions        |
| Events       | domain events/outbox, sequences, projector checkpoints          |
| Retrieval    | immutable graph-context snapshots and path evidence             |
| Workflows    | versions, steps, runs/transitions, M4 bindings, compensation    |
| Agent Studio | templates, versions, proposals, activation transitions          |
| Universe     | tiles and rebuildable viewport/summary projections              |

All workspace foreign keys enforce workspace integrity. Closed enums/checks
mirror application contracts. Append-only rows use established database-level
update/delete rejection patterns.

Proposed API namespaces:

- `/workspaces/{workspace_id}/knowledge-graph/{entities,relationships,neighborhood,activity}`
- `/workspaces/{workspace_id}/universe/viewport`
- `/workspaces/{workspace_id}/agent-executions/graph-drafts/prepare`
- `/workspaces/{workspace_id}/workflows/{definitions,runs}`
- `/workspaces/{workspace_id}/workflows/runs/{run_id}/{resume,cancel,rollback-plan}`
- `/workspaces/{workspace_id}/agents/{templates,definitions}`

Graph writes are explicit revision/idempotency commands, not generic patches.
Provider calls remain outside database transactions and return through the
existing fenced commit path.

## Security, scale, tests, and risks

- Deny by default; owner-only, single-workspace.
- Selection names roots but grants no access; projections never authorize.
- Every step rechecks current authority. Revoked, expired, altered, missing,
  stale, or cross-scope resources fail closed.
- Failed transactions leave no partial mutation, event, effect, lifecycle
  success, lease, audit success, projection checkpoint, or successful Trace.
- Traversal, viewport, cache, payload, retry, and workflow size are bounded.
- Projection replay and backfill are idempotent, resumable, and observable.

Each checkpoint tests mappers/constraints, migration cycles, scope/authority,
duplicates, concurrency, failure injection, event replay, graph paths/budgets/
citations, workflow binding/branches/resume/retry/cancel/deadline/stale commit/
compensation, viewport selection/pagination/cache/accessibility, and prohibited
capabilities. PostgreSQL-marked tests validate graph locks, uniqueness, outbox
claims, event sequences, traversal plans, migration locks, and optional spatial
indexes before reliance on PostgreSQL behavior.

The final combined audit must prove the complete chain:

approved data
→ canonical graph and provenance
→ grounded question and citations
→ versioned workflow
→ adaptive agent proposal
→ validation and human activation
→ governed execution
→ traceable result

Primary risks and mitigations:

| Risk                          | Mitigation                                         |
| ----------------------------- | -------------------------------------------------- |
| Visual/canonical divergence   | Bindings, graph revisions, parity tests            |
| Pre-commit event leakage      | Transactional log/outbox; post-commit dispatch     |
| Graph explosion/leakage       | Server-derived immutable hard-bounded traversal    |
| Provenance volume/privacy     | Compact typed evidence, digests, scoped reads      |
| Stale writes                  | Graph revision plus object versions                |
| Partial compensation          | Truthful saga transitions and fresh approvals      |
| Database behavior differences | SQLite baseline plus PostgreSQL-marked tests       |
| Viewport selection loss       | Pinned hydration, boundary stubs, revision cursors |
| Trusted-looking AI config     | Untrusted proposal, validation, human activation   |

## Deferred

- 6. Multi-Workspace Collaboration
  - Nested and Federated Mobius Workspaces
- 7. Production Hardening
- 8. Public Portfolio and Product Release
- 9. SolarPlexus Agent Ecosystem
