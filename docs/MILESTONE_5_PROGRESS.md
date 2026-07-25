# Milestone 5 Progress — Living Knowledge Graph and AI Workflows

Last updated: 2026-07-25

Branch: `milestone-5-living-knowledge-workflows-architecture-local`

Baseline: `dadf114cfb33c557d6d1be7d8f98a4bb3ba36818`

Milestone 5 architecture and checkpoints 5.1–5.3 are complete locally. The
next checkpoint is 5.4, Controlled AI Workflows.

`MILESTONE 5 ARCHITECTURE COMPLETE LOCALLY — READY FOR KNOWLEDGE GRAPH FOUNDATION`

| Checkpoint                        | Status           | Dependency               |
| --------------------------------- | ---------------- | ------------------------ |
| Architecture                      | Complete locally | Completed Milestone 4    |
| 5.1 Knowledge Graph Foundation    | Complete locally | Architecture             |
| 5.2 Living State and Event System | Complete locally | 5.1                      |
| 5.3 Graph-Aware Retrieval         | Complete locally | 5.1–5.2                  |
| 5.4 Controlled AI Workflows       | Not started      | 5.1–5.3 and M4           |
| 5.5 Dynamic Universe Interface    | Not started      | 5.1; 5.2/5.4 to complete |
| 5.6 Bounded Agent Studio          | Not started      | 5.4                      |
| 5.7 Final Combined Audit          | Not started      | 5.1–5.6                  |

Only checkpoints 5.1, 5.2, and 5.3 are complete. Milestone 5 is not complete.

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

This contract amendment did not reopen 5.1. The completed 5.1
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
- 5.7 proves both the source-to-governed-result chain and the feedback-to-
  evaluated-candidate-to-human-promotion chain while retaining the prior
  reversible version.

## Adaptive agent and governed-improvement requirements

Milestone 5.6 now records two separate future controlled, proposal-only roles:

- The Adaptive Agent Architect analyzes approved goals, scoped data, repeated
  work, versioned workflows, evidence needs, specialist roles, registered
  tools/providers, outputs, approvals, and limits. It proposes immutable
  versioned definitions with roles, frameworks, sources, tools, workflow
  bindings, evidence/testing standards, schemas, escalation, limits,
  prohibitions, and evaluation criteria.
- The Adaptive Training and Evaluation Agent analyzes approved Trace,
  workflow/result/evidence/citation records, human feedback, decisions, scores,
  failures/recovery, reliability, resource/cost use, and later quarantine/
  rehabilitation outcomes. It identifies one supported weakness and proposes a
  new immutable agent or workflow version.

Neither role may activate, approve, or promote its own work; grant capability
or data access; install unreviewed tools; expand authority or limits; weaken
policy/security/approval; cross private scopes; conceal sources, conflict,
risk, or adverse evaluation; destroy old versions; create unrestricted
descendants; or autonomously train model weights. Mobius validates proposals
against registered capabilities, tools, providers, exact scopes, permissions,
policies, approvals, resources, and costs. Human approval controls activation
and promotion.

Governed improvement collects approved evidence, identifies one supported
weakness, proposes an immutable candidate, evaluates it in isolation against
fixed cases, and compares grounding, citation/task accuracy, security,
authority, reliability, latency, and cost. Any regression in security, scope,
provenance, reliability, or approval requirements rejects the candidate. Only
the human-approved version activates; the earlier version remains available
for audit, comparison, and rollback.

Initial training means governed changes to frameworks, instructions, retrieval,
workflows, tools, schemas, limits, and evaluation cases. Model-weight training
is deferred. Future fine-tuning requires licensed approved data, privacy and
scope review, dataset/model versioning, held-out security/grounding evaluation,
human promotion, monitoring, and rollback.

The 5.7 audit must prove: traceable workflow completion; approved feedback or
score; supported weakness identification; immutable candidate creation;
fixed-case old/new comparison; preserved security, permissions, grounding,
provenance, reliability, and cost controls; human promotion; approved
activation; reconstructable/reversible prior version; and the safe complete
source → workflow → agent → evaluation → promotion Trace chain.

## English Expert, evidence-bundle, and APA requirements

Milestone 5.6 now records the future controlled **Adaptive English
Communication Expert**. It improves grammar, clarity, concision, tone, reading
level, terminology, and audience fit while preserving supported facts,
citations, technical meaning, uncertainty, limits, and safety warnings.

It learns only from approved corrections, rewrite decisions, user-controlled
profiles, organization guides, glossaries, audience requirements, examples,
human feedback, evaluations, and immutable prior frameworks/Trace. It may
propose immutable writing-framework, instruction, terminology, tone/
reading-level, template, editing-workflow, and evaluation-case versions, but
cannot silently change factual content, invent information, cross private
scope, universalize one user’s style, deceptively imitate a person,
self-promote, alter active agents without approval, or autonomously train model
weights.

Communication profiles may control tone, formality, reading level, sentence
length, technical detail, terminology, prohibited phrases, organization style,
and optional writing rules. George Orwell’s six prose rules are an optional
profile only. Grounded revisions trace original text, sources/evidence,
workflow/agent versions, requested profile, edits, decisions, and approvals.

The governed English process identifies audience/tone/reading level, proposes
a fact-preserving revision, marks material edits, evaluates language and fact/
citation preservation, collects human feedback, proposes a new immutable
framework only on repeated evidence, compares fixed cases, requires human
promotion, and retains prior/rejected evidence for rollback.

The future **Trace Evidence Bundle** is an immutable, authority-filtered ZIP
containing the exact evidence used by a grounded answer, workflow/agent result,
evaluation, or training proposal. It distinguishes selected, retrieved,
included, excluded, conflicting, insufficient, full-source-authorized, and
referenced-but-not-exportable evidence.

The practical package contains `README.md`, `manifest.json`,
`trace-report.md`, `references.md`, `citations.json`, exact `excerpts/`,
optional authorized immutable `authorized-sources/`, and deterministic
`integrity/sha256sums.txt`. The manifest records safe scope/result identities,
every file/hash, source authority/status/version, Trace/audit references, and
redaction/omission reasons. ZIP paths are deterministic, unique, traversal-
safe, and size-bounded.

APA 7 is the initial human-readable citation style. Parenthetical, narrative,
direct-quotation, and References formatting uses only authoritative metadata;
missing author/date/publisher/URL data is never invented. Private sources never
leak internal locations. Presentation always retains canonical source/version/
hash/locator/export-authority mapping through `citations.json`,
`manifest.json`, and Trace.

Checkpoint responsibilities are now:

- 5.2 defines future-compatible evidence-bundle lifecycle/access/denial and
  citation-rendering success/failure event semantics without implementing them
  in this amendment.
- 5.3 builds authorized bundles, excerpts/full-source selection, APA rendering,
  citation mapping, manifests, SHA-256 integrity, redaction, and safe
  references.
- 5.4 attaches bundles to supported workflow results and each step’s evidence.
- 5.5 provides authority-aware evidence, citation, References, and download
  controls.
- 5.6 attaches bundles/citations to agent executions, evaluations, candidate
  comparisons, training proposals, and applicable English revisions.
- 5.7 proves real sources, authoritative/non-fabricated metadata, exact quotes/
  locators, export authority, safe ZIP paths, matching hashes, distinct
  evidence classes, Trace reconstruction, durable source versions, and
  fact-preserving English improvement.

## Future Milestone 9 scope recorded

Milestone 5.6 establishes only foundations. The complete **SolarPlexus Academy
and Adaptive Training System** remains Milestone 9 scope: domain schools,
specialist departments, versioned courses, approved lessons and datasets,
fixed examinations, trainer/mentor/student/evaluator identities and lineage,
Trace-backed transcripts, version-specific certifications, remedial training,
controlled skill transfer, candidate comparisons, human graduation and
activation, retraining, suspension, quarantine, rehabilitation, retirement,
replacement, and rollback.

The future Academy includes the **School of Language, Communication, and
Explanation**, with possible departments for Plain English, Technical Writing,
Academic Writing, Professional Communication, Instruction and Teaching,
Documentation, Editing and Quality Review, and Audience and Accessibility
Adaptation.

Academy records retain exact source/course/case/agent/trainer/evaluator/result/
feedback/promotion/capability/lifecycle provenance. The Academy may teach,
evaluate, compare, certify, recommend, and propose retraining or rehabilitation
but cannot activate, promote, grant authority, release quarantine, cross
private scope, hide failure, weaken controls, create unrestricted descendants,
or autonomously train model weights.

The future **Agent Justice, Quarantine, and Rehabilitation System** contains
the Agent Quarantine Center, Agent Rehabilitation Center, and Agent Review
Tribunal. It is a server-authoritative technical isolation and human-review
system; “jail” is only an optional visual metaphor, never personhood or
punishment. Evidence—not unsupported agent claims—controls eligibility.
Quarantine may stop jobs, fence leases/grants/delegation/travel/access, preserve
all required state and evidence, and notify authorized humans. Rehabilitation
reproduces and diagnoses failure, proposes and tests a corrected immutable
version, requires human release approval, restores minimum authority, and
preserves the prior version. The Tribunal controls review, appeal, release,
restriction, retraining, replacement, continued isolation, retirement,
archival, and legally permitted deletion with required audit retention.

Every case retains trigger → evidence → quarantine decision → investigation →
plan → evaluation → human decision → outcome.

> Agents may detect, classify, and report unsafe behavior, but only
> server-enforced policy and authorized humans may quarantine, restrict,
> restore, release, replace, or retire an agent.

Academy, quarantine, rehabilitation, and tribunal systems are not Milestone 5.7
implementation requirements. No such production system exists in this
checkpoint.

## 5.2 completion evidence

- Closed versioned registry: 12 existing-feature event contracts and 8
  non-emittable evidence-bundle/citation contracts.
- Immutable event, provenance, delivery-attempt, and activity evidence.
- Transactional event/outbox integration for graph mutations, approved
  effects, and rollback results.
- Server-derived scope, identity, digest, sequence, timing, attempts, retry,
  ownership, and safe failure classification.
- Bounded lease/generation fencing, retry, delivery, and terminal handling.
- Idempotent deterministic internal activity projection; no autonomous
  event-triggered agents.
- Authenticated, scope-checked, bounded, allowlist event/activity/status APIs.
- Migration and sole head: `20260725_0017`.
- SQLite migration cycle and append-only triggers validated; deterministic
  local contention validated with SQLite’s coarse-lock limitation recorded.
- PostgreSQL DDL compiles offline; runtime locking is not claimed.
- Handoff:
  [`MILESTONE_5_2_LIVING_STATE_EVENT_HANDOFF.md`](MILESTONE_5_2_LIVING_STATE_EVENT_HANDOFF.md).

## 5.3 completion evidence

- Selected canonical objects are an exact allowlist; graph connectivity never
  broadens authority.
- Closed versioned traversal, outcome, decision-reason, citation, APA, and
  evidence-bundle registries.
- Deterministic bounded traversal over all eight completed graph relationship
  kinds with direction enforcement, cycle termination, stable ranking, graph
  revision capture, and source-version retention.
- Immutable retrieval runs, inclusion/exclusion evidence, exact citations,
  hashes, locators, relationship paths, and Trace linkage.
- Distinct supported, conflicting, insufficient-evidence, and bounded-result
  outcomes; insufficient evidence creates no citations.
- Deterministic APA 7 output using only authoritative repository metadata.
- Deterministic ZIP evidence bundle with exact excerpts, manifest, citation
  map, References, Trace report, and SHA-256 verification.
- Full-source export fails closed and records `export_not_authorized`.
- All eight evidence-bundle/citation event contracts are now emittable through
  real producers with transactional outbox evidence.
- Duplicate replay and independent-session SQLite contention converge on one
  authoritative retrieval and citation without partial evidence.
- Migration and sole head: `20260725_0018`.
- No external search, autonomous agent/workflow trigger, frontend, workflow,
  Agent Studio, Academy, English, quarantine, rehabilitation, or tribunal code.
- Handoff:
  [`MILESTONE_5_3_GRAPH_AWARE_RETRIEVAL_HANDOFF.md`](MILESTONE_5_3_GRAPH_AWARE_RETRIEVAL_HANDOFF.md).

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

| Placeholder     | Scope                                                   |
| --------------- | ------------------------------------------------------- |
| `20260725_0016` | Complete: graph state, bindings, relationship evidence  |
| `20260725_0017` | Complete: events/outbox, sequences, activity projection |
| `20260725_0018` | Complete: retrieval, citations, evidence bundles        |
| `2026xxxx_0019` | Workflow versions/runs/transitions/compensation         |
| `2026xxxx_0020` | Viewport tiles and summaries                            |
| `2026xxxx_0021` | Agent versions, feedback, evaluations, promotion        |

The 5.1–5.3 identifiers are implemented Alembic revisions. Later identifiers
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
  - SolarPlexus Academy and Adaptive Training System
  - Agent Justice, Quarantine, and Rehabilitation System

Next authorized start:
`MILESTONE 5.4 STARTED LOCALLY — CONTROLLED AI WORKFLOWS`
