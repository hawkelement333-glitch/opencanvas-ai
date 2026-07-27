# Mobius Family Architecture Constitution

Date: 2026-07-27

Status: binding family governance established locally; documentation-only
amendment; technical implementation and release evidence remain independently
verifiable

Authoritative amendment baseline:

- parent SHA: `7189f8770e35403a9f67c7b254a1b5bd2edd5b27`;
- branch: `milestone-7-family-architecture-constitution`;
- Alembic sole head: `20260725_0025`;
- migrations `0026`, `0027`, and `0028`: absent;
- Milestone 7.2: not started.

## 1. Purpose and protected boundary

This constitution defines the minimum protected architecture, security,
privacy, reliability, migration, AI-governance, operations, and release
requirements inherited by every verified SolarPlexus Mobius family product.
It establishes:

- the Mobius Family Security Constitution;
- the Mobius Family Release Readiness Constitution;
- the Same-Milestone Control Rule;
- the product-profile and inheritance model;
- the release-readiness matrix;
- exception governance; and
- evidence-freshness and revalidation requirements.

Milestone 8.0 is the final proof and release-decision gate. It is not the first
point at which security, reliability, privacy, migration, deployment, or
operational risks may be addressed. A capability lacking its required
same-milestone controls MUST remain disabled and inaccessible until those
controls are complete.

This amendment changes documentation and governance only. It does not prove
that a technical control is implemented, does not certify a product or
environment, does not approve a release or exception, does not change an
existing milestone scope, and does not start Milestone 7.2.

## 2. Normative language and evidence states

- **MUST** and **MUST NOT** define protected requirements.
- **SHOULD** defines an expected control that permits only a recorded,
  approved, time-bounded exception.
- **MAY** identifies an optional implementation choice.

Every control record MUST distinguish these states:

| State                                    | Meaning                                                                                                        |
| ---------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| Binding family requirement               | The constitution requires the control. This is not implementation evidence.                                    |
| Current verified implementation evidence | Evidence identifies the exact validated code, artifact, model, configuration, provider, environment, and date. |
| Planned future evidence                  | Validation is required but has not yet been produced.                                                          |
| Known limitation                         | A bounded unresolved condition or unproved assumption is recorded without a false completion claim.            |
| Approved exception                       | A named, scoped, expiring exception has all required fields and approval.                                      |

Unknown, missing, expired, conflicting, or inapplicable-without-reason evidence
MUST NOT be represented as passing.

## 3. Constitutional hierarchy

1. The Mobius Family Architecture Constitution defines the minimum protected
   requirements for every SolarPlexus Mobius family product.
2. Product-specific profiles MAY narrow scope, add controls, or strengthen a
   requirement. They MUST NOT weaken the family constitution.
3. Milestone requirements MUST inherit every constitutional control
   applicable to the capability introduced by that milestone.
4. A milestone MAY omit an inapplicable control only when the reason is
   explicit and supported by the product profile or architecture.
5. Existing verified contracts and completed milestone decisions remain
   protected unless a verified defect requires a targeted amendment.
6. Undocumented exceptions are invalid.
7. Milestone 7.8 performs the complete cross-family readiness audit.
8. Milestone 8.0 verifies current evidence and blocks release on unresolved
   critical or high-severity gaps. It is not a deferred implementation phase.
9. Future ordinary requirements belong in product profiles, architecture
   decisions, or milestone plans rather than continually enlarging this
   constitution.

## 4. Relationship to established records

This constitution supplies family-wide requirements. It does not replace the
repository's implementation, threat-model, roadmap, or historical evidence
records:

- [Mobius Core and Product Family Roadmap Amendment](MOBIUS_CORE_PRODUCT_FAMILY_ROADMAP_AMENDMENT.md)
  defines verified roadmap terminology and product boundaries.
- [Security Model](SECURITY_MODEL.md) records the as-built threat model,
  implemented controls, and known gaps at its stated point in time.
- [Architecture](ARCHITECTURE.md) records the as-built system structure.
- [Milestone 7 Production Hardening Architecture](MILESTONE_7_ARCHITECTURE.md),
  [implementation plan](MILESTONE_7_IMPLEMENTATION_PLAN.md), and
  [progress](MILESTONE_7_PROGRESS.md) own the current hardening checkpoints.
- [Controlled-agent data retention and erasure policy](CONTROLLED_AGENT_DATA_POLICY.md)
  records the current data-policy boundary and enforcement gaps.
- [Trace and answer provenance](TRACE.md) defines Trace semantics and current
  inspection limits.
- [Deployment and operations guide](DEPLOYMENT.md) records the current
  production-readiness and operating boundary.
- [Known limitations](KNOWN_LIMITATIONS.md) records acknowledged product and
  deployment limitations.

Historical documents remain point-in-time evidence. A current status claim
MUST cite the current owning progress, handoff, completion, or release record
rather than silently treating historical language as current.

## 5. Mobius Family Security Constitution

### SC-01 Same-Milestone Control Rule

When a milestone introduces a new database, service, worker, queue, storage
system, integration, agent capability, data class, trust boundary, or
deployment path, that same milestone MUST define and validate:

- security and access controls;
- failure behavior;
- monitoring and alerting;
- backup and recovery requirements;
- capacity and rate limits;
- rollback, disablement, or kill procedures;
- privacy, retention, deletion, and export behavior;
- operational ownership and escalation; and
- focused tests and release evidence.

These controls MUST NOT be deferred to Milestone 8.0 unless the feature itself
remains disabled and inaccessible until the controls are complete.

### SC-02 Secure-by-default and fail-closed behavior

New products, accounts, services, agents, integrations, and capabilities MUST
begin with the safest practical settings.

Missing authority, unknown actions, invalid configuration, failed
verification, expired evidence, unavailable security controls, or ambiguous
ownership MUST fail closed. They MUST NOT silently grant access, continue a
high-risk action, or broaden authority.

### SC-03 Threat modeling and architecture decisions

Each major capability MUST identify and record:

- protected assets;
- users, agents, services, administrators, and external actors;
- trust boundaries and data flows;
- likely attack paths and abuse cases;
- privacy and operational risks;
- rejected designs;
- selected controls;
- accepted residual risks; and
- the owner and review trigger.

Material security and architecture decisions MUST remain traceable through
architecture decision records or the repository's established equivalent.

### SC-04 Database, migration, and identifier safety

Every migration MUST prove, where applicable:

- PostgreSQL and SQLite behavior while both remain supported;
- clean upgrade, downgrade, and re-upgrade;
- data, row, constraint, index, foreign-key, and trigger preservation;
- ORM and migration agreement;
- safe quoting of PostgreSQL-sensitive identifiers;
- compliance with the permanent identifier-safety validator;
- one sole Alembic head;
- no migration skip, stamp, parallel history, or unapproved `CASCADE`;
- safe transaction, lock, rollback, and error-precedence behavior; and
- backup, rollback, or forward-recovery instructions before production use.

Historical migration bytes and active migration hashes are protected evidence.
Any approved historical correction MUST be narrowly scoped, reviewed, tested,
and recorded.

### SC-05 Backward compatibility and versioning

APIs, events, stored records, exports, agent contracts, model contracts,
provider contracts, and integrations MUST use explicit versions where
compatibility matters.

Breaking changes MUST include:

- a migration or compatibility period;
- supported-client and stored-data tests;
- a deprecation notice;
- a rollback or disablement path;
- a documented removal date;
- an owner; and
- an affected-product list.

### SC-06 Data lifecycle and privacy

Every data class MUST define:

- why it is collected;
- its classification;
- where it is stored and processed;
- who or what may access it;
- retention duration;
- deletion behavior;
- export behavior;
- backup-deletion limitations;
- whether it may enter logs, traces, prompts, models, indexes, caches,
  evaluations, telemetry, or analytics; and
- whether a third-party provider may receive it.

Unknown or unclassified data MUST default to the more restrictive
classification. Data collection and retention MUST be limited to the approved
product purpose.

### SC-07 Tenant, workspace, organization, and authority isolation

Every protected operation MUST prove isolation across:

- users;
- workspaces;
- organizations;
- agents;
- services and workloads;
- devices; and
- environments.

Authorization MUST be enforced at the execution boundary, not only through
hidden interface controls. Cross-user and cross-tenant negative tests are
mandatory for protected operations. Ownership or network location alone MUST
NOT imply authority.

### SC-08 Identity lifecycle and zero trust

Human, agent, service, workload, and device identities MUST be authenticated
and authorized for each protected resource. Network location alone MUST NOT
grant trust.

The system MUST define prompt removal or loss of access for:

- expired sessions;
- revoked grants;
- dormant identities;
- departed users;
- disabled services;
- replaced or lost devices;
- compromised credentials; and
- retired agents or integrations.

Identity creation, privilege change, recovery, revocation, and deletion MUST
be auditable.

### SC-09 Agent-control safety

Every agent capability MUST remain:

- deny by default;
- narrowly granted;
- scoped to the authenticated user and owned workspace;
- limited to approved resources and actions;
- time-limited where appropriate;
- revocable;
- auditable;
- approval-gated for high-risk actions;
- resistant to approval replay or altered evidence;
- bounded by cost, time, concurrency, recursion, and resource limits; and
- stoppable by the user, an authorized operator, or a system-wide kill
  switch.

Agents MUST NOT silently expand their own authority, create unapproved
delegation chains, bypass revocation, or treat model output as authority.

### SC-10 Secrets, encryption, signing, and key lifecycle

Secrets MUST remain outside Git, generated artifacts, logs, traces, prompts,
model inputs, diagnostics, and user-visible errors.

Sensitive data MUST use approved protection in transit, at rest, and in backup
where product risk requires it. Keys, credentials, certificates, signing
identities, and encryption providers MUST have documented:

- creation;
- approved use;
- storage;
- access;
- version;
- rotation;
- recovery;
- compromise response;
- revocation;
- archival where required; and
- destruction.

Algorithms, key sizes, certificate chains, key versions, and encryption
providers MUST be replaceable without redesigning the product. Signed evidence
and artifacts MUST have verifiable integrity and named trust roots.

### SC-11 Configuration integrity and drift control

Configuration MUST have:

- a validated schema;
- safe defaults;
- environment validation;
- ownership;
- secret separation;
- redacted diagnostics;
- drift detection;
- versioning where compatibility matters; and
- explicit handling of unknown or deprecated settings.

Production MUST refuse unknown or unsafe critical configuration rather than
guessing or silently falling back.

### SC-12 AI and model-change governance

Every model, provider, prompt policy, system instruction, tool contract,
retrieval method, ranking method, evaluation set, safety rule, and fallback
policy MUST be versioned where it can affect behavior.

Material changes MUST receive applicable evaluation for:

- accuracy and groundedness;
- privacy and data handling;
- prompt injection;
- tool and agent abuse;
- unsafe authority expansion;
- bias or material user harm;
- provider failure and fallback behavior;
- cost and latency; and
- regression against supported workflows.

Model or provider substitution MUST NOT silently weaken safety, privacy,
evidence, or authority controls.

### SC-13 Observability and incident response

Every production service MUST provide, as applicable:

- health and readiness checks;
- structured logs;
- metrics and traces;
- secret and personal-data redaction;
- actionable alerts;
- named ownership and escalation;
- incident-response procedures; and
- tamper-resistant audit evidence for sensitive actions.

A service that cannot be monitored or safely diagnosed MUST NOT be released.
Sensitive logs and audit records MUST have access, retention, integrity, and
deletion rules.

### SC-14 Incident exercises and vulnerability handling

Written plans alone are insufficient. Before Milestone 8.0, applicable system
owners MUST run and record exercises covering:

- credential compromise;
- tenant-data exposure;
- malicious uploads;
- agent overreach;
- database failure;
- corrupted or unusable backup;
- signing-key loss or compromise; and
- critical provider outage.

The family process MUST define vulnerability intake, triage, severity, owner,
remediation target, disclosure handling, compensating controls, evidence, and
closure.

### SC-15 Backup, restoration, rollback, and continuity

A backup does not count as complete until restoration is tested. Each critical
system MUST define and prove:

- encrypted backups;
- recovery-point and recovery-time targets;
- restoration into a clean environment;
- key and credential recovery;
- migration rollback or forward-recovery strategy;
- failed-deployment recovery;
- dependency-outage behavior;
- data-integrity verification after restoration;
- an owner; and
- an exercise schedule.

### SC-16 Performance, capacity, cost, and abuse limits

Every service or agent capability MUST define:

- expected workload;
- measured or tested limits;
- timeout behavior;
- concurrency limits;
- queue depth limits where queues exist;
- file, request, payload, and result limits;
- rate limits shared across production instances where needed;
- cost budgets;
- runaway-agent controls;
- graceful degradation behavior; and
- overload and dependency-failure behavior.

Milestone 8.0 MUST NOT depend on unmeasured capacity or undefined cost
exposure.

### SC-17 Determinism, concurrency, and idempotency

Retries and concurrent requests MUST NOT create duplicate:

- payments;
- approvals;
- invitations;
- agent actions;
- state transitions;
- notifications;
- audit records; or
- external side effects.

Claims of exactly-once behavior require proof. Otherwise, implementations MUST
use explicit idempotency keys, transaction boundaries, deduplication,
reconciliation, and observable recovery behavior.

### SC-18 Dependency and software-supply-chain safety

The family standard MUST require, as applicable:

- pinned and reviewed dependencies;
- lockfile integrity;
- vulnerability scanning;
- license review;
- secret scanning;
- minimal production images;
- signed artifacts;
- machine-verifiable build provenance;
- reproducible builds where practical;
- documented handling of critical dependency vulnerabilities; and
- no unreviewed generated code in protected paths.

Build provenance SHOULD identify the source, inputs, builder, process, and
resulting artifact. Controlled signed builds are the minimum production
target; more strongly isolated and hardened builds remain the long-term
target.

### SC-19 Deployment and environment parity

Development, testing, staging, and production MUST use compatible architecture
and configuration contracts. Require, as applicable:

- validated configuration schemas;
- no hidden production-only steps;
- environment-specific secrets outside Git;
- feature flags or kill switches for risky releases;
- staged rollout;
- automated rollback criteria;
- health-based release gates;
- migration execution separated from ordinary application startup when risk
  requires it;
- explicit environment and provider differences; and
- rollback and failed-release evidence.

### SC-20 Accessibility and user-safety behavior

Before release, applicable interfaces MUST prove:

- keyboard navigation;
- readable contrast;
- visible focus states;
- accessible names;
- understandable errors;
- safe destructive-action handling;
- confirmation and undo where practical;
- clear status and recovery behavior; and
- no misleading claims about AI certainty, evidence, privacy, security, or
  task completion.

### SC-21 Decommissioning and provider exit

Every service, model provider, integration, feature flag, data store, agent
capability, and product MUST have a safe shutdown or replacement plan
covering:

- data export;
- retention and deletion;
- backup handling;
- key and credential destruction;
- dependency removal;
- customer or operator notice;
- rollback or replacement;
- audit preservation;
- contract and access revocation; and
- proof that disabled components can no longer act.

### SC-22 Evidence freshness and revalidation

A test result, review, audit, or certification does not remain valid forever.
Every release-control record MUST state:

- control owner;
- last validation date;
- validated code, artifact, model, configuration, provider, and environment;
- evidence location;
- known limitations;
- expiration date or revalidation trigger.

Changes to affected code, dependencies, infrastructure, models, prompts,
policies, data schemas, trust boundaries, or deployment environments MUST
invalidate or revalidate the relevant evidence.

### SC-23 Release evidence and exception governance

Release evidence and exception governance MUST satisfy RR-04 and RR-05 below.
Those clauses are binding family-wide security requirements, not release-only
administration. They define the required matrix and exception fields, block
release for unresolved critical or high-severity gaps, and prohibit permanent
undocumented waivers.

## 6. Mobius Family Release Readiness Constitution

### RR-01 Same-milestone closure

A milestone is not complete for a new boundary until every applicable SC-01
control is defined, validated, and recorded. A feature whose controls remain
incomplete MUST remain disabled and inaccessible.

### RR-02 Milestone 7.8 audit

Milestone 7.8 MUST perform the complete cross-family security and
release-readiness audit. It MUST consolidate applicable implementation,
testing, operational, privacy, migration, recovery, capacity, supply-chain,
accessibility, decommissioning, exception, and evidence-freshness records.

Milestone 7.8 MAY correct only verified defects within its approved boundary.
It MUST NOT convert undocumented missing controls into passing evidence.

### RR-03 Milestone 8.0 release decision

Milestone 8.0 MUST:

- verify that evidence remains current for the exact release candidate;
- use the family release-readiness matrix;
- confirm that applicable same-milestone controls were completed by their
  owning milestones;
- confirm that exceptions are valid, approved, scoped, and unexpired;
- block release for every unresolved critical or high-severity gap; and
- record the final release decision and rollback or disablement boundary.

Milestone 8.0 MUST NOT become a broad implementation, deferred-control, or
defect-repair phase.

### RR-04 Release-readiness matrix

Milestone 8.0 MUST use one matrix containing:

- control;
- responsible owner;
- applicable product or system;
- implementation location;
- test or evidence;
- `pass`, `fail`, `blocked`, or `not-applicable` state;
- last validation date;
- validated version and environment;
- remaining limitation;
- rollback or disablement method;
- release-blocking severity; and
- revalidation trigger.

An unresolved critical or high-severity gap MUST block release.

### RR-05 Exception governance

Every exception MUST include:

- owner;
- affected control and scope;
- reason;
- severity;
- compensating control;
- evidence;
- approver;
- approval date;
- expiration date; and
- revalidation or closure condition.

Permanent undocumented waivers are prohibited. An expired, altered,
unapproved, or scope-mismatched exception is invalid and MUST fail closed.

## 7. Product-profile and inheritance model

Each verified family product MUST have one approved product profile. A product
profile MAY strengthen or narrow a family rule but MUST NOT weaken, silently
override, or waive it.

The profile MUST define:

- product name and owner;
- approved purpose;
- users and environments;
- data classes;
- trust boundaries;
- services, storage, agents, models, and integrations;
- applicable constitutional controls;
- strengthened product-specific controls;
- release-evidence locations;
- known limitations;
- approved exceptions; and
- decommissioning plan.

The repository does not yet establish a complete approved family product
profile registry. The roadmap contains product terminology and planned product
boundaries, but this amendment does not transform roadmap entries into
implemented products, approved profiles, owners, or release states. The
registry remains **incomplete** until separately verified profiles are
created, reviewed, and approved.

## 8. Milestone application model

- Each later Milestone 7 checkpoint inherits only the constitutional controls
  relevant to the capability it introduces.
- The Same-Milestone Control Rule applies in full to every new boundary.
- Inapplicable controls require an explicit supported reason.
- Milestone 7.8 performs the complete security and release-readiness audit.
- Milestone 8.0 verifies fresh evidence and decides whether release is
  allowed.
- Milestone 8.0 MUST NOT become a broad implementation or defect-repair phase.
- A feature lacking required same-milestone controls MUST remain disabled and
  inaccessible.

This inheritance changes no approved Milestone 7 checkpoint scope. Checkpoint
7.2 remains the deterministic Indexer and ingestion checkpoint defined by the
existing architecture and implementation plan.

## 9. Current evidence and limitation boundary

### Current verified repository evidence

The current owning records establish only their stated evidence:

- completed Milestone 1–6 behavior and contracts are recorded by their
  architecture, handoff, completion, and progress documents;
- checkpoint 7.1 and the combined historical PostgreSQL correction are
  recorded complete locally in
  [Milestone 7 progress](MILESTONE_7_PROGRESS.md);
- Alembic currently has sole head `20260725_0025`; and
- Milestone 7.2 remains unstarted.

This constitution does not re-audit or recertify that evidence.

### Planned future evidence

- Each checkpoint 7.2–7.7 must produce its applicable same-milestone evidence.
- Milestone 7.8 must produce the complete cross-family readiness audit.
- Milestone 8.0 must verify fresh release-candidate evidence and make the
  release decision.
- Product profiles, the complete product registry, the populated release
  matrix, and any exception records remain pending until separately created
  and approved.

### Known limitations

- The current security, deployment, operations, data-policy, and Milestone 7
  documents record unresolved or future production evidence.
- Managed-provider, destructive recovery, load, incident-exercise,
  supply-chain, accessibility, and release evidence MUST be assessed through
  their owning milestones and matrix rows.
- Historical documents may contain superseded point-in-time status language;
  they remain historical evidence rather than current certification.

### Approved exceptions

This amendment approves **no exceptions**.

## 10. Reusable product-profile template

Copy this section into the owning product-profile document. Replace every
`Pending` value with verified information or retain it as an explicit blocker.

### Product identity

| Field                                     | Value   |
| ----------------------------------------- | ------- |
| Product name                              | Pending |
| Product-profile version                   | Pending |
| Profile status                            | Draft   |
| Owner                                     | Pending |
| Approver                                  | Pending |
| Approval date                             | Pending |
| Approved purpose                          | Pending |
| Users                                     | Pending |
| Environments                              | Pending |
| Repository, artifact, and release version | Pending |

### Architecture and data

| Field                           | Value   |
| ------------------------------- | ------- |
| Data classes                    | Pending |
| Trust boundaries and data flows | Pending |
| Services and workloads          | Pending |
| Storage systems                 | Pending |
| Agent capabilities              | Pending |
| Models and providers            | Pending |
| Integrations                    | Pending |
| External recipients             | Pending |
| Decommissioning plan            | Pending |

### Constitutional mapping

| Control           | Applicable? | Reason  | Product strengthening | Implementation location | Evidence | Limitation or exception |
| ----------------- | ----------- | ------- | --------------------- | ----------------------- | -------- | ----------------------- |
| `SC-__` / `RR-__` | Pending     | Pending | None recorded         | Pending                 | Pending  | Pending                 |

### Release and exception summary

| Field                          | Value         |
| ------------------------------ | ------------- |
| Release-evidence locations     | Pending       |
| Known limitations              | Pending       |
| Approved exception IDs         | None recorded |
| Evidence expiration or trigger | Pending       |
| Rollback or disablement method | Pending       |

## 11. Reusable release-readiness matrix template

Allowed states are `pass`, `fail`, `blocked`, and `not-applicable`.
`not-applicable` requires a supported reason. Unknown or expired evidence is
`blocked`, not `pass`.

| Control           | Owner   | Product or system | Implementation location | Test or evidence | State   | Last validation date | Validated version and environment | Remaining limitation | Rollback or disablement | Blocking severity | Revalidation trigger |
| ----------------- | ------- | ----------------- | ----------------------- | ---------------- | ------- | -------------------- | --------------------------------- | -------------------- | ----------------------- | ----------------- | -------------------- |
| `SC-__` / `RR-__` | Pending | Pending           | Pending                 | Pending          | Blocked | Pending              | Pending                           | Pending              | Pending                 | Pending           | Pending              |

Matrix metadata:

| Field                      | Value                   |
| -------------------------- | ----------------------- |
| Matrix version             | Pending                 |
| Release candidate          | Pending                 |
| Matrix owner               | Pending                 |
| Reviewers and approvers    | Pending                 |
| Generated or reviewed date | Pending                 |
| Final decision             | Blocked until completed |
| Decision evidence          | Pending                 |

## 12. Reusable exception-record template

| Field                                              | Value   |
| -------------------------------------------------- | ------- |
| Exception ID and version                           | Pending |
| Status                                             | Draft   |
| Owner                                              | Pending |
| Affected control                                   | Pending |
| Affected product, system, environment, and version | Pending |
| Exact scope                                        | Pending |
| Reason                                             | Pending |
| Severity                                           | Pending |
| Compensating control                               | Pending |
| Evidence                                           | Pending |
| Approver                                           | Pending |
| Approval date                                      | Pending |
| Expiration date                                    | Pending |
| Revalidation trigger                               | Pending |
| Closure condition                                  | Pending |
| Rollback or disablement method                     | Pending |

An exception MUST NOT be used before approval and MUST NOT survive its
expiration, scope, or validated assumptions.

## 13. Reusable evidence-freshness template

| Field                                                  | Value                   |
| ------------------------------------------------------ | ----------------------- |
| Evidence ID and control                                | Pending                 |
| Control owner                                          | Pending                 |
| Evidence location and integrity reference              | Pending                 |
| Validation method                                      | Pending                 |
| Last validation date                                   | Pending                 |
| Validated code SHA                                     | Pending                 |
| Validated artifact and provenance                      | Pending                 |
| Validated model, prompt, policy, and provider versions | Pending                 |
| Validated configuration                                | Pending                 |
| Validated environment and infrastructure               | Pending                 |
| Data or fixture boundary                               | Pending                 |
| Result                                                 | Blocked until validated |
| Known limitations                                      | Pending                 |
| Expiration date                                        | Pending                 |
| Revalidation triggers                                  | Pending                 |
| Superseded evidence                                    | None recorded           |

At minimum, changes to affected code, dependencies, infrastructure, models,
prompts, policies, data schemas, trust boundaries, providers, configuration,
or deployment environments trigger review and revalidation.

## 14. Adoption, amendment, and closure

- Later architecture and milestone documents MUST link this constitution and
  map applicable controls without copying it in full.
- Ordinary product requirements SHOULD live in product profiles, architecture
  decisions, or milestone plans.
- A constitutional change requires a focused documentation amendment,
  rationale, impact review, and local evidence record.
- A verified implementation defect requires its own targeted implementation
  amendment; changing this document is not a technical fix.
- No exception, product profile, release matrix, or implementation claim is
  created merely by this constitution's existence.

This documentation checkpoint is complete only when its local commit is
created, the tree is clean, protected Git and recovery state remain intact,
and Milestone 7.2 remains unstarted.
