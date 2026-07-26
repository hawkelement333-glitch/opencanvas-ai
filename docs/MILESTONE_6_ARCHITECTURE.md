# Milestone 6 Architecture — Core Multi-Workspace Collaboration

Date: 2026-07-25

Branch: `milestone-6-multi-workspace-collaboration-architecture-local`

Architecture baseline: `01a38526320560d54033bed510b0f15a7e77eea7`

Status: architecture complete locally; checkpoint 6.1 complete locally

Next checkpoint: 6.2 — Collaboration Roles and Permission Authority

Implementation record: checkpoint 6.1 realizes the approved membership and
invitation foundation at sole Alembic head `20260725_0021`. It does not alter
the remaining architecture or begin generalized collaboration authority.

## 1. Purpose

Milestone 6 makes SolarPlexus Mobius usable by bounded teams without weakening
the completed Milestone 4 controlled-agent authority boundary or the completed
Milestone 5 graph, retrieval, workflow, event, Trace, Dynamic Universe, and
Agent Studio contracts.

The architecture answers:

- who belongs to a workspace;
- how a person is invited and accepts;
- which one closed role a membership holds;
- which resources that membership may see, edit, share, or invoke;
- who may transfer ownership or review an approval;
- how access changes fence pending and running work;
- how shared workflows and agents retain exact authority; and
- how every database, service, API, worker, event, Trace, and frontend path
  remains isolated by tenant.

Milestone 6 architecture is documentation and planning only. No collaboration
model, migration, service, route, event, test, component, dependency, or
configuration exists as a result of this pass.

## 2. Repository constraints and foundations

The design extends these existing contracts:

- `Principal` derives the authenticated user from a database-backed session.
  Session tokens and CSRF secrets are hashed; state-changing browser requests
  require CSRF.
- `Workspace.owner_id` is the current owner-only authorization source.
  `require_owned_workspace`, `require_owned_canvas`, route dependencies, and
  service `_scope` or `_authorize_operation` methods provide replacement
  seams.
- Canvas, canonical graph, retrieval, workflow, Agent Studio, controlled-agent
  execution, Trace, event, outbox, and activity records already retain opaque
  user/workspace/canvas/resource identities.
- Milestone 4 policy binds exact user, workspace, execution, capability,
  versioned resource, risk, grant, approval, context digest, plan digest,
  expiry, and revocation. Membership cannot replace any of those checks.
- Milestone 5 immutable definitions and evidence use scoped composite
  constraints, append-only state histories, idempotency digests, safe
  serializers, transactional Trace/events, and stale generation fencing.
- Domain events and the transactional outbox are the only durable activity
  source. Activity is a rebuildable projection and never grants authority.
- The frontend uses Next.js, React, the existing authenticated API client,
  TanStack Query, React Flow, scoped query keys, abort signals, and
  authoritative refresh. Milestone 6 adds no second state framework.
- SQLite is the deterministic local database. PostgreSQL runtime isolation,
  row locking, row-level security, and load behavior require explicit
  PostgreSQL tests before production reliance.

The current owner-only `user_id` on historical workflow, agent, event, and
controlled-execution records remains immutable historical scope. Milestone 6
adds normalized membership and reviewer evidence rather than rewriting those
records or reinterpreting their original actor.

## 3. Scope

Required core scope:

- workspace membership and closed lifecycle;
- invitation creation, delivery, acceptance, decline, expiry, revocation, and
  bounded resend;
- closed, versioned roles and collaboration permissions;
- one-role assignment and append-only role changes;
- membership suspension, restoration, and removal;
- workspace and resource ownership plus accepted transfer;
- explicit canvas, canonical resource, workflow, and agent sharing;
- document, note, graph-resource, immutable-version, retrieval, citation,
  Trace, and Evidence Bundle access rules;
- approval-review eligibility composed with Milestone 4 approval;
- fail-closed revocation and active-operation fencing;
- bounded comments, threads, revisions, resolution, and moderation;
- collaboration domain events and bounded activity;
- multi-workspace frontend management;
- tenant-isolation testing and final security audit.

Optional stretch after core completion:

- coarse online status such as `offline`, `recently_active`, or `online`,
  derived from an expiring server session heartbeat.

Basic status is not required by checkpoints 6.1–6.7, grants no authority,
contains no cursor or detailed activity, and cannot delay core completion.

## 4. Non-goals

Milestone 6 does not implement or require:

- Google-Docs-style simultaneous editing;
- live cursors or detailed real-time presence;
- CRDT or operational-transform synchronization;
- offline editing, reconnect merging, or distributed conflict resolution;
- distributed real-time collaboration infrastructure or its load testing;
- cross-workspace workflow or agent bindings;
- federation or nested/federated workspace behavior;
- public or anonymous sharing;
- unrestricted notifications, chat, messaging, or mention delivery;
- arbitrary roles, permissions, grants, tools, plugins, workflows, or agents;
- deterministic production indexing or the Milestone 7 Indexer;
- the Milestone 9 Librarian, Catalog, Academy, marketplace, Agent Justice,
  Quarantine, Rehabilitation, or Tribunal.

## 5. Authority composition

Every authoritative operation evaluates these layers in order:

1. authenticated server-derived `Principal`;
2. active membership in the exact workspace;
3. one closed role under an exact collaboration-policy version;
4. explicit resource visibility, ownership, or narrowly declared inheritance;
5. exact closed collaboration permission;
6. exact user/workspace/canvas/resource and immutable-version scope;
7. Milestone 4 capability and risk classification where applicable;
8. exact unexpired, unrevoked Milestone 4 grant;
9. exact approval plus reviewer eligibility where required;
10. immutable context, plan, request, and version digests;
11. current resource, workflow, agent, execution, membership, and share
    lifecycle;
12. current membership, share, approval-assignment, and workspace revocation
    generations.

Denial at any layer is final. Unknown values, missing evidence, stale
generations, and conflicting policy versions fail closed.

Membership and sharing answer whether a principal may attempt a human product
action. They do not create an agent capability grant. A collaboration role is
a bounded ceiling, not ambient authority. A resource share is a visibility or
collaboration fact, not a controlled-execution grant.

No authority arises from:

- creator identity or resource ownership alone;
- workspace membership or a role name alone;
- sharing alone;
- a graph relationship, visual adjacency, or selected UI state;
- a workflow or agent definition/version;
- a prompt, provider response, model output, evaluation, comment, event,
  activity item, Trace record, or prior success.

## 6. Identity and ownership distinctions

The architecture keeps these identities separate:

| Concept            | Meaning                                                                                        |
| ------------------ | ---------------------------------------------------------------------------------------------- |
| Authenticated user | Account proven by the current server session                                                   |
| Workspace          | Tenant boundary and event-sequence scope                                                       |
| Workspace owner    | Exactly one active membership that controls transfer and high-level administration             |
| Membership         | Stable relationship between one user and one workspace                                         |
| Role               | One closed baseline responsibility assigned to a membership                                    |
| Resource creator   | Immutable actor that first created the resource                                                |
| Resource owner     | Current workspace or active membership responsible for the resource                            |
| Resource manager   | Not a separate core identity; bounded management comes from ownership, role, and share policy  |
| Action authority   | Current effective collaboration permission and, where applicable, Milestone 4 capability/grant |
| Approval authority | Exact reviewer eligibility plus the existing approval policy and record                        |
| Billing owner      | Deferred; never inferred from workspace ownership                                              |

Creator identity never changes. Ownership transfer appends evidence and changes
current responsibility; it never rewrites creator or historical actor fields.
Resource ownership never bypasses risk, capability, grant, approval, selected
context, immutable version, or lifecycle checks.

## 7. Closed role registry

### 7.1 Decision: one role per membership

Each membership has exactly one current role:

- `owner`
- `administrator`
- `editor`
- `approver`
- `member`
- `viewer`

The registry is code-defined, database-constrained, versioned as
`collaboration-policy-v1`, and returned read-only by the API. Role changes are
append-only transitions. There are no user-authored roles and no unrestricted
superuser.

One role avoids ambiguous unions, order-dependent permission merges, and
accidental privilege escalation. Narrow approval assignments and resource
shares cover exceptional responsibilities without creating a second role.

### 7.2 Responsibilities and prohibitions

| Role          | Baseline responsibilities                                                                                                                                           | Explicit prohibitions                                                                                                                     |
| ------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| Owner         | Owns the workspace; initiates workspace transfer; manages administrators and high-level settings; may administer bounded sharing when exact resource policy permits | Cannot bypass capability, risk, approval, selected-context, lifecycle, or revocation rules; has no automatic high-risk approval authority |
| Administrator | Manages bounded memberships, invitations, non-owner roles, resource-sharing administration, moderation, and collaboration activity                                  | Does not own the workspace or resources; cannot assign owner; has no automatic private-content access or universal approval authority     |
| Editor        | May view and edit explicitly accessible canvases/resources and participate in explicitly shared workflows/agents                                                    | Cannot manage ownership, membership, roles, or its own authority; visibility alone does not permit invocation                             |
| Approver      | May review only exact approval classes assigned by closed policy and receives only the evidence required for that review                                            | Does not automatically edit, share, invoke, activate, or administer                                                                       |
| Member        | May participate in explicitly shared resources, comments, workflows, and agents within role and share ceilings                                                      | Has no workspace administration, general sharing, moderation, or approval baseline                                                        |
| Viewer        | May read explicitly shared resources and safe comments/activity where policy permits                                                                                | Cannot edit, comment, share, approve, invoke controlled effects, export sources/bundles, or widen access                                  |

An owner or administrator may receive a narrow approval assignment, but their
role alone never supplies `approval.review`. An approver still needs an exact
assignment or policy match for the action, resource, and risk.

## 8. Closed collaboration-permission registry

The initial registry is separate from `Capability` and contains no free text:

```text
workspace.view
workspace.settings.manage
membership.view
membership.manage
invitation.create
invitation.resend
invitation.revoke
role.assign
ownership.transfer.request
ownership.transfer.accept
ownership.transfer.cancel
canvas.view
canvas.edit
canvas.share
resource.view
resource.edit
resource.share
comment.create
comment.edit_own
comment.resolve
comment.moderate
workflow.view
workflow.edit
workflow.share
workflow.invoke
agent.view
agent.edit
agent.share
agent.activate_request
agent.invoke
approval.review
collaboration_activity.view
trace.view
source.export
evidence_bundle.view
evidence_bundle.export
```

The role registry defines maximum eligibility. Effective permission is:

```text
active identity and membership
AND current role ceiling
AND explicit resource ownership/share/inheritance
AND current lifecycle and revocation generations
AND exact collaboration permission
AND, when applicable, Milestone 4 policy/grant/approval
```

Absence denies. Private-resource restriction overrides parent inheritance.
There are no arbitrary per-user permission strings. Exceptional access uses a
typed share, ownership transfer, or approval assignment.

The following permissions remain insufficient without Milestone 4 authority:

- `workflow.invoke`
- `agent.activate_request`
- `agent.invoke`
- `approval.review`
- `source.export`
- `evidence_bundle.export`
- any edit that is executed as a controlled effect

## 9. Membership and admission lifecycle

### 9.1 Stable membership identity

`WorkspaceMembership` is immutable identity evidence:

- `membership_id`
- `user_id`
- `workspace_id`
- `created_by_user_id`
- optional accepted `invitation_id`
- `created_at`
- `collaboration_policy_version`
- creation Trace/audit references

Current role and lifecycle are derived from append-only ordered transitions,
not mutable identity columns. Each transition repeats exact user/workspace
scope, actor, sequence, prior/current state, prior/current role, reason code,
policy version, authority generation, Trace, audit, and timestamp.

### 9.2 Persisted lifecycle

Membership states are:

- `active`
- `suspended`
- `removed`

Allowed transitions:

```text
active -> suspended
suspended -> active
active -> removed
suspended -> removed
```

`removed` is terminal. Rejoining creates a new membership identity and retains
the old evidence.

The complete user-visible admission lifecycle is:

```text
invited -> pending acceptance -> active
                      |-> declined
                      |-> expired
                      |-> revoked
active <-> suspended -> removed
```

`invited`, `pending acceptance`, `declined`, `expired`, and pre-acceptance
`revoked` belong to the invitation lifecycle. A membership row is created only
when an authenticated, recipient-matched user accepts. This avoids nullable
or ghost membership identities for unregistered email addresses.

Removal never deletes actions, approvals, comments, evaluations, Trace, audit,
events, or activity. Historical reads remain available only to principals
with current audit/evidence authority.

## 10. Invitation architecture

### 10.1 Invitation identity and state

An immutable invitation records:

- opaque `invitation_id`;
- exact `workspace_id`;
- normalized recipient email and keyed recipient digest;
- optional server-resolved `recipient_user_id`;
- intended closed role;
- `inviter_user_id` and inviter membership;
- policy version and request digest;
- initial expiry;
- Trace and audit references.

Bearer secrets are generated with cryptographic randomness. Persistence stores
only an HMAC/hash using a dedicated server secret and a secret-version number.
Raw tokens appear once at the delivery boundary or acceptance request and
never in logs, Trace, events, URLs returned to unrelated users, or API reads.

Invitation state is append-only:

- `pending`
- `accepted`
- `declined`
- `expired`
- `revoked`

All terminal states remain terminal. Acceptance has a database uniqueness
constraint. Resend appends a delivery attempt and new secret version,
invalidating all older tokens; it does not create parallel live invitations.

### 10.2 Existing and future users

- Existing user: the server may bind `recipient_user_id` internally at
  creation. Acceptance still requires that authenticated user and the exact
  recipient email.
- Not-yet-registered recipient: the invitation retains normalized recipient
  identity and digest but no user ID. Registration does not auto-join. After
  sign-in, acceptance binds the account only when its normalized verified
  email matches.

Both paths use the same authenticated, CSRF-protected acceptance transaction.
Public creation and acceptance responses are indistinguishable for existing
and unknown addresses to prevent enumeration.

### 10.3 Security and delivery

- Exact workspace and intended role are server-owned and digest-bound.
- The acceptance API accepts no role or workspace override.
- Expiry, revocation, recipient mismatch, old secret version, reuse, and
  cross-workspace substitution fail closed.
- Duplicate creation with the same scoped idempotency key returns the same
  invitation only when the request digest matches.
- A pending invitation for the same workspace/recipient/role may be reused or
  rotated according to policy; conflicting roles require explicit revocation
  or role-authorized replacement.
- Email delivery extends the current safe email boundary. Provider failure
  records a safe delivery classification without accepting, revoking, or
  exposing the invitation.
- Deterministic local tests use a capture provider and never send external
  email.

## 11. Resource visibility and sharing

### 11.1 Decision: explicit, narrow, revocable sharing

Workspace membership grants workspace metadata and no blanket canvas access.
Canvases are private until shared or explicitly workspace-visible. A share
targets either the entire workspace membership population or one active
membership. Core Milestone 6 has no public, link, email-only, group, or
cross-workspace audience.

Share access levels are closed per resource kind and map to the permission
registry:

- `view`
- `contribute`
- `manage`

`manage` never means ownership, approval, export, or Milestone 4 authority.
The sharer cannot grant an access level beyond their own current effective
permission or the recipient role ceiling.

### 11.2 Inheritance

- Workspace metadata is visible to active members with `workspace.view`.
- Canvas access requires a canvas share, canvas ownership, or a closed
  workspace-visible canvas policy.
- Nodes, documents, notes, and graph resources inherit at most the parent
  canvas share unless marked `private` or directly restricted.
- A directly shared child resource exposes only minimum parent container
  metadata required to navigate it; it reveals no sibling resources and grants
  no canvas edit.
- Workflows and agents may inherit a canvas share only when their sharing
  policy is explicitly `inherit`; otherwise they require a direct share.
- Immutable workflow and agent versions are never independently shared.
  Access follows the parent identity and verifies the exact requested version.
- Retrieval results follow the initiating workflow/execution plus current
  access to required sources.
- Citations expose safe metadata only when the retrieval is visible; source
  passage access independently requires current source visibility.
- Trace follows its authoritative parent and `trace.view`; restricted audit
  evidence is never implied by ordinary resource view.
- Evidence Bundle metadata requires `evidence_bundle.view`. Artifact download
  and full-source contents additionally require current
  `evidence_bundle.export` and `source.export`.
- Comments inherit their exact parent resource and never widen it.
- A graph relationship is visible only when both endpoints and the
  relationship itself are visible. Hidden endpoints are not disclosed.

### 11.3 Private resources inside shared workspaces

A resource may be `private`, `inherit`, or `workspace_visible`. `private`
denies inheritance and requires a direct membership share or resource
ownership. Changing visibility is a versioned, audited, optimistic-concurrency
command. Stale share or resource versions conflict; clients cannot overwrite
newer policy.

Every share has immutable identity plus append-only state transitions:

```text
active -> revoked
revoked -> active  # explicit re-share with a new generation
```

Reactivation preserves the share identity and increments its authority
generation. Historical evidence is never deleted.

Read access never implies edit, sharing, workflow invocation, agent invocation,
approval, source export, or Evidence Bundle export.

## 12. Shared workflows and agents

A shared workflow or agent retains:

- immutable definition/identity and immutable version;
- exact owning workspace and canvas;
- immutable creator and current resource owner;
- current sharing identity and generation;
- closed lifecycle;
- required capabilities, resources, grants, approvals, risk, selected-context
  rules, provider policy, and server-owned limits;
- Trace, audit, domain-event, outbox, and activity history.

Visibility enables inspection only. Every invocation independently verifies:

1. current authenticated principal;
2. active membership and role policy;
3. exact workflow/agent and canvas share;
4. lifecycle and immutable version digest;
5. collaboration permission (`workflow.invoke` or `agent.invoke`);
6. exact selected context and source access;
7. Milestone 4 capability, grant, risk, and approval;
8. user/workspace/canvas/resource/version scope;
9. membership/share/workspace authority generations;
10. context, plan, request, and version digests.

Execution records remain attributed to the invoking user and membership.
Creator or resource-owner identity is not substituted for the invoker. Agents
and workflows cannot bind across workspaces in core Milestone 6.

## 13. Approval authority

`approver` is a collaboration role, not an approval record. Collaboration
permission only makes a principal eligible to enter the existing Milestone 4
approval path.

An append-only approval-authority assignment binds:

- approver membership;
- exact workspace;
- exact action and resource kind, and resource ID where narrow assignment is
  required;
- maximum risk class;
- policy version;
- validity window;
- conflict-of-interest policy;
- issuer and revocation evidence.

Every approval decision verifies active membership, role or explicit
assignment, `approval.review`, exact action/resource/risk, unexpired assignment,
current authority generations, and the existing grant/approval digests and
single-use rules.

Milestone 4 approval evidence is extended, not replaced, with an append-only
reviewer-eligibility record keyed to the existing approval ID. It records the
requester, deciding user, deciding membership, assignment, collaboration
policy/digest, decision session, and scope. The eligibility record, approval
decision, policy decision, and one-time consumption commit atomically where
the existing effect boundary requires it.

Default conflict rules deny self-review for ownership, role, sharing,
activation, source export, Evidence Bundle export, and durable-write actions.
Any narrower exception must be a closed policy rule and cannot be chosen by
the requester. Owner and administrator roles have no universal approval
power.

## 14. Ownership transfer

### 14.1 Workspace ownership

There is exactly one current workspace owner and exactly one active owner-role
membership. The existing `Workspace.owner_id` remains the canonical current
owner and must agree with the latest accepted transfer evidence.

Workspace transfer:

```text
pending_acceptance -> accepted
                   -> canceled
                   -> expired
```

- Only the current owner with exact authority may request.
- The recipient must be a different active membership in the same workspace.
- The recipient must accept before expiry.
- Only one pending workspace transfer may exist.
- Acceptance atomically changes `Workspace.owner_id`, appends transfer and
  membership-role transitions, increments workspace authority generation, and
  emits Trace/audit/event/outbox evidence.
- The recipient becomes `owner`; the former owner becomes `administrator` by
  default. A different closed post-transfer role must be selected and
  validated in the original request.
- Current owner authority remains until acceptance.
- Cancel, expiry, failure, or recipient suspension changes no ownership.
- The final owner cannot be removed or suspended until a transfer completes.

This preserves a minimum-one-owner invariant and prevents orphaned workspaces.

### 14.2 Resource ownership

Shareable resources have immutable creator evidence and current ownership by
either the workspace or one active membership. A normalized ownership binding
references the exact typed resource and scope without changing immutable
workflow, agent, graph, or source identities.

Membership-to-membership resource transfer requires recipient acceptance.
Transfer to workspace ownership requires current resource-owner and
administrative policy. Workspace-owned resources cannot be silently claimed
by a member. Transfer never creates capabilities or changes historical actors.

## 15. Revocation and active-operation fencing

Every membership, share, approval assignment, and workspace has a monotonic
authority generation. Prepared and running authoritative operations capture
the exact generations and recheck them before claim, provider/tool call,
retry, approval decision, effect commit, result commit, compensation, export,
and artifact download.

### 15.1 Immediate effects

Invitation revocation, membership suspension/removal, role downgrade,
unsharing, approval-assignment revocation, workflow/agent access removal, and
ownership transfer immediately:

- deny new operations;
- invalidate workspace-scoped frontend caches;
- deny direct navigation on authoritative refresh;
- invalidate pending collaboration approvals and activation requests that no
  longer have an eligible reviewer/requester;
- fence unclaimed jobs and retries;
- make old authority snapshots stale.

The user account session may remain valid for other workspaces. High-risk
administrative removal may revoke all of that user's sessions only under an
explicit security policy. Ordinary membership change increments workspace and
membership authority generations rather than logging the user out globally.

### 15.2 Running operations

| Operation state                                | Revocation behavior                                                                            |
| ---------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| Prepared or queued                             | Cancel/fence before claim                                                                      |
| Claimed but no provider/tool call              | Cancel and release/fence generation                                                            |
| Provider call in flight                        | Request cancellation where supported; always discard the returned result if authority is stale |
| Read-only result before commit                 | Reject result and record safe cancellation/denial                                              |
| Durable effect not committed                   | Recheck and deny commit                                                                        |
| Durable effect already committed               | Preserve authoritative effect; do not rewrite history                                          |
| Compensation already and separately authorized | May finish only under its unrevoked compensation authority                                     |
| Compensation lacks current authority           | Pause as `awaiting_reauthorization`; never reuse revoked authority                             |
| Pending approval                               | Invalidate or require a new eligible reviewer and exact approval                               |
| Evidence/Bundle read                           | Deny immediately unless current audit/export authority independently permits                   |

Stale workers and retries cannot complete after a generation change. A safe
internal security audit may record denied cross-scope attempts, but public
activity never exposes probed identifiers.

## 16. Comments and threads

Comments are plain-text collaboration records attached to one exact scoped
parent resource. Core Milestone 6 renders escaped text and permits only
server-sanitized `https` links with an external-link warning. It provides no
HTML, raw Markdown, embeds, link previews, executable content, or semantic
mentions.

`CommentThread` records exact workspace, optional canvas, typed parent
resource, creator, and creation evidence. Thread state is:

```text
open -> resolved -> reopened
```

`Comment` identity is immutable. Text is stored in append-only
`CommentRevision` rows. Comment presentation state is:

- `active`
- `edited`
- `hidden_by_moderation`
- `removed_by_author`

Editing requires the original active author and `comment.edit_own`; moderation
requires `comment.moderate`. Author removal or moderation adds a tombstone
transition and hides normal text while preserving governed evidence. No
historical revision is overwritten or hard-deleted.

Replies retain exact thread, parent comment, workspace, canvas, resource, and
author scope. Depth, size, count, and rate are server-bounded. Cross-resource
or cross-workspace reply IDs return not found. Resolution changes thread
state, not comment evidence.

## 17. Events, outbox, activity, and notifications

Milestone 6 extends `EVENT_TYPE_REGISTRY`, `DomainEventService`, the existing
transactional outbox, and `DomainActivityEntry`. It does not create a second
feed.

Future real producers use closed event types equivalent to:

```text
collaboration.invitation.created
collaboration.invitation.accepted
collaboration.invitation.declined
collaboration.invitation.expired
collaboration.invitation.revoked
collaboration.membership.activated
collaboration.membership.suspended
collaboration.membership.restored
collaboration.membership.removed
collaboration.role.changed
collaboration.ownership_transfer.requested
collaboration.ownership_transfer.accepted
collaboration.ownership_transfer.canceled
collaboration.resource.shared
collaboration.resource.unshared
collaboration.comment.created
collaboration.comment.edited
collaboration.comment.resolved
collaboration.comment.moderated
collaboration.access.denied
```

Events retain actor user and membership separately from workspace scope.
Milestone 6 reads activity by authorized workspace/resource scope rather than
requiring the viewer to equal the event actor. Sensitive membership,
invitation, denial, and moderation activity is audience-filtered.

Success events share the authoritative transaction. Delivery and projection
remain idempotent and generation-fenced. Failure events carry safe closed
classifications, never emails, tokens, comment text, probed IDs, grants,
policies, SQL, paths, or private reasoning.

Activity is durable shared history. Notifications are per-recipient attention
state. Core Milestone 6 does not require notifications. If later included,
they are a bounded in-product projection from authorized events with
`unread/read/dismissed` state; they add no email/chat platform and grant no
authority. Invitation email remains the only required email delivery.

## 18. Tenant isolation

Tenant isolation is enforced at every layer.

### 18.1 Database

- Every collaboration table carries exact `workspace_id`.
- Canvas/resource records repeat `canvas_id` where applicable.
- Composite foreign keys bind membership, invitation, share, comment,
  approval assignment, execution authority, event, and activity to the same
  workspace/canvas.
- Typed share/ownership targets use real foreign keys and a check constraint
  requiring exactly one target family.
- Unique constraints enforce one active user/workspace membership identity,
  one owner, one invitation acceptance, one ordered transition sequence, one
  scoped idempotency identity, and one event projection.
- Append-only histories and immutable identities use ORM rejection plus
  SQLite and PostgreSQL update/delete triggers.
- Mutable current rows, where unavoidable for session or projection state,
  use optimistic version/generation checks and immutable history.

### 18.2 Services and APIs

- A `CollaborationAuthorizationService` replaces owner-only decisions at
  existing seams; routes never compute authority.
- Repository queries join exact membership, workspace, canvas, typed resource,
  lifecycle, share, and generation.
- Foreign or malformed identifiers share a not-found boundary.
- Responses use allowlisted schemas and bounded pagination.
- Idempotency digests include user, membership, workspace, canvas, action,
  typed resource, policy version, and request body.

### 18.3 Jobs, events, Trace, and audit

- Jobs capture membership and authority generations and recheck before every
  authoritative boundary.
- Events retain workspace, actor, membership, resource, and audience scope.
- Outbox and activity stay workspace-scoped.
- Trace and audit record exact actor, membership, action, resource, policy,
  authority snapshot, outcome, and safe reason without raw grants or secrets.

### 18.4 Frontend

- Query keys include authenticated user/session scope, workspace, canvas,
  resource, and returned authority version.
- Logout clears the entire query client and user-scoped local storage.
- Workspace/canvas change aborts in-flight requests and removes prior-scope
  queries.
- Membership or role change invalidates all affected workspace queries.
- Stored last-canvas choices are namespaced by user and workspace and are
  always server-validated.
- A stale response cannot repopulate a revoked scope.

### 18.5 PostgreSQL row-level security

Every table includes stable workspace scope so Milestone 7 may add PostgreSQL
row-level security as defense in depth. Application authorization remains
mandatory. RLS is not a Milestone 6 completion claim until policies, tenant
session variables, privileged maintenance paths, migrations, and runtime
isolation tests are deliberately implemented and validated.

## 19. Frontend architecture

The frontend extends existing patterns with:

- a workspace switcher listing only active memberships and current role;
- workspace settings for members, invitations, roles, and transfer;
- canvas and resource sharing panels;
- workflow and agent sharing panels;
- comment threads on supported resources;
- collaboration activity views;
- explicit access-denied, access-revoked, invitation-expired, and
  membership-suspended states.

Proposed routes:

```text
/workspaces
/workspaces/{workspaceId}/members
/workspaces/{workspaceId}/invitations
/workspaces/{workspaceId}/ownership
/workspaces/{workspaceId}/activity
/workspaces/{workspaceId}/canvases/{canvasId}/sharing
/workspaces/{workspaceId}/workflows/{workflowId}/sharing
/workspaces/{workspaceId}/agents/{agentId}/sharing
```

Resource pages embed comments and sharing rather than introducing a second
canvas renderer.

All mutations use the existing API client and CSRF token. Lists are bounded
and paginated. Dialogs display effective role/share consequences returned by
the server, not client-derived policy. Invitation tokens never enter query
keys, analytics, local storage, error messages, or rendered administration
lists. Recipient emails are masked except in authorized invitation
administration.

Forms, tables, menus, dialogs, status messages, and comparisons require
semantic controls, accessible names, visible focus, focus containment and
restoration, escape-to-close, keyboard operation, screen-reader status,
non-color state/risk meaning, reduced motion, and narrow-viewport layouts.

## 20. Future real-time extension seams

Core records expose stable identity, resource revision, comment/event sequence,
and authority generation. Future adapters may use:

- expiring presence sessions keyed by session/membership/workspace;
- cursor channels keyed by authorized canvas/resource;
- document operation streams keyed by immutable base version and operation
  sequence;
- an abstract CRDT or operational-transform adapter;
- reconnect reconciliation and conflict-resolution evidence.

No adapter is selected now. Presence, cursor, and operation messages never
grant authority and must pass current membership/share checks. No speculative
CRDT/OT columns, dependencies, queues, or APIs are part of Milestone 6.

## 21. Server-owned default limits

These are proposed implementation-time constants. Repository tests must
validate the final values. Clients may request lower values but cannot weaken
server maximums.

| Limit                             | Proposed default / maximum                               |
| --------------------------------- | -------------------------------------------------------- |
| Active memberships per workspace  | 500                                                      |
| Workspaces per user               | 100                                                      |
| Pending invitations per workspace | 100                                                      |
| Invitation lifetime               | 7 days default; 30 days maximum                          |
| Invitation resend                 | no sooner than 10 minutes; 5 per invitation per 24 hours |
| Role changes per request          | 1                                                        |
| Resource shares per request       | 50                                                       |
| Shares per resource               | 500                                                      |
| Shared resources per workspace    | 10,000                                                   |
| Comment length                    | 5,000 Unicode code points                                |
| Comments per thread               | 500                                                      |
| Comment reply depth               | 4                                                        |
| Comment creation rate             | 30 per membership per minute                             |
| Collaboration activity page       | 50 default; 100 maximum                                  |
| Membership page                   | 50 default; 100 maximum                                  |
| Invitation page                   | 50 default; 100 maximum                                  |
| Notification page if implemented  | 50 default; 100 maximum                                  |
| Workspace switches                | 120 per user per minute before rate limiting             |
| Ownership-transfer lifetime       | 48 hours default; 7 days maximum                         |
| Bulk revocation                   | 50 targets per request                                   |

## 22. Persistence architecture

No migration is created during this architecture pass. The smallest coherent
future sequence after `20260725_0020` is:

### `20260725_0021` — Membership and invitations

- `workspace_memberships`
- append-only `workspace_membership_transitions`
- `workspace_invitations`
- append-only invitation state, secret-version, and delivery-attempt records
- collaboration request-idempotency identities
- workspace authority generation
- backfill one active owner membership for every existing workspace

Account creation must atomically create the personal workspace and owner
membership after this migration.

### `20260725_0022` — Roles, shares, ownership, approvals, and fencing

- closed role/permission checks and policy-version evidence;
- append-only approval-authority assignments/revocations;
- typed canvas, canonical-object, workflow, and agent shares;
- resource ownership bindings and transitions;
- ownership-transfer requests and transitions;
- execution authority snapshots and revocation generations.

Typed share/ownership targets use nullable real foreign keys with a
resource-kind check requiring exactly one target. Generic unverified UUID
targets are rejected.

### `20260725_0023` — Comments and collaboration activity

- comment threads;
- immutable comment identities;
- append-only comment revisions and state transitions;
- event-registry/subject extensions for real collaboration producers;
- audience-aware activity projection support;
- optional bounded notification state only if 6.4 explicitly justifies it.

Each migration must:

- upgrade from the prior sole head;
- downgrade exactly one revision and re-upgrade;
- preserve legacy owner-only records and immutable history;
- install SQLite and PostgreSQL append-only guards;
- validate composite scope FKs, uniqueness, checks, and indexes;
- compile PostgreSQL DDL offline;
- include deterministic SQLite behavior tests; and
- avoid claiming PostgreSQL runtime guarantees without a configured runtime.

## 23. Service architecture

Narrow services:

- `MembershipService`: list, resolve, suspend, restore, remove, and append role
  transitions.
- `InvitationService`: create, rotate/resend, accept, decline, expire, revoke,
  and record safe delivery.
- `CollaborationAuthorizationService`: resolve active membership, role
  ceiling, share/inheritance, permission, resource lifecycle, and generations.
- `ApprovalEligibilityService`: compose membership/assignment eligibility with
  existing Milestone 4 approval evidence.
- `SharingService`: typed share creation, reactivation, revocation, and
  visibility resolution.
- `OwnershipTransferService`: workspace/resource requests, acceptance,
  cancellation, expiry, and invariants.
- `RevocationFenceService`: increment generations, invalidate pending work,
  and provide claim/commit rechecks.
- `CommentService`: thread, revision, state, resolution, and moderation.
- Existing `DomainEventService` and outbox/activity services: extended for
  collaboration producers and audience filtering.

Services own transactions or clearly document caller ownership. Mutation,
Trace, audit, event, outbox, transition, and generation change commit
atomically. Routes perform parsing and serialization only.

## 24. API architecture

Proposed bounded authenticated endpoints:

```text
GET    /workspaces
GET    /workspaces/{workspaceId}/memberships
POST   /workspaces/{workspaceId}/invitations
GET    /workspaces/{workspaceId}/invitations
POST   /workspaces/{workspaceId}/invitations/{invitationId}/resend
POST   /workspaces/{workspaceId}/invitations/{invitationId}/revoke
POST   /collaboration-invitations/{invitationId}/accept
POST   /collaboration-invitations/{invitationId}/decline
POST   /workspaces/{workspaceId}/memberships/{membershipId}/role
POST   /workspaces/{workspaceId}/memberships/{membershipId}/suspend
POST   /workspaces/{workspaceId}/memberships/{membershipId}/restore
POST   /workspaces/{workspaceId}/memberships/{membershipId}/remove
POST   /workspaces/{workspaceId}/ownership-transfers
POST   /workspaces/{workspaceId}/ownership-transfers/{transferId}/accept
POST   /workspaces/{workspaceId}/ownership-transfers/{transferId}/cancel
GET    /workspaces/{workspaceId}/shares
POST   /workspaces/{workspaceId}/shares
POST   /workspaces/{workspaceId}/shares/{shareId}/revoke
GET    /workspaces/{workspaceId}/resources/{resourceKind}/{resourceId}/comments
POST   /workspaces/{workspaceId}/resources/{resourceKind}/{resourceId}/comments
POST   /workspaces/{workspaceId}/comments/{commentId}/revisions
POST   /workspaces/{workspaceId}/comments/{commentId}/moderate
POST   /workspaces/{workspaceId}/comment-threads/{threadId}/resolve
GET    /workspaces/{workspaceId}/collaboration-activity
```

Every mutation is CSRF-protected, idempotent where retry is plausible, uses
server-derived actor/membership, rejects authority fields in payloads, and
returns safe conflicts. Invitation acceptance accepts the bearer token in the
request body, never a query string.

No browser API exposes raw permission mutation, raw grants, policy internals,
worker/outbox claims, lease control, arbitrary authority, or cross-workspace
workflow/agent binding.

## 25. Threat model

| Threat                                                                    | Required mitigation                                                                                                   |
| ------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| Horizontal tenant escape / IDOR                                           | Server-derived principal; composite scope joins/FKs; not-found boundary; cross-user/workspace/canvas tests            |
| Vertical role escalation / role widening                                  | Closed single-role registry; role ceiling; append-only authorized transitions; client role rejection                  |
| Invitation theft/replay                                                   | Hashed/HMAC token, one-time acceptance, exact recipient/workspace/role, expiry, rotation, revocation                  |
| Recipient substitution / enumeration                                      | Authenticated verified-email match; indistinguishable public responses; masked admin views                            |
| Owner lockout / orphaned workspace                                        | Exactly one owner; accepted transfer; final-owner suspension/removal denied                                           |
| Stale membership/share/browser cache                                      | Monotonic authority generations; recheck at boundaries; abort/clear scoped queries                                    |
| Creator/owner/approval confusion                                          | Separate immutable creator, current owner, membership, action permission, reviewer eligibility, and approval evidence |
| Sharing treated as authority                                              | Role ceiling plus typed share plus Milestone 4 capability/grant/approval                                              |
| Workflow/agent invocation escalation                                      | Exact visible version, invocation permission, selected context, capability, grant, approval, digest, and generation   |
| Source/Evidence Bundle leakage                                            | Separate view/export permissions; current source access; scoped artifact download                                     |
| Comment HTML/Markdown/link injection                                      | Plain text; escaping; bounded sanitized HTTPS links; no embeds/previews                                               |
| Mention or notification abuse                                             | No semantic mentions in core; bounded optional per-recipient projection                                               |
| Active execution/retry after revocation                                   | Generation fencing before claim/call/retry/effect/result; discard stale provider results                              |
| Stale worker completion                                                   | Existing lease generation plus membership/share/workspace authority generation                                        |
| Duplicate invitation/transfer/event                                       | Scoped idempotency digest; unique acceptance; one pending transfer; idempotent event/projector                        |
| Activity leakage                                                          | Workspace/resource authorization and audience filter; safe payloads; no probed IDs                                    |
| Local path, secret, token, raw grant, policy, or chain-of-thought leakage | Allowlisted serializers, redacted safe errors/events/Trace, hygiene and security scans                                |

## 26. Rejected alternatives and risks

| Alternative                                                 | Decision and reason                                                                                                                             |
| ----------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| Multiple roles per membership                               | Rejected initially; union semantics obscure authority and complicate revocation. Use one role plus typed shares and exact approval assignments. |
| Role alone grants resource access                           | Rejected; membership and role are ceilings. Explicit ownership/share/inheritance is also required.                                              |
| Workspace membership exposes every canvas                   | Rejected; private resources in team workspaces are required.                                                                                    |
| One generic ACL with free-text permissions and target UUIDs | Rejected; use closed permissions and typed targets with real scope validation/FKs.                                                              |
| Membership rows for unregistered recipients                 | Rejected; invitations own pre-acceptance states so active membership always has an exact user.                                                  |
| Collaboration approval system separate from Milestone 4     | Rejected; add reviewer eligibility evidence to the existing approval path.                                                                      |
| Cancel every effect after revocation                        | Rejected; committed authoritative effects remain historical. Fence future commits and use separately authorized compensation.                   |
| Global logout for every role/share change                   | Rejected; increment workspace/membership authority generations and preserve unrelated workspace sessions.                                       |
| Hard-delete comments                                        | Rejected; append revisions and tombstones preserve governance evidence.                                                                         |
| Require PostgreSQL RLS in Milestone 6                       | Rejected as an unproved dependency; preserve compatibility and evaluate/test it in Milestone 7.                                                 |
| Choose CRDT or operational transform now                    | Rejected; stable adapter seams avoid speculative fields and dependencies.                                                                       |

Primary implementation risks:

- owner-only historical `user_id` fields may be accidentally treated as the
  current viewer; future reads must use membership authorization without
  rewriting actor identity;
- event/activity audience filtering must not expose invitation or denial data;
- resource inheritance can become ambiguous unless `private`, `inherit`, and
  `workspace_visible` precedence is implemented centrally;
- revocation must recheck before provider, effect, result, retry, compensation,
  and export boundaries, not only at request start;
- backfilling owner memberships must preserve every workspace and never create
  a second owner;
- SQLite contention proves deterministic local behavior, not PostgreSQL
  production isolation or performance.

## 27. Required future test architecture

Each implementation checkpoint adds focused tests and keeps affected prior
Milestone 4/5 tests green. The final matrix includes:

- membership lifecycle, role change, suspension, restoration, removal, and
  rejoin identity;
- invitation expiry, revocation, recipient matching, token replay/rotation,
  enumeration safety, duplicate behavior, resend bounds, and email failure;
- role/permission ceilings and unknown-value denial;
- approval eligibility, assignment expiry/revocation, self-review, one-time
  consumption, and Milestone 4 composition;
- canvas/resource/workflow/agent sharing, private inheritance, unsharing, and
  immutable-version access;
- workspace/resource ownership transfer, concurrent acceptance, one-owner
  invariant, cache/session invalidation, and historical evidence;
- revocation before claim, during provider call, before effect/result, before
  retry, during pending approval, and before export;
- workflow/agent shared visibility versus invocation authority;
- selected context, citation, Trace, source, and Evidence Bundle isolation;
- comment revision, tombstone, moderation, injection, link, depth, size, and
  cross-scope reply tests;
- collaboration events, transactional outbox, delivery retry, audience-aware
  activity, projection replay, and duplicate suppression;
- authentication, CSRF, bounded input/page sizes, safe errors, IDOR, and
  cross-user/workspace/canvas/resource tests;
- frontend cache partitioning/invalidation, direct navigation, refresh,
  revoked access, keyboard, focus, reduced motion, responsive layout, and safe
  invitation handling;
- scoped idempotency, deterministic SQLite contention, failure injection,
  migration cycles, SQLite triggers/constraints, PostgreSQL offline DDL, and
  configured PostgreSQL runtime tests before production claims;
- static typing, lint, formatting, compilation, mappers, production build,
  browser smoke, accessibility, secret/path/prohibited-scope scans, repository
  hygiene, and Git integrity.

## 28. Formal implementation checkpoints

### 6.1 — Workspace Membership and Invitations

- membership identity and lifecycle;
- secure invitation lifecycle;
- exact tenant scope;
- foundational role registry;
- authenticated membership/invitation APIs;
- migration and focused security tests.

### 6.2 — Collaboration Roles and Permission Authority

- closed role and permission registries;
- role assignment and history;
- Milestone 4 policy composition;
- exact approval-review eligibility;
- role/membership revocation;
- cross-role and cross-scope tests.

### 6.3 — Resource Sharing, Ownership, and Revocation

- canvas/canonical-resource/workflow/agent sharing;
- private and inherited visibility;
- ownership transfer;
- unsharing and active-operation fencing;
- sharing/isolation APIs.

### 6.4 — Comments and Collaboration Activity

- bounded comment threads/revisions/moderation;
- collaboration events/outbox/activity;
- optional bounded in-product notifications only if justified;
- injection and scope tests.

### 6.5 — Shared Workflow and Agent Governance

- shared workflow/agent inspection and invocation;
- approval authority;
- selected-context/evidence boundaries;
- exact capability/grant checks;
- revocation during controlled execution.

### 6.6 — Multi-Workspace Collaboration Interface

- workspace switcher;
- membership/invitation/role/sharing/ownership UI;
- comments and collaboration activity;
- revoked/suspended/expired states;
- accessibility, responsive behavior, cache isolation, and refresh safety.

### 6.7 — Final Collaboration Security Audit

- complete tenant, lifecycle, registry, authority, and roadmap audit;
- concurrency, idempotency, and failure injection;
- migration, backend, frontend, browser, accessibility, build, static, demo,
  hygiene, and Git validation;
- Milestone 6 completion and handoff.

Basic presence is not required for any checkpoint.

## 29. Roadmap preservation

Milestone 6 remains next. It provides collaboration authority and tenant
isolation needed by later systems.

Milestone 7 retains Production Hardening, the deterministic technical Indexer,
managed PostgreSQL/storage, malware scanning, backup/restore, monitoring,
shared rate limiting, and load/recovery validation. Indexing is not moved into
Milestone 6.

Milestone 9 retains Agent Society, the governed Librarian, AI Catalog, Academy,
Agent Justice, Quarantine, Rehabilitation, Tribunal, and governed marketplace.
The Librarian is not implemented in Milestone 6.

Advanced Real-Time Collaboration remains a separate phase after the initial
Milestone 8 release. Milestones 7–13 remain unstarted.

## 30. Architecture completion boundary

Milestone 6 architecture is complete when these documents agree and all
documentation/repository-integrity checks pass. No implementation behavior is
claimed.

Milestone 6.1 must begin only under a separate explicit request, from the
architecture completion commit, with a fresh baseline verification.
