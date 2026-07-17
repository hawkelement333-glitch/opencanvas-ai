# OpenCanvas AI implementation plan

Status: approved working plan  
Last updated: 2026-07-16

## Goal

Build a production-quality MVP of OpenCanvas AI: a spatial workspace where users can create notes, documents, images, code blocks, and AI artifacts; connect them into a graph; select any subset; and ask an AI assistant to reason over the selected context.

## Product slice

The MVP includes:

- A responsive, infinite React Flow canvas with pan, zoom, multi-select, drag, resize-ready node geometry, minimap, and labeled connections.
- Five editable object types: note, document, image, code, and AI artifact.
- Workspace and graph persistence in PostgreSQL, including optimistic revisions for concurrent-safe updates.
- Image/document asset upload through a storage abstraction backed by a mounted local volume in the MVP.
- Context-aware assistant conversations scoped to explicitly selected objects, their direct graph neighbors, and optional semantic matches.
- OpenAI Responses API streaming through the FastAPI server so API keys never reach the browser.
- pgvector embeddings and similarity retrieval, with deterministic local providers for development and tests.
- A one-click “Save as artifact” path that turns an assistant answer into a connected canvas object.
- Seeded demo content so the product is useful before any external integration is configured.

Not included in the MVP: multi-user authentication, presence/cursors, CRDT collaboration, external SaaS connectors, OCR, background ingestion workers, and cloud object storage. The architecture leaves explicit seams for each.

## Delivery milestones

### Milestone 0 — architecture and contract

Deliverables:

- Repository inspection and constraints captured.
- This implementation plan.
- `docs/ARCHITECTURE.md` with system boundaries, data model, API contract, and operational decisions.

Verification:

- Architecture review against every requested technology and product capability.
- Contract review for node types, edge semantics, assistant selection behavior, and streaming events.

### Milestone 1 — monorepo and developer foundation

Deliverables:

- pnpm workspace with `apps/web` and `apps/api`.
- Strict TypeScript, Next.js App Router, linting, formatting, and Vitest.
- FastAPI package, typed settings, Ruff, mypy, pytest, and async test support.
- Shared JSON/OpenAPI contract fixtures and deterministic IDs/sample graph.
- Docker Compose services for web, API, and pgvector-enabled PostgreSQL.
- Environment template, health endpoints, and task scripts.

Tests after the milestone:

- Frontend contract/unit tests.
- Backend settings and health tests.
- Type checks and production build smoke checks.

Exit criteria:

- Both applications start independently.
- Root commands run all checks without requiring an OpenAI key.

### Milestone 2 — graph persistence and API

Deliverables:

- SQLAlchemy 2 async models and repositories for workspaces, nodes, edges, assets, threads, and messages.
- Alembic migration enabling `vector` and creating indexes/constraints.
- CRUD APIs for workspaces, nodes, edges, graph snapshots, and asset uploads.
- Optimistic node/edge revisions with typed `409 conflict` responses.
- Seed endpoint/command for the demo workspace.
- Storage, repository, and embedding provider interfaces.

Tests after the milestone:

- Domain validation and conflict tests.
- Async API tests using an isolated SQLite database with vector fallback.
- Repository CRUD, cascade, graph snapshot, and upload-policy tests.
- PostgreSQL migration smoke test when Docker is available.

Exit criteria:

- A complete graph round-trips through the API.
- Invalid cross-workspace edges and stale updates are rejected.

### Milestone 3 — spatial canvas experience

Deliverables:

- React Flow canvas shell, custom nodes, graph edges, grid, controls, minimap, and fit/reset actions.
- Node creation toolbar and canvas-aware placement.
- Inline editors for note/document/code content and image metadata/upload.
- Selection tray showing exactly which objects form AI context.
- Debounced content autosave and drag-stop geometry persistence.
- Assistant panel shell and polished empty/loading/error/conflict states.
- Keyboard-accessible actions, visible focus, reduced-motion support, and responsive panels.

Tests after the milestone:

- Node renderer tests for all five object types.
- Selection, creation, update, connection, and save-as-artifact state tests.
- API client error and streaming-parser tests.
- Type check, lint, unit test, and Next.js production build.

Exit criteria:

- Users can build and edit a graph without AI configured.
- Reloading restores graph content and geometry.

### Milestone 4 — contextual AI and semantic retrieval

Deliverables:

- Context assembler with explicit-selection priority, graph-neighbor expansion, token/character budgets, and source labels.
- OpenAI Responses API provider using server-side `OPENAI_API_KEY` and configurable model.
- Streaming Server-Sent Events: `context`, `delta`, `complete`, and `error`.
- OpenAI embedding provider plus deterministic development/test provider.
- pgvector nearest-neighbor retrieval and embedding refresh on content changes.
- Persisted assistant threads/messages and source provenance.
- Save-answer-as-artifact flow connected to source nodes.

Tests after the milestone:

- Context ordering, deduplication, budgets, and provenance tests.
- Mocked Responses API stream lifecycle and failure tests.
- Embedding hashing/retry/staleness tests.
- Assistant endpoint and frontend stream-consumer tests.

Exit criteria:

- The assistant demonstrably uses only the intended workspace context.
- No OpenAI secret or raw provider error is exposed to the browser.

### Milestone 5 — integration and production handoff

Deliverables:

- End-to-end happy-path test: seed → edit graph → select → ask → save artifact.
- Container health checks, non-root images, production settings, and persistent volumes.
- Request IDs, structured logging, safe error responses, and readiness checks.
- README with local, Docker, test, migration, and OpenAI configuration instructions.
- Final architecture/known-limitations review.

Tests after the milestone:

- Complete frontend and backend test suites.
- Production frontend build and Python static analysis.
- Docker Compose configuration validation when Docker is available.
- Manual smoke checklist for canvas interaction and streamed assistant output.

Exit criteria:

- The project can be cloned, configured from `.env.example`, and started with documented commands.
- All automated checks pass; environment-only checks are clearly identified.

## Test strategy

| Layer                  | Tooling                        | Focus                                                        |
| ---------------------- | ------------------------------ | ------------------------------------------------------------ |
| Type/contracts         | TypeScript, Pydantic           | Client/server payload compatibility and strict validation    |
| Frontend unit          | Vitest, Testing Library        | Node rendering, state transitions, selection, stream parsing |
| Backend unit           | pytest                         | Domain rules, context assembly, providers, error mapping     |
| Backend API            | pytest, HTTPX, SQLite async    | CRUD, conflicts, uploads, assistant protocol                 |
| PostgreSQL integration | pytest + Docker profile        | Alembic, pgvector operators, indexes                         |
| Build/static           | Next build, ESLint, mypy, Ruff | Production compilation and code quality                      |
| End-to-end             | Playwright-compatible spec     | Core product journey                                         |

Every milestone is considered complete only after its own tests pass. External-service tests use fakes by default; live OpenAI calls are opt-in.

## Key engineering risks and mitigations

- **Canvas/API state divergence:** server snapshots are canonical; mutations use revisions and query invalidation.
- **Oversized AI context:** explicit budgets, normalized node text, deduplication, and source-aware truncation.
- **Embedding cost/churn:** content hashes prevent redundant embeddings; failures do not block editing.
- **Provider coupling:** AI, embeddings, storage, and repositories are interfaces with production and local implementations.
- **Upload abuse:** allowlisted MIME types, size limits, generated storage names, and no direct filesystem paths in responses.
- **Cross-workspace data leaks:** every repository query and edge constraint is workspace-scoped.
- **No local Docker daemon:** SQLite-compatible automated tests cover behavior; PostgreSQL-specific checks remain a clearly labeled optional profile.

## Definition of done

- Requested stack is used at the correct boundary.
- All five object types can be created, edited, positioned, connected, persisted, and selected.
- Contextual assistant output streams and can be saved as a graph artifact.
- pgvector-backed retrieval is implemented and migration-covered.
- Accessible keyboard and error/loading flows are present.
- Secrets stay server-side; unsafe inputs and stale writes fail safely.
- Automated tests and production builds pass, with documented commands and limitations.
