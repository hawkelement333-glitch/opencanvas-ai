# Milestone 7.8 local evidence and validation work

> **Subsequent pilot preparation - 2026-11-16:** the user selected read-only
> controlled drafts and pilot-only 900-second/20-second scanning. Focused secure
> UI/worker/native-PostgreSQL integration and the corrected API artifact now pass
> locally. See [current pilot preparation](MILESTONE_7_8_PILOT_PREPARATION.md) and
> the [bounded execution package](MILESTONE_7_8_PILOT_MANAGED_VALIDATION_PACKAGE.md).
> Earlier findings below remain dated history; full 7.8 remains incomplete.

Date: 2026-11-16. Starting checkpoint:
`8236da2f8bb612732da3abf7f5297e02ec1cbd9c`, branch
`milestone-7-8-production-readiness-audit-local`.

This continues the specific work list in the
[remaining-evidence reconciliation](MILESTONE_7_8_REMAINING_EVIDENCE_RECONCILIATION.md).
PostgreSQL, M78-D-001 and M78-D-002 remain accepted with verified cleanup.
Milestone 7.8 is not declared complete. No Azure operation, paid provider call,
image build/push, deployment or destructive recovery exercise was performed.
The local database restart below used an isolated synthetic test fixture only.
Billing remains unsettled; the prior $350.89 cumulative approved ceiling is
neither settled spending nor an allowance for further execution.

## Historical evidence and recovery mapping

The [historical retrieval record](MILESTONE_7_8_HISTORICAL_EVIDENCE_RECOVERY.md)
records bounded searches, recovered payloads, hashes and exact skipped test
identities. Seven archived original 7.7 payloads now pass their original
integrity/source/ledger validation. The original nine-stage validation transcript
is also retained. The two individual closeout/cleanup payloads and the signed
7.6 report/results remain unlocated; historical completion is preserved.

The precise current recovery gaps concern restored 0029 request identities,
restored roles/ownership/identity sessions, nonterminal worker/deletion fencing,
and joint object/version/scanner/event/outbox/activity/index consistency. These
are affected compatibility assertions, not permission to repeat PG/object/Redis
acceptance or all historical recovery exercises.

## Local PostgreSQL coverage

All **14 historically skipped PostgreSQL test identities now have accepted local
results**, using PostgreSQL 17 and cached pgvector 0.8.7 in disposable databases.
The exact identity-to-receipt mapping is private at
`.runtime/milestone_7_8/local-gap-20261116/local-tests/fourteen-assertion-reconciliation.json`,
SHA-256 `d8c6cb006e185bfa4e9f13331172e8820e47488252e445f283daa95c3a4a7581`.
It maps the recovered original identities to successful final results, including
the explicitly renamed current-head test. Failed attempts remain retained.

The first 13-test run reported 12 passes, one assertion failure and one teardown
error. The assertion expected historical head 0026 instead of authorized 0029;
the teardown query admitted a role-less autovacuum backend through a left join.
Only the affected cases were resumed after correction:

- Cleanup now targets known non-superuser client backends in the exact disposable
  child database. Background/unknown-role/superuser/unrelated/self sessions are
  excluded. Twenty fixture-safety unit checks passed.
- The clean-chain test pins authorized head 0029 and its exact event registry,
  preserving the catalog and downgrade-to-0024/upgrade-to-head assertions. The
  prepared fixture explicitly sets `OPENCANVAS_POSTGRES_TEST_VECTOR_VERSION=0.8.7`;
  the historical default is retained and equality remains exact.
- The existing restart test no longer restarts a global WSL service. Explicit
  opt-in selects a locally inspected, labeled, loopback-bound, tmpfs-backed
  disposable container with a persistent supervisor. `pg_ctl restart` preserves
  the same database; trigger identities and post-restart mutation checks passed.
  No managed failover or restore was repeated.

Accepted receipts under `local-tests/`:

- `historical-uncovered.xml` preserves the first run, including its failures.
- `affected-correction.xml` closes the protected-table test and cleanup.
- `clean-chain-final.xml` closes the current migration cycle.
- `restart.xml` closes the fourteenth scenario; SHA-256
  `b7aca7c9325d475e5418de15f819b7fe4ac737397e645b533c458c9f2c804943`.
- `fixture-unit-final.xml` records 20 safety checks; SHA-256
  `f4941b07a8baf1a4f3d21446e12342ebe91b3bffdbd6f8469dc62f2acae7fd91`.

## Dependency applicability and retained image metadata

The [dependency report](MILESTONE_7_8_DEPENDENCY_ALERT_APPLICABILITY.md) maps all
74 actual GitHub alerts to this branch. Focused fixes leave zero matches to
those affected ranges. A scoped lookup of the 14 named packages at their new
versions returned no advisories. This is not a general vulnerability-free claim.
Twenty-five affected contract tests, TypeScript, focused lint and the corrected
frontend production build passed. The build generated nine pages; no container
image was built. Default-branch alerts are not closed by pushing this branch.

The [provenance record](MILESTONE_7_8_LOCAL_PROVENANCE_RECONCILIATION.md) verifies
the exact retained API archive's 20 OCI blobs and 14 layer diff IDs. Original
unsigned BuildKit provenance was recovered. A retrospective SPDX inventory was
generated and independently matched to 44 Python distributions and 87 Debian
binaries. It is not original signed provenance. A trusted signing identity and
verification record remain unresolved.

Frontend dependency changes do not alter the retained Python API image. The
separate grounded-draft, retrieval and local-deletion corrections do alter API
build inputs: the historical image and its scan stay accepted for their exact
bytes, but cannot represent a future release containing those corrections.
A future candidate needs a source-bound API image build and affected artifact
verification; that build is outside this task's authority.

## Local browser environment and contract boundary

The browser ran against the actual FastAPI process, PostgreSQL schema 0029 and
a separate database-backed document worker. Authentication and CSRF remained
enabled; each scenario creates a synthetic account/workspace through the real
signup API. There is no browser response interception. AI and embeddings use
the repository's deterministic providers; file storage is a private local
directory. This does not establish live AI quality/credentials, managed scanner
behavior, cloud roles/networking or production hosting readiness.

The old scenarios lacked authentication and used removed toolbar/readiness
labels. The fixture now establishes real session cookies, and selectors reflect
the existing UI. Assertions were not weakened. A Windows 277-character temporary
storage filename caused an initial upload failure; only the isolated fixture's
storage root was shortened. Failed runs are retained privately.

The canvas scenario proved two edited notes and their edge survived reload.
Both original scenarios then encounter a substantive contract conflict:
`assistant-input`/`ask-assistant` and editable AI canvas-node creation belong to
the older interface. The normal authenticated website intentionally renders
`ControlledDraftPanel`, whose result is read-only. This is recorded in the
[Milestone 4 completion contract](MILESTONE_4_COMPLETION.md), line 63, and
`open-canvas-app.tsx` around line 1585. No legacy mode or mocked workspace was
substituted to obtain a pass. The original tests remain failed/incomplete for
their full legacy expectations, not skipped or relabeled accepted.

A separate `core-grounded-workflow.real.spec.ts` **passed** the current
authenticated document/retrieval/controlled-draft journey: real PDF upload and
worker readiness, grounded answer and bound citation, passage/page navigation,
authenticated retrieval, unsupported-question refusal, read-only result,
successful deletion, subsequent document/passage/search denial and absence after
reload. Chromium reported **1 passed, 0 failed/skipped/flaky** in 16.0 seconds
(scenario 8.4 seconds). This separate test does not replace the old editable-node
criterion. Its private `browser/core-accepted.json` SHA-256 is
`0eb415e1c8f824fa8ff8c6fe7caff2ec9eead57687e45358c02d45ece08375a0`.

## Demonstrated API corrections and affected validation

The real browser and focused regressions demonstrated the following failures;
their failed receipts remain retained alongside successful final results:

- A document card has empty node text. Controlled-draft preparation now resolves
  its authorized ready document/version, rather than failing the nonempty-content
  contract. Preparation and immutable execution use the same resolver; replacement
  versions and deletion continue to invalidate captured evidence.
- The provider received a request identifier/default instruction instead of the
  validated user instruction. It now receives the actual persisted instruction.
- Preparation admitted first chunks without the existing query-relevance gate.
  It now reuses configured retrieval, unchanged relevance threshold and top-K.
  Exact selected document/version pairs constrain candidates **before** ranking
  and limits, so an old version cannot displace a selected current version.
- Document-backed NODE content is excluded from provider notes. Document text
  reaches the provider through admitted chunks, preserving private-clean and
  relevance checks; ordinary selected notes remain available. Unsupported
  questions keep the existing fail-closed no-source refusal.
- Legacy local deletion hit `fk_durable_job_request_document_scope` because
  immutable durable intent retains document/version identities. That path now
  preserves tombstones and immutable job history while removing live projections
  and denying reads, retrieval and processing retries. Locked ORM reads refresh
  cached state to reject concurrently deleted documents. The existing secure
  object-storage path and immutable index guard remain unchanged. Legacy file
  unlink before database commit remains an existing atomicity limitation; this
  correction does not claim managed transaction acceptance.

Final affected validation: **27 grounded/retrieval/immutable-context/API checks**,
**4 legacy deletion checks**, and strict mypy across the **5 changed production
files** passed. The two review regressions failed before correction. Independent
focused source review confirmed version filtering precedes limits and document
text cannot bypass admission through notes. No full unchanged suite was rerun.

The changed API build inputs are `services/agents/execution.py`,
`services/agents/grounded_draft.py`, `services/documents/retrieval.py`,
`services/documents/processing.py` and `api/routes/documents.py`, relative to
`apps/api/opencanvas_api/`. The final private receipt binds their exact hashes.
It does not claim that the retained image contains these later fixes.

## Final local receipts and cleanup

All paths here are relative to private
`.runtime/milestone_7_8/local-gap-20261116/` and remain outside Git:

| Receipt | SHA-256 / result |
| --- | --- |
| `final-local-results.json` | `e317f170a28d203b691d63f27404c77e523affbdcb3affb3c56bf2cf2b74da26`; source hashes, native result accounting, retained receipt hashes and all five stash identities. |
| `local-tests/grounded-review-correction.json` | `d043a2b44eb694ea99f47d4c4c3a5acd01c4398551a83f79fae3db6373f1268f`; two reproduced review failures, corrections and final validation. |
| `local-tests/grounded-review-affected.xml` | `9a15ff4334b21bfb420a0e5b490bd7ae104336e8b60132a8f2d37d349c4d5307`; 27 passes. |
| `browser/deletion-final.log` | Four affected passes; hash bound by the final receipt. |
| `browser/frontend-build-final.log` | Next 16.4.5 production build passed; hash bound by the final receipt. The local API URL is not a deployed hosting configuration. |
| `local-cleanup.json` | `abd2bf87cb8a0cf612c620c51250170eb62fd782f1e44033735247cb7dc263c8`; local cleanup verified. |

Both exactly identified disposable database containers were stopped and removed.
Their child test database counts were zero before removal. Owned API/worker
processes and fixture listeners on 3000/8000/55432/55433 are absent. Synthetic
short-path storage was archived privately and its temporary directory removed.
No cloud cleanup was necessary or performed. Original failed attempts and private
receipts remain intact; the five protected stashes remain unchanged.

## Core-feature pilot decision

The target retains authenticated canvas editing, document upload, extraction,
retrieval, citation navigation and grounded AI. None is disabled to claim
readiness. Assume invited authenticated users, a bounded cohort, non-sensitive
synthetic/evaluation documents and operator supervision; no safe user count,
public SLA or production durability guarantee is inferred from local results.

| Remaining decision or observation | Feature/dependency and credited evidence | Exact next step and class |
| --- | --- | --- |
| Editable AI node versus current controlled draft | Real graph persistence and the existing read-only Milestone 4 contract; original legacy browser assertions remain distinct. | **Explicit product/acceptance decision:** confirm the existing read-only controlled-draft journey as the pilot contract, or authorize a compatible persisted/editable-result workflow. Do not remove assertions or bypass controlled-write governance merely to pass old tests. |
| Website scanner timing | D001's 24 accepted assertions and 900-second/20-second proof policy remain closed. Default website decision window is still 300 seconds; historical native delivery exceeded it. | **Configuration decision, then affected validation:** approve or reject pilot-specific `OPENCANVAS_MALWARE_SCAN_TIMEOUT_SECONDS=900` and `OPENCANVAS_SCANNER_RESULT_BRIDGE_RETRY_MAX_SECONDS=20`. Keep upload-capability expiry, late-result rejection, exact object/version binding and quarantine until both sources agree. Validate admission, pending/timeout UI behavior and expiry boundaries for the chosen release; reuse D001 acceptance rather than repeat its campaign. |
| Operational destination and category logs | Local redaction/exporter/alert checks and D001 native scanner ingestion; historical infrastructure metrics. | **Managed observation:** application log/metric/span routing and privacy, dashboards/alert delivery/recovery, outage/backpressure, retention/access/revocation and missing usable infrastructure categories. |
| Worker/external delivery | Local database-worker processing and accepted durability/PG/object component results. | **Managed observation:** exact intended provider polling/wake-up, operational signals and external delivery/acknowledgment where enabled. No new broker is implied. |
| Current restore/rollback compatibility | Historical 7.6 managed recovery and closed PG/object recovery; 14 local PostgreSQL scenarios. | **Affected managed recovery evidence:** the four current restore assertions listed above. Missing historical receipts alone do not justify repeating every exercise. |
| Bounded application workload | Historical health soak and accepted component measurements. | **Evidence mapping / targeted managed observation:** supported workload/data/concurrency limits and safe rejection/recovery for the enabled combined website workload. No tested pilot user ceiling exists here. |
| Live AI/embedding and release artifact/configuration | Deterministic local provider behavior, corrected frontend dependencies/build and current API regressions. | **Release/configuration and provider observation:** bind the future API image to corrected source, verify signed provenance using an approved identity, and validate the selected real AI/embedding provider and full deployed configuration. Local substitutes do not prove those provider contracts. |

D003/D007 and worker operational/delivery observations can share one separately
approved isolated environment with the exact API/worker/exporter/destination
identities, synthetic inputs and a common cleanup ledger. Its logs can also
support the chosen workload observations. No environment is provisioned here,
and a shared environment does not waive each assertion or reopen closed areas.
Any future package must price its actual SKU/region/duration, transfers,
logging/retention and cleanup allowance. Temporary validation cost must be
separate from recurring website compute/database/cache/storage/scanner/AI/
telemetry hosting cost. No new forecast or spending allowance is asserted here.

The core-feature pilot is **conditionally feasible after the named decisions
and evidence steps, and currently blocked from a supported readiness claim**.
Full 7.8 still requires all existing outstanding criteria, even if a pilot has
a narrower expressly approved operational commitment. No deployment or next
area starts automatically from this report.
