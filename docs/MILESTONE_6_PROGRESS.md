# Milestone 6 Progress — Core Multi-Workspace Collaboration

Last updated: 2026-07-25

Branch: `milestone-6-multi-workspace-collaboration-architecture-local`

Baseline: `01a38526320560d54033bed510b0f15a7e77eea7`

Status: architecture complete locally; implementation not started

| Checkpoint                                       | Status           | Dependency                        |
| ------------------------------------------------ | ---------------- | --------------------------------- |
| Architecture                                     | Complete locally | Milestone 5 and roadmap amendment |
| 6.1 Workspace Membership and Invitations         | Not started      | Architecture                      |
| 6.2 Collaboration Roles and Permission Authority | Not started      | 6.1                               |
| 6.3 Resource Sharing, Ownership, and Revocation  | Not started      | 6.1–6.2                           |
| 6.4 Comments and Collaboration Activity          | Not started      | 6.1–6.3                           |
| 6.5 Shared Workflow and Agent Governance         | Not started      | 6.1–6.4 and Milestones 4–5        |
| 6.6 Multi-Workspace Collaboration Interface      | Not started      | 6.1–6.5                           |
| 6.7 Final Collaboration Security Audit           | Not started      | 6.1–6.6                           |

## Architecture decisions

- Extend current owner-only authorization seams with one central
  collaboration resolver.
- Keep Milestone 4 capability, grant, risk, approval, digest, and revocation
  checks authoritative.
- Use one closed role per membership; no role unions or free-text
  permissions.
- Role is a ceiling. Exact typed resource ownership/share/inheritance is also
  required.
- Keep invitation pre-acceptance evidence separate from active membership so
  every membership has an exact user.
- Preserve one workspace owner with accepted transfer and no orphan state.
- Keep creator, owner, membership, action authority, and approval authority
  distinct.
- Extend Milestone 4 approval with reviewer-eligibility evidence rather than
  create another approval system.
- Fence revocation with monotonic workspace, membership, share, and approval
  generations.
- Use typed shares for canvas, canonical resources, workflows, and agents.
- Treat immutable versions as children of the shared identity; never share
  them independently.
- Keep source/Bundle export separate from read access.
- Store comments as escaped plain text with immutable identities,
  append-only revisions, and tombstones.
- Extend existing domain events, outbox, and activity; add no second feed.
- Preserve PostgreSQL RLS and real-time collaboration as future adapter
  options, not current claims or schema.

## Closed role model

The initial registry is owner, administrator, editor, approver, member, and
viewer. A membership has exactly one current role. Owner controls transfer;
administrator manages bounded membership/sharing; editor changes explicitly
accessible resources; approver reviews only exact assigned classes; member
participates only where shared; viewer is read-only.

No role bypasses Milestone 4 or independently supplies resource visibility,
invocation, approval, export, or controlled-effect authority.

## Planned persistence

- `20260725_0021`: memberships, invitation identity/state/secret/delivery,
  idempotency, owner-membership backfill, workspace authority version.
- `20260725_0022`: role/approval authority, typed shares, ownership transfer,
  resource ownership, execution authority snapshots, revocation fencing.
- `20260725_0023`: comments/revisions/states, collaboration event/audience and
  activity support, optional bounded notification state only if justified.

No migration has been created. Alembic remains at sole head
`20260725_0020`.

## Scope boundaries

Milestone 6 core includes memberships, invitations, roles, sharing, ownership,
revocation, comments, activity, shared workflow/agent governance, frontend
management, and final tenant-security audit.

Basic presence is optional stretch scope and not required.

Advanced Real-Time Collaboration remains after the initial Milestone 8
release. No cursors, detailed presence, simultaneous editing, CRDT, OT,
offline merge, reconnect reconciliation, or distributed real-time
infrastructure is designed for implementation here.

Milestone 7 retains Production Hardening and the deterministic Indexer.
Milestone 9 retains the governed Librarian and Agent Society. Milestones 7–13
remain unstarted.

## Current implementation state

This architecture pass changes documentation only. It adds no backend or
frontend code, model, schema, migration, API, test, fixture, dependency,
configuration, CI, deployment, collaboration event, or placeholder.

Next authorized implementation start:
`MILESTONE 6.1 — WORKSPACE MEMBERSHIP AND INVITATIONS`
