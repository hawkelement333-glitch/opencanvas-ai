# Mobius Core and Product Family Roadmap Amendment

Date: 2026-07-26

Baseline: completed Milestone 6.4 commit
`f585a9c55323f39f186e0c159a63c6b702b74ae5`

Status: documentation-only product and roadmap amendment complete locally

## Reason for the amendment

Earlier roadmap language correctly ordered Milestones 6–13 but described
Advanced Real-Time Collaboration as an unnamed future phase and could be read
as making every later milestone necessary before SolarPlexus Mobius became a
finished product.

This amendment makes the commercial and platform boundary explicit:

- Milestone 8.0 completes and releases the first finished Mobius product.
- Milestone 8.5 is an optional later advanced-collaboration edition.
- Milestones 9–13 begin separate SolarPlexus product lines built on stable,
  versioned Mobius Core contracts.

The roadmap can continue after Core is complete. That later work is ecosystem
expansion, not evidence that Mobius Core remains unfinished.

## SolarPlexus Mobius Core

SolarPlexus Mobius Core consists of Milestones 1–8.5. It is the shared
evidence, governance, workflow, agent, collaboration, and operating platform
used by later SolarPlexus products.

Mobius Core includes:

- evidence-grounded workspaces;
- explicit context selection and source review;
- exact citations and Trace;
- canonical knowledge and reconstructable provenance;
- deterministic retrieval;
- governed workflows;
- bounded, versioned agents;
- deny-by-default capability and approval controls;
- core multi-workspace collaboration;
- production infrastructure and deterministic indexing;
- controlled deployment, guided onboarding, and product/support
  documentation;
- optional advanced real-time collaboration after Version 1.

Mobius Core is a complete commercial product. It is not merely an unfinished
prerequisite for the later product family.

## Milestone 8.0 — Mobius Core Version 1

Milestone 8 retains its numbered roadmap identity and its approved Controlled
Public Release and Guided Onboarding scope. “8.0” identifies the product
release boundary; it does not renumber the milestone.

Milestone 8.0 completes:

- **SolarPlexus Mobius Core 1.0**;
- the first finished SolarPlexus Mobius product;
- a deployable and usable commercial product;
- controlled public release;
- guided onboarding;
- product, operator, and support documentation;
- production-ready infrastructure inherited from Milestone 7;
- normal multi-user collaboration inherited from Milestone 6.

Mobius Core 1.0 is complete in its own right. Milestone 8.5 and Milestones
9–13 are not prerequisites for describing Version 1 as finished.

## Milestone 8.5 — Mobius Core Advanced Collaboration

The primary product name is **SolarPlexus Mobius Core 1.5 — Advanced
Collaboration**. “SolarPlexus Mobius Collaborative” remains a possible future
commercial edition name, not a second roadmap identity.

Milestone 8.5 follows a released and stable Milestone 8.0 and precedes
Milestone 9. It is a major optional upgrade to Mobius Core, not a Version 1
release requirement.

Its planned scope is:

- simultaneous editing;
- live cursors and selections;
- detailed presence;
- a proven convergence architecture, such as CRDT or operational
  transformation, selected only after formal evaluation;
- offline editing and reconnect synchronization;
- distributed collaboration sessions;
- active-session authorization and revocation;
- operation persistence;
- snapshots, replay, recovery, and compaction;
- collaboration load, network-failure, concurrency, and security testing.

Milestone 8.5 remains unimplemented until Mobius Core 1.0 is released and
stable. It does not begin Agent Society.

## Product family after Mobius Core

Milestones 9–13 remain part of the SolarPlexus ecosystem, but each begins a
separate product or product line with its own positioning and release
boundary. None is required to complete Mobius Core.

### Milestone 9 — SolarPlexus Mobius Society

**Purpose:** a governed agent ecosystem built on Mobius Core.

Planned scope includes the Agent Catalog, Academy, training and evaluation,
certification, governed Librarian, agent identity and lineage, reputation,
controlled delegation, marketplace, quarantine, rehabilitation, appeals, and
agent governance.

Existing deny-by-default authority, bounded capabilities, immutable evidence,
human approval, and controlled-workflow boundaries remain authoritative.

### Milestone 10 — SolarPlexus Mobius Worlds

**Purpose:** a deterministic simulation and scenario platform built on Mobius
Core and Mobius Society.

Planned scope includes simulated worlds, locations, resources, institutions,
agent populations, economies, incentives, governance, scenario replay,
branching, metrics, Trace, and simulation-integrity controls.

Worlds must keep real evidence, simulated facts, agent beliefs, inferred
state, system rules, and human decisions explicitly distinct.

### Milestone 11 — SolarPlexus Mobius Spatial

**Purpose:** a spatial-reasoning and bounded-embodiment platform.

Planned scope includes spatial world representations; perception and sensor
abstractions; position, orientation, distance, and containment; navigation
and spatial planning; simulated embodied actions; optional hardware-adapter
boundaries; human interruption; fresh authority before external effects; and
safety, Trace, and audit.

Initial implementation should prefer deterministic simulation before broad
physical-device control.

### Milestone 12 — SolarPlexus Mobius Federation

**Purpose:** a secure network for cooperation among separate Mobius
deployments and organizations.

Planned scope includes node and organization identity, federation membership,
trust agreements, cross-node authentication and authorization,
privacy-preserving evidence exchange, federated retrieval, distributed
workflows, bounded agent delegation, cross-node revocation, dispute handling,
partition recovery, and federated Trace and audit.

Federation depends on proven local authority and safety contracts; it does not
weaken them.

### Milestone 13 — SolarPlexus Mobius Continuity

**Purpose:** a governed framework for long-term identity, lineage, succession,
memory, compatibility, and evolution.

Planned scope includes identity continuity, version lineage, governed
upgrades, succession, memory retention and decay, archival policy, forking,
merging, inheritance, compatibility, migration across generations, recovery,
and constitutional governance.

Continuity is not unrestricted self-improvement.

## Shared platform relationship

```text
SolarPlexus Mobius Core
    ├── SolarPlexus Mobius Society
    ├── SolarPlexus Mobius Worlds
    ├── SolarPlexus Mobius Spatial
    ├── SolarPlexus Mobius Federation
    └── SolarPlexus Mobius Continuity
```

Later products may use separate repositories, packages, services, or
deployments. They depend on stable, versioned Mobius Core interfaces rather
than copied security-critical implementations.

The preferred boundary is:

- versioned Core packages and stable APIs;
- explicit service boundaries;
- shared authority, Trace, and audit contracts;
- no duplication of security-critical logic;
- independent product release schedules;
- independent customer positioning;
- independent licensing where appropriate.

The whole Mobius repository should not be copied into unrelated repositories.
Repository separation is a product and deployment decision made against
versioned interfaces, compatibility tests, security ownership, and release
needs.

## Authoritative roadmap order

1. Milestone 6 — Core Multi-Workspace Collaboration
2. Milestone 7 — Production Hardening and deterministic Indexing
3. Milestone 8.0 — SolarPlexus Mobius Core 1.0: Controlled Public Release and
   Guided Onboarding
4. Milestone 8.5 — SolarPlexus Mobius Core 1.5: Advanced Collaboration
5. Milestone 9 — SolarPlexus Mobius Society
6. Milestone 10 — SolarPlexus Mobius Worlds
7. Milestone 11 — SolarPlexus Mobius Spatial
8. Milestone 12 — SolarPlexus Mobius Federation
9. Milestone 13 — SolarPlexus Mobius Continuity

Milestone 8 remains the numbered roadmap checkpoint. Milestone 8.0 is its
Version 1 release label. Milestones 9–13 retain their numbers, and Milestone
11 remains before Milestone 12.

## Preserved boundaries

This amendment does not alter these established decisions:

- Milestone 6 remains Core Multi-Workspace Collaboration.
- Milestone 7 remains Production Hardening and the deterministic Indexer.
- Milestone 8 remains Controlled Public Release and Guided Onboarding.
- Advanced Real-Time Collaboration remains after Milestone 8.0.
- The governed Librarian and Agent Society remain in Milestone 9.
- Simulated worlds remain in Milestone 10.
- Embodied and spatial intelligence remains in Milestone 11.
- Federation remains in Milestone 12.
- Continuity and evolution remain in Milestone 13.
- Deny-by-default authority, human approval, exact scope, immutable evidence,
  Trace, audit, event, and controlled-workflow contracts remain unchanged.

## Current Milestone 7 architecture status

The documentation-only
[Milestone 7 Production Hardening architecture](MILESTONE_7_ARCHITECTURE.md),
[implementation plan](MILESTONE_7_IMPLEMENTATION_PLAN.md), and
[architecture handoff](MILESTONE_7_ARCHITECTURE_HANDOFF.md) are complete
locally.

They preserve this roadmap and divide Milestone 7 into:

1. production runtime foundation and managed PostgreSQL;
2. deterministic Indexer and ingestion;
3. private object storage, upload security, and malware quarantine;
4. durable queues/workers/retries and shared limits;
5. observability and operational controls;
6. backup, restore, rollback, and disaster recovery;
7. load, capacity, resilience, and infrastructure security; and
8. the final production-readiness audit.

Milestone 7 implementation has not started. The next authorized checkpoint is
7.1. Milestone 8.0, optional Milestone 8.5, and Milestones 9–13 remain
unstarted.

## Amendment boundary

This amendment changes product structure, naming, release boundaries, and
roadmap language only.

It adds no production code, test, migration, dependency, configuration, CI,
deployment, service, API, frontend, workflow, agent, collaboration runtime,
Indexer, Librarian, simulation, spatial, federation, or continuity behavior.

Milestone 6.5 was not started. Milestones 8, 8.5, and 9–13 remain
unimplemented.

## Execution-status addendum — 2026-08-13

The status statements above are the dated architecture-amendment snapshot and
remain historical. Milestone 7 checkpoints 7.1–7.7 subsequently completed and
were committed. The retained checkpoint 7.7 terminal lifecycle validates
through `MILESTONE_7_7_COMPLETE` at
`b191a392922f94557e6ebf5914113b5e229ab00e`.

Checkpoint 7.8, **Final Production-Readiness Audit**, has now begun only its
first ordered audit surface, architecture and checkpoint scope. Milestone 8.0,
optional Milestone 8.5, and Milestones 9–13 remain unstarted. This addendum
changes execution status only; it does not change the product-family order,
release boundary, or exclusions established by the amendment.
