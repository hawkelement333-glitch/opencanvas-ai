# OpenCanvas AI Build Week release audit

Audit date: July 17, 2026  
Proposed release: `v0.3.0-buildweek-demo`  
Current recommendation: **READY WITH MANUAL ACTIONS**

## 1. Executive summary

The completed Milestone 3 source has been prepared as a competition-oriented repository with an
isolated deterministic demo, judge documentation, Trace/evidence fixtures, security and legal
notices, dependency-license inventory, non-publishing CI, canonical validation scripts, container
notice propagation, and repository-hygiene checks.

The selected Git worktree began empty except for a new `.git` directory. The reviewed source was
committed to `main` and connected to
`https://github.com/hawkelement333-glitch/opencanvas-ai`. Before public release, the initial
snapshot's personal author email was replaced with the account's GitHub noreply identity. The
published history and candidate tree are included in the final secret/privacy review.

The exact source candidate now passes the aggregate validation suite, source-only clean-clone
reproduction, deterministic demo integrity/startup checks, production dependency audit, and final
repository-hygiene scan. The transitive PostCSS advisory is remediated by a lockfile-backed nested
override to `8.5.14`; the moderate production audit reports no known vulnerabilities.

The owner approved public source access, proprietary All Rights Reserved evaluation terms, and the
**Work and Productivity** category. No tag, GitHub release, hosted deployment, or Devpost submission
has been created. The public YouTube video, primary-build `/feedback` Session ID, and Devpost form
remain manual; the checked-in screenshots use only synthetic demo data.

## 2. Files created

Release/legal/community:

- `.github/workflows/ci.yml`
- `BUILD_WEEK_CHECKLIST.md`
- `RELEASE_CHECKLIST.md`
- `CHANGELOG.md`
- `CODE_OF_CONDUCT.md`
- `CONTRIBUTING.md`
- `COPYRIGHT`
- `NOTICE`
- `THIRD_PARTY_NOTICES.md`
- `LICENSE_RECOMMENDATION.md`
- `SECURITY.md`

Competition and audit documentation:

- `docs/BASELINE_REPORT.md`
- `docs/BUILD_WEEK.md`
- `docs/DEMO_GUIDE.md`
- `docs/JUDGE_SETUP.md`
- `docs/KNOWN_LIMITATIONS.md`
- `docs/RELEASE_AUDIT_REPORT.md`
- `docs/RELEASE_METADATA.md`
- `docs/RELEASE_NOTES_v0.3.0-buildweek-demo.md`
- `docs/SECURITY_LICENSE_AUDIT.md`
- `docs/SECURITY_MODEL.md`
- `docs/TRACE.md`

Demo and release automation:

- `apps/api/opencanvas_api/services/demo.py`
- `apps/api/scripts/__init__.py`
- `apps/api/scripts/demo.py`
- `apps/api/tests/test_demo_mode.py`
- `apps/api/tests/test_release_settings.py`
- `apps/web/src/components/demo-mode-banner.test.tsx`
- `apps/web/public/.gitkeep`
- `scripts/check_repository_hygiene.py`
- `scripts/clean_clone_check.py`
- `scripts/validate_migrations.py`

## 3. Files modified

- `.dockerignore`, `.env.example`, `.gitignore`
- `README.md`, `package.json`, `pnpm-workspace.yaml`
- `docker-compose.yml`, `apps/api/Dockerfile`, `apps/web/Dockerfile`
- `docs/ARCHITECTURE.md`
- `apps/api/opencanvas_api/core/config.py`
- `apps/api/opencanvas_api/services/trace.py`
- `apps/api/opencanvas_api/main.py`
- `apps/api/opencanvas_api/api/routes/health.py`
- `apps/api/tests/test_health.py`
- `apps/api/tests/test_trace_service.py`
- `apps/web/next.config.ts`, `apps/web/vitest.config.ts`
- `apps/web/src/app/globals.css`
- `apps/web/src/components/open-canvas-app.tsx`
- `apps/web/src/lib/api-client.ts`, `apps/web/src/lib/contracts.ts`

`pnpm-lock.yaml` was regenerated with pnpm 10.15.1 after adding the required nested PostCSS
override to both the requested root package configuration and pnpm workspace settings. Frozen
installation and the moderate production audit both pass; the lockfile was not hand-edited.

## 4. Security findings

- No high-confidence key, access token, private key, certificate, private dataset, user record,
  private URL, local environment file, or local database was found in the source inventory.
- The complete publication history was scanned after replacing the initial snapshot's personal
  author email with the account's GitHub noreply identity.
- The product has no authentication or authorization and must remain a trusted local/demo
  deployment until that is implemented.
- Live AI mode sends the exact selected context and instruction to OpenAI; local mock/demo mode does
  not. This privacy boundary is documented.
- API responses now set `Cache-Control: no-store`, clickjacking, MIME-sniffing, referrer, and
  browser-permission protections. Next.js responses set the applicable browser security headers.
- Production settings reject SQLite, wildcard CORS, and explicitly selected OpenAI providers that
  lack a server-side key.
- Demo settings reject production mode, external credentials, non-mock providers, non-SQLite
  persistence, and storage outside the exact project-local demo directory.
- `.gitignore` and `.dockerignore` exclude environment files, credential/key material, logs,
  caches, uploads, databases, runtime state, and generated output.

## 5. Secret scan status

The final canonical hygiene scan passed across 163 source files after all code and configuration
changes. No real secret was found and no rotation requirement was identified. The commit-eligible
tree and reachable `main` history were reviewed after replacing the initial personal-email commit;
the published branch uses the account's GitHub noreply identity.

## 6. Dependency-license findings

- No direct GPL, AGPL, noncommercial, unknown, or custom-licensed dependency was identified.
- Direct dependencies are predominantly MIT, Apache-2.0, BSD-3-Clause, or ISC.
- `orjson` declares `MPL-2.0 AND (Apache-2.0 OR MIT)` and needs artifact-level compliance review,
  particularly if covered files are modified or binaries are redistributed.
- Sharp/libvips platform artifacts carry Apache/LGPL obligations; `caniuse-lite` carries CC-BY-4.0
  attribution requirements.
- Project notices are copied into both final container images. A final distributable still needs
  an exact-target SBOM and complete upstream license-text bundle.
- Python requirements remain bounded rather than locked, so the exact Python release resolution is
  a documented reproducibility limitation.

## 7. Copyright and license recommendation

The repository identifies `Copyright (c) 2026 Patrick Parke. All rights reserved.` and does not
claim registration. No open-source license was silently applied.

Owner-selected competition path: publish the repository under the proprietary evaluation terms in
the root `LICENSE`, retain all other rights, and use public visibility to satisfy judge-access
requirements. Public visibility does not make the project open source or technically prevent
cloning; the license preserves the owner's legal position. Any later open-source or commercial
license remains a separate owner decision.

## 8. Demo mode behavior

Demo mode uses fixed IDs/timestamps and an isolated `.runtime/demo` SQLite database/document store.
It persists two synthetic sources, notes, relationships, selected-context snapshots, ranked
retrieval evidence, embeddings, canonical objects, validated citations, response-source records,
and Trace events. It contains:

- a clearly labeled deterministic grounded replay with supported, inference, conflict, and
  unsupported sections;
- a separate insufficient-evidence replay with no citations;
- exact clickable source passages; and
- a visible demo banner linking to the persisted Trace.

The labels are demonstration fixtures, not a claim that production currently performs automatic
inference/conflict classification. Normal live mode remains unchanged.

## 9. Demo startup command

After activating the Python virtual environment and installing dependencies:

```powershell
corepack pnpm demo
```

The command migrates and idempotently seeds the isolated demo, starts API and web processes, and
prints `http://localhost:3000`. It explicitly blanks OpenAI credential variables and uses mock
providers.

## 10. Demo reset command

```powershell
corepack pnpm demo:reset
```

Reset is constrained to the resolved `.runtime/demo` directory and then rebuilds deterministic
demo data. It refuses unexpected or repository-root targets.

## 11–16. Quality and migration status

| Gate              | Exact-candidate result                                                                                       | Final release state                                                     |
| ----------------- | ------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------- |
| Build             | Next.js 16.2.10 production build compiled, type-checked, and prerendered successfully.                       | PASS                                                                    |
| Formatting/lint   | Prettier, Ruff formatting, ESLint, and Ruff lint passed.                                                     | PASS                                                                    |
| Type check        | Strict TypeScript and mypy passed across 40 Python source files.                                             | PASS                                                                    |
| Unit tests        | Frontend: 24/24; backend: 106/106.                                                                           | PASS                                                                    |
| Integration tests | API integration: 20/20; deterministic Playwright: 2/2 with 2 intentional real PostgreSQL-stack skips.        | PASS for deterministic release path; real-stack coverage remains noted. |
| Security tests    | 17/17 security-marked tests passed; production dependency audit reports no known vulnerabilities.            | PASS                                                                    |
| Migrations        | Isolated upgrade to `20260717_0004`, downgrade to `20260717_0003`, and re-upgrade to `20260717_0004` passed. | PASS; Docker/PostgreSQL rerun was unavailable on this host.             |
| Demo/hygiene      | Demo reset/check/smoke passed, manual citation/Trace review passed, and hygiene passed for 159 source files. | PASS                                                                    |

## 17. Clean-clone status

`scripts/clean_clone_check.py` creates a source-only temporary worktree, initializes local Git,
performs a frozen pnpm install, creates a fresh Python virtual environment, installs API
dependencies, runs `pnpm validate`, and removes the temporary checkout with bounded Windows cleanup
retries. The exact candidate passed this complete reproduction with exit code 0. Docker is absent
on this host, so the two real PostgreSQL-stack Playwright cases remain intentionally skipped.

## 18. Competition compliance status

Status: **READY WITH MANUAL ACTIONS**. PostgreSQL-backed canonical validation passed in
[GitHub Actions run 29624339220](https://github.com/hawkelement333-glitch/opencanvas-ai/actions/runs/29624339220).
The public repository contains judge setup, demo, Trace, security, architecture, Build Week,
release, and limitation documentation plus deterministic sample data. Official rules were rechecked against
[OpenAI Build Week](https://openai.com/build-week/), the
[Devpost FAQ](https://openai.devpost.com/details/faqs), and the
[official rules](https://openai.devpost.com/rules). **Work and Productivity** is the selected track.

See `BUILD_WEEK_CHECKLIST.md` for the evidence-by-evidence PASS/PARTIAL/MISSING/BLOCKED table.

## 19. Remaining manual actions

- Capture and insert the final primary, citation, and Trace screenshots.
- Record and publicly upload an English YouTube demo of three minutes or less, with audio covering
  the product, Codex, and GPT-5.6.
- Run `/feedback` in the primary Codex build task and insert the real Session ID.
- Fill the Devpost form and final demo link, then verify every public URL.
- Rehearse both a cited answer and an insufficient-evidence answer before recording.

## 20. Blocking issues

No automated blocker remains once the corrected workflow passes on GitHub. The following known
limitations still constrain broader release claims:

1. Python dependency resolution is bounded but not locked or vulnerability-scanned from a lockfile.
2. Docker was unavailable, so the two real PostgreSQL-stack Playwright cases remain intentionally
   skipped; deterministic API/browser workflows and migration round-trips pass.
3. Authentication and authorization are absent, so this build must not be represented as a safe
   internet-facing multi-user service.
4. Owner-controlled competition and publication actions in section 19 remain incomplete.

## 21. Final Git commands

The owner approved the public source update. Stage only reviewed paths; the four confirmed
accidental pager-output files must never be included:

```powershell
git status --short --branch
git add -- .github/workflows/ci.yml BUILD_WEEK_CHECKLIST.md CHANGELOG.md LICENSE `
  LICENSE_RECOMMENDATION.md NOTICE README.md RELEASE_CHECKLIST.md SECURITY.md docs
git diff --cached --check
git diff --cached --stat
git diff --cached
git commit -m "Harden public Build Week submission"
git push --force-with-lease origin main
```

The one-time force-with-lease is limited to replacing the private snapshot's personal author email
with GitHub's noreply identity before public exposure. Do not rewrite the public history again.

## 22. Proposed GitHub publication sequence

Repository and branch:

```powershell
git remote get-url origin
git branch --show-current
```

The expected values are `https://github.com/hawkelement333-glitch/opencanvas-ai.git` and `main`.
The push and green GitHub Actions run are complete. Confirm public/incognito access, enable private
vulnerability reporting, and verify the repository description/topics before handoff. Tag and
GitHub release creation remain separate optional actions.

## 23. Rollback instructions

- Before commit: inspect `git diff --cached` and unstage unintended paths without deleting working
  files.
- After the public push: revert with a new commit and coordinate access/release changes. Do not
  force-push or rewrite public shared history again.
- Demo data is isolated and ignored. `pnpm demo:reset` safely reconstructs it without touching the
  normal database.

## 24. Final validation record

The root `package.json` contains the required override, with the equivalent pnpm workspace setting
used for compatibility with newer pnpm releases:

```json
{
  "pnpm": {
    "overrides": {
      "next>postcss": "8.5.14"
    }
  }
}
```

The following commands completed successfully in CI mode on July 17, 2026:

```powershell
.\.venv\Scripts\Activate.ps1
$env:CI = "true"
corepack pnpm install --lockfile-only
corepack pnpm install --frozen-lockfile
corepack pnpm audit --prod --audit-level=moderate
corepack pnpm format
corepack pnpm validate
corepack pnpm validate:clean-clone
corepack pnpm demo:check
corepack pnpm demo:smoke
git status --short --branch
```

The final `validate` run passed all represented gates, and the final source-only clean clone passed
the same suite before removing its temporary checkout. The public source update is owner-approved;
tag/release publication, the video, `/feedback` Session ID, and Devpost submission remain governed
by the manual actions in section 19.
