# Milestone 6.5 Invocation Identity Migration Amendment

Date: 2026-07-26

Branch: `milestone-6-5-invocation-identity-migration-amendment-local`

Starting commit: `39a791c5a8ecf3932617ba72b83cbeb4806b4c34`

Status: documentation-only migration allocation complete locally; Milestone
6.5 implementation and migration remain unstarted

## Blocking conflict

The approved Milestone 6 architecture requires every shared workflow
invocation and shared agent invocation to remain attributed to the exact
authenticated invoking user and active membership. Definition creator,
current resource owner, membership, action authority, and approval authority
remain distinct.

The governed operations are:

- shared workflow invocation; and
- shared agent invocation.

The attempted 6.5 implementation inspection proved that current persistence
cannot represent a shared invocation truthfully:

- `ControlledWorkflowExecution.user_id` participates in the composite foreign
  key to the immutable workflow version's owner-scoped `user_id`;
- `BoundedAgentInvocation.user_id` participates in composite foreign keys to
  both the immutable agent version and resulting workflow execution;
- workflow version lookup requires the requester to equal the immutable
  workflow definition/version owner; and
- Agent Studio identity and version lookup similarly require requester and
  immutable definition owner to be the same user.

A shared member therefore cannot invoke another user's workflow or agent while
remaining the recorded invoker. Substituting the definition owner would make
audit, Trace, request/idempotency ownership, membership, authority snapshot,
revocation, and activity attribution false.

The 6.5 run stopped before branch creation, production changes, tests, or
migration creation, as required by the migration-boundary safety rule.

## Permanent identity distinction

Milestone 6.5 persistence must keep these concepts separate:

1. **Definition owner:** the exact historical user/owner scope associated with
   the workflow or agent identity and its immutable versions.
2. **Invoking user:** the exact authenticated user who requests a workflow
   execution or agent invocation.
3. **Invoking membership:** the exact active workspace membership through
   which collaboration visibility and invocation permission are resolved.
4. **Invocation authority evidence:** the exact visibility basis, typed share
   or inheritance basis, permission, authority generation and snapshot,
   capability grants, approvals, policy decision, request identity, execution
   identity, Trace identity, and audit identity.

Definition ownership grants no automatic invocation. Invocation transfers no
definition ownership. Revocation and stale-authority evaluation follow the
invoking user's membership and authority, not merely the definition owner's
state.

## Approved migration allocation

Migration `20260725_0025` belongs exclusively and completely to Milestone 6.5.

- Direct parent: `20260725_0024`
- Current Alembic head before implementation: `20260725_0024`
- `20260725_0025` status: planned and allocated, not created
- Ownership rule: create, complete, validate, and commit the migration wholly
  within 6.5; never leave it partial for a later checkpoint
- Immutability rule: after commit, any correction uses the next unused
  revision

Final alignment:

- 6.1 -> `20260725_0021` — complete and immutable
- 6.2 -> `20260725_0022` — complete and immutable
- 6.3 -> `20260725_0023` — complete and immutable
- 6.4 -> `20260725_0024` — complete and immutable
- 6.5 -> `20260725_0025` — planned, exclusively allocated, not created
- 6.6 -> no migration currently assigned
- 6.7 -> no migration currently assigned

## Required semantic persistence

The eventual migration and implementation must provide, where required by the
final repository-grounded design:

- an exact definition-owner or owner-scope field used by immutable workflow
  version foreign keys;
- an exact definition-owner or owner-scope field used by immutable agent
  version foreign keys;
- `user_id`, or an equivalently clear field, retained as the authenticated
  invoking user on workflow executions and agent invocations;
- exact invoking-membership persistence;
- exact tenant, workspace, canvas, resource, parent identity, immutable
  version, definition owner, invoker, membership, execution, authority
  snapshot, Trace, and audit scope;
- authority-snapshot linkage for shared invocation;
- collaboration visibility and invocation-permission linkage;
- shared-agent authority evidence linked to the resulting workflow execution
  where applicable;
- exact parent identity and immutable-version ownership validation;
- preservation of existing execution and invocation identities; and
- preservation of append-only execution, Trace, audit, event, outbox,
  activity, request-idempotency, retry, cancellation, compensation, export,
  and publication histories.

Exact column names remain an implementation decision unless an existing
repository convention makes them unambiguous. The semantic identities and
defensive constraints above are mandatory.

## Legacy backfill

Rows created before shared invocation used one owner-scoped user identity.
For each legacy row:

- definition owner equals the existing recorded user;
- invoking user equals the existing recorded user;
- invoking membership is derived deterministically from exact historical
  workspace-membership evidence where available;
- existing execution and invocation identities remain unchanged; and
- existing Trace and audit meaning is not rewritten.

Before creating `0025`, the final implementation plan must decide and test how
to handle a row whose exact historical membership cannot be derived safely.
The migration must fail closed or use a separately approved deterministic
compatibility state. It must never invent an actor or membership.

## Foreign-key and scope requirements

Migration `0025` must defensively preserve exact scope across:

- tenant and workspace;
- canvas where applicable;
- workflow identity and immutable workflow version;
- agent identity and immutable agent version;
- definition owner;
- invoking user and invoking membership;
- workflow execution and agent invocation;
- authority snapshot;
- Trace identity; and
- audit identity.

The schema and services must prevent:

- a version associated with the wrong parent identity;
- owner/invoker substitution in either direction;
- membership from another workspace;
- workflow execution linked to an unrelated workflow version;
- agent invocation linked to an unrelated agent version or workflow
  execution;
- cross-tenant or cross-workspace identity substitution; and
- client-supplied owner, invoker, membership, permission, generation, or
  authority identities being trusted.

SQLite and PostgreSQL receive the defensive constraints and append-only
protections required by repository policy. Upgrade, downgrade to `0024`, and
re-upgrade must preserve history without destructive loss.

## Authority, evidence, and revocation

Every shared invocation binds:

- exact invoking user and active membership;
- current visibility basis and invocation permission;
- exact parent identity and immutable version;
- current lifecycle and authority generation;
- immutable authority snapshot;
- applicable capability grants, approvals, risk and policy decision;
- selected context, context/plan/request/version digests;
- request and execution identities; and
- Trace and audit identities.

The existing Milestone 4 capability, grant, approval, policy, context,
execution, retry, cancellation, effect, compensation, and publication checks
remain authoritative. Collaboration visibility or permission cannot replace
them.

Revocation, role reduction, membership suspension/removal, share change,
ownership transfer, lifecycle change, capability or approval revocation, and
generation change revalidate the invoker's captured authority at every
protected boundary. Stale claims, calls, retries, effects, compensation,
export, and publication fail closed. Historical committed evidence remains
append-only.

Trace, audit, domain events, transactional outbox, activity projection, and
request idempotency extend the existing systems. They retain bounded,
non-secret facts and cannot expose private prompts, grants, approval
internals, authority snapshots, credentials, or model chain of thought.

## Explicit exclusions

Revision `0025` contains no persistence for:

- the 6.6 multi-workspace interface or collaboration-administration UI;
- Advanced Real-Time Collaboration, presence, cursors, CRDT/OT, or offline
  merging;
- Indexer or managed production infrastructure;
- Academy, Catalog, Librarian, marketplace, reputation, or Agent Society;
- simulated worlds, spatial intelligence, federation, or continuity; or
- any Milestone 6.6 or later checkpoint.

The product-family roadmap is unchanged: Milestone 8.0 remains Mobius Core
1.0, Milestone 8.5 remains optional Mobius Core 1.5 Advanced Collaboration,
Milestones 9–13 remain separate product lines, and Milestone 11 remains before
Milestone 12.

## Repository state and restart baseline

This amendment changes documentation only. Migrations `20260725_0021` through
`20260725_0024` remain unchanged. Migration `20260725_0025` does not exist.
No production code, test, dependency, configuration, CI, deployment,
frontend, backend, service, API, or Milestone 6.5 implementation is added.

Milestone 6.5 may restart only from the committed local amendment branch and
SHA recorded in its final handoff, with:

- a clean working tree;
- no upstream and no remote operation;
- sole Alembic head `20260725_0024`;
- unchanged migrations `0021` through `0024`;
- migration `0025` absent but exclusively allocated to 6.5;
- protected references unchanged; and
- the semantic identity, backfill, authority, evidence, revocation, and
  exclusion rules in this amendment treated as authoritative.
