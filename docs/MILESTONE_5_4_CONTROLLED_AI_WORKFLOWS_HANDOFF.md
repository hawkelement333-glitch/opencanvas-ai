# Milestone 5.4 Controlled AI Workflows Handoff

Date: 2026-07-25

Status: complete locally

Branch: `milestone-5-living-knowledge-workflows-architecture-local`

Starting SHA: `c575945091a393590fb25a45a6bfb85a29406da0`

Alembic sole head: `20260725_0019`

## Outcome

Milestone 5.4 adds a repository-grounded controlled workflow layer without
creating a second authority, retrieval, evidence, provider, Trace, audit,
event, outbox, effect, rollback, lease, or retry system. An authenticated
human can explicitly start an active immutable workflow version. The service
then executes a bounded deterministic DAG under exact user/workspace/canvas
scope and records reconstructable authority, evidence, execution, and outcome
facts without private model reasoning.

The permanent product loop remains:

Approved data
→ grounded answers
→ traceable workflows
→ adaptive agent proposals
→ governed agents
→ traceable results
→ evaluated feedback
→ governed agent improvement

Milestone 5.4 implements only the traceable-workflow stage.

## Persistence and migration

Migration `20260725_0019_controlled_ai_workflows.py` follows
`20260725_0018` and creates:

- controlled workflow definitions;
- immutable workflow versions and append-only version states;
- immutable steps and dependencies;
- scoped workflow executions;
- immutable deterministic plan snapshots;
- append-only execution transitions;
- step executions with lease generation and bounded attempts;
- append-only step transitions;
- append-only step-attempt evidence; and
- append-only evidence links.

Composite keys and foreign keys retain user, workspace, canvas, definition,
version, execution, and step scope. Check constraints close lifecycle,
outcome, failure, compensation, schema, digest, and attempt values. Unique
constraints enforce scoped idempotency and one authoritative plan/result.
Indexes support scoped reads, ready work, transitions, retries, deadlines, and
evidence lookup. SQLite and PostgreSQL definitions include append-only
mutation protection for immutable records.

The migration upgrades from an empty database, downgrades to
`20260725_0018`, and re-upgrades to `20260725_0019`. PostgreSQL DDL compiles
offline. PostgreSQL runtime locking, isolation, deadlock, and query-plan
behavior were not tested because no PostgreSQL runtime was configured.

## Definition, versions, and lifecycle

`controlled-workflow-v1` uses stable server-created definition and version
identities. Names and descriptions are bounded. Every definition edit creates
a new immutable version rather than rewriting executable history. Canonical
serialization produces a stable SHA-256 content digest. Supersession retains
the prior version and all of its evidence.

The closed workflow kinds are:

- `grounded_answer`;
- `evidence_package`; and
- `approved_reversible_note`.

The closed version lifecycle is:

- `draft`;
- `validated`;
- `active`;
- `superseded`;
- `disabled`; and
- `retired`.

Only an explicitly validated and activated version can start. Unknown,
tampered, draft, disabled, superseded, retired, and cross-scope versions fail
closed. Validation does not silently activate a version.

## Closed step registry and DAG plan

The registered step types are:

- `validate_input`;
- `capture_context`;
- `graph_retrieval`;
- `evaluate_evidence`;
- `grounded_model`;
- `render_citations`;
- `evidence_bundle`;
- `human_approval`;
- `controlled_effect`;
- `compensation`; and
- `record_output`.

Each registry entry fixes its capability, risk class, approval requirement,
and allowlisted configuration keys. Note create/update is chosen only from the
closed reversible-write action registry. Prompt templates, retrieval options,
providers, schemas, and compensation references are server validated.

Compilation rejects duplicate or missing step keys, self-dependencies, cycles,
invalid compensation references, unknown schemas and step types, unsupported
configuration, excessive dependencies, excessive operations, missing output,
and incompatible workflow shapes. Step and dependency identities and ready
ordering are deterministic. Runtime insertion, loops, recursion,
self-expansion, and model-generated steps do not exist.

The plan binds the immutable version and digest, normalized input and request
digests, selected canonical resources, graph revision, capabilities, approval
requirements, compensation mapping, and server limits.

## Server-owned bounds

- workflow steps: 32;
- dependencies per step: 8;
- selected context resources: 50;
- retrieval steps: 4;
- grounded model steps: 4;
- approval steps: 8;
- controlled effects: 8;
- evidence bundles: 4;
- retries per step: 3;
- total attempts: 64;
- workflow duration: 900 seconds;
- step input: 64,000 serialized bytes;
- step output: 64,000 serialized bytes;
- total output: 128,000 serialized bytes;
- name: 160 characters; and
- description: 1,000 characters.

Clients cannot increase these values. `insufficient_evidence`,
`conflicting_evidence`, and `bounded_result` remain distinct truthful
outcomes and are not converted into full supported success.

## Execution, authority, and approvals

A start request derives an authoritative execution identity from the
authenticated scope, immutable version, and idempotency identity. It binds:

- user, workspace, and canvas;
- workflow definition and version;
- normalized request and digest;
- exact selected and seed canonical identities;
- current graph revision;
- immutable plan snapshot and digest;
- deadline, retry, and compensation policy;
- root Trace identity; and
- transactional event/outbox evidence.

The client cannot supply execution, plan, lifecycle, capability, authority,
approval-satisfaction, worker, lease, digest, or outcome fields.

Ordinary executable steps create one distinct Milestone 4 controlled execution
with immutable context and plan snapshots and a narrow capability grant.
Policy is re-evaluated from server facts before the step. Missing, expired,
revoked, altered, mismatched, or cross-scope authority fails closed. Workflow
shape, model output, graph relationships, prior steps, and events never grant
authority.

Risk-bearing steps pause durably, release their lease, and await an exact human
decision. Approval binds the controlled execution, step capability/resource,
context digest, plan digest, scope, expiration, and decision. Denial is
truthful and terminal or enters predefined compensation. A workflow, model,
or step cannot approve itself.

## Retrieval, citations, provider, and output

Graph retrieval delegates to Milestone 5.3 with the exact selected-context
allowlist. Seed objects must remain inside it. Connected unauthorized objects
stay excluded. The workflow retains the graph revision, retrieval identity,
decision/path evidence, immutable source versions, exact citation identities,
conflict and insufficiency outcomes, and traversal bounds.

Grounded model steps use the existing server-selected provider abstraction.
They receive validated workflow input and approved retrieval evidence only.
Model-produced citation text is not authoritative; citation identities must
match the Milestone 5.3 result. Provider, model, provider-configuration
version, prompt version, token counts, input/output digests, and safe outcome
facts are recorded. Private chain of thought, credentials, and secret prompts
are not stored or returned.

Deterministic demo and test execution uses the existing mock provider and makes
no paid or external network call. External-provider behavior was not validated
in this checkpoint.

Supported workflows can attach the existing deterministic Trace Evidence
Bundle. The bounded output records safe result, evidence, citation, effect,
rollback, and bundle identities. It cannot contain raw grants, policy
internals, SQL, stack traces, local paths, worker/lease data, credentials, or
private model reasoning.

## Claims, retries, cancellation, and compensation

Ready work is claimed with an expiring lease and increasing generation.
Completion uses owner/generation/status compare-and-set checks. A recovered,
canceled, deadline-expired, or otherwise stale worker cannot commit its
output. Terminal work cannot reopen.

Only closed transient provider and internal classifications retry. Delay is
server derived and attempts remain bounded. Non-retryable and unknown failures
fail closed. A duplicate successful retrieval, model operation, effect, or
step delivery reuses authoritative evidence rather than repeating work.

Authenticated cancellation moves through request/canceling states, clears
leases, increments generations, prevents new ordinary work, and preserves
already committed evidence. Duplicate cancellation is idempotent.

Compensation is available only for a definition that declares the predefined
saga. The exact inverse is frozen before activation. A compensable effect
includes the matching rollback capability and exact post-effect resource in
its immutable action plan; that bounded authority alone cannot execute a
rollback. Cancellation freezes forward work, invokes the existing Milestone 4
rollback review, and pauses for a fresh human rollback approval. Execution
then calls the existing rollback service with exact revision/evidence checks
and idempotency.

Create compensation deletes only the note produced by the effect. Update
compensation uses immutable prior-title/prior-text evidence and exact revision
checks. Conflicts and failed compensation remain visible and are never
reported as rolled back. Duplicate compensation converges on the original
result.

## Trace, audit, events, and activity

Trace connects definition, version, request, plan, execution, every step,
policy result, approval, retrieval, citation, provider/model, output digest,
effect, retry, cancellation, compensation, evidence bundle, timing, and final
outcome. This is operational provenance, not model chain of thought.

The existing audit repository stores safe controlled-execution and step facts.
The existing Milestone 5.2 event/outbox transaction stores 23 new closed event
types:

- definition created;
- version created, validated, activated, and disabled;
- execution requested, planned, started, awaiting approval, completed, failed,
  and canceled;
- compensation started, completed, and failed;
- step started, completed, failed, retry scheduled, and awaiting approval; and
- approval requested, accepted, and denied.

Event identities and sources are deterministic where replay is possible.
Events cannot authorize or start a workflow. The existing bounded activity
consumer projects allowlisted workflow facts idempotently and preserves exact
scope.

## Scoped APIs

The authenticated canvas-scoped workflow API supports:

- create and read definition;
- create immutable version;
- validate, activate, and disable version;
- start and read execution;
- decide a pending step approval; and
- request cancellation.

State-changing routes use the repository's mutating-principal and CSRF
boundary. Reads and writes enforce exact user/workspace/canvas scope.
Pagination and serialization are bounded. Responses expose only allowlisted
operational provenance and never raw authority or worker internals.

## Transaction and failure behavior

Definition/version persistence, plan creation, execution start, step
completion, evidence linkage, lifecycle transitions, Trace/audit facts, and
domain event/outbox evidence share explicit database transaction boundaries.
Injected failures prove rollback does not leave a partial version, execution
without a plan, successful step without evidence, consumed approval without
the required effect/transition, false completion event, false success Trace,
duplicate effect, or false compensation.

Append-only ORM listeners and database triggers reject updates/deletes of
immutable workflow evidence. Mutable operational rows are changed only through
validated state transitions and generation-fenced compare-and-set operations.

## Validation summary

Focused controlled-workflow tests cover registries, version immutability, DAG
validation, deterministic plans, exact grounded evidence, API field rejection,
approval pause/accept/deny, one-time controlled effects, bounded retry,
cancellation, failure injection, append-only evidence, predefined
compensation, stale-generation suppression, and competing identical starts.

Affected Milestone 4 reversible effect, rollback, and persistence tests prove
the optional predefined-compensation authority does not broaden ordinary
reversible-write proposals. The complete non-PostgreSQL backend suite, strict
mypy, Ruff, compilation/imports, mapper configuration, migration cycling,
offline PostgreSQL DDL, repository hygiene, and Git integrity are required
release gates and are recorded in the final local checkpoint report.

SQLite contention proves deterministic convergence and stale-generation
behavior, but it is not evidence of PostgreSQL runtime locking or isolation.
No external provider, distributed queue, managed object storage, browser, or
frontend validation was needed because no frontend or external integration was
changed.

## Concrete defects corrected during audit

- SQLite ORM synchronization compared timezone-aware and naive timestamps;
  claim/completion updates now disable unsafe session synchronization.
- A step that first requested approval could remain `running`; the pause now
  releases the lease and records `awaiting_approval`.
- Approval pause consumed an attempt and could prevent resume; paused work no
  longer spends its bounded attempt.
- Approval-resume events reused an identity; generation now participates in
  the step-start event source.
- Equivalent graph retrieval requests in different idempotency scopes could
  collide on one deterministic primary key; retrieval identity now includes
  the scoped idempotency key.
- Migration helpers depended on the caller's working directory; Alembic script
  location is now absolute.
- Inactive compensation rows blocked ordinary completion; they now become
  truthfully skipped when compensation is not required.
- Predefined compensation lacked production rollback authority. The effect
  plan now predeclares only the exact inverse capability and post-effect
  resource while retaining a fresh human rollback approval.
- Compensation approval temporarily hid the compensation phase; final-state
  derivation now follows the durable cancellation marker and generation-fenced
  saga state.

## Deferred and explicitly absent

No Milestone 5.5 frontend, Dynamic Universe component, Bounded Agent Studio,
Adaptive Agent Architect behavior, agent creation/activation/training,
Academy, English Expert, quarantine, rehabilitation, tribunal, autonomous
trigger, schedule, recurring workflow, webhook trigger, federation,
distributed queue, arbitrary code, SQL, shell, filesystem, HTTP, plugin, or
MCP execution was added.

All previously documented Adaptive Agent, Training, Academy, English,
Evidence Bundle, APA, Quarantine, Rehabilitation, Tribunal, Milestone 5.5–5.7,
and Milestone 6–9 requirements remain authoritative and deferred.

## Local Git protection

All work remains local under the freeze through August 13, 2026. No push,
pull, fetch, sync, upstream, pull request, remote branch/tag change, upload,
publication, deployment, or release operation occurred. `main`, the Milestone
4 checkpoint, `competition-demo-v1`, protected tag history, and completed
Milestone 5.1–5.3 history remain unchanged and reachable.

Milestone 5 is not complete. The next authorized checkpoint is Milestone 5.5.
