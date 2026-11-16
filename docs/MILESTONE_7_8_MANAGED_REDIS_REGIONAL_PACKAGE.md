# M78-D-002 East US managed Redis package

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
