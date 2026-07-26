# Milestone 5.6 Bounded Agent Studio Handoff

Date: 2026-07-25

Branch: `milestone-5-living-knowledge-workflows-architecture-local`

Starting commit: `15484c9b2ec728522b871bca7d5081d4149d5c0e`

Status: complete locally; Milestone 5 remains incomplete until 5.7.

## Outcome

Milestone 5.6 adds a bounded, human-governed Agent Studio over the completed
Milestone 4 authority system and Milestone 5.4 controlled workflow executor.
It provides immutable definitions, deterministic validation, exact activation,
controlled invocation, traceable evaluation and proposals, communication
profiles, protected-fact revisions, lifecycle controls, safe APIs, and a
responsive `/agents` interface.

The permanent product loop remains:

Approved data
→ grounded questions
→ traceable workflows
→ adaptive agent proposals
→ governed agents
→ traceable results

Every answer, workflow, agent definition, approval, action, retry, failure,
evaluation, proposal, communication revision, and result stays connected to
the authority and evidence that produced it. Trace is auditable provenance and
execution evidence, not private model chain of thought.

## Authoritative model

The `20260725_0020` migration adds append-only records for:

- agent identity and lifecycle state;
- immutable definition versions and version lifecycle state;
- exact workflow-version/digest bindings and capability requirements;
- deterministic validation reports;
- activation requests and human decisions;
- controlled invocations;
- adaptive/human proposals and human decisions;
- evidence-bound evaluations;
- communication profile identities and immutable versions; and
- proposed communication revisions and human decisions.

Every record retains exact opaque server-derived user, workspace, and canvas
scope. Composite foreign keys prevent cross-scope associations. Database
triggers and ORM listeners reject update/delete operations on immutable
records. Lifecycle, validation, activation, proposal, evaluation, invocation,
and communication history is append-only; supersession and deactivation never
rewrite evidence.

## Closed definition and validation contracts

The versioned `bounded-agent-definition-v1` contract contains a bounded purpose,
private system instruction, one to eight exact workflow version identifiers,
closed capability/resource requirements, explicit selected-context policy,
closed provider/model pair, server-capped limits, communication policy,
evaluation policy, and non-prohibited risk class.

The server owns the registries. Current providers are:

- `mock` / `mock-context-v1`; and
- `openai` / `gpt-5.6-terra`.

Validation is deterministic and content-digest-bound. It checks schema,
provider/model, limits, scoped active workflow identity and digest, workflow
capabilities, communication profile scope, and prohibited prompt requests such
as self-activation, authority escalation, bypassed approval, arbitrary tools,
or private-scope expansion. Validation writes an immutable report; it never
activates a version.

## Human activation and runtime authority

Activation is a separate exact human boundary:

1. the latest immutable version validates successfully;
2. an activation request freezes the validation identity, content digest,
   workflow bindings, capabilities, provider/model, risk, limits, and exact
   scope in an authority summary and request digest;
3. the request expires after fifteen minutes;
4. an authenticated, CSRF-protected human approves or denies the exact request;
5. approval activates only the validated version and supersedes a prior active
   version without deleting it.

Activation creates no capability grant and cannot authorize execution. Every
invocation rechecks identity state, active version, exact approved activation,
workflow identity/digest, user/workspace/canvas scope, explicit selected
context, and configured bounds. It then calls the completed Milestone 5.4
`ControlledWorkflowService`. That service remains the sole workflow executor
and obtains fresh Milestone 4 authority for each executable step.

There is no Agent Studio executor, standing authority, agent-generated grant,
autonomous trigger, recurring schedule, arbitrary code/tool/connector, hidden
delegation, descendant creation, or policy modification.

## Adaptive proposals and governed evaluation

Proposals may originate from a human, the bounded Adaptive Agent Architect, or
the bounded Adaptive Training and Evaluation Agent. Creating or accepting a
proposal cannot activate an agent, grant authority, install a tool, increase a
limit, assign private data, or start a workflow. Where an accepted creation or
improvement proposal can be materialized, it creates only a new immutable
draft identity/version requiring normal validation and human activation.

Evaluations bind an immutable outcome, summary, recommendations, exact
invocation, workflow execution, and evidence digest. Failed versions,
unfavorable evaluations, rejected proposals, and prior active versions remain
reconstructable.

The Adaptive Agent Architect may propose specialized definitions from approved
frameworks, data structures, repeated work, and workflows. It cannot activate
agents, grant authority, assign private data, install unreviewed tools, or
increase limits. Policy validation and human approval are mandatory before
activation.

## Adaptive English communication boundary

Communication profiles are immutable, versioned, and scoped to the exact user,
workspace, and canvas. The current profile contract uses closed audience,
reading-level, formality, verbosity, technical-depth, and optional Orwell-rule
values.

A communication revision records original and revised text, optional source
invocation, profile version, citation identifiers, content digests, protected
facts digest, preservation result, Trace, and later human decision. The
deterministic checker protects numbers, dates, measurements, URLs, hashes,
quotes, title-case names, citation identifiers, and explicit
insufficient-evidence, bounded-result, conflict, effect, compensation, and
cancellation warnings. Unsafe revisions fail closed and cannot be accepted.
Even a safe revision requires a separate human decision.

This checkpoint does not implement model-weight training, autonomous
communication-framework promotion, style imitation, organization membership,
Academy, quarantine, rehabilitation, or Tribunal behavior.

## Trace, events, activity, and API safety

Agent identity, version, validation, activation, invocation, evaluation,
proposal, communication revision, suspension, and retirement operations emit
real closed domain events through the completed transactional outbox. Trace
records contain safe lifecycle/provenance evidence. Controlled invocations
also retain the completed workflow and Milestone 4 audit/Trace chain.

The activity projection consumes the new events using its established
idempotent projector. Projection state never grants authority.

The authenticated namespace is:

`/workspaces/{workspace_id}/canvases/{canvas_id}/agent-studio`

Writes require the existing authenticated mutating principal and CSRF
boundary. Responses expose operational provenance, versions, digests, safe
limits, workflow bindings, validation issues, decisions, and Trace identities.
They omit private system instructions, raw grants, authority internals, worker
state, secrets, and private model reasoning.

## Frontend

The `/agents` route resolves the requested workspace and canvas only from the
authenticated server lists, then uses exact scoped Agent Studio APIs. It
provides:

- scoped identity list and lifecycle filters;
- closed-control draft and immutable-version creation;
- version history, digests, workflow bindings, and Trace links;
- deterministic validation;
- exact activation review with expiry and authority summary;
- deliberate human approve/deny confirmation;
- active-version invocation with explicit selected object IDs;
- workflow evidence navigation and immutable evaluation;
- proposal creation and human accept/reject review;
- communication profile creation;
- original/revised fact-preservation comparison and human decision;
- suspension, restoration, and retirement; and
- responsive keyboard-accessible loading, error, empty, and mobile states.

The client never accepts or derives user/workspace/canvas scope from an agent
definition, proposal, workflow binding, visual selection, or communication
profile. It does not display the private system instruction returned during
creation because the server never returns that value.

## Future Milestone 6 collaboration compatibility

Milestone 5.6 preserves compatibility with future Multi-Workspace
Collaboration without implementing Milestone 6.

All agent identities, versions, validation reports, activation records,
workflow bindings, invocations, evaluations, proposals, communication
profiles and revisions, Trace records, domain events, activity projections,
and API operations retain exact server-derived user/workspace/canvas scope.
Identifiers are opaque.

These concepts remain distinct:

- creator identity;
- workspace ownership;
- resource ownership;
- membership;
- role;
- action authority; and
- approval authority.

The service has an operation-level authorization seam before:

- agent creation;
- version creation;
- validation;
- activation;
- invocation;
- evaluation;
- proposal acceptance;
- suspension;
- restoration; and
- retirement.

The current seam enforces owner-only exact scope. Future membership and role
checks can replace that decision without changing immutable record identity,
historical scope, workflow authority, or API contracts. The implementation
does not assume one workspace per user, creator permanence, equal future
permissions, client-selected scope authority, cross-workspace resources, or
authority from visual adjacency/sharing.

No workspace membership table, invitation, collaboration role, sharing record,
comment, presence, live cursor, cross-workspace agent, cross-workspace workflow
binding, Milestone 6 API, Milestone 6 frontend behavior, or speculative
Milestone 6-only migration field was added.

Milestone 5.7 must explicitly verify exact scope on every Agent Studio record,
event, projection, Trace, and operation; distinct creator/ownership/
membership/role/action/approval concepts; all authorization insertion seams;
cross-scope failure; and the absence of Milestone 6 implementation.

## Milestone 6 and advanced real-time roadmap

Core Milestone 6 remains a normal required milestone immediately after
Milestone 5 and before Milestones 7 and 8. It is not deferred until after the
initial release.

Its required scope is workspace memberships; invitation lifecycle; closed
collaboration roles and permissions; approved workspace owner,
administrator, editor, approver, member, and viewer boundaries; scoped canvas,
resource, workflow, and agent sharing; comments and collaboration activity;
ownership transfer; access revocation; exact user/workspace/canvas/tenant
isolation; collaboration security; and final audit. Bounded basic online
presence is optional only if it does not delay the core.

Google-Docs-style simultaneous editing is not a Milestone 6 completion
requirement. The separate Future Advanced Real-Time Collaboration phase follows
the initial Milestone 8 controlled release and owns:

- live cursors;
- detailed user presence;
- simultaneous same-document or same-canvas editing;
- CRDT synchronization;
- operational-transform synchronization;
- offline editing;
- reconnect merging;
- deterministic conflict resolution;
- distributed presence infrastructure; and
- production real-time collaboration load/recovery testing.

The roadmap order is:

1. Milestone 5.6 — Bounded Agent Studio
2. Milestone 5.7 — Final Milestone 5 Audit
3. Milestone 6 — Core Multi-Workspace Collaboration
4. Milestone 7 — Production Hardening
5. Milestone 8 — Controlled Public Portfolio and Product Release
6. Future Advanced Real-Time Collaboration
7. Milestone 9 — SolarPlexus Agent Society
8. Milestone 10 — Civilization and Simulated Worlds

This list is preserved as historical checkpoint evidence. Its later product
positioning and names are superseded by
[`MOBIUS_CORE_PRODUCT_FAMILY_ROADMAP_AMENDMENT.md`](MOBIUS_CORE_PRODUCT_FAMILY_ROADMAP_AMENDMENT.md):
Milestone 8.0 completes Mobius Core 1.0, Milestone 8.5 is optional Advanced
Collaboration, and Milestones 9–13 are separate named product lines.

Milestone 5.7 must verify two distinct items:

1. Milestone 5.6 preserves all required future collaboration authorization
   seams and exact scope.
2. Milestone 6 remains scheduled normally, while Advanced Real-Time
   Collaboration alone is deferred until after Milestone 8.

## Migration and rollback

Alembic sole head is `20260725_0020`. The migration:

- upgrades from `20260725_0019`;
- creates only Agent Studio 5.6 state;
- extends closed event/subject constraints only for real Agent Studio
  producers;
- installs append-only enforcement for every new immutable table;
- downgrades back to `20260725_0019`; and
- upgrades again without residue.

PostgreSQL offline DDL compilation validates the PostgreSQL migration path.
The local audit uses SQLite for executable migration/runtime checks and does
not claim a configured PostgreSQL server.

## Validation and completion boundary

Exact local validation:

- complete non-PostgreSQL backend suite: `487 passed, 1 deselected`;
- PostgreSQL-marked suite: `1 skipped, 487 deselected` because no PostgreSQL
  runtime is configured;
- dedicated security suite: `29 passed, 459 deselected`;
- focused Agent Studio backend suite: `12 passed`;
- complete migration suite across legacy, graph, events, retrieval, workflow,
  and Agent Studio cycles: `20 passed`;
- standalone migration validator: upgrade `20260725_0020`, downgrade
  `20260725_0019`, re-upgrade `20260725_0020`;
- complete frontend unit/component suite: `66 passed` in 15 files;
- Chromium Agent Studio direct-navigation, refresh, and 390px layout smoke:
  `2 passed`;
- optimized Next.js 16.2.10 build: passed, including dynamic `/agents` and
  `/universe`;
- full TypeScript: passed;
- full ESLint with zero warnings: passed;
- full frontend and documentation Prettier: passed;
- full Ruff formatting and lint across `apps/api` and `scripts`: passed;
- strict MyPy across 75 API source files: passed;
- Python compilation and import validation: passed;
- SQLAlchemy mapper validation: passed with 96 configured mappers;
- PostgreSQL `0019:0020` offline DDL compilation: passed;
- SQLite append-only trigger and ORM immutability checks: passed;
- exact duplicate, conflicting reuse, expiry, workflow revocation, cross-scope,
  failure-injection, safe event/activity projection, and file-backed SQLite
  identity-contention cases: passed;
- repository hygiene: passed for 310 source files;
- secret-pattern, local-path, prohibited-scope, whitespace, and
  `git diff --check` scans: passed.

The only warning is the established FastAPI/Starlette deprecation warning for
`HTTP_422_UNPROCESSABLE_ENTITY`; it is unrelated to Agent Studio behavior.
Automated browser checks are not a complete accessibility certification, and
SQLite contention tests do not establish PostgreSQL locking guarantees.

## Concrete defects corrected during the audit

1. Communication-profile identities and versions initially lacked exact canvas
   scope. Composite user/workspace/canvas scope and foreign keys were added to
   the model, migration, service, API, tests, and frontend contract.
2. The activation-request model initially lacked the composite uniqueness
   needed by its exact version-scope foreign key. The constraint was added.
3. ORM domain-event checks initially omitted the new real Agent Studio event
   types. ORM and migration registries were synchronized.
4. The retirement event name was misspelled during implementation and was
   corrected to the closed `agent.retired` contract.
5. The frontend initially checked the wrong safe communication-revision status.
   It now permits human acceptance only for the server-declared `preserved`
   outcome.
6. Thirteen established migration assertions and the standalone validator
   still named prior head `20260725_0019`. Current-head assertions now use
   `20260725_0020`; checkpoint-specific migration cycles remain pinned to their
   own revisions.
7. Two initial browser assertions used ambiguous text locators. They were
   narrowed to semantic heading/profile scopes; no product defect was involved.

Milestone 5.7 was not started. No combined Milestone 5 audit, Milestone 6
feature, deployment, publication, or remote operation occurred.
