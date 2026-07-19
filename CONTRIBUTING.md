# Contributing

Thank you for your interest in SolarPlexus Mobius, formerly developed under the working name
OpenCanvas AI. This repository is a proprietary competition release candidate under the limited
evaluation terms in `LICENSE`. Public visibility does not grant permission to copy, redistribute,
modify, or create derivative works.

Before making a substantial contribution, contact the project owner and confirm that contributions
are being accepted under the current repository license and contribution terms. Do not submit code
you do not have the right to contribute.

## Development setup

Prerequisites and clean setup are documented in `docs/JUDGE_SETUP.md`. For local development:

```powershell
pnpm install --frozen-lockfile
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e "apps/api[dev]"
Copy-Item .env.example .env
docker compose up -d db
pnpm db:migrate
```

Start `pnpm dev:api` and `pnpm dev:web` in separate terminals.

## Change principles

- Preserve user control over selected AI context.
- Keep OpenAI credentials and calls server-side.
- Treat uploads, extracted content, browser input, and model output as untrusted.
- Never present an answer as grounded without a server-validated citation.
- Keep Trace evidence distinct from application logs and transient domain events.
- Preserve existing canvas/document behavior unless the change explicitly migrates it.
- Prefer small, typed, tested changes over broad rewrites.
- Do not add real secrets, private data, copyrighted fixtures without permission, or generated output
  represented as human-authored or implemented-product evidence.
- Keep internal `opencanvas` identifiers stable unless a reviewed compatibility migration is planned.

## Before proposing a change

1. Search existing documentation and tests.
2. Describe the user problem and compatibility impact.
3. Add or update tests at the lowest useful layer.
4. Run the focused test while iterating.
5. Run the complete gate:

   ```sh
   corepack pnpm validate
   ```

6. Update architecture, security, environment, migration, and limitations documentation when
   applicable.

## Pull requests

A reviewable pull request should contain:

- a concise problem/solution description;
- behavior and data-model impact;
- security/privacy considerations;
- migration and rollback notes when relevant;
- exact commands and results;
- real screenshots from the reviewed build for visible product changes;
- no unrelated formatting or generated artifacts presented as product evidence.

Do not combine schema migrations with unrelated refactors. Never rewrite shared history or force-push
a branch under review without coordinating with maintainers.

## Tests

- Web unit/component: Vitest and Testing Library
- API/unit/integration/security: pytest
- Browser workflows: Playwright
- Formatting/lint/types: Prettier, ESLint, TypeScript, Ruff, mypy
- Database: Alembic migration validation against disposable state

Real-stack Playwright coverage may require the API and migrated PostgreSQL service. Deterministic
tests must not call paid/live providers.

## Security reports

Do not disclose a vulnerability or secret in a public issue. Follow `SECURITY.md`.

## Conduct

Participation is governed by `CODE_OF_CONDUCT.md`.
