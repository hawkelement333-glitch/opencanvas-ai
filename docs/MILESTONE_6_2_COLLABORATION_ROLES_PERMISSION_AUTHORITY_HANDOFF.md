# Milestone 6.2 — Collaboration Roles and Permission Authority Handoff

Date: 2026-07-25

Status: complete locally; Milestone 6.3 not started

Branch: `milestone-6-2-collaboration-roles-permission-authority-local`

Migration: `20260725_0022`

Direct parent: `20260725_0021`

## Completed scope

Checkpoint 6.2 implements one centralized, closed, deny-by-default
collaboration authority layer. It preserves exact authenticated user,
workspace, membership, lifecycle, and server-owned authority-generation
scope. It does not grant resource visibility or any Milestone 4 controlled
capability.

The closed roles are:

- owner;
- administrator;
- editor;
- approver;
- member;
- viewer.

The closed 36-permission vocabulary is the exact registry approved in
`MILESTONE_6_ARCHITECTURE.md`. There are no wildcard, free-text,
`is_admin`, or universal-authority paths.

Explicit code-defined ceilings implement the approved responsibilities:

- owner receives the administrator ceiling plus workspace settings and
  ownership-transfer request/cancel eligibility;
- administrator receives bounded membership, invitation, non-owner role,
  moderation, sharing-administration, activation-request, and export
  eligibility;
- editor receives bounded participation and editing eligibility;
- approver receives read eligibility plus `approval.review`, which still
  requires an exact assignment;
- member receives bounded participation eligibility;
- viewer receives only the read ceiling.

Owner and administrator roles do not contain `approval.review`. A role is
only a ceiling: exact resource sharing/ownership from 6.3 and Milestone 4
policy/grant/approval evidence remain independently required.

## Central authority and 6.1 integration

`CollaborationAuthorizationService` resolves the exact workspace, current
active membership transition, closed role, closed action/permission mapping,
workspace lifecycle, and current authority generation. Unknown or missing
values deny. Public callers receive the existing bounded non-enumerating
collaboration error.

Membership listing and invitation create/list/resend/revoke now use formal
action checks rather than temporary owner-only route logic. Invitation
acceptance and decline retain exact recipient binding, current secret,
expiration, one-time consumption, replay, and tenant isolation.

## Membership authority

The API adds:

```text
POST /workspaces/{workspaceId}/memberships/{membershipId}/role
POST /workspaces/{workspaceId}/memberships/{membershipId}/suspend
POST /workspaces/{workspaceId}/memberships/{membershipId}/restore
POST /workspaces/{workspaceId}/memberships/{membershipId}/remove
```

Every command uses an exact active actor membership and exact same-workspace
target. Owners may administer non-owner roles. Administrators may administer
only editor, approver, member, and viewer memberships and cannot manipulate
themselves, an owner, or another administrator. Ordinary operations cannot
assign, demote, suspend, remove, or replace the owner. Active-to-active role
changes require an actual role difference. Lifecycle transitions preserve the
role and follow active→suspended, suspended→active, or
active/suspended→removed.

Exact idempotent replay returns the existing result. A successful authority
change increments `WorkspaceAuthorityVersion.authority_generation` exactly
once in the same transaction. Failure or replay does not increment it.

## Approval authority and Milestone 4 boundary

The API adds bounded assignment, replacement, and revocation:

```text
POST /workspaces/{workspaceId}/approval-authority
POST /workspaces/{workspaceId}/approval-authority/{assignmentId}/replace
POST /workspaces/{workspaceId}/approval-authority/{assignmentId}/revoke
```

Assignments bind the exact reviewer membership/user/workspace, issuer
membership/user/workspace, controlled-agent capability, resource kind and ID,
maximum non-prohibited risk class, validity window, policy version,
deny-self-review policy, scope digest, Trace, and audit evidence. Only an
owner may administer assignments in this checkpoint, and self-assignment is
denied. Eligible targets are exact active approver or administrator
memberships. Replacement supersedes rather than rewrites prior evidence.

Reviewer evaluation requires exact active membership, unexpired active
assignment, capability, resource kind/ID, bounded risk, non-self requester,
and optional expected current authority generation. It returns eligibility
only. It never creates an approval, capability grant, effect, or Milestone 4
policy decision.

`CollaborationReviewerEligibilityEvidence` extends an existing exact
`ControlledAgentApproval` with deciding user/membership, assignment,
authority generation, collaboration policy/digest, decision session, Trace,
and scope. Existing Milestone 4 action, grant, hash, risk, expiry, revocation,
single-use, and outcome validation remains authoritative.

## Migration and database protections

Migration `20260725_0022` directly follows immutable `20260725_0021` and adds:

- `collaboration_approval_authority_assignments`;
- `collaboration_approval_authority_transitions`;
- `collaboration_reviewer_eligibility_evidence`;
- exact composite tenant-scope foreign keys;
- closed capability, resource-kind, risk, lifecycle, policy, digest, and time
  constraints;
- reviewer/scope/current-transition indexes;
- append-only update/delete guards;
- an append-only approval-assignment lifecycle guard;
- a replacement membership transition guard permitting only authorized
  non-owner role/lifecycle shapes;
- expanded collaboration request, audit-subject, domain-event type, and
  domain-event subject constraints.

The migration preserves a sole head and supplies SQLite upgrade,
downgrade, re-upgrade, constraint/trigger testing, and PostgreSQL offline DDL.
Downgrade refuses destructive removal when 6.2 append-only evidence exists.

Migration `20260725_0021` was not modified. Migrations `20260725_0023` and
`20260725_0024` were not created.

## Events, outbox, activity, Trace, and audit

The existing event registry is extended with:

- `membership.role_changed`;
- `membership.suspended`;
- `membership.restored`;
- `membership.removed`;
- `approval_authority.assigned`;
- `approval_authority.replaced`;
- `approval_authority.revoked`.

Every successful transition creates bounded collaboration audit and Trace
evidence plus the existing domain event and transactional outbox record in
the same transaction. The established outbox projector produces the bounded
activity entry. Idempotent replay creates no duplicate mutation, event,
outbox, Trace, audit, or generation change.

## Security and bounded limitations

- Server-derived authenticated user/workspace/membership scope is
  authoritative.
- Unknown roles, permissions, actions, states, capabilities, resource kinds,
  risks, assignments, or generations fail closed.
- Cross-workspace identifiers do not enumerate authority.
- Owner membership and owner role cannot be changed through 6.2 commands.
- Administrator ceiling checks prevent equal/higher-role manipulation.
- Approval eligibility is not approval and cannot bypass Milestone 4.
- Append-only identities and transitions retain original evidence.

This checkpoint intentionally does not implement typed shares, resource
ownership, ownership transfer, 6.3 authority snapshots or revocation
fencing, bulk revocation, comments, collaboration UI, shared workflow/agent
governance, Advanced Real-Time Collaboration, Milestone 7 Indexer work, or
Milestone 9 Librarian work.

## Validation

Focused collaboration validation passed:

- 15 collaboration registry, migration, service, API, security, concurrency,
  failure-rollback, and end-to-end tests;
- SQLite `0021`→`0022` upgrade, `0022`→`0021` downgrade, and re-upgrade;
- PostgreSQL `0021:0022` offline DDL compilation;
- Ruff formatting/lint, Python compilation, and mypy for the affected slice.

Full repository validation passed:

- backend: 502 passed, 1 skipped, with 36 known deprecation warnings;
- security selection: 36 passed, 467 deselected;
- migration regression set: 24 passed, with 35 known SQLite datetime
  deprecation warnings;
- frontend unit tests: 15 files and 66 tests passed;
- frontend browser smoke tests: 6 passed and 2 environment-only PostgreSQL
  cases skipped;
- frontend ESLint, TypeScript checking, Prettier formatting, and Next.js
  production build passed, with 8 routes generated;
- strict backend mypy passed for 80 source files;
- Python compilation and application imports passed;
- SQLAlchemy mapper validation passed for 108 mapped tables;
- migration validation passed for upgrade, downgrade, and re-upgrade with sole
  Alembic head `20260725_0022`;
- repository hygiene and secret-pattern checks passed for 331 source files;
- Git object integrity, diff/whitespace, dependency-lock, local-path leakage,
  immutable `0021` hash, and prohibited-scope checks passed.

The repository's `pnpm` wrapper remains blocked by its pre-existing ignored
native-build policy for `sharp` and `unrs-resolver`. It made no retained
dependency or workspace configuration change. The same locked frontend tools
were therefore run directly from `apps/web`; all frontend gates above passed.

## Next boundary

Milestone 6.3 may begin only from this completed local checkpoint. It owns
`20260725_0023` and the approved typed sharing, ownership, transfer,
authority-snapshot, and revocation-fencing scope. It must not rewrite
`20260725_0022`.

MILESTONE 6.2 COMPLETE LOCALLY — READY FOR 6.3 RESOURCE SHARING, OWNERSHIP, AND REVOCATION
