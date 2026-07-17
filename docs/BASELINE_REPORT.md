# Release-hardening baseline

Recorded: 2026-07-17 (America/Chicago)

## Source-state note

The selected Git worktree initially contained only a new `.git` directory: branch `master`, no
commits, no `HEAD`, no remote, and no tracked files. The completed Milestone 3 OpenCanvas AI source
was available in the immediately preceding Codex workspace and was copied into this worktree before
release changes. Machine-local virtual environments, dependency folders, caches, runtime databases,
document stores, uploads, logs, test reports, and environment files were explicitly excluded.

As a result, the repository cannot supply commit-based evidence for the project start date or prior
milestones. All imported project files are initially untracked. No history, remote, commit, tag, or
publication action was created during the import.

## Inventory

- Frontend: Next.js 16, React 19, strict TypeScript, React Flow, React Query, Zod, and Zustand.
- Backend: FastAPI, Pydantic, async SQLAlchemy, Alembic, and server-only OpenAI providers.
- Persistence: PostgreSQL with pgvector in normal mode; SQLite is used by isolated tests.
- Migrations: initial canvas MVP, document intelligence, Trace Foundation, and canonical knowledge
  persistence (`20260716_0001` through `20260717_0004`).
- AI integration: OpenAI Responses and Embeddings APIs when a server-side key is configured;
  deterministic mock providers otherwise.
- Document support: PDF, TXT, Markdown, and DOCX with server-side extraction and selected-document
  retrieval.
- Tooling: pnpm workspace, Python 3.12 project, Docker Compose, Ruff, mypy, ESLint, TypeScript,
  Vitest, pytest, and Playwright.
- Entry points: `apps/web/src/app/page.tsx`, `apps/api/opencanvas_api/main.py`, root package scripts,
  and `docker-compose.yml`.

## Local toolchain observed

- Node.js: 24.16.0
- Repository-pinned pnpm: 10.15.1 through Corepack
- Python: 3.12.13
- Docker: unavailable on this host
- Git branch: `master`
- Git commit/hash: unavailable because the repository has no commits
- Git remote: none

## Dependency installation

- `corepack pnpm install --frozen-lockfile`: completed from the lockfile. It reported that `sharp`
  and `unrs-resolver` build scripts were ignored, exposing a pnpm 10 policy-configuration issue to
  fix during release hardening.
- Fresh `.venv` creation and `python -m pip install -e "apps/api[dev]"`: passed.

## Baseline commands and results

| Check                            | Result                                                                                                                                                                                                                   |
| -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `pnpm format:check`              | Passed.                                                                                                                                                                                                                  |
| `pnpm lint`                      | Passed.                                                                                                                                                                                                                  |
| `pnpm typecheck`                 | Passed; strict mypy covered 39 Python source files.                                                                                                                                                                      |
| `pnpm test:web`                  | Failed: 19 tests passed, one suite could not resolve `@/lib/api-client` because the Vitest alias used a URL pathname that retained `%20` in this worktree's directory name. This is a confirmed path-portability defect. |
| `pnpm test:api`                  | Passed: 89 tests.                                                                                                                                                                                                        |
| `pnpm test:security`             | Passed: 12 tests; 77 non-security tests deselected.                                                                                                                                                                      |
| `pnpm test:e2e`                  | Passed: 2 deterministic Playwright workflows; 2 real-stack tests skipped by their explicit opt-in condition.                                                                                                             |
| `pnpm build`                     | Passed: optimized Next.js production build.                                                                                                                                                                              |
| Docker Compose migration/startup | Not run: Docker is not installed on this host.                                                                                                                                                                           |

The aggregate `pnpm check` correctly stopped at the frontend test failure and did not suppress it.
The remaining checks were then run individually to complete the inventory. Release work must fix
the alias portability issue, correct pnpm native-build policy, validate migrations without relying
on Docker, and rerun the full canonical gate.

## Baseline failures to distinguish from release changes

1. Vitest path alias fails when the repository path contains spaces.
2. The pinned pnpm 10 installer ignores the existing native-build allow-list syntax.
3. Docker-based reproduction cannot be exercised on this machine because Docker is unavailable.
4. Commit-history and remote-based competition evidence is unavailable because the repository has
   no commits or remote.
