# Milestone 4.2 Terra Handoff

Last updated: 2026-07-23 (America/Chicago)

## TERRA IMPLEMENTATION COMPLETE — READY FOR LUNA

Terra now has a bounded server-authoritative controlled grounded-draft path with truthful active
execution cancellation: preparation returns a real server-issued ID in `ready`, and explicit run
reconstructs the persisted request server-side. The browser cannot generate an execution ID or
authority payload and only shows cancellation after the lifecycle endpoint confirms it.

## Verified state

- Branch: `milestone-4-controlled-agents`.
- Terra began at `7b968146b413a1d0c09c42564915d06c2b5efc41`.
- Service checkpoint: `7dd816a15a7a3f995b41c54ea0f0900f4ad15764`.
- API checkpoint: `8dfd290d9b541fa5fedfb4ab49fe6a22a273ad3d`.
- UI checkpoint: `aacfdf28a4a3771fecd3ac0b36e453662c5f512a`, normally pushed to the same
  branch.
- Active-cancellation checkpoint: `9d78b723db7878739332c2d5398c5dd9e11a781e`, normally pushed to
  the same branch.
- Protected tag object: `acbde89b6e2cc3e41c372887794726d393836716`.
- Protected peeled demo commit: `b45b7763b65861f9dfb3be7edf9b5eb271950917`.

## Completed work

- Existing provider, authority preflight, immutable selected context, citation validation, usage
  limits, Trace behavior, late-result suppression, and authoritative cancellation are reused by the
  grounded-draft bridge and authenticated routes.
- The UI is limited to explicit start, live starting feedback, duplicate-start prevention,
  server-confirmed read-only result, authorized existing citation preview, and Trace link.
  Deterministic replay retains its existing assistant and has no controlled-draft UI.
- No browser authority, approval, lifecycle, context, citation-validation, or result-acceptance
  decision exists. Safe errors are generic. No workspace-write, automatic execution/retry, worker,
  queue, scheduler, delegation, provider, embedding, dependency, Milestone 3.75, Luna, or Milestone
  4.3 work was added. Migration `20260724_0010_agent_prepared_execution.py` is the one required
  persistence change for server-owned request reconstruction; it does not mutate workspace data.

## Checks run

- Controlled-agent backend suite after the cancellation contract: `38 passed`.
- Focused prepare/cancel/refused-run API coverage: included in `13 passed` focused API/bridge tests.
- Frontend suite after the cancellation contract: `9 files passed`, `32 tests passed`.
- Focused frontend cancellation/API-client coverage: `2 files passed`, `6 tests passed`.
- Frontend typecheck, lint, and production build: passed.
- Focused changed-file Prettier and `git diff --check`: passed before the UI checkpoint.
- Repository-wide `npm run format:check`: not clean on the pre-existing 16-file baseline.
- PostgreSQL execution, browser smoke, dependency audit, and deterministic-demo E2E were not run;
  PostgreSQL remains unavailable because Docker and a configured PostgreSQL test URL are absent.

## Luna audit result

Luna audit is complete at `9d78b72`; this final handoff records the corrected evidence. No further
Milestone 4.2 implementation is authorized. The next milestone must be separately approved and must
not reinterpret this prepare/run contract as a worker, queue, scheduler, polling loop, delegation,
or autonomous execution mechanism.
