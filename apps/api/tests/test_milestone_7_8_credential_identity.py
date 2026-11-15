"""Credential identity uses canonical runtime authority, without Azure or private inputs."""

from __future__ import annotations

import copy
import hashlib
import json

import pytest
from test_milestone_7_8_controller_admission import authority_fixture

from infra.milestone_7_8 import controller_admission as admission
from infra.milestone_7_8 import evidence_console as ec
from infra.milestone_7_8.campaign import CampaignError


@pytest.fixture
def case(tmp_path):
    evidence = authority_fixture()
    anchor = admission.validate_authority_evidence(evidence)
    authority = tmp_path / "controller-authority.json"
    authority.write_text(json.dumps(evidence))
    suffix = hashlib.sha256(f"{anchor.campaign_id}\0{anchor.generation_id}".encode()).hexdigest()[
        :10
    ]
    runtime = {
        "controllerAuthorityEvidenceFile": str(authority),
        "controllerAuthorityEvidenceSha256": admission.digest(
            "m7.8/controller-authority-evidence/v1",
            evidence,
        ),
        "subscriptionId": anchor.subscription_id,
        "cleanupResourceGroupName": anchor.controller_resource_group_name,
        "automationAccountName": anchor.automation_account_name,
        "cleanupScriptSha256": anchor.cleanup_script_sha256,
        "freshControllerAdmissionEvidenceSha256": anchor.fresh_controller_admission_evidence_sha256,
        "cleanupRegion": anchor.controller_location,
        "controllerAuthorizedUntilUtc": anchor.controller_authorized_until_utc,
        "resourceGroupName": f"rg-m78-{suffix}-target",
    }
    payloads = [
        {
            "version": "m7.8-credential-recovery-observation-v1",
            "status": "observed",
            "campaignId": anchor.campaign_id,
            "generationId": anchor.generation_id,
            "mode": phase,
            "loginEnabled": phase == "restore",
            "activeSessions": 0 if phase == "revoke" else None,
            "terminatedSessions": 15 if phase == "revoke" else None,
        }
        for phase in ("revoke", "restore")
    ]
    return runtime, payloads


@pytest.mark.parametrize("index,phase", [(0, "revoke"), (1, "restore")])
def test_canonical_runtime_identity_comes_from_bound_authority(case, index, phase):
    runtime, payloads = case
    assert "campaignId" not in runtime and "generationId" not in runtime
    ec.credential(payloads[index], phase, runtime)
    assert ec.validate_capture.__globals__["credential"] is ec.credential
    assert ec.validate_proofs.__globals__["validate_capture"] is ec.validate_capture


@pytest.mark.parametrize(
    "field,value",
    [
        ("campaignId", "wrong-campaign"),
        ("generationId", "wrong-generation"),
        ("controllerAuthorityEvidenceSha256", "0" * 64),
        ("resourceGroupName", "rg-m78-0000000000-target"),
        ("subscriptionId", "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
    ],
)
def test_runtime_identity_or_authority_substitution_rejected(case, field, value):
    runtime, payloads = case
    runtime[field] = value
    with pytest.raises(CampaignError):
        ec.credential(payloads[0], "revoke", runtime)


@pytest.mark.parametrize(
    "field,value",
    [
        ("campaignId", "wrong-campaign"),
        ("generationId", "wrong-generation"),
        ("activeSessions", 1),
        ("loginEnabled", True),
        ("terminatedSessions", -1),
    ],
)
def test_payload_binding_and_revocation_checks_remain_strict(case, field, value):
    runtime, payloads = case
    payload = copy.deepcopy(payloads[0])
    payload[field] = value
    with pytest.raises(CampaignError):
        ec.credential(payload, "revoke", runtime)


def test_existing_explicit_identity_runtime_remains_supported(case):
    _, payloads = case
    runtime = {key: payloads[0][key] for key in ("campaignId", "generationId")}
    ec.credential(payloads[0], "revoke", runtime)


def test_missing_identity_has_controlled_failure(case):
    _, payloads = case
    with pytest.raises(CampaignError, match="identity is absent"):
        ec.credential(payloads[0], "revoke", {})
