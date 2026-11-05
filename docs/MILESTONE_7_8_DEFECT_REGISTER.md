# Milestone 7.8 Defect Register

Date: 2026-08-27

Status: active; architecture and checkpoint-scope findings are corrected;
managed PostgreSQL defects through M78-PG-013 and the first object-storage
finding are locally remediated. The exact prior Automation account remains
provider-retained nonzero residue. The disposable-controller architecture is
superseded locally by one stable reusable controller outside campaign deletion
scope; its state is `architecture-corrected-live-execution-not-authorized`.
All five managed database evidence gaps remain open, and Milestone 7.8 is not
complete.

This register records defects proved by the Milestone 7.8 audit and, in a
separate section, the evidence gaps the audit contract requires it to preserve.
A historical deferral, known limitation, warning, or missing validation is not
silently promoted to a defect. Remediation is mandatory only where the
governing repository contract says so; otherwise validation is required first
and remediation remains conditional on proof.

## Architecture and checkpoint-scope findings

| Identifier | Source                                                                                                              | Description                                                                                                                                   | Severity    | Affected surface                       | Classification                      | Mandatory in 7.8 | Disposition                         |
| ---------- | ------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- | ----------- | -------------------------------------- | ----------------------------------- | ---------------- | ----------------------------------- |
| M78-AS-001 | Current status blocks in the implementation plan, architecture, progress, and roadmap; retained 7.7 terminal chain  | Current governance documents still presented 7.7 as incomplete and 7.8 as unstarted after the terminal chain proved `MILESTONE_7_7_COMPLETE`. | Not defined | Architecture and checkpoint governance | Audit finding; documentation debt   | Yes              | Corrected by this audit surface     |
| M78-AS-002 | Implementation-plan execution rule and final-validation no-upstream requirement; inherited 7.7 branch configuration | The inherited 7.7 branch tracked a remote branch, so it could not satisfy the required no-upstream 7.8 checkpoint evidence boundary.          | Not defined | Local Git checkpoint boundary          | Audit finding; operational/Git debt | Yes              | Corrected with a fresh local branch |

No finding in this table claims that Milestone 7.7 was materially false or
unsafe. Both findings concern the safe entry boundary for new 7.8 work.

## Managed PostgreSQL and tenant-isolation findings

The second ordered audit surface inspected the declared architecture, Bicep
topology, runtime configuration, connection construction, SQLAlchemy engine
creation, database runtime gates, PostgreSQL bootstrap, migration runner,
Alembic environment and chain, recovery records, all 181 API operations, all
151 ORM tables, central authorization and sharing services, durable workers,
indexing, ingestion, graph retrieval, workflows, and the affected local test
suites. A source defect is listed only when current code contradicts an
authoritative repository requirement or permits a concrete unsafe path.

| Identifier | Exact requirement and source evidence                                                                                                                                                                                                                                                                                                                                                                                                                                                                             | Affected production path                                                                                                                                                     | Severity | Classification and disposition                                                                                                                                                                                                                                                                                                                                                                                                          | Changed files and validation                                                                                                                                                                                                                                                                                                                                                                           | Residual risk                                                                                                                                                                                                                                                                                                                  |
| ---------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| M78-PG-001 | Architecture section 9.2 requires direct non-pooled migration/maintenance connections; `alembic/env.py` used `Database.from_settings`, which constructed `QueuePool` for every PostgreSQL role. This contradicted the Milestone 7.1 `NullPool` record.                                                                                                                                                                                                                                                            | Alembic migration job and non-application role connections                                                                                                                   | Medium   | Proved defect; corrected so only API and worker roles pool and migration, backup, observability, and emergency roles use `NullPool`.                                                                                                                                                                                                                                                                                                    | `apps/api/opencanvas_api/db/session.py`; `apps/api/tests/test_database_runtime.py`. Direct-pool regression passes; affected database/migration group passes 138 tests.                                                                                                                                                                                                                                 | No known local residual for pool selection; managed execution under the corrected code remains part of M78-PG-E03.                                                                                                                                                                                                             |
| M78-PG-002 | The implementation plan requires API/worker DML only on required tables. The original Bicep bootstrap and `scripts/bootstrap_postgres.py` gave both principals identical CRUD on all tables, sequence write, all-function execution, and matching default privileges.                                                                                                                                                                                                                                             | Every API and worker SQL path, including auth, collaboration, ingestion, indexing, jobs, and workflows                                                                       | High     | Proved defect; locally resolved. API and worker now consume distinct literal per-operation matrices; neither receives sequence or function privileges; current/default blanket grants and unsafe `PUBLIC` execution are revoked.                                                                                                                                                                                                        | `db/role_privileges.py`, split bootstrap/migration scripts, compute/identity/registry Bicep, and focused contract tests. Local emitted-grant and prohibited-grant assertions pass; managed catalog/negative execution remains M78-PG-E02.                                                                                                                                                              | Effective deployed ownership, inheritance, and positive/negative managed-identity execution remain unproved until the managed campaign.                                                                                                                                                                                        |
| M78-PG-003 | Architecture sections 5 and 9.2-9.3 and `DEPLOYMENT.md` require a distinct least-privilege migration user. The original Bicep authenticated the job as the configured Entra administrator and combined principal provisioning, grants, and Alembic.                                                                                                                                                                                                                                                               | One-shot migration/bootstrap job and all schema/extension ownership                                                                                                          | High     | Proved defect; locally resolved. `id-mobius77-db-admin` is confined to a provisioning-only job; `id-mobius77-db-migration` alone runs the guarded migration/grant job and owns the application schema objects.                                                                                                                                                                                                                          | Identity, registry, compute, owner-bootstrap, main Bicep; `bootstrap_postgres.py`; `migrate_and_grant.py`; config and contract tests. NullPool, role exclusion, ordering, sole-head, and local migration-cycle checks pass.                                                                                                                                                                            | Actual Entra principal creation, ownership transfer, job ordering, and negative role behavior require the bounded managed campaign.                                                                                                                                                                                            |
| M78-PG-004 | Architecture section 9.4 requires every mutation to resolve ambiguous commits by durable idempotency key/digest. Canvas, node, duplicate-node, and edge creation originally accepted neither and created server-random UUIDs.                                                                                                                                                                                                                                                                                     | Legacy create operations during disconnect, restart, DNS change, or zone failover                                                                                            | High     | Proved defect; locally resolved with required keys and one expansion migration. Database uniqueness serializes actor/operation/key claims; scope/digest/result identity and the domain object commit atomically; replay reauthorizes and returns the original identity; conflicts fail closed.                                                                                                                                          | `20260726_0029`, ORM/service/schema/routes, first-party retrying client, and API/web tests. First, replay, conflict, concurrency, rollback, client replacement, forged workspace, and all four path cases pass locally.                                                                                                                                                                                | PostgreSQL concurrency/failover behavior remains to be executed through managed identities; SQLite migration and API proofs do not substitute for that campaign.                                                                                                                                                               |
| M78-PG-005 | The independently bounded 7.8 campaign contract forbids retained 7.7 identifiers. The shipped principal-bootstrap and migration/grant entry points accepted only `id-mobius77-db-admin`, `id-mobius77-db-migration`, `id-mobius77-api`, and `id-mobius77-worker`; every distinct 7.8 identity name failed closed before principal creation or grant reconciliation.                                                                                                                                               | Managed principal bootstrap, migration/grant reconciliation, and every 7.8 evidence job that authenticates as a campaign-specific database identity                          | High     | Proved defect; locally resolved. Both operational entry points now consume one strict campaign/generation principal manifest whose closed semantic slots bind distinct names and object IDs for bootstrap, migration, API, worker, evidence, and cleanup. The active identity must match its semantic name and controlled object-ID binding. Retained 7.7 labels have no special case.                                                  | `db/principal_manifest.py`; bootstrap, migration/grant, and credential-recovery scripts; campaign Bicep manifest emission; focused alternative-generation, missing/duplicate/swapped/malformed/stale/unknown/current-binding tests. No Azure or live database was used.                                                                                                                                | Effective Entra-to-PostgreSQL object mapping remains part of M78-PG-E02. The independent campaign is repository-ready but has not created a principal or produced managed proof.                                                                                                                                               |
| M78-PG-006 | The independent campaign must be executable from its authorized Windows operator host. At clean starting HEAD `a80643233d81d60f4b47b022cbfc66842eaf5cbd`, every planned Azure command flowed to `SubprocessRunner`, which passed symbolic `az` directly to `subprocess.run(..., shell=False)`. The installed CLI exposed trusted `az.cmd`/batch launchers but no native `az.exe`, so preflight failed with Windows error 2 before its ledger or any Azure mutation.                                               | All 44 planned operator Azure commands across 14 phases, plus generated job polling, failure cleanup, direct cleanup, and documented Bicep/image/config readback commands    | High     | Proved defect; locally resolved. One resolver now deterministically prefers native `az.exe`, otherwise binds canonical installed `az.cmd`/`az.bat` to the absolute Windows system `cmd.exe`. Batch arguments use one-pass temporary environment indirection, are erased before the CLI child starts, and run with `shell=False`; repository/current-directory/`.runtime`/arbitrary launchers and unsafe control characters fail closed. | `infra/milestone_7_8/azure_cli.py`, `campaign.py`, the operator runbook/README, and `test_milestone_7_8_azure_cli_launcher.py`. Real temporary `.cmd`/`.bat`, exact argv, injection sentinel, error/timeout, resolution, preflight, static call-site, and local non-authenticated version-smoke checks pass.                                                                                           | The correction proves only the local process boundary. It does not validate account authority, Azure control-plane behavior, managed PostgreSQL, cleanup, cost, or any managed evidence gap; a fresh source-bound campaign still requires separate authorization.                                                              |
| M78-PG-007 | The fresh corrected-launcher campaign bound the cleanup Automation account to the unchecked `westus` default. Preparation serialized that value into configuration and Bicep parameters, while `capacity-check` proved only provider registration and never proved Automation regional support, location policy, active or soft-deleted account occupancy, or regional capacity before `scope-create`. Azure then rejected the one cleanup deployment because the region's subscription capacity was unavailable. | Preparation, pre-mutation capacity proof, cleanup-controller deployment/readback, restart ledger, failure cleanup, and all future source-bound managed PostgreSQL campaigns  | High     | Proved defect; locally resolved. One closed candidate order is evaluated through provider support, enforced location policy, active-account occupancy, and soft-deleted-account occupancy before a bundle exists and again before scope mutation. The selected region and four evidence hashes are immutable through configuration, runtime, ledger, parameter, Bicep, readback, and receipt surfaces.                                  | `automation_region.py`; preparation/campaign/operator lifecycle; three schemas plus one new closed receipt schema; cleanup and target Bicep; focused regional/campaign/launcher contracts; current runbook/README/handoffs. Synthetic selection, substitution, policy, occupancy, no-hop, exact-cleanup, and leakage proofs pass; sanitized live discovery selected `southcentralus` without mutation. | Azure exposes no reliable exact regional Automation quota endpoint in this repository contract. Zero discoverable occupancy is therefore necessary but not represented as provider reservation; a separately authorized fresh campaign must still stop on the first deployment failure and may not hop regions after mutation. |
| M78-PG-008 | The corrected regional-capacity selector marked `southcentralus` viable after proving provider support, policy allowance, and zero active/soft-deleted occupancy. The one authorized cleanup deployment then returned `BadRequest`: Azure reported that Free Trial and Student subscriptions cannot create Automation accounts in that location and supplied a narrower allowed-region set. The selector never proved subscription-offer admission before mutation.                                               | Campaign preparation, repeated `capacity-check`, cleanup-controller admission, and every future source-bound managed PostgreSQL campaign on an offer-restricted subscription | High     | Proved defect; locally resolved. Subscription-offer eligibility is now a fourth independent mandatory gate. Free Trial/Student and unclassified public offers receive the reviewed restrictive baseline `eastus,eastus2,northeurope,southeastasia,westus`; `southcentralus` and `westus2` cannot be re-enabled by provider or policy evidence. The unresolved `JapanWest2`/`japanwest` spelling is excluded rather than guessed.        | `automation_region.py`; campaign, preparation, operator, lifecycle, four schemas, cleanup/target Bicep, focused regional/campaign/launcher tests, current runbook/README, and the [offer-region remediation handoff](MILESTONE_7_8_AUTOMATION_OFFER_REGION_ELIGIBILITY_REMEDIATION_HANDOFF.md). Synthetic adversarial tests and sanitized live read-only discovery pass without mutation.              | Offer admission remains locally closed. The later stale candidate-order contradiction is the distinct M78-PG-009 defect and is also corrected. All five managed database evidence gaps remain open.                                                                                                                            |
| M78-PG-009 | The M78-PG-008 contract declared `eastus`, `eastus2`, `northeurope`, `southeastasia`, and `westus` offer-safe, but the operational order still evaluated only `eastus2`, `southcentralus`, `westus2`, and `westus`. Sanitized complete provider, policy, active, and soft-deleted reads proved `southeastasia` selectable and excluded solely by that stale order.                                                                                                                                                | Preparation, repeated `capacity-check`, configuration/runtime/ledger bindings, Bicep deployment/readback, and every later campaign's pre-mutation Automation selection       | High     | Proved defect; locally resolved. The closed deterministic order now includes all seven reviewed regions and still prohibits caller overrides. Every offer-safe region participates; historical candidates remain to receive explicit offer-ineligible dispositions. The exact ordered set is independently bound in addition to the full selection hash.                                                                                | `automation_region.py`; campaign, preparation, operator, lifecycle; campaign/runtime/ledger/selection schemas; cleanup/target Bicep; focused candidate, capacity, launcher, campaign, runtime, and infrastructure tests; current runbook/README; and the [candidate reconciliation handoff](MILESTONE_7_8_AUTOMATION_OFFER_SAFE_CANDIDATE_RECONCILIATION_HANDOFF.md).                                  | Sanitized current state selects `southeastasia`, but this read-only proof is not a reservation and authorizes no deployment. Azure state can drift, so preparation and `capacity-check` must repeat the complete proof. All five managed database evidence gaps remain open.                                                   |
| M78-PG-010 | The initial cleanup Bicep declared the one-time schedule and job-schedule binding in the same deployment as a draft runbook. ARM resource dependency proved creation, not publication. The fresh campaign consequently attempted binding before a published runbook version existed.                                                                                                                                                                                                                              | Cleanup deployment, runbook publication, schedule creation, binding, arming ledger, and interruption/restart behavior                                                        | High     | Proved defect; locally resolved. Initial deployment now emits zero schedules and zero bindings. The imperative arming executor validates deployment, identity, exact two-scope RBAC, publication state/content, schedule, and one deterministic binding in strict order; no partial proof advances `cleanup-armed`.                                                                                                                     | `cleanup-controller.bicep`, `cleanup.bicep`, `prepare.py`, `operator.py`, campaign/runtime/ledger/receipt schemas, cleanup script, runbook/README, and focused ordering/failure/restart tests.                                                                                                                                                                                                         | The ordering defect is closed locally. No cleanup deployment was run. The Automation controller remains non-armable for the separate M78-PG-011 provider-retention reason.                                                                                                                                                     |
| M78-PG-011 | The 15-counter residue model treated cleanup-resource-group deletion as Automation-account absence and omitted the provider's soft-deleted account inventory. Complete readback proved the exact campaign-created account remains soft deleted, contradicting the prior zero-residue statement.                                                                                                                                                                                                                   | Cleanup runbook/direct fallback, active/deleted inventories, ledger disposition, receipt/finalization, runtime preservation, and campaign readiness                          | High     | Proved defect; repository truth is locally resolved. Soft-deleted accounts are a distinct 16th counter; both inventories must paginate completely; exact attribution is hash-bound; unrelated deleted accounts are preserved; provider retention is a distinct nonterminal disposition; finalization requires proven zero. Current preparation is marked `blocked-provider-retention`.                                                  | `campaign.py`, `operator.py`, `prepare.py`, schemas, cleanup script, tests, current runbook/README, sanitized receipt, support draft, and the [critical cleanup handoff](MILESTONE_7_8_CRITICAL_CLEANUP_RETENTION_REMEDIATION_HANDOFF.md).                                                                                                                                                             | The exact account remains provider retained. Microsoft documents 30-day retention and exposes list/read but no self-service permanent-delete operation. Actual cleanup is nonzero, actual cost is unavailable after one HTTP 429, and no new campaign is armable or authorized.                                                |
| M78-PG-013 | The GET-only retention verifier could eventually prove the prior account absent, but preparation, stable-controller bootstrap/adoption, runtime, campaign parameters, cleanup authority, both execution authorizations, ledger, and terminal receipt did not require or bind that result. Elapsed time or an unrelated local artifact could therefore reach cleanup admission without the exact M78-PG-012 proof. | Retention admission, controller selection/configuration/bootstrap, campaign preparation/runtime, cleanup deployment/arming, authorization, replay/recovery, ledger, and receipt | High     | Proved defect; locally resolved. A closed sanitized absence artifact now requires the exact deletion/boundary, subscription/campaign/generation/location relationships, zero target candidates, four exact unrelated hashes, complete pagination, and zero mutations. Its domain-separated hash is propagated through every executable cleanup-admission surface. Synthetic fixtures are allowed only for local preparation tests and are rejected at live controller and operator entry. | `retention.py`; preparation, region selection, controller, campaign, operator, cleanup authority and runbook; Bicep; eight schemas; focused rejection/replay tests; current README, runbook, progress, and handoffs. All work is repository-local and produces no passing live artifact. | Managed-provider absence remains unavailable until a separately authorized post-boundary GET-only run succeeds. That success still does not authorize controller bootstrap, campaign execution, or any Azure mutation. |
| M78-TI-001 | The implementation plan requires server-derived scope and stale-authority denial. Retrieval replay/read/bundle paths and workflow creator-owned read/mutation helpers trusted durable creator/scope columns without checking current workspace/member authority.                                                                                                                                                                                                                                                  | Graph retrieval replay/readback, evidence bundles, workflow execution readback, and definition/version mutation                                                              | High     | Proved defect; corrected with current owner/workspace checks and centralized `workflow.view`/`workflow.edit` authorization.                                                                                                                                                                                                                                                                                                             | Graph/workflow services and their two test files. Three exact new regression nodes pass; the affected graph/workflow group is included in 108 passing tests.                                                                                                                                                                                                                                           | Local stale-workspace paths are closed; managed pool/revocation/failover isolation remains M78-TI-E01.                                                                                                                                                                                                                         |

All proved repository defects now have coherent local corrections. The exact
provider-retained cleanup residue and the managed-evidence gaps prevent this
audit surface and Milestone 7.8 from satisfying their completion rules.

The M78-PG-010 and M78-PG-011 table rows preserve the disposition proved at
their original correction boundary. On 2026-08-25 the structurally disposable
controller was replaced locally by the single architecture recorded in the
[cleanup-controller architecture correction handoff](MILESTONE_7_8_CLEANUP_CONTROLLER_ARCHITECTURE_CORRECTION_HANDOFF.md).
The stable controller is separately bootstrapped and published outside target
scope; new campaigns can only adopt it, grant exact target-scoped temporary
authority, create/adopt one schedule and binding, delete only the target, and
prove schedule/binding revocation. This correction used no Azure operation and
does not prove a controller live or authorize a campaign.

### M78-PG-006 local remediation disposition

The smallest complete local correction is one process boundary, not a
machine-specific path or copied wrapper. `azure_cli.py` canonicalizes an
existing launcher outside the repository, working directory, `.runtime`, and
Git-controlled paths. Windows discovery checks `az.exe`, then `az.cmd`, then
`az.bat`; POSIX discovery checks native `az`. A batch launcher is invoked only
through the canonical `GetSystemDirectoryW` result plus `cmd.exe`, using
`/d /s /v:off /c` and `shell=False`. Each nonempty argument is bound to a
collision-resistant process-only variable, expanded once, and unset before
the batch child begins. This preserves empty strings, spaces, quotes,
backslashes, Unicode, JSON, and `&|<>^%()!` without treating them as commands.

The call-site inventory found 44 planned Azure CLI commands across 14 operator
phases; all execute through `SubprocessRunner`, as do generated job polling,
failure cleanup, and direct cleanup commands. No other Python file in
`infra/milestone_7_8` directly executes a literal `az`. The current README and
operator runbook now route their Bicep, image, manifest, and server-readback
commands through the same module's `invoke` operation. The retained blocked
campaign generation remains non-resumable because its source binding predates
this correction.

### M78-PG-007 local remediation disposition

The smallest complete correction preserves the independent Automation cleanup
architecture and moves regional capacity proof ahead of every mutation. One
repository-owned candidate order -- `eastus2`, `southcentralus`, `westus2`,
then `westus` -- is reviewed, closed, and case-insensitive after Azure-location
normalization. Preparation uses the centralized Azure CLI boundary to read
the Automation provider's supported locations, active Automation-account
locations, discoverable soft-deleted account locations, and applicable
location-policy assignments/definitions. A candidate is viable only when its
normalized location is known and supported, policy evaluation explicitly
allows it, and both occupancy counts are zero. Unsupported, malformed,
duplicate, policy-disallowed, occupied, capacity-unproved, or incomplete
discovery stops before a generation directory or ledger is created; there is
no hard-coded fallback.

The selected location, its domain-separated receipt hash, and separate hashes
of provider locations, active occupancy, soft-deleted occupancy, and evaluated
policy evidence are immutable fields in the campaign configuration, private
runtime, restart ledger, cleanup and target parameter bundles, redacted command
plan, Bicep deployment outputs, cleanup-account readback, and terminal receipt.
The existing `capacity-check` repeats the same read-only discovery and
requires the prepared selection and provenance to remain viable before
`scope-create`. Once any mutation begins, the operator issues only the one
bound cleanup deployment; failure enters the existing exact-two-group cleanup
path and never retries or chooses another region. No unrelated Automation
account is named, modified, restored, reused, or deleted.

The authorized sanitized read-only observation on 2026-08-14 found 47
provider-supported Automation regions, zero active accounts, and four
soft-deleted accounts in `eastus2`, `westus`, `eastus`, and `northeurope`.
The one enforced initiative produced no candidate-denying location policy.
Accordingly `eastus2` and `westus` were classified occupied,
`southcentralus` and `westus2` were viable, and the closed order selected
`southcentralus`. Seven unrelated resources were unchanged; campaign-tagged
resources and `rg-m78-*` groups remained zero. This read produced no campaign
or generation identity and authorized no later mutation.

### M78-PG-008 campaign disposition

The later authorized campaign from clean HEAD
`ba8f2eb42ec25ce8937de27fc4070ab8f15b5ff6` repeated the complete selector
immediately before mutation and reproduced the prepared `southcentralus`
choice with identical immutable evidence. Its single cleanup-controller
deployment then proved that the subscription offer has a separate admission
rule: Azure allows Automation-account creation for Free Trial and Student
subscriptions only in `eastus`, `eastus2`, `westus`, `northeurope`,
`southeastasia`, and `japanwest`. Provider support, Azure Policy, active
occupancy, and soft-deleted occupancy did not expose this restriction.

The selected region was therefore ineligible before mutation despite being
classified viable. The campaign stopped without a retry, region hop, second
generation, image, target topology, database, or managed proof. Direct cleanup
completed at `2026-08-14T14:06:59.775287Z`; operator and independent readbacks
proved all 15 residue counters zero and the unrelated inventory unchanged at
seven resources. The sanitized campaign and generation correlations are
`0da94b3cc81ac68b` and `d3f01044e870c0e8`. The full result is recorded in the
[corrected regional-capacity campaign execution handoff](MILESTONE_7_8_MANAGED_POSTGRESQL_CORRECTED_REGIONAL_CAPACITY_CAMPAIGN_EXECUTION_HANDOFF.md).

M78-PG-008 is not remediated by this evidence-only campaign. The smallest
complete correction must be proved separately and must retain the one-region,
one-generation, no-post-mutation-hop, exact-cleanup contract. Another managed
campaign is not authorized by this record.

That statement is the historical disposition at the failed campaign boundary.
The later local M78-PG-008 correction is recorded in the
[offer-region remediation handoff](MILESTONE_7_8_AUTOMATION_OFFER_REGION_ELIGIBILITY_REMEDIATION_HANDOFF.md).

### M78-PG-009 armability reconciliation disposition

The post-M78-PG-008 read-only report evaluated only the old four-region order,
even though its reviewed offer-safe set also contained `eastus`, `northeurope`,
and `southeastasia`. Complete provider, offer, enforced-policy, active, and
soft-deleted reads proved that `southeastasia` was selectable and omitted only
by the stale operational order. This establishes M78-PG-009 as a local
candidate-set defect rather than an external empty-intersection condition.

The corrected exact order is `eastus2`, `southcentralus`, `westus2`, `westus`,
`eastus`, `northeurope`, `southeastasia`. It preserves explicit dispositions
for the two offer-ineligible historical candidates and makes every reviewed
offer-safe region participate. The ordered set is separately immutable across
configuration, runtime, ledger, ARM parameters, schemas, Bicep, lifecycle
tags, deployment readback, repeated capacity validation, and terminal receipt;
caller override and post-mutation hopping remain absent.

Sanitized current evidence selects `southeastasia`. `eastus2`, `westus`,
`eastus`, and `northeurope` each have one discoverable soft-deleted Automation
account; `southcentralus` and `westus2` remain offer-ineligible. Both inventory
reads were pagination-complete, and all definitions reachable from the one
enforced policy assignment were evaluated. Seven unrelated subscription
resources and zero campaign residue were unchanged. Exact per-region evidence,
hashes, validation, and the no-mutation boundary are in the
[offer-safe candidate reconciliation handoff](MILESTONE_7_8_AUTOMATION_OFFER_SAFE_CANDIDATE_RECONCILIATION_HANDOFF.md).

### M78-PG-010 and M78-PG-011 critical cleanup disposition

The preserved generation with campaign correlation `07e350df451c6bec` and
generation correlation `599df8555c0781d9` proved both defects. The deployment
path created the job-schedule binding while the runbook was still draft. Later,
both generated groups and all active campaign resources were absent, but a
complete one-page deleted-account inventory contained exactly one record whose
generated name, normalized `southeastasia` location, expected account resource
binding hash, and preserved lifecycle evidence all matched the generation.
Four pre-existing unrelated deleted-account identity hashes were unchanged.

Current Microsoft Automation contracts document restoration during retention
and permanent provider removal after 30 days. The current REST surface documents
listing deleted accounts, and live provider metadata exposes only
`Microsoft.Automation/deletedAutomationAccounts/read`; neither documents an
exact permanent-delete operation. No endpoint was guessed and no Azure mutation
occurred. The provider deletion evidence places the expected (not proved)
removal boundary at `2026-09-13T20:09:46Z`. The one prior cost query returned
HTTP 429, so actual cost remains unavailable rather than USD 0.00.

The repository correction makes publication and arming sequential and
restart-safe, expands residue to 16 counters, persists arming/residue evidence
hashes and explicit dispositions, and blocks finalization while the exact
soft-deleted account exists. No locally proved replacement met the immutable
deadline, interruption survival, exact-scope deletion, least-privilege, and
no-retained-artifact requirements. The Automation implementation is therefore
retained with its ordering fixed, but every newly prepared runtime is marked
`blocked-provider-retention` and executable campaign mutation stops before
`scope-create`. The private runtime is preserved. The support-request draft is
not submitted. Its legacy 15-counter `finalized` ledger is retained as
disproved historical evidence, is not silently upgraded, and is not resumable
through the v4 operator. No new campaign is authorized.

Final local validation passed 116 Milestone 7.8 tests, 53 preserved topology
and database-remediation tests, and 94 infrastructure contracts, with no test
failures or skips. Focused Ruff, strict mypy, both changed Bicep builds,
PowerShell/JSON parsing, installed Prettier, five-document structure and 12-link
resolution, the 644-file repository hygiene/private-material guard, the
0028/0029 upgrade/downgrade/re-upgrade cycle, sole-head/0030 absence, and
canonical-input verification all passed. The critical-cleanup handoff records
the exact commands, corrected validation findings, and remaining provider
blocker.

## Pre-expiry continuation findings

### M78-PG-012 — retained-account identity evidence was not replayable

**Severity:** High. **Disposition:** locally resolved; the provider record is
still present and is not reclassified as zero residue.

The original sanitized retention receipt asserted exact hash-bound attribution,
but its target hash and four unrelated-record hashes did not match the
domain-separated SHA-256 values calculated from the documented authoritative
`properties.automationAccountResourceId` fields returned by the completely
paginated deleted-account endpoint. Normal verification therefore could not
prove either continued presence or future absence from that receipt. The raw
identifiers are intentionally not stored in the repository.

One explicit, one-time legacy reconciliation mode required the exact generated
name, verified subscription, `southeastasia`, internally related top-level and
original resource IDs, one target among five records, four unrelated records,
and the authoritative deletion instant. It emitted the corrected hashes into
[`automation-retention-live-reconciliation.json`](../evidence/milestone_7_8/automation-retention-live-reconciliation.json).
The historical receipt remains byte-for-byte unchanged. Normal operation is now
strictly bound to the corrected receipt; the reconciliation override cannot be
used for an absence claim.

Changed files are `infra/milestone_7_8/retention.py`, its 16 focused tests, the
sanitized reconciliation receipt, the current campaign README, and the
pre-expiry continuation handoff. Local tests cover pagination, subscription and
ARM-ID binding, provider key casing, the provider's timezone-naive Central
Daylight timestamp, exact UTC equality, duplicate/drift rejection, safe
`nextLink`, pre-boundary refusal without an Azure call, strict post-boundary
absence, and absence of mutation verbs. A final current-presence execution
proved five records, one exact target, four unchanged unrelated hashes, one
inventory page, two Azure GET operations, and zero Azure mutations.

Residual risk is external: the exact record remains present until provider
retention removes it. Its authoritative deletion time is
`2026-08-15T01:09:46.307Z`; the earliest expected 30-day boundary is
`2026-09-14T01:09:46.307Z`. The subsequent stable-controller and M78-PG-013
corrections supersede the historical disposable-controller conclusion without
claiming that absence or a live controller has been proved.

### M78-PG-013 — retention absence was not an executable admission fact

**Severity:** High. **Disposition:** locally resolved; managed-provider absence
and every Azure execution remain separately unavailable or unauthorized.

The post-boundary verifier had a strict success result, but no controller or
campaign executable required that result. The correction promotes only the
sanitized `retained-account-absent` result into a closed evidence artifact,
requires the exact prior target identity, region, deletion/boundary times,
subscription and historical correlations, four unchanged unrelated hashes,
zero target candidates, complete pagination, and zero mutations, and computes
one canonical domain-separated hash.

Preparation copies that artifact into the private generation and binds its hash
through region selection, controller configuration/tags, campaign/runtime,
both parameter files, cleanup authority and runbook parameters, both execution
authorizations, ledger, recovery/replay validation, and terminal receipt.
Controller and operator live entry revalidate the artifact and reject
`synthetic-test-fixture`; that class is limited to isolated local test
validation and cannot enter preparation or execution.
No managed-provider absence artifact was added to the repository.

### M78-PG-014 — v2 unrelated-record equality made absence admission non-live

**Severity:** High. **Disposition:** locally resolved; no managed-provider
absence, controller deployment, arming, or campaign execution is claimed.

The v2 absence contract required all four unrelated historical deleted-record
hashes to remain currently observable. That requirement correctly protected
against drift while the records existed, but it made the exact target-absence
gate permanently unsatisfiable when any unrelated record independently stopped
appearing in the provider's current deleted inventory. Historical evidence does
not include each unrelated record's deletion time, so its absence cannot safely
be called natural or timely expiration.

The v3 contract retains immutable target, subscription, campaign, generation,
region, deletion-boundary, GET-only, pagination, and zero-mutation bindings.
It preserves the four unrelated hashes as historical context and records each
current observation only as `present-unchanged` or `absent-unattributed`.
Unknown, changed, duplicate, colliding, malformed, ambiguous, or current-only
records reject admission. The hashed page chain, baseline observation set, and
current inventory digest are included in the canonical v3 digest. Runtime and
controller admission require the v3 version and digest; controller tags and
controller execution authorizations bind the version as well. The retained v2
format remains audit-only and cannot enter live preparation, controller,
operator, recovery, cleanup, finalization, or authorization paths.

The historical four hashes are unchanged. No provider observation from the
diagnostic was stored as an admission artifact, and no claim about individual
unrelated-record retention or deletion timing is made.

### M78-OS-001 — durable deletion requests had no production executor

**Severity:** High. **Disposition:** locally resolved; managed-provider
execution remains unproved.

Migration `20260726_0027`, the API, and `UploadLifecycleService` durably created
exact-version `ObjectDeletionRequest` rows and immediately fenced reads with a
`deletion_requested` transition. No production API or worker path selected
those rows, invoked `VersionedObjectStorage.delete_version`, or appended the
terminal `deleted` transition. A committed request could therefore remain
forever pending and the checkpoint's claimed deletion/reconciliation control
was not operational.

The existing schema is sufficient; no migration was added. `DocumentWorker`
now constructs the already-required versioned provider in trusted ingestion
mode and services one locked deletion request before ordinary jobs.
`ObjectReconciler.execute_deletion_requests` uses durable request ordering and
`FOR UPDATE SKIP LOCKED`, revalidates the workspace/version/lifecycle binding,
deletes only the recorded physical key plus immutable provider version, and
appends exactly one deterministic terminal transition in the same database
transaction. An ambiguous provider success rolls back the database transition;
the retry accepts only authoritative exact-version 404 readback and then
commits the original request's completion. Provider authorization and transport
failures remain errors. Conflicting reuse of the same deletion key and reason
scope now returns an explicit 409.

Changed production files are `services/object_ingestion.py`,
`services/documents/storage.py`, and `services/jobs.py`. Focused tests cover
the request conflict, ambiguous committed response, rollback/retry, repeat-safe
terminal state, exact Azure version absence, and the production worker entry
point. The object/scanner/document shard passes 137 tests with one unavailable
local PostgreSQL fixture skipped. The legacy unlink-before-relational-commit
path remains an explicit development/demo limitation; staging and production
require trusted secure ingestion and cannot fall back to it.

### Current validation-contract corrections

Two repository-validation failures were local harness drift rather than
production behavior. The scanner-bridge recovery fixture still used the
superseded `2026-08-12T22:15:00Z` cleanup deadline while the authoritative
managed binding requires `2026-08-13T06:30:00Z`; only the success fixture was
updated and all 261 affected recovery tests pass. The mocked browser document
endpoint returned `ready` on its first poll, racing the test's required
`Extracting text` observation; it now preserves one deterministic processing
poll, and the browser suite passes 8 tests with two real PostgreSQL scenarios
explicitly skipped. Neither correction changes production behavior or retained
Milestone 7.7 evidence.

## Authorized High-defect remediation plan

Disposition recorded before production implementation on 2026-08-13:

- **M78-PG-002 — correct locally.** Replace both blanket-grant emitters with
  one literal role matrix. The API role receives `SELECT` only on the 149
  current tables referenced by API routes/services plus the authorized 0029
  request-identity table; `INSERT` excludes the worker-only heartbeat table;
  `UPDATE` is limited to `ai_requests`, `ai_responses`, `canonical_objects`,
  `canvases`, `controlled_agent_executions`,
  `controlled_workflow_executions`,
  `controlled_workflow_step_executions`, `document_processing_jobs`,
  `document_versions`, `documents`, `domain_event_outbox`, `nodes`, `users`,
  `user_sessions`, `workspace_authority_versions`, `workspace_event_sequences`,
  and `workspaces`; and `DELETE` is limited to `ai_response_sources`,
  `canonical_objects`, `canonical_relationships`, `canvases`, `citations`,
  `document_chunks`, `documents`, `edges`, and `nodes`. The API receives no
  access to migration-only `application_errors` or
  `index_compatibility_projections`. The worker receives reads only for the
  document-processing, durable-job, scanner/reconciliation, current-authority,
  event/outbox, trace, and heartbeat tables reached from `scripts.worker`;
  writes are restricted to the exact job attempt/outcome/retry/audit, document
  chunk/embedding/state, scanner result/promotion/audit, event/outbox, trace,
  and heartbeat paths. Neither runtime role receives sequence or function
  privileges. Current and default `PUBLIC` function execution is revoked;
  default table/sequence/function privileges grant nothing to either runtime
  role. Literal table names, concrete source evidence, generated SQL, and
  prohibited SQL will be contract-tested.
- **M78-PG-003 — correct locally.** Add `id-mobius77-db-migration` as a distinct
  user-assigned identity. A provisioning-only job attached to
  `id-mobius77-db-admin` creates and verifies the migration/API/worker Entra
  principals, transfers the existing `public` schema objects to the migration
  principal, grants only database/schema DDL needed by Alembic, and proves no
  dangerous flags or runtime-to-migration membership. The migration job is
  attached only to the migration identity, preserves the direct `NullPool`,
  guarded sole-head/expected-revision/advisory-lock runner, and applies the
  literal runtime matrix after migration. No administrator identity or token
  enters the migration, API, or worker container.
- **M78-PG-004 — correct locally with exactly one migration 0029.** The existing
  durable identity tables are bound to collaboration, ingestion, graph,
  workflow, agent, queue, or object-lifecycle operation/result constraints;
  reusing any would require widening an unrelated domain and still would not
  provide a canvas result/scope contract. Create one expansion-only
  `legacy_creation_request_identities` table in direct child revision
  `20260726_0029`. A unique actor/operation/key constraint is the PostgreSQL
  concurrency authority. Each record stores authoritative workspace/canvas
  scope, a canonical payload digest, result kind/id, and an append-only
  creation time. Claim and domain-object creation share one transaction;
  rollback removes both, committed replay returns the stored identity after
  current authority is revalidated, conflicting payload/scope reuse fails
  closed, and deleted results remain non-recreatable. Retention is indefinite
  while the referenced actor/workspace exists; no TTL silently invalidates a
  legitimate retry. The required key is added to all four legacy create
  contracts and their first-party callers.

The legacy creation inventory is exactly `POST /canvases`,
`POST /canvases/{canvas_id}/nodes`,
`POST /canvases/{canvas_id}/nodes/{node_id}/duplicate`, and
`POST /canvases/{canvas_id}/edges`. The first-party web client invokes those
four methods directly; tests and callers may replay after a transport-ambiguous
response, while no repository code currently provides a durable replay key.
Document upload, AI response-node creation, demo seeding, and controlled-agent
reversible writes use different established operation contracts and are not
the four proved legacy counterexamples.

## Authorized High-defect remediation result

The planned disposition above was implemented without Azure or a live
database. The complete changed production surface is:

- runtime privilege authority: `apps/api/opencanvas_api/db/role_privileges.py`,
  `apps/api/scripts/bootstrap_postgres.py`, and
  `apps/api/scripts/migrate_and_grant.py`;
- identity/job topology: `infra/milestone_7_7/main.bicep` and the `compute`,
  `identities`, `owner-bootstrap`, and `registry` modules;
- durable creation identity: migration `20260726_0029`, ORM model, service,
  API schemas/routes, and the web contracts/client/callers;
- current-head, infrastructure, role/grant, API idempotency, and affected
  caller tests plus `scripts/validate_migrations.py`.

The privilege matrix is literal and fail-closed. It covers every ORM table
reached from API routes/services except the migration-only
`application_errors` and `index_compatibility_projections`. Worker privileges
are the strict subset traced from `scripts/worker.py` through document
processing, durable jobs, authority fences, scanner/object reconciliation,
domain events, trace, and heartbeat paths. API and worker have distinct
`SELECT`/`INSERT`/`UPDATE`/`DELETE` sets. Neither receives sequence access or
function execution. Reconciliation revokes current blanket table, sequence,
and function privileges before applying the exact grants, revokes schema
creation and migration-role membership, revokes unsafe `PUBLIC` function
execution, and gives future objects no implicit runtime or `PUBLIC` privilege.

The migration lifecycle is now two-stage: the administrator-attached,
provisioning-only job deterministically creates the three Entra database
principals, rejects dangerous role flags, assigns the migration principal only
`CONNECT`/database `CREATE` and `USAGE`/schema `CREATE`, makes it the `public`
schema owner, and transfers existing application object ownership. The normal
migration job is attached only to `id-mobius77-db-migration`; it retains direct
`NullPool`, exact revision checks, the existing advisory lock and ordering, and
then reconciles runtime grants. API and worker identities cannot inherit or
assume the migration principal. The migration identity receives only ACR pull
outside PostgreSQL; no Azure-administration role was added.

Revision `20260726_0029` directly descends from `20260726_0028` and creates
only `legacy_creation_request_identities`, its two scope indexes, actor index,
unique actor/operation/key authority, constraints, and append-only guards.
There is no `0030`; `0029` is the sole head. The downgrade refuses to discard
nonempty durable identity state. Local upgrade/downgrade/re-upgrade validation
passed. Historical Milestone 7.7 records and hashes still truthfully describe
their earlier state in which `0029` did not exist and were not rewritten.

Focused local validation passed: 19 canvas/document/idempotency tests; seven
role/identity/grant contracts; 12 general migration tests; migration validator
upgrade/downgrade/re-upgrade; 10 auth/AI/collaboration tests; 78 graph/agent
tests; strict mypy over eight affected production files; affected Ruff checks;
web TypeScript, ESLint, and 75 unit tests. The infrastructure contract suite is
not all green at remediation commit `ce4543bc`: it was 93 passed / 1 failed. The corrected
`test_post_secret_migration_output_uses_explicit_subscription_scope` directly
overlapped that work. The remaining
`test_tracked_contract_text_has_no_private_arm_id_guid_or_user_path` failure is
the inherited private retained-authorization UUID embedded in
`observability_operator_bootstrap_adapter.py`. A later, separately authorized
local governance correction removed that identifier-specific check. The exact
historical authorization remains bound by its fixed authorization and receipt
integrity hashes, while the receipt field is validated semantically as a UUID;
all other source-head, execution, timestamp, URL, terminal-status, and live
readback checks remain fail closed. The exact node and full 94-node
infrastructure suite now pass. The same correction replaced the historical
audit handoff's workstation-specific receipt path with a repository-local
evidence link; repository hygiene now passes. No managed evidence gap was
closed. A local Bicep executable was not installed, so Bicep compilation was
not claimed and no tool was downloaded.

## Managed PostgreSQL and tenant-isolation evidence gaps

An evidence gap is not silently labeled as a passing control or an
implementation defect. These gaps are nevertheless blockers because this
audit surface expressly requires the associated production-readiness proof.

| Identifier | Evidence inspected and exact missing proof                                                                                                                                                                                                                                                                                                                                       | Affected production path                                                     | Severity / classification             | Validation and smallest authorized rerun                                                                                                                                                                                           | Residual risk                                                                                                           |
| ---------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------- | ------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| M78-PG-E01 | Pool defaults, replica ceilings, init gates, job shape, and retained receipts prove 40 API + 40 worker + 1 migration + 8 rollout gates = a concrete 89-connection scenario. The deployed `max_connections`, old/new revision overlap, backup/observability/emergency allocations, and operator reserve are absent, so the required budget inequality is unproved.                | Scale-out, rollout, pool exhaustion, migration, and operator access          | High; unproved claim / evidence gap   | Local pool/topology tests pass. Separately record `SHOW max_connections`, per-role activity at ceilings, overlap, every non-application allocation, and explicit reserve; pass only when the full sum is below capacity.           | Connection exhaustion can make readiness and work fail despite individually bounded pools.                              |
| M78-PG-E02 | Bicep, bootstrap SQL, runtime flags, and a migration receipt do not inventory effective table/sequence/function/database/schema/PUBLIC/ownership privileges or run negative DDL/cross-role DML tests. Backup, observability, and emergency have no deployed principals/grants.                                                                                                   | Every managed database role                                                  | High; unproved claim / evidence gap   | Local role-flag tests pass. After M78-PG-002/003, inventory catalogs and execute positive/negative tests through every exact managed identity without exposing credentials.                                                        | Undocumented ownership, inheritance, PUBLIC grants, or missing operator identities can defeat least privilege/recovery. |
| M78-PG-E03 | Milestone 7.6 proves isolated restore paths; retained 7.7 proves migration/readiness and uninterrupted health. Neither induces failover/disconnect, preserves traffic across recovery, resolves an ambiguous commit, nor proves token expiration/revocation and stale pooled-connection handling.                                                                                | API/worker pools, readiness, managed-identity rotation, worker claims, retry | High; unproved claim / evidence gap   | Local pre-ping/timeout/readiness/idempotency tests pass. After M78-PG-004, induce one bounded failover and credential-rotation case; prove degradation, pool recovery, durable request resolution, and zero duplicate effects.     | Provider failover or revoked/stale authentication may produce unknown outcomes or prolonged unready state.              |
| M78-TI-E01 | Central authority, 167 composite FKs, local cross-scope/revocation tests, and managed health are insufficient: no managed campaign combines cross-user/workspace/canvas/resource reads/writes, stale membership, worker/indexer paths, pool reuse, retry, and failover.                                                                                                          | All protected API and background database paths                              | High; unproved claim / evidence gap   | Local collaboration and data-path groups pass 24 + 108 tests. In an approved isolated campaign use two users/workspaces, revoke membership, force pool reuse/failover, and require zero cross-scope results or mutations.          | Managed-driver, PostgreSQL, pooled-transaction, or background-path behavior could differ from local SQLite proofs.      |
| M78-PG-E04 | Bicep and retained topology prove PostgreSQL 17, pgvector, `centralus`, cross-region private peering to `southcentralus` compute, Entra-only auth, seven-day retention, ZoneRedundant HA, 64-GiB P6 storage, and disabled geo backup/autogrow. Exact assigned zones, maintenance window, connection ceiling, storage-growth rationale, and production capacity claim are absent. | Maintenance/restart, storage exhaustion, regional latency, backup durability | Medium; unproved claim / evidence gap | Focused PostgreSQL/runtime topology contracts pass; the handoff records the separate mixed infrastructure-suite result. Record the approved managed configuration and capacity rationale; no topology mutation is authorized here. | Maintenance timing, storage ceiling, exact zone behavior, and capacity remain operational unknowns.                     |

### Latest managed campaign execution blocker

The later campaign authorized from clean HEAD
`e683ab00626fac9a1ac5a483ed4107e4ae47c60f` stopped in the committed operator's
first executable preflight. `infra/milestone_7_8/operator.py` passes the bare
executable name `az` to Python `subprocess.run`. The authorized Windows host has
an enabled AzureCloud login and installed Azure CLI command/batch launchers,
but no native `az.exe`; the subprocess therefore returned
`FileNotFoundError:2`. A direct control resolved `git` and reproduced the
Azure-CLI failure. No ledger transition or Azure mutation occurred.

Read-only post-blocker inventory proved both generated resource groups absent,
zero campaign- or generation-tagged resources, zero campaign-scope role
assignments, all 15 campaign residue counters at zero, and seven unrelated
subscription resources before and after. Resource generations, image
generations, scans, billable mutations, elapsed billable time, and actual cost
were 0, 0, 0, 0, 0 seconds, and USD 0.00 respectively. No evidence gap above
is closed. The sanitized receipt and full command ledger are in the
[campaign execution handoff](MILESTONE_7_8_MANAGED_POSTGRESQL_CAMPAIGN_EXECUTION_HANDOFF.md).

M78-PG-006 records the later authorized local correction to this Windows Azure
CLI launch boundary. The historical receipt and zero-residue observations
above remain unchanged. The failed source-bound generation must not be resumed;
a fresh campaign generation from the corrected clean HEAD must be separately
reviewed and authorized.

### Fresh corrected-launcher campaign execution blocker

A separately authorized fresh campaign from clean HEAD
`15837918c9e17b0bc1ce9e49ebca7bc4f9ae9999` used the corrected centralized
Windows launcher. The repository, canonical-image, account, provider,
PostgreSQL SKU/zone, quota, name, collision, seven-resource inventory, and
refreshed USD 25.6832 cost gates all passed. The lifecycle then created its two
tagged resource-group boundaries and invoked exactly one independent cleanup
deployment.

Azure rejected the cleanup Automation account with `BadRequest`: only one
Automation account is permitted for the subscription per region, and the
committed `westus` cleanup region already contains an unrelated account. The
cleanup controller never armed. Per the first-failure rule, target deployment,
image build, admission scan, PostgreSQL, managed evidence, failover, redesign,
and retry did not start. The operator entered exact-two-group direct cleanup;
both groups are absent, unrelated resources remain 7 / 7, all 15 residue
counters are zero, the billable clock never started, and best available actual
cost is USD 0.00.

Fresh campaign correlation `7d3af05024f9604f` and generation correlation
`e7fe6e05df20bfca` are retained only in sanitized evidence. Resource, image,
scan, managed-evidence, failover, and billable-mutation counts are all zero.
No evidence gap is closed. The complete result is in the
[fresh campaign execution handoff](MILESTONE_7_8_MANAGED_POSTGRESQL_FRESH_CAMPAIGN_EXECUTION_HANDOFF.md)
and its linked machine-readable receipt. A later correction or execution plan
for the regional Automation-account limit requires separate authorization and
another fresh campaign; this result does not authorize the object-storage
audit.

## Managed campaign pre-mutation disposition

A separately authorized campaign at
`b0b92c780a4afa2c4d1decfed4ebbd0b6ee7e87d` stopped before mutation because
the mandatory independent-cleanup gate could not be satisfied without
executing or modifying the completed Milestone 7.7 lifecycle. The 7.8 handoff
defines commands against an already deployed environment but supplies no 7.8
provisioning, cleanup, or evidence-probe executable. The retained 7.7 runbook
targets its deleted 7.7 scope, past deadline, and deleted principal fingerprint.

Sanitized Azure reads proved the account enabled, all nine required providers
registered, the requested PostgreSQL SKU capable of ZoneRedundant HA, and zero
relevant deployed database, registry, Container Apps, identity, Automation,
private-endpoint, private-DNS, or VNet resources. The conservative four-hour
maximum was USD 25.6832 including 25% contingency, below the USD 50 ceiling.
Cost therefore was not the blocker.

No resource or image generation began, the billable clock did not start, best
available actual cost is USD 0.00, and every campaign residue counter is zero.
No evidence gap in the table above is closed. The exact result, image decision,
validation ledger, and required campaign-enablement correction are recorded in
the
[managed PostgreSQL evidence campaign handoff](MILESTONE_7_8_MANAGED_POSTGRESQL_EVIDENCE_CAMPAIGN_HANDOFF.md).

### Campaign-enablement resume blocker

The repository-local campaign-enablement task resumed from clean HEAD
`89aafc6d65fbec376bd26796d1a1b74ee3bafd50` and stopped before implementation
after proving M78-PG-005. The new 7.8 deployment is required to derive distinct
principal names from its campaign/generation identity and to contain no retained
7.7 identifier. However, both database operational entry points are shipped in
the canonical API image and reject every name outside the exact 7.7 literals:

- `apps/api/scripts/bootstrap_postgres.py` restricts the active administrator to
  `id-mobius77-db-admin` and restricts migration/API/worker principals to the
  `id-mobius77-*` forms before it creates or validates them; and
- `apps/api/scripts/migrate_and_grant.py` independently restricts the migration,
  API, and worker principal environment values to the same exact 7.7 forms
  before Alembic or grant reconciliation runs.

Creating new Azure identity objects with those names would still embed retained
7.7 identifiers in the 7.8 campaign surface. Creating compliant 7.8-derived
names instead deterministically produces `database principal contract is
invalid` or `database role contract is invalid`. The conflict cannot be solved
in new infrastructure, cleanup, lifecycle, ledger, or evidence-harness code.
It requires a focused change to the shipped database operational scripts and
their principal-name contract tests, which the campaign-enablement authority
explicitly excludes.

No implementation file, migration, canonical image input, dependency, or
Milestone 7.7 record was changed while proving this blocker. The next action is
a separately authorized, minimal principal-contract remediation followed by a
fresh campaign-enablement run from its resulting clean HEAD. It is not Azure
execution or the object-storage audit.

### Campaign-enablement implementation result

The later expressly authorized remediation resumed from clean HEAD
`9e4b12c04f3882d4530be0e6318e9a46c4ccce12`. It resolved M78-PG-005 and added
the missing independent 7.8 campaign surface without modifying migration 0029,
runtime table privilege authority, the four legacy idempotency contracts, or
retained Milestone 7.7 evidence.

The principal correction is a closed JSON manifest with exact semantic slots
for bootstrap, migration, API, worker, evidence, and cleanup. It binds one
campaign, one generation, one sanitized subscription correlation, and a
distinct name/object-ID pair for each slot. Both database operational entry
points consume the same manifest; the active bootstrap or migration process
must match both its declared semantic name and object ID. Malformed, missing,
extra, duplicated, swapped, stale, or conflicting bindings fail before
principal creation, Alembic, or privilege reconciliation. Names remain safely
quoted, but no specific retained label receives an exception.

The campaign implementation is contained in `infra/milestone_7_8/` plus the
new managed-evidence and credential-recovery probes. It provides:

- one immutable private runtime bundle created only from a clean committed
  no-upstream branch with exactly five protected stashes;
- campaign/generation-derived identity and resource names with no executable
  7.7 lifecycle or identifier coupling;
- independent target and cleanup resource groups, one deadline-bound cleanup
  controller, exact-scope cleanup authority, verified published content, and
  a direct exact-group deletion fallback;
- a restart-safe 20-state ledger enforcing one resource generation, no more
  than one image generation, one digest/source/tree-bound passing image scan,
  a four-hour deadline, a USD 50 hard ceiling, and zero-residue finalization;
- private PostgreSQL 17, registry, network, Container Apps, identities,
  bootstrap/migration/runtime/recovery jobs, and observability definitions;
- managed catalog, exact runtime table-grant, prohibited sequence/function,
  migration ownership/revision, capacity, credential denial/recovery,
  failover, four-operation durable replay, and two-tenant isolation probes; and
- closed JSON schemas for every persisted configuration, runtime, ledger,
  scan, principal, and control-plane evidence artifact.

Focused local contracts cover the principal defect, cost boundaries at USD
49.99/50.00/50.01, contingency and immutable-deadline enforcement, every
lifecycle failure boundary, resume/substitution rejection, image admission,
cleanup deployment/readback, job completion, exact evidence inventory, and
zero residue. All six Bicep entry points compile with the installed CLI. Exact
commands and results are in the
[campaign-enablement handoff](MILESTONE_7_8_MANAGED_POSTGRESQL_CAMPAIGN_ENABLEMENT_HANDOFF.md).

This result closes M78-PG-005 only in repository state. M78-PG-E01,
M78-PG-E02, M78-PG-E03, M78-TI-E01, and M78-PG-E04 remain open until a
separately authorized execution produces and validates their managed evidence.
No Azure resource, live database, image, scan, or campaign execution occurred,
and the object-storage audit remains unstarted.

## Proved compliant controls on this surface

- The Bicep topology is a single authoritative PostgreSQL 17 Flexible Server
  with ZoneRedundant high availability, private access, public access disabled,
  Entra authentication enabled, password authentication disabled, pgvector
  allowlisted, and no application replica-read path.
- Deployed connection URLs contain a principal name but no stored password;
  short-lived managed-identity tokens are supplied at connect time. TLS
  `verify-full`, `READ COMMITTED`, connection/statement/lock/idle/acquisition
  timeouts, pool pre-ping, and safe dependency errors are explicit.
- API and worker each have a separate identity, application name, and bounded
  `10 + 0` pool per replica. The declared maximum is four replicas per service.
  Health checks reuse the service database object rather than adding another
  independent pool.
- Startup never applies migrations. The provisioning and migration jobs are
  manual, single parallel, zero-retry, and bounded. The migration runner
  verifies the expected current/target revision, sole repository head,
  PostgreSQL advisory lock, and final revision; authorized
  `20260726_0029` is now the sole head and `0030` remains absent.
- Liveness remains independent of a transient database outage, readiness fails
  closed, deployment init gates wait for the exact revision and runtime role,
  and runtime diagnostics do not expose connection details.
- The schema contains 151 ORM tables; 120 carry `workspace_id`, 54 carry
  `canvas_id`, and 167 composite foreign keys bind typed parents. The four
  canvas-scoped tables without direct `workspace_id` are constrained through
  their canvas/document/node parent chains. Current authorization is derived
  from the server principal and centralized membership authority; ingestion,
  indexing, durable jobs, workflows, agents, and object publication carry
  workspace scope and revocation fences.
- PostgreSQL row-level security remains out of scope by the deliberate
  architecture decision. It is neither required nor claimed as a passing
  control.

## Located Milestone 7.7 records that are not active defects

| Source                                                    | Exact record                                                                                                                                                                                                           | Evidence classification       | Mandatory remediation in 7.8 |
| --------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------- | ---------------------------- |
| `preflight/milestone_7_7/scope-contract.json`             | `azure-topology-preflight-execution`, `checkpoint-7`, `deployment`, `failure-injection`, `milestone-7.8`, `provisioning`, `runtime-validation`, `workload-execution`                                                   | Historical scope deferral     | No                           |
| `preflight/milestone_7_7/operation-contracts.json`        | `separately-authorized-read-only-azure-observation`, `isolated-infrastructure-provisioning`, `runtime-gate-validation`, `managed-workload-and-failure-execution`, `milestone-7.7-final-consolidation`, `milestone-7.8` | Historical operation deferral | No                           |
| `docs/MILESTONE_7_7_REMAINING_LIFECYCLE_COMPATIBILITY.md` | Seven grouped defects in image-source identity, post-secret authority, scanner arguments, mutation attribution, stage separation, terminal producers/consumers, and simulator behavior                                 | Closed defect inventory       | No; already corrected        |
| Retained nine-stage terminal lifecycle evidence           | Complete predecessor chain through soak, closeout, cleanup, zero-residue verification, and `MILESTONE_7_7_COMPLETE` at `b191a392922f94557e6ebf5914113b5e229ab00e`                                                      | Durable completion evidence   | No                           |

The two JSON `deferredWork` arrays are immutable historical scope records.
They do not prove that every named item is a defect, and the validated terminal
chain supersedes their pre-completion 7.7 execution status without rewriting
them.

## Evidence debts routed to later audit surfaces

These items are exact persisted debts or limitations. They are not yet proved
implementation defects, so this first audit surface does not fix them.

| Identifier | Source                                            | Description                                                                                                  | Classification                                      | 7.8 contract consequence                                                                                                     |
| ---------- | ------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ | --------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| M78-D-001  | `docs/KNOWN_LIMITATIONS.md`                       | File unlink and relational commit are not atomic; staged trash/outbox cleanup is deferred.                   | Architectural, reliability, and operational debt    | The object lifecycle and failed-transaction audit must validate it; remediation is conditional on a proved defect.           |
| M78-D-002  | `docs/KNOWN_LIMITATIONS.md`                       | The shared-rate-limit adapter lacks recorded end-to-end revalidation against approved isolated Azure Redis.  | Validation, reliability, and operational debt       | The shared-limit audit and final atomic-across-replicas scenario are mandatory; remediation is conditional on failure.       |
| M78-D-003  | `docs/KNOWN_LIMITATIONS.md`; `docs/DEPLOYMENT.md` | Full live telemetry destination, dashboards, alerts, retention, access, and revocation validation is absent. | Validation, operational, privacy, and security debt | The observability audit is mandatory; retained evidence must be assessed before any separately authorized Azure mutation.    |
| M78-D-004  | `docs/KNOWN_LIMITATIONS.md`                       | Production queue wake-up, operational telemetry, and external multi-service delivery require validation.     | Validation, reliability, and operational debt       | The durable-work audit is mandatory; remediation is conditional on a proved contract failure.                                |
| M78-D-005  | `docs/KNOWN_LIMITATIONS.md`                       | Backup/restore/rollback lacks validation against a managed production deployment.                            | Recovery and validation debt                        | The managed recovery scenario must be audited against retained evidence; production deployment remains excluded.             |
| M78-D-006  | `docs/KNOWN_LIMITATIONS.md`                       | No load/performance benchmarks or capacity claims are published.                                             | Capacity and documentation debt                     | The capacity audit and final documentation must record supported evidence and limitations; no unsupported claim is allowed.  |
| M78-D-007  | `docs/MILESTONE_7_ARCHITECTURE.md`                | Stage 3 category-log rows had not arrived before cleanup.                                                    | Observability validation debt                       | The observability/evidence audit must decide whether later retained evidence closes or preserves this limitation.            |
| M78-D-008  | `docs/MILESTONE_7_ARCHITECTURE.md`                | Exact Stage 3 posted cost was unavailable because of throttling and delayed usage posting.                   | Operational and cost-evidence debt                  | Final results must record the proved cost boundary and any exact-cost limitation; remediation is not automatically required. |

This routing authorizes no Azure operation, migration, image build,
publication, scanner execution, secret access, or Git remote operation.
