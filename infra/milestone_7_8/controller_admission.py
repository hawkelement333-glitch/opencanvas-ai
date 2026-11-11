"""Local evidence validation, never an Azure renewal executor.

The original verified config anchors the original deadline. Matching live tags
cannot manufacture that anchor or replace a completed renewal's readbacks.
Hashes bind reviewed private records; they are not provider signatures.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from infra.milestone_7_8.campaign import CampaignError, parse_utc
from infra.milestone_7_8.cleanup_controller import (
    controller_binding_sha256,
    validate_renewal_completion_receipt,
)
from infra.milestone_7_8.controller import (
    ControllerConfig,
    controller_config_document,
    controller_config_sha256,
    validate_controller_authorization_document,
    validate_controller_results,
)

VERSION = "m7.8-controller-authority-evidence-v1"
DEADLINE_TAG = "mobius.controller-authorized-until-utc"


def _json_document(text: str) -> object:
    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON field")
            result[key] = value
        return result

    def invalid_constant(_value: str) -> object:
        raise ValueError("non-finite JSON value")

    return cast(
        object,
        json.loads(text, object_pairs_hook=unique, parse_constant=invalid_constant),
    )


def digest(domain: str, value: object) -> str:
    try:
        encoded = json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    except (TypeError, ValueError) as exc:
        raise CampaignError("controller authority evidence is not JSON") from exc
    return hashlib.sha256(domain.encode() + b"\0" + encoded).hexdigest()


def _closed(value: object, fields: set[str], label: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != fields:
        raise CampaignError(f"controller {label} fields are incomplete")
    return cast(dict[str, object], value)


def _readback(value: object, config: ControllerConfig) -> list[dict[str, object]]:
    if (
        not isinstance(value, list)
        or len(value) != 7
        or any(
            not isinstance(item, dict)
            or set(item) != {"exitCode", "stdout", "stderr"}
            or type(item.get("exitCode")) is not int
            or item["exitCode"] != 0
            or not isinstance(item.get("stdout"), str)
            or not isinstance(item.get("stderr"), str)
            for item in value
        )
    ):
        raise CampaignError("controller preservation readback is incomplete")
    results = cast(list[dict[str, object]], value)
    try:
        _snapshot_values(results)
    except (TypeError, ValueError) as exc:
        raise CampaignError("controller preservation readback is malformed") from exc
    validate_controller_results(results, config)
    group_id = (
        f"/subscriptions/{config.subscription_id}/resourceGroups/"
        f"{config.controller_resource_group_name}"
    )
    account_id = (
        f"{group_id}/providers/Microsoft.Automation/automationAccounts/"
        f"{config.automation_account_name}"
    )
    for index, resource_id in (
        (0, group_id),
        (1, account_id),
        (3, f"{account_id}/runbooks/{config.runbook_name}"),
    ):
        resource = json.loads(str(results[index]["stdout"]))
        if str(resource.get("id", "")).casefold() != resource_id.casefold():
            raise CampaignError("controller preservation resource identity differs")
    return results


def _snapshot_values(results: list[dict[str, object]]) -> list[object]:
    # Index 4 is the exact runbook content, not JSON. All other responses are JSON.
    try:
        return [
            item["stdout"] if index == 4 else _json_document(str(item["stdout"]))
            for index, item in enumerate(results)
        ]
    except (ValueError, TypeError) as exc:
        raise CampaignError("controller preservation snapshot is malformed") from exc


def _preservation(
    before: list[dict[str, object]], after: list[dict[str, object]]
) -> str:
    original = _snapshot_values(before)
    renewed = _snapshot_values(after)
    comparable = copy.deepcopy(renewed)
    for index in (0, 1, 3):
        old = cast(dict[str, object], original[index])
        new = cast(dict[str, object], comparable[index])
        old_tags = cast(dict[str, object], old["tags"])
        new_tags = cast(dict[str, object], new["tags"])
        # Restore precisely the one authorized value. No fields are discarded.
        new_tags[DEADLINE_TAG] = old_tags[DEADLINE_TAG]
    # Azure updates these read-only metadata values when tags are merged.
    # Normalize only existing string values so missing or malformed fields fail.
    for index, path in (
        (1, ("lastModifiedTime",)),
        (1, ("systemData", "lastModifiedAt")),
        (3, ("etag",)),
        (3, ("properties", "lastModifiedTime")),
    ):
        old_value: object = original[index]
        new_value: object = comparable[index]
        for key in path[:-1]:
            if not isinstance(old_value, dict) or not isinstance(new_value, dict):
                break
            old_value = old_value.get(key)
            new_value = new_value.get(key)
        if isinstance(old_value, dict) and isinstance(new_value, dict):
            key = path[-1]
            if isinstance(old_value.get(key), str) and isinstance(new_value.get(key), str):
                new_value[key] = old_value[key]
    if digest("comparison", comparable) != digest("comparison", original):
        raise CampaignError("controller renewal changed other tags or properties")
    return digest(
        "m7.8/controller-renewal-preservation/v1",
        {"before": original, "after": renewed},
    )


def validate_authority_evidence(value: object) -> ControllerConfig:
    """Validate the preserved bootstrap anchor and, if present, completed renewal.

    Expired historical authorizations are checked at a historical instant only
    to verify their exact binding. This does not renew them or authorize work.
    The caller separately checks the observed live deadline and required horizon.
    """
    evidence = _closed(
        value,
        {
            "version",
            "verifiedConfig",
            "verificationAuthorization",
            "verificationResult",
            "baselineReadback",
            "renewal",
        },
        "bootstrap anchor",
    )
    if evidence["version"] != VERSION:
        raise CampaignError("controller bootstrap anchor version differs")
    original = ControllerConfig.from_document(evidence["verifiedConfig"])
    authorization_hash = validate_controller_authorization_document(
        evidence["verificationAuthorization"],
        config=original,
        operation="controller-verify",
        now=datetime(2000, 1, 1, tzinfo=UTC),
    )
    baseline = _readback(evidence["baselineReadback"], original)
    result = _closed(
        evidence["verificationResult"],
        {
            "status",
            "operation",
            "commandCount",
            "authorizationSha256",
            "controllerProofSha256",
        },
        "bootstrap verification",
    )
    if (
        result["status"] != "controller-baseline-verified"
        or result["operation"] != "controller-verify"
        or type(result["commandCount"]) is not int
        or result["commandCount"] != 7
        or result["authorizationSha256"] != authorization_hash
        or result["controllerProofSha256"]
        != validate_controller_results(baseline, original)
    ):
        raise CampaignError("controller bootstrap verification anchor differs")
    if evidence["renewal"] is None:
        return original
    raw_renewal = evidence["renewal"]
    direct_fields = {
        "renewedConfig",
        "approval",
        "beforeReadback",
        "afterReadback",
        "completion",
        "startedAtUtc",
        "completedAtUtc",
    }
    renewal = _closed(
        raw_renewal,
        direct_fields
        | (
            {"reconciliation"}
            if isinstance(raw_renewal, dict) and "reconciliation" in raw_renewal
            else set()
        )
        | (
            {"priorAuthorityEvidence"}
            if isinstance(raw_renewal, dict) and "priorAuthorityEvidence" in raw_renewal
            else set()
        ),
        "renewal completion",
    )
    prior_evidence = renewal.get("priorAuthorityEvidence")
    if "priorAuthorityEvidence" in renewal and prior_evidence is None:
        raise CampaignError("prior controller authority evidence differs")
    if prior_evidence is not None:
        if (
            not isinstance(prior_evidence, dict)
            or not isinstance(prior_evidence.get("renewal"), dict)
            or "priorAuthorityEvidence" in prior_evidence["renewal"]
            or any(
                prior_evidence.get(key) != evidence[key]
                for key in (
                    "version", "verifiedConfig", "verificationAuthorization",
                    "verificationResult", "baselineReadback",
                )
            )
            or "reconciliation" not in renewal
        ):
            raise CampaignError("prior controller authority evidence differs")
        original = validate_authority_evidence(prior_evidence)
    renewed = ControllerConfig.from_document(renewal["renewedConfig"])
    old_document = controller_config_document(original)
    new_document = controller_config_document(renewed)
    for key in old_document:
        if (
            key not in {"sourceHead", "controllerAuthorizedUntilUtc"}
            and old_document[key] != new_document[key]
        ):
            raise CampaignError("controller renewal configuration identity differs")
    old_deadline = original.controller_authorized_until_utc
    new_deadline = renewed.controller_authorized_until_utc
    if parse_utc(new_deadline) <= parse_utc(old_deadline):
        raise CampaignError("controller renewal deadline did not increase")
    before = _readback(renewal["beforeReadback"], original)
    if isinstance(prior_evidence, dict):
        previous = _readback(prior_evidence["renewal"]["afterReadback"], original)
        _preservation(previous, before)
    after = _readback(renewal["afterReadback"], renewed)
    preservation_hash = _preservation(before, after)
    binding = controller_binding_sha256(
        original.subscription_id,
        resource_group=original.controller_resource_group_name,
        account=original.automation_account_name,
        runbook=original.runbook_name,
    )
    approval = _closed(
        renewal["approval"],
        {
            "version",
            "operation",
            "controllerBindingSha256",
            "originalConfigSha256",
            "renewedConfigSha256",
            "originalDeadlineUtc",
            "renewedDeadlineUtc",
            "baselineReadbackSha256",
            "issuedAtUtc",
            "expiresAtUtc",
            "authorizationSha256",
        },
        "renewal approval",
    )
    expected_approval = {
        "version": "m7.8-controller-renewal-approval-v1",
        "operation": "controller-renew-deadline-tags",
        "controllerBindingSha256": binding,
        "originalConfigSha256": controller_config_sha256(original),
        "renewedConfigSha256": controller_config_sha256(renewed),
        "originalDeadlineUtc": old_deadline,
        "renewedDeadlineUtc": new_deadline,
        "baselineReadbackSha256": digest(
            "m7.8/controller-renewal-before/v1", _snapshot_values(before)
        ),
        "issuedAtUtc": approval["issuedAtUtc"],
        "expiresAtUtc": approval["expiresAtUtc"],
    }
    expiry = approval["expiresAtUtc"]
    if not isinstance(expiry, str) or parse_utc(expiry) > parse_utc(new_deadline):
        raise CampaignError("controller renewal approval expiry is malformed")
    times = [
        approval["issuedAtUtc"],
        renewal["startedAtUtc"],
        renewal["completedAtUtc"],
        expiry,
    ]
    if not all(isinstance(item, str) for item in times):
        raise CampaignError("controller renewal completion time is malformed")
    issued, started, completed, expires = [parse_utc(cast(str, item)) for item in times]
    if not issued <= started < expires or completed < started:
        raise CampaignError("controller renewal completion is outside approval window")
    approval_hash = digest("m7.8/controller-renewal-approval/v1", expected_approval)
    if approval != {**expected_approval, "authorizationSha256": approval_hash}:
        raise CampaignError("controller renewal approval binding differs")
    if "reconciliation" not in renewal:
        if completed >= expires:
            raise CampaignError(
                "controller renewal completion is outside approval window"
            )
    else:
        reconciliation = _closed(
            renewal["reconciliation"],
            {"plan", "attemptJournal", "authorization", "observationSha256"},
            "renewal reconciliation",
        )
        plan = reconciliation["plan"]
        recon_auth = reconciliation["authorization"]
        if not isinstance(plan, dict) or not isinstance(recon_auth, dict):
            raise CampaignError("controller renewal reconciliation is malformed")
        from infra.milestone_7_8.controller_renewal import build_reconciliation_approval

        base_evidence = prior_evidence if prior_evidence is not None else {**evidence, "renewal": None}
        recon_issued = recon_auth.get("issuedAtUtc")
        recon_expires = recon_auth.get("expiresAtUtc")
        if not isinstance(recon_issued, str) or not isinstance(recon_expires, str):
            raise CampaignError("controller reconciliation approval window is invalid")
        expected_recon = build_reconciliation_approval(
            base_evidence,
            cast(dict[str, object], plan),
            before,
            approval,
            reconciliation["attemptJournal"],
            issued_at=recon_issued,
            expires_at=recon_expires,
            now=completed,
            source_head=cast(str | None, recon_auth.get("reconciliationSourceHead")),
        )
        if recon_auth != expected_recon:
            raise CampaignError("controller reconciliation approval binding differs")
        attempts = cast(
            list[dict[str, object]],
            cast(dict[str, object], reconciliation["attemptJournal"])["attempts"],
        )
        if (
            parse_utc(cast(str, attempts[0]["dispatchedAtUtc"])) < started
            or parse_utc(cast(str, attempts[-1]["dispatchedAtUtc"])) > completed
            or parse_utc(cast(str, attempts[-1]["dispatchedAtUtc"])) > parse_utc(recon_issued)
        ):
            raise CampaignError("controller reconciliation history time differs")
        if reconciliation["observationSha256"] != digest(
            "m7.8/controller-renewal-observation/v1",
            {
                "observedAtUtc": renewal["completedAtUtc"],
                "readback": _snapshot_values(after),
            },
        ):
            raise CampaignError("controller reconciliation observation binding differs")
    completion = renewal["completion"]
    validate_renewal_completion_receipt(
        completion,
        controller_binding=binding,
        original_config_sha256=controller_config_sha256(original),
        renewed_config_sha256=controller_config_sha256(renewed),
        renewal_approval_sha256=approval_hash,
        baseline_preservation_sha256=preservation_hash,
        original_deadline=old_deadline,
        observed_deadline=new_deadline,
    )
    return renewed


def validate_controller_admission(
    value: object,
    *,
    subscription_id: str,
    subscription_correlation: str,
    resource_group: str,
    account: str,
    cleanup_script_sha256: str,
    fresh_evidence_sha256: str,
    location: str,
    observed_deadline: str,
    observed_at: datetime | None = None,
) -> str:
    config = validate_authority_evidence(value)
    if (
        config.subscription_id != subscription_id
        or config.subscription_correlation != subscription_correlation
        or config.controller_resource_group_name != resource_group
        or config.automation_account_name != account
        or config.cleanup_script_sha256 != cleanup_script_sha256
        or config.fresh_controller_admission_evidence_sha256 != fresh_evidence_sha256
        or config.controller_location != location
        or config.controller_authorized_until_utc != observed_deadline
    ):
        raise CampaignError(
            "controller bootstrap anchor or renewal completion binding differs"
        )
    evidence = cast(dict[str, object], value)
    renewal = evidence["renewal"]
    if (
        observed_at is not None
        and isinstance(renewal, dict)
        and parse_utc(str(renewal["completedAtUtc"])) > observed_at.astimezone(UTC)
    ):
        raise CampaignError(
            "controller renewal completion is later than live observation"
        )
    return digest("m7.8/controller-authority-evidence/v1", value)


def load_authority_evidence(path: Path) -> dict[str, object]:
    try:
        value = _json_document(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CampaignError("controller authority evidence is unreadable") from exc
    validate_authority_evidence(value)
    return cast(dict[str, object], value)


def main() -> int:
    """Assemble existing reviewed records locally; issue no authorization."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verified-config", type=Path, required=True)
    parser.add_argument("--verification-authorization", type=Path, required=True)
    parser.add_argument("--verification-result", type=Path, required=True)
    parser.add_argument("--baseline-readback", type=Path, required=True)
    parser.add_argument("--renewal", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:

        def read(path: Path) -> object:
            return _json_document(path.read_text(encoding="utf-8"))

        evidence = {
            "version": VERSION,
            "verifiedConfig": read(args.verified_config),
            "verificationAuthorization": read(args.verification_authorization),
            "verificationResult": read(args.verification_result),
            "baselineReadback": read(args.baseline_readback),
            "renewal": read(args.renewal) if args.renewal else None,
        }
        validate_authority_evidence(evidence)
        descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(evidence, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
        print(
            json.dumps(
                {
                    "status": "controller-authority-evidence-validated",
                    "evidenceSha256": digest(
                        "m7.8/controller-authority-evidence/v1", evidence
                    ),
                }
            )
        )
        return 0
    except (CampaignError, OSError, ValueError) as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
