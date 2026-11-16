# M78-D-002 managed Redis execution package

Current result — 2026-11-16 UTC: **M78-D-002 remains open: 0 accepted, 0 failed, 17 unproved out of 17 existing assertions.** All 18 cleanup counters are zero; the reusable controller is preserved and the campaign ledger finalized. PostgreSQL and M78-D-001 remain closed. Milestone 7.8 remains incomplete. Billing remains **unsettled**.
See the [managed campaign reconciliation](#managed-campaign-reconciliation).

## Exact blocker and minimum continuation

**No managed Redis assertion failed: none executed.** The next planned operation,
`execute.py foundation`, was never dispatched. Its retained guard requires the
current time to be between the paid-start and provisioning-cutoff timestamps.
The original cutoff was 2026-11-16 09:00 UTC (03:00 CST); after waiting for the
07:00 UTC permitted start, execution was observed again at 17:15:51 UTC, already
past both that cutoff and the 15:00 UTC cleanup-authority expiry. There is no
retained failed Redis connection, ACL, Lua, Bicep deployment or probe execution
to diagnose. The cause of the elapsed session/clock gap is not established by
the retained campaign receipts. Expiry prevented starting the proof; it must
not be attributed to a Redis service defect.

The independently observed cleanup error was the scheduled
`Remove-M78Campaign` job `ab6e6978-761c-4c99-8645-fc79272247e1`, which rejected
`CostCeilingCents=1000` during PowerShell parameter binding:

> Cannot validate argument on parameter 'CostCeilingCents'. The argument "1000" does not belong to the set "5000,5651" specified by the ValidateSet attribute.

It failed before the runbook body, leaving the empty target and cleanup bindings.
The separately approved direct cleanup subsequently removed those leftovers and
verified all 18 counters zero. The failure remains in history; it is not an
assertion failure and is not reported as a successful Automation execution.

Retained diagnosis evidence under `.runtime/milestone_7_8/redis-20261116/`:

| Evidence | What it establishes |
| --- | --- |
| `window.json`, `execution-approval.json`, archived `execute.py` | Original exact authority window and foundation dispatch guard |
| `operations/`, `final-results.json` | No foundation/workload/probe dispatch; all 17 assertions unproved, no contributing execution IDs |
| `expired-window-reconciliation.json`, `expired-window-readbacks/candidate-job-d11a0fe1.json` | Native failed-job status, exact parameter-binding exception and empty target inventory |
| `expired-cleanup-operations/`, `cleanup-verification.json`, `terminal-receipt.json` | Five exact approved DELETE operations, authoritative absence readbacks, 18 zero counters and controller preservation |
| `approved-inputs/`, `focused-validation.json` | Frozen original inputs and reusable passing local probe/template checks |

The smallest code correction is the already tested one-line addition of `1000`
to `ValidateSet(1000, 5000, 5651)` in the cleanup runbook. No Redis adapter,
acceptance threshold or retained image change is supported by these observations.
The published controller still has the old allowlist. Before new paid proof,
prepare one fresh scope/window package, renew the preserved controller, publish
and verify the corrected content through the existing publication workflow,
validate the exact cleanup parameters against that content, and then arm the
campaign. Do not reopen this finalized attempt or borrow its expired authority.
The continuation must bind publication evidence correctly when arming cleanup
and verifying the final controller content. Reuse the existing 17-assertion
probe, template, retained image and valid focused tests.

This recovery checkpoint is authorized for normal commit/push while M78-D-002
remains incomplete. Publication of source is not managed acceptance or Azure
execution authority. A new paid continuation requires its concrete package and
separate approval because the prior paid window has expired.

## Historical preparation package

Prepared 2026-11-16 UTC at `2de5ed04fd965e1a65f0536b93c13019cbf8fde4` on
`milestone-7-8-production-readiness-audit-local`. **Approved window expired;
cleanup recovery requires a new bounded authority window.** The original package
below is retained as history; its frozen inputs remain in private
`.runtime/milestone_7_8/redis-20261116/approved-inputs/`.
M78-D-002 remains open: **0 accepted, 0 failed, 17 unproved** managed assertions.
PostgreSQL and M78-D-001 remain closed. Milestone 7.8 remains incomplete.
Billing remains **unsettled**. No Redis/workload provisioning was dispatched.
Controller renewal, empty target creation, two target grants, cleanup scheduling
and the Redis provider registration occurred under the original approval.
See [expired-window reconciliation](#expired-window-reconciliation-and-cleanup-decision).

## Existing requirement and retained evidence

The [existing checklist](MILESTONE_7_IMPLEMENTATION_PLAN.md#78-completion-checklist-reconciliation--2026-11-15)
and [M78-D-002 debt](MILESTONE_7_8_DEFECT_REGISTER.md#evidence-debts-routed-to-later-audit-surfaces)
require application-to-managed-Redis evidence for atomic shared limits across
replicas and safe dependency failure. The [operating runbook](DURABLE_WORK_SHARED_LIMITS_RUNBOOK.md)
and [7.4 contract](MILESTONE_7_4_DURABLE_QUEUES_SHARED_LIMITS_HANDOFF.md#shared-limit-contract)
define the observations below; this package adds no broader capacity, telemetry,
durable-worker or disaster-recovery campaign.

Reuse the earlier [managed-store prerequisite](MILESTONE_7_4_DURABLE_QUEUES_SHARED_LIMITS_HANDOFF.md#managed-store-prerequisite-evidence),
the local shared-limit/Entra/recovery adapter tests and the retained passing
63-test durable/shared-limit/recovery/governance shard. The prerequisite proved
the provider contract, not the current application adapter. Its raw Redis
campaign receipts were not located in the scoped retained inventory; the
documented handoff remains the available historical record. Local memory and
mocked identity tests cannot replace the missing managed observations.

## Exact change and image reuse

New external probe `infra/milestone_7_8/managed_redis_probe.py` uses the unchanged
`build_shared_rate_limit_service`, `RedisAtomicRateLimitStore`, Entra token path,
Lua implementation and production HTTP `_enforce_shared` dependency. It runs
real staging Settings validators with inert unrelated endpoints. It does not
start application lifespan or connect to unrelated dependencies. A synthetic
protected HTTP fixture measures the production limiter's 200/429/503 decisions
and verifies a denied request produces no protected effect. Limiter dependency
health is recorded; full-platform readiness is not claimed.

Two separate Container Apps jobs, each with its own managed identity, share
only the campaign HMAC secret, deployment and managed Redis namespace. They
record actual execution IDs and identity hashes. Redis control barriers and
immutable receipts use a separate, explicitly allowed campaign prefix. A lost
write response is reconciled by reading the exact key; accepted phases and
uncertain mutations are never blindly repeated.

The frozen 7.7 Redis template is not deployable for this scope: it has old
names/regions and `~mobius:v1:*`, while current production keys use
`namespace:rl:v1:{limits}:...`. The new narrow template reuses its private
Redis pattern with fresh names, Canada Central and exact current prefixes.
It grants only `PING`, `EVAL`, `TIME`, `HMGET`, `HSET`, `PEXPIRE`, `GET`, `SET`,
`PTTL` and `EXISTS` under the two campaign prefixes. Foreign-prefix access must
actually fail with `NOPERM`. The old template/history and production code remain
unchanged.

The retained OCI image is reused with **zero new builds**:

| Binding | Value |
| --- | --- |
| Source checkpoint | `2de5ed04fd965e1a65f0536b93c13019cbf8fde4` |
| Retained index/image | `sha256:f498e5aa0f5e44dc7becc92868e1bb989372ef09a3f30d694e89d172eaa66b0a` |
| Runtime manifest | `sha256:241c55acd6e169546969b1c36f58806a146e3562f69011f5a3efc438a71eb769` |
| Canonical build inputs | `d94e350754821b1172a9b4452466391053e0221d3095e336e43379f6f33c312f` |
| Retained archive SHA-256 | `25d46785b855429dccdb7a6877976fb6874407a8ddab17ee8124a5c3c168e7c1` |
| Injected Redis probe SHA-256 | `f610ff80a42cb3545fc3ce7fa199c76ab217e7684ed5bb6b9819b8dc3baf691e` |
| Redis template SHA-256 | `b58398d50b034a4ad65144d920ce2a048994b16b1848327791fcdc6a67c7f4ee` |

Current canonical inputs match the retained corrected image. The source verifier
hashes the injected probe before execution. Exact probe/template/test/helper
hashes, actual source checkpoint, archive provenance and the complete package
digest are in private `package-review.json`. No source/image ID or successful
managed execution is fabricated in advance.

## Resource scope and dependencies

One isolated group: **`rg-m78-08bb3291ca-target`**, Canada Central.

- One `Balanced_B0` Azure Managed Redis cache, HA enabled, default database,
  `NoCluster`, `NoEviction`, no modules, encrypted client protocol, minimum
  TLS 1.2, access-key authentication and public access disabled.
- Two user-assigned identities, two exact Redis access assignments and two
  registry pull grants. No custom ARM role definitions.
- One private Premium ACR, one internal Consumption Container Apps environment,
  two manual jobs (`leader`/`follower`), each 0.5 vCPU/1 GiB, one active execution
  per job, no automatic replica retries, 1,200-second replica timeout.
- One VNet, one NSG, two private endpoints and two private DNS zones/links.
  No PostgreSQL, object storage, Defender scanner, Log Analytics or AMPLS.
- Existing reusable cleanup controller, exact target-scoped cleanup grants,
  new one-time schedule/binding and three controller deadline-tag updates.
  Published runbook, controller identity and existing Reader grant are preserved.

Azure's [custom ACL contract](https://learn.microsoft.com/en-us/azure/redis/configure-access-permissions)
requires API `2026-05-01-preview` or later and excludes module-enabled instances.
The template pins that API and no modules. [Private Link](https://learn.microsoft.com/en-us/azure/redis/private-link)
is the network path. Regional availability does not guarantee current capacity;
a provider rejection is preserved, reconciled and cleaned up, not silently
converted to another SKU/region or a wider approval.

Temporary ACR access is restricted to the privately recorded current operator
IPv4 `/32`, for at most **20 minutes cumulative**, with five minutes reserved
for exact original-network restoration. There is no Redis public-access
exception. Verify pushed digest, restore and read back the original private
network settings in `finally`, then log out of only this registry. Uncertain
restoration stops proof and triggers exact scoped cleanup.

## Missing managed observations and acceptance

The executable inventory contains **17 assertions**, currently all **unproved**.
Both replicas must provide accepted, source-bound receipts and actual successful
terminal executions for each phase. Do not count replica copies twice.

| Phase | Assertions | Required managed evidence |
| --- | ---: | --- |
| Admission | 2 | Actual private DNS/TLS and Entra path; foreign-prefix ACL denial on both identities |
| Healthy replicas | 12 | Seven atomic budgets (network, user, workspace, resource, operation, provider, global); all-or-nothing denial; burst/refill/expiry/reset; workspace/deployment isolation; opaque versioned keys; production HTTP 429 with bounded Retry-After |
| Controlled dependency failure | 2 | Protected HTTP 503 and zero protected effects; limiter health false, bounded completion and real Redis store retained with no local fallback |
| Recovery | 1 | Exact fault removed, limiter health restored and one bounded successful protected decision on each replica |

For each of the six explicit dimensions, the two jobs concurrently submit
25 decisions each against a shared budget of 17: exactly 17 allows, 33 denials,
zero errors and no refill token in the observed server-time interval. The
global emergency case consumes the whole ceiling per request, requiring exactly
one winner before refill. The probe checks independent executions/identities
and exact campaign, run, source and image bindings before accepting aggregates.

After healthy proof is accepted and both jobs terminate, inject only outbound
TCP port 10000 denial on the exact campaign NSG, limited to VirtualNetwork
source/destination. Read back the exact rule. Start fresh fault executions so
old TCP connections cannot mask the fault. Require 503 within the probe's
six-second bound, `Retry-After: 1`, no protected effect and unhealthy limiter.
Remove the exact rule in `finally` and verify its absence before recovery.
The fault does not block identity, ACR or management traffic. Fault failure
still requires restoration and cleanup; it does not authorize weakening checks.

Receipts bind the actual fault/readback and restoration hashes. Successful
recovery imports the captured fault receipt into immutable Redis evidence.
Accepted proof remains accepted through any later failed phase. Report every
assertion as accepted, failed or unproved from actual evidence; cleanup and
local checks do not establish managed acceptance.

## Exact execution package and order

Private folder: `.runtime/milestone_7_8/redis-20261116/`.
`command-manifest.json` contains exact ARM URLs, bodies and CLI argument arrays;
all private identifiers and credentials remain outside Git. Commands below are
relative to this folder and use the existing Azure CLI bundled Python.

1. Record the user's separate approval in `execution-approval.json`, bound to
   the frozen package hash, exact scope, ceilings and deadlines. No such
   authority file exists during preparation. `approval-template.json` is false
   and is not authority. Verify package bytes and retained image bindings.
2. `activate_controller.py`: read the exact controller, validate its current
   identity/roles/content/tags, renew only the three deadline tags, reconcile
   provider readbacks. `arm_cleanup.py`: verify target absence, create only the
   group/grants, arm and read back exact schedule/binding before paid resources.
3. `execute.py foundation`: verify tags/grants/window, deploy the prepared
   template, require actual successful deployment, verify Redis policy,
   assignments, private endpoints and internal environment. Preserve the actual
   provider-managed infrastructure-group attribution before deletion.
4. `transfer_retained_image.py`: transfer the existing image under the bounded
   exact-IP window and verify restoration/digest. `execute.py workload` derives
   source-bound job parameters from verified foundation outputs and deploys
   the two jobs. The HMAC secret is a secure job secret, not a URL or log value.
5. `run_pair.py admission` verifies collector readiness, starts each exact job
   sequentially and immediately launches its read-only console/status collector
   before starting the other job. It accepts admission only after both receipts
   and terminal states validate. No detached proof or automatic retry occurs.
6. `run_pair.py healthy` uses the same fixed run UUID, captures both jobs and
   accepts only their bound aggregate. No second fixture namespace
   or rerun of accepted observations is implicit.
7. `execute.py fault-apply`; `run_pair.py fault`; accept only actual
   evidence. Always run `execute.py fault-restore`, including on a failed check.
   Run `run_pair.py recovery` only after accepted fault and verified
   restoration; accept the recovery phase.
8. Optionally run `run_pair.py receipts` to export immutable Redis receipts and
   case intents/results for reconciliation. `execute.py reconcile` validates
   all phase contributions and writes managed-proof results. Missing export
   never delays cleanup; retained local source-bound receipts are required.
9. `start_final_cleanup.py`, `poll_cleanup.py`, `verify_final_cleanup.py`:
   reconcile exact active executions and any existing scheduled cleanup job,
   perform teardown, verify all residue and preservation checks, then disarm
   only the campaign binding/schedule. A documented failed/stuck runbook may
   use `start_final_cleanup.py --direct` within the same exact scope/deadline;
   preserve its history and verify with `verify_final_cleanup.py --direct`.

Console evidence uses gzip/base64 chunks and a full raw SHA-256. A bounded
120-second receipt grace allows capture while the job is active, because this
package has no log-retention workspace. Require complete chunks, matching
bindings/hash and actual terminal success. Missing/truncated output is unproved,
never a reason to rerun successful mutations. Preserve Redis receipts before
teardown and keep fault console evidence even when Redis is intentionally denied.
`run_pair.py PHASE --collect-only` resumes observation without another start.
Exports can adopt a retained accepted receipt only against its original recorded
dispatch and source/identity bindings; terminal success is still required. An
exporting execution never substitutes for the actual contributing execution.

`recovery-checkpoint.json` records current operations, receipt locations,
accepted observations, exact next action and deadlines. Every uncertain write
requires provider-evidence reconciliation before retry. Focused corrections and
affected resumption must preserve prior source bindings/results, stay inside
this resource/time/cost scope and not replay successful work. Changed build
inputs, another region/SKU, new resources or larger ceilings require a separate
decision; there is no arbitrary single-attempt limit.

## Cost, window and cleanup approval

| Item | Proposed bound |
| --- | --- |
| Incremental forecast, including 25% contingency | USD **7.9603** |
| New incremental ceiling | USD **10.00** |
| Prior cumulative approved ceiling, still unsettled | USD **320.89** |
| Proposed cumulative ceiling | USD **330.89** |
| Prior cumulative forecast, not settled charges | USD **314.5951** |
| Proposed cumulative forecast, not settled charges | USD **322.5554** |
| Earliest paid start | 2026-11-16 **07:00 UTC / 01:00 CST** |
| Begin provisioning by | 2026-11-16 **09:00 UTC / 03:00 CST** |
| Stop proof; scheduled cleanup | 2026-11-16 **13:00 UTC / 07:00 CST** |
| Runbook binding expiry | 2026-11-16 **14:00 UTC / 08:00 CST** |
| Cleanup/controller authority ends | 2026-11-16 **15:00 UTC / 09:00 CST** |

The estimate prices the entire eight-hour resource/cleanup bound, both B0 HA
nodes and both jobs continuously, full-day ACR, two full-month DNS zones,
private endpoints/data processing, bounded network and controller reserves.
`cost-estimate.json` binds 15 exact public retail meters, quantities, two saved
pricing responses and the previous finalized ledger. Actual cost is not inferred
from a ceiling. Public [Azure retail prices](https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices)
and [Managed Redis pricing](https://azure.microsoft.com/en-us/pricing/details/managed-redis/)
support the estimate; billing remains unsettled.

No new proof may start without its full 1,200-second replica timeout plus
120-second dispatch reserve remaining. Resource hours and forecast are checked
against the new ceiling; stop and clean up if the approved bound cannot be met.
An expired provisioning window requires a newly frozen window/cost/controller
package before spending. Existing PostgreSQL/object budgets are not reused.

Cleanup requires **18 zero residue counters**: target group, provider-managed
group, target resources, target role assignments, campaign cleanup binding and
schedule, Redis cache/database/access assignments, NSG/rules, registry, jobs,
environment, identities, private endpoints, DNS zones and VNet. The exact cache,
default database and both Redis ACL children require authoritative 404s; errors
are not absence. Verify target/group inventory and attribution, exact scoped
grants, binding/schedule absence and preserved controller/Reader/content.
Provider registrations are preserved. Partial provisioning is also torn down;
any missing attribution evidence must be reconciled before cleanup is declared
verified. Cleanup never depends on a successful export.

After accepted managed evidence and verified cleanup, reconcile M78-D-002 in the
existing checklist/register and report remaining existing milestone items.
Preserve all failed attempts, completed PostgreSQL/object evidence, Git history,
unrelated changes and all five protected stashes. Raw `.runtime` evidence stays
ignored. This preparation does not commit or push pending execution work, start
another requirement or declare Milestone 7.8 complete.

## Focused local preparation validation

The new probe's 27 focused tests passed; the new infrastructure contract's six
focused tests passed. Bicep compilation and scoped Ruff checks passed. These
tests validate package behavior and boundaries, not managed Redis acceptance.
Private helper validation, exact source/image hashes, unchanged closed-campaign
receipts, protected stash IDs and focused reference/privacy results are bound
in `package-review.json`. Existing valid suites are reused without rerunning.

## Expired-window reconciliation and cleanup decision

The user approved package
`c4952bd63262dcfc5caac32b7cd162281b1da97c3646815c1e054e72eaedcb16`.
The controller was renewed and cleanup armed before paid provisioning. The last
retained clock observation before waiting was 2026-11-16 06:28:31 UTC; the next
explicit clock observation was 17:15:51 UTC, after the 15:00 UTC authority expiry.
No foundation, image transfer, workload, proof job or fault operation was
dispatched. The original approval does not authorize mutations after expiry.

The scheduled cleanup job's provider job ID is
`ab6e6978-761c-4c99-8645-fc79272247e1`. Its provider schedule execution name is
`SCH_c8e92af3-e888-44ce-b773-5970fea9ce28_a92e5b4d-a862-40b9-8dca-5388ba2560bc_639304308000000000`.
It failed at 13:02:57 UTC before the runbook body: the published parameter
`CostCeilingCents` permits only `5000, 5651` and rejected the approved `1000`.
Preparation missed this compatibility check. This is a cleanup-control failure,
not a managed Redis assertion failure. The 17 assertions listed above are all
**unproved**, with no contributing managed proof execution IDs.

Read-only reconciliation at 17:18:49 UTC found the target group
`rg-m78-08bb3291ca-target` still present with **zero workload resources**,
**two target cleanup grants**, the expired campaign binding and schedule.
The expected provider-managed group was absent. The controller remained present
and published. Cleanup is **not verified**, the ledger is **not finalized**, and
zero workload resources must not be reported as 18 zero residue counters.
Evidence is private `expired-window-reconciliation.json` and
`expired-window-readbacks/` under `.runtime/milestone_7_8/redis-20261116/`.
The failed scheduled execution and all original approval/operation records are
preserved. The failed Automation job may still contribute charges; billing is
unsettled and no claim of zero total spending is made.

The smallest next decision is the prepared **cleanup-only extension**, bound by
`expired-cleanup-plan.json` SHA-256
`343d45677fab3a8a9e766c1490736b3e0c43e9edbaa7c70ecb3906d763176c59`
(the canonical plan digest stored in `planSha256`). It authorizes a maximum of
**two hours from explicit approval**, five exact DELETE operations and necessary
readbacks, with **no new spending allowance**; the existing Redis aggregate
ceiling remains USD 10 and the cumulative ceiling remains USD 330.89.

1. Refresh the exact target, ownership tags, empty resource inventory, failed
   job, both grant bindings and controller preservation baseline. If new
   workload resources or an active campaign job appear, stop and reconcile.
2. Remove only the two recorded target grants and the empty target group.
   Read each exact resource before dispatch; skip an already absent resource.
   Reconcile any uncertain response before a retry.
3. Verify target/provider group absence, then delete the exact campaign binding
   and its expired schedule. No controller renewal or publication is included.
4. Verify all 18 existing residue categories, exact Redis child absence and
   preserved controller identity, Reader, tags and published content. Retain
   the never-provisioned evidence instead of inventing an environment snapshot.
   Finalize this failed attempt only after verified cleanup.

The private plan contains the exact URLs, CLI argument arrays, input hashes and
approval template. Its preparation performs no Azure calls. It does not grant
authority by itself. Controller publication and paid proof resumption are not
ready for approval under this cleanup-only plan.

The focused local correction adds `1000` to the existing runbook ceiling
allowlist, preserving `5000, 5651` and all later scope, deadline, identity and
hash checks. It has **not been published**. The live controller must remain
unchanged during this cleanup. Before a later paid attempt, use the existing
renewal/publication workflow after the expired binding/schedule are absent,
bind the corrected published content and new window, validate cleanup parameter
compatibility before arming, and prepare a new frozen package. The retained
Redis image and acceptance criteria remain unchanged; no image rebuild is
needed for this controller-only correction.

The existing PowerShell response replay reproduced the old `1000` rejection
before any mocked read or deletion. After the one-line correction, six focused
cases passed: accept `1000`, `5000`, `5651`; reject `999`, `1001`, `5652`.
The corrected working-file SHA-256 is
`38cfeb6cd6e706d197e7a689e5080c36fdc6c3007ad14c0c0cbf35ca626cefd9`.
Rehash after any checkout or line-ending conversion before future publication.

<!-- M78-D-002 terminal documentation reconciliation -->
## Managed campaign reconciliation

Reconciled 2026-11-16 UTC after verified cleanup and ledger finalization.

**M78-D-002 remains open: 0 accepted, 0 failed, 17 unproved out of 17 existing assertions.** All 18 cleanup counters are zero; the reusable controller is preserved and the campaign ledger finalized. PostgreSQL and M78-D-001 remain closed. Milestone 7.8 remains incomplete. Billing remains **unsettled**.

The preparation text above is retained historical scope, not authority for another run. Accepted results retain their actual contributing execution IDs. Failed and uncertain attempts remain history; cleanup does not turn them into accepted proof.

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
| `ab6e6978-761c-4c99-8645-fc79272247e1` | `scheduled-cleanup-parameter-validation` | `Failed` |

### Bound artifacts and cleanup

| Binding | Value |
| --- | --- |
| Approved package SHA-256 | `c4952bd63262dcfc5caac32b7cd162281b1da97c3646815c1e054e72eaedcb16` |
| Source checkpoint | `2de5ed04fd965e1a65f0536b93c13019cbf8fde4` |
| Injected Redis probe SHA-256 | `f610ff80a42cb3545fc3ce7fa199c76ab217e7684ed5bb6b9819b8dc3baf691e` |
| Retained image/index | `sha256:f498e5aa0f5e44dc7becc92868e1bb989372ef09a3f30d694e89d172eaa66b0a` |
| Cleanup execution | `ab6e6978-761c-4c99-8645-fc79272247e1` |
| Cleanup method / actual runbook status | `explicit-approved-direct-empty-target-cleanup` / `Failed` |
| Approved cleanup-only plan | `343d45677fab3a8a9e766c1490736b3e0c43e9edbaa7c70ecb3906d763176c59` |
| `final-results.json` SHA-256 | `465d1a649635b85a2a26b3216e11255f7dab28905963cc79454339d6fa64b441` |
| `terminal-receipt.json` SHA-256 | `990d4dd911575d719539d8d9b6c1464936aa3bf96f733ac99aa1233bae4c3d2e` |
| `cleanup-verification.json` SHA-256 | `3249f315a820b9f27ddd110bfaecf86fd251f131cf190c84bff6eef331343082` |
| `campaign-ledger.json` SHA-256 | `927c34065b26cb73dbc208611c18452ed158b2f468a013703d2acb766f660912` |
| `assertion-inventory.json` SHA-256 | `b0ed5f39d51c2a0e03275205479c28165145be8bc2f9a61b5292e9f89cd0d9ae` |

Raw evidence remains ignored under `.runtime/milestone_7_8/redis-20261116/`; it is not published. No workload, probe execution or native chunk export was produced. Final results bind the retained source/image inputs and actual cleanup HTTP receipts. All 18 counters verify target/provider-managed-group, Redis/cache/database/ACL, NSG, network, job, identity, registry, role and schedule/binding absence. The reusable controller, identity, Reader grant and published runbook/content are preserved. This is active-resource absence, not physical-erasure or settled-billing evidence.

The cleanup-only extension was explicitly approved and completed using five exact management-plane DELETE operations. The scheduled runbook remains Failed in history; direct cleanup is independently verified. No new spending allowance, workload provisioning, Automation job, controller renewal or publication occurred during recovery. The local 1,000-cent compatibility correction remains unpublished. This attempt is closed; do not resume its expired paid-proof package.

Approved incremental ceiling: USD 10.00; prior cumulative ceiling: USD 320.89; cumulative ceiling: USD 330.89. These are approved ceilings, not settled charges. Billing remains unsettled. No previous campaign budget is reused.

This reconciliation closes only supported M78-D-002 assertions. Existing observability, durable-worker, broader managed recovery, capacity/failure and consolidated final-validation requirements remain in the milestone checklist. It does not authorize another campaign or milestone.
