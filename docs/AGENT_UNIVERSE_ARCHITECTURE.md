# Agent Universe Architecture Bridge

Milestone 4.0 is planning only. No agents, subagents, delegation, travel, tools, queues, schedules,
or autonomous operation are active.

This document connects the Milestone 3.75 living-universe presentation to future controlled-agent
roles. Visual roles remain semantic labels and never grant execution authority. The normative
Milestone 4 control-plane, permissions, approval, Trace, failure, and phase contract is
`MILESTONE_4_CONTROLLED_AGENT_ARCHITECTURE.md`.

This bridge does not add active execution, database tables, background work, provider consumption,
or user-visible agent activity.

## Scope Levels

- Universe coordinator: future metadata-only router; it has no implicit content or cross-workspace
  authority.
- Galaxy analyst: future read-only helper limited to one user-owned workspace.
- Solar-system researcher: future selected-context helper limited to one canvas or project area.
- Planet specialist: future object-scoped helper limited to one document, note, answer, or durable
  knowledge object.
- Evidence verifier: future read-only helper limited to exact citations, chunks, claims, passages,
  or sections.
- Controlled action executor: future effectful role limited to an exact approved action plan.

These roles are descriptions, not permissions. A future server-minted capability grant determines
the effective scope and allowed tools for one execution.

## Ownership and Isolation

Agent scope must inherit the existing Milestone 3.5 ownership model:

- Users own workspaces.
- Workspaces isolate canvases, notes, documents, chunks, executions, citations, Trace records, jobs, and settings.
- Server-side authorization remains mandatory for every read and write.
- Future delegation cannot expand access beyond the current authenticated user and workspace boundary.

## Permission Narrowing

Permissions should narrow as scope becomes smaller:

- Universe scope may route across authorized workspaces but cannot bypass workspace checks.
- Galaxy scope is bound to one workspace.
- Solar-system scope is bound to one canvas or project cluster.
- Planet scope is bound to one object and its authorized child records.
- Evidence-fragment scope is bound to specific citations, chunks, claims, passages, or sections.

Future records should store the effective permission scope used for each action.

## Context Boundaries

Future agent context must be explicit and auditable:

- Selected nodes
- Selected documents
- Source versions
- Included chunks
- Excluded chunks
- Exclusion reasons
- Prompt-template version
- User approval state where required

Uploaded document instructions remain untrusted content and must never override system, developer, authorization, retrieval, citation, or safety rules.

## Resource, Tool, and Pathway Access

Future agents may only access resources, tools, and pathways authorized by their narrowed scope. Every future tool call should record:

- User ID
- Workspace ID
- Scope level
- Tool identifier
- Resource identifiers
- Start and completion timestamps
- Status
- Safe error category
- Token and cost impact where applicable

No API keys, authorization headers, hidden system instructions, private provider diagnostics, or internal filesystem paths may appear in user-visible Trace records.

## Delegation Records

Delegation is disabled in Milestone 4.0–4.3. If bounded child work is explicitly accepted in 4.4,
it must be nonrecursive, limited to one child level, and strictly narrower than the parent grant.
Records should capture:

- Parent execution
- Child execution
- Delegation reason
- Assigned scope
- Allowed tools
- Context snapshot
- Human approval requirement
- Stop condition
- Result summary
- Failure category

Delegation must preserve comparison and replay requirements already established for original-context and current-context reruns.

## Trace Requirements

Every future agent action must write complete Trace records equivalent to current AI execution Trace quality:

- Who acted
- Which workspace and canvas were in scope
- What context was available
- Which resources were read or written
- Which provider or tool was used
- What evidence supported the result
- What was excluded and why
- Whether the action completed, failed, retried, or stopped

## Token, Cost, and Abuse Limits

Future agent work must respect existing cost controls:

- Per-user limits
- Per-workspace limits
- Context-size limits
- Retrieval limits
- Output limits
- Retry limits
- Provider-configuration fail-closed behavior

Agents must stop rather than silently switching to mock providers in staging or production.

## Human Approval Boundaries

Future agents require explicit human approval before:

- Deleting user data
- Sharing or exporting private data
- Spending meaningful provider budget
- Uploading files externally
- Changing permissions
- Running cross-workspace operations
- Taking irreversible actions

## Failure Isolation

Failures must remain scoped:

- A failed planet specialist must not corrupt the whole galaxy.
- Delayed future agent work must not resurrect deleted documents or objects.
- Failed or partial processing must not appear searchable.
- Retry exhaustion must produce diagnosable permanent-failure state.

## Future Migration Needs

Milestone 4.1 may propose reviewed migrations for:

- Agent scope records
- Delegation records
- Tool-call records
- Approval records
- Agent-specific usage accounting
- Agent Trace relationships

Those migrations are intentionally not added in Milestone 4.0 because this checkpoint is planning
only.
