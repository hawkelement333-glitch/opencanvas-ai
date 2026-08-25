# Milestone 7.8 pre-expiry maximum-safe progress handoff

Date: 2026-08-18

Status: all currently executable repository-local work completed; the retained
account remains present; Milestone 7.8 remains incomplete

> **2026-08-25 local architecture correction:** the historical
> `blocked-provider-retention` controller disposition below is superseded for
> new source by one stable reusable Automation controller outside campaign
> deletion scope. Campaign preparation requires exact-controller adoption;
> ordinary cleanup cannot create or delete the controller. The current state is
> `architecture-corrected-live-execution-not-authorized`. No Azure operation
> established live operability. See the
> [cleanup-controller architecture correction handoff](MILESTONE_7_8_CLEANUP_CONTROLLER_ARCHITECTURE_CORRECTION_HANDOFF.md).

## Authoritative boundary

- Starting HEAD: `637e7a100a79c03100272bd3c8bafd994289d953`
- Branch: `milestone-7-8-production-readiness-audit-local`
- Starting upstream: absent
- Starting tracked tree and index: clean
- Protected stashes: exactly five, untouched
- Alembic: sole head `20260726_0029`; migration 0030 absent
- Azure authority in this continuation: GET/read-only only

The retained Milestone 7.7 terminal chain was not reopened or regenerated. Its
nine stages, 91 samples, 5,400 uninterrupted seconds, and ten zero residue
counters remain historical evidence.

## Dependency audit

The earlier pause was the support-ticket and managed-campaign execution
boundary, not a dependency of every remaining Milestone 7.8 requirement. The
governing plan independently requires audits of object storage, Indexer,
durable workers, shared limits, observability, recovery, capacity/security,
regressions, and documentation. None logically depends on the old deleted
Automation record.

| Classification                                              | Unfinished requirement at entry                                                                                                                                                        | Disposition in this continuation                                                                                |
| ----------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| Executable locally now                                      | Retention evidence replayability and post-expiry verifier                                                                                                                              | M78-PG-012 corrected and tested                                                                                 |
| Executable locally now                                      | Object upload, quarantine, scanner, promotion, deletion, and recovery audit                                                                                                            | Local audit complete; M78-OS-001 corrected                                                                      |
| Executable locally now                                      | Indexer, durable jobs, rate limits, observability, recovery contracts, authority, graph, workflow, agents, documents, frontend, browser, migration, configuration, and Git regressions | Bounded shards completed; results below                                                                         |
| Executable through Azure GET now                            | Current retained-account identity, count, location, timestamp, and unrelated-record preservation                                                                                       | One strict current-presence run passed; sanitized receipt retained                                              |
| Requires separately authorized Azure mutation               | M78-PG-E01, M78-PG-E02, M78-PG-E03, M78-TI-E01, M78-PG-E04                                                                                                                             | Open; local evidence cannot replace managed execution                                                           |
| Requires separately authorized Azure mutation               | Current managed object/scanner, Managed Redis, live telemetry, managed recovery, and capacity/failure evidence                                                                         | Open; no infrastructure was created or changed                                                                  |
| Strictly blocked by retained-account expiration             | Exact absence of the prior generated Automation account                                                                                                                                | Named external gate; verifier refuses Azure access before the boundary                                          |
| Requires architecture correction and separate authorization | A cleanup controller able to satisfy zero residue without creating another retained record                                                                                             | Corrected locally on 2026-08-25; live bootstrap, adoption, and campaign evidence remain separately unauthorized |

Expiration is therefore not the sole remaining blocker. It can prove absence of
the prior record, but does not make the current Automation-based controller
armable and does not generate any required managed evidence.

## M78-PG-012 retention correction

The original sanitized receipt's target and unrelated-record hashes were not
replayable against the documented authoritative resource-ID fields. The new
GET-only `infra.milestone_7_8.retention` verifier:

- validates the ignored runtime and tracked sanitized receipt;
- confirms the authenticated subscription without printing it;
- calls only the documented `2024-10-23` deleted-account list endpoint through
  the centralized Azure CLI launcher and follows all safe `nextLink` pages;
- validates exact name, region, subscription, top-level deleted-record ID,
  original Automation-resource ID, and deletion instant relationships;
- preserves four unrelated records by domain-separated hashes;
- emits no raw IDs and contains no Azure mutation verb;
- rejects normal absence checks before the exact boundary without an Azure
  call; and
- permits the one-time legacy reconciliation only for a present record and old
  receipt, never for an absence claim.

The tracked
[`automation-retention-live-reconciliation.json`](../evidence/milestone_7_8/automation-retention-live-reconciliation.json)
records corrected hashes only. The historical receipt is unchanged. The final
strict current-presence run proved five total records, one target, four
unrelated records, one inventory page, two GET operations, and zero mutations.

Authoritative deletion time: `2026-08-15T01:09:46.307Z`.
Earliest expected boundary: `2026-09-14T01:09:46.307Z`.

## M78-OS-001 object deletion correction

The local object audit proved that durable exact-version deletion requests
were created and fenced reads but had no production executor. The existing
0027 schema was sufficient; no migration was added.

The database worker now handles one request before ordinary work. It locks the
request with skip-locked semantics, revalidates workspace, immutable version,
and lifecycle state, invokes exact-version deletion, and appends one terminal
`deleted` transition in the database transaction. Concurrent workers cannot
execute the same locked request. If the provider commits and the response is
ambiguous, the database transaction rolls back; retry accepts only
authoritative exact-version absence and commits the original terminal result.
Authorization and transport failures remain errors. Same-key conflicting
deletion intent returns 409.

The disabled legacy development/demo unlink path remains a documented
limitation. Trusted staging/production ingestion cannot fall back to it.

## Validation corrections

The scanner-bridge success fixture was aligned to the current managed-binding
cleanup deadline. Intentional old-deadline rejection tests and all retained
evidence remain unchanged. The browser document mock now returns one
deterministic processing poll before readiness, eliminating a race while still
proving both UI states. These are validation-harness corrections, not
production behavior changes.

## Exact validation ledger

All commands used installed dependencies. Python shards set
`PYTHONDONTWRITEBYTECODE=1`; final runs disabled pytest cache creation.

| Command or bounded shard                                                | Result                                                                                  |
| ----------------------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| `python -m pytest -o addopts='' -q apps/api/tests -k milestone_7_8`     | exit 0; 132 passed, 2,462 deselected; one dependency deprecation warning                |
| object/scanner/document/release shard                                   | exit 0; 137 passed, 1 PostgreSQL fixture skipped                                        |
| Indexer plus graph-retrieval shard                                      | exit 0; 24 passed, 1 PostgreSQL fixture skipped                                         |
| durable jobs, events, shared limits, recovery limiter, governance shard | exit 0; 63 passed, 1 PostgreSQL fixture skipped                                         |
| observability plus recovery-control shard                               | exit 0; 339 passed                                                                      |
| scanner-bridge recovery correction shard                                | exit 0; 261 passed                                                                      |
| current infrastructure contract                                         | exit 0; 94 passed                                                                       |
| agent/workflow shard                                                    | exit 0; 317 passed, 1 PostgreSQL fixture skipped in 547.34 seconds                      |
| collaboration/authority/canonical/trace/legacy-idempotency shard        | exit 0; 79 passed; one dependency deprecation warning                                   |
| migration/configuration/health/demo shard                               | exit 0; 152 passed, 10 PostgreSQL fixture skips; 15 SQLite adapter deprecation warnings |
| document extraction/processing/retrieval/AI shard                       | exit 0; 33 passed                                                                       |
| web Vitest                                                              | exit 0; 17 files and 75 tests passed                                                    |
| web ESLint, TypeScript, and Prettier                                    | exit 0 for each                                                                         |
| Next production build                                                   | exit 0; nine pages generated                                                            |
| Playwright after fixture correction                                     | exit 0; 8 passed, 2 real PostgreSQL scenarios skipped                                   |
| focused Ruff check and format check                                     | exit 0; clean                                                                           |

One attempted recovery/observability command named nonexistent 7.6 test files
and exited 1 with no tests collected; the corrected repository paths are in the
339-test recovery-control shard. One mixed historical 7.7 validation command
exited with 26 failures: 25 were caused by newly generated bytecode inside its
immutable bundle and passed after removal in the 94-test current contract run;
the remaining historical assertion requires migration 0029 to be absent and
is intentionally superseded by the authorized 7.8 migration. It is not used as
current-state evidence.

## Remaining gates

1. At or after the boundary, prove exact absence with the command below.
2. Correct or replace the structurally non-armable Automation cleanup
   controller under separate architecture and Azure authorization.
3. Separately authorize and execute managed PostgreSQL evidence for
   M78-PG-E01/E02/E03, M78-TI-E01, and M78-PG-E04.
4. Separately authorize current managed-provider proofs for object/scanner,
   Managed Redis, telemetry, recovery, and capacity/failure behavior.
5. Consolidate every remaining result, rerun final affected checks, and create
   `MILESTONE_7_COMPLETION.md` only when no Critical/High gap remains.

## Post-expiration command and success criteria

```powershell
.\.venv\Scripts\python.exe -m infra.milestone_7_8.retention `
  --runtime .runtime\milestone_7_8\runtime.json `
  --evidence evidence\milestone_7_8\automation-retention-live-reconciliation.json `
  --authoritative-deletion-time 2026-08-15T01:09:46.307Z `
  --expect absent
```

Success is exit 0 with `status=retained-account-absent`, four deleted records,
zero target candidates, four unchanged unrelated hashes, complete pagination,
and zero Azure mutations. Failure is nonzero and must not be waived. Success
does not authorize campaign execution.

## Prohibited operations and exit

Azure mutations: **0**. No support ticket, campaign/generation, account
restoration/deletion, quota, subscription, RBAC, provider, image, scanner,
soak, dependency, lockfile, remote Git, Milestone 8, protected-stash, secret,
or unrelated-resource operation occurred. The four unrelated deleted accounts
were observed only as hashes and remain out of scope.

Milestone 7.8 remains incomplete.
