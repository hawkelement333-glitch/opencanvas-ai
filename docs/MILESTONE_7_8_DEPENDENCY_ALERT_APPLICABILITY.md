# Milestone 7.8 dependency-alert applicability and focused correction

Date: 2026-11-16. Baseline: `8236da2f8bb612732da3abf7f5297e02ec1cbd9c`.

## Result and limits

The actual GitHub API returned **74 open default-branch alerts, representing
46 advisories across 14 npm package names**: 10 critical, 33 high, 28 medium
and 3 low alert records. All 74 matched at least one version in this branch's
baseline lockfile. This is package/version applicability, not a claim that
every advisory's exploit prerequisites are reachable in this application.

The corrected lockfile has **zero matches to those 74 alert ranges**. A
scoped npm advisory lookup of the 14 named packages at their corrected
versions returned no advisories. This is not a repository-wide security
scan or a guarantee against all vulnerabilities. The GitHub default branch
was not modified and its open-alert count need not change after pushing this
branch.

The retained `f498e5aa…` image is the Python API image, not the Next.js
frontend. Its installed-package inventory and Dockerfile have no npm runtime.
These frontend manifest/lockfile changes do not change its canonical build
inputs, and its accepted scan remains evidence for that exact image. An API
scan never established frontend dependency safety. A future frontend release
must use the corrected lockfile and obtain its own build/runtime evidence;
no image build, image publication or deployment was performed here.

## Applicability boundaries

- **Applicable runtime condition:** Next.js 16.2.10 is affected by the Windows
  App Router RCE advisory; the isolated local website setup uses Windows.
  [Upstream advisory](https://github.com/vercel/next.js/security/advisories/GHSA-p293-qw3h-jr36).
- **Feature-dependent runtime exposure:** the remaining Next server/cache/action/
  proxy/image advisories and sharp codecs have specific route, platform or input
  prerequisites. Source inspection found no `use cache`, `unstable_cache`,
  Server Actions, `next/og` or `next/image` usage in the current application.
  That does not exempt the installed vulnerable package versions or guarantee
  that all built-in routes are unreachable. The shared dependency boundary
  was corrected rather than relying on an undocumented feature restriction.
- **Browser validation:** Zod parses API responses/input; some application
  schemas contain unbounded arrays. The package's collection-validation memory
  issue therefore cannot be dismissed as an absent dependency. It is not a
  Python API-server vulnerability.
- **Development/build exposure:** Vitest/mocker/Vite and lint/build glob, YAML,
  browser-data and source-map packages do not by their presence establish a
  production HTTP exploit. Their local development-server or untrusted-input
  conditions remain relevant. Next's MCP information-disclosure advisory is
  specifically a development-server issue.
- **Unaffected versions/components:** minimatch 3.1.5 is outside the reported
  `>=7.0.0 <11.0.1` range and was retained; the 10.x copy was corrected.
  None of these npm alerts maps to an installed distribution in the retained
  Python API image. Exact API inventory is recorded in the local provenance work.
- **Unresolved:** exploitability of every conditional frontend route in a future
  deployed topology is not claimed here. Version remediation removes the named
  affected dependency ranges; production packaging and topology validation are
  separate remaining release evidence.

## Minimal correction

Pinned Next and its matching lint configuration to **16.4.5**, Zod to **4.6.6**,
and Vitest/mocker to **4.1.12**. Added an explicit development Vite **8.1.6**
pin because pnpm retained the older automatically resolved peer despite an
override. Scoped overrides pin only advisory-bearing transitive families:
PostCSS 8.5.23, sharp 0.35.5, source-map-js 1.2.2, brace-expansion 1.1.21 and
5.0.12, minimatch 11.0.1 for the affected >=7 family, js-yaml 4.3.2,
browserslist 4.28.7, baseline-browser-mapping 2.11.0 and nanoid 3.3.18.
The unaffected minimatch 3.x copy stays unchanged. No blanket dependency update
or application architecture change was made.

The initial Next 16.4.1 candidate covered the 74 GitHub alerts, but the local
startup check exposed a newer moderate advisory affecting 16.3.0–16.4.4.
The npm response and [upstream advisory](https://github.com/vercel/next.js/security/advisories/GHSA-mfr8-8qww-v76h)
identify **16.4.5** as the first fixed version. That bounded correction was
made before final browser proof. The advisory involves nesting `use cache`
through `unstable_cache`; neither is used by this app. No tool-generated
instruction to run an autonomous upgrade agent was followed.

## Every reported alert mapped

`Baseline matches` lists only affected copies, not every installed copy.
All rows have **zero corrected-version matches** to the stated range.
The raw provider response stays private; identifiers, versions and public
advisory links below are the sanitized mapping.

| Alert numbers | Package / advisory | Affected range | Baseline matches | Corrected installed versions |
| --- | --- | --- | --- | --- |
| #1 | `sharp` / [GHSA-f88m-g3jw-g9cj](https://github.com/advisories/GHSA-f88m-g3jw-g9cj) | `< 0.35.0` | 0.34.5 | 0.35.5 |
| #2, #11 | `next` / [GHSA-m99w-x7hq-7vfj](https://github.com/advisories/GHSA-m99w-x7hq-7vfj) | `>= 16.0.0, < 16.2.11` | 16.2.10 | 16.4.5 |
| #3, #12 | `next` / [GHSA-6gpp-xcg3-4w24](https://github.com/advisories/GHSA-6gpp-xcg3-4w24) | `>= 16.0.0, < 16.2.11` | 16.2.10 | 16.4.5 |
| #4, #13 | `next` / [GHSA-955p-x3mx-jcvp](https://github.com/advisories/GHSA-955p-x3mx-jcvp) | `>= 16.0.0, < 16.2.11` | 16.2.10 | 16.4.5 |
| #5, #14 | `next` / [GHSA-q8wf-6r8g-63ch](https://github.com/advisories/GHSA-q8wf-6r8g-63ch) | `>= 16.0.0, < 16.2.11` | 16.2.10 | 16.4.5 |
| #6, #15 | `next` / [GHSA-p9j2-gv94-2wf4](https://github.com/advisories/GHSA-p9j2-gv94-2wf4) | `>= 16.0.0, < 16.2.11` | 16.2.10 | 16.4.5 |
| #7, #16 | `next` / [GHSA-4c39-4ccg-62r3](https://github.com/advisories/GHSA-4c39-4ccg-62r3) | `>= 16.0.0, < 16.2.11` | 16.2.10 | 16.4.5 |
| #8, #17 | `next` / [GHSA-4633-3j49-mh5q](https://github.com/advisories/GHSA-4633-3j49-mh5q) | `>= 16.0.0, < 16.2.11` | 16.2.10 | 16.4.5 |
| #9, #18 | `next` / [GHSA-68g3-v927-f742](https://github.com/advisories/GHSA-68g3-v927-f742) | `>= 16.0.0, < 16.2.11` | 16.2.10 | 16.4.5 |
| #10, #19 | `next` / [GHSA-89xv-2m56-2m9x](https://github.com/advisories/GHSA-89xv-2m56-2m9x) | `>= 16.0.0, < 16.2.11` | 16.2.10 | 16.4.5 |
| #20 | `postcss` / [GHSA-r28c-9q8g-f849](https://github.com/advisories/GHSA-r28c-9q8g-f849) | `<= 8.5.17` | 8.5.14 | 8.5.23 |
| #22 | `brace-expansion` / [GHSA-mh99-v99m-4gvg](https://github.com/advisories/GHSA-mh99-v99m-4gvg) | `>= 4.0.0, < 5.0.8` | 5.0.7 | 1.1.21, 5.0.12 |
| #23 | `brace-expansion` / [GHSA-rgw5-rvv9-x895](https://github.com/advisories/GHSA-rgw5-rvv9-x895) | `>= 4.0.0, < 5.0.9` | 5.0.7 | 1.1.21, 5.0.12 |
| #24 | `brace-expansion` / [GHSA-mh99-v99m-4gvg](https://github.com/advisories/GHSA-mh99-v99m-4gvg) | `< 1.1.17` | 1.1.16 | 1.1.21, 5.0.12 |
| #25 | `js-yaml` / [GHSA-5p4m-2wfm-xmqj](https://github.com/advisories/GHSA-5p4m-2wfm-xmqj) | `>= 4.0.0, < 4.3.1` | 4.3.0 | 4.3.2 |
| #26 | `postcss` / [GHSA-fxqj-rqcc-2cmp](https://github.com/advisories/GHSA-fxqj-rqcc-2cmp) | `<= 8.5.22` | 8.5.14, 8.5.19 | 8.5.23 |
| #28 | `nanoid` / [GHSA-2v37-7h3g-55p8](https://github.com/advisories/GHSA-2v37-7h3g-55p8) | `< 3.3.18` | 3.3.16 | 3.3.18 |
| #29 | `brace-expansion` / [GHSA-rgw5-rvv9-x895](https://github.com/advisories/GHSA-rgw5-rvv9-x895) | `< 1.1.18` | 1.1.16 | 1.1.21, 5.0.12 |
| #30 | `browserslist` / [GHSA-c83g-rgw3-j3cx](https://github.com/advisories/GHSA-c83g-rgw3-j3cx) | `<= 4.28.6` | 4.28.6 | 4.28.7 |
| #31 | `browserslist` / [GHSA-73wf-gq98-2v4g](https://github.com/advisories/GHSA-73wf-gq98-2v4g) | `<= 4.28.6` | 4.28.6 | 4.28.7 |
| #32 | `@vitest/mocker` / [GHSA-82fw-gwwq-j7x9](https://github.com/advisories/GHSA-82fw-gwwq-j7x9) | `>= 2.1.0, < 4.1.11` | 4.1.10 | 4.1.12 |
| #33, #34 | `vitest` / [GHSA-82fw-gwwq-j7x9](https://github.com/advisories/GHSA-82fw-gwwq-j7x9) | `>= 2.1.0, < 4.1.11` | 4.1.10 | 4.1.12 |
| #35 | `baseline-browser-mapping` / [GHSA-w5vr-8v7q-w6rv](https://github.com/advisories/GHSA-w5vr-8v7q-w6rv) | `>= 2.0.0, < 2.11.0` | 2.10.43 | 2.11.0 |
| #36, #37 | `next` / [GHSA-2xp9-vwfh-vxw4](https://github.com/advisories/GHSA-2xp9-vwfh-vxw4) | `>= 16.0.0, < 16.3.3` | 16.2.10 | 16.4.5 |
| #38, #39 | `next` / [GHSA-p293-qw3h-jr36](https://github.com/advisories/GHSA-p293-qw3h-jr36) | `>= 16.0.0, < 16.3.3` | 16.2.10 | 16.4.5 |
| #40 | `sharp` / [GHSA-rgj7-g3m4-5g8c](https://github.com/advisories/GHSA-rgj7-g3m4-5g8c) | `< 0.35.4` | 0.34.5 | 0.35.5 |
| #41 | `js-yaml` / [GHSA-2883-xcg3-v3hh](https://github.com/advisories/GHSA-2883-xcg3-v3hh) | `>= 4.0.0, < 4.3.2` | 4.3.0 | 4.3.2 |
| #42 | `brace-expansion` / [GHSA-qhr7-859c-m2p7](https://github.com/advisories/GHSA-qhr7-859c-m2p7) | `>= 4.0.0, < 5.0.11` | 5.0.7 | 1.1.21, 5.0.12 |
| #43 | `brace-expansion` / [GHSA-6j4f-fj2g-mc7p](https://github.com/advisories/GHSA-6j4f-fj2g-mc7p) | `>= 4.0.0, < 5.0.10` | 5.0.7 | 1.1.21, 5.0.12 |
| #44, #45 | `next` / [GHSA-vcvr-r3jv-pc5j](https://github.com/advisories/GHSA-vcvr-r3jv-pc5j) | `>= 16.2.0, < 16.3.6` | 16.2.10 | 16.4.5 |
| #46, #47 | `next` / [GHSA-cjq9-62q9-8jv4](https://github.com/advisories/GHSA-cjq9-62q9-8jv4) | `>= 16.0.0, < 16.3.8` | 16.2.10 | 16.4.5 |
| #48, #49 | `next` / [GHSA-4jqv-mc3x-m676](https://github.com/advisories/GHSA-4jqv-mc3x-m676) | `>= 16.0.0, < 16.3.8` | 16.2.10 | 16.4.5 |
| #50, #51 | `next` / [GHSA-f87g-xv8r-7p7x](https://github.com/advisories/GHSA-f87g-xv8r-7p7x) | `>= 16.0.0, < 16.3.8` | 16.2.10 | 16.4.5 |
| #52, #53 | `next` / [GHSA-39w2-rjm5-chcv](https://github.com/advisories/GHSA-39w2-rjm5-chcv) | `>= 16.0.0, < 16.3.8` | 16.2.10 | 16.4.5 |
| #54 | `brace-expansion` / [GHSA-q2hr-2g5m-vwhr](https://github.com/advisories/GHSA-q2hr-2g5m-vwhr) | `< 1.1.21` | 1.1.16 | 1.1.21, 5.0.12 |
| #55 | `source-map-js` / [GHSA-68fv-2mgg-jv7q](https://github.com/advisories/GHSA-68fv-2mgg-jv7q) | `>= 1.0.0, < 1.2.2` | 1.2.1 | 1.2.2 |
| #57 | `vite` / [GHSA-698v-4r3x-3vcv](https://github.com/advisories/GHSA-698v-4r3x-3vcv) | `>= 8.0.0, <= 8.1.5` | 8.1.5 | 8.1.6 |
| #58 | `vite` / [GHSA-587h-7wmj-h5pm](https://github.com/advisories/GHSA-587h-7wmj-h5pm) | `>= 8.0.0, <= 8.1.5` | 8.1.5 | 8.1.6 |
| #59 | `vite` / [GHSA-r825-w8mm-5pxw](https://github.com/advisories/GHSA-r825-w8mm-5pxw) | `>= 8.0.0, <= 8.1.5` | 8.1.5 | 8.1.6 |
| #60 | `vite` / [GHSA-9jrq-w75r-8gcw](https://github.com/advisories/GHSA-9jrq-w75r-8gcw) | `>= 8.0.0, <= 8.1.5` | 8.1.5 | 8.1.6 |
| #61 | `vite` / [GHSA-rq7h-c2jc-7f22](https://github.com/advisories/GHSA-rq7h-c2jc-7f22) | `>= 8.0.0, <= 8.1.5` | 8.1.5 | 8.1.6 |
| #62 | `@vitest/mocker` / [GHSA-qxg6-89mg-rqv8](https://github.com/advisories/GHSA-qxg6-89mg-rqv8) | `>= 2.1.0-beta.7, < 4.1.12` | 4.1.10 | 4.1.12 |
| #63, #64 | `next` / [GHSA-2464-fhr4-w9xw](https://github.com/advisories/GHSA-2464-fhr4-w9xw) | `>= 16.0.0, <= 16.4.0` | 16.2.10 | 16.4.5 |
| #65, #66 | `next` / [GHSA-p3m5-59mp-jv5r](https://github.com/advisories/GHSA-p3m5-59mp-jv5r) | `>= 16.0.0, <= 16.4.0` | 16.2.10 | 16.4.5 |
| #67, #68 | `next` / [GHSA-673q-mjm6-r5xr](https://github.com/advisories/GHSA-673q-mjm6-r5xr) | `>= 16.0.0, <= 16.4.0` | 16.2.10 | 16.4.5 |
| #69, #70 | `zod` / [GHSA-mrhx-c7xc-m3w5](https://github.com/advisories/GHSA-mrhx-c7xc-m3w5) | `< 4.6.6` | 4.4.3 | 4.6.6 |
| #71, #76 | `next` / [GHSA-mcj8-r9mp-w47p](https://github.com/advisories/GHSA-mcj8-r9mp-w47p) | `>= 16.0.0, < 16.3.8` | 16.2.10 | 16.4.5 |
| #72 | `brace-expansion` / [GHSA-6j4f-fj2g-mc7p](https://github.com/advisories/GHSA-6j4f-fj2g-mc7p) | `< 1.1.19` | 1.1.16 | 1.1.21, 5.0.12 |
| #73 | `brace-expansion` / [GHSA-qhr7-859c-m2p7](https://github.com/advisories/GHSA-qhr7-859c-m2p7) | `< 1.1.20` | 1.1.16 | 1.1.21, 5.0.12 |
| #74 | `brace-expansion` / [GHSA-q2hr-2g5m-vwhr](https://github.com/advisories/GHSA-q2hr-2g5m-vwhr) | `>= 4.0.0, < 5.0.12` | 5.0.7 | 1.1.21, 5.0.12 |
| #75 | `sharp` / [GHSA-wq5f-xc86-pv6w](https://github.com/advisories/GHSA-wq5f-xc86-pv6w) | `< 0.35.5` | 0.34.5 | 0.35.5 |
| #77 | `minimatch` / [GHSA-g3hv-75wg-m249](https://github.com/advisories/GHSA-g3hv-75wg-m249) | `>= 7.0.0, < 11.0.1` | 10.2.5 | 3.1.5, 11.0.1 |

## Validation

- `corepack pnpm install --frozen-lockfile`: passed using repository-pinned
  pnpm 10.15.1; final installed Next version 16.4.5 confirmed directly.
- Full 74-record semver comparison: **74 baseline matches, zero final matches**;
  all 46 advisory identities and each manifest-level alert are retained.
- Scoped registry lookup for all 14 named package/version sets: **zero returned
  advisories**, including the newer Next cache issue.
- Five affected contract/API-client test files: **25 passed**, covering Zod
  contracts and legitimate API parsing under Zod 4.6.6/Vitest 4.1.12. This run
  preceded the final Next-only 16.4.1 to 16.4.5 correction; those contract
  dependencies did not change and the suite was not repeated.
- Final TypeScript check: passed under Next 16.4.5.
- Focused ESLint check of `next.config.ts` and `src/lib/api-client.ts`: passed
  with zero warnings under the corrected lint dependency graph.
- Real-stack browser outcomes are recorded in the main local-gap completion
  record; no unchanged frontend suite or production build was run by this
  dependency correction.

The security confirmation is an advisory-range and installed-version check,
not execution of an RCE payload against the host. The legitimate controls are
the focused contract/type checks and separately recorded real-stack journeys.
All agent slots were occupied, so the security boundary and candidate review
were performed as separate read-only passes: check actual app/config entry
points, distinguish runtime from development paths, retain unaffected package
families, and inspect the final dependency diff. No authorization or input
validation checks were weakened.

## Private evidence bindings

Private evidence directory:
`.runtime/milestone_7_8/local-gap-20261116/security/`.

- `dependabot-open.json`: SHA-256 `89427eba55e03483212e8b565b006d3ead3d798f064224200187cdf2109e0f81`.
- `baseline-pnpm-lock.yaml`: SHA-256 `c6f8bd3e0c53bc75a8ad34de3befef3a761dcde94cdbf4cab12d7d68c26f924a`.
- `applicability.json`: SHA-256 `9520bca534524c02744b56602f015b96fa950e56d68076c6ddf28628dd96632f`.
- `named-package-current-advisories.json`: SHA-256 `6aae1407cb347d7715eff52cca1d840df3d5616f9ccacef41ee7afa02d521580`.
- `next-current-advisories.json`: SHA-256 `c0766507478ad8fd3318731a6f720f4ce48b3c8d62ffd6644ca3c7e19a40840c`.
- `focused-contracts.log`: SHA-256 `84d314c79d10b52ddab8b590dda227140cb64be322baf7585ee769ae0d7ce8a9`.
- `typecheck-final.log`: SHA-256 `400426f2ff0d5fbe1c45e5d4e0cb0a30bc2562e50599876bd1b0ea08e2ae7516`.
