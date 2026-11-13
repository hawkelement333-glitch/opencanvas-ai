"""One explicit operator-source transition for the retained bootstrap attempt.

This record does not rebind the runtime, image, old approval, or failed attempt.
It authorizes only a corrected operator and one bounded guarded bootstrap retry.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

from infra.milestone_7_8.campaign import CampaignConfig, CampaignError, Ledger, parse_utc
from infra.milestone_7_8.canonical_inputs import canonical_snapshot
from infra.milestone_7_8.cleanup_controller import load_execution_authorization
from infra.milestone_7_8.controller import REPOSITORY_ROOT, local_source_binding

ORIGINAL_SOURCE_HEAD = "c83ffb4544aae52b1b6e60e0662f4d9ab3fd0622"
REVIEWED_PATCH_SHA256 = "41da588f9fe783c6894a4745c9e9ea6984a7accb7492c4371ec85b042625c787"
VERSION = "m7.8-bootstrap-recovery-transition-v1"
DOMAIN = "bootstrap-recovery-transition"
FILE_NAMES = frozenset({
    "runtime", "config", "attempt", "pause", "originalAuthorization", "imageAdmission",
    "scan", "validationReceipt", "explicitApproval", "patch",
})
ALLOWED_CHANGED_PATHS = frozenset({
    "infra/milestone_7_8/operator.py",
    "infra/milestone_7_8/bootstrap_transition.py",
    "infra/milestone_7_8/schemas/bootstrap-recovery-transition.schema.json",
    "apps/api/tests/test_milestone_7_8_bootstrap_transition.py",
    "apps/api/tests/test_milestone_7_8_job_diagnostics.py",
    "docs/MILESTONE_7_8_MANAGED_POSTGRESQL_CAMPAIGN_OPERATOR_RUNBOOK.md",
})
FIELDS = frozenset({
    "version", "originalSourceHead", "operatorSourceHead", "campaignId", "generationId",
    "cleanupDeadlineUtc", "issuedAtUtc", "expiresAtUtc", "maximumRetryDispatches",
    "originalFiles", "patchSha256", "validationReceiptSha256", "explicitApprovalSha256",
    "originalAttemptSha256", "originalPauseSha256", "originalAuthorizationSha256",
    "failedExecution", "imageDigest", "canonicalBuildInputSha256", "cleanupScriptSha256",
    "protectedStashesSha256", "cleanupArmSha256", "transitionSha256",
})


def _hash(domain: str, value: object) -> str:
    return hashlib.sha256(
        f"m7.8/{domain}/v1\0".encode()
        + json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _file_hash(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise CampaignError("bootstrap transition bound file is unavailable") from exc


def _document(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError
        return cast(dict[str, object], value)
    except (OSError, ValueError) as exc:
        raise CampaignError("bootstrap transition bound JSON is invalid") from exc


def _git(*arguments: str, binary: bool = False) -> str | bytes:
    result = subprocess.run(
        ("git", *arguments), cwd=REPOSITORY_ROOT, capture_output=True,
        text=not binary, check=False, timeout=30,
    )
    if result.returncode:
        raise CampaignError("bootstrap transition source inspection failed")
    return cast(str | bytes, result.stdout)


def inspect_transition_source(original_head: str, corrected_head: str) -> dict[str, str]:
    """Check the actual clean workstation boundary; callers cannot supply a Git report."""
    head, cleanup_hash = local_source_binding()
    if (
        original_head != ORIGINAL_SOURCE_HEAD
        or re.fullmatch(r"[a-f0-9]{40}", corrected_head) is None
        or head != corrected_head
        or str(_git("rev-list", "--parents", "-n", "1", head)).split()
        != [head, original_head]
    ):
        raise CampaignError("bootstrap transition requires the exact clean corrected child")
    changed = set(str(_git("diff", "--name-only", original_head, head)).splitlines())
    if not changed or not changed <= ALLOWED_CHANGED_PATHS:
        raise CampaignError("bootstrap transition changed paths exceed the reviewed correction")
    original = canonical_snapshot(original_head)
    current = canonical_snapshot(head)
    script = _git(
        "show", f"{original_head}:infra/milestone_7_8/scripts/Remove-M78Campaign.ps1",
        binary=True,
    )
    if (
        not isinstance(script, bytes)
        or original != current
        or hashlib.sha256(script).hexdigest() != cleanup_hash
    ):
        raise CampaignError("bootstrap transition changed image inputs or cleanup content")
    stashes = str(_git("stash", "list", "--format=%H")).splitlines()
    if len(stashes) != 5:
        raise CampaignError("bootstrap transition protected stashes differ")
    return {
        "canonicalBuildInputSha256": str(current["buildInputSha256"]),
        "cleanupScriptSha256": cleanup_hash,
        "protectedStashesSha256": _hash("bootstrap-transition-stashes", stashes),
    }


def _record(path: Path, domain: str) -> dict[str, object]:
    value = _document(path)
    body = {key: item for key, item in value.items() if key != "recordSha256"}
    if value.get("recordSha256") != _hash(domain, body):
        raise CampaignError("bootstrap transition original stage record hash differs")
    return value


def _validate_window(value: dict[str, object]) -> None:
    issued = parse_utc(str(value["issuedAtUtc"]))
    expires = parse_utc(str(value["expiresAtUtc"]))
    if not issued < expires <= min(
        issued + timedelta(minutes=15), parse_utc(str(value["cleanupDeadlineUtc"]))
    ):
        raise CampaignError("bootstrap transition dispatch window is invalid")


def validate_dispatch_window(value: dict[str, object], now: datetime | None = None) -> None:
    """Call immediately before the one retry dispatch, never to age later readbacks."""
    _validate_window(value)
    observed = (now or datetime.now(UTC)).astimezone(UTC)
    if not parse_utc(str(value["issuedAtUtc"])) <= observed < parse_utc(
        str(value["expiresAtUtc"])
    ):
        raise CampaignError("bootstrap transition retry dispatch window is not current")


def require_operation(
    value: dict[str, object], operation: str, resume: bool,
    completed_transition_sha256: str | None = None,
) -> None:
    """Completion is supplied only after the existing retry validator accepts it."""
    if operation in {"cleanup", "cleanup-wait", "cleanup-disarm", "residue", "finalize"}:
        return
    if operation == "bootstrap" and resume:
        return
    if (
        operation in {"migrate", "evidence", "dispose"}
        and completed_transition_sha256 == value.get("transitionSha256")
    ):
        return
    raise CampaignError("bootstrap source transition does not admit this phase")


def _build_transition(
    *, runtime_path: Path, config_path: Path, attempt_path: Path, pause_path: Path,
    original_authorization_path: Path, image_admission_path: Path, scan_path: Path,
    validation_receipt_path: Path, explicit_approval_path: Path, patch_path: Path,
    corrected_source_head: str, issued_at: str, expires_at: str,
) -> dict[str, object]:
    """Construct only; the caller writes once privately after all local checks pass."""
    # Reuse the image-admission contract without introducing an import cycle at startup.
    from infra.milestone_7_8.operator import load_image_scan_evidence

    paths = {
        "runtime": runtime_path, "config": config_path, "attempt": attempt_path,
        "pause": pause_path, "originalAuthorization": original_authorization_path,
        "imageAdmission": image_admission_path, "scan": scan_path,
        "validationReceipt": validation_receipt_path, "explicitApproval": explicit_approval_path,
        "patch": patch_path,
    }
    if (
        attempt_path.resolve() != runtime_path.resolve().with_name("bootstrap-stage-attempt.json")
        or pause_path.resolve() != runtime_path.resolve().with_name("bootstrap-stage-pause.json")
    ):
        raise CampaignError("bootstrap transition original stage paths differ")
    runtime = _document(runtime_path)
    config = CampaignConfig.from_json(config_path, allow_expired=True)
    original = str(runtime.get("sourceHead", ""))
    source = inspect_transition_source(original, corrected_source_head)
    attempt = _record(attempt_path, "stage-attempt")
    pause = _record(pause_path, "stage-pause")
    image = _document(image_admission_path)
    scan = _document(scan_path)
    validation = _document(validation_receipt_path)
    approval = _document(explicit_approval_path)
    patch_hash = _file_hash(patch_path)
    bindings = attempt.get("bindings")
    if not isinstance(bindings, dict):
        raise CampaignError("bootstrap transition original bindings are missing")
    expected_bindings = {
        "campaignId": config.campaign_id,
        "generationId": config.generation_id,
        "sourceHead": original,
        "runtimeSha256": _hash("stage-runtime", runtime),
        "configSha256": _hash("stage-config", asdict(config)),
        "imageDigest": image.get("imageDigest"),
        "ledgerPhase": "image-decided",
        "cleanupArmSha256": bindings.get("cleanupArmSha256"),
        "cleanupDeadlineUtc": config.cleanup_deadline_utc,
    }
    if (
        original != ORIGINAL_SOURCE_HEAD
        or patch_hash != REVIEWED_PATCH_SHA256
        or source["canonicalBuildInputSha256"] != runtime.get("canonicalBuildInputSha256")
        or source["cleanupScriptSha256"] != runtime.get("cleanupScriptSha256")
        or bindings != expected_bindings
        or re.fullmatch(r"[a-f0-9]{64}", str(bindings.get("cleanupArmSha256"))) is None
        or attempt.get("version") != "m7.8-protected-stage-attempt-v1"
        or attempt.get("operation") != "bootstrap"
        or pause.get("version") != "m7.8-protected-stage-pause-v1"
        or pause.get("operation") != "bootstrap"
        or pause.get("bindings") != bindings
        or pause.get("attemptSha256") != attempt["recordSha256"]
        or pause.get("authorizationSha256") != attempt.get("authorizationSha256")
        or type(pause.get("maximumRetryDispatches")) is not int
        or pause["maximumRetryDispatches"] != 1
        or not isinstance(pause.get("failedExecution"), str)
        or not pause["failedExecution"]
    ):
        raise CampaignError("bootstrap transition original attempt or source binding differs")
    for record in (image, scan):
        if any(record.get(key) != expected for key, expected in (
            ("sourceHead", original),
            ("canonicalBuildInputSha256", runtime["canonicalBuildInputSha256"]),
            ("imageDigest", bindings["imageDigest"]),
        )):
            raise CampaignError("bootstrap transition admitted image binding differs")
    if (
        image.get("version") != "m7.8-local-image-result-v1"
        or re.fullmatch(r"sha256:[a-f0-9]{64}", str(image.get("imageDigest"))) is None
    ):
        raise CampaignError("bootstrap transition image admission record differs")
    load_image_scan_evidence(
        scan_path, digest=str(image["imageDigest"]), runtime=cast(dict[str, str], runtime),
    )
    load_execution_authorization(
        original_authorization_path, config=config, runtime=cast(dict[str, str], runtime),
        operation="bootstrap", now=parse_utc(str(attempt["startedAtUtc"])),
    )
    if _file_hash(original_authorization_path) != attempt["authorizationSha256"]:
        raise CampaignError("bootstrap transition original authorization hash differs")
    checks = validation.get("checks")
    if (
        validation.get("status") != "passed"
        or validation.get("operatorSourceHead") != corrected_source_head
        or not isinstance(validation.get("completedAtUtc"), str)
        or parse_utc(str(validation["completedAtUtc"])) > parse_utc(issued_at)
        or not isinstance(checks, list) or not checks
        or any(
            not isinstance(check, dict) or check.get("status") != "passed"
            or not isinstance(check.get("name"), str) or not check["name"]
            for check in checks
        )
        or approval.get("approved") is not True
        or approval.get("maximumRecoveryMinutes") != 15
        or approval.get("cleanupDeadlineUtc") != config.cleanup_deadline_utc
        or approval.get("allowedOperations")
        != ["bootstrap-retry", "post-retry-campaign", "cleanup"]
        or any(
            record.get("originalSourceHead") != original or record.get("patchSha256") != patch_hash
            for record in (validation, approval)
        )
    ):
        raise CampaignError("bootstrap transition review or explicit approval differs")
    value: dict[str, object] = {
        "version": VERSION, "originalSourceHead": original,
        "operatorSourceHead": corrected_source_head,
        "campaignId": config.campaign_id, "generationId": config.generation_id,
        "cleanupDeadlineUtc": config.cleanup_deadline_utc,
        "issuedAtUtc": issued_at, "expiresAtUtc": expires_at, "maximumRetryDispatches": 1,
        "originalFiles": {
            name: {"path": str(path.resolve(strict=True)), "sha256": _file_hash(path)}
            for name, path in paths.items()
        },
        "patchSha256": patch_hash,
        "validationReceiptSha256": _file_hash(validation_receipt_path),
        "explicitApprovalSha256": _file_hash(explicit_approval_path),
        "originalAttemptSha256": attempt["recordSha256"],
        "originalPauseSha256": pause["recordSha256"],
        "originalAuthorizationSha256": attempt["authorizationSha256"],
        "failedExecution": pause["failedExecution"],
        "imageDigest": image["imageDigest"],
        "cleanupArmSha256": bindings["cleanupArmSha256"],
        **source,
    }
    _validate_window(value)
    value["transitionSha256"] = _hash(DOMAIN, value)
    return value


def build_transition(
    *, runtime_path: Path, config_path: Path, attempt_path: Path, pause_path: Path,
    original_authorization_path: Path, image_admission_path: Path, scan_path: Path,
    validation_receipt_path: Path, explicit_approval_path: Path, patch_path: Path,
    corrected_source_head: str, issued_at: str, expires_at: str,
) -> dict[str, object]:
    """Prepare one new transition only while the original retry remains unused."""
    if any(
        runtime_path.with_name(name).exists()
        for name in (
            "bootstrap-stage-retry-intent.json", "bootstrap-stage-retry-start.json",
            "bootstrap-stage-recovery-completed.json",
        )
    ):
        raise CampaignError("bootstrap transition cannot authorize another retry attempt")
    return _build_transition(
        runtime_path=runtime_path, config_path=config_path, attempt_path=attempt_path,
        pause_path=pause_path, original_authorization_path=original_authorization_path,
        image_admission_path=image_admission_path, scan_path=scan_path,
        validation_receipt_path=validation_receipt_path,
        explicit_approval_path=explicit_approval_path, patch_path=patch_path,
        corrected_source_head=corrected_source_head, issued_at=issued_at, expires_at=expires_at,
    )


def load_bootstrap_transition(
    path: Path, runtime_path: Path, config_path: Path, runtime: dict[str, str],
    config: CampaignConfig, ledger: Ledger, operation: str, resume: bool,
    now: datetime | None = None,
) -> dict[str, object]:
    """Revalidate immutable history and current source, without renewing any timer.

    The operator separately checks phase admission and the immediate dispatch window.
    A late read-only completion can therefore still observe the exact recorded retry.
    """
    del operation, resume, now
    value = _document(path)
    if (
        set(value) != FIELDS or value.get("version") != VERSION
        or type(value.get("maximumRetryDispatches")) is not int
        or value["maximumRetryDispatches"] != 1
    ):
        raise CampaignError("bootstrap transition fields differ")
    files = value.get("originalFiles")
    if not isinstance(files, dict) or set(files) != FILE_NAMES:
        raise CampaignError("bootstrap transition original files differ")
    paths: dict[str, Path] = {}
    for name, entry in files.items():
        if (
            not isinstance(entry, dict) or set(entry) != {"path", "sha256"}
            or not isinstance(entry.get("path"), str)
        ):
            raise CampaignError("bootstrap transition file binding is malformed")
        bound = Path(entry["path"])
        if not bound.is_absolute() or _file_hash(bound) != entry.get("sha256"):
            raise CampaignError("bootstrap transition original file changed")
        paths[name] = bound
    if (
        paths["runtime"].resolve() != runtime_path.resolve()
        or paths["config"].resolve() != config_path.resolve()
        or _document(runtime_path) != runtime
        or CampaignConfig.from_json(config_path, allow_expired=True) != config
        or ledger.image_digest != value.get("imageDigest")
        or ledger.image_scan_evidence_sha256 != _file_hash(paths["scan"])
        or ledger.cleanup_arm_evidence_sha256 != value.get("cleanupArmSha256")
    ):
        raise CampaignError("bootstrap transition current campaign binding differs")
    rebuilt = _build_transition(
        runtime_path=paths["runtime"], config_path=paths["config"],
        attempt_path=paths["attempt"], pause_path=paths["pause"],
        original_authorization_path=paths["originalAuthorization"],
        image_admission_path=paths["imageAdmission"], scan_path=paths["scan"],
        validation_receipt_path=paths["validationReceipt"],
        explicit_approval_path=paths["explicitApproval"], patch_path=paths["patch"],
        corrected_source_head=str(value["operatorSourceHead"]),
        issued_at=str(value["issuedAtUtc"]), expires_at=str(value["expiresAtUtc"]),
    )
    if value != rebuilt:
        raise CampaignError("bootstrap transition hash or history differs")
    return value
