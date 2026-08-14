# Milestone 7.8 Automation offer-safe candidate reconciliation handoff

Date: 2026-08-14

Status: M78-PG-009 is locally remediated; sanitized read-only evidence proves
one currently selectable cleanup region; no campaign was prepared or executed

## Authoritative boundary and scope

The reconciliation started from clean local HEAD
`d5df81069f6636902a581a02c92bc292d578f8ef` on
`milestone-7-8-production-readiness-audit-local`, with no upstream and exactly
five protected stashes. Alembic had sole head `20260726_0029`; migration 0030
and `.runtime/milestone_7_8` were absent. Read-only Azure inventory proved zero
campaign-tagged resources, zero `rg-m78-*` groups, and seven unrelated
resources.

This was an armability reconciliation only. It did not prepare a campaign,
create a campaign or generation identity, deploy a resource, reserve a region,
build or scan an image, connect to PostgreSQL, alter policy, touch an occupied
Automation account, or begin the object-storage audit.

## Proved defect

M78-PG-008 established the reviewed restrictive offer-safe set as `eastus`,
`eastus2`, `northeurope`, `southeastasia`, and `westus`. The executable closed
candidate order still contained only `eastus2`, `southcentralus`, `westus2`,
and `westus`. Therefore three reviewed offer-safe regions never received
provider, policy, or occupancy dispositions during selection.

Complete sanitized reads proved that `southeastasia` was provider-supported,
offer-eligible, policy-allowed, and unoccupied. Its omission from the stale
four-region order was its only blocker. This is High defect M78-PG-009, not an
external empty-intersection condition.

## Complete regional disposition

`Present before` records the candidate order at the starting HEAD. `Selectable
after` applies the corrected seven-region contract to the same complete live
evidence.

| Region           | Present before | Provider | Offer | Policy | Active | Soft-deleted | Selectable after | Sanitized rejection reason                                      |
| ---------------- | -------------- | -------- | ----- | ------ | -----: | -----------: | ---------------- | --------------------------------------------------------------- |
| `eastus`         | no             | yes      | yes   | yes    |      0 |            1 | no               | occupied by one discoverable soft-deleted Automation account    |
| `eastus2`        | yes            | yes      | yes   | yes    |      0 |            1 | no               | occupied by one discoverable soft-deleted Automation account    |
| `northeurope`    | no             | yes      | yes   | yes    |      0 |            1 | no               | occupied by one discoverable soft-deleted Automation account    |
| `southeastasia`  | no             | yes      | yes   | yes    |      0 |            0 | yes              | none; omission from the stale operational order was the blocker |
| `westus`         | yes            | yes      | yes   | yes    |      0 |            1 | no               | occupied by one discoverable soft-deleted Automation account    |
| `southcentralus` | yes            | yes      | no    | yes    |      0 |            0 | no               | outside the immutable restricted public-offer eligible set      |
| `westus2`        | yes            | yes      | no    | yes    |      0 |            0 | no               | outside the immutable restricted public-offer eligible set      |

The corrected deterministic order is:

1. `eastus2`;
2. `southcentralus`;
3. `westus2`;
4. `westus`;
5. `eastus`;
6. `northeurope`; and
7. `southeastasia`.

This preserves the reviewed historical prefix, makes every offer-safe region
participate, and returns `southeastasia` as the first viable candidate under
the current observation. Caller-supplied candidate orders and cleanup regions
remain prohibited. There is no fallback, retry, region hop, account reuse, or
post-mutation selection.

## Read-only evidence completeness

Every Azure command passed through `azure_cli.py`. Successful selection proves
both active and soft-deleted inventory responses had no `nextLink`; otherwise
the selector fails closed. The provider returned 47 normalized Automation
locations. One enforced policy assignment was expanded through every required
definition and deny-capable initiative member, producing 57 definition reads.
All seven candidates were policy-allowed.

| Evidence                         | Sanitized result                                                   |
| -------------------------------- | ------------------------------------------------------------------ |
| account context                  | enabled AzureCloud subscription                                    |
| offer classification             | `restricted-public-offer`                                          |
| offer eligibility SHA-256        | `8675787fe1c8aa6482e2b5f593549fc6f823b863bf086e1c9f226bc237236dd1` |
| provider locations SHA-256       | `bc579b6632f91e04c948709bd0ae4eec211d075bc06c96dcd62370591af17285` |
| active occupancy SHA-256         | `28d2bce512c7aefd02db18987f717fb8f950e04f710155062e43ea163dce0d2e` |
| soft-deleted occupancy SHA-256   | `9ab15ae22ba1be8b483e26d543a59016f009ae93e745f053a38dd1beb5894831` |
| policy evidence SHA-256          | `e03b0604e703ad3438b4c2ec4f55229a63e7669e478b0cc4bffc791b585805da` |
| corrected v3 selection SHA-256   | `b7c964e429f4dbba1ff10718d9f1fcdf72061a24c26959f3045f2d27ec0f5026` |
| active pagination                | complete                                                           |
| soft-deleted pagination          | complete                                                           |
| selected region                  | `southeastasia`                                                    |
| campaign-tagged Azure residue    | zero                                                               |
| unrelated subscription resources | seven, unchanged                                                   |

## Local correction and immutable binding

The candidate tuple is still a repository-owned exact constant. Its new CSV
binding is independent of the selection hash and is carried through:

- campaign configuration and validation;
- private runtime and prepared-bundle validation;
- restart ledger bind/resume checks;
- cleanup and campaign ARM parameter files;
- cleanup and target Bicep parameters and outputs;
- lifecycle and target resource-group tags;
- cleanup deployment and campaign deployment readback;
- the repeated pre-mutation `capacity-check`; and
- the zero-residue terminal receipt.

Campaign, runtime, ledger, selection, and terminal receipt contracts advance
to version 3 and close the exact order. The selection schema requires seven
candidate dispositions. The full selection
hash continues to bind provider, offer, policy, active occupancy, soft-deleted
occupancy, per-candidate results, and deterministic selection. Preparation and
the repeated capacity check use the same selector and exact hash inputs.

## Adversarial coverage

Focused tests prove:

- the formerly omitted viable `southeastasia` candidate is selected;
- the offer-safe set is a subset of the immutable candidate set and a dropped
  candidate is rejected;
- every one of seven candidates receives a disposition;
- occupied `eastus2` and `westus` remain rejected;
- offer-ineligible `southcentralus` and `westus2` remain rejected;
- provider response order and casing do not affect the document or hash;
- full offer-safe occupancy keeps the intersection fail-closed;
- configuration, runtime, ledger, parameters, schemas, tags, Bicep outputs,
  deployment readback, and terminal receipt carry the same candidate order;
- preparation and repeated capacity validation use the same full candidate
  set and selection hash; and
- caller override, restore, account reuse, retry, or region hopping is absent.

## Validation status

| Validation                         | Exact result                                                                      |
| ---------------------------------- | --------------------------------------------------------------------------------- |
| focused M78-PG-009/candidate nodes | exit 0; 19 passed                                                                 |
| complete Milestone 7.8 contracts   | exit 0; 104 passed across regional, launcher, campaign, and database preservation |
| runtime/infrastructure contracts   | exit 0; 103 passed; one inherited Starlette deprecation warning                   |
| strict Mypy                        | exit 0; four production files and the regional test clean                         |
| Ruff                               | exit 0; seven affected Python files linted and format-checked                     |
| Bicep                              | six centralized-launcher compilations exited 0                                    |
| schema syntax/contracts            | eight schemas parsed; repository contract tests passed                            |
| PowerShell cleanup syntax          | AST parse exit 0; zero errors                                                     |
| Markdown/JSON formatting           | targeted installed Prettier write/check; nine files matched                       |
| Markdown links                     | five affected documents; 11 local links; zero missing                             |
| repository hygiene                 | exit 0; 640 source files                                                          |
| private/developer-path guard       | exit 0; one exact guard node passed                                               |
| canonical image inputs             | exit 0; all five retained hashes exact                                            |
| migrations                         | 0029 upgrade/downgrade/re-upgrade passed; sole head 0029; no 0030                 |
| Git integrity                      | `git diff --check` and `git fsck --full --no-reflogs` exited 0                    |
| final sanitized Azure counts       | zero campaign-tagged resources/groups; seven unrelated resources                  |

The first Mypy invocation omitted `--explicit-package-bases` and exited 2 on
duplicate module naming; the corrected strict invocation passed. An optional
test-only cache redirection to Windows `NUL` triggered a Mypy 1.20.2 internal
error; the ordinary strict test-file invocation passed. Neither invocation
changed dependencies. No `jsonschema` dependency was installed, and no package
manager, image, scanner, campaign, or live database was invoked.

## Exact changed scope

- `infra/milestone_7_8/automation_region.py`
- `infra/milestone_7_8/campaign.py`
- `infra/milestone_7_8/prepare.py`
- `infra/milestone_7_8/operator.py`
- `infra/milestone_7_8/cleanup.bicep`
- `infra/milestone_7_8/main.bicep`
- `infra/milestone_7_8/modules/cleanup-controller.bicep`
- `infra/milestone_7_8/modules/campaign-resources.bicep`
- `infra/milestone_7_8/schemas/campaign.schema.json`
- `infra/milestone_7_8/schemas/cleanup-region-selection.schema.json`
- `infra/milestone_7_8/schemas/ledger.schema.json`
- `infra/milestone_7_8/schemas/runtime.schema.json`
- `infra/milestone_7_8/README.md`
- `apps/api/tests/test_milestone_7_8_automation_region.py`
- `apps/api/tests/test_milestone_7_8_campaign_enablement.py`
- `apps/api/tests/test_milestone_7_8_azure_cli_launcher.py`
- `docs/MILESTONE_7_8_DEFECT_REGISTER.md`
- `docs/MILESTONE_7_8_MANAGED_POSTGRESQL_CAMPAIGN_OPERATOR_RUNBOOK.md`
- `docs/MILESTONE_7_8_AUTOMATION_OFFER_REGION_ELIGIBILITY_REMEDIATION_HANDOFF.md`
- this handoff

## Remaining boundary

This proof establishes current armability only; it is not an Azure reservation
and does not close M78-PG-E01, M78-PG-E02, M78-PG-E03, M78-TI-E01, or
M78-PG-E04. Milestone 7.8 remains incomplete. The object-storage audit remains
unstarted.

Only a separately authorized fresh managed PostgreSQL evidence campaign from
the final clean commit may be considered next. This reconciliation does not
authorize that campaign, a GitHub push, or any other Azure mutation.
