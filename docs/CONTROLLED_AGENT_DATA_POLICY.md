# Controlled-agent data retention and erasure policy

## Status and scope

This document is an **engineering policy proposal** for the controlled-agent persistence added in
Milestones 4.1A and 4.1B. It has not received legal, privacy, compliance, security, or operations
approval. Nothing in this document should be represented as an approved legal retention schedule.

This proposal does not implement retention jobs, legal holds, cryptographic erasure, production
deletion workflows, redaction services, or operator tooling. It defines the controls and approvals
required before sensitive controlled-agent data can be accepted in production. The existing
controlled-agent records remain inert security evidence; Milestone 4.2 behavior is outside scope.

## Data classification

Hashes can remain linkable to a person or source and can reveal equality or support inference. A
canonical hash does **not** make personal or source-derived data anonymous.

### Append-only record families

| Record family               | Purpose                                                                            | Sensitivity                                    | Ownership scope                              | Personal data possible                    | Source-derived content possible                                        | Append-only | Security, audit, or replay need                            |
| --------------------------- | ---------------------------------------------------------------------------------- | ---------------------------------------------- | -------------------------------------------- | ----------------------------------------- | ---------------------------------------------------------------------- | ----------- | ---------------------------------------------------------- |
| Execution identities        | Bind one proposed execution to its role, context, plan, grant, user, and workspace | Confidential security metadata                 | One user and one owned workspace             | Yes, through identifiers and associations | Indirectly through snapshot references and digests                     | Yes         | Root of scope, provenance, and authorization evidence      |
| Execution state transitions | Preserve ordered lifecycle decisions and safe failure reasons                      | Confidential operational and security metadata | Same user/workspace/execution tuple          | Yes, through associations                 | Normally no raw content; reason codes may reveal activity              | Yes         | Audit chronology and failure investigation                 |
| Context snapshots           | Preserve the exact selected context used for policy and later verification         | Highly confidential content                    | Same user/workspace/execution tuple          | Yes                                       | Yes; payloads may contain notes, source text, and references           | Yes         | Context integrity, dispute review, and digest verification |
| Plan snapshots              | Preserve the exact proposed plan bound to authority                                | Highly confidential content                    | Same user/workspace/execution tuple          | Yes                                       | Yes; plans may restate source-derived facts                            | Yes         | Approval integrity and plan-substitution prevention        |
| Capability grants           | Record narrowly scoped, expiring authority and its canonical binding               | Confidential security data                     | Same user/workspace/execution tuple          | Yes, through identifiers and scope        | Payload may carry resource references but should avoid raw content     | Yes         | Authorization proof and least-privilege review             |
| Grant revocations           | Prove that authority was withdrawn and why                                         | Confidential security data                     | Same grant/user/workspace/execution tuple    | Yes, through associations                 | Normally no; reason payloads must remain minimal                       | Yes         | Immediate deny decisions and incident review               |
| Approvals                   | Preserve the human decision bound to exact scope and digests                       | Highly confidential security and decision data | Same grant/user/workspace/execution tuple    | Yes, including decision attribution       | Payload may describe the proposed action or source context             | Yes         | Non-repudiation, approval validation, and dispute review   |
| Policy decisions            | Record allow, deny, or approval-required outcomes and reason codes                 | Confidential security data                     | Same user/workspace/execution tuple          | Yes, through associations                 | Normally no raw content; digests and reasons remain linkable           | Yes         | Explainability, enforcement review, and denial evidence    |
| Approval consumptions       | Prove one-time use of an approval                                                  | Confidential replay-prevention data            | Same approval/user/workspace/execution tuple | Yes, through associations                 | No raw content expected                                                | Yes         | Mandatory replay prevention                                |
| Audit events                | Preserve typed security and execution events linked to Trace                       | Confidential security telemetry                | Same user/workspace/execution tuple          | Yes; attributes must be minimized         | Attributes may reference sources but must not contain unnecessary text | Yes         | Security investigation, accountability, and chronology     |

### Common fields and related references

| Category                       | Purpose and handling                                                                                                                                                       |
| ------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| User identifiers               | Direct ownership links and personal data. Restrict to authorized scope and plan for pseudonymous replacement on approved erasure.                                          |
| Workspace identifiers          | Tenant-isolation links that may be personal or commercially sensitive. Never accept them as authority merely because a client supplied them.                               |
| Canvas identifiers             | Resource-scope references that may reveal user activity and workspace structure. Include only when required.                                                               |
| Document and source references | Potentially sensitive links to private content. Retain the minimum versioned reference needed for evidence and remove active source content under approved deletion rules. |
| Canonical hashes               | Integrity and replay-prevention evidence. Treat as potentially personal and source-linked, not anonymous. Do not recalculate historical hashes during redaction.           |
| Timestamps                     | Security chronology that can reveal user activity patterns. Use precise values only in authorized views.                                                                   |
| Safe error categories          | Operational evidence intended to avoid raw diagnostics. They may still disclose activity or failure type and require scoped access.                                        |
| Provider or model metadata     | Provenance and cost/security evidence. It may reveal customer configuration; never store credentials, headers, hidden instructions, or unrestricted diagnostics.           |

All ten record families are scoped to one execution, user, and workspace. Existing composite
constraints and ownership-scoped reads enforce that relationship. Payload minimization remains
mandatory even when a table is append-only.

## Proposed retention schedule

Every duration below is a proposal, not an approved legal requirement.

| Data or state                                    | Proposed retention                                                                                  | Rationale                                                                  | Approval status                                                                            |
| ------------------------------------------------ | --------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| In-progress executions                           | While active; after terminal state, follow the applicable completed or failed execution policy      | Preserve current control state without creating indefinite active records  | Proposed engineering default — requires privacy, legal, security, and operations approval. |
| Completed execution identities and state history | 12 months after completion                                                                          | Investigation, provenance, and authorization evidence                      | Proposed engineering default — requires privacy, legal, security, and operations approval. |
| Context and plan snapshots                       | 90 days after terminal state unless required for a dispute, security review, or approved legal hold | Reduce sensitive payload exposure while retaining a bounded review window  | Proposed engineering default — requires privacy, legal, security, and operations approval. |
| Capability grants and revocations                | 12 months after grant expiry or revocation                                                          | Prove historical authority and revocation                                  | Proposed engineering default — requires privacy, legal, security, and operations approval. |
| Approvals and approval consumptions              | 12 months after decision or consumption                                                             | Approval accountability and replay evidence                                | Proposed engineering default — requires privacy, legal, security, and operations approval. |
| Denied policy decisions                          | 12 months after evaluation                                                                          | Abuse detection, policy review, and dispute evidence                       | Proposed engineering default — requires privacy, legal, security, and operations approval. |
| Security audit events                            | 24 months after recording                                                                           | Longer security investigation and incident-response window                 | Proposed engineering default — requires privacy, legal, security, and operations approval. |
| Failed execution records                         | 12 months after terminal failure                                                                    | Reliability analysis, safe-error review, and security investigation        | Proposed engineering default — requires privacy, legal, security, and operations approval. |
| Operational logs outside append-only tables      | 30–90 days according to approved log class                                                          | Minimize broad telemetry while supporting operations and incident response | Proposed engineering default — requires privacy, legal, security, and operations approval. |
| Account-deletion tombstones                      | Minimal pseudonymous record for the shortest approved security period                               | Prevent silent history loss while minimizing retained identity             | Proposed engineering default — requires privacy, legal, security, and operations approval. |
| Export-request records                           | 90 days after completion or failure; exported artifacts may require a shorter expiry                | Support delivery troubleshooting without indefinite export retention       | Proposed engineering default — requires privacy, legal, security, and operations approval. |

Retention expiry must create an auditable disposition outcome. Expiry must not be inferred merely
from a grant, approval, session, or signed URL becoming unusable.

## Account deletion and erasure

Immutable history must not be edited or silently deleted in place. Today, account deletion revokes
sessions, deletes private uploaded files, removes current workspace records, and deletes the user.
The controlled-agent tables instead use restrictive user/workspace relationships and append-only
mutation guards. Those behaviors are not yet reconciled; an account with controlled-agent evidence
cannot be accepted for production until an approved erasure workflow exists.

A future deletion workflow should perform, in an authorized and recoverable sequence:

1. Deactivate the account and immediately revoke sessions, grants, pending approvals, and access.
2. Stop new processing and prevent new controlled-agent activity for affected workspaces.
3. Delete private uploaded file bytes, current document content, chunks, embeddings, and retrieval
   indexes, including authorized storage copies.
4. Detach retained evidence from direct account identity and replace user/workspace identifiers
   with purpose-specific pseudonymous identifiers under an approved mapping policy.
5. Expose redacted projections rather than raw append-only payloads after deletion.
6. Record retention-expiry and deletion outcomes as minimal append-only audit events.
7. Use cryptographic erasure for encrypted context and plan payloads when their retention ends.
8. Remove temporary exports, test copies, caches, and operational copies under the same request.

Temporary retention may be necessary for security investigations, fraud prevention,
approval-replay evidence, contractual requirements, or legal holds. Every exception requires an
approved policy, recorded authority, bounded review date, access logging, and the minimum necessary
data. A security interest does not justify retaining all source content by default.

## Legal holds

A future legal-hold contract must contain:

- hold ID and immutable audit trail;
- exact scope and covered users, workspaces, executions, and record types;
- authority, reason, creator, approver, and release authority;
- start time, next review date, release time, and current status;
- the effect on pending deletion, retention expiry, backups, exports, and restored copies.

Creating, changing, reviewing, or releasing a hold must require separate authorized roles and must
never be inferred from an ordinary application request. A hold pauses only the covered disposition;
it does not grant broader read access.

No legal-hold API is implemented. No legal-hold process is approved. Production use requiring
legal holds remains blocked until the process is legally reviewed, operationally owned,
implemented, tested, and auditable.

## Redaction and authorized views

The system must distinguish these representations:

| Representation                      | Purpose                                                                                                                  |
| ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| Immutable stored record             | Original integrity and replay evidence, accessible only under narrowly authorized internal controls                      |
| Authorized internal inspection view | Bounded operational view; the current GET-only inspection is an initial safe projection, not a complete privacy workflow |
| Redacted user-facing view           | Workspace-scoped presentation that omits data no longer needed by the user                                               |
| Data-export view                    | Authenticated, purpose-limited export with documented omissions, expiry, and delivery controls                           |
| Security-review view                | Time-bounded, approved view with reason, operator identity, and access audit                                             |

Views must redact or omit:

- direct personal identifiers when not required for the authorized purpose;
- source-derived text, prompt content, and plan content beyond the minimum needed;
- provider diagnostics and unnecessary model configuration;
- internal object, storage, and service references not intended for the recipient;
- raw error details, stack traces, and private paths;
- issuing-service information and session identifiers;
- credentials, secrets, cookies, authorization headers, tokens, and key material in all cases.

Redaction changes the view, not the stored historical hash. Historical hashes must not be
recalculated or replaced to conceal data. If a payload becomes unreadable through approved key
destruction, retained metadata must say so without pretending that the original hash changed.

## Cryptographic erasure

**Required before production acceptance of sensitive controlled-agent snapshot payloads.**

The future design should use envelope encryption for context and plan snapshot payloads:

- encrypt payloads with per-user or per-workspace data-encryption keys;
- wrap those keys with a managed key-encryption key held outside the application database;
- define rotation for key-encryption and data-encryption keys without weakening audit evidence;
- revoke access immediately and destroy the applicable data-encryption key after approved expiry
  or erasure;
- retain only minimal non-sensitive metadata and the historical digest after key destruction;
- create audited key-destruction records with authority, scope, time, outcome, and failure state;
- ensure backups cannot silently restore destroyed plaintext keys or usable payloads;
- test restore behavior, rotation, partial failure, retry, and legal-hold exclusion.

No envelope encryption, per-user/workspace key hierarchy, or cryptographic key-destruction workflow
is implemented for these tables today.

## Backups, replicas, logs, and copies

Deletion is not complete merely because primary application access is removed. Approved retention
and deletion procedures must cover:

- database backups and point-in-time recovery archives;
- read replicas and delayed replicas;
- object-storage versions, multipart remnants, and lifecycle policies;
- operational logs, error tracking, and analytics systems;
- test databases, fixtures derived from real data, and staging copies;
- developer exports, local diagnostics, and support copies.

Backup expiry must be bounded and documented. Restored copies must reapply deletion tombstones,
holds, expired-key state, and access restrictions before becoming available. Test-copy deletion and
sanitization must be verified. Developer and support copies require explicit authorization,
expiry, encryption, and access logging. Analytics ingestion must either exclude sensitive payloads
or implement the same disposition controls.

## Required approvals

| Reviewer            | Required review                                                                                    | Status           |
| ------------------- | -------------------------------------------------------------------------------------------------- | ---------------- |
| Engineering         | Feasibility, invariants, migration, deletion orchestration, restore behavior, and test plan        | Not yet approved |
| Security            | Threat model, access roles, audit integrity, key lifecycle, incident response, and abuse cases     | Not yet approved |
| Privacy             | Data classification, minimization, erasure rights, pseudonymization, exports, and processor copies | Not yet approved |
| Legal or compliance | Retention basis, legal holds, contractual duties, jurisdiction, and recordkeeping                  | Not yet approved |
| Operations          | Backup/restore, key custody, monitoring, support access, runbooks, and evidence of execution       | Not yet approved |

Production acceptance remains blocked until the applicable reviewers approve a versioned policy
and engineering proves its enforcement against production-shaped infrastructure.

## Engineering enforcement gap table

| Control                          | Current status                                                                                         | Evidence                                                                                                | Remaining gap                                                                              | Required owner                          | Target milestone or review                | Production blocker                  |
| -------------------------------- | ------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ | --------------------------------------- | ----------------------------------------- | ----------------------------------- |
| Append-only ORM guards           | Implemented and tested                                                                                 | SQLAlchemy update/delete listeners and focused persistence tests                                        | Ensure all privileged maintenance paths preserve the invariant                             | Engineering, Security                   | Production security review                | No, if database controls also pass  |
| SQLite append-only triggers      | Implemented and tested                                                                                 | Migration `20260721_0007` and SQLite migration/persistence tests                                        | Keep parity tests with future schema changes                                               | Engineering                             | Every controlled-agent migration          | No                                  |
| PostgreSQL append-only triggers  | Implemented; authoritative integration test exists; NOT RUN because PostgreSQL/Docker was unavailable. | Migration trigger function plus `test_agent_postgres.py`                                                | Run against disposable PostgreSQL in CI/local infrastructure and preserve evidence         | Engineering, Operations                 | Before production acceptance              | Yes until authoritative test passes |
| Composite ownership constraints  | Implemented and tested                                                                                 | Composite foreign keys bind execution, user, and workspace                                              | Revalidate every new child record family                                                   | Engineering, Security                   | Every schema review                       | No for current schema               |
| Approval replay prevention       | Implemented and tested                                                                                 | Unique consumption constraint and atomic policy decision/consumption service                            | Production concurrency/load verification                                                   | Engineering, Security                   | Before effect-capable phase               | Yes before effects                  |
| Safe read-only inspection        | Partially implemented                                                                                  | Authenticated GET projection is bounded and omits raw payloads and issuing-service/session data         | Formal redaction roles, export view, operator view, and privacy tests                      | Engineering, Privacy, Security          | Before production controlled-agent access | Yes                                 |
| User/workspace authorization     | Implemented and tested                                                                                 | Ownership-scoped repository query joins active owned workspace                                          | Extend tests to all future views and operator paths                                        | Engineering, Security                   | Every new endpoint                        | No for current GET path             |
| Account deletion                 | Partially implemented                                                                                  | Existing account route removes files/workspaces and revokes sessions; controlled-agent FKs use RESTRICT | Reconcile deletion with append-only evidence, pseudonymization, holds, and key destruction | Engineering, Privacy, Legal             | Privacy design review                     | Yes                                 |
| Workspace deletion               | Partially implemented                                                                                  | Existing workspace/canonical lifecycle controls; controlled-agent records restrict workspace deletion   | Define deletion orchestration and retained-evidence detachment                             | Engineering, Privacy                    | Privacy design review                     | Yes                                 |
| Snapshot retention               | Documented only                                                                                        | Proposed 90-day context/plan schedule in this policy                                                    | Approved schedule, expiry state, disposition workflow, tests, and monitoring               | Privacy, Legal, Engineering, Operations | Retention implementation milestone        | Yes                                 |
| Source-reference retention       | Documented only                                                                                        | Classification and minimization rules in this policy                                                    | Exact reference taxonomy, deletion behavior, and version-retention tests                   | Privacy, Engineering                    | Retention implementation milestone        | Yes                                 |
| Audit retention                  | Documented only                                                                                        | Proposed 24-month audit-event schedule                                                                  | Approval, expiry enforcement, legal-hold integration, and evidence reports                 | Security, Legal, Operations             | Audit policy review                       | Yes                                 |
| Pseudonymization                 | Not implemented                                                                                        | Future deletion model in this policy                                                                    | Identifier replacement design, mapping custody, reidentification controls, and tests       | Privacy, Security, Engineering          | Privacy implementation milestone          | Yes                                 |
| Redacted projections             | Partially implemented                                                                                  | Current inspection omits raw payloads and sensitive internal fields                                     | Purpose-specific user/export/security views and tested redaction policy                    | Privacy, Security, Engineering          | Before production controlled-agent access | Yes                                 |
| Legal holds                      | Not implemented                                                                                        | Proposed contract in this policy                                                                        | Approved process, separation of duties, API/service, backup integration, and tests         | Legal, Privacy, Security, Operations    | Legal-hold review                         | Yes where holds are required        |
| Encryption at rest               | Partially implemented                                                                                  | Deployment can rely on database/storage platform encryption; no controlled-agent-specific proof         | Document vendor controls, key custody, rotation, and restore verification                  | Security, Operations                    | Deployment acceptance review              | Yes for sensitive production data   |
| Per-user/workspace encryption    | Not implemented                                                                                        | Future envelope-encryption design in this policy                                                        | Key hierarchy, payload migration, rotation, access policy, and tests                       | Security, Engineering, Operations       | Cryptographic-erasure milestone           | Yes for sensitive snapshots         |
| Cryptographic key destruction    | Not implemented                                                                                        | Future erasure design in this policy                                                                    | Approved destruction authority, workflow, evidence, failures, backups, and restore tests   | Security, Privacy, Operations           | Cryptographic-erasure milestone           | Yes for sensitive snapshots         |
| Backup erasure                   | Not implemented                                                                                        | Backup obligations documented here and in deployment guidance                                           | Backup inventory, expiry enforcement, tombstone replay, key-state restore tests            | Operations, Security, Privacy           | Disaster-recovery/privacy review          | Yes                                 |
| Export behavior                  | Partially implemented                                                                                  | Authenticated export-request entry point exists                                                         | Artifact generation, controlled-agent coverage, redaction, delivery, expiry, and deletion  | Engineering, Privacy, Security          | Export implementation review              | Yes for production privacy requests |
| Operator access                  | Not implemented                                                                                        | No controlled-agent audit-administrator workflow exists                                                 | Least-privilege roles, reason capture, time bounds, approvals, and access audit            | Security, Operations, Privacy           | Operations/security review                | Yes                                 |
| Monitoring and incident response | Partially implemented                                                                                  | Structured application observability and safe error categories exist                                    | Controlled-agent retention/erasure/key/hold alerts, runbooks, ownership, and exercises     | Security, Operations                    | Production readiness review               | Yes                                 |

## Acceptance boundary

This proposal is complete as documentation only. It does not authorize production controlled-agent
payloads or active agent behavior. Implementation must proceed through separately approved,
testable checkpoints and must preserve the deterministic demo boundary.
