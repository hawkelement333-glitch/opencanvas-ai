# Milestone 3.75 Completion Report

Status: **MILESTONE 3.75 VALIDATED WITH DOCUMENTED LIMITATION**

Date: 2026-07-23 (America/Chicago)

## Scope delivered

Milestone 3.75 remains visual polish only. The checkpoint improves the living-universe evidence
surfaces without changing demo facts, retrieval, citations, Trace semantics, providers, or backend
behavior:

- Source preview is a semantic dialog with stable title and metadata hierarchy, exact cited-passage
  focus, visible keyboard focus, contained scrolling, long-title wrapping, and full-viewport
  tablet/mobile presentation.
- Document cards expose the existing processing stage with restrained semantic status treatment;
  no progress percentage or new processing behavior was invented.
- Account loading and identity regions are explicit, long identities wrap, and the narrow account
  surface uses practical full-width touch targets.
- Focused regression coverage verifies the source-viewer accessibility and citation behavior.

## Validation

- Frontend tests through the installed runner: **passed — 9 files, 31 tests**.
- Production frontend build through installed Next.js 16.2.10: **passed**; compilation,
  TypeScript, 6 static pages, and route optimization completed.
- Full web ESLint with zero warnings: **passed**.
- Strict web TypeScript check: **passed**.
- Repository hygiene: **passed for 187 source files**.
- `git diff --check`: **passed**.
- Secret-pattern and prohibited-scope audits: **passed**.
- Deterministic demo smoke: **passed** earlier in the recovery checkpoint with external AI disabled.

The repository-level `pnpm --filter @opencanvas/web test` and `pnpm --filter @opencanvas/web build`
wrappers remain blocked before invoking the scripts by the existing ignored-build-script policy for
`sharp@0.34.5` and `unrs-resolver@1.12.2`. The policy was not weakened, no build approval was added,
and the installed web tools provided equivalent test/build execution.

## Browser evidence limitation

The in-app browser accepted the wide source-viewer and narrow account evidence and verified DOM
geometry, overflow, reachability, focus, and console cleanliness. At some explicit narrow viewport
overrides it cropped the outer surface despite correct measured layout. Those captures were rejected
and the limitation is documented in the progress ledger; no product workaround was added.

## Safety boundary

No workers, queues, schedulers, autonomous agents, tool-calling behavior, external AI or embedding
calls, production services, new dependencies, Milestone 4 code, or competition-demo content changes
were introduced. `competition-demo-v1` remains unchanged and peels to
`b45b7763b65861f9dfb3be7edf9b5eb271950917`.

## Handoff

The visual redesign checkpoint is complete within the documented validation limitation. The next
action is to stop this milestone and obtain separate authorization before any Milestone 4 work.
Resolve the final documentation commit with `git rev-parse HEAD` after committing and verify the
same SHA on `origin/milestone-3.75-visual-redesign`.
