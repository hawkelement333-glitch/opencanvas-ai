# Milestone 5.1 Handoff — Knowledge Graph Foundation

Status: complete locally

Branch: `milestone-5-living-knowledge-workflows-architecture-local`

Starting architecture commit: `f9cc7ea3240cc9df79d0685031b5ac64d515d567`

`MILESTONE 5.1 KNOWLEDGE GRAPH FOUNDATION COMPLETE LOCALLY — READY FOR LIVING STATE AND EVENT SYSTEM`

## Delivered boundary

Milestone 5.1 extends the canonical object and relationship system. It does not
create a separate graph database or promote visual canvas edges into semantic
facts.

Delivered:

- stable graph identity backed by existing canonical objects;
- explicit user/workspace/canvas bindings;
- a closed relationship registry and endpoint compatibility rules;
- server-derived provenance and integrity digests;
- append-only relationship history;
- a monotonic workspace graph revision;
- authenticated, CSRF-protected, bounded graph APIs;
- deterministic idempotency and conflict behavior; and
- migration, integrity, security, concurrency, and failure validation.

Events/outbox, graph-aware retrieval, workflows, frontend graph visualization,
Agent Studio, federation, and repository ingestion remain deferred.

## Permanent traceability contract

Approved data
→ grounded answers
→ traceable workflows
→ adaptive agent proposals
→ governed agents
→ traceable results
→ evaluated feedback
→ governed agent improvement

> Every answer, workflow, agent definition, approval, action, retry, failure,
> evaluation, training proposal, quarantine decision, rehabilitation plan,
> promotion decision, and result must remain connected to the authority and
> evidence that produced it. Trace means auditable provenance and execution
> evidence, not private model chain of thought.

Focused inspection confirms that 5.1 is a stable foundation for this rule:

- graph entities resolve to canonical resources under exact user, workspace,
  and canvas scope;
- relationship type, direction, endpoints, scope, provenance, and lifecycle
  history are reconstructable;
- public user-created relationships identify the authenticated actor;
- controlled-agent provenance requires the responsible same-user/workspace
  controlled execution;
- imported or citation-derived provenance identifies its source reference, and
  deterministic provenance identifies its rule and version;
- deactivation and supersession append history while retaining original
  identity, provenance, and predecessor evidence;
- graph APIs expose bounded operational provenance and Trace identities without
  private reasoning, policy, grant, or hidden authority details; and
- later answers, workflows, and agent definitions can reference stable graph,
  provenance, and history identities without rewriting historical records.

No production defect was found during this amendment. No production code,
migration, event, retrieval, workflow, frontend, or Agent Studio implementation
changed, and checkpoint 5.2 was not started.

## Future adaptive-agent and training contract

Milestone 5.6 will establish two separate controlled proposal roles:

- The Adaptive Agent Architect may analyze approved goals, selected scoped data
  structures, repeated work, workflows, evidence needs, specialist roles,
  registered tools/providers, outputs, approval points, and resource/cost
  limits. It may propose an immutable versioned specialized-agent definition
  containing its purpose, framework, perspectives, sources, tools/providers,
  workflow bindings, evidence/testing standards, schema, escalation, limits,
  prohibited actions, and evaluation criteria.
- The Adaptive Training and Evaluation Agent may analyze approved Trace,
  workflow outcomes, evidence/citations, human feedback and decisions,
  evaluation scores, retries/failures/cancellations/rollbacks, reliability,
  latency, resources/cost, grounding quality, and later quarantine/
  rehabilitation outcomes. It may identify one supported weakness and propose
  a new immutable agent or workflow version changing controlled instructions,
  retrieval, workflow, tool-selection, schema, evaluation, thresholds, limit
  recommendations, restrictions, or remedial training.

Neither role can activate, approve, or promote its proposal; grant capability
or private data; install tools; choose unrestricted authority; raise limits;
bypass or weaken policy, security, or approvals; combine private scopes; hide
instructions, sources, conflicts, risks, failures, or evaluations; delete old
versions; release quarantine; create unrestricted descendants; or perform
autonomous model-weight training. Mobius validates exact registered
capabilities, tools, providers, scopes, permissions, policies, approvals,
resources, and costs. Human approval is mandatory for activation and
promotion.

Governed improvement must collect approved evidence, identify one supported
weakness, propose an immutable candidate, evaluate it in isolation against
fixed cases, compare it to the active version across grounding, citation/task
accuracy, security, authority, reliability, latency, and cost, reject weakened
controls, require human promotion, activate only the approved candidate,
preserve the prior version for audit/comparison/rollback, and retain later
failure/retraining/restriction/quarantine/retirement/replacement evidence.

Initial training is limited to frameworks, instructions, retrieval, workflows,
tools, schemas, limits, and evaluation cases. Autonomous model-weight training
is deferred. Any future fine-tuning requires licensed approved datasets,
privacy and scope review, dataset/model versions, held-out security and
grounding evaluations, human-controlled promotion, monitoring, and rollback.

## Entity kinds

The first-stage registry contains only repository-backed canonical kinds:

| Kind        | Identity and resolution                                                                |
| ----------- | -------------------------------------------------------------------------------------- |
| `document`  | Existing non-deleted `CanonicalObject` and `CanonicalDocument` in the owned workspace  |
| `note`      | Existing non-deleted `CanonicalObject` and `CanonicalNote` in the owned workspace      |
| `execution` | Existing non-deleted `CanonicalObject` and `CanonicalExecution` in the owned workspace |

No placeholder agent, workflow, repository, organization, project, answer,
citation, effect, or federated entity persistence was created. Existing
answers, citations, and reversible effects need an explicit canonical mapping
before they can become graph identities.

`CanonicalGraphEntity` stores only identity, kind, scope, creation actor, and
Trace. `CanonicalCanvasObjectBinding` is immutable and permits one canonical
entity to appear on multiple canvases inside the same owned workspace.

## Relationship registry

| Type           | Source kinds              | Target kinds              | Cycle rule |
| -------------- | ------------------------- | ------------------------- | ---------- |
| `references`   | document, note, execution | document, note, execution | Allowed    |
| `derived_from` | note, execution           | document, note, execution | Prohibited |
| `related_to`   | document, note, execution | document, note, execution | Allowed    |
| `cites`        | note, execution           | document                  | Allowed    |
| `supports`     | document, note            | note, execution           | Allowed    |
| `contradicts`  | document, note            | document, note            | Allowed    |
| `produced_by`  | document, note            | execution                 | Allowed    |
| `affected_by`  | document, note            | execution                 | Allowed    |

Direction is explicit and reverse edges are not inferred. Every type rejects
self-edges. Only `derived_from` is acyclic; its check is bounded to 500 active
edges and fails closed if the bound is exceeded.

The older canonical `contains` and `part_of` types remain valid for existing
canonical APIs but are not exposed by the 5.1 graph API because chunks and
container entities are not in the initial graph entity registry.

## Persistence and migration

Revision `20260725_0016` adds:

- `workspace_graph_states`
- `canonical_graph_entities`
- `canonical_canvas_object_bindings`
- `canonical_graph_relationships`
- `canonical_relationship_provenance`
- `canonical_relationship_history`

`CanonicalGraphRelationship` is a one-to-one scoped integrity extension of the
existing `CanonicalRelationship`. Composite foreign keys enforce object, user,
workspace, canvas, endpoint-binding, controlled-execution, and relationship
scope. Completed migrations were not edited.

New sole head: `20260725_0016`.

SQLite clean upgrade, downgrade to `20260724_0015`, and re-upgrade pass.

## Provenance and history

The closed provenance registry supports:

- `user_created`
- `imported_canonical`
- `citation_derived`
- `controlled_agent_approved`
- `deterministic_rule`

Public APIs always derive `user_created`. Clients cannot submit origin, actor,
execution, Trace, timestamp, digest, scope, or history state. Other origins
exist only as persistence contracts for future trusted adapters.

Agent provenance requires a same-user/workspace controlled execution.
Imported/citation provenance requires a source reference. Deterministic
provenance requires rule ID and version.

SHA-256 relationship and provenance digests use canonical JSON over
server-derived identity, direction, type, scope, origin, actor, and Trace
fields. Request digests bind idempotency keys to exact inputs.

History records `active`, `inactive`, `superseded`, or `rejected`. Transitions
reference their predecessor and graph revision. Identity, endpoints, type,
provenance, and prior history are never rewritten. Timeline ordering uses the
monotonic graph revision because SQLite timestamps may tie.

ORM listeners and SQLite/PostgreSQL triggers reject updates/deletes of graph
entity, canvas binding, graph relationship, provenance, and history. Endpoint
deletion blocks new resolution while existing relationship evidence remains
readable in its original scope.

## Scope, idempotency, and authority

- Authentication derives the user; path ownership and CSRF protect mutations.
- The service revalidates workspace owner, lifecycle, and exact canvas scope.
- Both endpoints must be supported, non-deleted canonical objects with
  same-user/workspace/canvas bindings.
- Cross-user and cross-workspace access fails with not-found semantics.
- Exact idempotency key and request digest replay the original result.
- Conflicting key reuse fails; a second key for an existing directional
  relationship also conflicts.
- Successful mutations advance the server-owned graph revision.
- Failed mutations roll back graph state, identity, provenance, history, and
  successful Trace evidence together.

Milestone 4 adds the closed capability
`knowledge_graph.relationship.write`, but no controlled action registers it in
5.1. The action registry remains grounded-draft only. A grant of any state
therefore cannot invoke a graph write. Agent graph writes remain fail-closed
until a future reviewed action supplies proposal, approval, audit, Trace,
lease, idempotency, and stale-result contracts.

## Service and APIs

`KnowledgeGraphService` resolves/binds entities, creates one typed
relationship, reads scoped relationships/provenance/history, appends
inactive/superseded/rejected transitions, handles replay/conflicts, advances
graph revision, and enforces cycles.

Routes:

- `POST /workspaces/{workspace_id}/canvases/{canvas_id}/knowledge-graph/relationships`
- `GET /workspaces/{workspace_id}/canvases/{canvas_id}/knowledge-graph/entities/{entity_id}/relationships`
- `GET /workspaces/{workspace_id}/canvases/{canvas_id}/knowledge-graph/relationships/{relationship_id}`
- `GET /workspaces/{workspace_id}/canvases/{canvas_id}/knowledge-graph/relationships/{relationship_id}/history`
- `POST /workspaces/{workspace_id}/canvases/{canvas_id}/knowledge-graph/relationships/{relationship_id}/transition`

Reads allow 1–100 results with bounded offsets. There is no whole-graph export,
unbounded traversal, autonomous discovery, or graph-aware AI endpoint.

## Exact validation results

- Complete non-PostgreSQL backend suite: **423 passed**.
- PostgreSQL-marked suite: **1 skipped**; no runtime URL was configured.
- Complete migration suite: **12 passed**.
- Focused graph/schema/agent-contract suite: **29 passed**.
- Strict mypy: **63 source files, no issues**.
- Focused Ruff/formatting: **69 files passed**.
- Python compilation, imports, and SQLAlchemy mapper configuration: passed.
- Alembic sole head: `20260725_0016`.
- SQLite upgrade/downgrade/re-upgrade and append-only triggers: passed.
- Authentication, CSRF, unknown authority fields, safe errors, and cross-user
  scope: passed.
- Separate-session competition: one authoritative relationship and one safe
  conflict.
- Partial-persistence injection: no relationship, provenance, history, graph
  revision, or false success Trace survived.
- Trace-completion injection: graph state rolled back; only started/failed
  Trace evidence remained.
- Exact duplicate delivery: one relationship and one creation-history row.

No frontend or network-dependent suites ran.

## Defects corrected

1. SQLAlchemy could flush the graph extension before its canonical
   relationship when all rows were added without ORM relationship properties.
   Persistence now flushes identity, canonical detail, scope, then evidence.
2. SQLite timestamp ties could display history out of order. Queries and the
   timeline index now use monotonic graph revision.
3. Migration tests and the standalone validator still expected head `0015`.
   Head-only expectations now use `0016`; tests intentionally targeting `0015`
   remain unchanged.

## SQLite and PostgreSQL status

SQLite proves foreign keys, checks, uniqueness, migrations, append-only
triggers, rollback, replay, and deterministic separate-session conflict.

SQLite ignores `SELECT ... FOR UPDATE` and does not prove PostgreSQL row locks,
deadlocks, isolation, concurrent unique inserts, or query plans. The
PostgreSQL-marked test was skipped because no configured runtime existed.
PostgreSQL runtime concurrency and plan validation remains mandatory before
production claims.

## Deferred scope

- 5.2 Living State and Event System
- 5.3 Graph-Aware Retrieval
- 5.4 Controlled AI Workflows
- 5.5 Dynamic Universe Interface
- 5.6 Bounded Agent Studio
- 5.7 Final Combined Milestone 5 Audit
- 6. Multi-Workspace Collaboration
  - Nested and Federated Mobius Workspaces
- 7. Production Hardening
- 8. Public Portfolio and Product Release
- 9. SolarPlexus Agent Ecosystem
  - SolarPlexus Academy and Adaptive Training System
  - Agent Justice, Quarantine, and Rehabilitation System

Milestone 5 is not complete. Stop before 5.2.

Later acceptance criteria now require:

- 5.3 to trace selected context, relationships traversed, retrieved passages,
  citations, inclusion/exclusion decisions, conflicts, insufficient-evidence
  outcomes, and traversal/context-budget limits;
- 5.4 to trace workflow identity/version, approved inputs, every step/outcome,
  models/tools/APIs, evidence/outputs, approvals, retries/recovery/cancellation,
  proposed/completed mutations, compensation/rollback, and final result;
- 5.6 to trace source framework, served workflow/job, proposed specialist
  roles, approved sources/tools, capabilities/limits, creator/approver,
  provider/model, validation/activation, and revisions, executions, suspension,
  retirement, and replacement; and
- 5.7 to prove approved data → canonical graph and provenance → grounded
  question and citations → versioned workflow → adaptive agent proposal →
  validation and human activation → governed execution → traceable result.

The 5.7 combined audit must additionally prove a specialized agent’s traceable
workflow, approved feedback/evaluation, supported weakness, immutable
candidate, fixed-case old/new comparison, non-regression in security/
permissions/grounding/provenance/reliability/cost, human promotion, approved
activation, reconstructable/reversible prior version, and safe source →
workflow → agent → evaluation → promotion Trace chain.

## Future Milestone 9 systems

Milestone 5.6 establishes only immutable versions, approved feedback/
evaluations, fixed cases, isolated candidate testing, controlled proposal
roles, human promotion, and rollback. The full **SolarPlexus Academy and
Adaptive Training System** is future Milestone 9 scope.

The Academy will organize domain schools, specialist departments, versioned
courses, approved lessons/frameworks/examples/tools/procedures, fixed
examinations, trainer/mentor/student/evaluator identities and lineage, approved
programs/datasets, Trace-backed transcripts, version-specific certifications,
remedial training, controlled skill transfer, candidate comparison,
human-controlled graduation/activation, retraining, suspension, quarantine,
rehabilitation, retirement, replacement, and rollback. Its records trace all
sources, versions, cases, identities, results, feedback, decisions,
post-graduation capabilities, and later adverse outcomes.

The Academy may teach, evaluate, compare, certify, recommend, and propose
retraining or rehabilitation. It cannot self-activate/promote, grant authority,
release quarantine, cross private scope, silently rewrite agents, conceal
failure, weaken controls, equate repeated output with correctness, train
unrestricted descendants, or autonomously train model weights.

The future **Agent Justice, Quarantine, and Rehabilitation System** contains:

1. Agent Quarantine Center
2. Agent Rehabilitation Center
3. Agent Review Tribunal

“Jail” is only an optional visual metaphor for technical isolation, not
punishment or agent personhood. Evidence-supported eligibility covers
unauthorized or repeatedly out-of-scope action, unsafe/corrupted/unreliable
output, identity/version/signature/integrity failure, revoked dependency use,
behavior drift, resource-limit violations, poisoned-data instructions, failed
required Academy evaluation/certification, and hidden delegation or authority
expansion.

Server-authoritative quarantine may stop jobs, fence leases, revoke temporary
grants, block delegation/cross-planet travel and ordinary workspace access,
preserve configuration/memory references/versions/Trace/evidence, protect
required records, and notify authorized humans. Rehabilitation diagnoses and
reproduces the exact failure in isolation, proposes corrective training and a
new immutable version, performs fixed safety/task comparison, requires human
release approval, restores only minimum approved capabilities, and preserves
the prior version.

The human-controlled Tribunal reviews evidence, policy findings, evaluations,
plans, recommendations, appeals, and retirement. Outcomes include release,
restricted release, remedial Academy training, retraining, replacement,
continued suspension/quarantine, retirement, archival, and only legally and
technically permitted deletion preserving required audit evidence.

Every case retains trigger → evidence → quarantine decision → investigation →
rehabilitation/training plan → evaluation → human decision → release,
restriction, replacement, retirement, or continued quarantine. An unsupported
agent claim is never sufficient.

> Agents may detect, classify, and report unsafe behavior, but only
> server-enforced policy and authorized humans may quarantine, restrict,
> restore, release, replace, or retire an agent.

The system cannot let agents punish, release, or retire one another; erase
adverse evidence; rewrite Trace history; grant authority through
rehabilitation; combine private evidence; quarantine indefinitely without
review rules; release without evaluation and human approval; or make original
behavior disappear through rehabilitation.

Academy, quarantine, rehabilitation, and tribunal requirements are future
documentation and acceptance criteria only, not 5.7 implementation
requirements. This amendment creates no production code, migrations, tests,
models, APIs, capabilities, event types, workflows, agents, evaluations,
Academy system, quarantine system, or frontend, and does not start 5.2.

## Protected local Git state

No push, pull, fetch, sync, upstream, pull request, remote branch/tag change,
publication, upload, deployment, release, GitHub setting, or GitHub write
occurred.

- `main`: `f04ace592e253c48172d129331ed8cd9bc4d4f4f`
- completed Milestone 4:
  `dadf114cfb33c557d6d1be7d8f98a4bb3ba36818`
- `competition-demo-v1` tag object:
  `acbde89b6e2cc3e41c372887794726d393836716`
- protected tagged commit:
  `b45b7763b65861f9dfb3be7edf9b5eb271950917`
