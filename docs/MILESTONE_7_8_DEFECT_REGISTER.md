# Milestone 7.8 Defect Register

Date: 2026-08-13

Status: active; architecture and checkpoint-scope findings corrected and
validated; later audit surfaces remain unstarted

This register records only defects proved by the Milestone 7.8 audit. A
historical deferral, known limitation, warning, or missing validation is not
silently promoted to a defect. Remediation is mandatory only where the
governing repository contract says so; otherwise validation is required first
and remediation remains conditional on proof.

## Confirmed findings

| Identifier  | Source                                                                                                           | Description                                                                                                                                       | Severity       | Affected surface                                | Classification                           | Mandatory in 7.8 | Disposition                         |
| ----------- | ---------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- | -------------- | ----------------------------------------------- | ---------------------------------------- | ---------------- | ----------------------------------- |
| M78-AS-001  | Current status blocks in the implementation plan, architecture, progress, and roadmap; retained 7.7 terminal chain | Current governance documents still presented 7.7 as incomplete and 7.8 as unstarted after the terminal chain proved `MILESTONE_7_7_COMPLETE`.       | Not defined    | Architecture and checkpoint governance          | Audit finding; documentation debt        | Yes              | Corrected by this audit surface     |
| M78-AS-002  | Implementation-plan execution rule and final-validation no-upstream requirement; inherited 7.7 branch configuration | The inherited 7.7 branch tracked a remote branch, so it could not satisfy the required no-upstream 7.8 checkpoint evidence boundary.               | Not defined    | Local Git checkpoint boundary                    | Audit finding; operational/Git debt      | Yes              | Corrected with a fresh local branch |

No finding in this table claims that Milestone 7.7 was materially false or
unsafe. Both findings concern the safe entry boundary for new 7.8 work.

## Located Milestone 7.7 records that are not active defects

| Source                                                        | Exact record                                                                                                                                                                                                                           | Evidence classification               | Mandatory remediation in 7.8 |
| ------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------- | ---------------------------- |
| `preflight/milestone_7_7/scope-contract.json`                 | `azure-topology-preflight-execution`, `checkpoint-7`, `deployment`, `failure-injection`, `milestone-7.8`, `provisioning`, `runtime-validation`, `workload-execution`                                                                       | Historical scope deferral             | No                           |
| `preflight/milestone_7_7/operation-contracts.json`            | `separately-authorized-read-only-azure-observation`, `isolated-infrastructure-provisioning`, `runtime-gate-validation`, `managed-workload-and-failure-execution`, `milestone-7.7-final-consolidation`, `milestone-7.8`                       | Historical operation deferral         | No                           |
| `docs/MILESTONE_7_7_REMAINING_LIFECYCLE_COMPATIBILITY.md`     | Seven grouped defects in image-source identity, post-secret authority, scanner arguments, mutation attribution, stage separation, terminal producers/consumers, and simulator behavior                                                   | Closed defect inventory               | No; already corrected        |
| Retained nine-stage terminal lifecycle evidence               | Complete predecessor chain through soak, closeout, cleanup, zero-residue verification, and `MILESTONE_7_7_COMPLETE` at `b191a392922f94557e6ebf5914113b5e229ab00e`                                                                       | Durable completion evidence           | No                           |

The two JSON `deferredWork` arrays are immutable historical scope records.
They do not prove that every named item is a defect, and the validated terminal
chain supersedes their pre-completion 7.7 execution status without rewriting
them.

## Evidence debts routed to later audit surfaces

These items are exact persisted debts or limitations. They are not yet proved
implementation defects, so this first audit surface does not fix them.

| Identifier | Source                                      | Description                                                                                                  | Classification                                      | 7.8 contract consequence                                                                                                  |
| ---------- | ------------------------------------------- | ------------------------------------------------------------------------------------------------------------ | --------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| M78-D-001  | `docs/KNOWN_LIMITATIONS.md`                 | File unlink and relational commit are not atomic; staged trash/outbox cleanup is deferred.                  | Architectural, reliability, and operational debt    | The object lifecycle and failed-transaction audit must validate it; remediation is conditional on a proved defect.         |
| M78-D-002  | `docs/KNOWN_LIMITATIONS.md`                 | The shared-rate-limit adapter lacks recorded end-to-end revalidation against approved isolated Azure Redis. | Validation, reliability, and operational debt       | The shared-limit audit and final atomic-across-replicas scenario are mandatory; remediation is conditional on failure.      |
| M78-D-003  | `docs/KNOWN_LIMITATIONS.md`; `docs/DEPLOYMENT.md` | Full live telemetry destination, dashboards, alerts, retention, access, and revocation validation is absent. | Validation, operational, privacy, and security debt | The observability audit is mandatory; retained evidence must be assessed before any separately authorized Azure mutation.  |
| M78-D-004  | `docs/KNOWN_LIMITATIONS.md`                 | Production queue wake-up, operational telemetry, and external multi-service delivery require validation.    | Validation, reliability, and operational debt       | The durable-work audit is mandatory; remediation is conditional on a proved contract failure.                              |
| M78-D-005  | `docs/KNOWN_LIMITATIONS.md`                 | Backup/restore/rollback lacks validation against a managed production deployment.                           | Recovery and validation debt                        | The managed recovery scenario must be audited against retained evidence; production deployment remains excluded.           |
| M78-D-006  | `docs/KNOWN_LIMITATIONS.md`                 | No load/performance benchmarks or capacity claims are published.                                            | Capacity and documentation debt                     | The capacity audit and final documentation must record supported evidence and limitations; no unsupported claim is allowed. |
| M78-D-007  | `docs/MILESTONE_7_ARCHITECTURE.md`          | Stage 3 category-log rows had not arrived before cleanup.                                                    | Observability validation debt                       | The observability/evidence audit must decide whether later retained evidence closes or preserves this limitation.           |
| M78-D-008  | `docs/MILESTONE_7_ARCHITECTURE.md`          | Exact Stage 3 posted cost was unavailable because of throttling and delayed usage posting.                  | Operational and cost-evidence debt                  | Final results must record the proved cost boundary and any exact-cost limitation; remediation is not automatically required. |

This routing authorizes no Azure operation, migration, image build,
publication, scanner execution, secret access, or Git remote operation.
