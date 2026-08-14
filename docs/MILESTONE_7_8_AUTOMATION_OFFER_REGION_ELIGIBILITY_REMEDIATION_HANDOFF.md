# Milestone 7.8 Automation offer-region eligibility remediation handoff

Date: 2026-08-14

Status: M78-PG-008 corrected and proved locally; no campaign executed; no
Azure mutation occurred; all five managed PostgreSQL evidence gaps remain open

## Authoritative boundary

This bounded repository-local correction started from clean HEAD
`ab10407a9979ad4a156787469b7876c5b5fd16e2` on
`milestone-7-8-production-readiness-audit-local`, with no upstream, exactly five
protected stashes, sole Alembic head `20260726_0029`, no migration 0030, no
private campaign runtime, seven unrelated Azure resources, and zero campaign
residue. The three retired campaign/generation pairs remained historical and
were not resumed, adopted, or regenerated.

Campaign execution remained paused. The correction created no campaign or
generation identifier, resource, image, scan, database connection, failover,
secret access, support request, dependency change, remote Git operation, or
object-storage work.

## Root cause and proved defect

The M78-PG-007 selector treated the intersection of provider support, enforced
policy permission, and zero active/soft-deleted Automation-account occupancy as
armable. Those gates selected `southcentralus` deterministically. The later
single authorized cleanup deployment proved that the subscription offer had a
separate admission rule: Azure rejected the account and reported that Free
Trial and Student subscriptions use a narrower Automation region set.

Provider metadata describes resource-provider support; Azure Policy describes
governance permission; account inventories describe observed occupancy. None
of those proves subscription-offer admission. M78-PG-008 was therefore a
missing independent pre-mutation gate, not a regional retry problem. The
historical campaign correctly stopped after one failed deployment and completed
exact-two-group direct cleanup with zero residue.

## Reviewed offer-region contract

The selector now computes exactly:

`closed candidates ∩ provider support ∩ offer eligibility ∩ policy permission ∩ zero active/soft-deleted occupancy`

The closed candidate order remains:

1. `eastus2`;
2. `southcentralus`;
3. `westus2`;
4. `westus`.

The reviewed restrictive public-offer baseline is normalized, sorted, and
version-bound as:

`eastus,eastus2,northeurope,southeastasia,westus`

| Evidence dimension | Independent rule                                                 |
| ------------------ | ---------------------------------------------------------------- |
| provider           | exact normalized Automation `automationAccounts` locations       |
| offer              | candidate must occur in the immutable restrictive offer-safe set |
| policy             | every enforced deny-capable assignment/definition must allow it  |
| occupancy          | active and complete soft-deleted counts must both be zero        |

Free Trial/Student metadata is classified `restricted-public-offer` with
disposition `restricted-offer-metadata-confirmed`. Missing, malformed, unknown,
or unsupported offer metadata is classified `unclassified` and receives
`restrictive-public-baseline-applied`; it never falls back to provider support
or enables a broader region. There is no caller-controlled offer class,
allowlist, cleanup region, candidate order, or eligibility bypass.

The reviewed documentation input spelled the Japan variant `JapanWest2`, which
normalizes to `japanwest2`; the current provider read returned `Japan West`,
which normalizes to `japanwest`. The relationship cannot be established
unambiguously from the authorized read-only evidence, so neither token is in
the executable offer-safe set. No alias is guessed.

The source/version binding is
`microsoft-automation-restricted-public-offer-regions-2026-08-v1`. The offer
evidence hash is domain-separated and covers the sanitized subscription-policy
metadata, classification, disposition, exact eligible set, source/version, and
excluded unresolved alias.

## Transaction and replay behavior

Preparation reads subscription-policy metadata before it can create
`.runtime/milestone_7_8`. Selection receipt version 2 records the offer
classification/disposition, normalized eligible set, source, offer evidence
hash, and a per-candidate `offerEligible` result. The domain selection hash
binds all decision material while retaining observation time as receipt
metadata rather than making a later identical recheck differ only by clock
time.

The five offer fields and selection hash are propagated through campaign
configuration, runtime, ledger, cleanup and campaign parameter files, Bicep
parameters/outputs, resource-group tags, deployment readback, resume
validation, and terminal receipt. A configured cleanup region outside the bound
offer set is invalid even when all hash strings are well formed.

Immediately before `scope-create`, `capacity-check` repeats all six regional
reads and generated policy-definition reads. The selected region, complete
selection hash, offer classification/disposition, eligible set, source, and
offer evidence hash must exactly match the prepared immutable values. Drift
fails before mutation. The cleanup deployment remains exactly one attempt in
one prepared region; no restore, existing-account reuse, retry, region hopping,
or rebinding was introduced.

## Sanitized current subscription evidence

All Azure calls used `azure_cli.py`; raw subscription, tenant, resource,
account, policy, and ARM identifiers remained in process memory and were not
printed or persisted.

| Read-only observation  | Sanitized result                                                   |
| ---------------------- | ------------------------------------------------------------------ |
| account                | enabled AzureCloud subscription                                    |
| offer classification   | `restricted-public-offer`                                          |
| offer disposition      | `restricted-offer-metadata-confirmed`                              |
| eligible set           | `eastus,eastus2,northeurope,southeastasia,westus`                  |
| offer evidence SHA-256 | `8675787fe1c8aa6482e2b5f593549fc6f823b863bf086e1c9f226bc237236dd1` |
| `eastus2`              | occupied                                                           |
| `southcentralus`       | offer-ineligible                                                   |
| `westus2`              | offer-ineligible                                                   |
| `westus`               | occupied                                                           |
| selection              | empty intersection; fail closed before preparation                 |

The final selection classification was
`automation-region-occupied-capacity-unproved`. This is a successful safety
result, not managed database evidence and not proof that a future subscription
state will remain unchanged.

## Regression coverage

Synthetic contracts prove the exact M78-PG-008 failure, independent rejection
of `southcentralus` and `westus2`, deterministic eligible alternatives, active
and soft-deleted occupancy independently, provider/policy non-expansion,
unknown/malformed metadata, Japan alias exclusion, caller override rejection,
ordering/case normalization, both inventory pagination boundaries, empty
intersection, immutable capacity replay, substitution rejection, prepared
bundle propagation, scope/deployment readback, terminal receipt, one-deployment
no-hop behavior, unrelated-account non-targeting, identifier redaction, and the
unchanged Windows/non-Windows launcher contract.

## Validation ledger

| Validation                               | Exact result                                                           |
| ---------------------------------------- | ---------------------------------------------------------------------- |
| focused offer/M78-PG-008 selection nodes | exit 0; 9 passed, 24 deselected                                        |
| full regional contract                   | exit 0; 33 passed                                                      |
| Azure CLI launcher                       | exit 0; 13 passed                                                      |
| campaign enablement                      | exit 0; 47 passed                                                      |
| runtime topology                         | exit 0; 9 passed; one inherited Starlette deprecation warning          |
| infrastructure contracts                 | exit 0; 94 passed                                                      |
| database-remediation preservation        | exit 0; 7 passed                                                       |
| strict Mypy                              | exit 0; four production files and one regional test clean              |
| Ruff                                     | exit 0; targeted changed Python files linted and formatted             |
| Bicep                                    | six centralized-launcher compilations exited 0                         |
| schema syntax/contracts                  | all Milestone 7.8 schemas parsed; repository contracts passed          |
| PowerShell cleanup syntax                | AST parse exit 0; zero errors                                          |
| Markdown and JSON formatting/links       | targeted Prettier and local-link checks exited 0                       |
| repository guards                        | hygiene, secret/private-identifier, and developer-path checks exited 0 |
| canonical image inputs                   | all five required hashes exact                                         |
| migrations                               | 0029 upgrade/downgrade/re-upgrade passed; sole head 0029; no 0030      |
| Git integrity                            | `git diff --check` and `git fsck --full --no-reflogs` exited 0         |

No `jsonschema` package was installed. JSON received syntax parsing and the
existing repository schema-contract tests, as authorized. No package-manager
execution or blanket formatting was used.

## Exact changed scope

- `infra/milestone_7_8/automation_region.py`
- `infra/milestone_7_8/campaign.py`
- `infra/milestone_7_8/prepare.py`
- `infra/milestone_7_8/operator.py`
- `infra/milestone_7_8/cleanup.bicep`
- `infra/milestone_7_8/main.bicep`
- `infra/milestone_7_8/modules/cleanup-controller.bicep`
- `infra/milestone_7_8/modules/campaign-resources.bicep`
- `infra/milestone_7_8/schemas/cleanup-region-selection.schema.json`
- `infra/milestone_7_8/schemas/campaign.schema.json`
- `infra/milestone_7_8/schemas/runtime.schema.json`
- `infra/milestone_7_8/schemas/ledger.schema.json`
- `apps/api/tests/test_milestone_7_8_automation_region.py`
- `apps/api/tests/test_milestone_7_8_campaign_enablement.py`
- `apps/api/tests/test_milestone_7_8_azure_cli_launcher.py`
- `infra/milestone_7_8/README.md`
- `docs/MILESTONE_7_8_DEFECT_REGISTER.md`
- `docs/MILESTONE_7_8_MANAGED_POSTGRESQL_CAMPAIGN_OPERATOR_RUNBOOK.md`
- `docs/MILESTONE_7_8_AUTOMATION_REGIONAL_CAPACITY_REMEDIATION_HANDOFF.md`
- `docs/MILESTONE_7_8_MANAGED_POSTGRESQL_CORRECTED_REGIONAL_CAPACITY_CAMPAIGN_EXECUTION_HANDOFF.md`
- this handoff

The two earlier handoffs retain their historical campaign and M78-PG-007 facts;
only later-correction cross-references were appended.

## Cost, residue, and remaining work

This task performed read-only Azure discovery and local validation only. Azure
mutations, campaign generations, target generations, cleanup deployments,
images, scans, database connections, failovers, and measured spend were all
zero. Final centralized readback preserved zero campaign residue and exactly
seven unrelated resources.

M78-PG-E01, M78-PG-E02, M78-PG-E03, M78-TI-E01, and M78-PG-E04 remain open.
This correction does not close the managed PostgreSQL audit surface or
Milestone 7.8. The object-storage audit remains unstarted.

The only next action is a separately authorized fresh managed PostgreSQL
evidence campaign from the new clean commit. Preparation must still fail
before mutation if the offer-aware intersection remains empty. It is not a
GitHub push and not object-storage work.
