# SolarPlexus Mobius competition demo guide

This guide is for a deterministic, judge-safe walkthrough. It does not require an OpenAI key and
must be described as **mock/demo mode**, not as a live GPT response.

Public YouTube submission video:
<https://www.youtube.com/watch?v=gd0JWNcHhAA>

## Start and reset

From a clean checkout, install dependencies as described in `JUDGE_SETUP.md`, activate the Python
virtual environment, then run:

```sh
pnpm demo
```

Reset only the isolated demo database and document store with:

```sh
pnpm demo:reset
```

Demo mode uses `.runtime/demo/opencanvas-demo.db` and `.runtime/demo/documents`. The API rejects demo
startup if it detects production environment mode, an OpenAI credential, a live provider, a different
database, or a different document-storage path. `demo:reset` deletes that exact runtime, migrates it,
and reseeds it; it does not leave an empty database.

If either script is absent or fails in the reviewed release candidate, do not improvise against a
normal database. Mark demo readiness blocked and use the documented Docker/mock path only after
reviewing its state.

## Presenter setup

- Reset and seed immediately before recording.
- Confirm the UI visibly identifies deterministic mock/demo output.
- Keep the browser at 100% zoom and close unrelated windows.
- Confirm both `/api/v1/health/live` and `/api/v1/health/ready` succeed.
- Do not place a real `OPENAI_API_KEY` in the environment.
- Prepare a second terminal for the Trace API example.
- Use only bundled synthetic sources; never upload private material during judging.

## Visual-integrity rules

The Devpost promotional thumbnail may be used as clearly identified branding at the beginning or end
of the video. It is not evidence of implemented functionality.

All footage and screenshots used to demonstrate product behavior must be captured from the reviewed
SolarPlexus Mobius localhost build. Do not present AI-generated interface concepts as completed
features. In particular, do not depict a complete Trace explorer, replay/comparison tabs, automatic
inference or conflict classification, collaboration controls, or invented execution metrics unless
those elements exist in the reviewed build and can be reproduced by judges.

## Suggested under-three-minute story

### 0:00–0:20 — Problem and control

“AI chats hide what was actually used. SolarPlexus Mobius makes sources spatial and lets me select
the exact context supplied to the assistant.”

Show the seeded **Build Week Evidence Lab — DEMO DATA** canvas and identify the visible replay/demo
labels.

### 0:20–0:55 — Sources and graph

Open `approved-pilot-brief.md`, show its ready state, then open its extracted text. Point out
`research-and-contingency.md`, the inference note, and the directional relationships on the canvas.

### 0:55–1:30 — Grounded question

Open the seeded `[Replay] Grounded launch synthesis` response. It reconciles the approved Chicago
launch date and budget, an onboarding inference, an unapproved contingency date, and the absence of a
numeric retention target. Show the response node, its connections, and its deterministic replay
warning.

Do not imply that deterministic mock output was generated live by GPT-5.6.

### 1:30–1:55 — Exact evidence

Click the citation. Show the exact source title and page, section, or passage range. Explain that the
server validates citation IDs against chunks retrieved only from selected documents.

### 1:55–2:20 — Unsupported question

Open the separately persisted insufficient-evidence response/node. Show that it is not presented as
grounded, has no citations, and states that the selected sources do not support the question. Its
execution evidence retains the ranked retrieval candidates as excluded chunks while recording
`grounded=false` and `insufficient_evidence=true`. This is deterministic replay data, not a live model
call.

### 2:20–2:40 — Trace

Open the replay Trace URL printed by `pnpm demo` (the deterministic ID is
`d3000000-0000-4000-8000-000000000002`). Identify operation, status, workspace/object association,
and timestamps. Then identify the AI execution snapshots: exact instruction, selected nodes, ranked
chunks, context inclusion, response, citations, and token usage when available.

Trace has no complete end-user explorer in the current release; do not suggest otherwise unless a
reviewed UI is present.

### 2:40–3:00 — Codex, GPT-5.6, and close

Explain that Codex accelerated repository inspection, implementation, tests, diagnosis, and release
preparation. Explain that live mode uses the server-side Responses API with a configurable model
(default `gpt-5.6-terra`), while this isolated replay uses deterministic mock providers and no
credential.

## Evidence categories to state accurately

| Category    | Current behavior                                                          |
| ----------- | ------------------------------------------------------------------------- |
| Supported   | Server-validated citation to an actually retrieved chunk.                 |
| Unsupported | Explicit insufficient-evidence response without grounding citations.      |
| Inference   | Not automatically classified; presenter may label a human interpretation. |
| Conflict    | Not automatically detected or classified.                                 |

## Trace API example

After obtaining a trace ID from a canonical API response or persisted demo metadata:

```powershell
Invoke-RestMethod "http://localhost:8000/api/v1/traces/<TRACE_ID>"
```

Filter the event feed by workspace or object:

```powershell
Invoke-RestMethod "http://localhost:8000/api/v1/trace-events?workspaceId=<WORKSPACE_ID>&limit=100"
```

Never paste credentials, internal storage paths, or private prompts into the recording.

## Final-video review checklist

Review <https://www.youtube.com/watch?v=gd0JWNcHhAA> against every item below before final Devpost
submission:

- [ ] Video opens successfully in an incognito browser and is public, not unlisted or private if the
      rules require public visibility.
- [ ] Runtime is under three minutes.
- [ ] Audio explains both Codex and GPT-5.6/runtime model use.
- [ ] Deterministic demo mode is named on screen or in narration.
- [ ] One supported answer and exact source passage are visible.
- [ ] One insufficient-evidence answer is visible.
- [ ] Trace/provenance is shown without claiming a nonexistent UI.
- [ ] Implemented features are shown with real product footage, not generated UI mockups.
- [ ] Promotional artwork is clearly separated from product evidence.
- [ ] No secret, private URL, user data, terminal history, or notification is visible.
- [x] Public YouTube URL has been recorded in the repository documentation.
- [ ] The same URL has been entered and saved in Devpost.

Before recording, run `pnpm demo:check` to validate the persisted grounded and
insufficient-evidence replay invariants, then run `pnpm demo:smoke` to verify startup. Both passed in
the July 17 submission-candidate validation and must be repeated immediately before recording.

## Submission assets and external fields

- Promotional thumbnail: `docs/assets/solarplexus-mobius-thumbnail.png`
- Primary product screenshot: `docs/assets/opencanvas-evidence-canvas.jpg`
- Citation screenshot: `docs/assets/opencanvas-citation-passage.jpg`
- Trace screenshot: `docs/assets/opencanvas-trace-record.jpg`
- Public YouTube video: <https://www.youtube.com/watch?v=gd0JWNcHhAA>
- Codex `/feedback` Session ID: enter the approved primary-build Session ID directly in Devpost; do
  not publish private Codex conversation content in this repository.
