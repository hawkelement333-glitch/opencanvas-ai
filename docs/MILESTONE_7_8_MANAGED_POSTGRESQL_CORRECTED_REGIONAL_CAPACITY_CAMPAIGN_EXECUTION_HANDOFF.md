# Milestone 7.8 corrected regional-capacity campaign execution handoff

Date: 2026-08-14

Status: blocked during the single cleanup-controller deployment; direct cleanup
completed with independently verified zero residue

Terminal disposition:
`MILESTONE_7_8_MANAGED_POSTGRESQL_EVIDENCE_CAMPAIGN_BLOCKED_CLEANUP_COMPLETE`

## Outcome

Exactly one fresh campaign was prepared and executed from the corrected
regional-capacity commit. The repository, Azure account, seven-resource
unrelated inventory, canonical image boundary, refreshed cost envelope, closed
Automation candidate order, policy evaluation, active and soft-deleted account
inventories, regional evidence hashes, provider/SKU/quota checks, name
availability, and repeated pre-mutation selection all passed.

The prepared and repeated selector chose `southcentralus`. The lifecycle created
the generated target boundary and invoked the cleanup-controller deployment
exactly once. Azure rejected the Automation account with `BadRequest`: Free
Trial and Student subscriptions cannot create Automation accounts in
`southcentralus`; Azure listed `eastus`, `eastus2`, `westus`, `northeurope`,
`southeastasia`, and `japanwest` as the allowed regions. The committed selector
does not evaluate that subscription-offer restriction. This is the newly proved
High defect `M78-PG-008`.

The first-failure rule stopped the campaign before the cleanup controller,
billable target deployment, image build, scan, PostgreSQL creation, bootstrap,
migration, managed evidence, or failover. The operator entered its exact-two-
group direct cleanup path. All 15 residue counters are zero, both generated
groups are absent, and the seven unrelated resources remain unchanged at 7 / 7.
All five managed PostgreSQL evidence gaps remain open. Milestone 7.8 remains
incomplete, and the object-storage audit remains unstarted.

The sanitized machine-readable receipt is
[`managed-postgresql-corrected-regional-capacity-campaign-execution.json`](../evidence/milestone_7_8/managed-postgresql-corrected-regional-capacity-campaign-execution.json).
Earlier blocked-campaign handoffs and receipts remain historical and unchanged.

## Starting boundary

- branch: `milestone-7-8-production-readiness-audit-local`;
- starting HEAD: `ba8f2eb42ec25ce8937de27fc4070ab8f15b5ff6`;
- subject: `fix(infra): make 7.8 cleanup region capacity-aware`;
- upstream: absent;
- starting tree/index: clean;
- protected stashes: exactly five and unchanged;
- Alembic sole head: `20260726_0029`;
- migration `0030`: absent;
- private runtime directory: absent before preparation;
- campaign residue: zero;
- unrelated subscription resources: exactly seven;
- retained campaign spend before authorization: USD 0.00; and
- object-storage audit: unstarted.

The canonical image boundary matched exactly:

| Input        | SHA-256                                                            |
| ------------ | ------------------------------------------------------------------ |
| build input  | `533dc8d9a64f2d4b1a8a10d5ac769b11e1bc962741a7637da44c037e34c4dad7` |
| Dockerfile   | `1f914420f661e40bcc8e61d149115387042fd3948323b645b9a204390c90a82b` |
| API project  | `b826c6e415e5c836cda5c74696d69b61f517a86556b2fecb82201ca35540868c` |
| build lock   | `22f8b5d1f0b8521e28470f6097717ff64c9cccc7b6037db7a5c25962e32a7ccb` |
| runtime lock | `cdab59f073ff510ff6d8b951d178381650236662b488c06b2d6436063f336aa0` |

## Fresh generation and Azure entry boundary

- campaign correlation: `0da94b3cc81ac68b`;
- generation correlation: `d3f01044e870c0e8`;
- retired correlation reused: no;
- resource generations: 0;
- Azure cloud/state: AzureCloud / Enabled;
- subscription correlation: `1164c8c17745a1f5`;
- tenant correlation: `03b6af3c6cec9bc7`;
- generated group collisions before mutation: false / false;
- campaign-tagged resources before mutation: 0;
- unrelated resources before mutation: 7; and
- immutable cleanup deadline: `2026-08-14T18:02:38Z`.

Raw subscription, tenant, resource-group, identity, object, role-assignment,
and ARM identifiers are excluded from tracked evidence. The private runtime was
removed only after operator and independent zero-residue readback passed.

## Regional-capacity proof and defect

Preparation and the immediately repeated 15-command `capacity-check` produced
the same deterministic selection:

| Candidate        | Provider/policy/occupancy status |
| ---------------- | -------------------------------- |
| `eastus2`        | occupied                         |
| `southcentralus` | viable and selected              |
| `westus2`        | viable                           |
| `westus`         | occupied                         |

The repeated selection matched the immutable prepared selection. Account,
provider, active-account, soft-deleted-account, policy-assignment, and generated
policy-definition reads were complete and unpaginated. The bound evidence was:

| Evidence                                  | SHA-256                                                            |
| ----------------------------------------- | ------------------------------------------------------------------ |
| complete regional selection               | `6d8839b61d64bed340271cf192b13905375be60a8882b491132a247875e5f845` |
| provider locations                        | `bc579b6632f91e04c948709bd0ae4eec211d075bc06c96dcd62370591af17285` |
| active Automation-account occupancy       | `28d2bce512c7aefd02db18987f717fb8f950e04f710155062e43ea163dce0d2e` |
| soft-deleted Automation-account occupancy | `9ab15ae22ba1be8b483e26d543a59016f009ae93e745f053a38dd1beb5894831` |
| enforced location-policy evaluation       | `e03b0604e703ad3438b4c2ec4f55229a63e7669e478b0cc4bffc791b585805da` |

The one cleanup deployment then returned the nested codes `DeploymentFailed`,
`ResourceDeploymentFailure`, and `BadRequest`. Azure's sanitized terminal
message established an additional admission dimension: the subscription offer
limits Automation-account creation to a provider-owned region set that differs
from provider support, Azure Policy, and account occupancy. The committed
selector did not read or prove that dimension before choosing
`southcentralus`.

This is not a race after a correct preflight. The selected location was already
ineligible for this subscription class when the selector marked it viable.
`M78-PG-008` therefore remains an unresolved repository contract defect. No
region hop, second generation, replacement campaign, retry, source repair, or
manual infrastructure substitution was attempted.

## Refreshed cost gate

The Azure Retail Prices API was refreshed through the centralized launcher at
`2026-08-14T14:02:14Z`. The sanitized price-evidence SHA-256 is
`e08c5ef768be55cb62963d685fac4db2abdede122026d43277440374a3e40eb0`.
The current PostgreSQL rates remained USD 0.201 per two-vCore node-hour,
USD 0.13 per storage GiB-month, and USD 0.108 per backup GiB-month. The complete
reviewed envelope remained:

| Cost boundary             |     USD |
| ------------------------- | ------: |
| subtotal                  | 20.5466 |
| 25 percent contingency    |  5.1366 |
| conservative maximum      | 25.6832 |
| hard ceiling              | 50.0000 |
| margin below hard ceiling | 24.3168 |

The cost gate passed. The first billable mutation never occurred, so billable
elapsed time is 0 seconds. A post-cleanup Cost Management query scoped to the
two generated groups returned no current row; the best available actual cost is
therefore unavailable due to delayed or absent cost data, not asserted as a
measured USD 0.00.

## Image, topology, migration, and evidence disposition

| Surface                                      | Result                             |
| -------------------------------------------- | ---------------------------------- |
| generated resource-group boundaries          | 2 created, then deleted            |
| cleanup-controller deployments               | 1 failed attempt                   |
| cleanup controllers armed                    | 0                                  |
| billable target generations                  | 0                                  |
| image builds / immutable digests / scans     | 0 / 0 / 0                          |
| managed identities                           | not created                        |
| PostgreSQL / ACR / Container Apps topology   | not created                        |
| bootstrap / migration 0029                   | not reached                        |
| connection peak / remaining reserve          | not observed                       |
| effective role/ownership/grant execution     | blocked; `M78-PG-E02` remains open |
| 89-connection capacity scenario              | blocked; `M78-PG-E01` remains open |
| failover and recovery timing                 | not reached; no failover executed  |
| credential rotation and old-token revocation | not reached                        |
| four idempotency replay outcomes             | not reached                        |
| two-tenant isolation outcomes                | not reached                        |
| managed operational-configuration readback   | not reached                        |

No mutable or immutable image was built or deployed, and the one authorized
admission scan was not invoked. No managed database result is represented as a
pass or skip.

## Cleanup and residue

The operator transitioned from `scope-created` to `cleaning` immediately after
the failed deployment. Because the cleanup controller never armed, cleanup used
the committed direct exact-two-group path.

| Lifecycle event   | UTC timestamp                 |
| ----------------- | ----------------------------- |
| scope created     | `2026-08-14T14:05:56.925478Z` |
| cleanup started   | `2026-08-14T14:06:41.736869Z` |
| cleanup completed | `2026-08-14T14:06:59.775287Z` |
| residue verified  | `2026-08-14T14:07:15.885165Z` |
| finalized         | `2026-08-14T14:07:16.187493Z` |

| Residue counter             | Value |
| --------------------------- | ----: |
| target resource groups      |     0 |
| cleanup resource groups     |     0 |
| role assignments            |     0 |
| Automation accounts         |     0 |
| cleanup schedules           |     0 |
| managed identities          |     0 |
| PostgreSQL servers          |     0 |
| container registries        |     0 |
| Container Apps environments |     0 |
| Container Apps jobs         |     0 |
| virtual networks            |     0 |
| private endpoints           |     0 |
| private DNS zones           |     0 |
| diagnostic settings         |     0 |
| synthetic rows              |     0 |

The operator residue phase and a separate centralized-launcher readback both
proved the generated groups absent, campaign-tagged resources zero, and the
unrelated subscription inventory unchanged at exactly seven resources.

## Post-campaign validation

The inherited 904-second monolithic command was not repeated. Validation was
bounded to the evidence-only diff and the preserved repository invariants:

| Command or check                                                            | Exact result                                                                       |
| --------------------------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| targeted Prettier write, then `--check`, over three Markdown files and JSON | exit 0; 4 files matched                                                            |
| machine receipt parse                                                       | exit 0; 1 JSON document parsed                                                     |
| bounded relative Markdown-link resolver                                     | exit 0; 9 local links, 0 missing                                                   |
| `python scripts/check_repository_hygiene.py`                                | exit 0; 638 source files                                                           |
| tracked private-identifier guard                                            | exit 0; 1 passed                                                                   |
| `python scripts/validate_migrations.py`                                     | exit 0; upgrade 0029, downgrade 0028, re-upgrade 0029 passed                       |
| `python -m alembic -c alembic.ini heads` from `apps/api`                    | exit 0; sole `20260726_0029 (head)`                                                |
| migration `0030` inventory                                                  | exit 0; count 0                                                                    |
| canonical input snapshot                                                    | exit 0; all five required hashes exact                                             |
| centralized Azure CLI launcher version smoke                                | exit 0; batch launcher, Azure CLI `2.88.0`                                         |
| private runtime absence                                                     | exit 0; `.runtime/milestone_7_8` absent                                            |
| `git diff --check` / `git fsck --full --no-reflogs`                         | exit 0 / exit 0                                                                    |
| changed-file and prohibited-scope inventory                                 | exit 0; 4 changed files, 0 forbidden production/dependency/retained-evidence files |

No production or infrastructure source test result is promoted merely because
that source was unchanged. Final branch, upstream, tree/index, stash, and
zero-residue checks are repeated after the evidence commit.

## Preserved boundaries and next action

No production or infrastructure source, migration, dependency, lockfile,
canonical image input, production data, retained Milestone 7.7 evidence,
protected stash, object storage, object-upload scanner, soak, or remote Git
surface changed. No second campaign, target generation, cleanup region, image,
digest, scan, failover, or cleanup deadline was created.

The next action requires separate remediation authority for `M78-PG-008`, then
separate authorization for another fresh source-bound managed PostgreSQL
campaign. It is not a GitHub push and not the object-storage audit. A later
successful managed campaign would complete only this Milestone 7.8 audit
surface; Milestone 7.8 is not complete.
