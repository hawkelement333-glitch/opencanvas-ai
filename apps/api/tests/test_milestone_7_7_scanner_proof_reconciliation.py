from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from infra.milestone_7_7 import scanner_bridge_recovery_adapter as adapter
from infra.milestone_7_7.scripts import managed_binding_lifecycle
from performance.milestone_7_7.framework import JsonValue

_SUBSCRIPTION = "/subscriptions/9f7f5a53-95a6-469e-9b95-e4072f0fd226"
_TARGET = f"{_SUBSCRIPTION}/resourceGroups/rg-solarplexus-mobius-77-staging"
_QUARANTINE_SCOPE = (
    f"{_TARGET}/providers/Microsoft.Storage/storageAccounts/stmobius7711564669/"
    "blobServices/default/containers/quarantine"
)


def _terminal_evidence() -> dict[str, JsonValue]:
    body: dict[str, JsonValue] = {
        "blobEvidenceSha256": "40a6898b01af28ece53c08aa0d795387a0d03aefdfde6060b45eaf816e0aae8f",
        "blobTagResult": "No threats found",
        "blobTagsTimestamp": {
            "canonicalUtc": "2026-08-11T17:15:16Z",
            "fractionalSecondDigits": 0,
            "parserNormalizationPath": adapter.SCAN_FINISHED_NORMALIZATION_PATH,
            "rawLengthBytes": 20,
            "rawValue": "2026-08-11 17:15:16Z",
            "rawValueSha256": "91bc390b355ad83e5bed3047b605c7afd4f1bc8e1687992b0a4558379b749230",
            "timezoneRepresentation": "Z",
        },
        "comparisonContract": adapter.LEGACY_SCAN_FINISHED_COMPARISON_CONTRACT,
        "comparisonDecision": "different-instant",
        "correlationIdSha256": "6ce04f905e9cd34bc3acf207d875bee744ddc6b83cccd63be67290133a91c018",
        "etagComparison": "matched",
        "etagSha256": "98840692bf4ae5b15e2074e4489dc0ba37bb7c121b2c3ab25991e33ba25d39d8",
        "logAnalyticsEvidenceSha256": (
            "b1ab972a3310f7ffaf4cb15e75672b273aedf55cb55daec2c81e3b455399e1ac"
        ),
        "logAnalyticsMinusBlobTagsMicroseconds": 453_955,
        "logAnalyticsResult": "No threats found",
        "logAnalyticsTimestamp": {
            "canonicalUtc": "2026-08-11T17:15:16.453955Z",
            "fractionalSecondDigits": 7,
            "parserNormalizationPath": adapter.SCAN_FINISHED_NORMALIZATION_PATH,
            "rawLengthBytes": 28,
            "rawValue": "2026-08-11T17:15:16.4539552Z",
            "rawValueSha256": "c67c89ffbc934ebb453f30192b0bf4fca215c4d4709b4b80c405d98ac3e7fb95",
            "timezoneRepresentation": "Z",
        },
        "providerVersionSha256": "2be3a337c472a96dc52439c23ed547ae69ac514a34e0a3d18b5fabdc623e1106",
        "uriComparison": "matched",
        "uriSha256": "f444056fb0e2e0e54feafc19bade55d7b63efa50977ea718fbbd1c3237dced86",
    }
    return {
        **body,
        "integritySha256": adapter._scanner_runtime_hash(
            body,
            "mobius.scanner-bridge.scan-finished-comparison.v1",
        ),
    }


def _failure_marker() -> dict[str, JsonValue]:
    body: dict[str, JsonValue] = {
        "attemptCount": 120,
        "blobTagObservationCount": 120,
        "failureCode": "scanner-correlation-scan-finished-mismatch",
        "marker": "SCANNER_RESULT_BRIDGE_FAILED",
        "schemaVersion": "mobius.scanner-result-bridge.proof-failure.v2",
        "terminalEvidence": _terminal_evidence(),
    }
    return {
        **body,
        "markerIntegritySha256": adapter._scanner_runtime_hash(
            body,
            "mobius.scanner-bridge.proof-failure-marker.v2",
        ),
    }


def _blob_observation() -> dict[str, JsonValue]:
    body: dict[str, JsonValue] = {
        "differentBlobVersion": False,
        "exactComparisonDecision": "accepted",
        "httpStatus": 200,
        "marker": adapter.BLOB_TAG_OBSERVATION_MARKER,
        "parserNormalizationPath": adapter.BLOB_TAG_NORMALIZATION_PATH,
        "queriedBlobUriSha256": "f444056fb0e2e0e54feafc19bade55d7b63efa50977ea718fbbd1c3237dced86",
        "queriedBlobVersionIdSha256": (
            "2be3a337c472a96dc52439c23ed547ae69ac514a34e0a3d18b5fabdc623e1106"
        ),
        "queriedEtagSha256": "98840692bf4ae5b15e2074e4489dc0ba37bb7c121b2c3ab25991e33ba25d39d8",
        "requestCorrelationId": "6577eac0-e01e-005c-48bd-2907c9000000",
        "requiredKeysFound": [adapter.BLOB_RESULT_TAG, adapter.BLOB_SCAN_TIME_TAG],
        "requiredKeysMissing": [],
        "responseEmpty": False,
        "responseEtagSha256": None,
        "responseVersionIdSha256": None,
        "returnedTagKeys": [adapter.BLOB_RESULT_TAG, adapter.BLOB_SCAN_TIME_TAG],
        "schemaVersion": adapter.BLOB_TAG_OBSERVATION_SCHEMA,
        "tagCount": 2,
        "unexpectedKeys": [],
        "versionIdentityPath": "request-version-id-plus-if-match",
    }
    return {
        **body,
        "integritySha256": adapter._blob_tag_observation_hash(body),
    }


def _ordinal_binding() -> dict[str, JsonValue]:
    body: dict[str, JsonValue] = {
        "absoluteTotalExecutionCeiling": 2,
        "apiImageDigest": adapter.RETAINED_PROOF_IMAGE,
        "authorizedAdditionalExecutionCount": 1,
        "authorizedAtUtc": "2026-08-11T16:50:46Z",
        "buildInputSha256": "199863dea1c219da1f20adf6e38ecc13c5c348803f361dc4f55219046e89487c",
        "cleanupDeadlineUtc": adapter.RETAINED_PROOF_CLEANUP_DEADLINE,
        "cleanupGeneration": 4,
        "expiresAtUtc": "2026-08-11T17:50:46Z",
        "foundationIntegritySha256": (
            "9ec476ffe81b389179383d7a9aa14fcb4dab7fd642df5156be8b6b5852ba1d4d"
        ),
        "ociConfigDigest": adapter.RETAINED_PROOF_OCI_CONFIG,
        "priorExecutionCorrelationId": "1d128fc4-63bf-474b-b304-4ae9f8969663",
        "priorExecutionCount": 1,
        "repositoryHead": adapter.RETAINED_PROOF_SOURCE_HEAD,
        "schemaVersion": "mobius.milestone-7.7.scanner-proof-ordinal-binding-evidence.v1",
        "typedAuthorizationIntegritySha256": adapter.RETAINED_PROOF_AUTHORIZATION_INTEGRITY,
    }
    return {
        **body,
        "integritySha256": adapter._canonical_hash(
            body,
            "solarplexus-mobius/milestone-7.7/scanner-proof-ordinal-binding-evidence/v1",
        ),
    }


def _execution_start() -> dict[str, JsonValue]:
    body: dict[str, JsonValue] = {
        "absoluteTotalExecutionCeiling": 2,
        "apiImageDigest": adapter.RETAINED_PROOF_IMAGE,
        "authorizationIntegritySha256": adapter.RETAINED_PROOF_AUTHORIZATION_INTEGRITY,
        "executionName": adapter.RETAINED_PROOF_EXECUTION,
        "executionOrdinal": 2,
        "ociConfigDigest": adapter.RETAINED_PROOF_OCI_CONFIG,
        "priorExecutionCount": 1,
        "proofJobId": (f"{_TARGET}/providers/Microsoft.App/jobs/caj-mobius77-scanner-proof"),
        "schemaVersion": "mobius.milestone-7.7.scanner-proof-execution-start-evidence.v1",
        "startTimeUtc": "2026-08-11T17:14:45Z",
        "temporaryAuthorityPrincipalId": "b8a5e782-edca-4df8-930a-1f8e42fc4dbd",
        "temporaryAuthorityScope": _QUARANTINE_SCOPE,
        "temporaryRoleAssignmentId": (
            f"{_QUARANTINE_SCOPE}/providers/Microsoft.Authorization/roleAssignments/"
            "de0da5d7-5596-5f69-889d-42adb87c8fa6"
        ),
        "temporaryRoleDefinitionId": (
            f"{_SUBSCRIPTION}/providers/Microsoft.Authorization/roleDefinitions/"
            "7d78ed8f-4b48-4e74-bb95-f0fcfe811897"
        ),
    }
    return {
        **body,
        "integritySha256": adapter._canonical_hash(
            body,
            "solarplexus-mobius/milestone-7.7/scanner-proof-execution-start-evidence/v1",
        ),
    }


def _reconcile(tmp_path: Path, **overrides: object) -> dict[str, JsonValue]:
    values: dict[str, object] = {
        "correction_repository_head": "b" * 40,
        "ordinal_binding": _ordinal_binding(),
        "execution_start": _execution_start(),
        "failure_log_output": "F " + json.dumps(_failure_marker(), separators=(",", ":")),
        "blob_tag_log_output": "F " + json.dumps(_blob_observation(), separators=(",", ":")),
        "proof_residue_count": 0,
        "observed_at": datetime(2026, 8, 11, 19, 0, tzinfo=UTC),
        "output_path": tmp_path / "proof2-reconciliation.evidence.json",
    }
    values.update(overrides)
    return adapter.reconcile_retained_scanner_proof(**values)  # type: ignore[arg-type]


def _resign_record(value: dict[str, JsonValue], *, domain: str) -> dict[str, JsonValue]:
    body = {key: item for key, item in value.items() if key != "integritySha256"}
    return {**body, "integritySha256": adapter._canonical_hash(body, domain)}


def test_retained_proof_two_reconciles_without_execution_or_azure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        managed_binding_lifecycle,
        "_run",
        lambda *_args, **_kwargs: pytest.fail("reconciliation reached Azure execution"),
    )

    artifact = _reconcile(tmp_path)

    assert artifact["scannerGateDecision"] == "SCANNER_PROOF_PASSED_FROM_RECONCILED_EVIDENCE"
    assert artifact["proofExecutionCount"] == 2
    assert artifact["proofExecutionCreated"] is False
    assert artifact["authorizationCreated"] is False
    assert artifact["azureMutationPerformed"] is False
    assert (tmp_path / "proof2-reconciliation.evidence.json").is_file()


def test_reconciliation_preserves_original_values_hashes_and_semantic_distinction(
    tmp_path: Path,
) -> None:
    artifact = _reconcile(tmp_path)

    assert artifact["historicalFailureMarkerIntegritySha256"] == (
        adapter.RETAINED_PROOF_FAILURE_MARKER_INTEGRITY
    )
    assert artifact["historicalTerminalEvidenceIntegritySha256"] == (
        adapter.RETAINED_PROOF_TERMINAL_EVIDENCE_INTEGRITY
    )
    assert artifact["originalRaw"] == {
        "blobTags": "2026-08-11 17:15:16Z",
        "logAnalytics": "2026-08-11T17:15:16.4539552Z",
    }
    assert artifact["exactInstantDeltaMicroseconds"] == 453_955
    assert artifact["sourcePrecisionFractionalSecondDigits"] == {
        "blobTags": 0,
        "logAnalytics": 7,
    }
    assert artifact["comparisonPrecisionFractionalSecondDigits"] == 0
    assert artifact["exactInstantEqual"] is False
    assert artifact["commonPrecisionEqual"] is True
    assert artifact["historicalMarkerBytesRewritten"] is False


def test_reconciliation_rejects_proof_three_or_changed_total_count(tmp_path: Path) -> None:
    start = _execution_start()
    start["executionOrdinal"] = 3
    start = _resign_record(
        start,
        domain=("solarplexus-mobius/milestone-7.7/scanner-proof-execution-start-evidence/v1"),
    )

    with pytest.raises(adapter.ScannerBridgeRecoveryExecutionError):
        _reconcile(tmp_path, execution_start=start)


def test_reconciliation_cannot_fabricate_provider_timestamp_evidence(tmp_path: Path) -> None:
    marker = _failure_marker()
    terminal = cast(dict[str, JsonValue], marker["terminalEvidence"])
    blob = cast(dict[str, JsonValue], terminal["blobTagsTimestamp"])
    blob["rawValue"] = "2026-08-11 17:15:17Z"

    with pytest.raises(adapter.ScannerBridgeRecoveryExecutionError):
        _reconcile(
            tmp_path,
            failure_log_output="F " + json.dumps(marker, separators=(",", ":")),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("queriedBlobUriSha256", "0" * 64),
        ("queriedEtagSha256", "1" * 64),
        ("queriedBlobVersionIdSha256", "2" * 64),
    ],
)
def test_reconciliation_rejects_uri_etag_or_version_mismatch(
    field: str,
    value: JsonValue,
    tmp_path: Path,
) -> None:
    observation = _blob_observation()
    observation[field] = value

    with pytest.raises(adapter.ScannerBridgeRecoveryExecutionError):
        _reconcile(
            tmp_path,
            blob_tag_log_output="F " + json.dumps(observation, separators=(",", ":")),
        )


def test_reconciliation_rejects_result_mismatch(tmp_path: Path) -> None:
    marker = _failure_marker()
    terminal = cast(dict[str, JsonValue], marker["terminalEvidence"])
    terminal["logAnalyticsResult"] = "Malicious"

    with pytest.raises(adapter.ScannerBridgeRecoveryExecutionError):
        _reconcile(
            tmp_path,
            failure_log_output="F " + json.dumps(marker, separators=(",", ":")),
        )


def test_reconciliation_rejects_wrong_blob_tag_keys(tmp_path: Path) -> None:
    observation = _blob_observation()
    observation["returnedTagKeys"] = [adapter.BLOB_RESULT_TAG]

    with pytest.raises(adapter.ScannerBridgeRecoveryExecutionError):
        _reconcile(
            tmp_path,
            blob_tag_log_output="F " + json.dumps(observation, separators=(",", ":")),
        )


def test_reconciliation_rejects_nonzero_proof_residue(tmp_path: Path) -> None:
    with pytest.raises(adapter.ScannerBridgeRecoveryExecutionError):
        _reconcile(tmp_path, proof_residue_count=1)


def test_reconciliation_artifact_is_create_once(tmp_path: Path) -> None:
    _reconcile(tmp_path)

    with pytest.raises(
        adapter.ScannerBridgeRecoveryExecutionError,
        match="scanner-proof-reconciliation-evidence-already-exists",
    ):
        _reconcile(tmp_path)
