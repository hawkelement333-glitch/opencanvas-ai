# SolarPlexus Mobius

> Formerly developed under the working name OpenCanvas AI.

> A visual, source-grounded workspace for auditable AI knowledge work

SolarPlexus Mobius turns notes and source documents into a spatial knowledge workspace. A user chooses the exact canvas objects supplied to AI, receives an editable response as a connected node, and can open every validated citation at the supporting page or section.

Competition release candidate: `v0.3.0-buildweek-demo`. Source is published at
[github.com/hawkelement333-glitch/opencanvas-ai](https://github.com/hawkelement333-glitch/opencanvas-ai);
the optional release tag and GitHub release have not been created.

OpenAI Build Week track: **Work and Productivity**. The deterministic demo and recording script
are documented in [docs/DEMO_GUIDE.md](docs/DEMO_GUIDE.md).

[![Contributor Guide](https://img.shields.io/badge/Contributor_Guide-Open-BAFF5A?style=for-the-badge&logo=github)](CONTRIBUTING.md)

![SolarPlexus Mobius deterministic evidence canvas](docs/assets/opencanvas-slack-showcase.png)

Submission evidence: [validated citation passage](docs/assets/opencanvas-citation-passage.jpg) ·
[persisted Trace record](docs/assets/opencanvas-trace-record.jpg)

## Why it exists

Knowledge workers often lose the boundary between evidence, interpretation, and generated text inside a chat transcript. SolarPlexus Mobius makes that boundary visible: sources remain on the canvas, context is explicitly selected, retrieval is limited to those sources, and generated answers carry source-level provenance.

## What it does

1. Create or open a persistent canvas.
2. Add, edit, move, resize, duplicate, connect, and delete notes.
3. Upload PDF, TXT, Markdown, or DOCX sources.
4. Select the exact notes and ready documents that should become context.
5. Ask a question or give an instruction.
6. Receive an editable AI-response node connected to the selected context.
7. Open a citation to inspect the exact page, section, or extracted passage.
8. Use the Trace API and structured execution records to audit what happened.

## Evidence semantics

The current product makes two evidence states explicit:

- **Supported:** a response is grounded only when at least one server-validated citation points to a chunk that was actually retrieved from a selected document.
- **Unsupported:** when qualifying passages are absent, the response is marked as insufficient evidence and is not presented as grounded.

The persisted execution record also separates model context from retrieval candidates: each candidate has its rank, score, inclusion decision, and exclusion reason. **Inference and source conflict are not yet automatically classified in the UI.** A presenter may discuss them only as human interpretations of visible evidence, not as completed product features.

## Core features

- Infinite React Flow canvas with notes, document nodes, AI-response nodes, directional edges, multi-selection, keyboard deletion, and explicit save.
- Autosave with optimistic revisions and refresh restoration.
- Secure server-side document validation, storage, extraction, chunking, embedding, and deletion.
- PDF page metadata and Markdown/DOCX heading preservation where extraction supports it.
- Retrieval restricted to ready documents selected on the active canvas.
- Configurable top-k and minimum-relevance gates.
- OpenAI Responses and Embeddings APIs behind server-only provider interfaces.
- Deterministic mock providers when no OpenAI key is configured.
- Citation allow-list validation and clickable source passages.
- Structured AI-execution snapshots and append-only Trace events.
- Canonical workspace, object, lifecycle, execution, and relationship foundation.

## Trace in one minute

Trace is durable product provenance, not an application log and not the in-process domain-event bus. A Trace event records a stable event and trace ID, optional parent trace, actor, workspace, object, operation, status, safe metadata, structured failure information, and time. Canonical mutations retain both successful and rejected-operation evidence.

Phase 2 execution tables provide the answer-specific detail: exact instruction, selected-node snapshots, retrieved chunks, rank and score, inclusion decisions, model configuration, token usage when available, response text, validated citations, and source-node relationships.

Trace is currently available through read-only API endpoints and persisted records; a complete end-user Trace explorer, replay, and comparison UI remain future work. See [docs/TRACE.md](docs/TRACE.md).

## Architecture

```mermaid
flowchart LR
    U["Browser user"] --> W["Next.js + React Flow"]
    W -->|"Zod-validated HTTP"| A["FastAPI"]
    A --> P[("PostgreSQL + pgvector")]
    A --> F["Private file storage"]
    A -->|"optional server-side calls"| O["OpenAI Responses + Embeddings"]
    A --> M["Deterministic mock providers"]
```

The browser never receives an OpenAI key and never accesses storage paths or PostgreSQL directly. PostgreSQL is the durable source of truth; the React Flow graph is an interaction projection. The Phase 1/2 canvas path and the Milestone 3 canonical domain are intentionally additive compatibility layers.

Read the [as-built architecture](docs/ARCHITECTURE.md) and [Milestone 3 design](docs/MILESTONE3_ARCHITECTURE.md) for details.

## Technology

- Next.js 16, React 19, strict TypeScript, React Flow, React Query, Zod
- FastAPI, Pydantic, async SQLAlchemy, Alembic
- PostgreSQL 17 with pgvector and HNSW cosine search
- OpenAI Responses and Embeddings APIs, server-side only
- `pypdf` and `python-docx`
- Vitest, Testing Library, pytest, Playwright, ESLint, Ruff, mypy, Prettier
- pnpm workspaces and Docker Compose

## Repository map

```text
.
├── apps/
│   ├── api/                 FastAPI app, services, models, migrations, tests
│   └── web/                 Next.js canvas UI, contracts, component and E2E tests
├── docs/                    Architecture, judge, demo, security, and milestone records
├── scripts/                 Release/demo validation utilities when present
├── docker-compose.yml       PostgreSQL, migrations, API, and web reference stack
├── package.json             Canonical repository commands
└── pnpm-lock.yaml           Reproducible JavaScript dependency lock
```

## Judge quick start

The recommended path is the isolated deterministic demo. It uses project-local demo data, mock AI and embeddings, refuses OpenAI credentials, and does not require an account.

```powershell
pnpm install --frozen-lockfile
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e "apps/api[dev]"
pnpm demo
```

On macOS or Linux, activate with `source .venv/bin/activate`. Open the URL printed by the command. Reset only the isolated demo state with:

```sh
pnpm demo:reset
```

If the demo scripts are unavailable in a particular release candidate, use the Docker path below and leave `OPENAI_API_KEY` empty. Exact judge instructions and verification steps live in [docs/JUDGE_SETUP.md](docs/JUDGE_SETUP.md).

## Docker quick start

Prerequisite: Docker Desktop or Docker Engine with Compose.

```powershell
Copy-Item .env.example .env
docker compose up --build
```

On macOS/Linux, use `cp .env.example .env`. Then open <http://localhost:3000>. Readiness is at <http://localhost:8000/api/v1/health/ready>; development API docs are at <http://localhost:8000/docs>.

Compose runs PostgreSQL/pgvector, a one-shot Alembic migration service, FastAPI, an independent
database-backed document worker, and Next.js. Data persists in named `opencanvas-db` and
`opencanvas-files` volumes. `docker compose down --volumes` deletes both volumes and should be
used only when intentional. See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for staging, production,
backup, restore, and rollback procedures.

## Local development

Prerequisites: Node.js 20.9+, pnpm 10.15.1, Python 3.12+, and PostgreSQL with pgvector (or Docker for the database).

```powershell
pnpm install --frozen-lockfile
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e "apps/api[dev]"
Copy-Item .env.example .env
docker compose up -d db
pnpm db:migrate
```

Run the API and web app in separate terminals:

```powershell
pnpm dev:api
```

```powershell
pnpm dev:web
```

Open <http://localhost:3000>. Leave `OPENAI_API_KEY` empty for deterministic mock providers.

## Environment configuration

`.env.example` is the authoritative template. Important values are:

| Variable                           | Required                           | Purpose                                                               |
| ---------------------------------- | ---------------------------------- | --------------------------------------------------------------------- |
| `OPENCANVAS_DATABASE_URL`          | Yes outside isolated demo defaults | Async PostgreSQL URL for normal operation.                            |
| `NEXT_PUBLIC_API_URL`              | Yes for the web build              | Browser-visible API base URL; never place secrets in `NEXT_PUBLIC_*`. |
| `OPENAI_API_KEY`                   | Live providers only                | Server-only key for live AI and embeddings.                           |
| `OPENCANVAS_AI_PROVIDER`           | Yes                                | Explicitly `mock` or `openai`; failures never fall back to mock.      |
| `OPENCANVAS_EMBEDDING_PROVIDER`    | Yes                                | Explicitly `mock` or `openai`; failures never fall back to mock.      |
| `OPENCANVAS_OPENAI_MODEL`          | No                                 | Responses model, currently defaulting to `gpt-5.6-terra`.             |
| `OPENCANVAS_DOCUMENT_STORAGE_ROOT` | Yes outside Docker defaults        | Non-public upload storage root.                                       |
| `OPENCANVAS_DEMO_MODE`             | Demo command only                  | Enables strict project-local demo isolation checks.                   |

Chunk size, overlap, file limits, retrieval top-k, relevance threshold, embedding model, dimensions, and CORS are also configurable in `.env.example`. Demo mode must not be combined with a production environment, OpenAI credentials, live providers, or non-demo storage/database paths.

## Supported source formats

| Format     | Extensions         | Location metadata       | Important limit                                        |
| ---------- | ------------------ | ----------------------- | ------------------------------------------------------ |
| PDF        | `.pdf`             | One-based page          | No OCR; image-only files fail actionably.              |
| Plain text | `.txt`             | Character offsets       | UTF-8 and no binary nulls.                             |
| Markdown   | `.md`, `.markdown` | ATX heading and offsets | Extracted as untrusted text.                           |
| Word       | `.docx`            | Heading and offsets     | Unsafe, encrypted, or oversized archives are rejected. |

The default upload ceiling is 25 MiB, with independent PDF-page, extracted-character, DOCX-member, and expanded-size limits.

## Database and migrations

Run all migrations with:

```sh
pnpm db:migrate
```

Alembic revisions cover the initial canvas, document intelligence, Trace Foundation, and canonical persistence. Do not run destructive downgrade operations against user data. The release validation path uses a disposable database for migration checks.

## Validation

Install both dependency sets, install Playwright Chromium when needed, and run the canonical gate:

```powershell
pnpm install --frozen-lockfile
.\.venv\Scripts\Activate.ps1
python -m pip install -e "apps/api[dev]"
pnpm exec playwright install chromium
pnpm validate
```

`pnpm validate` is the release gate. It must preserve nonzero exits and cover formatting, linting, strict types, automated tests, security checks, production build, migrations, demo validation, smoke coverage, and repository hygiene according to the current root scripts. Historical Milestone 3 results are recorded in [docs/MILESTONE3_IMPLEMENTATION_REPORT.md](docs/MILESTONE3_IMPLEMENTATION_REPORT.md); do not treat those historical counts as a substitute for a fresh run.

## Security notes

- Uploaded content is untrusted data and cannot override server instructions.
- MIME, extension, signatures/structure, size, path safety, and archive expansion are validated server-side.
- Files use opaque storage keys outside publicly served directories.
- Model citations are checked against server-created source identifiers.
- OpenAI and embedding calls remain server-side.
- Accounts use database-backed secure sessions and CSRF protection; every workspace/canvas,
  document/file, execution, citation, and Trace read/write is authorized server-side.
- Staging and production require PostgreSQL, SMTP reset delivery, explicit OpenAI providers,
  private S3-compatible storage, and the durable database-backed worker.

See [docs/SECURITY_MODEL.md](docs/SECURITY_MODEL.md), [SECURITY.md](SECURITY.md), and [docs/KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md).

## Sample and demo data

Competition fixtures are synthetic and non-sensitive. The seeded replay includes both a grounded response with validated source evidence and a separate persisted insufficient-evidence response/node. The latter records excluded retrieval chunks, has no citations, and is stored with `grounded=false` and `insufficient_evidence=true`. Deterministic replay/mock behavior must be visibly identified as demo output rather than a live model response. Demo reset targets only the isolated project-local demo database and file root. `pnpm demo:check` validates persisted replay invariants, and `pnpm demo:smoke` exercises demo startup. See [docs/DEMO_GUIDE.md](docs/DEMO_GUIDE.md).

## Build Week record

The repository now has a dated Build Week publication history on `main`. That history establishes
when reviewed snapshots were published, but a snapshot alone cannot prove the complete development
start or sequence. The project owner reports that SolarPlexus Mobius was conceived and development began
on July 16, 2026 during OpenAI Build Week; Codex task history and the dated repository commits are
the supporting evidence for work completed during the submission period.

Codex was used for repository inspection, implementation planning, incremental code changes, automated test construction, failure diagnosis, security review, and release preparation. Human decisions included the spatial interaction model, explicit-selection context boundary, citation semantics, additive canonical compatibility strategy, and the decision to keep demo mode isolated from live credentials. Private Codex conversation content is not included. The `/feedback` session ID remains a manual submission field.

At runtime, live mode uses the server-side OpenAI Responses API with a configurable model; the supplied configuration defaults to `gpt-5.6-terra`. Mock mode performs no OpenAI calls and must not be described as live GPT output. See [docs/BUILD_WEEK.md](docs/BUILD_WEEK.md).

## Known limitations and roadmap

Major limitations include no OCR or malware-scanning service, per-process rate limiting, a
database-backed rather than broker-backed job queue, non-streaming AI responses, no automatic
inference/conflict classification, and no complete end-user Trace explorer. See the complete
[known-limitations register](docs/KNOWN_LIMITATIONS.md).

Milestone 4 controlled agents and Milestone 5 architecture and checkpoints
5.1–5.7 are complete locally. Milestone 6 architecture and checkpoints
6.1–6.6 are complete locally. Milestone 6.7 — Final Collaboration Security
Audit is next. The
[Milestone 6.5 migration amendment](docs/MILESTONE_6_5_INVOCATION_IDENTITY_MIGRATION_AMENDMENT.md)
and
[implementation handoff](docs/MILESTONE_6_5_SHARED_WORKFLOW_AGENT_GOVERNANCE_HANDOFF.md)
record completed migration `20260725_0025` and the separation of immutable
definition ownership from the exact invoking user and active membership. The
[Milestone 6.6 handoff](docs/MILESTONE_6_6_MULTI_WORKSPACE_COLLABORATION_INTERFACE_HANDOFF.md)
records the complete bounded collaboration console, server-confirmed
workspace/operation context, scoped cache invalidation, accessibility, and
responsive browser validation. The
required roadmap order is:

1. Milestone 6 — Core Multi-Workspace Collaboration
2. Milestone 7 — Production Hardening, including deterministic indexing
3. Milestone 8.0 — SolarPlexus Mobius Core 1.0: Controlled Public Release and
   Guided Onboarding
4. Milestone 8.5 — SolarPlexus Mobius Core 1.5: Advanced Collaboration
5. Milestone 9 — SolarPlexus Mobius Society
6. Milestone 10 — SolarPlexus Mobius Worlds
7. Milestone 11 — SolarPlexus Mobius Spatial
8. Milestone 12 — SolarPlexus Mobius Federation
9. Milestone 13 — SolarPlexus Mobius Continuity

SolarPlexus Mobius Core consists of Milestones 1–8.5. Milestone 8 remains the
numbered Controlled Public Release and Guided Onboarding checkpoint; its 8.0
release boundary completes the deployable, usable commercial product
**SolarPlexus Mobius Core 1.0**. Version 1 does not depend on Milestone 8.5 or
Milestones 9–13.

Milestone 6 remains a normal required milestone before Milestones 7 and 8. Its
core scope covers membership and invitation lifecycle, closed roles and
permissions, scoped sharing of canvases/resources/workflows/agents, comments
and collaboration activity, ownership transfer, revocation, tenant isolation,
and collaboration security/audit. It does not require simultaneous editing.

Live cursors, detailed presence, simultaneous same-resource editing, CRDT or
operational-transform synchronization, offline editing, reconnect merging,
deterministic conflict resolution, distributed presence infrastructure, and
production real-time load/recovery testing belong to optional Milestone 8.5,
**SolarPlexus Mobius Core 1.5 — Advanced Collaboration**, after the stable
Milestone 8.0 release.

Milestone 7 includes deterministic technical indexing and reindexing
infrastructure. The Indexer is not an autonomous agent: it supports controlled,
scoped, immutable-version ingestion and retrieval operations and cannot grant
authority, broaden context, alter evidence, fabricate metadata, or approve
itself.

Milestone 9 begins the separate **SolarPlexus Mobius Society** product line,
including a governed Librarian Agent built on the completed
indexing, authority, graph, retrieval, workflow, collaboration, and production
foundations. It may make evidence-backed catalog-quality proposals but cannot
independently mutate, archive, share, authorize, reindex, or reclassify
authoritative resources or approve itself. Human review and controlled
workflows remain authoritative.

SolarPlexus Mobius Worlds, Spatial, Federation, and Continuity follow as
separate product lines built on stable, versioned Mobius Core interfaces.
They may use independent repositories, services, release schedules, customer
positioning, and licensing, but must share authority, Trace, and audit
contracts without copying security-critical logic. See the
[Mobius Core product-family roadmap amendment](docs/MOBIUS_CORE_PRODUCT_FAMILY_ROADMAP_AMENDMENT.md).

Milestones 6.1–6.5 are complete locally. Workspace memberships now bind exact
authenticated users to exact workspaces, and secure invitations support
bounded creation, delivery, resend, acceptance, decline, expiry, revocation,
idempotency, and concurrency handling. A closed six-role and 36-permission
registry, centralized deny-by-default evaluator, append-only role and
membership lifecycle administration, and exact reviewer-eligibility
assignments now preserve the Milestone 4 capability and approval boundary.
Typed canvas, canonical-object, workflow, and agent sharing, resource and
workspace ownership transfer, immutable authority snapshots, and monotonic
revocation fences are complete locally. Migration `20260725_0023` is the sole
parent of migration `20260725_0024`. Bounded resource comments now use
immutable identities, append-only revisions and lifecycle transitions,
auditable tombstones, four-level replies, exact replay/concurrency controls,
and the existing event/outbox/activity, Trace, and audit systems. Shared
workflow and agent visibility now composes current typed-resource access with
a separate invocation permission. Executions preserve exact definition owner,
immutable version, authenticated invoker, active membership, authority
snapshot, Trace, audit, event, outbox, and activity evidence.

Milestone 6 migrations now have checkpoint-owned immutable boundaries:
6.2 owns completed migration `20260725_0022`, 6.3 owns completed migration
`20260725_0023`, 6.4 owns completed migration `20260725_0024`, and 6.5 owns
completed direct child `20260725_0025`, the sole Alembic head. No later
migration exists. A migration must be completed within its owning checkpoint and must
not be rewritten by a later checkpoint.

See
[docs/MILESTONE_5_ARCHITECTURE.md](docs/MILESTONE_5_ARCHITECTURE.md),
[docs/MILESTONE_5_IMPLEMENTATION_PLAN.md](docs/MILESTONE_5_IMPLEMENTATION_PLAN.md),
[docs/MILESTONE_5_PROGRESS.md](docs/MILESTONE_5_PROGRESS.md),
[docs/MILESTONE_5_7_FINAL_AUDIT_HANDOFF.md](docs/MILESTONE_5_7_FINAL_AUDIT_HANDOFF.md),
[docs/MILESTONE_5_COMPLETION.md](docs/MILESTONE_5_COMPLETION.md),
[docs/MILESTONE_6_ARCHITECTURE.md](docs/MILESTONE_6_ARCHITECTURE.md),
[docs/MILESTONE_6_IMPLEMENTATION_PLAN.md](docs/MILESTONE_6_IMPLEMENTATION_PLAN.md),
[docs/MILESTONE_6_PROGRESS.md](docs/MILESTONE_6_PROGRESS.md),
[docs/MILESTONE_6_ARCHITECTURE_HANDOFF.md](docs/MILESTONE_6_ARCHITECTURE_HANDOFF.md),
[docs/MILESTONE_6_MIGRATION_BOUNDARY_AMENDMENT.md](docs/MILESTONE_6_MIGRATION_BOUNDARY_AMENDMENT.md),
[docs/MILESTONE_6_1_WORKSPACE_MEMBERSHIPS_INVITATIONS_HANDOFF.md](docs/MILESTONE_6_1_WORKSPACE_MEMBERSHIPS_INVITATIONS_HANDOFF.md),
[docs/MILESTONE_6_2_COLLABORATION_ROLES_PERMISSION_AUTHORITY_HANDOFF.md](docs/MILESTONE_6_2_COLLABORATION_ROLES_PERMISSION_AUTHORITY_HANDOFF.md),
[docs/MILESTONE_6_3_RESOURCE_SHARING_OWNERSHIP_REVOCATION_HANDOFF.md](docs/MILESTONE_6_3_RESOURCE_SHARING_OWNERSHIP_REVOCATION_HANDOFF.md),
[docs/MILESTONE_6_4_COMMENTS_COLLABORATION_ACTIVITY_HANDOFF.md](docs/MILESTONE_6_4_COMMENTS_COLLABORATION_ACTIVITY_HANDOFF.md),
[docs/MILESTONE_6_5_INVOCATION_IDENTITY_MIGRATION_AMENDMENT.md](docs/MILESTONE_6_5_INVOCATION_IDENTITY_MIGRATION_AMENDMENT.md),
and the
[Mobius Core product-family roadmap amendment](docs/MOBIUS_CORE_PRODUCT_FAMILY_ROADMAP_AMENDMENT.md).

## Competition and release status

Submission assets and owner actions are tracked in [BUILD_WEEK_CHECKLIST.md](BUILD_WEEK_CHECKLIST.md).
Release review is tracked in [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md). The repository is public;
no release tag, GitHub release, Devpost submission, or internet deployment has been created.

## License and ownership

Copyright (c) 2026 Patrick Parke. This is a proprietary **All Rights Reserved** release under the
limited competition-evaluation terms in [LICENSE](LICENSE). It is not open source; public visibility
does not grant permission to copy, modify, redistribute, commercialize, deploy, or create derivative
works. See `LICENSE_RECOMMENDATION.md`, `COPYRIGHT`, `NOTICE`, and `THIRD_PARTY_NOTICES.md`.

Project owner/contact: **Patrick Parke** via the
[repository owner's GitHub profile](https://github.com/hawkelement333-glitch).
