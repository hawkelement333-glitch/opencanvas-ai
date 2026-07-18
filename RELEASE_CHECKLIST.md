# Release checklist

Proposed release: `v0.3.0-buildweek-demo`  
State: source committed and published on `main`; not tagged, released, submitted, or deployed.

## Source and scope

- [ ] Owner has reviewed every working-tree change.
- [x] `git status --short` contains only intended source, docs, configuration, and fixtures.
- [x] No `.env`, database, upload, log, report, coverage, cache, credential, or private session export is included.
- [x] `git diff --check` passes after the initial commit exists or files are staged for review.
- [x] No generated/vendored files are accidentally added beyond the lockfile and intentional fixtures.

## Security and legal

- [x] Final secret scan passes against the entire working tree.
- [x] No real credential was discovered; no rotation is required.
- [x] Dependency license inventory and notices are reviewed.
- [x] Proprietary All Rights Reserved evaluation terms are selected and consistent across README/legal files.
- [ ] Copyright owner and year are confirmed.
- [x] Demo fixtures and checked-in screenshots contain only owned/synthetic/non-sensitive material.
- [x] `SECURITY.md` contains the approved GitHub private-vulnerability-reporting route.

## Reproducibility

- [x] Clean-clone install with `pnpm install --frozen-lockfile` passes.
- [x] Fresh Python virtual environment install passes.
- [x] `.env.example` contains placeholders only.
- [x] Database initialization and upgrade to Alembic head pass.
- [x] `pnpm demo:reset` and `pnpm demo` work without credentials.
- [x] `pnpm demo:check` validates both grounded and separate insufficient-evidence persisted replay invariants.
- [x] `pnpm demo:smoke` verifies isolated demo startup.
- [x] Demo startup is visibly labeled and uses only isolated paths.
- [ ] Docker Compose path works from a clean configuration.

## Quality gates

Current handoff status: all required local automated gates, source-only clean-clone reproduction,
deterministic demo checks, and the PostgreSQL-backed GitHub Actions run passed on the submission
candidate.

- [x] `corepack pnpm validate` passes on the exact release candidate.
- [x] Formatting, linting, strict type checks, unit tests, integration tests, security tests, browser tests, build, migrations, demo checks, smoke tests, and hygiene are represented in that command.
- [x] GitHub Actions runs the same canonical command and is green ([run 29624339220](https://github.com/hawkelement333-glitch/opencanvas-ai/actions/runs/29624339220)).
- [x] No quality gate suppresses errors or converts failures to success.
- [x] Actual final results and skips are recorded; no historical result is misrepresented as current.

## Documentation and competition

- [x] README commands were copied and tested.
- [x] Architecture reflects implementation, not aspirational features.
- [x] Known limitations are accurate.
- [x] Primary, citation, and Trace screenshot placeholders are replaced with synthetic demo captures.
- [ ] Video is public, under three minutes, and includes required audio.
- [ ] `/feedback` session ID is added.
- [x] Public repository URL/access and **Work and Productivity** category are approved.
- [ ] Build Week checklist has no unexplained MISSING or BLOCKED item.
- [x] Release notes and metadata are reviewed.

## Publication guard

- [x] The owner explicitly approved committing, pushing, and public repository visibility.
- [x] `origin` and destination branch `main` are verified.
- [x] The proposed tag does not exist locally or remotely.
- [ ] Tag creation and GitHub release publication receive separate final approval.
- [ ] Rollback owner and procedure are agreed.

Do not create a tag or GitHub release, deploy, or submit to Devpost until every applicable item is
complete or explicitly accepted by the owner.
