# GitHub, OpenAI Build Week, and Handshake metadata

Current source repository: <https://github.com/hawkelement333-glitch/opencanvas-ai>. The owner
approved public visibility under the proprietary All Rights Reserved evaluation terms in
`LICENSE`. No tag, GitHub release, hosted deployment, YouTube video, or Devpost submission has
been created.

## Release

- Proposed tag: `v0.3.0-buildweek-demo`
- Proposed release title: `OpenCanvas AI — Build Week Demo`
- Release notes: `docs/RELEASE_NOTES_v0.3.0-buildweek-demo.md`
- Pre-release: recommended **yes** until the final video and Devpost submission are verified
- Package manifests remain at `0.1.0`; the proposed tag names the competition milestone and does
  not silently change package publication versions.

## Repository

- Name: `opencanvas-ai`
- URL: <https://github.com/hawkelement333-glitch/opencanvas-ai>
- Description: `Visual, source-grounded AI knowledge workspace with user-controlled context and durable provenance.`
- Homepage/demo URL: **TBD — use the final public YouTube or Devpost project URL**
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

## OpenAI Build Week submission copy

- Project name: `OpenCanvas AI`
- Tagline: `See the context. Trust the evidence.`
- Category: **Work and Productivity**
- One sentence: `OpenCanvas AI is a spatial knowledge workspace that lets users select exact context, generate source-grounded answers, and inspect durable provenance.`
- Short description: `OpenCanvas AI turns notes and documents into an interactive canvas where users choose exactly what AI may use. It retrieves only from selected sources, validates citations to exact passages, refuses unsupported questions, and preserves structured Trace evidence for each execution.`
- Built with: `Codex`, `GPT-5.6`, `OpenAI Responses API`, `OpenAI Embeddings`, `Next.js`,
  `React Flow`, `FastAPI`, `PostgreSQL`, `pgvector`
- Repository URL: <https://github.com/hawkelement333-glitch/opencanvas-ai>
- Testing path: follow `docs/JUDGE_SETUP.md`; no account or paid API credential is required

## Handshake AI Showcase copy

- Project title: `OpenCanvas AI`
- Project link: **use the final public YouTube or Devpost project URL; the GitHub URL is an
  acceptable code link but is less effective as an employer-facing demo**
- Description: `OpenCanvas AI helps knowledge workers reason across notes and documents without losing the boundary between evidence and generated analysis. Users arrange context on an infinite canvas, retrieve only from selected sources, open validated page- or section-level citations, and inspect durable execution provenance. I built the full-stack product with Codex and integrated GPT-5.6 through the server-side OpenAI Responses API, with deterministic judge-safe demo providers and a production-shaped PostgreSQL/pgvector architecture.`

## Required owner-supplied fields

- Public YouTube video URL: **TBD**
- Primary screenshot: `docs/assets/opencanvas-evidence-canvas.jpg`
- Citation screenshot: `docs/assets/opencanvas-citation-passage.jpg`
- Trace screenshot: `docs/assets/opencanvas-trace-record.jpg`
- Live demo URL: **optional; local deterministic judge path is documented**
- Codex `/feedback` Session ID from the primary build task: **TBD**
- Devpost account registration and final form acceptance: **manual action required**

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
git add -- <reviewed paths only>
git diff --cached --check
git diff --cached
git commit -m "Harden public Build Week submission"
git push --force-with-lease origin main  # one-time rewrite removes the private snapshot's personal email
```

The one-time privacy rewrite and green GitHub Actions validation are complete. Before submission,
verify public/incognito repository access, enable private vulnerability reporting, upload and
verify the public YouTube video, add the primary-build `/feedback` Session ID, and submit through
<https://openai.devpost.com/> before the deadline. Handshake AI Showcase is a separate optional
portfolio action.

## Rollback outline

- Prefer a new corrective commit or `git revert <published-commit>` after the one-time privacy
  rewrite; do not rewrite public shared history again.
- If a secret is exposed, rotate or revoke it first. A normal revert does not erase it from Git
  history; coordinate repository visibility and history remediation separately.
- If a migration causes a deployment issue, stop application writes, restore the pre-release
  database/file backup, and redeploy the previous reviewed artifact. Do not improvise an untested
  destructive downgrade.
