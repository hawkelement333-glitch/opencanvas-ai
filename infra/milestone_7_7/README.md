# Milestone 7.7 Checkpoint 1 Infrastructure Contracts

This directory contains the resource-free, local-only infrastructure and
policy contract for Milestone 7.7. It does not contain a deployable
environment. Every Bicep module declares parameters and outputs only; no
module declares an Azure resource, role assignment, policy assignment, or
deployment script. `main.bicep` inventories, but does not invoke, the module
boundaries.

## Fixed checkpoint boundary

- Proposed IaC format: Bicep.
- Preferred compute topology: internal Azure Container Apps, pending later
  capability and cost validation.
- Region: unresolved and required at a later authorized preflight.
- Cost target: USD 100.00.
- Provisioning block: any estimate over USD 120.00.
- Absolute ceiling: USD 150.00, which is never an authorized target.
- Networking: private endpoints, no public application or data-service access,
  three exact infrastructure-only Standard public-IP exceptions for Azure
  Firewall Basic and P2S VPN, forced firewall routing, and explicit CIDR
  contracts.
- Capacity: fixed SKU and replica contracts for every resolved role, fixed
  lease and cleanup ceilings, and no mutable runtime selection. The
  fault-controller CPU and memory remain blocked for a later authorized
  runner checkpoint; its zero-idle and one-instance limits are fixed now.
- State: no migration, no application state, no deployment output, and no
  credentials or private Azure identifiers.

An unresolved gate, missing exact price, non-digest image, invalid scope,
public access, mutable SKU/replica selection, or expired lease keeps
`provisioningAuthorized` false.

## Contract layout

- `main.bicep` records the policy, platform, data, compute, observability, and
  lifecycle module inventory without creating nested deployments.
- `modules/` contains resource-free Bicep contracts.
- `manifests/` contains closed Draft 2020-12 schemas and intentionally
  unresolved templates.
- `policies/` contains the resource, network, lifecycle, dependency-order, and
  unresolved-gate allowlists.
- `scripts/` contains standard-library-only local validation,
  canonicalization, target-scope guards, and inert lifecycle entry points.
- `apps/api/tests/test_milestone_7_7_infrastructure_contracts.py` validates the
  local bundle without Azure, network, application imports, generated state,
  or dependency installation.

## Safe local validation

From the repository root, with the existing API virtual environment:

```powershell
$env:PYTHONDONTWRITEBYTECODE = "1"
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider `
  apps/api/tests/test_milestone_7_7_infrastructure_contracts.py
.\.venv\Scripts\python.exe infra/milestone_7_7/scripts/preflight.py `
  --bundle-root infra/milestone_7_7
```

The preflight prints a deterministic, domain-separated bundle checksum. It
does not write a manifest or inspect an Azure context.

## Lifecycle entry points

`what_if.py`, `deploy.py`, `teardown.py`, and `verify_zero_residue.py` are
intentionally non-mutating and non-deploying lifecycle contracts. They
validate the local bundle and emit a redacted denial record with
`status=checkpoint_1_inert`; they never invoke Azure tooling. Later work must
replace this boundary only after every unresolved gate has authoritative,
reviewed evidence and separate authorization.

Every lifecycle entry point requires both a synthetic or later-approved exact
target resource-group scope and a separate cleanup-control resource-group
scope. It validates their canonical structure and emits only a
domain-separated scope-binding checksum; it never echoes either scope.

Deployment order is fail-safe:

1. validate exact scope and immutable inputs;
2. arm independent cost and cleanup controls and prove the cleanup timer;
3. apply deny policies, create the isolated network, and apply deny-public
   controls;
4. create private telemetry before workloads that must emit evidence;
5. create identities, Key Vault, and private data services;
6. publish digest-pinned images, then create internal compute;
7. close bootstrap egress;
8. prove denial, lease, cost, and zero-public-access controls.

Teardown reverses authority before data or resource removal:

1. stop scheduled work and workloads, then lock external effects;
2. finalize sanitized evidence;
3. revoke temporary authority and prove post-revocation denial;
4. preserve only approved bounded evidence;
5. delete compute, data services, private telemetry, workload identities, and
   the private network;
6. prove target-group zero residue;
7. delete cleanup controls and prove final zero residue.

## Unresolved gates

Checkpoint 1 records, but does not resolve:

- region and subscription availability;
- exact provider API versions;
- managed-identity environment mapping;
- Redis custom ACL support;
- private ACR source path;
- telemetry gateway;
- scanner-result bridge;
- alert destination;
- OpenAI/SMTP test providers;
- evidence retention.

No Azure or Git remote operation is required or authorized by this bundle.
