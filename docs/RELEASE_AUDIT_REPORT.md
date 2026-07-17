# OpenCanvas AI Build Week release audit

Audit date: July 17, 2026  
Proposed release: `v0.3.0-buildweek-demo`  
Current recommendation: **READY WITH MANUAL ACTIONS**

## 1. Executive summary

The completed Milestone 3 source has been prepared as a competition-oriented repository with an
isolated deterministic demo, judge documentation, Trace/evidence fixtures, security and legal
notices, dependency-license inventory, non-publishing CI, canonical validation scripts, container
notice propagation, and repository-hygiene checks.

The selected Git worktree began empty except for a new `.git` directory. It has no commit, `HEAD`,
remote, or history, so the Milestone 3 snapshot was imported without machine-local/runtime data.
That prevents commit-based chronology and historical secret review. Every source file remains
untracked until the owner reviews and creates the first commit.

The exact source candidate now passes the aggregate validation suite, source-only clean-clone
reproduction, deterministic demo integrity/startup checks, production dependency audit, and final
repository-hygiene scan. The transitive PostCSS advisory is remediated by a lockfile-backed nested
override to `8.5.14`; the moderate production audit reports no known vulnerabilities.

The repository is technically ready for owner review and competition packaging, but it is not
committed, tagged, pushed, published, or deployed. License selection, repository access, category,
video, screenshots, `/feedback` Session ID, Devpost fields, and publication approval remain manual.

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
- Git history could not be scanned because no commits exist.
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

The final canonical hygiene scan passed across 159 source files after all code and configuration
changes. No real secret was found and no rotation requirement was identified. Git history still
cannot be scanned because the repository has no commit or `HEAD`; owner review remains required
before the first commit.

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

Recommended competition path: retain All Rights Reserved, keep the repository private, and share
it with `testing@devpost.com` and `build-week-event@openai.com`. If the owner instead approves a
public/open-source release, Apache License 2.0 is preferable to MIT for its express contributor
patent grant and termination terms. The final choice remains a manual owner decision.

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

Status: **PARTIAL**. The repository now contains judge setup, demo, Trace, security, architecture,
Build Week, release, and limitation documentation plus deterministic sample data. Official rules
were checked against [OpenAI Build Week](https://openai.com/build-week/) and the
[Devpost FAQ](https://openai.devpost.com/details/faqs). Work and Productivity is the recommended
track, but final category selection remains manual.

See `BUILD_WEEK_CHECKLIST.md` for the evidence-by-evidence PASS/PARTIAL/MISSING/BLOCKED table.

## 19. Remaining manual actions

- Choose the final license/repository-visibility path.
- Create the first reviewed commit and configure the intended GitHub remote.
- Share a private repository with both required judging addresses, or explicitly approve a public
  release with relevant licensing.
- Select the final competition category.
- Capture and insert real screenshots.
- Record and publicly upload an English YouTube demo of three minutes or less, with audio covering
  the product, Codex, and GPT-5.6.
- Run `/feedback` in the primary Codex build task and insert the real Session ID.
- Fill the Devpost form, repository URL, contact details, and final demo link.
- Rehearse both a cited answer and an insufficient-evidence answer before recording.

## 20. Blocking issues

No automated blocker remains for the isolated deterministic competition demo. The following known
limitations still constrain broader release claims:

1. Python dependency resolution is bounded but not locked or vulnerability-scanned from a lockfile.
2. Docker was unavailable, so the two real PostgreSQL-stack Playwright cases remain intentionally
   skipped; deterministic API/browser workflows and migration round-trips pass.
3. Authentication and authorization are absent, so this build must not be represented as a safe
   internet-facing multi-user service.
4. Owner-controlled competition and publication actions in section 19 remain incomplete.

## 21. Proposed Git commands

Do not run these until the owner has reviewed the complete working tree and explicitly approved
the first commit and release preparation:

```powershell
git status --short --branch
git add .dockerignore .editorconfig .env.example .gitignore .github `
  BUILD_WEEK_CHECKLIST.md CHANGELOG.md CODE_OF_CONDUCT.md CONTRIBUTING.md `
  COPYRIGHT LICENSE_RECOMMENDATION.md NOTICE README.md RELEASE_CHECKLIST.md `
  SECURITY.md THIRD_PARTY_NOTICES.md docker-compose.yml package.json `
  pnpm-lock.yaml pnpm-workspace.yaml apps docs scripts
git diff --cached --check
git diff --cached --stat
git diff --cached
git commit -m "Prepare OpenCanvas AI Build Week demo release"
git tag -a v0.3.0-buildweek-demo -m "OpenCanvas AI Build Week demo"
```

Because there is no remote, remote configuration cannot be made exact until the owner supplies the
reviewed repository URL.

## 22. Proposed GitHub publication sequence

Only after explicit publication approval:

```powershell
git remote add origin <REVIEWED_GITHUB_REPOSITORY_URL>
git push -u origin master
git push origin v0.3.0-buildweek-demo
```

Then either keep the repository private and share it with both judging addresses, or carry out the
separately approved public/license path. Create release notes from
`docs/RELEASE_NOTES_v0.3.0-buildweek-demo.md`. Do not enable automated deployment/package
publication as part of this sequence.

## 23. Rollback instructions

- Before the first commit: do not delete the imported Milestone 3 snapshot. Copy the reviewed
  worktree to a separate backup before staging if rollback is required.
- After staging but before commit: inspect `git diff --cached`; use `git reset` to unstage while
  preserving working files.
- After a local commit but before push: delete only the local proposed tag with
  `git tag -d v0.3.0-buildweek-demo`; use a new corrective commit rather than rewriting history.
- After push: revert with a new commit and coordinate repository access/release changes. Do not
  force-push or rewrite published history.
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
the same suite before removing its temporary checkout. Do not stage, tag, push, share, or publish
until the owner completes the manual review and approval actions in sections 19 and 21.
