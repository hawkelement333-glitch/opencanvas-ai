# SolarPlexus Mobius `v0.3.0-buildweek-demo` — competition release notes

Status: **OpenAI Build Week competition release candidate**. A GitHub tag or formal GitHub Release
may be created after the final submission review; the documented localhost judging path does not
depend on either.

## Highlights

SolarPlexus Mobius is a visual knowledge workspace where users select the exact notes and documents
supplied to an AI assistant. The Build Week demo release combines:

- a persistent infinite canvas with notes, directional edges, multi-selection, autosave, and editable
  AI responses;
- secure PDF, TXT, Markdown, and DOCX ingestion;
- retrieval restricted to explicitly selected documents;
- source-grounded answers with server-validated, clickable citations;
- explicit insufficient-evidence behavior;
- structured AI execution evidence and durable Trace events;
- a workspace-scoped canonical object/lifecycle/relationship foundation;
- isolated deterministic demo mode with no account or OpenAI credential required.

## Judge path

```sh
pnpm install --frozen-lockfile
python -m venv .venv
# Activate .venv for the current shell
python -m pip install -e "apps/api[dev]"
pnpm demo
```

Reset with `pnpm demo:reset`. See `docs/JUDGE_SETUP.md` and `docs/DEMO_GUIDE.md`.

## Evidence integrity

A response is shown as grounded only when at least one citation resolves to a qualifying retrieved
chunk from a selected document. Unsupported questions return an insufficient-evidence state.
Automatic inference and conflict classification are not included in this version.

Demo mode uses deterministic mock providers and must not be described as a live GPT-5.6 call. Live
mode uses the server-side Responses API with a configurable model and defaults to `gpt-5.6-terra`
when configured.

The promotional thumbnail is branding artwork. Screenshots and video segments used to demonstrate
implemented behavior must be real captures from the reviewed localhost build, not generated UI
concepts.

## Security posture

Server-side controls cover upload type/size/structure, opaque private storage, archive/path limits,
prompt-injection boundaries, selected-document retrieval, citation allow-list validation, and demo
isolation. This version has no authentication and is limited to trusted single-user/local evaluation.

## Validation

The release gate is:

```sh
corepack pnpm validate
```

Final local and GitHub Actions results are recorded in the release checklist for the exact submission
candidate. Historical Milestone 3 results remain available in
`docs/MILESTONE3_IMPLEMENTATION_REPORT.md`.

## Known limitations

No authentication, OCR, collaboration, distributed worker/outbox, automatic inference/conflict
classification, workspace-wide retrieval, or complete Trace UI. Files use local server storage. See
`docs/KNOWN_LIMITATIONS.md`.

## Upgrade notes

Run Alembic migrations before starting the API:

```sh
pnpm db:migrate
```

Back up existing PostgreSQL and document volumes before any release migration. No destructive
downgrade is part of the normal upgrade path.

## Release governance

The owner selected public source access, proprietary All Rights Reserved evaluation terms, and the
**Work and Productivity** category. The public video, Devpost submission, and approved primary-build
Codex `/feedback` Session ID remain owner-entered submission actions. A GitHub tag or formal release
is optional release management and should occur only after final review.
