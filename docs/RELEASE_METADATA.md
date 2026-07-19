# GitHub, OpenAI Build Week, and Handshake metadata

Current source repository: <https://github.com/hawkelement333-glitch/opencanvas-ai>. The owner approved
public visibility under the proprietary All Rights Reserved evaluation terms in `LICENSE`.

The official judging path is the documented deterministic localhost demonstration. A hosted
application is not currently available. External submission values—especially the public YouTube URL
and Codex `/feedback` Session ID—must be entered directly in Devpost after they are verified.

## Release

- Proposed tag: `v0.3.0-buildweek-demo`
- Proposed release title: `SolarPlexus Mobius — Build Week Demo`
- Release notes: `docs/RELEASE_NOTES_v0.3.0-buildweek-demo.md`
- Pre-release: recommended **yes** until the final video and Devpost submission are verified
- Package manifests remain at `0.1.0`; the proposed tag names the competition milestone and does not
  silently change package publication versions.

## Repository

- Name: `opencanvas-ai`
- URL: <https://github.com/hawkelement333-glitch/opencanvas-ai>
- Recommended description: `SolarPlexus Mobius — a visual, source-grounded workspace for auditable AI knowledge work.`
- Recommended homepage URL: use the final public YouTube or Devpost project URL after submission
- Visibility: **public**
- License posture: **proprietary / All Rights Reserved; limited competition evaluation**
- Topics:
  - `ai`
  - `codex`
  - `gpt-5-6`
  - `knowledge-management`
  - `infinite-canvas`
  - `provenance`
  - `rag`
  - `traceability`
  - `openai-build-week`
  - `productivity`

The repository, package, module, database, environment-variable, and storage identifiers retain the
`opencanvas` working name for compatibility. Public product branding is **SolarPlexus Mobius**.

## OpenAI Build Week submission copy

- Project name: `SolarPlexus Mobius`
- Subtitle: `A visual, source-grounded workspace for auditable AI knowledge work`
- Category: **Work and Productivity**
- One sentence: `SolarPlexus Mobius is a spatial knowledge workspace that lets users select exact context, generate source-grounded answers, and inspect durable provenance.`
- Short description: `SolarPlexus Mobius turns notes and documents into an interactive canvas where users choose exactly what AI may use. It retrieves only from selected sources, validates citations to exact passages, refuses unsupported questions, and preserves structured Trace evidence for each execution.`
- Built with: `Codex`, `GPT-5.6`, `OpenAI Responses API`, `OpenAI Embeddings`, `Next.js`,
  `React Flow`, `FastAPI`, `PostgreSQL`, `pgvector`
- Repository URL: <https://github.com/hawkelement333-glitch/opencanvas-ai>
- Testing path: follow `docs/JUDGE_SETUP.md`; no account or paid API credential is required

## Handshake AI Showcase copy

- Project title: `SolarPlexus Mobius`
- Project link: use the final public YouTube or Devpost project URL; the GitHub URL is an acceptable
  code link but is less effective as an employer-facing demo
- Description: `SolarPlexus Mobius helps knowledge workers reason across notes and documents without losing the boundary between evidence and generated analysis. Users arrange context on an infinite canvas, retrieve only from selected sources, open validated page- or section-level citations, and inspect durable execution provenance. I built the full-stack product with Codex and integrated GPT-5.6 through the server-side OpenAI Responses API, with deterministic judge-safe demo providers and a production-shaped PostgreSQL/pgvector architecture.`

## Submission assets and owner-supplied fields

- Public YouTube video URL: enter the verified URL directly in Devpost after upload
- Devpost thumbnail: `docs/assets/solarplexus-mobius-thumbnail.png`
- Primary product screenshot: `docs/assets/opencanvas-evidence-canvas.jpg`
- Citation screenshot: `docs/assets/opencanvas-citation-passage.jpg`
- Trace screenshot: `docs/assets/opencanvas-trace-record.jpg`
- Live demo URL: optional; the deterministic local judging path is documented
- Codex `/feedback` Session ID: enter the approved primary-build ID directly in Devpost
- Devpost account registration and final form acceptance: manual action required

## Visual-asset guardrails

- The promotional thumbnail is branding artwork, not evidence of implemented functionality.
- Product screenshots and video demonstrations must be real captures from the reviewed localhost
  build.
- Do not use generated UI concepts to claim a complete Trace explorer, replay/comparison interface,
  automatic inference/conflict classification, collaboration controls, or invented execution data.

## Accuracy guardrails

- Do not call deterministic replay or mock responses live GPT-5.6 output.
- Do not claim automatic inference or source-conflict classification.
- Do not claim a complete end-user Trace UI.
- Dated commits prove publication snapshots, not the entire development chronology.
- Do not publish test counts unless rerun against the exact candidate.
- A public repository can be viewed and cloned; `LICENSE` reserves legal rights but cannot provide
  technical copy protection.

## Final technical sequence

```powershell
git status --short --branch
corepack pnpm validate
corepack pnpm validate:clean-clone
corepack pnpm demo:check
corepack pnpm demo:smoke
git diff --check
```

The one-time privacy rewrite and prior green GitHub Actions validation are complete. Before
submission, rerun the final technical sequence against the exact candidate, verify public/incognito
repository access, upload and verify the public YouTube video, enter the primary-build `/feedback`
Session ID, and submit through <https://openai.devpost.com/> before the deadline. Handshake AI
Showcase is a separate optional portfolio action.

## Rollback outline

- Prefer a new corrective commit or `git revert <published-commit>` after the one-time privacy
  rewrite; do not rewrite public shared history again.
- If a secret is exposed, rotate or revoke it first. A normal revert does not erase it from Git
  history; coordinate repository visibility and history remediation separately.
- If a migration causes a deployment issue, stop application writes, restore the pre-release
  database/file backup, and redeploy the previous reviewed artifact. Do not improvise an untested
  destructive downgrade.
