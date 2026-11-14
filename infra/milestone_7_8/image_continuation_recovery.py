"""Validate only the retained pre-push staging failure; never dispatch recovery."""
from __future__ import annotations

import hashlib
import json
import tarfile
from pathlib import Path
from typing import cast

from infra.milestone_7_8 import image_continuation, local_image, operator
from infra.milestone_7_8.campaign import CampaignError, Ledger, parse_utc
from infra.milestone_7_8.canonical_inputs import BUILD_INPUTS

PRIOR_HEAD = "ba7308dd0bbae01564b20fdb974fea876b370eea"
PRIOR_PLAN = "f10f8f4157cd58f9751fdbd3cea476173b455f65b1053b8f500478c6e152a1f3"
FIELDS = frozenset({
    "version", "planFile", "planSha256", "sourceHead", "imagePlanSha256",
    "imageApprovalSha256", "pauseFile", "pauseFileSha256", "pauseRecordSha256",
    "filesSha256", "priorAttemptSha256",
})


def _read(path: Path) -> dict[str, object]:
    try:
        return local_image._object(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        raise CampaignError("prior image evidence is missing or malformed") from exc


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _hash(value: object) -> str:
    return hashlib.sha256(b"m7.8/image-continuation-prior/v1\0" + json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode()).hexdigest()


def _inventory(folder: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in folder.rglob("*"):
        if path.is_symlink():
            raise CampaignError("prior image evidence contains a symbolic link")
        if path.is_file() and not path.is_relative_to(folder / "local-image/source"):
            result[str(path.resolve())] = _file_hash(path)
    return result


def _replay(plan_path: Path) -> dict[str, object]:
    plan_path = image_continuation._private(plan_path)
    raw_plan = _read(plan_path)
    if ("priorImageAttempt" in raw_plan or raw_plan.get("sourceHead") != PRIOR_HEAD
            or raw_plan.get("planSha256") != PRIOR_PLAN):
        raise CampaignError("prior image attempt is not the exact reviewed failed plan")
    plan = image_continuation.load_plan(plan_path)
    runtime, config = image_continuation._effective(plan)
    folder, output = plan_path.parent, plan_path.parent / "local-image"
    if folder != Path(str(plan["runtimeFile"])).parent / "image-continuation":
        raise CampaignError("prior image attempt folder differs")
    image_plan, approval = _read(output / "plan.json"), _read(output / "approval.json")
    if (image_plan != _read(folder / "local-image-plan.json")
            or approval != _read(folder / "local-image-approval.json")
            or image_plan != local_image._rebuild_plan(runtime, config, image_plan)
            or image_plan.get("continuationFile") != str(plan_path)
            or image_plan.get("continuationPlanSha256") != PRIOR_PLAN):
        raise CampaignError("prior image plan or private copies differ")
    expected_approval = local_image.build_approval(
        image_plan, issued_at=str(approval.get("issuedAtUtc")),
        expires_at=str(approval.get("expiresAtUtc")),
        restore_until=str(approval.get("restoreUntilUtc")),
    )
    marker_path = folder / "local-image-attempt.json"
    if approval != expected_approval or _read(marker_path) != {
        "planSha256": image_plan["planSha256"], "approvalSha256": approval["approvalSha256"],
    }:
        raise CampaignError("prior image approval or attempt binding differs")
    retained = local_image._object(image_plan.get("retainedImage"))
    base = ("az", "rest", "--method")
    tail = ("--url", str(image_plan["registryUrl"]), "--subscription",
            runtime["subscriptionId"])
    get = (*base, "get", *tail, "--output", "json")
    def patch(field: str) -> tuple[str, ...]:
        if _read(output / f"{field}.json") != image_plan[field]:
            raise CampaignError("prior image network request body differs")
        return (*base, "patch", *tail, "--body", f"@{output / (field + '.json')}",
                "--output", "json")
    commands = (
        ("docker", "image", "inspect", str(retained["imageId"])), get, patch("openBody"), get,
        ("docker", "info", "--format", "{{json .}}"),
        ("git", "-C", str(local_image.ROOT), *local_image.ARCHIVE_OPTIONS, "archive",
         "--format=tar", "--output", str(output / "source.tar"), PRIOR_HEAD, "--", *BUILD_INPUTS),
        ("git", "-C", str(local_image.ROOT), "ls-tree", "-r", "--full-tree", PRIOR_HEAD,
         "--", *BUILD_INPUTS), patch("restoreBody"), get,
    )
    responses: list[dict[str, object]] = []
    previous = parse_utc(str(approval["issuedAtUtc"]))
    for index, command in enumerate(commands, 1):
        intent = _read(output / f"{index:02}-intent.json")
        observed = parse_utc(str(intent.get("intentAtUtc")))
        limit = "restoreUntilUtc" if index >= 8 else "expiresAtUtc"
        if (set(intent) != {"command", "approvalSha256", "intentAtUtc"}
                or intent["command"] != list(command)
                or intent["approvalSha256"] != approval["approvalSha256"]
                or not previous <= observed < parse_utc(str(approval[limit]))):
            raise CampaignError("prior image dispatch history or authorization differs")
        previous = observed
        response = _read(output / f"{index:02}-response.json")
        if (set(response) != {"exitCode", "stdout", "stderr"}
                or type(response["exitCode"]) is not int or response["exitCode"] != 0
                or not isinstance(response["stdout"], str)
                or not isinstance(response["stderr"], str)):
            raise CampaignError("prior image command outcome is incomplete")
        responses.append(response)
    required = {f"{index:02}-{suffix}.json" for index in range(1, 10)
                for suffix in ("intent", "response")}
    required |= {"plan.json", "approval.json", "fresh-before.json", "restore-scope.json",
                 "openBody.json", "restoreBody.json", "restored.json", "source.tar"}
    if {path.name for path in output.iterdir() if path.is_file()} != required:
        raise CampaignError(
            "prior image contains missing, extra or indeterminate execution evidence"
        )
    local_image._validate_retained_inspection(local_image._result(responses[0]), image_plan)
    baseline, opened, restored = (local_image._result(responses[i]) for i in (1, 3, 8))
    local_image._verify_registry(baseline, image_plan)
    local_image._verify_registry(opened, image_plan, opened=True)
    local_image._verify_registry(restored, image_plan)
    if (baseline != _read(output / "fresh-before.json")
            or restored != _read(output / "restored.json")
            or _read(output / "restore-scope.json") != image_plan["restoreBody"]):
        raise CampaignError("prior image registry snapshot is not the retained response")
    info = local_image._object(local_image._result(responses[4]))
    if info.get("OSType") != "linux" or info.get("Architecture") not in {"amd64", "x86_64"}:
        raise CampaignError("prior image engine platform differs")
    try:
        local_image._extract_source(
            output / "source.tar", output / "source", cast(str, responses[6]["stdout"]),
            str(image_plan["canonicalBuildInputSha256"]), extract=False,
        )
    except (OSError, tarfile.TarError) as exc:
        raise CampaignError("prior image canonical archive is unreadable") from exc
    pause_path = Path(str(plan["runtimeFile"])).parent / "local-image-stage-pause.json"
    pause = operator._read_stage_record(pause_path, "stage-pause")
    ledger = Ledger(**local_image._object(plan["baselineLedger"]))  # type: ignore[arg-type]
    if (pause.get("version") != "m7.8-protected-stage-pause-v1"
            or pause.get("operation") != "local-image" or pause.get("failedExecution") is not None
            or pause.get("attemptSha256") != _file_hash(marker_path)
            or pause.get("authorizationSha256") != approval["approvalSha256"]
            or pause.get("bindings") != operator._stage_bindings(config, runtime, ledger)
            or parse_utc(str(pause.get("failedAtUtc"))) < previous):
        raise CampaignError("prior image protected pause binding differs")
    return {
        "version": "m7.8-image-continuation-prior-v1", "planFile": str(plan_path),
        "planSha256": PRIOR_PLAN, "sourceHead": PRIOR_HEAD,
        "imagePlanSha256": image_plan["planSha256"],
        "imageApprovalSha256": approval["approvalSha256"],
        "pauseFile": str(pause_path), "pauseFileSha256": _file_hash(pause_path),
        "pauseRecordSha256": pause["recordSha256"], "filesSha256": _inventory(folder),
    }


def build_prior(plan_path: Path) -> dict[str, object]:
    body = _replay(plan_path)
    plan = _read(plan_path)
    ledger_path = Path(str(plan["ledgerFile"]))
    if (_read(ledger_path) != plan["baselineLedger"]
            or _file_hash(ledger_path) != plan["baselineLedgerFileSha256"]):
        raise CampaignError("prior image original ledger changed before recovery review")
    return {**body, "priorAttemptSha256": _hash(body)}


def validate_prior(record: dict[str, object]) -> None:
    body = {key: value for key, value in record.items() if key != "priorAttemptSha256"}
    if (set(record) != FIELDS or record.get("priorAttemptSha256") != _hash(body)
            or body != _replay(Path(str(record.get("planFile"))))):
        raise CampaignError("prior image attempt receipt or underlying evidence differs")


def bound_pause_matches(record: dict[str, object], pause: dict[str, object]) -> bool:
    validate_prior(record)
    return pause == _read(Path(str(record["pauseFile"])))
