# Milestone 5 Implementation Plan

Status: architecture and checkpoint 5.1 complete locally; checkpoints 5.2–5.7
pending.

This plan implements
[`MILESTONE_5_ARCHITECTURE.md`](MILESTONE_5_ARCHITECTURE.md) sequentially.
Every checkpoint starts from the preceding clean local commit, extends existing
patterns, preserves all Milestone 4 contracts, and uses additive,
resumably-backfillable migrations. SQLite remains the correctness baseline;
PostgreSQL-specific concurrency and plans require marked tests. No event,
projection, client, workflow, import, or AI output may grant authority.

Permanent product loop:

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

Dependencies: 5.2 requires 5.1; 5.3 requires 5.1–5.2; 5.4 requires 5.1–5.3
and Milestone 4; 5.5 may begin after 5.1 but requires 5.2/5.4 to complete; 5.6
requires 5.4; 5.7 requires 5.1–5.6.

## 5.1 — Knowledge Graph Foundation

Status: complete locally.

Start: `MILESTONE 5.1 STARTED LOCALLY — KNOWLEDGE GRAPH FOUNDATION`

Complete: `MILESTONE 5.1 COMPLETE LOCALLY — READY FOR LIVING STATE AND EVENT SYSTEM`

Model/reasoning: `gpt-5.6-sol`, xhigh.

Deliver canonical type extensions, graph revision, temporal canvas bindings,
relationship assertions, graph services/APIs, and reviewed graph resource/
capability contracts. Preserve visual edges.

Migration `20260725_0016`: additive graph types/subtypes, graph state,
bindings, and relationship evidence. Backfill only deterministic facts, record
origin, infer no visual-edge semantics, and retain legacy tables.

Gate: mapper/constraint/index tests; concurrent/stale revisions; duplicates;
cross-workspace failures; tombstone provenance; empty/legacy and
upgrade/downgrade/re-upgrade/resumed-backfill cycles; PostgreSQL lock and
uniqueness tests.

Implemented with passing SQLite, API, authority, integrity, idempotency,
separate-session competition, failure-injection, migration, mapper, typing,
lint, formatting, compilation, and complete non-PostgreSQL backend validation.
PostgreSQL runtime validation remains pending because no configured runtime was
available. See
[`MILESTONE_5_1_KNOWLEDGE_GRAPH_HANDOFF.md`](MILESTONE_5_1_KNOWLEDGE_GRAPH_HANDOFF.md).

## 5.2 — Living State and Event System

Start: `MILESTONE 5.2 STARTED LOCALLY — LIVING STATE AND EVENT SYSTEM`

Complete: `MILESTONE 5.2 COMPLETE LOCALLY — READY FOR GRAPH-AWARE RETRIEVAL`

Model/reasoning: `gpt-5.6-sol`, xhigh.

Deliver transactional events/outbox, workspace sequences, post-commit
dispatch, checkpoints/replay, projections, poison-event handling, retries,
stale-claim fencing, and observability. Preserve event/audit/Trace separation.

Migration `2026xxxx_0017`: events, outbox evidence, sequences, checkpoints, and
initial projections. Seed only reconstructable facts.

Gate: mutation/event/Trace atomicity; rollback has no event; duplicate delivery
applies once; deterministic replay; safe gap handling; stale projector fencing;
events cannot grant/start execution; PostgreSQL outbox/sequence concurrency.

## 5.3 — Graph-Aware Retrieval

Start: `MILESTONE 5.3 STARTED LOCALLY — GRAPH-AWARE RETRIEVAL`

Complete: `MILESTONE 5.3 COMPLETE LOCALLY — READY FOR CONTROLLED AI WORKFLOWS`

Model/reasoning: `gpt-5.6-sol`, xhigh.

Deliver connected-context opt-in, closed traversal, immutable resolved
path/context, deterministic graph/vector ranking, exact citations, conflict
handling, and insufficient-evidence results by extending grounded drafts.

Migration `2026xxxx_0018`: graph-context/path evidence and traversal indexes.

Gate: exact roots and all budgets/allowlists; scope/lifecycle/version/evidence
checks; revoked/altered/missing/stale/cross-scope failures; deterministic
ranking/path/citations; conflicts; cancellation/deadline/lease/stale result;
seeded query and latency bounds.

Trace acceptance: selected context; relationships traversed; retrieved
passages; citations; inclusion and exclusion decisions; conflicts;
insufficient-evidence outcomes; and traversal and context-budget limits.

## 5.4 — Controlled AI Workflows

Start: `MILESTONE 5.4 STARTED LOCALLY — CONTROLLED AI WORKFLOWS`

Complete: `MILESTONE 5.4 COMPLETE LOCALLY — READY FOR DYNAMIC UNIVERSE INTERFACE`

Model/reasoning: `gpt-5.6-sol`, max.

Deliver immutable definitions/digests, closed DAG steps/branches, user-started
runs, append-only transitions, one Milestone 4 execution per executable step,
authority intersection/revalidation, layered idempotency, bounded failure, and
immutable saga compensation.

Migration `2026xxxx_0019`: definitions, versions, steps, branches, runs,
transitions, M4 bindings, and compensation plans/items.

Gate: digest/cycle/limit validation; exact version binding; typed branches;
duplicate start/resume/step/result/compensation; retry succeeds once; stale,
canceled, or expired workers cannot commit; invalid authority fails closed;
compensation order/approval/conflict/partial state; no partial success evidence
after transaction failure.

Trace acceptance: workflow identity and version; approved inputs; every step
and outcome; models, tools, and APIs used; evidence and outputs; approvals;
retries, recovery, and cancellation; proposed and completed mutations;
compensation or rollback; and the final result.

## 5.5 — Dynamic Universe Interface

Start: `MILESTONE 5.5 STARTED LOCALLY — DYNAMIC UNIVERSE INTERFACE`

Complete: `MILESTONE 5.5 COMPLETE LOCALLY — READY FOR BOUNDED AGENT STUDIO`

Model/reasoning: `gpt-5.6-terra`, high, plus `gpt-5.6-sol` xhigh security/data
contract review.

Deliver viewport/boundary/selection/activity/workflow/MiniMap APIs, portable
tiling, normalized cache, visible rendering, prefetch/eviction with pinned
selection, editing/conflict preservation, and accessible navigation/status.

Migration `2026xxxx_0020`: layout tiles, summaries, portable indexes. Optional
PostgreSQL spatial indexes require measured proof.

Gate: stable revision cursors; no duplicates/omissions; boundary/off-screen
selection; cache bounds; no full-snapshot regression; projection lag; keyboard,
screen reader, focus, contrast, motion; browser smoke/build; large-workspace
budgets.

## 5.6 — Bounded Agent Studio

Start: `MILESTONE 5.6 STARTED LOCALLY — BOUNDED AGENT STUDIO`

Complete: `MILESTONE 5.6 COMPLETE LOCALLY — READY FOR FINAL COMBINED AUDIT`

Model/reasoning: `gpt-5.6-sol`, xhigh.

Deliver template/agent identities, immutable versions/digests, proposal
evidence, activation, declarative bounds, and effective-authority review.
Runtime authority remains Milestone 4. Prohibit delegation, descendants,
arbitrary code/tools/connectors, agent-initiated creation, and policy changes.

The future controlled Adaptive Agent Architect may analyze approved user goals,
selected/scoped data structures, repeated questions and tasks, versioned
workflows, evidence requirements, specialist-role needs, registered tools and
providers, required outputs, approval points, and time/token/cost/retry limits.
It may propose an immutable versioned definition containing purpose/role,
operating framework, specialist perspectives, approved sources, proposed
tools/providers, workflow bindings, evidence/testing standards, output schema,
escalation rules, recommended limits, prohibited actions, and evaluation
criteria.

The Architect cannot self-activate or self-approve, grant capabilities, assign
private data, install tools, choose unrestricted authority, increase budgets or
limits, bypass policy validation, create unrestricted descendants, or hide
inherited instructions, sources, conflicts, or risks. Mobius validates every
proposal against registered capabilities, tools, providers, exact user/
workspace/canvas scopes, data permissions, policies, approvals, resources, and
cost limits. Human approval is required before activation.

The separate future controlled Adaptive Training and Evaluation Agent may
analyze approved execution Trace records, workflow outcomes, evidence and
citations, human corrections, approval/rejection decisions, evaluation scores,
retry/failure/cancellation/rollback evidence, reliability and latency,
resource/cost use, grounding/citation quality, and later quarantine/
rehabilitation outcomes. It identifies one supported weakness and may propose a
new immutable agent or workflow version changing instructions/frameworks,
retrieval, workflow steps, tool-selection rules, schemas, evaluation cases,
approval-threshold recommendations, server-controlled limit recommendations,
restrictions, or remedial training.

The Training Agent cannot silently alter active definitions; self-approve or
self-promote; release quarantine; grant capabilities or data; weaken approval,
policy, or security; combine private scopes; treat successful execution as
correctness; delete failed versions or unfavorable evaluations; hide results;
train on unapproved data; create unrestricted descendants; or autonomously
train model weights.

Governed improvement must:

1. collect approved Trace, result, evaluation, and feedback records;
2. identify one evidence-supported weakness;
3. propose a new immutable agent or workflow version;
4. evaluate it in isolation against fixed cases;
5. compare it with the active version across grounding, citation accuracy,
   task accuracy, security, authority boundaries, reliability, latency, and
   cost;
6. reject any candidate weakening security, scope, provenance, reliability, or
   approval requirements;
7. require human promotion approval;
8. activate only that approved version;
9. retain the prior version for audit, comparison, and rollback; and
10. record later failure, retraining, restriction, quarantine, retirement, or
    replacement.

Initial training changes only frameworks, instructions, retrieval, workflows,
tools, schemas, limits, and evaluation cases. Autonomous model-weight training
is deferred. Future fine-tuning additionally requires licensed approved
datasets, privacy and scope review, dataset/model versioning, held-out security
and grounding evaluations, human-controlled promotion, monitoring, and
rollback.

Migration `2026xxxx_0021`: templates, agents, versions, proposals, approved
feedback, fixed evaluation cases, candidate evaluations, promotion, and
activation.

Gate: schemas/digests/immutability; malicious data confinement; no
self-activation/standing grant; strict runtime authority intersection;
revocation/replacement/stale/prohibited capability; isolated fixed-case
candidate comparison; feedback/evaluation provenance; human-controlled
promotion; prior-version reconstruction/rollback; accessible browser smoke.

Trace acceptance: source framework; workflow or job being served; proposed
specialist roles; approved sources and tools; capabilities and limits; creator
and approver; provider and model; validation and activation; and revisions,
executions, suspension, retirement, and replacement. Later Milestone 9 records
extend this chain with quarantine and rehabilitation.

## 5.7 — Final Combined Milestone 5 Audit

Start: `MILESTONE 5.7 STARTED LOCALLY — FINAL COMBINED MILESTONE 5 AUDIT`

Complete: `MILESTONE 5.7 COMPLETE LOCALLY — READY FOR MILESTONE 6 ARCHITECTURE`

Model/reasoning: `gpt-5.6-sol`, max.

Audit 5.1–5.6 together and fix only proved defects. Run affected backend and
frontend suites; controlled exact-citation/effect/rollback scenarios; retry,
recovery, stale, cancel, deadline, and invalid-authority cases; failure
injection; event replay; migration cycles; concurrency; PostgreSQL-marked
tests; browser/accessibility; typing, lint, formatting, build, mappers,
compilation, imports, hygiene, secrets, whitespace, diff, and prohibited scope.

The combined acceptance scenario must prove:

approved data
→ canonical graph and provenance
→ grounded question and citations
→ versioned workflow
→ adaptive agent proposal
→ validation and human activation
→ governed execution
→ traceable result

It must also prove:

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
10. The safe Trace chain preserves source → workflow → agent → evaluation →
    promotion.

Academy, quarantine, rehabilitation, and tribunal systems remain future
Milestone 9 scope and are not 5.7 implementation requirements.

Create the completion document only after the combined gates pass. Milestone 6
still requires explicit authorization.

## Future Milestone 9 — Academy and agent review systems

Milestone 5.6 establishes only immutable agent/workflow versions, approved
feedback/evaluations, fixed cases, isolated candidate testing, proposal-only
Architect and Training Agent roles, human-controlled promotion, and rollback.
Milestone 9 expands them into the SolarPlexus Academy and Adaptive Training
System with domain schools, specialist departments, versioned courses,
approved lessons/frameworks/examples/tools/procedures, examinations, trainer/
mentor/student/evaluator identities, lineage, approved programs/datasets,
Trace-backed transcripts, version-specific certifications, remedial training,
controlled skill transfer, candidate comparisons, human graduation/
activation, retraining, suspension, quarantine, rehabilitation, retirement,
replacement, and rollback.

Academy records trace sources, course/framework versions, cases, student-agent
version, trainers/evaluators, results/feedback, promotion/rejection,
post-graduation capabilities, and later adverse lifecycle outcomes. The Academy
may teach, evaluate, compare, certify, recommend, and propose retraining or
rehabilitation. It cannot activate/promote itself, grant authority, release
quarantine, cross private scopes, silently rewrite definitions, hide failure,
weaken security/approval, infer correctness from repetition, create
unrestricted descendants, or autonomously train model weights.

Milestone 9 also owns the **Agent Justice, Quarantine, and Rehabilitation
System**, composed of the Agent Quarantine Center, Agent Rehabilitation Center,
and Agent Review Tribunal. “Jail” is only an optional UI metaphor for isolating
unsafe software behavior, never punishment or personhood.

Evidence-supported quarantine eligibility includes unauthorized action,
repeated policy/scope violation, unsafe/corrupted/materially unreliable output,
identity/version/signature/integrity failure, revoked dependency use, behavior
drift, repeated resource-limit violations, poisoned-data instructions, failed
required Academy evaluation/certification, and hidden delegation or authority
expansion. Server-authoritative quarantine can stop work, fence leases, revoke
temporary grants, block delegation/cross-planet travel, isolate ordinary
workspace access, preserve required configuration/memory references/versions/
Trace/evidence, prevent evidence destruction, and notify authorized humans.

Rehabilitation reproduces and diagnoses the supported failure in isolation,
proposes corrective training and a new immutable version, evaluates and
compares it, requires authorized human release approval, restores only minimum
approved capabilities, and preserves the old version. The human-controlled
Tribunal reviews evidence, findings, evaluations, plans, recommendations,
appeals, and retirement. Outcomes include release, restricted release,
remedial Academy training, retraining, replacement, continued suspension or
quarantine, retirement, archival, and legally/technically permitted deletion
that preserves required audit evidence.

Every case traces trigger → evidence → quarantine decision → investigation →
rehabilitation/training plan → evaluation → human decision → release,
restriction, replacement, retirement, or continued quarantine. Unsupported
agent claims alone can never justify quarantine, restriction, restoration, or
retirement.

> Agents may detect, classify, and report unsafe behavior, but only
> server-enforced policy and authorized humans may quarantine, restrict,
> restore, release, replace, or retire an agent.

The system cannot let agents punish, release, or retire one another; erase
adverse evidence; rewrite Trace history; grant authority through
rehabilitation; combine private evidence across scopes; quarantine indefinitely
without review rules; release without evaluation and human approval; or erase
the truth of original behavior. These are documentation and future acceptance
criteria only.

## Deferred

- 6. Multi-Workspace Collaboration
  - Nested and Federated Mobius Workspaces
- 7. Production Hardening
- 8. Public Portfolio and Product Release
- 9. SolarPlexus Agent Ecosystem
  - SolarPlexus Academy and Adaptive Training System
  - Agent Justice, Quarantine, and Rehabilitation System
