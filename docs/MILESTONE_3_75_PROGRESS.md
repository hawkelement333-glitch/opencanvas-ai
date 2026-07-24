# Milestone 3.75 Visual Redesign Progress Ledger

Last updated: 2026-07-23 (America/Chicago)

## Repository state

- Current branch: `milestone-3.75-visual-redesign`
- Starting Milestone 3.5 remote commit: `3b576cae81d5622ca930eb2538e6527d861c759a`
- Protected `competition-demo-v1` tag object: `acbde89b6e2cc3e41c372887794726d393836716`
- Protected `competition-demo-v1` commit: `b45b7763b65861f9dfb3be7edf9b5eb271950917`
- Recovery starting local HEAD: `ff34f22b6264f9a0e12b8fa5d8e66dcd2e7074a4`
  (`Polish living-universe canvas legibility`)
- Recovery starting remote branch HEAD: `ff34f22b6264f9a0e12b8fa5d8e66dcd2e7074a4`
  on `origin/milestone-3.75-visual-redesign`
- Branch created from `origin/milestone-3.5-productization`.
- Push target: `origin/milestone-3.75-visual-redesign` only.

## Baseline before Milestone 3.75 edits

- Working tree before branch creation: clean.
- `origin/milestone-3.5-productization`: `3b576cae81d5622ca930eb2538e6527d861c759a`.
- `competition-demo-v1`: unchanged and still resolves to `b45b7763b65861f9dfb3be7edf9b5eb271950917`.
- Root `pnpm format:check`: failed before edits because pnpm attempted an install/dependency-status check and stopped on ignored build scripts for `sharp` and `unrs-resolver`.
- Direct Prettier check using installed web dependencies: failed before edits on existing docs/web formatting backlog and `.env.example` parser inference.
- API Ruff format check: passed, `85 files already formatted`.
- Web lint: passed.
- Web type check: passed.
- Web unit/component tests: passed, `24` tests across `7` files.
- API tests: passed, `118` tests.
- API Ruff lint: passed.
- API mypy: passed, `45` source files.
- Production web build: passed.
- Demo smoke: passed, deterministic replay runtime reported no external AI.
- Browser baseline at `1440x900`, `1280x800`, `1024x768`, `768x1024`, and `390x844`: screenshots saved under `.runtime/milestone-3-75-baseline`. The app shell rendered without horizontal overflow, but the local browser session stayed on `Opening SolarPlexus Mobius...` despite healthy API endpoints and no captured console errors. Treat as a pre-existing manual-inspection blocker to recheck after the first UI checkpoint.

## Completed phases

- Phase 1 repository/product audit: partially complete. Frameworks, routes, main shell, canvas, assistant panel, document preview, contracts, tests, and validation commands inspected. Browser baseline recorded with the loading-state issue above.
- Phase 2 semantic universe model: complete for the first checkpoint. Added a typed frontend mapping layer for universe, galaxy/workspace, solar-system/canvas, node roles, citation fragments, pathway types, processing labels, and resource summaries.
- Initial design-system foundation: complete for the first checkpoint. Added restrained cosmic tokens, black-hole compact mark treatment, data-backed resource strip, pathway legend, semantic node labels, context-zone copy, and source/citation role labels.
- Future-agent architecture documentation: complete for the first checkpoint. Documentation only; no active agent behavior added.
- First live visual audit: complete. Deterministic demo mode reported `appMode=demo`, `mode=deterministic_replay`, and `externalAiEnabled=false`; the seeded canvas and source viewer were inspected in the browser.
- Canvas legibility polish: complete for this checkpoint. Shortened solar-system navigation labels, compacted pathway legend text while preserving full accessible names, increased useful fit-to-view scale, and reduced minimap obstruction.
- Interrupted Terra checkpoint recovery: complete locally. Preserved and reviewed the inherited
  source-viewer, document-state, account, and CSS changes; corrected the remaining narrow-screen
  source-viewer defect; and added focused semantic regression coverage.
- Source-viewer polish: complete for the Terra checkpoint. Added long-title handling, stable
  source/citation hierarchy, exact-passage focus semantics, named extracted text, visible focus,
  contained scrolling, long-passage wrapping, and full-viewport tablet/mobile presentation.
- Upload and processing presentation: complete for the existing document-card states. Existing
  backend stages and retry behavior are unchanged; the real stage label now has a restrained
  semantic status treatment and supporting action copy remains visible. No progress percentage or
  processing stage was invented.
- Account-surface consistency: complete for the existing account page. Loading and account regions
  have explicit semantics, long account identities wrap, and the narrow layout uses full-width,
  practical touch targets without adding account features.

## Current phase

- `LUNA FINALIZATION COMPLETE — DOCUMENTED VALIDATION LIMITATION`
- The responsive evidence-surface checkpoint is pushed and validated. No additional implementation
  surface is permitted in this milestone; stop before Milestone 4.

## Files changed in current checkpoint

- `apps/web/src/app/globals.css`
- `apps/web/src/app/account/page.tsx`
- `apps/web/src/components/canvas/document-node.tsx`
- `apps/web/src/components/document-preview-panel.tsx`
- `apps/web/src/components/document-preview-panel.test.tsx`
- `docs/MILESTONE_3_75_PROGRESS.md`

## Commits created

- `522f4bd` (`Establish the living-universe design system`)
- `cc1bc41` (`Record Milestone 3.75 push blocker`)
- `ff34f22` (`Polish living-universe canvas legibility`)
- Current recovered Terra commit: this ledger is included in the checkpoint commit
  `Polish responsive evidence surfaces`; resolve its immutable SHA with `git rev-parse HEAD`.

## Commits pushed

- `522f4bd` (`Establish the living-universe design system`)
- `cc1bc41` (`Record Milestone 3.75 push blocker`)
- `ff34f22` (`Polish living-universe canvas legibility`)
- Prior checkpoints were pushed normally to `origin/milestone-3.75-visual-redesign`; the recovery
  session started with local and remote HEAD matching at
  `ff34f22b6264f9a0e12b8fa5d8e66dcd2e7074a4`.
- The recovered Terra checkpoint `8b6fd9d8e4bd52ee16de50ca08fd90686e46e32a` is pushed normally and
  was the local and remote branch tip before this Luna documentation checkpoint.

## Tests run after current edits

- Deterministic demo runtime check: passed; replay mode loaded with no external AI.
- Browser visual audit: passed for the seeded canvas and source viewer at the available `1280 × 720` viewport.
- Changed-file Prettier write: passed; all six intended files were already formatted.
- Focused web tests: passed, `18` tests across `5` files.
- Web TypeScript check: passed.
- Focused web lint on changed TypeScript files: passed.
- `git diff --check`: passed.
- Secret-pattern scan across all six changed files: no matches.
- Prohibited-scope audit: passed. No worker, queue, scheduler, agent-runtime, external-call, embedding-provider, production-dependency, or Milestone 4 source additions; no dependency files changed.
- Protected `competition-demo-v1` commit rechecked and unchanged at `b45b7763b65861f9dfb3be7edf9b5eb271950917`.

Prior checkpoint validation:

- Changed-file Prettier write: passed.
- Focused web tests: passed, `15` tests across `4` files.
- Web TypeScript check: passed.
- Focused web lint on changed TypeScript files: passed.
- `git diff --check`: passed.
- Stricter secret-pattern scan across `apps`, `docs`, `.env.example`, package metadata, and workspace metadata: no matches.

Recovered Terra checkpoint validation (2026-07-23):

- Interrupted state verification: passed. The branch was
  `milestone-3.75-visual-redesign`; local and remote HEAD were both
  `ff34f22b6264f9a0e12b8fa5d8e66dcd2e7074a4`; only the four reported visual
  files were initially modified.
- Complete inherited-diff review: passed. No changed data contract, demo fact, source identity,
  citation behavior, backend behavior, dependency, or Milestone 4 import was found.
- Clear corrections made during recovery: enabled real two-line/anywhere wrapping for long source
  titles, connected the document processing status hook to a visible stage treatment, and changed
  the source viewer to a full-viewport surface at widths up to `820px`.
- Focused source-viewer test added:
  `apps/web/src/components/document-preview-panel.test.tsx`. It verifies the accessible dialog and
  long title identity, document metadata label, exact cited passage resolution and focus, named
  extracted text, and close control behavior.
- Focused Vitest: passed, `1` test across `1` file.
- Web TypeScript check: passed with `tsc --noEmit`.
- Focused ESLint: passed for the four changed TypeScript/TSX files and the new test.
- Changed-file Prettier check: passed for all five frontend files.
- `git diff --check`: passed.
- Repository hygiene check: passed for `187` source files.
- Fast secret-pattern scan across all changed files: no matches.
- Prohibited-scope diff scan: passed. No backend service, migration, worker, queue, scheduler,
  controlled-agent runtime, tool execution, provider, external AI call, embedding call, production
  dependency, demo fact, grounded answer, citation data, Trace semantics, or Milestone 4
  implementation was added.
- Deterministic demo smoke: passed. The API reported `appMode=demo`,
  `mode=deterministic_replay`, and `externalAiEnabled=false`; the local web shell returned HTTP 200.
- Rendered source viewer:
  - `1440 × 900`: visually inspected; exact citation and cited passage remained legible; no
    page-level horizontal overflow.
  - `1024 × 768`: visually inspected; the panel, close action, and evidence content remained
    reachable; no page-level horizontal overflow.
  - `768 × 1024`: the pre-fix audit exposed a `202px` inherited canvas-column panel; the correction
    was recaptured and measured at the full `768px` viewport width with no horizontal overflow.
  - `390 × 844`: the pre-fix audit exposed a `158px` inherited canvas-column panel; the correction
    measured the panel at the full `390px` viewport width, with the close action reachable and no
    page-level horizontal overflow.
- Rendered account page:
  - `390 × 844`: visually inspected; card width remained inside the viewport and all three buttons
    measured approximately `45px` high and full width.
  - `1024 × 768`: DOM layout inspection passed with a centered `620px` card and no horizontal
    overflow. The in-app browser's viewport-override screenshot was cropped and was rejected as
    visual evidence.
- Keyboard/focus inspection: the account input exposed a visible solid focus outline; the focused
  source-viewer test verified automatic focus on the resolved cited passage.
- Browser console inspection: no warnings or errors were captured on the audited source-viewer and
  account routes.

## Known failures

- Pre-existing root pnpm dependency-status failure and Prettier backlog described above.
- The in-app browser blocks direct navigation to the demo API port, so its documented two-port startup remains on the loading state in that browser tool. A temporary uncommitted same-origin test proxy allowed the real seeded UI to be audited; the proxy was fully removed before validation. This is a browser-tool constraint, not a change to the demo startup contract.
- The first `demo.py check` attempt found a stale local `.runtime/demo` database revision left by a
  newer branch. The repository's path-validated smoke command reset only `.runtime/demo`, then
  migrated, seeded, and passed. No tracked fixture or protected history was changed.
- The top-level pnpm wrapper again stopped on ignored `sharp` and `unrs-resolver` build scripts
  before it could invoke formatting or tests. It also added three placeholder `allowBuilds` lines
  to `pnpm-workspace.yaml`; those tool-generated lines were removed, and the tracked workspace file
  is unchanged. Installed web binaries were used directly for all focused checks.
- At some explicit viewport overrides, the in-app browser captured a larger outer surface than its
  measured inner viewport. Cropped captures were rejected. DOM geometry, overflow, reachability,
  accepted captures, and the 390-pixel account screenshot were used together; Luna may perform one
  final narrow source-viewer capture with another approved browser if desired.

## Work in progress

- No partial source or account implementation remains.
- Only the final Luna ledger and completion report are being committed; no further UI or runtime
  work is planned in Milestone 3.75.

## Next exact implementation step

After this documentation checkpoint, verify local/remote SHA equality and the protected tag, then
stop. Any future work belongs to a separately authorized milestone; do not add another UI surface,
runtime behavior, or Milestone 4 code here.

## Luna finalization validation (2026-07-23)

- Repository state: passed. Branch is `milestone-3.75-visual-redesign`; local and remote HEAD were
  `8b6fd9d8e4bd52ee16de50ca08fd90686e46e32a` before this documentation checkpoint; the protected
  tag still peels to `b45b7763b65861f9dfb3be7edf9b5eb271950917`.
- Full frontend suite through the repository wrapper: blocked before test execution by the existing
  pnpm ignored-build-script policy for `sharp@0.34.5` and `unrs-resolver@1.12.2`.
- Full frontend suite through the installed web runner: passed, `9` test files and `31` tests.
- Production build through the repository wrapper: blocked by the same unchanged pnpm policy.
- Production build through installed Next.js: passed; Next.js `16.2.10` compiled, typechecked,
  generated all `6` static pages, and completed route optimization.
- Full web ESLint: passed with `--max-warnings=0`.
- Strict web TypeScript: passed with `tsc --noEmit`.
- Repository hygiene: passed for `187` source files.
- `git diff --check`: passed.
- Secret-pattern scan and prohibited-scope audit: passed; no secrets or runtime/agent/provider/
  worker/queue/scheduler/production changes were introduced.
- The browser capture limitation remains documented above: at narrow explicit viewport overrides,
  the in-app browser can crop the outer surface even when DOM geometry, overflow, reachability,
  accepted captures, and focused tests pass. No code change was made to work around that tool
  limitation.

## Resume commands

```sh
git branch --show-current
git status --short
git fetch origin
git rev-parse HEAD
git rev-parse origin/milestone-3.75-visual-redesign
git rev-parse competition-demo-v1
git rev-parse competition-demo-v1^{}
git log --oneline --decorate -15
cd apps/web
.\node_modules\.bin\vitest.CMD run
.\node_modules\.bin\next.CMD build
```

## Scope confirmations

- No default branch was changed.
- No protected tag was changed.
- No pull request was created.
- No Milestone 4 work was started.
- No active agents, subagents, delegation, tools, effects, or autonomous operation were implemented.
- No backend service, database migration, worker, queue, scheduler, provider, external AI or
  embedding call, production dependency, demo-content change, grounded-answer change,
  citation-data change, or Trace-semantics change was introduced.
- No secrets, credentials, generated dependency directories, temporary files, or test databases are intended for commit.
