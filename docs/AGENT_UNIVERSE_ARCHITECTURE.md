# Future Agent Universe Architecture

No agents, subagents, delegation, travel, or autonomous operation are active in Milestone 3.75.

This document records future extension points for the living knowledge universe. It is design and architecture preparation only. It does not add active agent execution, database tables, background autonomous work, provider consumption, or user-visible agent activity.

## Scope Levels

- Universe orchestrator: future application-level coordinator across authorized galaxies.
- Galaxy agent: future workspace-scoped helper limited to one user-owned workspace.
- Solar-system subagent: future project-cluster helper limited to one canvas or project area.
- Planet specialist: future object-scoped helper limited to one document, note, answer, or durable knowledge object.
- Lower-level worker: future task helper limited to citations, chunks, claims, passages, or sections.

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
- Lower-level scope is bound to specific evidence fragments or processing records.

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

If delegation is added in a future milestone, records should capture:

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
- A delayed lower-level worker must not resurrect deleted documents.
- Failed or partial processing must not appear searchable.
- Retry exhaustion must produce diagnosable permanent-failure state.

## Future Migration Needs

Future implementation may require migrations for:

- Agent scope records
- Delegation records
- Tool-call records
- Approval records
- Agent-specific usage accounting
- Agent Trace relationships

Those migrations are intentionally not added in Milestone 3.75 because no active agent feature is being implemented.
