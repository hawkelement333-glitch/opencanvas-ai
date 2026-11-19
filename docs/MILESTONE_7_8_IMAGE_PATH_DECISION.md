# Milestone 7.8 managed proof while OpenSSL repair is deferred

Source checkpoint `4b7b44729dfed37fef84c219132e522c92dfd26f` on
`milestone-7-8-production-readiness-audit-local`. PostgreSQL, D001 and D002
remain closed. Keep the accepted signup, bootstrap, migration, native
route, alert-creation, worker destination and cleanup receipts in their exact
historical bindings. The [closure ledger](MILESTONE_7_8_FULL_CLOSURE_LEDGER.md#existing-criteria-and-disposition)
continues to define acceptance.

## Completed local work

Reconciled the retained SPDX files, runtime inventories and exact OCI archives
for API5, the corrected API and web3. The archive and manifest digest checks
bound the collected notices to the actual image bytes. The separate license
bundles preserve all four project notices for each image. All 87 Debian and
43 third-party Python package notice sets were found in each API image. For
web3, all 79 Debian copyright records were collected. The Node v24.22.3
license was obtained from its official distribution after matching the
installed executable byte-for-byte. The image contains 21 third-party npm
package manifests. Matching their exact installed manifests to the locked
distribution archives, including the five bundled through Next, supplied
14 notice sets. The 16 parent npm archives matched their lockfile SHA-512
integrity values.

Seven frontend notice dispositions remain open. These are
`@img/sharp-libvips-linux-x64@1.3.4`,
`@img/sharp-libvips-linuxmusl-x64@1.3.4`, `@next/env@16.4.5`,
`client-only@0.0.1`, `@edge-runtime/cookies@6.0.0`,
`@edge-runtime/ponyfill@4.0.0`, and `@edge-runtime/primitives@6.0.0`.
The two libvips packages declare LGPL-3.0-or-later. The other five declare
MIT. Both libvips registry records identify upstream build source
`ebb95f8add54eee8bed840e3fb587e4cbec857d7`. The bundled native-library
notices and distribution obligations remain open. Obtain the remaining
upstream notices before calling this release's license bundle complete. The
private archive supplement leaves the images and the earlier signed release
materials intact. See [release notice requirements](../THIRD_PARTY_NOTICES.md#release-follow-up).

Private receipts are under `.runtime/milestone_7_8/licenses-4b7b447-v2/`.

| Receipt | SHA-256 |
| --- | --- |
| `receipt.json` | `062dc3242db7c77df57515e9ab97ec7c2f45b268a389316b0095aa37475c7775` |
| `web3-npm-receipt.json` | `01a08e37b6efd7eafab61b1b5405771a218019665ac33108e42c1b28e932df18` |
| `web3-node-runtime-receipt.json` | `3cfb7f0b89f6973ad218f33844e677e1016e6b10d7560f82f9f8ff92b6c481ab` |

The operator already has an offline-tested telemetry-first route, core
continuation, and quota fallback. Keep those results, the original scan
receipts, and the frozen blocked review. No application changes or repeat
tests are needed to choose an execution path.

## Image-specific managed evidence

API5 is the previously signed
`sha256:9ec275f46b587fde50aaf7e04f4ed93f30edac4efd45da9452790e5be91f1d12`.
The corrected API is the unsigned
`sha256:e0e6518e8f54c6151e598c6b591923dfade3e35c7b10a18dc0fc38bc22cc3c62`.
The API build-input comparison shows changes only to the API lifespan and
operational exporter. Verification of the five-second partial flush and
its trace-correlated gateway witness requires the corrected code. Exact
release evidence remains stamped to the actual digest. Earlier functional
evidence can be reused wherever it satisfies the existing criterion.

Both API inventories contain `openssl`, `libssl3t64`, and
`openssl-provider-legacy` at `3.5.7-1~deb13u3`. The signed web3 frontend
`sha256:1ee742b604d406ad8cc4c3c53001853ad58a033b68f4d613251ea7fc088fdb3a`
contains `libssl3t64` and `openssl-provider-legacy` from that same source
revision. The six High results below were observed by Scout on the
corrected API. The signed images' package inventories establish exposure
to the same affected source revision. Their older scans remain historical
evidence. No new scan of either signed image was run.

| Ledger assertion | What API5 could exercise in separately approved staging | What needs the corrected API or further evidence |
| --- | --- | --- |
| D003 signals and trace continuity | Worker and outbox rows, their links, and native backup/forecast inputs. API5 can emit on a full batch; genuine rows count for that execution and source. | One quiet private GET, its exact API destination row, and the trace-correlated gateway witness. API-origin requirements and API-to-worker links for the corrected release need matching API and worker evidence in the same run. |
| D003 13 dashboard renders and 16 alert firing/recovery pairs | Workbook rendering, worker/provider-backed panels and alerts when their real inputs arrive, and native firing and recovery. Existing native alert-rule creation stays credited. | API request/error/duration panels and API-backed alerts need valid API rows. For mixed-source panels and alerts, retain each accepted source observation and hold the missing API leg. Integrity recovery still requires authorized investigation. Backup/cost fixtures cannot stand in for unavailable native observations. |
| D003 destination rejection, outage, access, retention | Exact 401/422/422 rejection and absence, worker/gateway outage/readiness/recovery, denied identity reads, operator revocation and regrant with fresh sessions, and five exact table-retention readbacks. | The corrected API's own exporter loss/backpressure/readiness/recovery needs a real API export sequence. Long-term physical expiry remains outside this window. |
| D004 worker and activity-v1 | Authenticated upload, independently deployed worker claim/scan/promotion/publication, independent private receiver ACK after durable commit, duplicate and lost ACK, stale fencing, bounded retry/terminal failure, standalone drain and recovery. A clean core fixture is still required. | The API trace linked to these operations needs the corrected release's native evidence. Any old run still needs accepted native receipts for the particular worker and delivery assertions. |
| D005 R1 through R4 | Scoped PITR at 0030, replay identity denial and exact state reconciliation, restored roles and cross-user denial, quiescence and stale fencing, resumption without duplicate effects, rollback, and measured RPO/RTO. | Credit exact old-image observations; compare any later production candidate at its changed compatibility boundary. The retained local 0028→0029 proof and historical accepted recovery stay credited. |
| D006 capacity, release and controls | Synthetic workload sizes, ramp/spike, admissions and rejections, scoped pressure/fault/recovery, and independently observable private egress, roles, secret access and restore protection. Historical API5/web3 digest and signing evidence stays credited. | API telemetry-backed workload correlations need valid rows under the release being qualified. Production release of the corrected API still requires a passing exact-image scan and trusted signatures. Staging receipts cannot supply those. License dispositions above remain open. |
| D007 diagnostics | Configured native category rows and retention for applicable deployed services, including PostgreSQL, Blob, registry and Key Vault. | Each claimed category needs its actual native receipt. Firewall and VM retain their existing not-applicable disposition for this topology. |
| Editable AI and password reset | Both managed editable-AI browser/provider scenarios can use the unchanged signed frontend and API5 application functionality after the core fixture is accepted. The password-reset contract can use either API when separately scoped end to end. | Password reset remains outside the shared package. It requires native received messages, single-use and expiry evidence. No Gmail input is needed for the proposed shared run. |
| Exit and cleanup | Each executed campaign verifies its own cleanup. Billing remains unsettled. | Milestone 7.8 stays open until the remaining criteria are satisfied. Earlier zero counters do not verify the next campaign. |

Splitting API5 work from the corrected-image proof means a second paid
provisioning cycle if the first campaign is cleaned up before the corrected
image is admitted. The first run's private access and dependency setup would
have to be repeated. A single live environment could only carry both release
bindings under a separately reviewed, bounded two-image plan. The frozen
package binds one API digest. A narrower follow-up might reduce the second
run's cost; its exact scope depends on the accepted results from the first.

## Optional single staging run

For a decision only. Use the exact corrected API and signed web3 OCI indexes
above for one private synthetic staging campaign. The exception would cover
the affected Debian OpenSSL package set at `3.5.7-1~deb13u3` for these exact
digests and the six findings only:

- CVE-2026-107496
- CVE-2026-124709
- CVE-2026-88823
- CVE-2026-95692
- CVE-2026-107493
- CVE-2026-95691

Scout recorded zero Critical and six High on the corrected API, using
SARIF SHA-256 `5f78502e2ab2d4dc741573f055a5d8325441e5659a0002b5a61bdeb7b1c2bd9a`.
The unsigned corrected API must remain identified as such. Keep the
production zero-Critical/zero-High and trusted-signing rules in force. A
separate staging admission review would have to explicitly bind the unsigned
digest and exact inventory, keep production admission intact, and reject scope,
digest, finding or deadline drift. The current blocked package remains blocked.
Any subsequent production-image evidence needs its own exact release binding.

- **Scope.** Existing isolated Canada Central target
  `rg-m78-a712b8c940-target`, private East US HA Redis, existing temporary
  VPN/private DNS and restricted operator access, and one isolated PITR
  copy. Use synthetic data, campaign-only identities and provider allowances,
  private ingress and the existing scoped egress, and preserve certificate
  verification. The signed frontend and the corrected API are the only proposed
  images. Those API bytes cover the API, worker, gateway, activity and job
  roles already bound to that image. Keep the exact-IP registry exception
  at 20 minutes and the existing caps of 10,000 HTTP requests, 200 model
  attempts and 160M embedding tokens. Email, production hosting, production
  traffic and public launch are outside the scope.
- **Expiry.** Derive start from the first whole UTC minute strictly after
  approval. Private readiness at +2h, core and one-request gate at +3h,
  proof stop at +11h, Automation authority expiry at +12h, and verified
  removal and exception expiry at +13h. No persistence beyond the campaign
  window. The liveness result never terminates eligible work on its own.
- **Cost.** Retained full shared-scope forecast **$40.8177 USD**, replacement
  execution ceiling **$56.51**, and proposed cumulative ceiling **$460.40**,
  including **$53** reserved for unsettled prior exposure. This is one
  replacement proposal. The controls above use existing resources and
  schedule. No new hosting or overlapping execution allowance is assumed.
- **Cleanup.** Require native schedule and binding readbacks and the
  entitled operator available through +13h. The separate approval may
  bind the exact-target early fallback for a fresh monthly Automation 429
  after proof stops and complete native inventory confirms no job. Otherwise
  use the scheduled path and the ordinary +12h fallback if required.
  Verify named-vault purge, all 48 counters, and disarm only this campaign's
  binding and schedule. Preserve the reusable controller.

The [telemetry-first package description](MILESTONE_7_8_TELEMETRY_FIRST_SHARED_RUN.md)
contains the existing continuation and cleanup rules. No signed-production
disposition or Azure authority follows from this decision record.
