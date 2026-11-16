# Milestone 7.8 historical evidence recovery

Date: 2026-11-16. Historical source references were inspected from checkpoint
`8236da2f8bb612732da3abf7f5297e02ec1cbd9c`; later local corrections and their
results are recorded separately in the
[local-gap completion report](MILESTONE_7_8_LOCAL_GAP_COMPLETION.md#local-postgresql-coverage).

This document closes artifact-location and historical skipped-test identity
mappings where the recovered evidence supports them. PostgreSQL, M78-D-001 and
M78-D-002 remain accepted with verified cleanup. Historical 7.6 and 7.7
acceptance is preserved. Retrieval did not execute a managed campaign, issue
Azure queries, run recovery, build an image or change acceptance criteria.

## Recovered 7.7 terminal evidence

The original directory was identified from an archived command:
`%TEMP%/mobius77-soak-final-b191a39/receipts`. It still exists but contains no
files. Archived tool outputs retained seven complete JSON payloads originally
read from that directory. Those JSON payloads were extracted into private
storage and verified with the existing side-effect-free
[`load_stage_evidence` contract](../preflight/milestone_7_7/terminal_lifecycle.py).

Each recovered payload validates against original repository HEAD
`b191a392922f94557e6ebf5914113b5e229ab00e` and ledger integrity
`6190368594c16c8c67524a880080fca6cbb1e507ea06a0d68a515258a5f7fec1`.
Extraction provenance records the archive, original tool call, ordinal,
timestamp, embedded integrity and extracted-file hash.

| Original stage | Recovered evidence and verification | Scope of the observation |
| --- | --- | --- |
| `post-secret-provisioning` | Complete archived payload; production integrity/binding validation passed | Historical post-secret foundation readiness |
| `migration-execution` | Complete archived payload; production integrity/binding validation passed | One successful execution at revision `20260726_0028` |
| `readiness-validation` | Complete archived payload; production integrity/binding validation passed | Historical API/worker revision and runtime readiness |
| `live-validation` | Complete archived payload; production integrity/binding validation passed | Private DNS/TLS, API/worker readiness, telemetry readiness and armed cleanup |
| `soak` | Complete archived payload; production integrity/binding validation passed | 91 samples over 5,400 uninterrupted seconds; historical health/stability scope |
| `zero-residue-verification` | Complete archived payload; production integrity/binding validation passed | Every recorded residue count zero |
| `milestone-completion` | Complete archived payload; production integrity/binding validation passed | `MILESTONE_7_7_COMPLETE`, with Milestone 7.8/provisioning false at that boundary |
| `successful-closeout` | Individual original payload remains unlocated | Historical acceptance remains supported by the original nine-stage validator transcript |
| `cleanup` | Individual original payload remains unlocated | Historical acceptance remains supported by the original nine-stage validator transcript and recovered zero-residue/completion payloads |

These are **recovered original JSON payloads from archived read output**, not
new managed observations. The extracted files have new local file hashes;
their byte-for-byte identity with the missing original files is not asserted.
Embedded payload integrity and original source/ledger bindings were verified.
The seven recovered payloads do not constitute a freshly validated complete
nine-stage chain because two intermediate payloads are absent.

The archive also retains the original production-validator result:
`retained_terminal_chain=PASS stages=9 samples=91 duration_seconds=5400 residue_zero=true marker=MILESTONE_7_7_COMPLETE`.
That is a recovered **historical execution transcript**, not a fresh nine-stage
validation. It supports the existing completion recorded in the
[7.8 entry handoff](MILESTONE_7_8_ARCHITECTURE_SCOPE_AUDIT_HANDOFF.md), lines
29–35 at the reviewed checkpoint.

The soak payload and its producer contract do not supply application-wide
throughput, latency-percentile, queue-age or saturation measurements. No
additional workload receipt was recovered. This does not invalidate the
completed health soak or justify repeating it.

## Recovery report and bounded search outcome

The [7.6 handoff](MILESTONE_7_6_BACKUP_RESTORE_DISASTER_RECOVERY_HANDOFF.md#portable-backup-signing-and-atomicity-evidence)
records final signed report SHA-256
`976b0b7e611f59c488e76ba04d054ddf8696f3910db22778318bd5439a0997b1`.
The report bytes, signature and individual Stage 3 result 14–24 receipts remain
unlocated. No new signature-verification claim is made. The historical
successful PITR/full restore/portable recovery/failback results and their
recorded measurements remain accepted.

The original handoff states that evidence objects, signing resources and
runtime files were removed during verified cleanup. That explains a possible
retention boundary; it does not prove that no independent archive exists.

| Bounded search location | Search basis | Result |
| --- | --- | --- |
| Repository documents, relevant Git history, `.runtime`, `.tmp`, `evidence`, preflight and validation locations | Recorded report hash, terminal schema/marker, known filenames and owning handoffs | Historical records located; original 7.6 report and individual receipts not found |
| Original workspace `AzureValidationFiles`, `.codex-scan-validation-azure` and `outputs` | Named original workspace directories | No requested recovery/terminal evidence; outputs contained demo artifacts |
| Original `work/mobius-local-recovery` | Recovery directory retained by the 7.6 handoff | Eight earlier PostgreSQL patch/manifest files; no signed 7.6 report |
| Original `work/mobius-live` | Known local runtime directory | API/web logs, not the requested managed report |
| Exact final and predecessor temporary 7.7 campaign directories; original `C:/Temp` scratch location | Paths recovered from archived execution commands | Final receipts directory empty; no missing final stage or 7.6 report recovered |
| Targeted Codex session archives for the original project and execution dates | Known session identifiers, parent links, exact report hash, stage marker and historical result counts | Seven original terminal payloads, original nine-stage validator transcript and five skipped-shard command/result transcripts recovered |
| Archived-session inventory and connected read of the exact original parent chat | Parent identifier recovered from session metadata | No additional artifact; connected chat returned metadata but no turns |
| GitHub Actions artifact inventory for `hawkelement333-glitch/opencanvas-ai` | One read-only repository API page, `per_page=100&page=1`; matching names would include 7.6/7.7, recovery, terminal, SBOM and provenance | Successful response reported `total_count=0` and no artifacts. Nothing was downloaded. This does not establish whether earlier artifacts expired or were deleted. |

No broad home-directory search, Azure retrieval or paid storage access was
performed. The connected GitHub tool exposes per-run artifacts but not a
repository-wide artifact inventory, so the bounded inventory used the existing
authenticated `gh api` read path. It found no currently listed Actions artifact
for this repository; other cloud archives are not claimed absent.

## Four affected current-release recovery assertions

The governing existing criteria are the
[7.8 recovery requirement](MILESTONE_7_IMPLEMENTATION_PLAN.md#required-final-scenarios)
and [recovery runbook](PRODUCTION_RECOVERY_RUNBOOK.md#object-queue-index-and-evidence-reconciliation),
lines 105–124, 139–177 and 218–224 at the reviewed checkpoint. The current
changes narrow the compatibility question as follows; they do not reopen
every recovery exercise.

| Relevant change | Existing evidence credited | Exact recovery assertion still needing a current-release mapping or observation |
| --- | --- | --- |
| [Migration 0029](../apps/api/alembic/versions/20260726_0029_legacy_creation_idempotency.py): durable legacy creation identities and append-only trigger | Local idempotency/rollback checks; accepted PG current-head and privilege checks; new local coverage in the parent report | After restore or compatible rollback, original creation request/result bindings and append-only protection survive; duplicate canvas/node/edge requests do not repeat state/evidence. An older 0028 backup needs an explicit compatible migration path before effects unlock. |
| [Database roles/ownership](../apps/api/opencanvas_api/db/role_privileges.py), principal manifest and [identity-backed sessions](../apps/api/opencanvas_api/db/session.py) | Accepted PG role/negative-permission, tenant-isolation, credential and failover results | The restored target has the expected ownership, grants, identity sessions and scope restrictions. Original-target bootstrap proof alone does not observe a restored target. |
| [Worker](../apps/api/opencanvas_api/services/jobs.py) now processes private scanner work and exact-version deletion, with bounded database-disconnect recovery | Accepted PG failover/stale-pool/replay and D001 deletion/transaction/absence/retry results | Restore reconstructs nonterminal job/deletion eligibility, fences pre-restore workers/effects and reconciles provider absence/version state without repeating durable effects. |
| [Upload/event identities](../apps/api/opencanvas_api/services/object_ingestion.py) and [scanner provenance payload](../apps/api/opencanvas_api/services/domain_events.py) | D001 exact-version scanner/promotion/recovery/replay results | Restored upload/event/outbox/activity and index manifests preserve session, exact object/version/checksum and native-scan bindings, with consistent publication and no stale result reuse. |

`durable_jobs.py` and `scripts/worker.py` are unchanged from the 7.6 completion
checkpoint. The domain-event delivery mechanism is unchanged, but
`domain_events.py` gained **eight scanner-provenance payload allowlist fields**;
describing that entire file as unchanged would be inaccurate. The absence of
the original per-result recovery receipts prevents assigning individual
numbers 14–24 to current assertions solely from the handoff summary.

## Historical skipped-test identities

Five original August 18 shard transcripts were recovered: **137 passed / 1
skipped; 24 / 1; 63 / 1; 317 / 1; and 152 / 10**. The exact commands identify
the selected modules. Their test definitions at
`7a99d297f3c82722486e5f4b33db12532e1cc4a9` identify the 14 PostgreSQL-gated
tests below. The counts agree. This is a command-plus-historical-source
identity mapping, not a claim that the old compact console output printed
every skipped node ID.

All paths in this table are relative to `apps/api/tests/`. “Same” means the
entire original node ID remains the current target. Fresh results, corrections
and failed-attempt history belong to the
[parent local-gap report](MILESTONE_7_8_LOCAL_GAP_COMPLETION.md#local-postgresql-coverage),
not to these historical execution transcripts.

| Original skipped node ID | Current target | Fresh local result record |
| --- | --- | --- |
| `test_object_ingestion_postgres.py::test_postgresql_0027_cycle_and_append_only_catalog` | Same | Parent local-gap report |
| `test_indexer_postgres.py::test_postgresql_0026_cycle_and_append_only_trigger_catalog` | Same | Parent local-gap report |
| `test_durable_jobs_postgres.py::test_postgresql_skip_locked_claims_once_and_evidence_is_append_only` | Same | Parent local-gap report |
| `test_agent_postgres.py::test_postgres_enforces_all_controlled_agent_append_only_boundaries` | Same | Parent local-gap report |
| `test_migration_0005_postgres.py::test_postgresql_migration_0005_preserves_seeded_workspace_dependencies` | Same | Parent local-gap report |
| `test_migration_0021_postgres.py::test_postgresql_migration_0021_current_role_constraint_and_cycle` | Same | Parent local-gap report |
| `test_migration_0023_0024_postgres.py::test_postgresql_0023_preserves_exact_predecessor_registries_and_cycles` | Same | Parent local-gap report |
| `test_migration_0023_0024_postgres.py::test_postgresql_0023_backfills_exact_uuid_and_null_matrix_and_cycles` | Same | Parent local-gap report |
| `test_migration_0023_0024_postgres.py::test_postgresql_0024_consumes_0023_registries_without_widening_and_cycles` | Same | Parent local-gap report |
| `test_migration_0023_0024_postgres.py::test_postgresql_all_13_protected_tables_bind_existing_function_and_rollback_mutations` | Same | Parent local-gap report |
| `test_migration_0023_0024_postgres.py::test_postgresql_trigger_identity_and_mutations_survive_same_database_restart` | Same | Parent local-gap report |
| `test_migration_0023_0024_postgres.py::test_postgresql_clean_chain_reaches_0025_and_cycles_final_revision` | `test_migration_0023_0024_postgres.py::test_postgresql_clean_chain_reaches_0029_and_cycles_final_revision` | Parent local-gap report; original historical name preserved here |
| `test_migration_runner_postgres.py::test_postgresql_guard_excludes_competitor_and_releases_after_success` | Same | Parent local-gap report |
| `test_migration_runner_postgres.py::test_postgresql_guard_rolls_back_before_unlock_and_preserves_failure` | Same | Parent local-gap report |

The later accepted managed proofs overlap some mechanisms but do not replace
these exact migration-cycle, seeded-data, trigger-catalog, rollback and restart
assertions. No later exact native JUnit match was located before the newly
authorized local work. Running these uncovered local checks does not reopen
managed PostgreSQL acceptance.

## Private artifact references

Private originals, extracted payloads and archive provenance remain outside
Git under `.runtime/milestone_7_8/local-gap-20261116/historical/`:

- `findings.json`: SHA-256
  `52a55db53fb8e16639ec42338c2ae77e37b472c4ffcb96a737a55f5d34c1663c`;
- `historical-skips.json`: SHA-256
  `f209efb579c5f4f1290d32144eebd66d428f8a60fbadf925a595837ecf85e02d`;
- `historical-skip-results.json` and `skip-shard-commands.json`: original
  execution transcript excerpts and command provenance;
- `terminal/*.evidence.json`, `terminal-extraction-provenance.json` and
  `terminal-validation.json`; validation record SHA-256
  `477ccba7134532ddb2314cf6b8fce5003597637bba8633cbbb587a5af435eb71`;
- `archived-call-281.json`: original nine-stage validator transcript;
- `file-manifest.json`: extracted artifact sizes and hashes.
- `github-actions-artifacts-page1.json`: read-only repository artifact-inventory
  response, SHA-256
  `244563f989470892c537c9a4622920af0d228ee4528f7d00c64a06d6cd95856c`.

Fresh local PostgreSQL results are separately retained under
`.runtime/milestone_7_8/local-gap-20261116/local-tests/` in
`historical-uncovered.xml`, `affected-correction.xml`, `clean-chain-final.xml`,
`restart.xml` and `fixture-unit-final.xml`. The parent report verifies 14 unique
accepted assertions in `fourteen-assertion-reconciliation.json`, SHA-256
`d8c6cb006e185bfa4e9f13331172e8820e47488252e445f283daa95c3a4a7581`.
Their final accounting is owned by that report. Historical failed attempts
remain intact; billing remains unsettled.
