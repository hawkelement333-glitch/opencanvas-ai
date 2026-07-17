# Release checklist

Proposed release: `v0.3.0-buildweek-demo`  
State: draft; not committed, tagged, pushed, published, or deployed.

## Source and scope

- [ ] Owner has reviewed every working-tree change.
- [x] `git status --short` contains only intended source, docs, configuration, and fixtures.
- [x] No `.env`, database, upload, log, report, coverage, cache, credential, or private session export is included.
- [ ] `git diff --check` passes after the initial commit exists or files are staged for review.
- [x] No generated/vendored files are accidentally added beyond the lockfile and intentional fixtures.

## Security and legal

- [x] Final secret scan passes against the entire working tree.
- [ ] Any discovered real credential has been removed and rotated by its owner.
- [ ] Dependency license inventory and notices are reviewed.
- [ ] Final license option is selected and consistent across README/legal files.
- [ ] Copyright owner and year are confirmed.
- [x] Demo fixtures contain only owned/synthetic/non-sensitive material; screenshots remain pending.
- [ ] `SECURITY.md` contains an approved private reporting route.

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

Current handoff status: all required local automated gates pass on the exact release candidate,
including source-only clean-clone reproduction and deterministic demo checks. GitHub Actions remains
unverified until a repository is created and CI runs remotely.

- [x] `corepack pnpm validate` passes on the exact release candidate.
- [x] Formatting, linting, strict type checks, unit tests, integration tests, security tests, browser tests, build, migrations, demo checks, smoke tests, and hygiene are represented in that command.
- [ ] GitHub Actions runs the same canonical command and is green.
- [x] No quality gate suppresses errors or converts failures to success.
- [x] Actual final results and skips are recorded; no historical result is misrepresented as current.

## Documentation and competition

- [x] README commands were copied and tested.
- [x] Architecture reflects implementation, not aspirational features.
- [x] Known limitations are accurate.
- [ ] Screenshots and video placeholders are replaced.
- [ ] Video is public, under three minutes, and includes required audio.
- [ ] `/feedback` session ID is added.
- [ ] Repository URL/access and category are approved.
- [ ] Build Week checklist has no unexplained MISSING or BLOCKED item.
- [ ] Release notes and metadata are reviewed.

## Publication guard

- [ ] Patrick Parke has explicitly approved commit, tag, push, repository visibility, and release publication.
- [ ] Remote name and destination branch are verified.
- [ ] Proposed tag does not already exist locally or remotely.
- [ ] Rollback owner and procedure are agreed.

Do not commit, tag, push, publish, deploy, or change repository visibility until every applicable item is complete or explicitly accepted by the owner.
