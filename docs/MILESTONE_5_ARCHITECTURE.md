# Milestone 5 Architecture — Living Knowledge Graph and AI Workflows

Status: architecture and checkpoints 5.1–5.4 complete locally; 5.5–5.7 pending

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

## Implemented 5.2 event foundation

Milestone 5.2 implements a closed `mobius-domain-events-v1` registry,
immutable scoped event/provenance evidence, an event-per-workspace sequence,
and one transactional outbox row per event. Graph relationship creation and
lifecycle transitions, approved controlled effects, and approved rollbacks
write their event evidence inside the authoritative mutation transaction.
Exact idempotent replay returns the original event; conflicting reuse fails
closed.

The local deterministic consumer creates only an append-only `activity-v1`
projection. It cannot invoke models, start agents or workflows, grant
authority, or mutate unrelated authoritative state. Dispatch claims use
server-owned bounded attempts, expiring leases, monotonically increasing
generations, stale-owner fencing, closed failure classifications, and terminal
states that cannot reopen. Authenticated bounded read APIs expose allowlisted
activity, event, and delivery status only.

Evidence-bundle and citation lifecycle names are reserved contracts. They have
no producer and cannot be emitted during 5.2. All Adaptive Agent, Training,
Academy, English, Evidence Bundle, APA, Quarantine, Rehabilitation, and
Tribunal requirements remain unchanged future acceptance criteria.

## Implemented 5.3 retrieval and evidence foundation

Milestone 5.3 extends the canonical graph, existing document chunks/embeddings,
Trace, and transactional event/outbox boundary. A retrieval begins from
authenticated, user-selected canonical objects bound to the exact workspace
and canvas. Seed objects must be a subset of that selected allowlist. A graph
relationship never grants access to an unselected object.

`graph-retrieval-v1` performs deterministic bounded traversal over active
`references`, `derived_from`, `related_to`, `cites`, `supports`,
`contradicts`, `produced_by`, and `affected_by` relationships. Direction is
forward except `related_to` and `contradicts`, which are bidirectional.
Server-owned limits are 50 selected objects, 50 seeds, depth 3, 250 visited
entities, 500 considered relationships, 200 candidates, 50 passages, and
60,000 serialized evidence characters. Existing deterministic mock embeddings
remain the demo/test boundary; no external retrieval or paid dependency was
added.

Retrieval runs, decisions, and `graph-citation-v1` passage evidence are
append-only and bind graph revision, canonical/source version, source/excerpt
hash, exact locator, relationship path, and Trace. Outcomes are closed to
supported, conflicting evidence, insufficient evidence, and bounded result.
APA 7 rendering uses only existing repository metadata, emits `n.d.` where
date metadata does not exist, labels internal/uploaded material, emits no
invented author/publisher/URL, and escapes Markdown-significant text.

`trace-evidence-bundle-v1` produces a deterministic ZIP containing README,
manifest, Trace report, references, citation mapping, exact excerpts, and
SHA-256 checksums. Complete sources are omitted with
`export_not_authorized` because no general source-export authority exists.
The verified opaque ZIP bytes are stored transactionally in the database.
All eight previously reserved evidence-bundle/citation event contracts now
have real 5.3 producers and transactional outbox records. Events cannot start
agents or workflows.

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

The future-compatible event contract reserves evidence-bundle requested,
generation started, generation completed, generation failed, bundle accessed,
export denied, citation rendering completed, and citation rendering failed.
Milestone 5.2 must establish their safe event semantics without this
documentation amendment implementing event types.

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

### Trace Evidence Bundle and APA 7

The future **Trace Evidence Bundle** is an immutable export package containing
the exact permitted evidence used for a grounded answer, workflow result, agent
result, evaluation, or training proposal. It distinguishes selected,
retrieved, included, excluded, conflicting, and insufficient evidence; full
source files included under export authority; and referenced sources that are
not exportable.

Where applicable, a bundle records the question/task and final result;
canonical source IDs, names, types, immutable versions, and hashes; exact cited
excerpts and page/section/paragraph/line/character locators; repository paths
and commit IDs; traversed graph entities/relationships; retrieval rankings and
inclusion/exclusion reasons; conflict and insufficient-evidence records;
workflow/agent/framework identities and versions; model/provider; tools/APIs;
permissions/approvals; audit/Trace references; creation/access times; and an
integrity manifest.

Full-source export includes immutable copies only when authorized. Otherwise,
the bundle contains only permitted excerpts, redacted metadata, canonical
references, version hashes, and safe access references. It never includes
unrelated workspace content, out-of-authority material, private model chain of
thought, raw grants, credentials/secrets, worker/lease secrets, hidden policy
internals, or private information requiring redaction.

ZIP is the initial practical container:

```text
trace-evidence-bundle.zip
├── README.md
├── manifest.json
├── trace-report.md
├── references.md
├── citations.json
├── excerpts/
│   ├── source-001-excerpt.txt
│   └── source-002-excerpt.txt
├── authorized-sources/
│   ├── source-001.pdf
│   └── source-002.docx
└── integrity/
    └── sha256sums.txt
```

`README.md` explains the bundle, requester, scope, included/omitted material,
and integrity verification. `manifest.json` records bundle/schema identity,
creation time, safe requester/workspace/canvas identifiers, task/result
identity, every file and SHA-256 hash, source authority/export status,
canonical source version, Trace/audit references, and redaction/omission
reasons.

`trace-report.md` gives the human-readable task/result, selected context,
retrieval/graph summary, used/excluded/conflicting/insufficient evidence,
workflow or agent summary, approvals, and relevant actions. `references.md`
contains an APA 7 References section with exactly the cited sources.
`citations.json` maps displayed citation text to canonical source ID, immutable
version, hash, exact excerpt, locator, supported answer claim or workflow step,
and Trace reference.

`excerpts/` contains exact permitted passages under stable manifest-linked
filenames and no unauthorized surrounding content. `authorized-sources/`
contains only authorized complete immutable files and is absent when none are
authorized. `integrity/sha256sums.txt` contains the SHA-256 value of every
exported file except itself, in deterministic path order, matching the
manifest.

ZIP construction uses deterministic filenames, rejects unsafe paths and path
traversal, prevents duplicates, and enforces a bounded total size. Streaming
large files, encryption, signed manifests, temporary download links, retention,
cleanup, and regional export controls remain Milestone 7.

APA 7th edition is the initial human-readable citation style. When
authoritative metadata supports it, Mobius renders parenthetical citations
such as `(Author, Year)`, narrative citations such as `Author (Year)`, direct
quotations such as `(Author, Year, p. 12)`, and one References entry per cited
source. Every citation links through Trace to the canonical source version and
exact passage.

Citation metadata comes only from authoritative individual/organization
author, publication date, title, document type, publisher, journal/site,
edition/version, DOI, authorized URL, and accurate locator fields. Mobius never
invents missing metadata. It uses the best supported form, uses an organization
as author only when identified as such, uses `n.d.` only when no date exists,
uses the source title or approved internal-document name when no author exists,
and flags material metadata incompleteness when needed.

Private/internal citations never invent a public publisher or URL and never
expose an internal location to an unauthorized recipient. Canonical source ID,
immutable version, hash, and exact locator remain privately traceable even when
not displayed.

APA formatting is presentation only. It never replaces canonical Trace
identity, immutable source version, source hash, exact locator, or export-
authority enforcement. Each ZIP citation and References entry maps through
`citations.json` and `manifest.json` to a real canonical source, exact version,
accurate locator, supported claim/step, and export/access authority.

## Implemented 5.4 controlled workflow foundation

Milestone 5.4 implements `controlled-workflow-v1` as a server-owned,
human-started DAG over the completed Milestone 4 and Milestone 5.3 services.
Definitions have stable scoped identities. Every edit creates an immutable
version with a canonical SHA-256 digest, deterministic step/dependency
identities, a frozen plan snapshot, and append-only lifecycle evidence.
Only an explicitly validated and activated version executes.

The closed initial workflow kinds are grounded answer, evidence package, and
approved reversible note. The closed step registry contains input validation,
selected-context capture, graph retrieval, evidence evaluation, grounded
model use, citation rendering, evidence-bundle generation, human approval,
controlled effect, predefined compensation, and bounded output recording.
There are no script, SQL, shell, HTTP, filesystem, plugin, MCP, dynamic-step,
loop, recursive, event-triggered, scheduled, or recurring steps.

Runs bind the authenticated user, workspace, canvas, immutable version and
plan, normalized request digest, exact selected canonical identities, graph
revision, server-derived execution and step identities, deadline,
idempotency, Trace, audit, and transactional domain-event/outbox evidence.
Non-effect executable steps receive their own Milestone 4 context, plan,
execution, and narrow capability grant. Retrieval, citations, APA rendering,
and evidence bundles reuse Milestone 5.3 directly. Provider/model selection
remains server controlled and deterministic demo tests make no network call.

Claims use expiring leases and monotonically increasing generations.
Completion is compare-and-set fenced, retry classes and delays are closed and
bounded, and cancellation increments generations before canceling pending
work. Predefined saga steps declare the exact inverse before activation. A
compensable effect includes only the matching rollback capability and exact
post-effect node identity in its immutable plan/grant; actual rollback still
requires fresh server review and a separate human rollback approval. Create
rollback deletes only the created note, update rollback uses immutable
prior-state evidence, and duplicate effect/rollback delivery converges on one
authoritative result.

Workflow APIs expose allowlisted operational state and safe evidence
identities. They never serialize grants, policy internals, prompts, private
reasoning, worker owners, leases, local paths, or credentials. The 23 workflow
event types feed the existing transactional outbox and idempotent activity
projection; they do not start workflows or grant authority.

Migration `20260725_0019` adds the version, DAG, execution, plan, transition,
attempt, and evidence-link tables with scoped constraints, indexes, and
append-only protections. See
[`MILESTONE_5_4_CONTROLLED_AI_WORKFLOWS_HANDOFF.md`](MILESTONE_5_4_CONTROLLED_AI_WORKFLOWS_HANDOFF.md).

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

Supported workflow results attach an immutable evidence bundle and preserve the
evidence used by each workflow step.

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

The interface provides authority-aware **View Evidence**, **Open Citation**,
**View References**, and **Download Evidence Bundle** controls without treating
client visibility as export authority.

Rejected: continued full snapshots, PostgreSQL-only correctness, client-derived
scope, and color-only state.

### Bounded Agent Studio

Templates and agents have stable identity, immutable versions/digests, typed
purpose/sources/closed tools/limits/approvals/exact workflow version, and
explicit activation transitions. AI output is an untrusted proposal. Server
policy validates and displays effective bounds; a human activates it.
Activation grants no runtime authority—every run uses Milestone 4.

Prohibit agent-initiated creation, delegation, descendants, arbitrary
connectors/tools/code, and policy modification. These belong to Milestone 9.

#### Adaptive Agent Architect

Milestone 5.6 records the Adaptive Agent Architect as a future controlled,
proposal-only role. It may analyze approved:

- user goals;
- selected and scoped data structures;
- repeated questions and tasks;
- versioned workflows;
- evidence requirements;
- specialist-role needs;
- registered tools and providers;
- required outputs;
- approval points; and
- time, token, cost, and retry limits.

It may propose an immutable, versioned specialized-agent definition containing
purpose and role, operating framework, specialist perspectives, approved
knowledge sources, proposed tools and providers, workflow bindings, evidence
and testing standards, output schema, escalation rules, recommended operating
limits, prohibited actions, and required evaluation criteria.

It cannot activate or approve its own proposal, grant capabilities, assign
private data, install tools, select unrestricted authority, increase budgets or
limits, bypass policy validation, create unrestricted descendants, or hide
inherited instructions, sources, conflicts, or risks.

Mobius validates every proposal against registered capabilities, tools,
providers, user/workspace/canvas scopes, data permissions, policy rules,
approval requirements, resource limits, and cost limits. Human approval is
required before activation.

Each proposal and activated agent remains traceable to the user goal, source
framework, workflow or job served, approved sources, proposed and approved
tools, capabilities and limits, creator and approver, provider and model,
validation results, activation decision, later versions, executions,
suspension, retirement, and replacement. Quarantine and rehabilitation join
that chain only when the future Milestone 9 systems exist.

#### Adaptive Training and Evaluation Agent

Milestone 5.6 also records a separate future controlled Adaptive Training and
Evaluation Agent. It may analyze approved agent-execution Trace records,
workflow-step outcomes, retrieved evidence and citations, human corrections,
approval and rejection decisions, evaluation scores, retries, failures,
cancellations, rollbacks, latency and reliability measurements, token/tool/API/
storage/compute/cost use, grounding and citation quality, and—when Milestone 9
implements them—quarantine and rehabilitation outcomes.

It may identify one evidence-supported weakness and propose a new immutable
agent or workflow version by changing frameworks and instructions, retrieval
policies, workflow steps, tool-selection rules, output schemas, evaluation
cases, approval-threshold recommendations, server-controlled time/token/cost/
retry recommendations, or proposed restrictions and remedial-training
requirements.

It cannot silently alter an active agent; approve or promote its own proposal;
release an agent from quarantine; grant capabilities or data access; weaken
approval, policy, or security rules; combine private data across users or
workspaces; treat successful execution as proof of correctness; delete failed
versions or unfavorable evaluations; hide evaluation results; train on
unapproved data; create unrestricted descendants; or perform autonomous
model-weight training.

#### Governed improvement process

Agent and workflow improvement follows this required process:

1. Collect approved Trace, result, evaluation, and feedback records.
2. Identify one specific evidence-supported weakness.
3. Propose a new immutable agent or workflow version.
4. Evaluate the candidate in an isolated environment against fixed cases.
5. Compare candidate and active versions across grounding, citation accuracy,
   task accuracy, security, authority boundaries, reliability, latency, and
   cost.
6. Reject any candidate that weakens security, scope, provenance, reliability,
   or approval requirements.
7. Require human approval for promotion.
8. Activate only the approved version.
9. Preserve the earlier version for audit, comparison, and rollback.
10. Record later failures, retraining, restriction, quarantine, retirement, or
    replacement.

Initial “training” means governed improvement to frameworks, instructions,
retrieval, workflows, tools, schemas, limits, and evaluation cases. Autonomous
model-weight training remains deferred.

Any future fine-tuning requires approved and properly licensed datasets,
privacy review, data-scope validation, dataset and model versioning, held-out
evaluations, security and grounding evaluation, human-controlled promotion,
monitoring, and rollback.

#### Adaptive English Communication Expert

Milestone 5.6 records the **Adaptive English Communication Expert** as a future
controlled role. Its purpose is clear, correct, concise, audience-appropriate
English that preserves supported facts, citations, technical meaning,
uncertainty, and safety warnings.

It may assist with grammar, spelling, punctuation, sentence structure,
plain-English rewriting, concision, professional/academic/technical/
instructional/conversational tone, reading-level adjustment, audience-specific
explanations, consistent terminology, editing documents/messages/reports/
workflow results/agent outputs, identifying vague/repetitive/confusing/
needlessly complex language, retaining technical terms needed for precision,
and before/after explanations of material edits.

It may learn only from approved user corrections; accepted/rejected rewrites;
user-controlled tone/style preferences; organization style guides;
terminology/glossary lists; audience/reading-level requirements; examples;
reviewer feedback; evaluations; and prior immutable framework versions and
Trace. It may propose immutable new versions of writing frameworks,
communication instructions, terminology rules, tone/reading-level profiles,
response templates, editing workflows, and language evaluation cases.

Every review distinguishes factual correction, grammar correction, clarity
improvement, tone change, reading-level adjustment, terminology normalization,
and unsupported content requiring human review.

It must not silently alter facts, names, dates, numbers, citations, or supported
claims; remove uncertainty, limits, or safety warnings to sound confident;
invent missing information; replace technical terms inaccurately; cross private
scope; universalize one user’s style; deceptively imitate a real person;
self-promote a framework; alter an active agent without approval; or perform
autonomous model-weight training.

Grounded rewrites preserve Trace links to original text, canonical source
versions, evidence/citations, workflow and agent versions, requested audience/
style profile, accepted/rejected changes, and human approvals.

User-controlled communication profiles may define tone, formality, reading
level, sentence-length preference, technical-detail level, terminology
preferences, prohibited phrases, organization style guide, and optional
writing-rule profiles. George Orwell’s six prose rules are one optional
supported profile, never a universal system rule.

The governed improvement process is:

1. Receive approved source text and a communication goal.
2. Identify audience, tone, and reading level.
3. Propose a revision without changing supported facts.
4. Mark material edits and explain their purpose.
5. Evaluate grammar, clarity, precision, readability, terminology, citation
   preservation, and factual preservation.
6. Collect approved human feedback.
7. Propose a new immutable communication-framework version only after repeated
   supporting evidence.
8. Compare it against fixed writing and fact-preservation cases.
9. Require human approval before promotion.
10. Preserve previous versions, evaluations, and rejected edits for Trace and
    rollback.

Where applicable, English revisions and their evaluations, candidate
comparisons, and training proposals attach citations and evidence bundles.

## Logical model, service, and API outline

Planned records:

| Area         | Records/invariants                                                 |
| ------------ | ------------------------------------------------------------------ |
| Graph        | workspace graph state, typed subtypes, temporal canvas bindings    |
| Provenance   | immutable relationship assertions with endpoint versions           |
| Events       | domain events/outbox, sequences, projector checkpoints             |
| Retrieval    | immutable graph-context snapshots and path evidence                |
| Workflows    | versions, steps, runs/transitions, M4 bindings, compensation       |
| Agent Studio | versions, proposals, feedback, fixed cases, evaluations, promotion |
| Universe     | tiles and rebuildable viewport/summary projections                 |

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

It must also prove the governed-improvement chain:

1. A specialized agent completes a traceable workflow.
2. Approved human feedback or an evaluation score is recorded.
3. The Training Agent identifies a supported weakness.
4. A new immutable candidate version is proposed.
5. Old and new versions are evaluated against fixed cases.
6. The candidate cannot weaken security, permissions, grounding, provenance,
   reliability, or cost controls.
7. Human approval controls promotion.
8. The approved version is activated.
9. The earlier version remains reconstructable and reversible.
10. The complete source-to-workflow-to-agent-to-evaluation-to-promotion chain
    remains visible through safe Trace records.

Quarantine, rehabilitation, and Academy systems remain future Milestone 9
scope, not Milestone 5.7 implementation requirements.

Evidence-bundle and communication acceptance must prove:

- every citation maps to a real source and authoritative metadata;
- missing metadata is not fabricated;
- quoted passages and locators match immutable sources;
- every exported file is authorized;
- ZIP names/paths are safe and manifest/SHA-256 values match;
- included, excluded, conflicting, and insufficient evidence remain distinct;
- bundle and Trace reconstruct the same path after later source changes;
- English revisions improve clarity/correctness while preserving factual
  meaning, names, dates, numbers, citations, technical terms, uncertainty, and
  limitations;
- approved tone and reading level are followed;
- unsupported content is flagged rather than invented; and
- original/revised text plus accepted/rejected edits remain reconstructable and
  traceable.

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

## Future Milestone 9 — SolarPlexus Academy

Milestone 5.6 establishes only Academy foundations: immutable agent and
workflow versions, approved feedback and evaluation records, fixed evaluation
cases, isolated candidate testing, Adaptive Agent Architect proposals,
Adaptive Training and Evaluation Agent proposals, human-controlled promotion,
and version rollback. Milestone 9 expands those foundations into the complete
SolarPlexus Academy.

The Academy includes a future **School of Language, Communication, and
Explanation**, with possible departments for Plain English, Technical Writing,
Academic Writing, Professional Communication, Instruction and Teaching,
Documentation, Editing and Quality Review, and Audience and Accessibility
Adaptation.

The Academy supports schools organized by broad technology or knowledge
domains; departments organized by specialist roles; versioned courses for
defined agent capabilities; approved lessons, frameworks, examples, tools, and
procedures; fixed examinations and evaluation suites; trainer, mentor, student,
and evaluator agent identities; mentor and student lineage relationships;
approved training programs and datasets; performance transcripts linked to
exact Trace evidence; certifications tied to specific agent versions and
capabilities; remedial training after supported failures; controlled framework
and skill transfer; candidate-version comparison; human-controlled graduation
and activation; retraining; suspension; quarantine; rehabilitation; retirement;
replacement; and rollback.

Each Academy record remains traceable to approved training sources, framework
and course versions, evaluation cases, student-agent version, trainer and
evaluator identities, results and human feedback, promotion or rejection
decision, capabilities granted after graduation, and later failures,
retraining, restriction, quarantine, rehabilitation, or retirement.

The Academy may teach, evaluate, compare, certify, recommend, propose
retraining, and propose rehabilitation. It must not activate or promote its own
candidates; grant permissions or capabilities; release agents from quarantine;
use private data outside approved scope; silently rewrite active agents; hide
failed evaluations; weaken security or approval requirements; treat repeated
output as proof of correctness; train unrestricted descendants; or perform
autonomous model-weight training.

## Future Milestone 9 — Agent Justice, Quarantine, and Rehabilitation

The formal future system is named **Agent Justice, Quarantine, and
Rehabilitation System** and contains:

1. Agent Quarantine Center
2. Agent Rehabilitation Center
3. Agent Review Tribunal

“Jail” is permitted only as an optional visual metaphor. The technical system
isolates unsafe software behavior; it does not treat agents as people or impose
punishment.

An agent may become eligible for quarantine only when evidence shows an
attempted unauthorized action; repeated policy or scope violations; unsafe,
corrupted, or materially unreliable outputs; identity/version/signature/
integrity failure; use of a revoked tool, provider, capability, or grant;
behavior differing from its approved version; repeated cost/retry/population/
resource-limit violations; suspicious instructions from poisoned or untrusted
data; failed required Academy evaluations or certifications; or attempted
hidden delegation or authority expansion.

Quarantine is server-authoritative. It may stop new jobs, fence or revoke
active execution leases, revoke temporary grants, block delegation and
cross-planet travel, isolate the agent from ordinary apartments and workspaces,
preserve its configuration/memory references/versions/Trace/evidence, prevent
modification or deletion of required records, and notify authorized owners and
administrators.

The Agent Rehabilitation Center may:

1. Identify the exact supported policy, workflow, retrieval, tool, or authority
   failure.
2. Reproduce the failure in an isolated environment.
3. Compare expected and actual behavior.
4. Create a proposed corrective training plan.
5. Propose a new immutable agent version.
6. Test that version against fixed safety and task evaluations.
7. Compare it with the quarantined version.
8. Require authorized human approval before release.
9. Restore only the minimum approved capabilities.
10. Preserve the prior version for audit and rollback.

The Agent Review Tribunal provides human-controlled review of quarantine
evidence, policy findings, evaluation results, rehabilitation plans, release
and restriction recommendations, appeals, and retirement decisions. Outcomes
include release, restricted release, remedial Academy training, retraining,
replacement, continued suspension, continued quarantine, retirement, archival,
and deletion only where legally and technically permitted while preserving
required audit evidence.

Every case retains:

Triggering event
→ supporting evidence
→ quarantine decision
→ investigation
→ rehabilitation or training plan
→ evaluation results
→ human decision
→ release, restriction, replacement, retirement, or continued quarantine

No agent may be quarantined, restricted, restored, or retired solely because
another agent made an unsupported claim.

> Agents may detect, classify, and report unsafe behavior, but only
> server-enforced policy and authorized humans may quarantine, restrict,
> restore, release, replace, or retire an agent.

The system must not permit agents to imprison, punish, release, or retire one
another; erase adverse evidence; rewrite historical Trace records; grant new
authority through rehabilitation; combine private evidence across scopes;
allow indefinite unrestricted quarantine without review rules; release an
agent without required evaluation and human approval; or treat rehabilitation
as proof that the original behavior never occurred.

These Academy, quarantine, rehabilitation, and tribunal requirements are
future documentation and acceptance criteria only. Milestone 5 creates none of
their persistence models, APIs, capabilities, events, workflows, agents,
evaluations, or frontend components.

## Deferred

- 6. Multi-Workspace Collaboration
  - Nested and Federated Mobius Workspaces
- 7. Production Hardening
- 8. Public Portfolio and Product Release
- 9. SolarPlexus Agent Ecosystem
  - SolarPlexus Academy and Adaptive Training System
  - Agent Justice, Quarantine, and Rehabilitation System
