"""Fail-closed scanner-result bridge serialization for post-secret deployment.

This module has no Azure client. It accepts only a complete sanitized evidence
envelope and produces explicit Bicep parameters for the post-secret executor.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from performance.milestone_7_7.framework import load_json
from preflight.milestone_7_7.managed_binding_contracts import REPOSITORY_ROOT
from preflight.milestone_7_7.scanner_result_bridge import (
    ScannerResultBridgeDeploymentEvidence,
    build_scanner_result_bridge_deployment_evidence,
    deployment_evidence_from_mapping,
)

_CONTRACT_VERSION: Final = "mobius.scanner-result-bridge.v1"


class ScannerBridgeDeploymentError(ValueError):
    """A deterministic, non-sensitive post-secret admission failure."""


class AzureCommandError(RuntimeError):
    def __init__(self, sanitized_azure_error_code: str) -> None:
        super().__init__("lifecycle-command-nonzero")
        self.sanitized_azure_error_code = sanitized_azure_error_code


class PublisherAccessPending(RuntimeError):
    pass


class PublisherOAuthTransient(RuntimeError):
    pass


class DockerPushTransient(RuntimeError):
    pass


def format_utc(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _external_path(path: Path) -> Path:
    resolved = path.resolve()
    repository = REPOSITORY_ROOT.resolve()
    if resolved == repository or repository in resolved.parents:
        raise ScannerBridgeDeploymentError("scanner-bridge-evidence-inside-repository")
    return resolved


def load_deployment_evidence(
    path: Path, *, repository_head: str, now: datetime
) -> ScannerResultBridgeDeploymentEvidence:
    """Load a typed external artifact and bind it to the active repository HEAD."""

    value = load_json(_external_path(path))
    if not isinstance(value, Mapping):
        raise ScannerBridgeDeploymentError("scanner-bridge-evidence-malformed")
    try:
        evidence = deployment_evidence_from_mapping(value, now=now)
    except ValueError as exc:
        raise ScannerBridgeDeploymentError("scanner-bridge-evidence-invalid") from exc
    if evidence.control_plane_head != repository_head:
        raise ScannerBridgeDeploymentError("scanner-bridge-control-plane-head-mismatch")
    return evidence


def bicep_parameters(
    evidence: ScannerResultBridgeDeploymentEvidence, *, repository_head: str, now: datetime
) -> list[str]:
    """Return explicit parameters; callers cannot pass a bridge-resolution flag."""

    validated = build_scanner_result_bridge_deployment_evidence(evidence, now=now)
    if validated.control_plane_head != repository_head:
        raise ScannerBridgeDeploymentError("scanner-bridge-control-plane-head-mismatch")
    return [
        f"scannerResultBridgeContractVersion={_CONTRACT_VERSION}",
        "scannerResultBridgeState=RESOLVED",
        f"scannerResultBridgeEvidenceIntegrity={validated.integrity_sha256()}",
        f"scannerResultBridgeObservedAtUtc={validated.observed_at_utc}",
        f"scannerResultBridgeProviderProofIntegrity={validated.provider_capability_proof_integrity}",
        f"scannerResultBridgeProducerProofIntegrity={validated.producer_proof_integrity}",
        f"scannerResultBridgeTransportProofIntegrity={validated.transport_proof_integrity}",
        f"scannerResultBridgeConsumerProofIntegrity={validated.consumer_proof_integrity}",
        f"scannerResultBridgeIdentityRbacProofIntegrity={validated.assignment_proof_integrity}",
        f"scannerResultBridgePrivatePathProofIntegrity={validated.private_path_proof_integrity}",
        f"scannerResultBridgeCorrelationProofIntegrity={validated.legacy_evidence.integrity_sha256()}",
        f"scannerResultBridgeRevocationProofIntegrity={validated.revocation_proof_integrity}",
        f"scannerResultBridgeCleanupInventoryIntegrity={validated.cleanup_inventory_integrity}",
        "scannerResultBridgeUnresolvedReasonCount=0",
    ]


def deployment_parameters(
    *,
    stage: str,
    ledger_integrity: str,
    repository_head: str,
    cleanup_at_utc: str,
    expected_cost: int,
    maximum_cost: int,
    lifecycle_tags: Mapping[str, object],
    runtime_config: Mapping[str, object] | None,
    scanner_bridge_evidence: ScannerResultBridgeDeploymentEvidence | None,
    now: datetime,
) -> list[str]:
    """Build the existing Bicep input vector with a validated bridge extension."""

    import json

    parameters = [
        "checkpointMode=contract-only",
        "deploymentEnabled=false",
        "managedBindingMode=managed-binding-one-run",
        "managedBindingDeploymentEnabled=true",
        f"deploymentStage={stage}",
        "location=southcentralus",
        "cleanupLocation=westus",
        "redisLocation=australiacentral",
        f"authorizationLedgerSha256={ledger_integrity}",
        f"cleanupAtUtc={cleanup_at_utc}",
        f"expectedUsdCents={expected_cost}",
        f"maximumPlausibleUsdCents={maximum_cost}",
        "lifecycleTags=" + json.dumps(lifecycle_tags, separators=(",", ":"), sort_keys=True),
    ]
    if runtime_config is None:
        return parameters
    if scanner_bridge_evidence is None:
        raise ScannerBridgeDeploymentError("scanner-bridge-evidence-absent")
    for key in ("apiImageDigest", "smtpHost", "smtpFromAddress"):
        value = runtime_config.get(key)
        if not isinstance(value, str) or not value:
            raise ScannerBridgeDeploymentError("post-secret-runtime-config-invalid")
        parameters.append(f"{key}={value}")
    return parameters + bicep_parameters(
        scanner_bridge_evidence, repository_head=repository_head, now=now
    )


def deployment_name(stage: str, ledger_integrity: str, *, allowed_stages: set[str]) -> str:
    """Bind each deployment name to its validated one-run ledger."""

    if stage not in allowed_stages or len(ledger_integrity) != 64:
        raise ScannerBridgeDeploymentError("deployment-history-binding-invalid")
    if any(character not in "0123456789abcdef" for character in ledger_integrity):
        raise ScannerBridgeDeploymentError("deployment-history-binding-invalid")
    name = f"mobius77-managed-binding-{stage}-{ledger_integrity[:16]}"
    if len(name) > 64:
        raise ScannerBridgeDeploymentError("deployment-history-binding-invalid")
    return name


def parse_post_secret_outputs(
    response: Mapping[str, object], *, evidence: ScannerResultBridgeDeploymentEvidence
) -> dict[str, str]:
    """Validate the minimal ARM output projection before later post-secret gates."""

    properties = response.get("properties")
    if not isinstance(properties, Mapping):
        raise ScannerBridgeDeploymentError("post-secret-deployment-output-malformed")
    outputs = properties.get("outputs")
    if not isinstance(outputs, Mapping):
        raise ScannerBridgeDeploymentError("post-secret-deployment-output-malformed")

    def value(name: str) -> object:
        output = outputs.get(name)
        if not isinstance(output, Mapping) or set(output) - {"type", "value"}:
            raise ScannerBridgeDeploymentError("post-secret-deployment-output-malformed")
        return output.get("value")

    integrity = value("scannerResultBridgeEvidenceIntegrity")
    state = value("scannerResultBridgeState")
    resolved = value("scannerResultBridgeResolved")
    enabled = value("deploymentEnabled")
    job_name = value("migrationJobName")
    job_id = value("migrationJobResourceId")
    if (
        integrity != evidence.integrity_sha256()
        or state != "RESOLVED"
        or resolved is not True
        or enabled is not True
        or not isinstance(job_name, str)
        or not job_name
        or not isinstance(job_id, str)
        or not job_id
    ):
        raise ScannerBridgeDeploymentError("post-secret-deployment-bridge-output-invalid")
    return {
        "scanner-result-bridge-evidence-integrity": integrity,
        "migration-job-name": job_name,
        "migration-job-resource-id": "redacted",
    }
