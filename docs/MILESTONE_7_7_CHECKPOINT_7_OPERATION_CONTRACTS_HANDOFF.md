# Milestone 7.7 Internal Checkpoint 7 Operation Contracts Handoff

Date: 2026-07-30

Status:
`complete-local-operation-contracts-with-provisioning-blocked`

## Decision

Internal Checkpoint 7 is complete locally. The implementation adds one
versioned, machine-readable, default-deny definition matrix for exactly the 15
operation identities that remained blocked after Checkpoint 6.

Repository evidence did not establish a complete executable method, parser,
minimum retained projection, and semantic read-only proof for any of those 15
operations. The approved Checkpoint 7 outcome is therefore a complete explicit
blocked disposition for every slot. No command or provider result was
invented.

This classifier does not mean that an Azure operation ran, an infrastructure
or runtime gate passed, provisioning became authorized, Milestone 7.7
completed, or Milestone 7.8 began.

## Restart and protected boundary

The implementation began from:

- branch: `milestone-7-7-implementation-local`;
- source HEAD:
  `39f6409a44e1e9219e001eda80adb126559c94f2`;
- source parent:
  `2dfb22e2ea1eb27737e9af76053d76dcab8dd494`;
- clean tree and index;
- no upstream;
- sole Alembic head: `20260726_0028`;
- migration `20260726_0029`: absent;
- protected `0028` blob:
  `55c203e669cace5be64fc25cdcf0eb8c05519198`;
- five protected stash identities and eight recovery artifacts unchanged; and
- Checkpoint 6 classified
  `complete-with-provisioning-blocked`.

No stash content was inspected and no Git maintenance ran.

## Contract artifacts

The matrix version is:

`mobius.milestone-7.7.azure-topology-operation-contracts.v1`

Its domain-separated integrity SHA-256 is:

`100293931dcc71bb069e4f6fe06228360e0953b3b756544a555941d81bf8d6bc`

It binds, without altering:

- Checkpoint 6 operation inventory SHA-256:
  `923cbf934040405fd1702b49bd79d876ee3e85fe88d68bbb3d94f980fa45b843`;
- Checkpoint 6 scope SHA-256:
  `a98776f4d2ea33f64e28514fc7c13d2e6160a79ea29247f79fc71f4ffe529e3e`;
- the 18-slot historical inventory;
- the historical scope contract; and
- the persisted Checkpoint 6 evidence.

An exact 15-row supersession map binds every prior blocked operation identity
to the same Checkpoint 7 identity with disposition `preserved-blocked`.
Historical inventory, scope, and evidence remain immutable and are not
reclassified.

The implementation adds:

- `operation-contracts.json`;
- `operation-contracts.schema.json`;
- `operation_contracts.py`;
- `verify_operation_contracts.py`; and
- focused fail-closed tests.

## Exact operation registry

The closed order is:

1. `regional-service-availability`;
2. `provider-registration-api-versions`;
3. `regional-sku-capabilities`;
4. `subscription-quota-bounded-usage`;
5. `private-endpoint-network-support`;
6. `private-dns-prerequisites`;
7. `managed-identity-support`;
8. `scoped-rbac-prerequisites`;
9. `telemetry-diagnostic-prerequisites`;
10. `evidence-retention-prerequisites`;
11. `scanner-result-bridge-prerequisites`;
12. `external-test-provider-prerequisites`;
13. `bounded-cost-budget-prerequisites`;
14. `provisioning-dependency-blockers`; and
15. `private-acr-source-prerequisites`.

No identity was renamed, added, removed, merged, split, or reordered.

## Fail-closed behavior

Every entry records:

- the supported infrastructure gate or gates;
- required inputs and prerequisites;
- approved future region and scope boundary;
- required authority level and denied current authority state;
- a future fresh sanitized minimum-projection evidence requirement;
- no-secret, no-private-data privacy policy;
- zero current Azure cost effect;
- one maximum future attempt, a 30-second timeout, and zero retries;
- exact stop and failure behavior; and
- a precise current blocker.

Every entry also fixes:

- `definitionStatus: blocked`;
- `proofStatus: unproved`;
- `executionAuthorized: false`;
- `mutationAuthorized: false`;
- `provisioningAuthorized: false`;
- `dataPlaneAllowed: false`;
- `semanticReadOnlyVerified: false`;
- `methodDefinition: null`;
- `parserDefinition: null`; and
- an empty retained projection.

Missing input, prerequisite, scope, authority, evidence, freshness, or
integrity denies execution. Unknown fields, operations, states, authority, or
transitions are rejected. Even a caller that claims every future condition is
present receives a denied decision because the operations remain blocked and
no execution authorization exists.

A contract definition is not execution evidence. Fabricated or incomplete
evidence cannot prove an operation. Contract validation cannot change an
infrastructure or runtime gate.

## Preserved gates and authority

All ten infrastructure gates remain `blocked`:

- alert destination;
- evidence retention;
- exact provider API versions;
- managed-identity environment mapping;
- OpenAI/SMTP test providers;
- private ACR source path;
- Redis custom ACL support;
- region and subscription availability;
- scanner-result bridge; and
- telemetry gateway.

All five runtime gates remain `unproved`:

- cleanup-supervisor runtime proof;
- effect-lock runtime proof;
- fault-controller shape;
- isolated environment; and
- live-failure authorization.

Azure access, external calls, execution, mutation, provisioning, data-plane
access, workloads, faults, deployments, and migration remain unauthorized.

## Validation

The focused Checkpoint 7 suite passed 37 tests. It covers exact identity and
order, schema and version closure, missing/duplicate/additional operations,
unknown fields, missing inputs and prerequisites, state and authority
strengthening, fabricated methods/parsers/evidence, gate upgrades, retry
changes, deterministic reproduction, integrity tampering, privacy, denied
execution, no external clients, and migration absence.

The complete affected internal Checkpoint 1–7 campaign covers 598 tests. Its
final result is 597 passed and one existing Windows symlink-permission skip.

The deterministic verifier reports:

- 15 operations;
- 15 blocked operation definitions;
- 15 unproved operation outcomes;
- ten blocked infrastructure gates;
- five unproved runtime gates;
- Azure access unauthorized;
- execution and mutation unauthorized; and
- provisioning unauthorized.

Strict mypy passes for both new source modules. Ruff lint and formatting pass
for the new source and test files. Direct installed Prettier passes for all
nine changed Markdown and JSON files. Repository hygiene passes for 519 source
files, and all 60 changed-document local links resolve.

`git diff --check`, trailing whitespace, secret patterns, raw identifiers,
private addresses, personal paths, generated residue, prohibited scope,
dependency and lock files, and historical-evidence checks pass. The sole
Alembic head remains `20260726_0028`, its protected blob remains
`55c203e669cace5be64fc25cdcf0eb8c05519198`, and migration
`20260726_0029` remains absent.

## Finite Milestone 7.7 closeout map

No later internal checkpoint number is defined. Exactly six work packages
remain, organized by the governing formal Milestone 7.7 exit requirements:

1. close the read-only topology, provider, cost, authority, and prerequisite
   evidence gates;
2. provision and secure one approved isolated synthetic environment;
3. prove monitoring, alerts, runbooks, effect lock, cleanup supervision,
   evidence retention, and supply-chain controls;
4. execute bounded stress, soak, spike, mixed, capacity, and recovery-under-
   load measurements;
5. execute the closed failure, resilience, isolation, revocation, limit,
   security, and cost-ceiling exercises; and
6. revoke access, clean synthetic data, delete all temporary infrastructure,
   prove zero residue, consolidate evidence and supported limits, resolve all
   critical/high findings, and complete the final Milestone 7.7 local audit.

Packages 1–3 are ordered prerequisites. Packages 4 and 5 may share the same
approved isolated environment after package 3 passes, but destructive faults
remain serialized and each exercise must restore its baseline. Package 6 is
last and is the only package that may close formal Milestone 7.7.

The detailed authorization, cost, evidence, cleanup, and acceptance boundary
for these six packages must be approved separately. This handoff grants no
such authority.

## Final boundary

- Internal Checkpoint 6:
  `complete-with-provisioning-blocked`.
- Internal Checkpoint 7:
  `complete-local-operation-contracts-with-provisioning-blocked`.
- Formal Milestone 7.7: in progress.
- Provisioning: unauthorized.
- Migration `20260726_0029`: absent.
- Milestone 7.8: unstarted.

No Azure access, Azure command, Git remote operation, package-manager action,
software installation, application, worker, service, browser, migration,
deployment, workload, fault, or probe occurred during this implementation.

## Local provider-prerequisite binding

Date: 2026-07-31

Status: Milestone 7.7 remains blocked by the dedicated non-production
OpenAI/SMTP provider prerequisite

This targeted local pass began from branch
`milestone-7-7-implementation-local` at
`5325961783b3f9a8a2766d418d437b440186bf4d`, with parent
`39f6409a44e1e9219e001eda80adb126559c94f2`, a clean tree and index, no
upstream, sole Alembic head `20260726_0028`, protected `0028` blob
`55c203e669cace5be64fc25cdcf0eb8c05519198`, and migration
`20260726_0029` absent. Protected references, five stash identities, eight
recovery artifacts, dependency and lock files, and historical evidence were
unchanged.

The pass used no Azure, OpenAI, SMTP, Git remote, package manager, credential,
provider account, non-example environment file, or secret value. It created
no resource or authority and incurred USD 0.

### Mechanical local corrections

Ruff reproduced and mechanically corrected two existing local defects:

- the redundant blank line that violated import ordering in
  `apps/api/tests/test_milestone_7_7_azure_topology_execution.py`; and
- line wrapping selected by the repository's Ruff formatter in
  `preflight/milestone_7_7/execution.py`.

The changes alter no runtime expression, test assertion, Azure command,
operation definition, authority, evidence contract, or security decision.

### Repository-defined OpenAI prerequisite

The dedicated non-production OpenAI configuration is:

- `OPENCANVAS_AI_PROVIDER=openai`;
- `OPENCANVAS_EMBEDDING_PROVIDER=openai`;
- one server-only API key supplied through exactly one supported alias,
  canonically `OPENAI_API_KEY` or alternatively
  `OPENCANVAS_OPENAI_API_KEY`;
- `OPENCANVAS_OPENAI_MODEL`, whose repository default is
  `gpt-5.6-terra`;
- `OPENCANVAS_OPENAI_EMBEDDING_MODEL`, whose repository default is
  `text-embedding-3-small`;
- `OPENCANVAS_EMBEDDING_DIMENSIONS=1536`, which is fixed by validation;
- bounded `OPENCANVAS_OPENAI_TIMEOUT_SECONDS`,
  `OPENCANVAS_AI_MAX_OUTPUT_TOKENS`,
  `OPENCANVAS_AI_CONTEXT_CHARACTER_LIMIT`, and
  `OPENCANVAS_EMBEDDING_BATCH_SIZE`; and
- the existing configuration identities
  `OPENCANVAS_AI_PROVIDER_CONFIGURATION_VERSION=openai-responses-v1` and
  `OPENCANVAS_EMBEDDING_PROVIDER_CONFIGURATION_VERSION=openai-embeddings-v1`.

The API key is secret. Provider modes, model names, dimensions, limits, and
configuration-version identifiers are non-secret configuration. Presence of
the key proves only configuration presence. It does not prove project
ownership, model entitlement, quota, rate limits, spending controls, request
success, citation behavior, embedding shape, revocation, or isolation.

The live provider must support the Responses API, structured grounded
responses, and the embeddings API used by the committed adapters. Mock
providers remain invalid in staging and production. Provider exceptions are
converted to generic application errors, and operational telemetry records
only the operation class, outcome, duration, and bounded usage count, never a
prompt, context, result, key, or provider credential.

### Repository-defined SMTP prerequisite

The SMTP configuration is:

- `OPENCANVAS_PASSWORD_RESET_PROVIDER=smtp`;
- non-empty `OPENCANVAS_SMTP_HOST`;
- `OPENCANVAS_SMTP_PORT`, bounded from 1 through 65535 and defaulting to
  `587`;
- non-empty `OPENCANVAS_SMTP_FROM_ADDRESS`;
- optional `OPENCANVAS_SMTP_USERNAME` and `OPENCANVAS_SMTP_PASSWORD`; and
- `OPENCANVAS_SMTP_STARTTLS`, defaulting to `true`.

The SMTP password is secret. The username is credential metadata and must be
handled through the same managed-secret boundary when authentication is
used. Host, port, sender, and STARTTLS selection are non-secret configuration,
although evidence must redact private hosts and email addresses.

The committed adapter opens SMTP with a fixed 15-second timeout, starts TLS
only when configured, authenticates only when a username is present, and then
sends password-reset or workspace-invitation mail. The deployed settings
boundary requires the provider mode, host, and sender, but does not require
STARTTLS or authenticated SMTP and does not validate username/password
pairing. Those choices therefore remain unresolved provider-contract
decisions; local settings acceptance cannot promote the infrastructure gate.
Generic delivery errors retain no host, recipient, password, or provider
response.

### Secret, isolation, and evidence boundary

The approved production principle remains managed secret references resolved
by workload identity and injected by the deployment platform into the
server-only settings boundary. Milestone 7.7 proposes a private standard Key
Vault, but the exact workload-identity-to-secret mapping remains unproved and
must be authorized with the later infrastructure work. No secret belongs in a
tracked file, non-example `.env` file, client bundle, command transcript,
evidence object, exception, or telemetry field.

OpenAI and SMTP must use dedicated non-production accounts or projects,
least-privilege send/inference-only credentials, synthetic data, an exact
synthetic-recipient allowlist, bounded provider-side rate and quota limits,
and a separately approved hard spending boundary. Production, customer,
personal, and sensitive data remain prohibited. The SMTP vendor, account
owner, region, authentication profile, sender, recipient allowlist, OpenAI
project owner, model entitlement, numeric provider limits, and provider
budget are owner decisions not established by this local pass.

Later sanitized gate evidence must bind the source commit and configuration
versions and retain only:

- presence booleans for required configuration, never values;
- approved non-secret provider/model/configuration identities;
- provider-side isolation, quota, rate, recipient, and spending-limit states;
- UTC observation and expiry times;
- bounded outcomes and usage counts for one synthetic Responses request, one
  structured grounded request with exact allowed citations, and one
  1536-dimension embedding request;
- one synthetic SMTP delivery outcome to an approved test recipient, plus
  STARTTLS and authentication-mode booleans;
- sanitized failure outcomes for missing/invalid credentials, unavailable
  models, quota/rate denial, SMTP TLS/authentication failure, and dependency
  unavailability; and
- rotation, replacement-readiness, immediate old-credential revocation, and
  post-revocation denial results.

Provider receipts, project/account identities, email addresses, hosts, raw
responses, tokens, and credentials must be omitted or transformed by the
approved evidence contract. Missing, incomplete, unsafe, mock-only, stale,
over-broad, conflicting, or unsanitized evidence keeps
`openai-smtp-test-providers` blocked. Provider evidence alone cannot authorize
Azure provisioning.

The 15 operation definitions remain blocked and unproved, all ten
infrastructure gates remain blocked, all five runtime gates remain unproved,
provisioning remains unauthorized, formal Milestone 7.7 remains blocked, and
Milestone 7.8 remains unstarted.

### Local validation

Focused Ruff lint and format checks pass for the two mechanically corrected
files. The deterministic operation-contract verifier remains valid at
`100293931dcc71bb069e4f6fe06228360e0953b3b756544a555941d81bf8d6bc`
and reports 15 blocked operations, ten blocked infrastructure gates, five
unproved runtime gates, and provisioning unauthorized. The focused
operation-contract suite passes 37 tests. The deployed-settings and
telemetry-redaction group passes 28 tests.

The complete affected campaign collected 598 tests and finished with 597
passed and one existing Windows symlink-permission skip. The first broad
invocation omitted Python's no-bytecode flag, created one disposable
`infra/milestone_7_7/scripts/__pycache__` directory, and correctly failed 25
bundle-integrity tests while 572 passed and one skipped. The directory was
removed, its absence was proved, and the identical campaign passed with
bytecode and pytest cache generation disabled. A separate initial direct
`pytest.exe` invocation also stopped during collection because that launcher
did not place the repository root on the import path; using the virtual
environment's Python module entry point resolved the invocation without a
repository change.

Strict mypy passes five source files. Full affected Ruff lint passes and Ruff
format reports 14 files formatted. Installed Prettier passes both changed
documents. Repository hygiene passes 519 source files, and all 31 local links
in the changed documents resolve. Diff, trailing-whitespace, secret-pattern,
private-identifier, personal-path, prohibited-scope, dependency/lock,
generated-residue, migration, and protected-state checks pass.

### Presence-only verification procedure

After secret injection, the owner may run this value-free process-environment
check. It emits exact configuration names and booleans, never values. A
positive result proves presence only and must be followed by a separately
authorized bounded live-provider validation.

```powershell
$names = @(
    "OPENCANVAS_AI_PROVIDER",
    "OPENCANVAS_EMBEDDING_PROVIDER",
    "OPENAI_API_KEY",
    "OPENCANVAS_OPENAI_API_KEY",
    "OPENCANVAS_OPENAI_MODEL",
    "OPENCANVAS_OPENAI_EMBEDDING_MODEL",
    "OPENCANVAS_EMBEDDING_DIMENSIONS",
    "OPENCANVAS_OPENAI_TIMEOUT_SECONDS",
    "OPENCANVAS_AI_MAX_OUTPUT_TOKENS",
    "OPENCANVAS_AI_CONTEXT_CHARACTER_LIMIT",
    "OPENCANVAS_EMBEDDING_BATCH_SIZE",
    "OPENCANVAS_AI_PROVIDER_CONFIGURATION_VERSION",
    "OPENCANVAS_EMBEDDING_PROVIDER_CONFIGURATION_VERSION",
    "OPENCANVAS_PASSWORD_RESET_PROVIDER",
    "OPENCANVAS_SMTP_HOST",
    "OPENCANVAS_SMTP_PORT",
    "OPENCANVAS_SMTP_FROM_ADDRESS",
    "OPENCANVAS_SMTP_STARTTLS",
    "OPENCANVAS_SMTP_USERNAME",
    "OPENCANVAS_SMTP_PASSWORD"
)
$names | ForEach-Object {
    [pscustomobject]@{
        Name = $_
        Present = -not [string]::IsNullOrWhiteSpace(
            [Environment]::GetEnvironmentVariable($_, "Process")
        )
    }
} | ConvertTo-Json
```

## Owner action checklist

- [ ] Select and own one dedicated non-production OpenAI project with access
      to the approved Responses and embedding models; decide the approved
      model identifiers, hard spend, rate, and quota limits.
- [ ] Select and own one dedicated non-production SMTP service; decide its
      region, authenticated-versus-private-relay profile, STARTTLS policy,
      approved sender, synthetic recipient allowlist, send-rate/quota, and
      hard spend limit.
- [ ] Put the OpenAI API key supplied through exactly one of
      `OPENAI_API_KEY` or `OPENCANVAS_OPENAI_API_KEY` and, when authenticated
      SMTP is selected, `OPENCANVAS_SMTP_USERNAME` and
      `OPENCANVAS_SMTP_PASSWORD` only in the approved managed secret store.
      Grant only the workload identity that needs each secret; grant no
      provider, billing, mailbox, or administrative authority to the
      application credential.
- [ ] Supply non-secret deployment configuration for
      `OPENCANVAS_AI_PROVIDER`, `OPENCANVAS_EMBEDDING_PROVIDER`,
      `OPENCANVAS_OPENAI_MODEL`, `OPENCANVAS_OPENAI_EMBEDDING_MODEL`,
      `OPENCANVAS_EMBEDDING_DIMENSIONS`,
      `OPENCANVAS_OPENAI_TIMEOUT_SECONDS`,
      `OPENCANVAS_AI_MAX_OUTPUT_TOKENS`,
      `OPENCANVAS_AI_CONTEXT_CHARACTER_LIMIT`,
      `OPENCANVAS_EMBEDDING_BATCH_SIZE`,
      `OPENCANVAS_AI_PROVIDER_CONFIGURATION_VERSION`,
      `OPENCANVAS_EMBEDDING_PROVIDER_CONFIGURATION_VERSION`,
      `OPENCANVAS_PASSWORD_RESET_PROVIDER`, `OPENCANVAS_SMTP_HOST`,
      `OPENCANVAS_SMTP_PORT`, `OPENCANVAS_SMTP_FROM_ADDRESS`, and
      `OPENCANVAS_SMTP_STARTTLS`; inject the OpenAI key through exactly one of
      `OPENAI_API_KEY` or `OPENCANVAS_OPENAI_API_KEY`.
- [ ] Approve restart-based rotation: install a replacement secret reference,
      validate one isolated replacement instance, shift only after readiness,
      revoke the old credential immediately after drain, prove denial, and
      restore the prior reference without widening authority if validation
      fails.
- [ ] After secret injection, run the documented value-free presence-only
      procedure, then obtain separate authorization for bounded live-provider
      validation; presence alone cannot promote a gate.
- [ ] Provide the sanitized, fresh evidence listed above. Milestone 7.7 may
      resume only after that evidence passes privacy and integrity validation
      and the remaining operation and infrastructure gates receive their own
      authority.
