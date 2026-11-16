# M78-D-002 East US managed Redis package

Current result — 2026-11-16 UTC: **M78-D-002 is complete: 17 accepted, 0 failed, 0 unproved out of 17 existing assertions.** All 18 cleanup counters are zero; the reusable controller is preserved and the campaign ledger finalized. PostgreSQL and M78-D-001 remain closed. Milestone 7.8 remains incomplete. Billing remains **unsettled**.
See the [managed campaign reconciliation](#managed-campaign-reconciliation).

## Historical preparation package

**Prepared for separate approval; no regional provisioning or spending is
authorized by this document.** M78-D-002 remains open: **0 accepted, 0 failed,
17 unproved**. PostgreSQL and M78-D-001 remain closed. Billing remains unsettled.

## Selection and retained evidence

The [Canada Central continuation](MILESTONE_7_8_MANAGED_REDIS_CONTINUATION_PACKAGE.md#actual-foundation-failure-and-completed-cleanup)
failed provider preflight for B0 capacity and an invalid logging payload.
The logging payload is corrected and validated; B0, B1 and B3 validation in
Canada Central all reported insufficient capacity. That attempt is finalized
with **18 zero cleanup counters** and a successful corrected-runbook cleanup.
Its terminal receipt is
`f225f19456404d4a77e1d84bcc4ab0ddf3e15999991e760fde6266c6981ac50e`.

The user permits another region for this isolated proof unless an existing
project requirement mandates Canadian residency. The owning checklist,
M78-D-002 register, directly referenced Redis runbooks and referenced governance
documents contain no identified Canadian-only mandate. Canada Central was the
previous campaign scope. This is a scoped finding for synthetic proof fixtures,
not an approval to relocate production data or a certification of external
contracts. The reviewed file hashes and exact findings are retained privately.

**Selected: East US, HA Balanced B0.** Current public retail comparisons of
Redis, two jobs and ACR put East US and East US 2 in the lowest suitable
full-package price tier. East US also matches the existing cleanup controller.
New Zealand North's lower Redis-only listing does not make its full package
cheaper because its job prices are higher.

| Compared option | Eight-hour forecast, including 25% contingency |
| --- | ---: |
| East US / East US 2, HA B0 | USD 7.5083 |
| East US / East US 2, HA B1 | USD 7.8283 |
| East US / East US 2, HA B3 | USD 8.4883 |
| West US 2, HA B0 | USD 7.9403 |
| New Zealand North, HA B0 | USD 7.9643 |

The authenticated provider offering lists East US and the retained Redis API.
An East US B0 subscription-scope **Provider** validation returned HTTP 200 and
`Succeeded`; its validated resource list includes the Redis cache, default
database, access assignments, internal Container Apps environment, registry,
identities and networking. The proposed target returned 404 before and after
validation. No group or workload was created. This is point-in-time provider
validation, **not a capacity reservation or managed acceptance**. Revalidate
the exact package at execution; preserve a failure and clean up if capacity is
unavailable. [ARM provider-validation semantics](https://learn.microsoft.com/en-us/rest/api/resources/deployments/validate-at-subscription-scope?view=rest-resources-2025-04-01).

## Exact scope and bindings

Target **`rg-m78-5e40fefee0-target`**, campaign `m78-redis-5e40fefee0a5`,
generation `g1-4602a1540561`, East US. Private preparation and evidence live in
`.runtime/milestone_7_8/redis-regional-20261116/`. `package-review.json` binds the
final clean source checkpoint, exact command arrays, request bodies, window,
cost quantities/meters, controller evidence and this document. Approval must
name its canonical package digest.

| Bound input | SHA-256 / digest |
| --- | --- |
| Unchanged injected probe | `f610ff80a42cb3545fc3ce7fa199c76ab217e7684ed5bb6b9819b8dc3baf691e` |
| Regional template, with JSON-null logging | `f9e0b30517bf09fd61e6ae239d735fa236a01c3cf63f29219bc1e3da81423905` |
| Already accepted published cleanup script | `38cfeb6cd6e706d197e7a689e5080c36fdc6c3007ad14c0c0cbf35ca626cefd9` |
| Retained image/index | `sha256:f498e5aa0f5e44dc7becc92868e1bb989372ef09a3f30d694e89d172eaa66b0a` |
| Runtime image | `sha256:241c55acd6e169546969b1c36f58806a146e3562f69011f5a3efc438a71eb769` |
| Canonical image inputs | `d94e350754821b1172a9b4452466391053e0221d3095e336e43379f6f33c312f` |

The source template adds only East US to its explicit region allowlist; Canada
Central remains the default. Private parameters select East US. B0, HA,
NoCluster, NoEviction, TLS, Entra-only authentication, exact Redis ACLs and all
17 assertion definitions are unchanged. The focused region/size check passed
with Bicep compilation; the logging correction's affected check also passed.
Existing valid probe, infrastructure, controller and helper tests are reused.
No unchanged suite or image rebuild is included.

Provision exactly one B0 HA cache/default database, two Redis access assignments,
two managed identities, two independent retained-image jobs (0.5 vCPU/1 GiB),
one internal Consumption environment, temporary Premium ACR, VNet/subnets, NSG,
two private endpoints and private DNS zones/links. Public Redis access and keys
remain disabled. No PostgreSQL, object/scanner, paid log sink, broader capacity
campaign or next-milestone resource is included.

## Execution order and recovery

1. Verify the source/package/image bindings and current window. Confirm target
   absence and that the finalized predecessor remains closed. Read the exact
   preserved controller, empty campaign inventories, identity, Reader and
   already accepted published content.
2. Renew only the controller's three deadline tags from 02:00 to 02:30 UTC on
   November 17. Reuse its valid publication chain and 1,000-cent compatibility
   proof; **do not republish unchanged content**. Accept the actual renewal
   readback through the existing authority validator.
3. Inside the provisioning window, create the isolated target, its two cleanup
   grants, and the exact one-time schedule/binding. Bind all cleanup parameters
   to the accepted current controller content and read back protection before
   any paid resource deployment.
4. Run exact provider validation of the prepared regional foundation. Only
   after it passes, provision and admit the private foundation. Transfer the
   retained image, restore ACR's network rules, then deploy the two jobs.
   Temporary ACR access is restricted to the bound current operator /32 for
   **at most 20 minutes cumulatively**, including recovery; always restore it.
5. Run the existing independent leader/follower `admission` and `healthy`
   phases. Preserve accepted source/image/identity/execution-bound receipts.
6. Apply only the recorded NSG rule denying Redis TCP 10000, run the `fault`
   pair, restore the rule unconditionally, then run the `recovery` pair.
   Preserve original contributing execution IDs when exporting/reusing a
   receipt. A wrapper or later export is not a substitute contributor.
7. Preserve evidence and reconcile uncertain outcomes before retrying only
   affected operations within the same scope, cost and deadline. Failed gates
   block dependent phases. If recovery cannot fit the bounds, stop proof and
   clean up. Once deletion starts, do not reopen that campaign.
8. Reconcile any existing cleanup job, perform teardown, verify all 18 counters
   and preserved controller content, then finalize the ledger and documentation.
   Missing exports never delay cleanup. Exact direct cleanup of the same target
   is covered if the runbook demonstrably fails/stalls, with its failure retained.

The unchanged inventory has **two admission, twelve healthy, two failure and
one recovery assertion**. Require both independent managed contributors where
specified; successful local tests or job status alone do not accept an
assertion. Require the full 1,200-second runtime plus 120-second dispatch reserve
before a pair starts. The compact recovery checkpoint records actual operations,
executions, accepted assertions, evidence paths, deadlines and exact next action.

## Cost, region dependencies and approval window

| Bound | Proposal |
| --- | --- |
| New forecast, including 25% contingency | USD **7.5083** |
| New incremental ceiling | USD **10.00** |
| Previous cumulative approved ceiling, unsettled | USD **340.89** |
| Proposed cumulative ceiling | USD **350.89** |
| Earliest paid start | November 16, 2026 **18:30 UTC / 12:30 CST**, only after approval |
| Begin provisioning by | November 16, 2026 **20:30 UTC / 14:30 CST** |
| Stop proof and scheduled cleanup | November 17, 2026 **00:30 UTC / November 16, 18:30 CST** |
| Binding expiry | November 17, 2026 **01:30 UTC / November 16, 19:30 CST** |
| Cleanup/controller authority ends | November 17, 2026 **02:30 UTC / November 16, 20:30 CST** |

The estimate includes eight hours for two HA Redis nodes, both jobs continuously,
one full ACR day, two DNS-zone months, endpoint/data processing, bounded network,
environment applicability and controller reserves, then 25% contingency. B0 is
USD 0.016 per node-hour in the retained regional price response. Previous
forecasts and ceilings remain history and are not unused spending allowances or
settled charges. No free grant or discount is deducted. Billing is unsettled.

Redis, jobs, registry and private networking are colocated in East US. The
controller is already in East US. No workload or image dependency requires
inter-region egress; upload of the retained local image is ingress. Existing
Canada Central campaigns are closed and supply no live dependency. The estimate
retains the prior conservative network reserves rather than assuming all data
processing is free. Introducing a remote registry, cross-region data path or
another paid service requires a revised concrete package. Public
[Azure retail prices](https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices)
and [bandwidth rates](https://azure.microsoft.com/en-us/pricing/details/bandwidth/)
support the retained meter comparison.

This is a new isolated campaign and spending request. The prior Canada Central
ceiling is not repurposed. Missed start windows require a newly frozen window;
do not arm an empty target merely to wait for a future permitted start.

## Cleanup, publication and remaining requirements

The same **18 zero residue counters** cover target/provider-managed groups,
resources/roles, binding/schedule, Redis cache/database/ACL children, NSG/rules,
registry, jobs, environment, identities, private endpoints, DNS and VNet. Require
exact child 404s and complete scoped inventories; errors are not absence. If
preflight fails before resource creation, retain its real dispatch and
independently verified no-effect reconciliation. Do not fabricate an
environment attribution snapshot. Preserve the controller, identity, Reader,
bootstrap history and accepted published script; preserve provider registration.

Only accepted managed evidence can close M78-D-002. Until all 17 assertions pass,
its checklist/register remain incomplete and list exact missing evidence.
Failed attempts and both prior cleanup receipts remain historical. The user
authorizes normal commits/pushes of useful sanitized recovery checkpoints and
completed areas with remote-SHA verification, but those commits do not imply
acceptance or Azure authority. Preserve unrelated changes and all five stashes;
no secrets or raw `.runtime` artifacts enter Git. Do not force-push or merge.

<!-- M78-D-002 regional terminal documentation reconciliation -->
## Managed campaign reconciliation

Reconciled 2026-11-16 UTC after verified cleanup and ledger finalization.

**M78-D-002 is complete: 17 accepted, 0 failed, 0 unproved out of 17 existing assertions.** All 18 cleanup counters are zero; the reusable controller is preserved and the campaign ledger finalized. PostgreSQL and M78-D-001 remain closed. Milestone 7.8 remains incomplete. Billing remains **unsettled**.

Both earlier Redis attempts remain finalized history: [the first attempt](MILESTONE_7_8_MANAGED_REDIS_EXECUTION_PACKAGE.md#managed-campaign-reconciliation) and [the Canada Central continuation](MILESTONE_7_8_MANAGED_REDIS_CONTINUATION_PACKAGE.md#managed-campaign-reconciliation) each accepted no managed assertions and retained their own failed operations and verified cleanup. The preparation text above is retained historical scope, not authority for another run. Accepted results retain their actual contributing execution IDs. Failed and uncertain attempts remain history; cleanup does not turn them into accepted proof.

| Existing assertion | Phase | Result | Actual contributing executions | Missing evidence or work |
| --- | --- | --- | --- | --- |
| `managed-entra-private-tls` | `admission` | accepted | `caj-m78r-5e40fefee0-leader-i5oi4er`, `caj-m78r-5e40fefee0-follower-39k1y2u` | Both source-bound replica receipts accepted. |
| `foreign-prefix-acl-denied` | `admission` | accepted | `caj-m78r-5e40fefee0-leader-i5oi4er`, `caj-m78r-5e40fefee0-follower-39k1y2u` | Both source-bound replica receipts accepted. |
| `replica-atomic-network` | `healthy` | accepted | `caj-m78r-5e40fefee0-leader-owoixnm`, `caj-m78r-5e40fefee0-follower-5t3ossk` | Both source-bound replica receipts accepted. |
| `replica-atomic-user` | `healthy` | accepted | `caj-m78r-5e40fefee0-leader-owoixnm`, `caj-m78r-5e40fefee0-follower-5t3ossk` | Both source-bound replica receipts accepted. |
| `replica-atomic-workspace` | `healthy` | accepted | `caj-m78r-5e40fefee0-leader-owoixnm`, `caj-m78r-5e40fefee0-follower-5t3ossk` | Both source-bound replica receipts accepted. |
| `replica-atomic-resource` | `healthy` | accepted | `caj-m78r-5e40fefee0-leader-owoixnm`, `caj-m78r-5e40fefee0-follower-5t3ossk` | Both source-bound replica receipts accepted. |
| `replica-atomic-operation` | `healthy` | accepted | `caj-m78r-5e40fefee0-leader-owoixnm`, `caj-m78r-5e40fefee0-follower-5t3ossk` | Both source-bound replica receipts accepted. |
| `replica-atomic-provider` | `healthy` | accepted | `caj-m78r-5e40fefee0-leader-owoixnm`, `caj-m78r-5e40fefee0-follower-5t3ossk` | Both source-bound replica receipts accepted. |
| `replica-atomic-global` | `healthy` | accepted | `caj-m78r-5e40fefee0-leader-owoixnm`, `caj-m78r-5e40fefee0-follower-5t3ossk` | Both source-bound replica receipts accepted. |
| `denial-all-or-nothing` | `healthy` | accepted | `caj-m78r-5e40fefee0-leader-owoixnm`, `caj-m78r-5e40fefee0-follower-5t3ossk` | Both source-bound replica receipts accepted. |
| `burst-refill-bounded-expiry` | `healthy` | accepted | `caj-m78r-5e40fefee0-leader-owoixnm`, `caj-m78r-5e40fefee0-follower-5t3ossk` | Both source-bound replica receipts accepted. |
| `workspace-deployment-isolation` | `healthy` | accepted | `caj-m78r-5e40fefee0-leader-owoixnm`, `caj-m78r-5e40fefee0-follower-5t3ossk` | Both source-bound replica receipts accepted. |
| `opaque-versioned-keys` | `healthy` | accepted | `caj-m78r-5e40fefee0-leader-owoixnm`, `caj-m78r-5e40fefee0-follower-5t3ossk` | Both source-bound replica receipts accepted. |
| `http-429-retry-after` | `healthy` | accepted | `caj-m78r-5e40fefee0-leader-owoixnm`, `caj-m78r-5e40fefee0-follower-5t3ossk` | Both source-bound replica receipts accepted. |
| `dependency-failure-http-503-no-effect` | `fault` | accepted | `caj-m78r-5e40fefee0-leader-043qwqf`, `caj-m78r-5e40fefee0-follower-88kfwof` | Both source-bound replica receipts accepted. |
| `dependency-health-degraded-no-fallback` | `fault` | accepted | `caj-m78r-5e40fefee0-leader-043qwqf`, `caj-m78r-5e40fefee0-follower-88kfwof` | Both source-bound replica receipts accepted. |
| `dependency-restored-health-and-decision` | `recovery` | accepted | `caj-m78r-5e40fefee0-leader-sv1pyn7`, `caj-m78r-5e40fefee0-follower-nevxrhm` | Both source-bound replica receipts accepted. |

### Execution and failure history

| Phase | Replica | Actual execution | Observed terminal status |
| --- | --- | --- | --- |
| `admission` | `follower` | `caj-m78r-5e40fefee0-follower-39k1y2u` | `Succeeded` |
| `admission` | `leader` | `caj-m78r-5e40fefee0-leader-i5oi4er` | `Succeeded` |
| `fault` | `follower` | `caj-m78r-5e40fefee0-follower-88kfwof` | `Succeeded` |
| `fault` | `leader` | `caj-m78r-5e40fefee0-leader-043qwqf` | `Succeeded` |
| `healthy` | `follower` | `caj-m78r-5e40fefee0-follower-4avj260` | `Failed` |
| `healthy` | `follower` | `caj-m78r-5e40fefee0-follower-5t3ossk` | `Succeeded` |
| `healthy` | `leader` | `caj-m78r-5e40fefee0-leader-miw7flx` | `Stopped` |
| `healthy` | `leader` | `caj-m78r-5e40fefee0-leader-owoixnm` | `Succeeded` |
| `receipts` | `follower` | `caj-m78r-5e40fefee0-follower-87441ry` | `Succeeded` |
| `receipts` | `leader` | `caj-m78r-5e40fefee0-leader-gb4oqjz` | `Succeeded` |
| `recovery` | `follower` | `caj-m78r-5e40fefee0-follower-nevxrhm` | `Succeeded` |
| `recovery` | `leader` | `caj-m78r-5e40fefee0-leader-sv1pyn7` | `Succeeded` |

Healthy dimension results retain their original immutable case contributors, which can precede the later aggregate receipt executions above:

| Dimension | Replica | Original case execution |
| --- | --- | --- |
| `global` | `follower` | `caj-m78r-5e40fefee0-follower-5t3ossk` |
| `global` | `leader` | `caj-m78r-5e40fefee0-leader-owoixnm` |
| `network` | `follower` | `caj-m78r-5e40fefee0-follower-5t3ossk` |
| `network` | `leader` | `caj-m78r-5e40fefee0-leader-owoixnm` |
| `operation` | `follower` | `caj-m78r-5e40fefee0-follower-5t3ossk` |
| `operation` | `leader` | `caj-m78r-5e40fefee0-leader-owoixnm` |
| `provider` | `follower` | `caj-m78r-5e40fefee0-follower-5t3ossk` |
| `provider` | `leader` | `caj-m78r-5e40fefee0-leader-owoixnm` |
| `resource` | `follower` | `caj-m78r-5e40fefee0-follower-5t3ossk` |
| `resource` | `leader` | `caj-m78r-5e40fefee0-leader-owoixnm` |
| `user` | `follower` | `caj-m78r-5e40fefee0-follower-5t3ossk` |
| `user` | `leader` | `caj-m78r-5e40fefee0-leader-owoixnm` |
| `workspace` | `follower` | `caj-m78r-5e40fefee0-follower-5t3ossk` |
| `workspace` | `leader` | `caj-m78r-5e40fefee0-leader-owoixnm` |

Observed failed attempts remain failed historical observations:

- `caj-m78r-5e40fefee0-follower-4avj260`, `healthy`/`follower`: `SharedRateLimitUnavailable`.

Operator failures or uncertain operations remain recorded separately:

| Operation receipt | Operation | Exit/status |
| --- | --- | --- |
| `fault-follower-logs-20261116T193844-8291c2` | `fault-follower-logs` | `1` |
| `fault-leader-logs-20261116T193851-dfef26` | `fault-leader-logs` | `1` |
| `healthy-follower-logs-20261116T193459-4fdfac` | `healthy-follower-logs` | `1` |
| `healthy-leader-logs-20261116T192229-b929fc` | `healthy-leader-logs` | `1` |
| `healthy-leader-logs-20261116T193507-a8fb5d` | `healthy-leader-logs` | `1` |
| `recovery-follower-logs-20261116T194204-cd7e46` | `recovery-follower-logs` | `1` |
| `recovery-leader-logs-20261116T194210-ef551b` | `recovery-leader-logs` | `1` |

### Preserved local recovery and abandoned healthy attempt

Foundation deployment succeeded. Local admission initially rejected the provider display name `East US` because it compared it literally with `eastus`. A separately hash-bound helper normalized case and spaces only for that exact region, retained the other admission gates, and completed admission from the saved deployment readback. Five focused checks accepted the two East US spellings and rejected other regions. The frozen helper was unchanged and the deployment was not repeated.

Healthy follower `caj-m78r-5e40fefee0-follower-4avj260` failed with `SharedRateLimitUnavailable` before its first coordination intent. Leader `caj-m78r-5e40fefee0-leader-miw7flx` waited behind the absent start barrier and was stopped. The underlying exception cause was not retained; these receipts do not establish a Lua or concurrency defect.

Read-only diagnostic `caj-m78r-5e40fefee0-follower-hqtdup2` found all seven original bucket keys absent, the follower intent and start barrier absent, and only the abandoned leader intent/ready records present. Read-only Lua TIME/HMGET checks passed. Recovery `caj-m78r-5e40fefee0-follower-0ros2gm` bound the original values and expired only those two abandoned coordination records; absence was verified. No budget call was repeated and no accepted assertion changed. These diagnostic/recovery observations are not additional acceptance results.

The affected healthy phase resumed with unchanged source, image, assertions and timeouts; accepted admission remained closed. Actual accepted replacement contributors are listed in the assertion and case tables above. The first failed/stopped executions remain historical failures, independently of later accepted results.


### Bound artifacts and cleanup

| Binding | Value |
| --- | --- |
| Approved package SHA-256 | `23c68ba7c8685b9009d590829da5910f941692e9f444748686e79ca993cdf8f5` |
| Source checkpoint | `121048813095714e865fd6e664f0ce8e1989b53b` |
| Injected Redis probe SHA-256 | `f610ff80a42cb3545fc3ce7fa199c76ab217e7684ed5bb6b9819b8dc3baf691e` |
| Retained image/index | `sha256:f498e5aa0f5e44dc7becc92868e1bb989372ef09a3f30d694e89d172eaa66b0a` |
| Preserved approved cleanup runbook SHA-256 | `38cfeb6cd6e706d197e7a689e5080c36fdc6c3007ad14c0c0cbf35ca626cefd9` |
| Cleanup execution | `4fe074eb-a768-4490-824c-1461bb46a178` |
| Cleanup method / actual runbook status | `automation-runbook` / `Completed` |
| `final-results.json` SHA-256 | `fffa9b4269cd19d7694f729697b4652e36e83191cc9c68b22254a18c02f06238` |
| `terminal-receipt.json` SHA-256 | `ee626147e4f7a93eabf17b19e66e9ddcd815307cd1dd5fbb7ed0ca886fbd0b1f` |
| `cleanup-verification.json` SHA-256 | `e3d36bad5516e5c40e0c6aca4ac986d8067afca22db924b0c1029fbbde490c79` |
| `campaign-ledger.json` SHA-256 | `8b6ec07264d95281caba573911a88f3e9509b5ca795ff963000bb77f47294738` |
| `assertion-inventory.json` SHA-256 | `bfdf57053aa18c1a5cb5bcbccca9f988c48eff7d163963b3f190c91f0f273f03` |
| `controller-reuse-spec.json` SHA-256 | `eb4531089c25910eb1cebff990ed704175352622087bb3ae2f1ffce4213adbfe` |
| `controller-wrapper-recovery.json` SHA-256 | `45598487dc688a826142a8227dc7139b8f620ba64ea192cec39b566f08f11a75` |
| `foundation-admission-recovery.json` SHA-256 | `201ffcacd63c353512ebc573518c983343cef8dd6c531e7d20cc840eea5f39a4` |
| `diagnostic-readonly-result.json` SHA-256 | `ebdbd9933b49afca92f85e7e1ecfd1f66d10c117c41a6bc8e0c41201ea26526f` |
| `coordination-recovery-result.json` SHA-256 | `526c8de57b7ace2b7150e3810d3b6200a0054bf0b9fb161b3f6cfaa054e9bb53` |
| `jobs/healthy-leader-2-resumption.json` SHA-256 | `75def1e5662193b505a9f7861e74c1865b05f1fc594e4125bf0cc6ecfc14cbcc` |
| `jobs/healthy-follower-2-resumption.json` SHA-256 | `01a769e513dddcfe1f76bf5d2be0cdf1893496a9d393c6ac0f0d637b1303f8ec` |
| `admission`/`leader` receipt; `caj-m78r-5e40fefee0-leader-i5oi4er` | `30a73f85c955ab2b9ab3733561022d82fa521d8cf38014d23a8c4ecfaf612c69` |
| `admission`/`follower` receipt; `caj-m78r-5e40fefee0-follower-39k1y2u` | `2755159e263365439c0027fcc1a1bf8382192e19b71ed51c117fa008a54fef8e` |
| `healthy`/`leader` receipt; `caj-m78r-5e40fefee0-leader-owoixnm` | `fee024d78a7a96dab2758e580dcfda8635df7b07c1abfb1db72d5e5d6f464282` |
| `healthy`/`follower` receipt; `caj-m78r-5e40fefee0-follower-5t3ossk` | `e5fbbacf1a3b93825e1be8bbc29ae9515b862023fdc33cea5fdf9dd28e21cc3e` |
| `fault`/`leader` receipt; `caj-m78r-5e40fefee0-leader-043qwqf` | `85ef50db545c99289e3873af4fd9f8d8bc70eb583fc8d559a38347da61d40174` |
| `fault`/`follower` receipt; `caj-m78r-5e40fefee0-follower-88kfwof` | `0087d9fd16de12368675c1b8ed7fbde599b23b593ba0ab832264ba73bbe7a48b` |
| `recovery`/`leader` receipt; `caj-m78r-5e40fefee0-leader-sv1pyn7` | `405e81c1d8aeaeb8cf6150f23fed2f897188ef2583a45af0c6223f08c153d484` |
| `recovery`/`follower` receipt; `caj-m78r-5e40fefee0-follower-nevxrhm` | `da65977688804f347c77a28c13d98457d2ab1420197cc555b4d41b64446bb2d1` |

Raw evidence remains ignored under `.runtime/milestone_7_8/redis-regional-20261116/`; it is not published. Final results bind the actual native exports, execution/source/image receipts and cleanup observations listed above. All 18 counters verify target/provider-managed-group, Redis/cache/database/ACL, NSG, network, job, identity, registry, role and schedule/binding absence. The reusable controller, identity, Reader grant and approved published runbook/content are preserved. This is active-resource absence, not physical-erasure or settled-billing evidence.

The existing accepted 1,000-cent-compatible runbook publication was inherited through the renewal-only authority chain; its exact bytes were preserved at final cleanup. This regional campaign performed no new runbook publication. The local controller_gate import failure occurred after the accepted renewal; it was recovered from the saved completed authority evidence without replaying Azure mutations. The cleanup method and actual runbook status are recorded above; no failed runbook is relabeled successful. Earlier failed publication/operation or proof attempts remain in their receipts and history. This finalized regional campaign is not authority for another paid execution.

Approved incremental ceiling: USD 10.00; prior cumulative ceiling: USD 340.89; cumulative ceiling: USD 350.89. These are approved ceilings, not settled charges. Billing remains unsettled. No previous campaign budget is reused.

This reconciliation closes only supported M78-D-002 assertions. Existing observability, durable-worker, broader managed recovery, capacity/failure and consolidated final-validation requirements remain in the milestone checklist. It does not authorize another campaign or milestone.
