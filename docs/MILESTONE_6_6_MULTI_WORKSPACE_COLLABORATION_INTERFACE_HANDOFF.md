# Milestone 6.6 — Multi-Workspace Collaboration Interface Handoff

Date: 2026-07-26

Branch: `milestone-6-6-multi-workspace-collaboration-interface-local`

Parent: `ef074bc1a38dd63f24dfdca46ec334fc29ea68d1`

Status: complete locally; ready for the Milestone 6.7 final collaboration
security audit

## Completion boundary

Milestone 6.6 implements the bounded end-user interface for collaboration
capabilities completed in checkpoints 6.1–6.5. It does not perform the 6.7
system-wide audit, create persistence, add a migration, implement real-time
collaboration, or begin Milestone 7 or later product work.

The sole Alembic head remains `20260725_0025`. Revisions
`20260725_0021` through `20260725_0025` were not modified, and no later
revision was created.

## Frontend architecture

The `/collaboration` route extends the existing Next.js application router,
authenticated API client, TanStack Query provider, Zod response validation,
and restrained cosmic design tokens. It adds no dependency or alternate state
framework.

The console contains five semantic tab panels:

1. Overview — current server-confirmed workspace, authenticated user,
   membership, role, lifecycle, authority generation, workspace ownership,
   and bounded operation ceiling.
2. People — memberships, non-owner role changes, suspension/restoration/
   removal, invitation lifecycle, exact-recipient response, and bounded
   reviewer eligibility.
3. Access — typed shares, resource visibility and ownership, and explicit
   pending workspace/resource ownership transfers.
4. Discussions — bounded plain-text comments, replies, immutable revision
   history, author tombstones, thread state, and the existing collaboration
   activity projection.
5. Automations — visible canvas selection, shared workflow/agent discovery,
   immutable version state, definition owner, visibility basis,
   server-confirmed invocation availability, selected context, bounded
   invocation result, and Trace navigation.

Existing Canvas, Dynamic Universe, and Agent Studio surfaces link to the
collaboration console without changing their workflows.

## Authority and workspace switching

`GET /workspaces` now derives results from active server membership rather
than owner identity. The switcher therefore lists only exact workspaces the
current user may inspect and exposes no hidden count or name.

`GET /workspaces/{workspaceId}/collaboration-context` returns a bounded current
membership, role, workspace lifecycle, authority generation, and closed
server operation ceiling. The browser uses that data to avoid presenting
unavailable controls, but never treats it as final resource authority. Every
read and mutation still passes centralized server authorization.

Workspace changes cancel in-flight prior-scope requests, remove prior
workspace queries, clear selected resource/canvas state, reset to the safe
overview, replace the route with the new workspace identity, and wait for a
fresh server context. A 404 context after revocation clears the same state and
announces access loss. Sensitive collaboration data is not stored in browser
storage.

Query keys include authenticated user, workspace, authority generation,
resource kind and identity, canvas, and workflow/agent collection. Immutable
versions remain inside their parent identity response and cannot be shared
independently.

## Memberships, invitations, roles, and approval eligibility

Administrators see only the operations returned by the server ceiling.
Ordinary role controls contain the closed non-owner roles and never offer
owner assignment. Current user and owner rows cannot be demoted through the
interface. Authority-reducing membership and role changes require
confirmation, wait for the server result, then invalidate membership,
workspace, authority, resource, automation, comment, and activity state.

Invitation creation, resend, revocation, exact invitation acceptance, and
decline use existing bounded endpoints. Invitation credentials are accepted
only in a password field and never placed in the URL, query key, local
storage, or rendered record list.

Reviewer eligibility is explicitly labeled as neither an approval nor a
Milestone 4 capability grant. The interface exposes only bounded assignments
that the existing centralized authority service allows the viewer to list.

## Sharing, ownership, comments, and activity

Sharing supports only canvas, canonical object, workflow identity, and agent
identity; workspace or membership audiences; and view, contribute, or manage
access. The interface states that visibility, contribution, management,
ownership, approval, activation, capability, and invocation remain distinct.
Share create/revoke and visibility changes revalidate authority and clear
stale resource state.

Visible resource ownership is exposed through a new read endpoint that first
evaluates current typed visibility. Ownership-transfer lists are server
filtered: the workspace owner may inspect the workspace list, while another
member sees only transfers where they are requester or recipient. Pending
requests are labeled as not changing ownership. Exact recipient
acceptance/rejection and requester cancellation require server authority and
refresh ownership, membership, sharing, workspace, and authority state.

Comments use plain text, the server-owned 5,000-code-point limit, four-level
reply boundary, 50-item default paging, immutable revisions, tombstone
placeholders, and current-authority mutation checks. The UI does not render
comment content as evidence. Activity reads only the existing audience-aware
`activity-v1` projection and never renders comment text, invitation
credentials, raw audit payloads, or private policy/approval facts.

## Shared workflows and agents

Workflow and agent list responses now include:

- immutable definition owner;
- current safe visibility basis;
- `canInvoke`, computed by the server through current typed visibility and
  the separate closed invocation permission.

The browser does not infer invocation from role or share access. Invocation
buttons remain disabled for visible-but-not-invokable identities, and the
server repeats full collaboration, lifecycle, capability, grant, approval,
policy, selected-context, digest, retry, cancellation, compensation, and
stale-result checks. The exact invoking user and membership remain distinct
from the definition owner.

## Failure and accessibility behavior

The interface has deliberate initial loading, refresh, no-workspace, empty,
denied/revoked, stale/canceled, expired, conflict, replay, rate-limit,
malformed-response, and unavailable-server messages. Safe 404 language does
not distinguish hidden from missing resources. Unknown closed-registry values
fail Zod validation and are not displayed as a privileged known value.

Semantic `main`, header, navigation, tablist/tab/tabpanel, table, list,
definition-list, form, status, alert, and live-region structures are used.
Native selects and confirmations preserve keyboard operation and focus.
Fields have visible labels, comment length has an accessible description,
focus is visibly outlined, state meaning is textual rather than color-only,
touch targets are at least 40 pixels, and reduced-motion styles disable
animation. Desktop, tablet, and 390-pixel mobile layouts wrap forms, actions,
cards, tables, and nested comments without horizontal page overflow.

## Minimal backend corrections

The audit proved and corrected only missing or defective 6.1–6.5 contracts:

- active membership now drives authorized workspace listing;
- shared-canvas listing evaluates current workspace membership and typed
  canvas visibility while retaining non-enumerating 404 for a foreign
  workspace;
- bounded collaboration context is available to the current active member;
- existing approval-authority assignments and ownership transfers have
  authorized list endpoints;
- existing visible resource ownership has an authorized read endpoint;
- workflow and agent discovery carries server-confirmed owner, visibility,
  and invocation metadata.

No database model, durable state, migration, grant, policy, approval, audit,
Trace, event, activity, workflow, agent, or controlled-execution invariant was
weakened.

One defect was found during full regression: a foreign user requesting
`GET /canvases?workspaceId=<foreign>` received an empty 200 after the first
shared-canvas implementation. The final implementation performs an explicit
central workspace-view decision first and restores the required
non-enumerating 404. The affected tenant-isolation and collaboration suites
pass after correction.

## Tests and validation

Added frontend tests cover:

- user/workspace/resource/authority-generation cache partitioning;
- unknown closed values failing safely;
- comment tombstone and size contracts;
- mandatory server-confirmed agent invocation state;
- server-returned workspace/context rendering;
- native keyboard workspace switching and authority refresh;
- viewer administration suppression;
- semantic landmarks, tabs, and live mutation status;
- Chromium desktop keyboard switching; and
- Chromium 390-pixel responsive behavior without page overflow.

Added backend assertions cover:

- shared-member workspace discovery without unauthorized exposure;
- bounded collaboration context and foreign-user non-enumeration;
- authorized approval-authority listing;
- unauthorized eligibility-list denial; and
- requester/recipient ownership-transfer listing.

Validation results:

- frontend Prettier: passed after formatting;
- ESLint: passed with zero warnings;
- TypeScript: passed;
- Vitest: 17 files, 74 tests passed;
- Next.js production build: passed; `/collaboration` is a dynamic route;
- Chromium: 8 passed, 2 expected real-service tests skipped;
- focused backend collaboration/tenant suite after the isolation fix:
  10 passed;
- final full backend regression: 518 passed, 1 PostgreSQL-runtime test skipped,
  61 dependency deprecation warnings, 0 failures;
- Python production-code Ruff: passed;
- strict MyPy: passed, 83 source files;
- initial full backend regression: 517 passed, 1 skipped, 1 failed and 61
  dependency deprecation warnings; the sole failure proved the canvas-list
  non-enumeration defect above and was corrected;
- repository-wide Ruff over all historical tests continues to report the 13
  pre-existing import-order differences recorded by the 6.5 handoff; changed
  production and test files pass focused Ruff.
- Python compilation/import: passed; mapper configuration covered 121 tables;
- migration validator: upgrade `0025`, downgrade `0024`, re-upgrade `0025`;
- configured PostgreSQL-runtime marker: 1 skipped because no PostgreSQL test
  URL was configured;
- deterministic demo isolation and persisted-provenance check: passed; and
- repository hygiene, including tracked-file, generated-file, credential-name,
  environment-file, and secret-pattern checks: 355 source files passed.

## Bounded limitations

- The interface is deliberately request/refresh based; it has no typing
  indicators, WebSockets, live presence, live cursors, simultaneous editing,
  CRDT, operational transform, offline editing, or reconnect merge.
- Server APIs expose stable identifiers because exact scoped commands require
  them; the UI renders bounded shortened forms in normal records.
- The workflow and agent console invokes existing immutable definitions. It
  does not add editing, sharing of versions, activation, promotion, approval,
  capability creation, or delegation.
- Real FastAPI/PostgreSQL browser scenarios remain opt-in and were skipped
  because their environment flag was not configured. The full Python
  migration suite exercises SQLite cycles and offline PostgreSQL DDL.

Milestone 6.7, Advanced Real-Time Collaboration, Milestone 7 Indexer and
production hardening, and Mobius Society/Librarian implementation were not
started.
