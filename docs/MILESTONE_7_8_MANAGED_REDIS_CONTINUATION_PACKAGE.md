# M78-D-002 managed Redis continuation package

Current result — 2026-11-16 UTC: **M78-D-002 remains open: 0 accepted, 0 failed, 17 unproved out of 17 existing assertions.** All 18 cleanup counters are zero; the reusable controller is preserved and the campaign ledger finalized. PostgreSQL and M78-D-001 remain closed. Milestone 7.8 remains incomplete. Billing remains **unsettled**.
See the [managed campaign reconciliation](#managed-campaign-reconciliation).

## Actual foundation failure and completed cleanup

Unlike the earlier expired-window attempt, this continuation dispatched its
foundation at 2026-11-16 18:28:39 UTC. Operation
`foundation-deploy-20261116T182839-0efdc6` returned `InvalidTemplateDeployment`
with two provider preflight errors:

- `CacheCapacityUnavailable`: **Balanced_B0 is not currently available in
  Canada Central due to insufficient capacity.**
- `InvalidRequestParameterWithDetails`: the Container Apps API rejected the
  literal `appLogsConfiguration.destination: 'none'` value.

The logging correction uses JSON `null`, matching
[Microsoft's CLI payload translation](https://github.com/Azure/azure-cli-extensions/blob/main/src/containerapp/azext_containerapp/containerapp_env_decorator.py).
The revised provider-contract test failed on the old literal and passed after
the correction, including Bicep compilation. Validation of the corrected B0
template then reported **only** `CacheCapacityUnavailable`. Validation-only
checks of B1 and B3 in Canada Central returned the same capacity error; neither
was provisioned. No Redis adapter, assertion or image change was made.

The deployment readback was `DeploymentNotFound`; a successful deployment-list
query returned empty, the target inventory was empty, and exact environment and
expected provider-managed-group absence were recorded. The failed foundation
was reconciled as **failed with no resource effects**, not described as an
undispatched operation. Therefore all **17 managed assertions remain unproved**;
there are no contributing probe execution IDs.

Cleanup job **`f56269ef-0ba3-4cad-acbf-f5533807ffa7`** completed at
2026-11-16 18:42:23 UTC using the corrected published runbook. All **18 residue
counters are zero**, including campaign binding/schedule absence. Controller
identity, Reader, bootstrap history and accepted content hash
`38cfeb6cd6e706d197e7a689e5080c36fdc6c3007ad14c0c0cbf35ca626cefd9`
are preserved. The ledger is finalized; this attempt is closed.

Private evidence under `.runtime/milestone_7_8/redis-continuation-20261116/`:

| Evidence | Meaning |
| --- | --- |
| `operations/foundation-deploy-20261116T182839-0efdc6-result.json` | Exact original provider errors |
| Matching `-reconciliation.json` and its bound provider reads | No deployment/resources created; outcome reconciled |
| `corrected-foundation-validation-result.json` | Logging fixed; B0 regional capacity still unavailable |
| `candidate-b1-validation-result.json`, `candidate-b3-validation-result.json` | Candidate validation only; same regional capacity rejection |
| `cleanup-no-environment-evidence.json` | Actual predelete absence after reconciled failed preflight; no invented environment attribution |
| `cleanup-verification.json`, `final-results.json`, `terminal-receipt.json` | Verified cleanup and 0 accepted / 0 failed / 17 unproved classification |

Final-results SHA-256:
`49b50a13980e439ab267968c7c57bb1718776131d2566d76eae386488f1d52e2`.
Terminal-receipt SHA-256:
`f225f19456404d4a77e1d84bcc4ab0ddf3e15999991e760fde6266c6981ac50e`.
Billing remains **unsettled**; absence of Redis resources is not a claim of zero
controller charges. The user authorized preparation of another region, subject
to existing residency requirements and a separate exact spending package.

## Historical preparation package

Prepared from recovery checkpoint
`cb8ffa8d65d926625def7141a0b8765034293387` on
`milestone-7-8-production-readiness-audit-local`.
**Execution and spending are not authorized by this document.**
M78-D-002 remains open: **0 accepted, 0 failed, 17 unproved**.
PostgreSQL and M78-D-001 remain closed. Billing remains **unsettled**.

## Why a continuation is needed

The [prior diagnosis and receipts](MILESTONE_7_8_MANAGED_REDIS_EXECUTION_PACKAGE.md#exact-blocker-and-minimum-continuation)
show that no Redis workload or probe executed before the approved provisioning
window expired. The separate scheduled cleanup failed at parameter binding
because its published runbook rejected the approved 1,000-cent ceiling.
The subsequent explicitly approved direct cleanup verified **18 zero residue
counters**, preserved the controller and finalized that attempt's ledger.
Its terminal receipt SHA-256 is
`990d4dd911575d719539d8d9b6c1464936aa3bf96f733ac99aa1233bae4c3d2e`.
This continuation uses a new campaign and scope; the finalized attempt is not
reopened and its expired authority is not reused.

The completed local correction changes only the cleanup runbook allowlist to
`ValidateSet(1000, 5000, 5651)`. The old 1,000-cent rejection was reproduced
before any mocked read/deletion. Six focused cases then passed: accept
1,000/5,000/5,651; reject 999/1,001/5,652. The live runbook still needs the
explicitly scoped publication below. No managed evidence supports changing the
Redis adapter, acceptance criteria or image inputs.

## Frozen inputs and reuse

The private package is retained under
`.runtime/milestone_7_8/redis-continuation-20261116/`. Its `package-review.json`
binds the final source checkpoint, this document, exact commands, window,
cost estimate, prepared cleanup parameters, execution helpers and reused
evidence. The approval must name that package's digest.

| Binding | SHA-256 / digest |
| --- | --- |
| Injected Redis probe | `f610ff80a42cb3545fc3ce7fa199c76ab217e7684ed5bb6b9819b8dc3baf691e` |
| Redis infrastructure template | `b58398d50b034a4ad65144d920ce2a048994b16b1848327791fcdc6a67c7f4ee` |
| Corrected cleanup runbook working bytes | `38cfeb6cd6e706d197e7a689e5080c36fdc6c3007ad14c0c0cbf35ca626cefd9` |
| Retained image/index | `sha256:f498e5aa0f5e44dc7becc92868e1bb989372ef09a3f30d694e89d172eaa66b0a` |
| Retained runtime image | `sha256:241c55acd6e169546969b1c36f58806a146e3562f69011f5a3efc438a71eb769` |
| Canonical image inputs | `d94e350754821b1172a9b4452466391053e0221d3095e336e43379f6f33c312f` |

Reuse the 27 passing probe tests, six infrastructure checks, Bicep compilation,
focused Ruff results and retained-image provenance. New focused validation covers
controller publication integration, exact prepared cleanup parameter binding,
cleanup before environment creation and retained-receipt metadata. The copied
receipt helper now uses the unchanged probe's actual `execution_id` field for
reused receipts; it still requires the original contributing execution. This
local helper correction did not cause the prior unexecuted result.
The runbook is outside image build inputs; **zero image
builds** are included. Source bytes and the clean checkpoint are checked again
before publication; a line-ending change requires rebinding, not an assumed hash.

## Scope and ordered operations

The new isolated Canada Central target is **`rg-m78-395e684ab3-target`**, campaign
`m78-redis-395e684ab336`, generation `g1-40a69271a3d6`. It contains one HA Balanced B0 Managed Redis cache, its default
database, two Entra access assignments, two managed identities, two independent
retained-image Container Apps jobs, one internal Consumption environment,
temporary Premium ACR, private endpoints, private DNS, VNet/subnets and an NSG.
Public Redis access and access-key authentication remain disabled. No
PostgreSQL, object/scanner, Log Analytics/AMPLS, extra capacity or other milestone
work is included.

1. Verify the new target is absent, the previous cleanup remains supported by
   its terminal evidence, and the preserved controller has no active campaign
   binding/schedule. Check the exact source/image and current window.
2. Renew only the existing controller's three deadline tags through
   `activate_controller.py` and the retained renewal workflow. Preserve its
   identity, Reader assignment, bootstrap tags and unrelated properties.
3. Use the existing `controller_publication.py` workflow to replace and publish
   only `Remove-M78Campaign` with the corrected, hash-bound source. The publication
   plan is derived from the **actual renewed-controller receipt**, not a
   fabricated future receipt. The frozen publication specification limits it to
   the exact content-write and publish requests. Read back and validate the
   published content, controller preservation and resulting authority evidence.
4. Validate all prepared cleanup parameters against the actual corrected
   PowerShell parameter contract. Arm the target's two cleanup grants and exact
   one-time schedule/binding only against the accepted publication evidence.
   Read them back before any paid deployment. Bootstrap tags remain historical;
   final content verification uses the newly accepted publication hash.
5. Run `execute.py foundation`, verify the private managed resource configuration,
   then transfer the retained image and run `execute.py workload`. Exact-IP ACR
   access is capped at **20 minutes cumulatively**, including recovery, and is
   restored in a `finally` path. A changed operator address must be reconciled
   before opening access; arbitrary public access is not authorized.
6. Run the existing independent leader/follower pairs for `admission` and
   `healthy`. Continue only with accepted, source/identity/execution-bound
   observations. Preserve complete console chunks and actual terminal status.
7. Apply only the exact NSG rule denying Redis TCP port 10000, run the `fault`
   pair, and unconditionally restore that rule. Then run the `recovery` pair.
   Preserve accepted observations and reconcile uncertain writes before retrying
   only the affected operation. Do not repeat unchanged suites or successful
   managed mutations.
8. Export receipts where available, stop proof at the deadline, reconcile any
   existing cleanup job before starting another, and complete verified cleanup.
   Failed/missing exports do not delay teardown. The exact direct fallback is
   covered within the cleanup window if the scheduled runbook demonstrably
   fails or stalls; preserve its actual status and evidence.

The exact CLI argument arrays, resource IDs, request bodies, identity bindings,
source hashes and guarded helper entrypoints are private package inputs. No
secret, raw provider response or private operator address is published here.

## Existing acceptance and stop conditions

The original [17-assertion inventory](MILESTONE_7_8_MANAGED_REDIS_EXECUTION_PACKAGE.md#managed-campaign-reconciliation)
is unchanged: two admission assertions, twelve healthy/atomic-limit assertions,
two dependency-failure assertions and one recovery assertion. Both independent
replica receipts must match their actual managed identities, source/image,
campaign/run and execution IDs. An assertion is accepted only on its required
managed evidence; a local test or successful job status alone is insufficient.

The production shared-limit adapter, Lua logic and HTTP enforcement dependency
remain unchanged. Healthy proof covers all seven shared-limit dimensions,
all-or-nothing denial, refill/expiry, deployment/workspace isolation, opaque keys
and HTTP 429/Retry-After. Fault proof requires HTTP 503 without protected effects
and degraded dependency health without fallback. Recovery requires restored
health and the protected decision. No new acceptance requirement is introduced.

Before starting a pair, require its full 1,200-second runtime plus the retained
120-second dispatch reserve. Stop new proof at the deadline. Preserve successful
results; correct only demonstrated failures within this scope and the aggregate
ceiling. Do not promise completion if the managed evidence fails.

## Cost and proposed window

| Bound | Proposal |
| --- | --- |
| Incremental forecast, including 25% contingency | USD **7.9603** |
| New incremental ceiling | USD **10.00** |
| Prior cumulative approved ceiling, unsettled | USD **330.89** |
| Proposed cumulative ceiling | USD **340.89** |
| Earliest paid start | November 16, 2026 **18:00 UTC / 12:00 CST**, only after explicit approval |
| Begin provisioning by | November 16, 2026 **20:00 UTC / 14:00 CST** |
| Stop proof and scheduled cleanup | November 17, 2026 **00:00 UTC / November 16, 18:00 CST** |
| Runbook binding expiry | November 17, 2026 **01:00 UTC / November 16, 19:00 CST** |
| Cleanup/controller authority ends | November 17, 2026 **02:00 UTC / November 16, 20:00 CST** |

The retained same-day retail-meter estimate prices eight hours including cleanup
reserve, two HA Redis nodes, both jobs continuously, a full day of ACR, two
DNS-zone months, private networking and controller runtime reserve.
The local/publication correction creates no image build. The new estimate binds
the prior finalized ledger and preserves all previous ceilings and forecasts;
none is a settled charge or an unused allowance available for this campaign.
The prior failed Automation execution may still incur charges. Billing remains
unsettled throughout.

The target and schedule may be created only inside the provisioning window.
If approval or execution misses the cutoff, do not create an empty target or
arm a campaign merely to wait. Reconcile current state and prepare a
new concrete window before paid execution. The documented window is a bound,
not authority by itself.

## Cleanup and checkpoint publication

Verify the same **18 zero residue counters**: target and provider-managed groups,
target resources and role assignments, campaign binding and schedule, Redis
cache/database/access assignments, NSG/rules, registry, jobs, environment,
identities, private endpoints, DNS zones and VNet. Require exact Redis child
404s and complete scoped inventory; authentication/transport errors are not
absence. Preserve the reusable controller, identity, Reader assignment,
bootstrap history and newly accepted published content. Provider registration
is preserved. Partial provisioning is cleaned within the same authority.

Keep a compact private recovery checkpoint with active operations, contributing
executions, accepted assertions, evidence locations, deadlines and exact next
action. Finalize the ledger only after verified cleanup. Update the checklist,
register and handoff with actual results, keeping M78-D-002 open unless all 17
existing assertions are accepted.

The user authorizes normal commits and pushes of useful sanitized recovery
checkpoints as well as completed areas, with remote-SHA verification. Such a
commit does not imply acceptance or authorize Azure operations. Preserve all
five protected stashes, unrelated work and Git history; raw `.runtime` evidence
and secrets remain outside Git. Do not force-push, rewrite history or merge.

<!-- M78-D-002 continuation terminal documentation reconciliation -->
## Managed campaign reconciliation

Reconciled 2026-11-16 UTC after verified cleanup and ledger finalization.

**M78-D-002 remains open: 0 accepted, 0 failed, 17 unproved out of 17 existing assertions.** All 18 cleanup counters are zero; the reusable controller is preserved and the campaign ledger finalized. PostgreSQL and M78-D-001 remain closed. Milestone 7.8 remains incomplete. Billing remains **unsettled**.

The [prior Redis attempt](MILESTONE_7_8_MANAGED_REDIS_EXECUTION_PACKAGE.md#managed-campaign-reconciliation) remains finalized history: 0 accepted, 0 failed, 17 unproved with its separate verified cleanup. The preparation text above is retained historical scope, not authority for another run. Accepted results retain their actual contributing execution IDs. Failed and uncertain attempts remain history; cleanup does not turn them into accepted proof.

| Existing assertion | Phase | Result | Actual contributing executions | Missing evidence or work |
| --- | --- | --- | --- | --- |
| `managed-entra-private-tls` | `admission` | unproved | None accepted | Missing accepted leader and follower replica evidence for this assertion. |
| `foreign-prefix-acl-denied` | `admission` | unproved | None accepted | Missing accepted leader and follower replica evidence for this assertion. |
| `replica-atomic-network` | `healthy` | unproved | None accepted | Missing accepted leader and follower replica evidence for this assertion. |
| `replica-atomic-user` | `healthy` | unproved | None accepted | Missing accepted leader and follower replica evidence for this assertion. |
| `replica-atomic-workspace` | `healthy` | unproved | None accepted | Missing accepted leader and follower replica evidence for this assertion. |
| `replica-atomic-resource` | `healthy` | unproved | None accepted | Missing accepted leader and follower replica evidence for this assertion. |
| `replica-atomic-operation` | `healthy` | unproved | None accepted | Missing accepted leader and follower replica evidence for this assertion. |
| `replica-atomic-provider` | `healthy` | unproved | None accepted | Missing accepted leader and follower replica evidence for this assertion. |
| `replica-atomic-global` | `healthy` | unproved | None accepted | Missing accepted leader and follower replica evidence for this assertion. |
| `denial-all-or-nothing` | `healthy` | unproved | None accepted | Missing accepted leader and follower replica evidence for this assertion. |
| `burst-refill-bounded-expiry` | `healthy` | unproved | None accepted | Missing accepted leader and follower replica evidence for this assertion. |
| `workspace-deployment-isolation` | `healthy` | unproved | None accepted | Missing accepted leader and follower replica evidence for this assertion. |
| `opaque-versioned-keys` | `healthy` | unproved | None accepted | Missing accepted leader and follower replica evidence for this assertion. |
| `http-429-retry-after` | `healthy` | unproved | None accepted | Missing accepted leader and follower replica evidence for this assertion. |
| `dependency-failure-http-503-no-effect` | `fault` | unproved | None accepted | Missing accepted leader and follower replica evidence for this assertion. |
| `dependency-health-degraded-no-fallback` | `fault` | unproved | None accepted | Missing accepted leader and follower replica evidence for this assertion. |
| `dependency-restored-health-and-decision` | `recovery` | unproved | None accepted | Missing accepted leader and follower replica evidence for this assertion. |

### Execution and failure history

| Phase | Replica | Actual execution | Observed terminal status |
| --- | --- | --- | --- |
| No managed execution | — | — | No managed assertion accepted |

No probe failure marker was recorded in the finalized evidence. Execution statuses above retain any stopped or unsuccessful provider execution.

Operator failures or uncertain operations remain recorded separately:

| Operation receipt | Operation | Exit/status |
| --- | --- | --- |
| `foundation-deploy-20261116T182839-0efdc6` | `foundation-deploy` | `1` |
| `foundation-readback-20261116T182946-e1f27a` | `foundation-readback` | `3` |

### Bound artifacts and cleanup

| Binding | Value |
| --- | --- |
| Approved package SHA-256 | `1560635160517abb5c109fd80b0f0f72648892e3d7c412cb400db8c15b35e6ff` |
| Source checkpoint | `eecc9a32f8f3ed31bd7e3bd9b00d09428c83e7a0` |
| Injected Redis probe SHA-256 | `f610ff80a42cb3545fc3ce7fa199c76ab217e7684ed5bb6b9819b8dc3baf691e` |
| Retained image/index | `sha256:f498e5aa0f5e44dc7becc92868e1bb989372ef09a3f30d694e89d172eaa66b0a` |
| Preserved approved cleanup runbook SHA-256 | `38cfeb6cd6e706d197e7a689e5080c36fdc6c3007ad14c0c0cbf35ca626cefd9` |
| Cleanup execution | `f56269ef-0ba3-4cad-acbf-f5533807ffa7` |
| Cleanup method / actual runbook status | `automation-runbook` / `Completed` |
| `final-results.json` SHA-256 | `49b50a13980e439ab267968c7c57bb1718776131d2566d76eae386488f1d52e2` |
| `terminal-receipt.json` SHA-256 | `f225f19456404d4a77e1d84bcc4ab0ddf3e15999991e760fde6266c6981ac50e` |
| `cleanup-verification.json` SHA-256 | `77e0cb8db26ef785b187c195b26a2a15b711cd35b08d4e609065abd54dd0fa9a` |
| `campaign-ledger.json` SHA-256 | `0db24fd24258de37553ae7265be4214315defb8dda416983f95e691e657ee014` |
| `assertion-inventory.json` SHA-256 | `bfdf57053aa18c1a5cb5bcbccca9f988c48eff7d163963b3f190c91f0f273f03` |

Raw evidence remains ignored under `.runtime/milestone_7_8/redis-continuation-20261116/`; it is not published. Final results bind the actual native exports, execution/source/image receipts and cleanup observations listed above. All 18 counters verify target/provider-managed-group, Redis/cache/database/ACL, NSG, network, job, identity, registry, role and schedule/binding absence. The reusable controller, identity, Reader grant and approved published runbook/content are preserved. This is active-resource absence, not physical-erasure or settled-billing evidence.

The corrected 1,000-cent-compatible runbook publication was accepted and its exact bytes were preserved at final cleanup. The cleanup method and actual runbook status are recorded above; no failed runbook is relabeled successful. Earlier failed publication/operation or proof attempts remain in their receipts and history. This finalized continuation is not authority for another paid execution.

Approved incremental ceiling: USD 10.00; prior cumulative ceiling: USD 330.89; cumulative ceiling: USD 340.89. These are approved ceilings, not settled charges. Billing remains unsettled. No previous campaign budget is reused.

This reconciliation closes only supported M78-D-002 assertions. Existing observability, durable-worker, broader managed recovery, capacity/failure and consolidated final-validation requirements remain in the milestone checklist. It does not authorize another campaign or milestone.
