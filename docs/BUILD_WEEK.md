# OpenAI Build Week development record

## Evidence status

The current branch is `master`, but the repository has no commits and therefore has no commit hash or immutable Git timeline. All current project files are untracked. Local filesystem metadata shows project files beginning on July 16, 2026—for example, the initial migration was created that date—but timestamps can be copied or modified and are not equivalent to version-control evidence.

Project owner statement: OpenCanvas AI was conceived and development began on **July 16, 2026** during OpenAI Build Week. The stronger claim that no functional version existed before the competition period should be published only after the owner confirms it and preserves supporting session/export evidence.

Codex `/feedback` session ID: **TBD — manual action required**

## Competition development summary

OpenCanvas AI progressed from a persistent spatial canvas to document intelligence and then to durable provenance and a canonical knowledge foundation:

| Milestone                          | Delivered capability                                                                                                                                                                                                      | Evidence                                                                                     |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| 1 — Canvas MVP                     | Canvas creation, notes, directional edges, selection, autosave, refresh restoration, server-side AI request, editable response nodes, mock provider.                                                                      | `docs/MVP_CHECKLIST.md`, initial migration, canvas/API/E2E tests.                            |
| 2 — Document intelligence          | Secure PDF/TXT/Markdown/DOCX ingestion, extraction, chunking, pgvector retrieval restricted to selected documents, grounded citations, source preview, insufficient-evidence behavior, structured AI execution snapshots. | `docs/PHASE2_CHECKLIST.md`, migration `0002`, document/security tests.                       |
| 3 — Trace and canonical foundation | Append-only Trace events, query API, canonical workspaces/objects/lifecycle/relationships, same-workspace invariants, transactional mutation evidence.                                                                    | `docs/MILESTONE3_IMPLEMENTATION_REPORT.md`, migrations `0003`/`0004`, Trace/canonical tests. |
| Competition preparation            | Isolated deterministic demo, reproducible validation, public/judge documentation, security and dependency review, non-publishing CI.                                                                                      | Release checklists and final validation report.                                              |

This table describes repository artifacts, not a Git commit chronology.

## Where Codex contributed

Codex was used as an engineering collaborator for:

- repository and architecture inspection;
- implementation plans and milestone sequencing;
- backend, frontend, persistence, migration, and provider implementation;
- unit, integration, browser, migration, and security-focused tests;
- diagnosing failures and iterating until validation passed;
- security, release, documentation, and competition-readiness audits.

No private Codex transcript is published. The session ID and any permissible screenshots must be added manually after owner review.

## Human product and architecture decisions

The human-directed decisions reflected in the repository include:

- use a spatial canvas instead of a chat-first interface;
- require explicit node selection as the AI context boundary;
- retrieve only from selected documents;
- make evidence clickable at page, section, or passage level;
- distinguish grounded results from insufficient evidence;
- keep Trace separate from operational logs and transient domain events;
- add the canonical model without rewriting the working Phase 1/2 path;
- isolate competition demo data and forbid live credentials in demo mode;
- defer authentication, OCR, collaboration, and broad autonomous-agent scope.

Final legal licensing, repository visibility, category selection, and publication remain owner decisions.

The current eligible tracks are Apps for Your Life, Work and Productivity, Developer Tools, and Education. **Work and Productivity** is the recommended fit, but category selection remains manual. Current rules require either a public repository with relevant licensing or a private repository shared with `testing@devpost.com` and `build-week-event@openai.com`.

## GPT-5.6 and runtime AI use

The application integrates the OpenAI Responses API behind a server-side provider interface. The checked-in configuration defaults to `gpt-5.6-terra`, but model selection is environment-configurable. Live mode also uses server-side OpenAI embeddings by default when a key is present. Provider request IDs, model/configuration snapshots, output, and token usage when available are persisted for AI executions.

When no key is present, deterministic mock answer and embedding providers are selected. Competition replay/demo mode deliberately uses those mock providers and must not be described as live GPT-5.6 output.

The exact model used by any historical Codex development session is not evidenced by Git and should not be asserted beyond the available Codex session metadata.

## Validation and evidence locations

- Current release validation: root `pnpm validate` output and CI job logs.
- Historical Milestone 3 validation: `docs/MILESTONE3_IMPLEMENTATION_REPORT.md`.
- API and behavior coverage: `apps/api/tests`, `apps/web/src/**/*.test.*`, `apps/web/e2e`.
- Migration history: `apps/api/alembic/versions`.
- Architecture decisions: `docs/ARCHITECTURE.md` and milestone architecture documents.
- Competition status: `BUILD_WEEK_CHECKLIST.md`.
- Release status: `RELEASE_CHECKLIST.md`.
- Codex session record: **TBD — `/feedback` session ID and approved evidence link**.

## Known limitations at submission preparation

The application has no authentication, OCR, distributed document worker, object-storage adapter, distributed rate limiter, automatic inference/conflict classification, or complete Trace UI. See `KNOWN_LIMITATIONS.md` for the maintained register.

## Manual evidence still required

- [ ] Owner attestation for the start/no-prior-version statement.
- [ ] Codex `/feedback` session ID.
- [ ] Approved screenshots without private content.
- [ ] Public demo video with audio and a sub-three-minute duration.
- [ ] Final category, repository URL/access, and license decision.

Current deadline: **July 21, 2026 at 5:00 PM PDT**. Verify the [Build Week page](https://openai.com/build-week/), [Devpost FAQ](https://openai.devpost.com/details/faqs), and [rules](https://openai.devpost.com/rules) before final submission.
