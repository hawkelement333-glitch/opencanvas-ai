# Milestone 5.5 Dynamic Universe Interface Handoff

Date: 2026-07-25

Branch: `milestone-5-living-knowledge-workflows-architecture-local`

Starting commit: `5a210c821ce41b9b8f32a0adba6f7aae25d3c518`

Status: complete locally; Milestone 5 remains incomplete.

## Outcome

Milestone 5.5 adds a bounded, evidence-aware Dynamic Universe over the
authoritative Milestone 4 and Milestone 5.1–5.4 system. It visualizes approved
resources, relationships, selected context, retrieval evidence, citations,
controlled workflows, approvals, retries, effects, compensation, activity,
Trace, and Evidence Bundles. It does not become an authority source.

The permanent product and Trace contracts remain unchanged:

Approved data
→ grounded answers
→ traceable workflows
→ adaptive agent proposals
→ governed agents
→ traceable results
→ evaluated feedback
→ governed agent improvement

Trace is auditable provenance and execution evidence, not private model chain
of thought.

## Information architecture

The dedicated `/universe` route separates:

1. the scoped workspace and active canvas region;
2. a bounded spatial resource and relationship view;
3. the explicit selected-context boundary;
4. retrieval decisions, citations, APA 7, and source inspection;
5. the immutable controlled-workflow DAG and execution state;
6. the bounded chronological activity projection;
7. safe Trace facts and scoped Trace navigation; and
8. authority-filtered Evidence Bundle status and download controls.

The inspector presents facts and governed actions beside the spatial or
chronological view. Loading, empty, error, inaccessible, stale, historical, and
bounded states are explicit.

## Renderer and layout

The implementation reuses `@xyflow/react` 12.11.2. React Flow renders DOM/SVG,
so Three.js and WebGL are neither dependencies nor requirements. There is no
duplicate React runtime, Three.js runtime, state framework, graph model, API
client, animation loop, or WebGL context.

Canonical canvas resources use authoritative saved coordinates. Workflow steps
use a deterministic presentation-only layout:

- dependency depth selects the column;
- stable step-key ordering selects the row;
- immutable dependencies create directed edges; and
- cycles in malformed presentation input fail safely without recursive
  failure.

The workflow renderer is read-only. Dragging and connection creation are
disabled, and no layout change can mutate an immutable workflow version.
React component unmount owns SVG, listener, and renderer cleanup.

## Viewport and loading bounds

`GET /canvases/{canvas_id}/universe-viewport` is an authenticated, owned-canvas
read surface. It accepts coordinate bounds, a UUID keyset cursor, an expected
canvas revision, and at most 50 selection identifiers. Each response is capped
at:

- 200 visible nodes;
- 500 incident edges;
- boundary stubs for connected off-screen resources; and
- 50 hydrated selected resources.

It returns canvas revision, workspace graph revision, a continuation cursor,
and an explicit bounded flag. Continuation sends the first page's canvas
revision. A concurrent mutation returns `viewport_revision_conflict`; the
client refreshes rather than combining different revisions.

The Dynamic Universe does not call the legacy whole-canvas snapshot route.
React Query keys include workspace, canvas, and selection scope. Obsolete
requests use abort signals. Activity is loaded 30 events at a time and
deduplicated by immutable event identity before deterministic newest-first
ordering. Relationship reads are focused-resource-only and capped at 100.

Existing float coordinates and indexes were sufficient for this measured local
bounded route. No persistent tile, summary, or spatial-index state was added.
Portable tiling, a server MiniMap summary, measured neighbor prefetch, and
bounded LRU eviction remain later performance evolutions if production
workspace measurements justify their integrity and invalidation costs.

## Nodes and relationships

The presentation covers existing repository-supported equivalents of:

- document, note, and grounded response resources;
- canonical document, note, and controlled execution identities;
- retrieval, citation, workflow execution, workflow step, approval, effect,
  rollback, compensation, Evidence Bundle, and activity records in their
  relevant views.

No backend entity kind was added for presentation, and no agent node exists.

The closed knowledge relationship registry is rendered with text labels and
direction metadata:

- `references`;
- `derived_from`;
- `related_to`;
- `cites`;
- `supports`;
- `contradicts`;
- `produced_by`; and
- `affected_by`.

Forward relationships show direction. Bidirectional `related_to` and
`contradicts` are labeled as such. Inactive, superseded, and rejected records
are historical and never presented as active. Unknown relationship kinds and
self-links fail schema validation instead of receiving invented semantics.
Color supplements labels, line treatment, state text, and inspector facts.

## Selected-context contract

Selection remains explicit and capped at 50. The interface distinguishes:

- selected resources;
- eligible but unselected resources;
- boundary or unavailable canonical resources;
- retrieval-included and retrieval-excluded candidates; and
- historical relationships.

Graph adjacency and visual proximity never select a resource. Double-click is
only a presentation shortcut for an eligible loaded canvas resource; the
accessible list provides the same add/remove operation with `aria-pressed`,
keyboard activation, count, and limit enforcement. A deep-linked workflow
shows its immutable approved selected object identifiers until the user
explicitly changes local review state.

The interface does not start a retrieval or workflow automatically when
selection changes.

## Retrieval, citation, and source evidence

The UI displays server-authored retrieval facts without recalculation:

- selected and seed identities;
- graph revision and algorithm version;
- supported, conflicting, insufficient-evidence, and bounded outcomes;
- included and excluded candidates;
- closed reason codes, graph distance, rank, score, and relationship path
  length;
- exact citations, immutable source and canonical versions;
- exact excerpt and locator;
- source and excerpt hashes;
- relationship paths and Trace linkage; and
- bounded-result warnings.

Selecting a citation focuses its canonical source identity in the spatial view,
loads only scoped relationships, highlights the presentation node, and opens
the exact authorized excerpt and locator in the inspector. Private storage
paths, local paths, fabricated metadata, and public URLs are never rendered.
APA 7 rendering uses the established authenticated endpoint and reports absent
citations honestly.

## Controlled workflows and governed actions

The workflow view renders the server-owned execution and deterministic DAG:

- definition, immutable version, plan digest, graph revision, and deadline;
- exact dependencies;
- pending, blocked, ready, claimed/running, awaiting-approval, retry-waiting,
  succeeded, failed, canceled, compensating, compensated,
  compensation-failed, and skipped step states;
- attempt count and bound;
- safe capability and risk class;
- requested action and affected resource where available;
- retrieval, Evidence Bundle, controlled execution, effect, rollback, and safe
  failure linkage; and
- final server-authored outcome.

The response-only backend extension exposes dependencies, capability, risk
class, requested action, and affected resource from the immutable workflow
definition. It exposes no grant, lease, worker, credential, policy decision, or
private reasoning.

Approve and deny are separate. Both require a modal confirmation that states
the exact workflow, step, action, resource, risk, and execution deadline.
Submission controls disable while pending, carry existing CSRF protection, and
send only the closed decision. A stale, revoked, expired, altered, missing, or
cross-scope approval remains a server error and triggers authoritative
refresh.

Cancellation also requires confirmation. The explanation states that completed
evidence, Trace, audit, events, model calls, and committed effects remain, and
that predefined compensation has its own approval and may visibly fail. The UI
does not claim that rollback erases history.

## Activity, Trace, and Evidence Bundles

Canvas activity uses the Milestone 5.2 projection with 30-row bounded pages.
Immutable event IDs suppress duplicate delivery in the client, while sequence
and event ID produce deterministic newest-first order. The UI shows safe scope,
subject kind, subject identity, timestamp, projection/delivery status, graph
revision when present, and Trace linkage without worker or lease details.

The Trace inspector uses the Milestone 5.3 safe summary and authenticated scoped
Trace route. It shows event types, statuses, graph/workflow linkage, and safe
metadata. It never asks for or displays private chain of thought, hidden
reasoning tokens, secret prompts, raw policy reasoning, or raw grants.

Evidence Bundle generation requests excerpt-only authority. Status and hash
come from the server. Download is a CSRF-protected POST; the client accepts
only ZIP or octet-stream content, rejects declared or actual payloads over
100 MB, creates a temporary local object URL, and promptly revokes it. No
public URL or local storage path is generated. Denied full-source authority
does not invalidate the excerpt bundle contract.

## Accessibility and responsive behavior

The interface provides:

- landmarks, headings, live loading/status text, and safe alerts;
- accessible names and text lifecycle/relationship meanings;
- a keyboard-operable selected-resource list;
- visible focus and `aria-pressed` selected state;
- native modal dialog focus containment, Escape handling, and focus
  restoration behavior;
- no pointer-only governed action;
- icon plus text status, never color alone;
- `prefers-reduced-motion` suppression for transitions and animated edges;
- an accessible spatial summary and MiniMap label; and
- a stacked mobile inspection layout retaining context, evidence, workflow,
  approval, cancellation, activity, Trace, and bundle controls.

Automated and deterministic browser checks support these claims; they are not
a complete accessibility certification or physical-device matrix.

## Security and state boundaries

Authoritative server state remains in React Query. Local state is limited to
view selection, search, focused records, active panel, dialog state, and
notifications. No client code derives authority, retrieval outcomes, workflow
completion, effect success, compensation success, or export permission.

All reads use exact workspace/canvas scopes. Mutations reuse credentials and
CSRF headers. Non-idempotent governed actions are not automatically retried.
Response schemas are closed and reject unknown lifecycle/relationship values.
React escapes all displayed text; no raw HTML, unsafe Markdown, SVG payload,
provider response body, SQL, stack trace, local path, or arbitrary URL is
rendered.

Scope changes produce distinct query keys. Aborted requests cannot replace the
new scope. Direct navigation and refresh resolve the requested workspace and
canvas only if they appear in the authenticated owned lists; otherwise the
route falls back to an owned scope and scoped APIs continue to fail closed.

## Backend and migration state

Backend production changes were limited to:

1. the bounded, read-only universe viewport response and route; and
2. safe workflow step presentation fields derived from existing immutable
   workflow rows.

No persistence model or migration changed. Alembic retains sole head
`20260725_0019`.

SQLite provided deterministic local API, concurrency-boundary, and migration
testing. PostgreSQL DDL/runtime behavior was not changed; no PostgreSQL runtime
was available or claimed for this checkpoint. No external AI provider,
external network feature, managed object storage, Azure service, deployment,
or publication was used.

## Validation evidence

The final validation run records exact results in the closing commit and final
handoff report. It includes:

- focused and full frontend unit/component tests;
- affected canvas, authorization, graph, activity, retrieval/citation/APA/
  bundle, and controlled-workflow backend suites;
- TypeScript, ESLint, Prettier, Ruff, MyPy, Python compilation, and imports;
- optimized Next.js production build including dynamic `/universe`;
- deterministic Chromium direct navigation, refresh, keyboard context,
  evidence, workflow, console, asset/hydration, and 390px layout checks;
- migration cycling and sole-head validation;
- repository hygiene, secret/local-path/prohibited-scope/whitespace scans;
- Git object and protected-ref audits.

Local browser and bounded dataset checks do not establish broad production
capacity, physical-device compatibility, complete accessibility
certification, or complete security assurance.

## Explicit deferred scope

Milestone 5.6 was not started. This checkpoint adds no Agent Studio, agent
definition, agent creation/activation, Adaptive Agent Architect, Adaptive
Training and Evaluation Agent, Adaptive English Communication Expert,
autonomous workflow trigger, schedule, recurring workflow, webhook, Academy,
School of Language/Communication/Explanation, agent improvement/promotion,
quarantine, rehabilitation, Tribunal, Agent Society, cross-workspace
collaboration, federation, public release, or Milestone 9 production behavior.

All prior Adaptive Agent, Training, governed improvement, English, Evidence
Bundle, APA, Academy, quarantine, rehabilitation, Tribunal, and Milestone 9
requirements remain preserved as future acceptance criteria.

## Git and remote boundary

Work remains local on
`milestone-5-living-knowledge-workflows-architecture-local`. No push, pull,
fetch, sync, upstream, pull request, remote branch/tag change, upload,
publication, deployment, or release occurred. `main`, the Milestone 4
checkpoint, `competition-demo-v1`, protected tags, branches, history, and
completed Milestone 5.1–5.4 commits remain preserved.
