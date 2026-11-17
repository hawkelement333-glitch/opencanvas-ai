# Milestone 7.8 full-closure admission checkpoint

On November 16, 2026 CST, the user approved execution and cleanup for
`rg-m78-a712b8c940-target` in East US, source
`d0e50ed6b42546958e667d08c6b76a4cbbad4e62` and review SHA-256
`6cb5bd784855d77cbcabd4af0f517b579c8796b439ae3e0afd2ddb0072670dc2`.
Preflight stopped before the first cloud mutation. The approved forecast was
$36.6423, with a $50 incremental ceiling and $400.89 cumulative ceiling.
Billing remains unsettled.

The private approval receipt records the first clock reading after approval
at 11:38:18 p.m. CST. On November 17 CST the gates were 1:38:18 a.m. for
readiness, 9:38:18 a.m. to stop proof and trigger cleanup, and 11:38:18 a.m.
for verified cleanup.

| Gate | Observed result |
|---|---|
| Package identity | The approved review SHA, source and all 185 bound file hashes matched. |
| Reusable controller | The scoped before-snapshot passed the existing controller preservation checks. Snapshot SHA-256 `ba4d7cbb9dc92ff263e71ccaa1a3809d33d03f86d0f19c0fb966007a4f7022cf`. |
| Campaign preparation | `prepare --maximum-hours 10` returned exit 2 with `invalid choice: '10' (choose from 4, 8)`. A local `CampaignConfig.validate` call independently rejected the 10-hour value. Both campaign and execution-authorization schemas also enumerate only 4 and 8. |
| Cleanup arming inputs | The approved package contains the named target and relative window, but lacks the campaign config, runtime and ledger required by the documented operator. The campaign/generation values are placeholders. The bound prior controller authority carries a historical campaign/generation pair that derives a different resource group under `prepare.py`. |
| Target state | The native Azure query returned false for the exact approved resource group. Zero managed assertions ran. No group, tenant object, controller renewal, schedule, binding or publication was created by this attempt. |

Private evidence is in
`.runtime/milestone_7_8/full-closure-prerequisites/execution-6cb5bd78/`.
`execution-approval.json` records authority and times,
`controller-renewal-before.json` retains the controller readback, and
`admission-blocker.json` records the exact failure and target absence.
The original package and signature files retain their approved bytes.

The next package needs a campaign binding for this exact target and a cleanup
arming path that accepts the selected +2/+10/+12 window. The existing runbook
accepts an Automation binding expiry of exactly one hour after its scheduled
deadline. A correction can preserve the runbook by using an internal +11-hour
expiry and explicitly binding the already scoped operator fallback and
verification through +12 hours. The correction must prove that the actual
operator accepts the config, runtime, ledger, schedule and binding together
before any paid operation. The packaged source and review hash must reflect
the correction before an execution decision on the new package.

Milestone 7.8 managed acceptance remains open. PostgreSQL, M78-D-001 and
M78-D-002 remain closed.

## Replacement execution stopped at native East US capacity admission

On November 17, 2026 CST, the user approved replacement package SHA-256
`e61d33694ed703279b910377d0dab69308329b44c929496ee7502985df9407fe` at source
`51764bca61c0c72b50fd03e5e75f8eaae8d5e087`. The initial recorded clock reading
after approval was 12:10:40 a.m. CST. The new readiness, proof-stop, Automation
expiry and operator cleanup deadlines were 2:10:40 a.m., 10:10:40 a.m.,
11:10:40 a.m. and 12:10:40 p.m. CST, respectively.

The existing controller completed its deadline-only renewal through
11:10:40 a.m. CST. Reconciliation verified the preserved controller and
allowed the replacement binder to produce the campaign config, runtime and
ledger. Real operator preflight and subscription/tenant correlation passed.
`capacity-check` then stopped with `required PostgreSQL SKU is unavailable`.
The focused native `postgres flexible-server list-skus --location eastus`
response returned zero supported server editions and reported that provisioning
is restricted in this region for the bound subscription. The native response
advises choosing a different region or seeking a service and subscription
limits exception. The restriction is regional for this subscription, so an
East US SKU substitution does not resolve the observed gate.

The ledger ended at `correlated`, with zero resource generations, no billable
start recorded and zero managed assertions. Exact readback confirmed absence
of the approved target group, target Automation schedule and target job binding.
The controller deadline renewal was the only cloud change from this attempt.
Billing remains unsettled. PostgreSQL, M78-D-001 and M78-D-002 remain closed.

Retained private evidence under
`.runtime/milestone_7_8/full-closure-prerequisites/run-e61d3369/` includes
`terminal-preflight.json`, `eastus-postgresql-skus.json`,
`bound/ledger.json` and
`renew/reconciliation/02-completed-authority-evidence.json`. The SKU response
receipt SHA-256 is `094b085545501a8b513c1bf2eba5ba1268eee2facd875931ab23c245022ba72b`.
The reconciled controller evidence SHA-256 is
`9d09430112c7a22ae04c0c3a7920b2ef64c180f7347b6cf9e42e9820a21099f6`.

To continue in East US, establish that the subscription restriction has been
lifted, then revalidate the exact approved SKU. A regional change requires
a revised scope, pricing and package decision. Managed Milestone 7.8 evidence
remains open.
