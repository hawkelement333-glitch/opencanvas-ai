# Milestone 7.7 Checkpoint 1 Infrastructure and Policy Manifest Handoff

Date: 2026-07-30

Status: Checkpoint 1 complete locally; Milestone 7.7 remains incomplete;
Checkpoint 2 and Milestone 7.8 are unstarted

## Checkpoint

- Checkpoint: Milestone 7.7 — Checkpoint 1 Local Infrastructure and Policy
  Manifest
- Starting branch: `milestone-7-6-recovery-adapter`
- Starting commit: `1aca65c4a1d131dd420154efbe36e2c2204c3903`
- Starting parent: `ca0e5a9ee97bd2b57f5f6eb664c97c615c27ee38`
- Implementation branch: `milestone-7-7-implementation-local`
- Completion commit: this handoff's local checkpoint commit; the exact SHA is
  reported after commit creation
- Commit message: `Add Milestone 7.7 infrastructure policy manifest`
- Upstream: none
- Sole Alembic head: `20260726_0028`
- Migration `0028` Git blob:
  `55c203e669cace5be64fc25cdcf0eb8c05519198`
- Migration `20260726_0029`: absent

No application, worker, frontend, migration, dependency, lockfile, CI,
container, or existing test behavior changed. The focused contract tests were
added to the established API test directory so they remain part of future
backend campaigns. No Azure resource exists for Milestone 7.7, and this
checkpoint performed no Azure authentication, discovery, what-if, deployment,
data-plane, role, or cost operation.

## Implemented local contract

The checkpoint establishes a fail-closed, resource-free contract graph under
[`infra/milestone_7_7`](../infra/milestone_7_7/README.md):

- one subscription-scope Bicep composition boundary that invokes no modules;
- eleven resource-free Bicep boundaries for policy, network, identities,
  registry, Key Vault, PostgreSQL, Redis, storage/scanner, compute,
  observability, and cleanup supervision;
- checksum-closed environment, image-digest, and cost-envelope schemas;
- unresolved, non-deployable templates containing no live Azure context;
- checksum-closed deny-by-default resource, SKU, network, lifecycle,
  dependency-order, and unresolved-gate policy contracts;
- standard-library-only schema, semantic, RFC 1918, private-material,
  canonicalization, checksum, and exact-scope validation;
- non-mutating preflight, what-if, deployment, teardown, and zero-residue
  entry points;
- focused contract tests in `apps/api/tests`; and
- an infrastructure-local generated-output denylist.

The Bicep files contain no `resource`, `existing`, or `module` declarations,
remote module references, deployment scripts, provider API versions,
automatic region or subscription discovery, live resource IDs, credentials,
secrets, or Azure outputs. `main.bicep` only inventories the module and gate
boundaries. The module files record fixed local parameter contracts and safe
outputs but are not invoked. The policy JSON files are descriptive contracts,
not executable Azure Policy definitions.

## Fixed controls

The contract fixes these values and rejects caller widening:

- IaC direction: Bicep;
- compute direction: internal Azure Container Apps on the Consumption
  workload profile, pending later capability and cost validation;
- location: unresolved, with no default, fallback, or current-context
  selection;
- data class: isolated synthetic only;
- cost target: `10000` USD cents;
- provisioning block: estimates above `12000` USD cents;
- absolute ceiling: `15000` USD cents, with maximum plausible cost required to
  remain strictly below it;
- uncertainty contingency: at least `2500` basis points, calculated against
  and added to the reconciled base maximum;
- budget alerts: monitoring only, never enforcement;
- default planned environment lifetime: 12 hours;
- hard environment lease: 24 hours;
- P2S maximum lifetime: 12 hours;
- final cleanup reserve: 90 minutes;
- public application ingress and public data-service access: denied;
- exactly three infrastructure-only Standard static public-IP exceptions:
  Azure Firewall Basic data, Azure Firewall Basic management, and `VpnGw1`
  P2S;
- no application, data-service, or VM public IP;
- inbound and outbound default: deny;
- broad `VirtualNetwork` service-tag egress: denied;
- exact-CIDR rules, firewall routing, and private endpoints: required;
- SKU and replica selection: fixed for every resolved role, with no mutable
  runtime selection; fault-controller CPU and memory remain blocked;
- shared storage keys, anonymous access, mutable image tags, and registry
  administrator credentials: denied; and
- independent cleanup, manual fallback, post-revocation denial, target
  zero-residue proof before cleanup-control deletion, and final zero-residue
  proof: required.

The exact proposed network plan is:

| Boundary                  | CIDR            |
| ------------------------- | --------------- |
| VNet                      | `10.77.0.0/20`  |
| Container Apps            | `10.77.0.0/23`  |
| Private endpoints         | `10.77.2.0/24`  |
| Management and cleanup    | `10.77.3.0/28`  |
| P2S gateway               | `10.77.3.32/27` |
| Azure Firewall            | `10.77.4.0/26`  |
| Azure Firewall management | `10.77.4.64/26` |

The proposed compute shapes are fixed without multiplying the shared worker
pool:

| Role                 | CPU        | Memory     | Min / normal / max |
| -------------------- | ---------- | ---------- | ------------------ |
| Web                  | 0.25 vCPU  | 0.5 GiB    | 1 / 1 / 2          |
| API                  | 0.5 vCPU   | 1 GiB      | 2 / 2 / 4          |
| Shared worker pool   | 0.5 vCPU   | 1 GiB      | 2 / 2 / 4          |
| Telemetry gateway    | 0.25 vCPU  | 0.5 GiB    | 1 / 1 / 1          |
| Migration job        | 0.5 vCPU   | 1 GiB      | 0 idle / 1 max     |
| Load-generator job   | 1 vCPU     | 2 GiB      | 0 idle / 1 max     |
| Fault-controller job | unresolved | unresolved | 0 idle / 1 max     |

Indexer, scanner, workflow, and agent work share the one bounded worker pool.
The fault-controller CPU and memory remain deferred to the later authorized
failure-runner checkpoint.

## Scope, identity, and immutable bindings

The exact-scope guard accepts only one canonical resource-group root or a
syntactically valid provider child under `<root>/providers/`. It validates
provider namespace and type/name pairs, including extension-resource
boundaries. It rejects parent, cross-subscription, sibling,
prefix-confusion, encoded, backslash, query, fragment, double-slash,
noncanonical subscription, invalid resource-group, trailing provider,
trailing child slash, and dot-segment scopes. It has no discovery or
automatic-renaming fallback and emits only a domain-separated scope-binding
checksum.

The mutable resource allowlist excludes subscription-scoped custom policy and
role definitions. Checkpoint 1 permits only resource-group-scoped policy and
role assignment boundaries; any later definition or external reference
requires separate scope design and authorization.

The image contract is bound to source commit
`1aca65c4a1d131dd420154efbe36e2c2204c3903`. A later verified image manifest
must bind one reviewed registry by checksum, one build manifest by checksum,
and all eight roles by immutable image digest. It never stores a live registry
host or Azure resource identifier.

Required future resource tags bind the contract version, source commit,
manifest checksum, cleanup checksum, cost ceiling, hard UTC expiry, opaque run
identity, data class, deny-public state, environment, and armed teardown
state. A resolved environment requires exact UTC provisioning, reserve,
expiry, and cleanup-timer verification timestamps. The cleanup timer must be
verified strictly before provisioning begins.

## Deterministic manifest binding

JSON input is parsed with duplicate-key and non-finite-number rejection.
Canonicalization:

1. normalizes strings and object keys to Unicode NFC;
2. rejects floating-point values;
3. sorts object keys ordinally;
4. preserves array order;
5. emits compact UTF-8 JSON without a BOM and with one terminal LF; and
6. hashes a domain-separated payload with SHA-256.

The canonicalizer validates the exact mapped schema and semantic contract,
then derives its hash domain from a closed `contractVersion` map; callers
cannot relabel one manifest as another type or checksum a malformed
known-version payload.
The full bundle checksum manifest sorts relative POSIX paths, rejects
symlinks, generated directories, compiled Python, and path escape, hashes
every included source file, and never self-embeds or writes generated state.
The validated Checkpoint 1 bundle contains 34 files and has checksum:

`b4f5ebbe9158d0264460158a31454e1ebf63ac038e51296c33cdfcb77b088297`

## Dependency order

Future deployment remains blocked, but its required order is checksum-closed:

1. validate contracts, exact scope, and immutable inputs;
2. arm cost and independent cleanup controls and prove the cleanup timer;
3. apply deny policies, create the private network, and apply deny-public
   controls;
4. create private telemetry before workloads that must emit evidence;
5. create identities, Key Vault, and private data services;
6. publish only digest-pinned images through the approved private source;
7. create internal compute, close bounded bootstrap egress, and prove security
   controls.

The teardown contract stops scheduled work and workloads, locks effects,
finalizes sanitized evidence, revokes temporary authority, proves denial,
preserves only approved bounded evidence, removes compute through network
dependencies, proves target-group zero residue, then removes cleanup controls
and proves final zero residue.

## Unresolved gates

The following ten gates remain unresolved and keep
`provisioningAuthorized=false`:

1. region and subscription availability;
2. exact provider API versions;
3. managed-identity environment mapping;
4. Redis custom ACL support;
5. private ACR source path;
6. telemetry gateway;
7. scanner-result bridge;
8. alert destination;
9. OpenAI/SMTP test providers; and
10. evidence retention.

The Redis service behavior is proposed as Balanced B0, two-node HA,
single-shard/nonclustered, `NoEviction`, Entra-only, access keys disabled, and
private access. Its literal provider enum and exact provider type/API remain
blocked. Managed Redis, Defender scanning, and scanner-event resource types
remain blocked candidates rather than executable allowlist entries.

No region, provider API version, provider capability, identity mapping, alert
route, external test provider, evidence destination, or price was invented or
selected in this checkpoint.

## Validation

| Check                                                     | Result                                                   |
| --------------------------------------------------------- | -------------------------------------------------------- |
| Focused API infrastructure contract tests                 | PASS — 84 tests                                          |
| Closed schema and template semantic validation            | PASS                                                     |
| External Draft 2020-12 validator                          | SKIPPED — no approved existing validator installed       |
| Checksum-closed schema and policy mutation tests          | PASS — all three schemas and five policy contracts       |
| Deterministic local preflight                             | PASS — 34 files, 10 unresolved gates, provisioning false |
| Non-mutating what-if entry point                          | PASS — fixed inert record and expected exit `4`          |
| Non-mutating deploy entry point                           | PASS — fixed inert record and expected exit `4`          |
| Non-mutating teardown entry point                         | PASS — fixed inert record and expected exit `4`          |
| Non-mutating zero-residue entry point                     | PASS — fixed inert record and expected exit `4`          |
| Ruff lint and formatting                                  | PASS — 9 Python files                                    |
| mypy                                                      | PASS — 8 source files                                    |
| Targeted Prettier JSON/Markdown formatting                | PASS                                                     |
| Repository hygiene                                        | PASS — 457 source files                                  |
| Standalone offline Bicep compilation                      | SKIPPED — no approved existing standalone compiler       |
| Azure CLI Bicep fallback                                  | NOT RUN — could install tooling or contact Azure         |
| Azure validation, deployment, load, and failure exercises | NOT RUN — outside Checkpoint 1                           |

Focused development initially exposed fail-open gaps in policy mutation,
verified cost, image registry binding, generated-residue handling, RFC 1918
enforcement, secret-name detection, exact-scope parsing, bounded error
handling, caller-selected canonicalization domains, source-commit binding,
lifecycle scope binding, dependency order, and permanent test discovery.
Those local contract and test defects were corrected before checkpoint
completion. No application code, migration, dependency, or Azure state
changed.

Final repository diff, whitespace, secret/private-identifier, local-path,
relative-link, generated-output, prohibited-scope, migration, protected-ref,
stash, recovery-artifact, clean-tree, and no-upstream checks are reported
with the completion commit.

## Protected boundary

- Azure was not contacted or changed.
- No Git remote was contacted or changed.
- No infrastructure was provisioned.
- No role, identity, policy, budget, credential, network, data, or provider
  registration changed.
- No dependency was installed.
- No application behavior or migration changed.
- Protected branches, tags, stashes, and recovery artifacts remain outside
  this checkpoint's write scope.
- Milestone 7.7 is not complete.
- Checkpoint 2 and Milestone 7.8 remain unstarted.

The next eligible action, only after separate approval, is Checkpoint 2
read-only capability and cost validation from the completion commit. This
handoff does not authorize Azure access, provisioning, workload, evidence, or
failure runners, or Milestone 7.8.
