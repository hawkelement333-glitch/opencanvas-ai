# Milestone 4.2 Terra Handoff

Last updated: 2026-07-23 (America/Chicago)

## TERRA IMPLEMENTATION INCOMPLETE

Terra now has a bounded, server-authoritative controlled grounded-draft path. Its remaining blocker
is intentional: the synchronous start route only returns an execution identifier after the
provider-backed operation is terminal. The browser therefore has no authoritative target for an
in-progress cancellation request, and does not display a misleading cancellation control.

## Verified state

- Branch: `milestone-4-controlled-agents`.
- Terra began at `7b968146b413a1d0c09c42564915d06c2b5efc41`.
- Service checkpoint: `7dd816a15a7a3f995b41c54ea0f0900f4ad15764`.
- API checkpoint: `8dfd290d9b541fa5fedfb4ab49fe6a22a273ad3d`.
- UI checkpoint: `aacfdf28a4a3771fecd3ac0b36e453662c5f512a`, normally pushed to the same
  branch.
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
  queue, scheduler, delegation, provider, embedding, migration, dependency, Milestone 3.75, Luna,
  or Milestone 4.3 work was added.

## Checks run

- Controlled-agent backend suite: `37 passed`.
- Frontend suite: `9 files passed`, `33 tests passed`.
- Frontend typecheck, lint, and production build: passed.
- Focused changed-file Prettier and `git diff --check`: passed before the UI checkpoint.
- Repository-wide `npm run format:check`: not clean on the pre-existing 16-file baseline.
- PostgreSQL migration execution, browser smoke, dependency audit, and deterministic-demo E2E:
  not run in this Terra task. PostgreSQL remained unavailable during the prior Sol gate.

## Exact next authorized work

1. Complete only the missing Terra cancellation contract: design a server-owned, non-autonomous way
   to return a real active execution identifier before provider completion. Preserve all Sol
   lifecycle, immutable-context, cancellation, and late-result rules.
2. Do not use a client-generated execution ID, aborted fetch, polling loop, worker, queue,
   scheduler, or autonomous execution. Do not start Luna yet.
3. Add focused UI coverage for cancellation request and server-confirmed cancellation only after the
   contract exists; re-run the Terra gate and update this handoff to an evidence-backed completion
   decision.
