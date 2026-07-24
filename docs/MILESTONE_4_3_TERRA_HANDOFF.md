# Milestone 4.3 Terra Handoff

## Frontend rollback flow complete locally

- Starting SHA: `9b1b04b35625446e17537584ab10d88335447052`.
- Frontend implementation: `f6362db65e85cc7cc7f3019d14e564962668634d`.

The current Milestone 3.75 canvas now presents the completed review, approval, and execution chain
for a known completed effect supplied as `rollbackEffectId`. The control is disabled in
deterministic replay mode, loads only the authenticated server review, and presents the action only
when that review is eligible. Create effects explain that the unchanged created note will be
removed; update effects explain that the server-captured prior title/text will be restored.

An accessible confirmation is required before approval issuance. Approval and execution use
separate idempotency keys and pending states, prevent repeat submission, and accept no
authority-bearing client fields. Successful execution refreshes the canvas snapshot and reports
note removal, prior-state restoration, or exact-duplicate completion without exposing internal
result evidence.

Closed UI messages distinguish expired approval, stale note conflict, unavailable or revoked
authority, authentication/CSRF failure, already-completed rollback, ineligibility, and a safe
generic failure. The client schemas and component never render prior state, evidence, grants or
grant digests, policy internals, SQL/database detail, stack traces, or raw exception text.

Validation: focused component/API-client coverage reported `19 passed`; the complete frontend
unit/component suite reported `48 passed` across 11 files. TypeScript, ESLint, Prettier,
`git diff --check`, repository hygiene, and the production Next.js frontend build passed. A
browser-driven visual audit, backend regressions, PostgreSQL runtime, external services, and network
tools were not run. No backend code changed and no remote operation occurred.

### Exact next checkpoint

Perform only the final Milestone 4.3 audit of the completed proposal, approval, effect, rollback
review, rollback approval, atomic rollback execution, audit/Trace, and frontend flow. Do not begin
Milestone 4.4 or Milestone 5 automatically.

## Atomic rollback execution complete locally

- Starting SHA: `75a83551275222465a30cb1fb670a90ade3e8c7f`.
- Persistence correction: `15b0913`.
- Atomic execution implementation: `8f1d22e`.

The backend now executes only the two approved inverse actions. Create rollback removes the exact
unchanged note produced by its effect and records canonical authoritative absence. Update rollback
restores only immutable evidence title/text through revision/content compare-and-set and advances
the note revision. The server derives every action, target, digest, evidence, grant, scope, and
result field from persisted authority.

The inverse note change, canvas revision, immutable result, audit event, and Trace start/completion
are one transaction. Three injected failure points prove rollback after note mutation, after result
construction, and after audit insertion. Exact duplicate delivery returns one existing result;
conflicting keys and later attempts do not repeat the mutation.

The authenticated CSRF-protected endpoint accepts only path identifiers and one idempotency key.
Unknown authority fields fail schema validation, inaccessible scope fails closed, and safe responses
omit prior state, evidence/grant material, policy internals, SQL, and exception details.

Two concrete defects were corrected. The unpublished `0014` live-node foreign keys were removed
from immutable approval/result note references so create rollback can delete the note while
preserving historical evidence. Duplicate result timestamps now use the existing UTC serializer,
keeping first and replayed API responses identical.

Validation: `62 passed` in the complete reversible-effects module and `183 passed` in the affected
SQLite regression group. The rollback-authority migration upgraded, downgraded, and re-upgraded
successfully. Ruff, strict mypy, compilation/imports, mapper validation, and sole Alembic head
`20260724_0014` passed. PostgreSQL runtime, frontend, unrelated full suites, and network tools were
not run.

### Exact next checkpoint

Begin only separately authorized frontend integration for the completed rollback review, approval,
and execution APIs. Do not begin Milestone 4.4 or Milestone 5 automatically.

## Rollback approval issuance validated locally

- Starting SHA: `70be72c0b6216aed0245bc6fcea37678c430ef14`.
- Local checkpoints: `290a75c` (scope/authentication/CSRF), `42aebec`
  (revalidation/capability/grant denial), and `e9d680a` (non-mutation/response/request authority).

The server-authoritative issuer is now validated across successful create/update issuance, exact
duplicate replay, authoritative-state replay conflict, expired replay, cross-user/workspace/canvas
scope denial, mismatched grant authority, real-session authentication and CSRF, fresh note/evidence
verification, closed rollback capabilities, expired/revoked grants, invalid effect state, and a
pre-existing successful rollback result.

Request authority remains limited to the path-owned workspace/canvas/effect and one scoped
idempotency key. Unknown fields cannot override revision, action, target, evidence, capability,
grant, proposal, execution, ownership, digest, or expiry. Successful responses expose only the
declared response schema. Failed or successful issuance does not mutate source authority, consume
forward approval state, create a rollback result, or emit rollback-completion audit/Trace evidence.

The affected SQLite regression group reported `161 passed`. Focused Ruff, strict mypy, compilation
and imports, SQLAlchemy mapper validation, and sole Alembic head `20260724_0014` passed. PostgreSQL
runtime, frontend, rollback execution, unrelated full suites, and network tools were not run. No
remaining issuance defect is known.

### Exact next checkpoint

Implement only the separately authorized atomic rollback transaction: revalidate the immutable
approval/effect/evidence and live note inside one transaction, apply the exact compare-and-set
inverse, and persist one immutable rollback result plus truthful audit/Trace evidence. Do not begin
frontend, Milestone 4.4, or Milestone 5.

## Backend rollback issuance implementation checkpoint (historical)

This implementation-only status is superseded by the validated checkpoint above.

`7bfccd69e6a4e61178b5a1154f8283c9704313e3` adds only approval issuance: a CSRF-protected endpoint,
safe schemas, and an issuer that re-runs the existing authoritative review inside its nested write
boundary. It creates the immutable approval with server-derived scope, canonical target/approval
digests, 15-minute expiry, and database-backed idempotency; it does not modify a note or create a
rollback result. Static validation passed; focused API/service tests and all execution work remain
unfinished. Resume with issuer tests, then the separate compensating transaction.

## Rollback approval authority contracts complete locally

- Starting SHA: `3b7d7dc04d9628a5709b83cab2aaf7f372ed7c17`.
- Contract commit: `96b1119e71a118a9c98ac1c5c287a6bc6eae4f9b`.

`authoritative_absence_digest()` now hashes exactly the canonical payload
`{"resource":"canvas.note","state":"authoritative_absence"}` under
`controlled-agent.rollback-target.v1`. It is the sole permitted create-rollback target digest;
update restoration continues to use immutable evidence `before_digest` without rehashing.

`rollback_approval_digest()` hashes only the typed, server-owned approval bindings under
`controlled-agent.rollback-approval.v1`, including schema version, authority scope, effect/proposal,
closed actions, verified revisions/digests, optional evidence ID, grant, key, and canonical expiry.
`ROLLBACK_APPROVAL_TTL` is exactly 15 minutes. The later issuer must never replace an expired approval
under the same scoped key.

The ORM and unpublished `20260724_0014` migration now share
`uq_agent_rollback_approval_execution_scope_idempotency` across `(execution_id, user_id,
workspace_id, canvas_id, scoped_idempotency_key)`, providing database-backed duplicate protection.

Focused contract, persistence, and SQLite migration-cycle validation: `92 passed`. Ruff, strict mypy,
compilation, Alembic sole-head inspection, diff/whitespace, secret-like-material, and prohibited-scope
checks passed. PostgreSQL runtime, issuance/execution, frontend, unrelated suites, and network tools
were not run. No remote operation occurred.

### Exact next checkpoint

Implement the server-authoritative rollback approval issuer only, using these contracts and fresh
in-transaction review revalidation. Do not execute rollback.

## Rollback revision contract corrected locally

- Starting SHA: `04119652d54c5c907fad9140ebcf8ae337ca5986`.
- Correction commit: `9f3ec4ff87bcf0de8f22a0744581006b74764a67`.

The authoritative create-effect contract produces revision `0`; update effects produce a positive
revision. The unpublished `20260724_0014` migration and matching ORM now enforce that exact closed
rule through `ck_agent_rollback_approval_expected_revision_action` and
`ck_agent_rollback_result_expected_revision_action`. Create approvals/results require expected
revision `0`; update approvals/results require a positive expected revision. Existing action/target
checks continue to require create-result absence and positive non-null update-result revisions.

SQLite persistence and migration-cycle coverage: `79 passed`; focused Ruff, strict mypy, compilation,
Alembic sole-head inspection, diff/whitespace, secret-like-material, and prohibited-scope checks
passed. PostgreSQL runtime, approval issuance/execution, frontend, unrelated suites, and network tools
were not run. No remote operation occurred; main and `competition-demo-v1` remain unchanged.

### Exact next checkpoint

Implement server-authoritative rollback approval issuance only, revalidating the current rollback
review state in the issuing transaction. Do not execute rollback.

## Rollback eligibility review complete locally

- Starting SHA: `2fd3b09d28e83e7aaae9ef7d70483bb04f20d9c1`.
- Implementation SHA: `784a46ad2f94496e7aa6828abde0aeaf19a339a3`.
- Branch: `milestone-4.3-reversible-writes-local`; upstream: none; remote freeze preserved.

`GET /workspaces/{workspace_id}/agent-executions/canvases/{canvas_id}/reversible-effects/{effect_id}/rollback-review`
is the sole new operation. It is authenticated, scoped, and read-only: request authority is limited
to workspace, canvas, and original effect. It derives the closed rollback action, target kind, and
required rollback capability from persisted state; it neither creates an approval/result nor mutates
a grant, note, Trace, or any other record.

Create reviews recompute only the legacy ID/revision/title/text note digest. Update reviews require
the immutable evidence record, exact `{title, text}` prior-state contract, matching canonical
before/after digests, and `verify_completed_effect_state`; no cross-format fallback exists. The
review denies on missing/stale/changed note state, malformed or mismatched evidence, a prior rollback
result, and absent/expired/revoked/mis-scoped rollback grants. Safe responses omit prior state,
digests, raw grants, and authority records.

Focused validation: the review and affected reversible-write group reported `85 passed` on SQLite.
Focused Ruff format/lint, strict mypy, compilation, Alembic sole-head inspection (`20260724_0014`),
diff/whitespace, secret-like-material, and prohibited-scope checks passed. PostgreSQL runtime,
frontend, rollback approval issuance/execution, unrelated suites, and network tools were not run.

`main` remains `f04ace592e253c48172d129331ed8cd9bc4d4f4f`; `competition-demo-v1` remains
`b45b7763b65861f9dfb3be7edf9b5eb271950917`; no remote operation occurred.

### Exact next checkpoint

Implement server-authoritative rollback approval issuance only: re-run this review immediately before
minting one immutable approval tied to its exact effect, note, revision, evidence, target digest, and
rollback capability. Do not execute rollback or begin frontend, final audit, Milestone 4.4, or 5.

## Note-create effect digest contract complete locally

- Starting SHA: `12faee145c03d1b776fd0941e7d1ad4caa2ff1ea`.
- Compatibility commit: `f4fe90ac0b73d46f4c6d089ee2d5a06d4671f6ef`.

`verify_completed_effect_state` is a fail-closed internal helper. `note.create` recomputes the
existing `_note_digest` from exact persisted note ID, revision, title, and text. `note.update`
requires exact rollback evidence and validates only canonical evidence state/digests; neither path
falls back to the other. No migration or historical backfill was needed: all create-effect writers
use the same existing helper. Focused persistence tests: `63 passed`; Ruff and strict mypy passed.

### Exact next checkpoint

Implement server-authoritative rollback eligibility review only, using this verifier. Do not issue
approval or execute rollback.

## Rollback-specific capability contract complete locally

- Starting SHA: `8c0fc5b02ca3953065ecacde830c52122ed89734`.
- Capability checkpoint: `2cbc34f4e088a0fdd186db9a0e3b2759d5aaa039`.
- Added closed values: `canvas.note.create.rollback` and `canvas.note.update.rollback`.

The pure mapping permits each value only for its matching inverse note action; it rejects forward
create/update substitution, cross-rollback substitution, and unknown values. No migration is
required because capability strings remain canonical payload data. Focused contract checks: `10 passed`;
Ruff, strict mypy, and diff checks passed. PostgreSQL and network tools were not run.

### Exact next checkpoint

Implement only server-authoritative rollback eligibility review and rollback-approval issuance using
these narrow capabilities. Do not execute a rollback.

## Rollback-authority SQLite validation complete locally

- Starting SHA: `f202e530385bc74781142d330f6a2849aa726502`.
- Validation commit: `a707c88d0d0c64fb9d2b7840745bbf124d616f79`.
- Branch: `milestone-4.3-reversible-writes-local`; upstream: none; no remote write occurred.
- Database: SQLite only. PostgreSQL runtime was not configured or run.

Focused persistence coverage validates both closed rollback-approval forms and both successful
rollback-result forms; digest, action, target, revision, evidence, grant, scope, uniqueness, and
append-only rejections; plus scoped idempotency and result identity behavior. The focused SQLite
persistence/migration-chain set reported `71 passed`.

The migration cycle upgrades `0013` to `0014`, verifies both tables, named checks, indexes,
foreign-key declarations, and four SQLite mutation-blocking triggers, downgrades to `0013`, confirms
cleanup while rollback evidence remains, then re-upgrades to sole head `0014`.

One defect was corrected: the update rollback-result check now requires non-null, positive
`resulting_revision`; SQLite permits `NULL` through a bare `> 0` expression. No other model or
migration defect was found.

Focused Ruff format/lint, strict mypy, Python compilation, model/migration imports, mapper and
SQLite metadata construction, Alembic head inspection, whitespace/diff, secret-like-material, and
prohibited-scope checks passed. Frontend, unrelated backend/API/service, PostgreSQL, and network
checks were not run.

`main` remains unchanged and `competition-demo-v1` remains
`b45b7763b65861f9dfb3be7edf9b5eb271950917`; no remote operation occurred.

### Exact next checkpoint

Implement separately authorized server-authoritative rollback review and execution only: revalidate
new approval, effect, evidence, and current state inside one compensating transaction; refuse later
unrelated changes; persist immutable result/audit/Trace evidence. Do not add frontend or Milestone 4.4.

## Rollback-authority migration complete locally

- Starting SHA: `783a55a6f66346d2e12d6d5444c8257f834da93d`.
- Migration commit: `4c8f5c4b30d0e7b87bd5cb57b34fa4d19323f398`
  (`Add rollback authority migration`).
- Branch: `milestone-4.3-reversible-writes-local`; upstream: none; no remote write occurred.
- Migration: `20260724_0014_reversible_write_rollback_authority`, revising `20260724_0013`.

The migration creates `controlled_agent_reversible_write_rollback_approvals` first, followed by
`controlled_agent_reversible_write_rollback_results`. It mirrors the completed ORM contracts:
scope-bound proposal/effect/note/grant relationships for approvals; approval/proposal/effect/note
relationships for results; closed note-create removal and note-update restoration actions; digest,
revision, idempotency, time, and successful-result uniqueness constraints; and all declared lookup
indexes, including Trace correlation on results.

Both tables are append-only. SQLite receives named `BEFORE UPDATE` and `BEFORE DELETE` rejection
triggers. PostgreSQL receives migration-specific rejection functions and combined UPDATE/DELETE
triggers. Downgrade removes result protections/table first, then approval protections/table, leaving
`20260724_0013` and earlier objects untouched.

Static validation at the migration checkpoint:

- Python compilation, module import, down-revision inspection, and Alembic sole-head validation:
  passed (`20260724_0014`).
- Static model-to-migration comparison of both table column lists, named constraints, and indexes:
  passed.
- SQLite and PostgreSQL trigger-definition inspection: passed.
- Focused Ruff format/lint and strict mypy: passed.
- `git diff --check`, whitespace, secret-like-material, and prohibited-scope checks: passed.
- PostgreSQL runtime, Alembic upgrade/downgrade/re-upgrade cycle, persistence tests, frontend tests,
  unrelated backend tests, and network tools: not run.

`main` remains unchanged and `competition-demo-v1` remains
`b45b7763b65861f9dfb3be7edf9b5eb271950917`. No push, pull, fetch, upstream change, tag operation,
publication, deployment, or GitHub write occurred.

### Exact next checkpoint

Run only rollback-authority SQLite persistence and migration-cycle tests: upgrade from `0013` to
`0014`, inspect both tables/constraints/indexes/triggers, downgrade to `0013`, re-upgrade, then test
valid and rejected approval/result persistence plus append-only behavior. Do not implement rollback
review or execution, routes, frontend work, Milestone 4.4, or Milestone 5.

## Rollback evidence bound to atomic note updates locally

- Starting SHA: `5281d85ab60c4036d1ed8200bd738a8530ae839e`.
- Transaction-integration commit: `8dde7573e3dbdffe78be2ecb19339b47d10c6fa3`
  (`Bind note updates to rollback evidence`).
- Branch: `milestone-4.3-reversible-writes-local`; upstream: none; no remote write occurred.
- Database validation: SQLite only. PostgreSQL was not configured or run.

For an approved `note.update`, the existing nested server-authoritative transaction now captures the
exact mutable state changed by that action—NFC-normalized `title` and `text`—before the compare-and-
set update. It serializes that JSON object with sorted keys, UTF-8, and compact separators, then
stores its SHA-256 digest. It calculates the post-update digest with the same canonical state rule.
The service flushes the immutable effect result and inserts exactly one immutable rollback-evidence
row bound to that effect, proposal, user, workspace, canvas, note, pre-update revision, post-update
revision, before state, and both digests before audit/Trace success records complete.

Creates still produce no rollback-evidence row. Exact duplicate update delivery returns the original
effect and creates neither a second note update, approval consumption, nor evidence row. Older effects
are not backfilled and therefore remain rollback-ineligible without exact authoritative evidence.
Any failure inside the nested transaction rolls back the note update, approval consumption, effect,
rollback evidence, audit success, and Trace success together.

Validation at the integration checkpoint:

- Focused transaction-integration tests: `6 passed`.
- Affected backend group (effects, effect persistence, proposals/approvals, agent API, migrations):
  `56 passed`.
- Focused Ruff format/lint and strict mypy for changed service/tests: passed.
- `git diff --check`, local secret-like-material scan, and prohibited-scope scan: passed.
- Skipped: PostgreSQL, frontend suites, unrelated backend suites, and all network tools.

No rollback execution, rollback review endpoint, frontend work, worker, queue, scheduler, delegation,
provider, or Milestone 4.4/5 behavior was added. `main` remains unchanged and
`competition-demo-v1` remains `b45b7763b65861f9dfb3be7edf9b5eb271950917`.

### Exact next checkpoint

Implement separately authorized server-authoritative rollback review and execution: require a new
approved proposal/key, compare the current note against the evidence after state, create a linked
immutable compensating effect/audit/Trace record, and refuse to overwrite later unrelated changes.

## Rollback-evidence migration cycle validated locally

- Starting SHA: `2c76d113b7477dd5df3df37e2c0aa409785bec59`.
- Branch: `milestone-4.3-reversible-writes-local`; upstream: none; no remote write occurred.
- Database environment: SQLite only through the repository Alembic/pytest harness. PostgreSQL was
  not configured or run.

Migration `20260724_0013_reversible_write_rollback_evidence` upgraded from `20260724_0012`, created
the rollback-evidence table, named scope/note indexes, composite foreign keys, action/revision checks,
the `ck_agent_rollback_evidence_before_state_object` JSON-object check, and append-only UPDATE/DELETE
triggers. A direct SQLite check proved JSON `null` is rejected and direct UPDATE/DELETE are rejected.
Downgrade to `20260724_0012` removed the evidence table, its triggers, and its parent-effect scope
index while preserving the `20260724_0012` effect table and immutable triggers. Re-upgrade restored
`20260724_0013` as the sole migration head.

The cycle exposed no migration defect. It did expose six stale current-head assertions and one stale
script-directory head assertion in the existing SQLite migration harness; they now expect `0013` when
testing an upgrade to `head`. Explicit `0012` target/downgrade assertions remain unchanged.

Validation:

- SQLite migration-chain suite: `8 passed`.
- Focused rollback-evidence persistence suite: `35 passed`.
- Focused migration-cycle test: `1 passed` before the broader migration-chain run.
- Strict mypy, Ruff format/lint, Python compilation, Alembic import/head validation, and whitespace
  checks: passed.
- Skipped: PostgreSQL execution, unrelated backend/frontend suites, and all network tools.

`main` remains unchanged and `competition-demo-v1` remains
`b45b7763b65861f9dfb3be7edf9b5eb271950917`. No remote operation, upstream change, or tag operation
occurred.

### Exact next checkpoint

Bind the already-validated rollback evidence into the atomic server-authoritative note-update
transaction. Do not begin rollback execution, frontend work, Milestone 4.4, or Milestone 5.

## Atomic reversible note effect complete locally

- Starting SHA: `177376f76b6c77a89229d5c4ddee69bcf43e3d6b`.
- Atomic-effect implementation commit: `3a959d9d70c45348c7fc4e1553e0afca32fe9647`.
- Branch: `milestone-4.3-reversible-writes-local`; upstream: none; no remote write occurred.

`ReversibleWriteEffectService` is the sole synchronous, server-authoritative effect path. The
CSRF-protected endpoint accepts only an execution ID and idempotency key. It reconstructs the
persisted proposal, exact preview content, canvas/destination, resource/revision, execution, plan,
grant, and approval server-side; it does not accept client authority, action, content, digest, or
success state.

Within one nested database boundary it checks owned user/workspace/canvas scope, proposal digest and
plan binding, approval decision/expiry, grant expiry/capability/revocation through the authoritative
approval-consumption policy, exact proposal idempotency, and current canvas/revision. Exact duplicate
delivery returns the immutable prior effect. Conflicting keys fail closed. Creation writes one note at
the approved canvas; update uses an exact node-revision compare-and-set. The transaction records
before/after digests, resulting resource/revision, immutable effect result, audit evidence, and
started/succeeded scoped Trace evidence. Any exception rolls back the note, consumption, effect,
audit, and Trace success records.

Focused coverage at `3a959d9`:

- Atomic create, update, exact duplicate, conflicting key, missing execution, stale update, before/
  after evidence, audit/Trace evidence, single consumption, and injected post-mutation rollback:
  `5 passed`.
- Affected proposal, persistence, schema, API, effect-persistence, and migration regressions:
  `59 passed`.
- Strict mypy for the service, endpoint, schemas, and tests; focused Ruff format/lint; `git diff
  --check`; and repository hygiene/secret scan: passed.
- PostgreSQL integration, network tools, frontend checks, and unrelated backend suites: not run.

No rollback feature, frontend work, worker, queue, scheduler, provider, Milestone 4.4, or Milestone
5 work was added. `main` remains unchanged and `competition-demo-v1` remains
`b45b7763b65861f9dfb3be7edf9b5eb271950917`.

### Exact next checkpoint

Review the atomic effect boundary, then implement separately authorized rollback only: a new approved
proposal/key, after-state compare-and-set, linked immutable compensating effect/audit/Trace evidence,
and refusal to overwrite later unrelated changes. Do not start it automatically.

## Effect-result persistence validated locally

- Starting SHA: `9d2bb55bf3523e46691eb92e4adeda55f8ca2525`.
- Persistence-test checkpoint: `9cb3781c08b09b162579ea6f43e3e0a2cc4db5ed`.
- Branch: `milestone-4.3-reversible-writes-local`; upstream: none.
- Database environment: SQLite only. PostgreSQL was not configured or run.

The focused tests exposed and corrected two concrete database-integrity gaps before the effect
record could be accepted: proposal and approval IDs are now bound to the same execution, user,
workspace, canvas, and action scope as the effect. The migration also enforces the closed
create/update resource shape: creates cannot carry update-only resource/revision/before-state
fields, while updates require the bound resource, expected revision, matching result resource, and
before-state digest.

The SQLite persistence coverage verifies valid create and update result records; required fields;
proposal, approval, user, workspace, and canvas scope; cross-scope rejection; closed actions and
outcomes; plan-digest presence; scoped idempotency; distinct identities; result uniqueness;
create/update nullable-field combinations; and direct migrated-trigger UPDATE/DELETE rejection.
Migration coverage upgrades `20260724_0011` to `20260724_0012`, confirms the sole head, table,
indexes, constraints, and immutable triggers, downgrades to `20260724_0011` and confirms removal,
then re-upgrades and reruns persistence tests.

Validation at `9cb3781`:

- Focused effect persistence, migration, and reversible-proposal chain: `34 passed` (SQLite).
- Strict mypy for changed tests: passed (2 source files).
- Focused Ruff format and lint: passed.
- Static migration validator: passed upgrade to `20260724_0012`, downgrade to
  `20260724_0011`, and re-upgrade to `20260724_0012`.
- `git diff --check`, repository hygiene/secret scan, and diff-scoped prohibited-scope scan:
  passed.
- Skipped: PostgreSQL integration, unrelated backend/frontend suites, and all network tools.

No remote write, fetch, pull, sync, upstream change, or tag operation occurred. `main` is
unchanged; `competition-demo-v1` remains protected at
`b45b7763b65861f9dfb3be7edf9b5eb271950917`.

### Exact next checkpoint

Implement only the atomic server-authoritative note create/update transaction: reload and verify
the owned proposal/approval/grant/context/plan inside one transaction, consume approval once,
apply the note compare-and-set, persist this immutable effect result with safe audit/Trace evidence,
and roll back every write on denial, conflict, or persistence failure. Do not add a route, rollback
feature, frontend work, worker, queue, scheduler, provider, or Milestone 4.4 work in that checkpoint.

## Phase 1 complete locally: proposal and approval foundation

- Starting Sol handoff: `718ca72e7af6141feb4e6bffc8be9edf74e27995`.
- Documentation correction checkpoint: `90a4e320b373e46ee2bf48ac183a19ba1e6c7fc7`.
- Branch: `milestone-4.3-reversible-writes-local`; no upstream and no remote branch.

## Implemented boundary

`20260724_0011_reversible_write_proposals` persists immutable review-only proposals, scoped to one
user, workspace, canvas, server-owned execution, action, idempotency key, canonical payload digest,
and Trace ID. The service creates only `note.create` or `note.update` proposals, reloads ownership
server-side, binds exact canvas/note revisions, creates existing immutable execution/context/plan/
grant records, and records proposed/awaiting-approval states plus audit evidence. Approval also
fails closed when the grant has already been revoked.

CSRF-protected endpoints create a proposal and explicitly approve its presented proposal digest. An
approval is persisted once and transitions to `ready`; it is not consumed here and no canvas node is
created, updated, deleted, or rolled back. Existing grant expiry, scope, immutable plan, and later
single-use-consumption controls remain authoritative for an effect phase.

## Phase 1 validation

- Proposal/approval, contract, persistence, and API set: `25 passed`.
- New service/route strict mypy: passed.
- New-file Ruff format/lint: passed.
- Migration cycle: upgrade `20260724_0011`, downgrade `20260724_0010`, re-upgrade: passed.
- `git diff --check`: passed before this handoff record.

## Known limits and exact next unit

No workspace effect, approval consumption, rollback, frontend control, worker, queue, scheduler,
delegation, provider, external AI behavior, or Milestone 4.4 code has been added. Phase 2 may add
only the minimal server-authoritative note create/update transaction, consuming the already persisted
approval atomically with compare-and-set revision checks and safe audit/Trace evidence. It must first
add tests for wrong scope, missing/expired/revoked/replayed approval, stale/concurrent revisions,
transaction failure, and exact/conflicting duplicate execution.
