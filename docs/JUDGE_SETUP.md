# Judge setup

OpenCanvas AI can run without an account and without paid API credentials. The deterministic demo path is recommended because it is isolated from normal application data and does not make OpenAI calls.

## Prerequisites

- Git
- Node.js 20.9 or newer
- pnpm 10.15.1 (declared by the root package)
- Python 3.12 or newer
- For browser tests: Playwright Chromium
- For the normal production-shaped path: Docker with Compose, or PostgreSQL 17 with pgvector

No globally installed Python package is assumed.

## Clean-clone deterministic demo

PowerShell:

```powershell
git clone <REPOSITORY_URL>
Set-Location <REPOSITORY_DIRECTORY>
pnpm install --frozen-lockfile
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e "apps/api[dev]"
pnpm demo
```

macOS/Linux:

```sh
git clone <REPOSITORY_URL>
cd <REPOSITORY_DIRECTORY>
pnpm install --frozen-lockfile
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e "apps/api[dev]"
pnpm demo
```

Open the URL printed by the demo command. The repository URL is intentionally a placeholder until the owner approves repository access.

Reset the demo:

```sh
pnpm demo:reset
```

Reset removes only the project-local demo runtime. It must not target PostgreSQL, a production database, or arbitrary upload directories.

## Docker path

```powershell
Copy-Item .env.example .env
docker compose up --build
```

Use `cp .env.example .env` on macOS/Linux. Leave `OPENAI_API_KEY` empty to use mock providers. Open:

- Web: <http://localhost:3000>
- API readiness: <http://localhost:8000/api/v1/health/ready>
- API documentation in development: <http://localhost:8000/docs>

Stop without deleting data:

```sh
docker compose down
```

`docker compose down --volumes` permanently deletes the project database and uploaded documents. It is not part of routine judge setup.

## Live OpenAI mode (optional)

Set a server-only `OPENAI_API_KEY` and choose `auto` or `openai` providers in normal mode. Never prefix the key with `NEXT_PUBLIC_`. Live mode is optional for the documented product workflow; deterministic demo mode intentionally rejects the key.

The configured Responses model defaults to `gpt-5.6-terra`, and embeddings default to `text-embedding-3-small`. Availability, access, latency, and cost depend on the judge’s OpenAI project and are not guaranteed by this repository.

## Verification walkthrough

1. Create or open a canvas.
2. Add and edit a note; move or resize it; reload and verify persistence.
3. Connect two nodes with a directional edge.
4. Upload a supported synthetic document and wait for `ready`.
5. Open its extracted text.
6. Shift-select the document and a note.
7. Ask a supported question and open the citation at the exact passage.
8. Open the separately persisted insufficient-evidence replay node and confirm it is ungrounded, has no citations, and preserves excluded retrieval candidates in its execution evidence.
9. Query a known Trace ID through `/api/v1/traces/{traceId}` or inspect the demo’s prepared provenance step.

## Full validation

With the virtual environment active and dependencies installed:

```sh
pnpm exec playwright install chromium
pnpm validate
```

The command should fail on any failed quality gate. CI runs the same canonical command against temporary services and must not publish or deploy.

The standalone demo checks are:

```sh
pnpm demo:check
pnpm demo:smoke
```

`demo:check` validates persisted replay invariants, including the separate grounded and insufficient-evidence executions. `demo:smoke` verifies that the isolated demo can start. These checks still require an actual final run against the release candidate; documentation alone is not validation evidence.

## Troubleshooting

| Symptom                                     | Check                                                                                                        |
| ------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| `python` resolves to the Windows Store shim | Activate `.venv` and confirm `python --version`.                                                             |
| Port 3000, 8000, or 5432 is occupied        | Stop the conflicting local process or adjust an explicitly documented local configuration.                   |
| API readiness fails                         | Check the database URL, migration container/log, and pgvector service health.                                |
| Document remains failed                     | Open its error, confirm file format/size, then retry; OCR is unavailable.                                    |
| AI shows `Mock AI`                          | Expected when no OpenAI key is configured.                                                                   |
| No grounded citation                        | The selected sources did not produce a qualifying passage or the provider result failed citation validation. |
| Demo isolation error                        | Remove live credentials and use only the exact demo command; do not override its paths.                      |

## Judge-facing caveats

- Single-user/local deployment only; no authentication.
- No OCR, browsing, collaboration, automatic conflict classification, or Trace explorer UI.
- Demo data and mock output are synthetic and visibly labeled.
- Repository URL, final license, public YouTube video, and category remain owner-controlled submission items until filled in. The current alternative to a public repository is private access for `testing@devpost.com` and `build-week-event@openai.com`.
