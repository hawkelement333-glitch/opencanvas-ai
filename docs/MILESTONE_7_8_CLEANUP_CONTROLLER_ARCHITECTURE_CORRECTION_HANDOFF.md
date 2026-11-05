# Milestone 7.8 cleanup-controller architecture correction handoff

Date: 2026-08-25
Repository state: local source correction only
Controller state: `architecture-corrected-live-execution-not-authorized`

> **2026-08-27 admission correction:** the architecture below is now also
> gated by the exact M78-PG-012 post-boundary absence artifact. Its canonical
> hash is bound through controller selection/configuration, campaign/runtime,
> cleanup parameters and authority, execution authorizations, ledger, and
> terminal receipt. Synthetic fixtures cannot enter live execution. No
> managed-provider absence artifact or Azure authorization was produced.

This handoff records a local architecture correction. It is not evidence that
the controller exists in Azure, is armed, is provider-proved, or is production
ready. No Azure operation, campaign, generation, deployment, or cleanup was
performed for this correction. Milestone 7 and Milestone 7.8 remain incomplete.

## Structural defect

The superseded campaign template created an Automation account inside a
campaign-specific cleanup resource group and instructed that controller to
delete its own group. The runbook could delete its control plane before
terminal readback, and ordinary cleanup necessarily moved the Automation
account into the provider's retained deleted-account inventory. Repeating the
campaign therefore created a create-delete-retain-recreate loop. Publication
ordering fixes and explicit soft-deleted inventory made that defect observable;
they could not make the disposable controller armable.

The production entry path had a second contradiction: regional admission
classified every active Automation account as occupied. A reusable controller
would therefore cause the next campaign to reject the exact account it needed
to adopt.

## Selected architecture

Exactly one architecture is selected: one subscription-bound Azure Automation
controller, provisioned and published once in a stable resource group outside
every campaign target scope.

1. `controller.bicep` is the only template that can create the controller
   resource group, Automation account, runbook, and permanent Reader grant on
   that controller group.
2. `controller.py` exposes a dry-run-by-default one-time bootstrap and readback
   sequence. Any live bootstrap or verification requires a separate, exact,
   expiring controller authorization artifact.
3. Region discovery may adopt only the exact controller name, group, resource
   ID suffix, architecture tags, subscription correlation, script hash, and
   authorization timestamp. When it exists, its established region is the only
   selectable controller region. Drift fails closed.
4. Campaign preparation first requires strict `retained-account-absent`
   evidence for the prior account, then refuses to create a runtime bundle
   until the exact controller identity and bounded authority are adoptable. `capacity-check`
   then proves the permanent Reader grant, published script, and empty complete
   schedule/binding inventories before `scope-create`.
5. `cleanup.bicep` references the controller account and runbook as `existing`.
   It can create only two temporary assignments at the exact target resource
   group: Contributor and Role Based Access Control Administrator.
6. Arming reads the complete schedule and binding collections first. It creates
   one deterministic one-time schedule and one deterministic binding only when
   absent, adopts an exact existing pair, completes an interrupted
   schedule-only state by creating only the binding, and rejects drift,
   duplicates, or a binding without its schedule.
7. The published runbook revalidates the subscription, controller and account
   ownership, executing managed identity, campaign and generation, immutable
   deadline, authority expiry and hash, exact binding parameters, target tags,
   and exact two-role authority before deleting only the target resource group.
8. Ambiguous target deletion succeeds only when authoritative target absence is
   observed. The stable controller is never an ordinary campaign deletion
   target.
9. `cleanup-disarm` deletes the exact binding and schedule, tolerates ambiguous
   delete results only when complete readback proves both collections empty,
   and records a deterministic revocation-evidence hash before residue proof.
10. Residue proof excludes the stable baseline controller from campaign
    residue, but requires exactly that one active controller, zero schedules,
    zero bindings, and no deleted account attributable to the campaign.
    Unrelated deleted-account identities remain observation-only and hashed.

## Why this option is uniquely supported

The repository already had Automation runbook publication, managed identity,
one-time scheduling, exact-scope RBAC, deadline enforcement, complete active and
deleted inventories, and deterministic ledger/readback contracts. Moving that
same controller outside the target scope and separating stable provisioning
from per-campaign authority uses those proved surfaces without introducing a
new platform or provider behavior.

The alternatives are rejected:

- Another disposable Automation account still creates a retained provider
  record and repeats the proved failure.
- A self-deleting controller can lose its schedule, identity, and evidence
  surface before terminal proof.
- A controller inside the target resource group cannot survive target deletion.
- A local caller or CI-only timer cannot survive caller termination and is not
  an independently armed control plane.
- Restoring or purging the retained account depends on an unresolved provider
  gate and would alter protected evidence.
- Logic Apps, Functions, Container Apps, a second subscription, or another
  external scheduler introduces a new service, authorization, cost surface, or
  dependency not supported by the preserved repository evidence.
- Leaving campaign RBAC or schedules indefinitely active violates bounded
  authority, cost, revocation, and deterministic terminal evidence.

## Invariant disposition

| Required invariant                         | Local correction                                                                                                                                     |
| ------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| Arm before target mutation                 | Preparation requires the separately provisioned, published, empty controller; campaign deployment and arming precede billable target deployment.     |
| Outside target scope and survives deletion | Stable controller group is subscription-bound and distinct from the campaign target group.                                                           |
| Survives initiating process                | Azure Automation owns the published runbook and one-time schedule.                                                                                   |
| Exactly one schedule and binding           | Complete collection reads, deterministic names, adoption, duplicate rejection, and zero-count disarm proof.                                          |
| Deterministic reconciliation               | Absent, exact-pair, schedule-only, drift, duplicate, and binding-only states have closed outcomes.                                                   |
| Least privilege and bounded lifetime       | Permanent Reader only on the controller group; temporary two-role grant only on the exact target; deadline plus one-hour authority expiry.           |
| Revalidation before action                 | Subscription, ownership, campaign, generation, identity, schedule, binding parameters, authority, target tags, and roles are checked in the runbook. |
| Retry and ambiguous success                | Exact adoption, schedule-only recovery, idempotent target absence, and readback-authoritative disarm.                                                |
| Revoke and prove                           | Target deletion removes target-scoped RBAC; disarm proves zero schedule and binding and binds the terminal receipt.                                  |
| No ordinary soft-deleted controller record | Ordinary cleanup never deletes the stable Automation account or controller group.                                                                    |
| Cost and deadline                          | USD 50 ceiling, contingency, immutable four-hour deadline, and bounded authority remain unchanged.                                                   |
| Retained evidence untouched                | The existing target retained account and four unrelated records remain read-only and untouched.                                                      |
| M78-PG-012 preserved                       | Deletion instant `2026-08-15T01:09:46.307Z` and absence boundary `2026-09-14T01:09:46.307Z` are unchanged.                                           |
| Separate future authorization              | Controller bootstrap/verify and every live campaign phase require exact expiring authorization artifacts.                                            |

## Future authorization and evidence gates

A future authorization must separately name and approve, in this order:

1. the v3 M78-PG-012 post-boundary GET-only absence verification, producing
   the exact sanitized admission artifact with zero target candidates, full
   pagination, zero current-only records, zero mutations, and each historical
   unrelated baseline observed only as `present-unchanged` or
   `absent-unattributed`;
2. complete read-only regional/provider/policy/inventory discovery;
3. one controller bootstrap or exact-controller adoption in the selected region;
4. published script hash, stable identity, local-auth policy, empty schedule and
   binding inventories, and permanent Reader readback;
5. a new clean-source campaign preparation and exact execution authorization;
   every operation that can enter failure cleanup must authorize both that
   operation and `cleanup`, including readback failure after scope creation;
6. live failure injection for interrupted bootstrap, publication failure,
   schedule-only recovery, duplicate invocation, expired authority, cleanup
   failure, ambiguous deletion, disarm failure, and evidence failure;
7. one bounded managed campaign, target zero-residue proof, schedule/binding
   revocation proof, cost evidence, and all still-open managed PostgreSQL
   evidence contracts.

None of those live gates is authorized or satisfied by this local correction.
Migration `0030` is not required and remains absent.
