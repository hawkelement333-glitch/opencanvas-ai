"""Narrow admission for the one private synthetic Milestone 7.8 campaign."""

from __future__ import annotations

from pathlib import Path

from infra.milestone_7_8.campaign import CampaignError
from infra.milestone_7_8.pilot.telemetry_first import RELEASE_KEY_SHA256
from infra.milestone_7_8.pilot_cleanup import file_hash, read
from infra.milestone_7_8.pilot_validation import SCANNER_OBSERVATION

API = "sha256:e0e6518e8f54c6151e598c6b591923dfade3e35c7b10a18dc0fc38bc22cc3c62"
FRONTEND = "sha256:1ee742b604d406ad8cc4c3c53001853ad58a033b68f4d613251ea7fc088fdb3a"
SCAN = "5f78502e2ab2d4dc741573f055a5d8325441e5659a0002b5a61bdeb7b1c2bd9a"
CVES = sorted(
    (
        "CVE-2026-107496",
        "CVE-2026-124709",
        "CVE-2026-88823",
        "CVE-2026-95692",
        "CVE-2026-107493",
        "CVE-2026-95691",
    )
)
TEMPLATE = "2002f19a05728bd9f2db207f9fb0aa7969d26ebf3af04fe9964ebb255a305cb0"
POLICY = {
    "schema": "m78-private-synthetic-staging-exception-v1",
    "target": "rg-m78-a712b8c940-target",
    "apiDigest": API,
    "apiSignature": "unsigned",
    "frontendDigest": FRONTEND,
    "frontendSignature": "retained-key-only-endorsement",
    "correctedApiSarifSha256": SCAN,
    "critical": 0,
    "highCves": CVES,
    "data": "synthetic-only",
    "publicIngress": False,
    "emailLimit": 0,
    "proofStopsAfterHours": 11,
    "exceptionExpiresAfterHours": 13,
    "productionRelease": False,
}
PRIOR_REVIEW = "51a21bf2b9284bfe54d0106dc74b7a9664ca30e5673b89fb94ef147b8a15a703"
SUCCESSOR_POLICY = {
    **POLICY,
    "schema": "m78-private-synthetic-staging-exception-v2",
    "supersedesExpiredReview": PRIOR_REVIEW,
    "approvedExecutions": 1,
    "scannerObservation": SCANNER_OBSERVATION,
}


def validate_staging_admission(package: Path, review: dict, approval: dict) -> None:
    policy_path = package / "staging-exception.json"
    policy = review.get("stagingException")
    required = {
        "compiled/pilot.json",
        "staging-exception.json",
        "planned-bindings.json",
        "parameters.bound.json",
        "release-bindings.json",
        "signing/api/release-binding.json",
        "signing/api/scout.sarif.json",
        "signing/api/runtime-package-inventory.json",
        "signing/frontend/release-binding.json",
        "signing/frontend/buildkit-provenance.json",
        "signing/frontend/runtime-package-inventory.json",
        "signing/opencanvas-m78-release.pub",
        "signing/frontend-release-binding.bundle.json",
        "signing/frontend-buildkit-provenance.bundle.json",
        "signing/retained-signature-verification-receipt.json",
    }
    if (
        policy not in (POLICY, SUCCESSOR_POLICY)
        or not required <= review["files"].keys()
        or read(policy_path) != policy
        or review["files"].get(policy_path.name) != file_hash(policy_path)
        or approval.get("approveStagingExceptionSha256") != file_hash(policy_path)
        or review.get("targetResourceGroup") != POLICY["target"]
        or review.get("targetRegion") != "canadacentral"
        or review.get("redisRegion") != "eastus"
        or review.get("operatorWindowHours", {}).get("proofStop") != 11
        or review.get("operatorWindowHours", {}).get("operatorCleanupExpiry") != 13
        or review.get("emailLimit") != 0
        or review.get("signedReleaseSourceCheckpoint") is not None
        or file_hash(package / "compiled/pilot.json") != TEMPLATE
    ):
        raise CampaignError("staging exception scope or exact approval differs")
    plan = read(package / "planned-bindings.json")
    if policy == SUCCESSOR_POLICY and (
        not {"successor-scope.json", "local-verification.json"} <= review["files"].keys()
        or review.get("supersedesReviewSha256") != PRIOR_REVIEW
        or plan.get("scannerObservation") != SCANNER_OBSERVATION
        or read(package / "successor-scope.json").get("scannerObservation") != SCANNER_OBSERVATION
        or review.get("boundRuntimeDirectory") != ".runtime/milestone_7_8/psv2"
    ):
        raise CampaignError("staging successor observation or execution scope differs")
    arm = read(package / "parameters.bound.json")["parameters"]
    images = read(package / "release-bindings.json")
    api, frontend = images["api"], images["frontend"]
    signing = package / "signing"
    if (
        (plan["imageDigest"], plan["frontendImageDigest"]) != (API, FRONTEND)
        or (arm["apiImageDigest"]["value"], arm["frontendImageDigest"]["value"]) != (API, FRONTEND)
        or (api["imageIndexDigest"], frontend["imageIndexDigest"]) != (API, FRONTEND)
        or arm["smtpHost"]["value"] != "disabled.mail.invalid"
        or any(op == "smtp" or op.startswith("password-reset-") for op in plan["enabledOperations"])
        or api["signatureStatus"] != "unsigned"
        or api["scanSarifSha256"] != SCAN
        or file_hash(signing / "api/scout.sarif.json") != SCAN
        or file_hash(signing / "api/runtime-package-inventory.json") != api["inventorySha256"]
        or file_hash(signing / "frontend/runtime-package-inventory.json")
        != frontend["inventorySha256"]
        or read(signing / "api/release-binding.json") != api
        or read(signing / "frontend/release-binding.json") != frontend
        or (signing / "api-release-binding.bundle.json").exists()
        or (signing / "api-buildkit-provenance.bundle.json").exists()
    ):
        raise CampaignError("staging image, inventory, or unsigned API evidence differs")
    verify_frontend_endorsement(signing)


def verify_frontend_endorsement(signing: Path) -> None:
    receipt = read(signing / "retained-signature-verification-receipt.json")
    if (
        receipt["status"] != "verified-local-endorsement"
        or receipt["publicKeySha256"] != RELEASE_KEY_SHA256
        or receipt["tamperedContentRejected"] is not True
        or file_hash(signing / "opencanvas-m78-release.pub") != RELEASE_KEY_SHA256
    ):
        raise CampaignError("retained frontend signing policy differs")
    for subject in ("release-binding", "buildkit-provenance"):
        target = f"frontend-{subject}"
        expected = {
            "id": target,
            "contentSha256": file_hash(signing / "frontend" / f"{subject}.json"),
            "bundleSha256": file_hash(signing / f"{target}.bundle.json"),
            "verified": True,
        }
        if [t for t in receipt["targets"] if t["id"] == target] != [expected]:
            raise CampaignError("retained frontend endorsement differs")


def validate_local_image(image: str, archive: Path, local: dict, binding: dict) -> None:
    expected_digest = {"api": API, "frontend": FRONTEND}[image]
    if (
        local.get("digest") != expected_digest
        or binding.get("imageIndexDigest") != expected_digest
        or file_hash(archive) != binding["archiveSha256"]
    ):
        raise CampaignError("staging publication requires the exact retained image and archive")
