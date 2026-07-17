# Milestone 3 completion checklist

## Baseline and sequencing

- [x] Read the Milestone 3 specification and inspect the current Phase 1/2 implementation.
- [x] Record a green backend, frontend, browser, security, migration, and production-build baseline.
- [x] Preserve every existing canvas, document-ingestion, retrieval, citation, and grounded-answer path.
- [x] Implement and test Trace Foundation before beginning canonical-object work.

## Trace Foundation

- [x] Add append-only Trace persistence with stable trace/event IDs and parent-trace correlation.
- [x] Store actor, workspace, logical object, operation, outcome, timestamps, metadata, and structured errors.
- [x] Provide reusable start, record, succeed, fail, and filtered-query service operations.
- [x] Keep successful mutations and success evidence in one transaction.
- [x] Roll back failed domain savepoints before retaining failure evidence.
- [x] Expose read-only trace and trace-event query APIs with strict schemas.
- [x] Keep Trace distinct from application logging and transient domain-event delivery.
- [x] Add migration, schema, service, and API tests and pass the Trace-only gate.

## Canonical persistence

- [x] Add canonical workspaces with stable IDs, versions, lifecycle state, metadata, and timestamps.
- [x] Backfill one canonical workspace per existing canvas without changing legacy data or APIs.
- [x] Add the universal canonical-object registry with explicit workspace ownership.
- [x] Add typed Document, Chunk, Note, and Execution detail records.
- [x] Add first-class directional Relationship records with mandatory Trace correlation.
- [x] Enforce same-workspace source/target relationships at the database and repository boundaries.
- [x] Preserve optional compatibility references to Phase 2 canvas and document records.
- [x] Validate clean PostgreSQL upgrade, downgrade, and re-upgrade through revisions 0003 and 0004.

## Domain behavior

- [x] Enforce `created`, `active`, `archived`, and terminal `deleted` lifecycle states.
- [x] Reject updates to archived objects until reactivation.
- [x] Hide deleted objects by default while allowing explicit audit reads.
- [x] Increment versions deterministically and support expected-version conflict checks.
- [x] Validate detached JSON metadata and immutable identity/ownership/type fields.
- [x] Enforce typed detail invariants, chunk parent type/workspace rules, and legacy-document compatibility.
- [x] Centralize controlled object and relationship vocabularies.
- [x] Reject duplicate/self/cross-workspace relationships deterministically.
- [x] Require live relationships and dependent chunks to be removed before endpoint/document deletion.
- [x] Publish typed, replaceable domain events with handler isolation and recursion protection.
- [x] Trace every significant mutation, including rejected and storage-failed operations.

## Canonical API

- [x] Add strict camelCase Pydantic request and response schemas.
- [x] Add Workspace create, get, list, update, and lifecycle endpoints.
- [x] Add typed Document, Chunk, Note, and Execution create/get/list/update/lifecycle endpoints.
- [x] Add Relationship create, filter/list, and traced removal endpoints.
- [x] Translate domain failures into safe 404, 409, 422, and 503 API responses.
- [x] Prevent unrestricted cross-workspace reads and mutations.
- [x] Preserve all existing Phase 1/2 routes and browser behavior.

## Automated coverage

- [x] Trace schema, service, API, and migration tests.
- [x] Canonical schema, lifecycle, repository, service, migration, and contract tests.
- [x] Full canonical graph ASGI workflow test.
- [x] Failed-mutation Trace retention test.
- [x] Trace-completion atomicity injection test.
- [x] Existing Phase 1/2 unit and integration regression suite.
- [x] Existing security-focused pytest suite.
- [x] Existing deterministic Playwright workflow suite.

## Release validation

- [x] Dependency installation.
- [x] Formatting and format verification.
- [x] Frontend and backend linting.
- [x] Strict TypeScript and Python type checking.
- [x] Unit and integration tests: 22 Vitest tests and 89 pytest tests passed.
- [x] Security tests: 12 passed.
- [x] Browser tests: 2 passed; 2 explicitly real-stack-only tests skipped as designed.
- [x] Clean PostgreSQL migration, downgrade, and re-upgrade validation.
- [x] Next.js production build.
- [x] Architecture document, implementation report, README, and final repository audit.

## Intentional non-goals

- [x] No Trace UI, replay, comparison, evaluation, or retention policy.
- [x] No visual canvas redesign or forced conversion of existing nodes/edges.
- [x] No new ingestion, embeddings, hybrid search, graph reasoning, or AI orchestration behavior.
- [x] No authentication, collaboration, agents, OCR, browsing, image, audio, or video features.
