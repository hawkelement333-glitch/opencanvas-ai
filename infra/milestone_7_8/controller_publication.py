"""Publish corrected content to the existing cleanup runbook under exact approval."""

from __future__ import annotations

import argparse
import copy
import json
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import cast

from infra.milestone_7_8 import controller_admission as admission
from infra.milestone_7_8.azure_cli import AzureCliLauncher
from infra.milestone_7_8.campaign import CampaignError, parse_utc
from infra.milestone_7_8.controller import (
    REPOSITORY_ROOT,
    ControllerConfig,
    controller_config_document,
    controller_config_sha256,
    local_source_binding,
    runbook_publication_commands,
    validate_controller_results,
)
from infra.milestone_7_8.controller_renewal import RenewalRunner, _durable_record, _read_controller

PLAN_DOMAIN = "m7.8/controller-runbook-publication-plan/v1"
APPROVAL_DOMAIN = "m7.8/controller-runbook-publication-approval/v1"
REQUEST_DOMAIN = "m7.8/controller-runbook-publication-request/v1"
AUTHORITY_DOMAIN = "m7.8/controller-authority-evidence/v1"


def _publication_requests(config: ControllerConfig) -> list[list[str]]:
    return [
        [*command[1:], "--subscription", config.subscription_id, "--only-show-errors"]
        for command in runbook_publication_commands(config)
    ]


def build_plan(
    prior: dict[str, object], *, source_head: str, script_hash: str, artifact_root: str
) -> dict[str, object]:
    if "runbookPublication" in prior:
        raise CampaignError("only one controller runbook publication is supported")
    original = admission.validate_authority_evidence(prior)
    if script_hash == original.cleanup_script_sha256 or source_head == original.source_head:
        raise CampaignError("controller publication must bind new source and content")
    path = PurePosixPath(artifact_root)
    if (
        path.parts[:1] != (".runtime",) or len(path.parts) < 2 or ".." in path.parts
        or path.as_posix() != artifact_root or "\\" in artifact_root
    ):
        raise CampaignError("controller publication artifact root is invalid")
    published = replace(original, source_head=source_head, cleanup_script_sha256=script_hash)
    published.validate()
    plan: dict[str, object] = {
        "version": "m7.8-controller-runbook-publication-plan-v1",
        "priorAuthorityEvidenceSha256": admission.digest(AUTHORITY_DOMAIN, prior),
        "priorConfigSha256": controller_config_sha256(original),
        "priorScriptSha256": original.cleanup_script_sha256,
        "publishedConfig": controller_config_document(published),
        "publishedConfigSha256": controller_config_sha256(published),
        "artifactRoot": artifact_root,
        "requests": _publication_requests(published),
    }
    plan["planSha256"] = admission.digest(PLAN_DOMAIN, plan)
    return plan


def _validate_plan(prior: dict[str, object], value: object) -> ControllerConfig:
    if not isinstance(value, dict):
        raise CampaignError("controller publication plan is malformed")
    published = ControllerConfig.from_document(value.get("publishedConfig"))
    artifact_root = value.get("artifactRoot")
    if not isinstance(artifact_root, str):
        raise CampaignError("controller publication artifact root is invalid")
    if value != build_plan(
        prior, source_head=published.source_head, script_hash=published.cleanup_script_sha256,
        artifact_root=artifact_root,
    ):
        raise CampaignError("controller publication plan binding differs")
    return published


def build_approval(
    plan: dict[str, object], *, issued_at: str, expires_at: str
) -> dict[str, object]:
    published = ControllerConfig.from_document(plan.get("publishedConfig"))
    if not parse_utc(issued_at) < parse_utc(expires_at) <= parse_utc(
        published.controller_authorized_until_utc
    ):
        raise CampaignError("controller publication approval window differs")
    approval = {
        "version": "m7.8-controller-runbook-publication-approval-v1",
        "operation": "replace-and-publish-controller-runbook",
        "planSha256": plan["planSha256"],
        "issuedAtUtc": issued_at,
        "expiresAtUtc": expires_at,
    }
    return {**approval, "authorizationSha256": admission.digest(APPROVAL_DOMAIN, approval)}


def _approval_window(
    prior: dict[str, object], plan: dict[str, object], approval: object
) -> tuple[datetime, datetime]:
    if not isinstance(approval, dict):
        raise CampaignError("controller publication approval is missing")
    issued, expires = approval.get("issuedAtUtc"), approval.get("expiresAtUtc")
    if (
        not isinstance(issued, str)
        or not isinstance(expires, str)
        or approval != build_approval(plan, issued_at=issued, expires_at=expires)
    ):
        raise CampaignError("controller publication approval binding differs")
    issued_at = parse_utc(issued)
    renewal = prior.get("renewal")
    if isinstance(renewal, dict) and issued_at < parse_utc(str(renewal["completedAtUtc"])):
        raise CampaignError("controller publication approval predates renewal completion")
    return issued_at, parse_utc(expires)


def _validate_before(
    prior: dict[str, object], value: object
) -> list[dict[str, object]]:
    original = admission.validate_authority_evidence(prior)
    renewal = prior.get("renewal")
    previous = renewal["afterReadback"] if isinstance(renewal, dict) else prior["baselineReadback"]
    before = admission._readback(value, original)
    admission._preservation(admission._readback(previous, original), before)
    return before


def _verify_preservation(
    before: list[dict[str, object]], after: list[dict[str, object]]
) -> None:
    original = admission._snapshot_values(before)
    published = admission._snapshot_values(after)
    comparable = copy.deepcopy(published)
    comparable[4] = original[4]
    old_runbook = cast(dict[str, object], original[3])
    new_runbook = cast(dict[str, object], comparable[3])
    for old, new, keys in (
        (old_runbook, new_runbook, ("etag",)),
        (old_runbook["properties"], new_runbook["properties"], ("lastModifiedTime",)),
        (old_runbook.get("systemData"), new_runbook.get("systemData"),
         ("lastModifiedAt", "lastModifiedBy", "lastModifiedByType")),
    ):
        if isinstance(old, dict) and isinstance(new, dict):
            for key in keys:
                if isinstance(old.get(key), str) and isinstance(new.get(key), str):
                    new[key] = old[key]
    if admission.digest("comparison", comparable) != admission.digest("comparison", original):
        raise CampaignError("controller publication changed other tags or properties")


def validate_publication(prior: dict[str, object], value: object) -> ControllerConfig:
    publication = admission._closed(value, {
        "plan", "approval", "beforeReadback", "attempts", "afterReadback",
        "verifiedAtUtc", "proofSha256",
    }, "runbook publication")
    published = _validate_plan(prior, publication["plan"])
    plan = cast(dict[str, object], publication["plan"])
    issued, expires = _approval_window(prior, plan, publication["approval"])
    verified = parse_utc(str(publication["verifiedAtUtc"]))
    attempts = publication["attempts"]
    requests = _publication_requests(published)
    if not isinstance(attempts, list) or len(attempts) != len(requests):
        raise CampaignError("controller publication dispatch history is incomplete")
    earliest = issued
    for item, request in zip(attempts, requests, strict=True):
        attempt = admission._closed(item, {
            "requestSha256", "dispatchedAtUtc", "result",
        }, "runbook publication dispatch")
        dispatched = parse_utc(str(attempt["dispatchedAtUtc"]))
        result = admission._closed(attempt["result"], {"exitCode", "stdout", "stderr"}, "result")
        if (
            attempt["requestSha256"] != admission.digest(REQUEST_DOMAIN, request)
            or not earliest <= dispatched <= verified < expires
            or type(result["exitCode"]) is not int or result["exitCode"] != 0
            or not isinstance(result["stdout"], str) or not isinstance(result["stderr"], str)
        ):
            raise CampaignError("controller publication dispatch binding differs")
        earliest = dispatched
    before = _validate_before(prior, publication["beforeReadback"])
    bootstrap_hash = admission.bootstrap_script_hash(prior)
    after = admission._readback(
        publication["afterReadback"], published, bootstrap_hash=bootstrap_hash
    )
    _verify_preservation(before, after)
    if publication["proofSha256"] != validate_controller_results(
        after, published, bootstrap_hash=bootstrap_hash
    ):
        raise CampaignError("controller publication proof differs")
    return published


def execute_publication(
    prior: dict[str, object],
    plan: dict[str, object],
    approval: object,
    *,
    output_dir: Path,
    runner: RenewalRunner,
    clock: Callable[[], datetime],
    source: Callable[[], tuple[str, str]],
) -> dict[str, object]:
    published = _validate_plan(prior, plan)
    issued, expires = _approval_window(prior, plan, approval)

    def authorize() -> None:
        if not issued <= clock().astimezone(UTC) < expires:
            raise CampaignError("controller publication approval is not current")

    def check_source() -> None:
        if source() != (published.source_head, published.cleanup_script_sha256):
            raise CampaignError("controller publication source boundary differs")

    check_source()
    authorize()
    output_dir.mkdir(exist_ok=False)
    _durable_record(output_dir / "plan.json", plan)
    _durable_record(output_dir / "approval.json", approval)
    before = _read_controller(published, runner=runner, authorize=authorize)
    _durable_record(output_dir / "before.json", before)
    _validate_before(prior, before)
    attempts: list[dict[str, object]] = []
    for index, request in enumerate(_publication_requests(published), 1):
        check_source()
        binding = {"requestSha256": admission.digest(REQUEST_DOMAIN, request)}
        _durable_record(output_dir / f"{index}-intent.json", binding)
        dispatched = clock().astimezone(UTC)
        if not issued <= dispatched < expires:
            raise CampaignError("controller publication approval is not current")
        attempt: dict[str, object] = {**binding, "dispatchedAtUtc": dispatched.isoformat()}
        _durable_record(output_dir / f"{index}-dispatch.json", attempt)
        authorize()
        try:
            result = runner.run(tuple(request))
        except Exception as exc:
            _durable_record(output_dir / f"{index}-result.json", {"outcome": "indeterminate"})
            raise CampaignError("controller publication outcome is indeterminate") from exc
        attempt["result"] = {
            "exitCode": result.returncode, "stdout": result.stdout, "stderr": result.stderr,
        }
        _durable_record(output_dir / f"{index}-result.json", attempt)
        if result.returncode != 0:
            raise CampaignError("controller publication command failed")
        attempts.append(attempt)
    after = _read_controller(published, runner=runner, authorize=authorize)
    _durable_record(output_dir / "after.json", after)
    verified_at = clock().astimezone(UTC)
    bootstrap_hash = admission.bootstrap_script_hash(prior)
    publication = {
        "plan": plan, "approval": approval, "beforeReadback": before, "attempts": attempts,
        "afterReadback": after, "verifiedAtUtc": verified_at.isoformat(),
        "proofSha256": validate_controller_results(after, published, bootstrap_hash=bootstrap_hash),
    }
    evidence = {**prior, "runbookPublication": publication}
    admission.validate_authority_evidence(evidence)
    _durable_record(output_dir / "controller-authority-evidence.json", evidence)
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("plan", "authorize", "execute"))
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--plan-sha256")
    parser.add_argument("--expires-at-utc")
    parser.add_argument("--approval", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        root = (REPOSITORY_ROOT / ".runtime").resolve()
        output = args.output.resolve()
        if output == root or not output.is_relative_to(root) or output.exists():
            raise CampaignError("controller publication requires a new private output path")
        if Path.cwd() != REPOSITORY_ROOT:
            raise CampaignError("controller publication must run from the repository root")
        plan_path = output if args.operation == "plan" else args.plan
        if plan_path is None:
            raise CampaignError("controller publication requires the reviewed plan path")
        artifact_root = plan_path.resolve().parent
        prior = admission.load_authority_evidence(args.evidence)
        head, script_hash = local_source_binding()
        plan = build_plan(
            prior, source_head=head, script_hash=script_hash,
            artifact_root=artifact_root.relative_to(REPOSITORY_ROOT).as_posix(),
        )
        if args.operation == "plan":
            _durable_record(output, plan)
            print(json.dumps({"planSha256": plan["planSha256"]}))
            return 0
        if (
            args.plan is None
            or args.plan_sha256 != plan["planSha256"]
            or admission._json_document(args.plan.read_text(encoding="utf-8")) != plan
        ):
            raise CampaignError("controller publication requires the exact reviewed plan")
        attempt_key = str(plan["planSha256"])[:24]
        attempt_dir = artifact_root / attempt_key
        if attempt_dir.exists() or attempt_dir.resolve() != attempt_dir:
            raise CampaignError("controller publication attempt already exists or path differs")
        if args.operation == "authorize":
            if args.expires_at_utc is None or output.parent != artifact_root:
                raise CampaignError("controller publication requires a private sibling approval")
            approval = build_approval(
                plan, issued_at=datetime.now(UTC).isoformat(), expires_at=args.expires_at_utc,
            )
            _approval_window(prior, plan, approval)
            _durable_record(output, approval)
            print(json.dumps({"authorizationSha256": approval["authorizationSha256"]}))
            return 0
        if not args.execute or args.approval is None or output != attempt_dir:
            raise CampaignError("controller publication requires explicit execution authorization")
        evidence = execute_publication(
            prior, plan, admission._json_document(args.approval.read_text(encoding="utf-8")),
            output_dir=output, runner=AzureCliLauncher.resolve(), clock=lambda: datetime.now(UTC),
            source=local_source_binding,
        )
        print(json.dumps({"authorityEvidenceSha256": admission.digest(AUTHORITY_DOMAIN, evidence)}))
        return 0
    except (CampaignError, OSError, ValueError) as exc:
        message = str(exc) if isinstance(exc, CampaignError) else "controller publication failed"
        print(message)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
