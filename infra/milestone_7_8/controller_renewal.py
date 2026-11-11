"""Plan or explicitly execute one controller deadline renewal attempt.

Execution records dispatch only; it never emits renewal completion evidence.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast

from infra.milestone_7_8 import controller_admission as admission
from infra.milestone_7_8.campaign import CampaignError, parse_utc
from infra.milestone_7_8.cleanup_controller import controller_binding_sha256
from infra.milestone_7_8.controller import (
    ControllerConfig,
    controller_command_plan,
    controller_config_document,
    controller_config_sha256,
    validate_controller_authorization_document,
)


class RenewalRunner(Protocol):
    def run(self, arguments: tuple[str, ...]) -> subprocess.CompletedProcess[str]: ...


def collect_before_snapshot(
    evidence: object,
    plan: dict[str, object],
    authorization: object,
    *,
    runner: RenewalRunner,
    clock: Callable[[], datetime],
) -> list[dict[str, object]]:
    """Read the original controller under an exact current verification approval."""
    original = admission.validate_authority_evidence(evidence)
    renewed = ControllerConfig.from_document(plan.get("renewedConfig"))
    if plan != build_plan(
        evidence,
        source_head=renewed.source_head,
        deadline=renewed.controller_authorized_until_utc,
    ):
        raise CampaignError("controller renewal plan binding differs")

    def authorize() -> None:
        validate_controller_authorization_document(
            authorization,
            config=renewed,
            operation="controller-verify",
            now=clock().astimezone(UTC),
        )

    results = admission._readback(
        _read_controller(renewed, authorize=authorize, runner=runner), original
    )
    if isinstance(evidence, dict) and isinstance(evidence.get("renewal"), dict):
        previous = admission._readback(evidence["renewal"]["afterReadback"], original)
        admission._preservation(previous, results)
    return results


def _read_controller(
    config: ControllerConfig,
    *,
    runner: RenewalRunner,
    authorize: Callable[[], None],
) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for command in controller_command_plan("controller-verify", config):
        authorize()
        try:
            result = runner.run(
                (
                    *command[1:],
                    "--subscription",
                    config.subscription_id,
                    "--only-show-errors",
                )
            )
        except Exception as exc:
            raise CampaignError("controller renewal readback failed") from exc
        if (
            result.returncode != 0
            or not isinstance(result.stdout, str)
            or not isinstance(result.stderr, str)
        ):
            raise CampaignError("controller renewal readback failed")
        results.append(
            {
                "exitCode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        )
    return results


def load_executor_journal(
    directory: Path,
    plan: dict[str, object],
    approval: dict[str, object],
    before: object,
) -> dict[str, object]:
    """Load actual executor records; never infer dispatch from a matching tag."""

    def read(name: str) -> object:
        try:
            return admission._json_document(
                (directory / name).read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as exc:
            raise CampaignError(
                "controller renewal attempt is partial or indeterminate"
            ) from exc

    if read("00-context.json") != {
        "plan": plan,
        "approval": approval,
        "beforeReadback": before,
    }:
        raise CampaignError("controller renewal executor context differs")
    completed = directory / "complete-dispatch-journal.json"
    uncertain = directory / "indeterminate-dispatch-journal.json"
    if not completed.exists() and not uncertain.exists():
        raise CampaignError("controller renewal attempt is partial or indeterminate")
    if completed.exists() and uncertain.exists():
        raise CampaignError("controller renewal executor journal is incomplete")
    journal = read(completed.name if completed.exists() else uncertain.name)
    validate_attempt_journal(plan, approval, journal)
    assert isinstance(journal, dict)
    for index, attempt in enumerate(journal["attempts"]):
        intent = read(f"{index + 1:02d}-intent.json")
        dispatch = read(f"{index + 1:02d}-dispatch.json")
        outcome = read(f"{index + 1:02d}-outcome.json")
        if not isinstance(intent, dict) or set(intent) != {
            "index",
            "requestSha256",
            "intentAtUtc",
        }:
            raise CampaignError("controller renewal intent is incomplete")
        if (
            intent["index"] != index
            or intent["requestSha256"] != attempt["requestSha256"]
        ):
            raise CampaignError("controller renewal intent binding differs")
        if parse_utc(str(intent["intentAtUtc"])) > parse_utc(
            str(attempt["dispatchedAtUtc"])
        ):
            raise CampaignError("controller renewal intent time differs")
        if dispatch != {
            key: attempt[key] for key in ("index", "requestSha256", "dispatchedAtUtc")
        }:
            raise CampaignError("controller renewal dispatch record differs")
        if attempt["outcome"] == "success":
            if outcome != attempt:
                raise CampaignError("controller renewal outcome differs")
            response = read(f"{index + 1:02d}-response.json")
            if (
                not isinstance(response, dict)
                or set(response) != {"exitCode", "stdout", "stderr"}
                or type(response.get("exitCode")) is not int
                or response["exitCode"] != 0
                or not isinstance(response["stdout"], str)
                or not isinstance(response["stderr"], str)
            ):
                raise CampaignError("controller renewal response is incomplete")
        elif not isinstance(outcome, dict) or outcome.get("outcome") != "indeterminate":
            raise CampaignError("controller renewal uncertain outcome differs")
    return cast(dict[str, object], journal)


def reconcile_renewal(
    evidence: dict[str, object],
    plan: dict[str, object],
    before: object,
    approval: dict[str, object],
    reconciliation_authorization: dict[str, object],
    *,
    journal_dir: Path,
    output_dir: Path,
    runner: RenewalRunner,
    clock: Callable[[], datetime],
    persist: Callable[[Path, object], None] | None = None,
) -> dict[str, object]:
    """Reconcile one recorded attempt using reads only, or leave it blocked."""
    if persist is None:
        persist = _durable_record
    original = admission.validate_authority_evidence(evidence)
    renewed = ControllerConfig.from_document(plan.get("renewedConfig"))
    journal = load_executor_journal(journal_dir, plan, approval, before)
    issued, expires = (
        reconciliation_authorization.get("issuedAtUtc"),
        reconciliation_authorization.get("expiresAtUtc"),
    )
    if not isinstance(issued, str) or not isinstance(expires, str):
        raise CampaignError("controller reconciliation approval window is invalid")

    def authorize() -> None:
        expected = build_reconciliation_approval(
            evidence,
            plan,
            before,
            approval,
            journal,
            issued_at=issued,
            expires_at=expires,
            now=clock().astimezone(UTC),
            source_head=cast(str | None, reconciliation_authorization.get("reconciliationSourceHead")),
        )
        if expected != reconciliation_authorization:
            raise CampaignError("controller reconciliation approval binding differs")

    authorize()
    output_dir.mkdir(mode=0o700, parents=False, exist_ok=False)
    persist(
        output_dir / "00-reconciliation-context.json",
        {
            "planSha256": plan["planSha256"],
            "authorization": reconciliation_authorization,
            "attemptJournal": journal,
        },
    )
    after = _read_controller(renewed, authorize=authorize, runner=runner)
    observed = clock().astimezone(UTC)
    authorize()
    persist(output_dir / "01-after-readback.json", after)
    admission._readback(after, renewed)
    before_validated = admission._readback(before, original)
    preservation = admission._preservation(before_validated, after)
    binding = cast(str, plan["controllerBindingSha256"])
    completion: dict[str, object] = {
        "version": "m7.8-controller-renewal-completion-v1",
        "status": "complete",
        "controllerBindingSha256": binding,
        "originalConfigSha256": controller_config_sha256(original),
        "renewedConfigSha256": controller_config_sha256(renewed),
        "renewalApprovalSha256": approval["authorizationSha256"],
        "baselinePreservationSha256": preservation,
        "originalDeadlineUtc": original.controller_authorized_until_utc,
        "observedDeadlineUtc": renewed.controller_authorized_until_utc,
        "allResourcesReadBack": True,
        "otherTagsAndPropertiesPreserved": True,
    }
    completion["receiptSha256"] = admission.digest(
        "m7.8/controller-renewal-completion/v1", completion
    )
    observed_text = observed.isoformat(timespec="microseconds").replace("+00:00", "Z")
    attempts = cast(list[dict[str, object]], journal["attempts"])
    renewal = {
        "renewedConfig": controller_config_document(renewed),
        "approval": approval,
        "beforeReadback": before_validated,
        "afterReadback": after,
        "completion": completion,
        "startedAtUtc": attempts[0]["dispatchedAtUtc"],
        "completedAtUtc": observed_text,
        "reconciliation": {
            "plan": plan,
            "attemptJournal": journal,
            "authorization": reconciliation_authorization,
            "observationSha256": admission.digest(
                "m7.8/controller-renewal-observation/v1",
                {
                    "observedAtUtc": observed_text,
                    "readback": admission._snapshot_values(after),
                },
            ),
        },
    }
    if evidence.get("renewal") is not None:
        renewal["priorAuthorityEvidence"] = evidence
    result = {**evidence, "renewal": renewal}
    admission.validate_authority_evidence(result)
    persist(output_dir / "02-completed-authority-evidence.json", result)
    return result


def _durable_record(path: Path, document: object) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
        json.dump(
            document, stream, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def execute_renewal(
    evidence: object,
    plan: dict[str, object],
    before_readback: object,
    approval: dict[str, object],
    *,
    output_dir: Path,
    runner: RenewalRunner,
    clock: Callable[[], datetime],
    persist: Callable[[Path, object], None] = _durable_record,
) -> dict[str, object]:
    """Dispatch at most three exact authorized updates, never retrying one."""
    issued, expires = approval.get("issuedAtUtc"), approval.get("expiresAtUtc")
    if not isinstance(issued, str) or not isinstance(expires, str):
        raise CampaignError("controller renewal approval window is invalid")
    now = clock().astimezone(UTC)
    if (
        build_approval(
            evidence,
            plan,
            before_readback,
            issued_at=issued,
            expires_at=expires,
            now=now,
        )
        != approval
    ):
        raise CampaignError("controller renewal approval binding differs")
    output_dir.mkdir(mode=0o700, parents=False, exist_ok=False)
    persist(
        output_dir / "00-context.json",
        {"plan": plan, "approval": approval, "beforeReadback": before_readback},
    )
    requests = cast(list[dict[str, object]], plan["requests"])
    attempts: list[dict[str, object]] = []
    for index, request in enumerate(requests):
        boundary = clock().astimezone(UTC)
        if not parse_utc(issued) <= boundary < parse_utc(expires):
            raise CampaignError("controller renewal approval expired before dispatch")
        intent: dict[str, object] = {
            "index": index,
            "requestSha256": admission.digest(
                "m7.8/controller-renewal-request/v1", request
            ),
            "intentAtUtc": boundary.isoformat(timespec="microseconds").replace(
                "+00:00", "Z"
            ),
        }
        persist(output_dir / f"{index + 1:02d}-intent.json", intent)
        dispatch_boundary = clock().astimezone(UTC)
        if not parse_utc(issued) <= dispatch_boundary < parse_utc(expires):
            raise CampaignError("controller renewal approval expired before dispatch")
        attempt: dict[str, object] = {
            "index": index,
            "requestSha256": intent["requestSha256"],
            "dispatchedAtUtc": dispatch_boundary.isoformat(
                timespec="microseconds"
            ).replace("+00:00", "Z"),
        }
        try:
            result = runner.run(
                (
                    "rest",
                    "--method",
                    "patch",
                    "--url",
                    cast(str, request["url"]),
                    "--body",
                    json.dumps(request["body"], separators=(",", ":")),
                    "--output",
                    "json",
                    "--only-show-errors",
                )
            )
        except Exception as exc:
            persist(output_dir / f"{index + 1:02d}-dispatch.json", attempt)
            persist(
                output_dir / f"{index + 1:02d}-outcome.json",
                {"outcome": "indeterminate", "errorClass": type(exc).__name__},
            )
            if index == 2:
                attempt["outcome"] = "indeterminate"
                attempts.append(attempt)
                ambiguous_journal: dict[str, object] = {
                    "version": "m7.8-controller-renewal-attempt-journal-v1",
                    "renewalPlanSha256": plan["planSha256"],
                    "renewalApprovalSha256": approval["authorizationSha256"],
                    "attempts": attempts,
                }
                validate_attempt_journal(plan, approval, ambiguous_journal)
                persist(
                    output_dir / "indeterminate-dispatch-journal.json",
                    ambiguous_journal,
                )
            raise CampaignError(
                "controller renewal dispatch outcome indeterminate"
            ) from exc
        persist(output_dir / f"{index + 1:02d}-dispatch.json", attempt)
        if not isinstance(result.stdout, str) or not isinstance(result.stderr, str):
            persist(
                output_dir / f"{index + 1:02d}-outcome.json",
                {"outcome": "indeterminate", "errorClass": "UnreadableResponse"},
            )
            raise CampaignError("controller renewal dispatch outcome indeterminate")
        response = {
            "exitCode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
        persist(output_dir / f"{index + 1:02d}-response.json", response)
        if result.returncode != 0:
            persist(
                output_dir / f"{index + 1:02d}-outcome.json",
                {"outcome": "indeterminate", "exitCode": result.returncode},
            )
            raise CampaignError("controller renewal request failed or is ambiguous")
        attempt["outcome"] = "success"
        persist(output_dir / f"{index + 1:02d}-outcome.json", attempt)
        attempts.append(attempt)
    journal: dict[str, object] = {
        "version": "m7.8-controller-renewal-attempt-journal-v1",
        "renewalPlanSha256": plan["planSha256"],
        "renewalApprovalSha256": approval["authorizationSha256"],
        "attempts": attempts,
    }
    validate_attempt_journal(plan, approval, journal)
    persist(output_dir / "complete-dispatch-journal.json", journal)
    return journal


def build_plan(
    evidence: object, *, source_head: str, deadline: str
) -> dict[str, object]:
    original = admission.validate_authority_evidence(evidence)
    if not isinstance(evidence, dict):
        raise CampaignError("renewal plan requires validated authority evidence")
    prior = evidence.get("renewal")
    if prior is not None and (
        not isinstance(prior, dict) or "priorAuthorityEvidence" in prior
    ):
        raise CampaignError("only one subsequent controller renewal is supported")
    if parse_utc(deadline) <= parse_utc(original.controller_authorized_until_utc):
        raise CampaignError("renewal deadline must increase")
    renewed = replace(
        original, source_head=source_head, controller_authorized_until_utc=deadline
    )
    renewed.validate()
    before = admission._readback(
        evidence["baselineReadback"] if prior is None else prior["afterReadback"], original
    )
    group = f"/subscriptions/{original.subscription_id}/resourceGroups/{original.controller_resource_group_name}"
    account = f"{group}/providers/Microsoft.Automation/automationAccounts/{original.automation_account_name}"
    targets = (group, account, f"{account}/runbooks/{original.runbook_name}")
    binding = controller_binding_sha256(
        original.subscription_id,
        resource_group=original.controller_resource_group_name,
        account=original.automation_account_name,
        runbook=original.runbook_name,
    )
    plan: dict[str, object] = {
        "version": "m7.8-controller-renewal-plan-v1",
        "operation": "controller-renew-deadline-tags",
        "controllerBindingSha256": binding,
        "originalConfigSha256": controller_config_sha256(original),
        "renewedConfigSha256": controller_config_sha256(renewed),
        "originalDeadlineUtc": original.controller_authorized_until_utc,
        "renewedDeadlineUtc": deadline,
        "baselineReadbackSha256": admission.digest(
            "m7.8/controller-renewal-before/v1", admission._snapshot_values(before)
        ),
        "renewedConfig": controller_config_document(renewed),
        "requests": [
            {
                "method": "PATCH",
                "url": f"https://management.azure.com{scope}/providers/Microsoft.Resources/tags/default?api-version=2021-04-01",
                "body": {
                    "operation": "Merge",
                    "properties": {"tags": {admission.DEADLINE_TAG: deadline}},
                },
            }
            for scope in targets
        ],
    }
    if prior is not None:
        plan["priorAuthorityEvidenceSha256"] = admission.digest(
            "m7.8/controller-authority-evidence/v1", evidence
        )
    plan["planSha256"] = admission.digest("m7.8/controller-renewal-plan/v1", plan)
    return plan


def build_approval(
    evidence: object,
    plan: dict[str, object],
    before_readback: object,
    *,
    issued_at: str,
    expires_at: str,
    now: datetime,
) -> dict[str, object]:
    """Build an exact approval from a validated pre-update observation.

    The caller supplies the explicit review times. This function performs no
    provider action and does not itself record user approval.
    """
    original = admission.validate_authority_evidence(evidence)
    renewed_document = plan.get("renewedConfig")
    from infra.milestone_7_8.controller import ControllerConfig

    renewed = ControllerConfig.from_document(renewed_document)
    expected_plan = build_plan(
        evidence,
        source_head=renewed.source_head,
        deadline=renewed.controller_authorized_until_utc,
    )
    if plan != expected_plan:
        raise CampaignError("controller renewal plan binding differs")
    before = admission._readback(before_readback, original)
    if isinstance(evidence, dict) and isinstance(evidence.get("renewal"), dict):
        previous = admission._readback(evidence["renewal"]["afterReadback"], original)
        admission._preservation(previous, before)
    issued = parse_utc(issued_at)
    expires = parse_utc(expires_at)
    if (
        not issued
        <= now
        < expires
        <= parse_utc(renewed.controller_authorized_until_utc)
    ):
        raise CampaignError("controller renewal approval window is invalid")
    payload: dict[str, object] = {
        "version": "m7.8-controller-renewal-approval-v1",
        "operation": "controller-renew-deadline-tags",
        "controllerBindingSha256": plan["controllerBindingSha256"],
        "originalConfigSha256": plan["originalConfigSha256"],
        "renewedConfigSha256": plan["renewedConfigSha256"],
        "originalDeadlineUtc": plan["originalDeadlineUtc"],
        "renewedDeadlineUtc": plan["renewedDeadlineUtc"],
        "baselineReadbackSha256": admission.digest(
            "m7.8/controller-renewal-before/v1", admission._snapshot_values(before)
        ),
        "issuedAtUtc": issued_at,
        "expiresAtUtc": expires_at,
    }
    payload["authorizationSha256"] = admission.digest(
        "m7.8/controller-renewal-approval/v1", payload
    )
    return payload


def build_reconciliation_approval(
    evidence: object,
    plan: dict[str, object],
    before_readback: object,
    renewal_approval: dict[str, object],
    attempt_journal: object,
    *,
    issued_at: str,
    expires_at: str,
    now: datetime,
    source_head: str | None = None,
) -> dict[str, object]:
    """Bind a separate GET-only reconciliation approval to the original attempt."""
    original_issued = renewal_approval.get("issuedAtUtc")
    original_expiry = renewal_approval.get("expiresAtUtc")
    if not isinstance(original_issued, str) or not isinstance(original_expiry, str):
        raise CampaignError("controller renewal approval window is invalid")
    expected = build_approval(
        evidence,
        plan,
        before_readback,
        issued_at=original_issued,
        expires_at=original_expiry,
        now=parse_utc(original_issued),
    )
    if renewal_approval != expected:
        raise CampaignError("controller renewal approval binding differs")
    journal_hash = validate_attempt_journal(plan, renewal_approval, attempt_journal)
    issued = parse_utc(issued_at)
    expires = parse_utc(expires_at)
    deadline = parse_utc(str(plan["renewedDeadlineUtc"]))
    if not issued <= now < expires <= deadline:
        raise CampaignError("controller reconciliation approval window is invalid")
    payload: dict[str, object] = {
        "version": "m7.8-controller-renewal-reconciliation-approval-v1",
        "operation": "controller-renewal-reconcile-get-only",
        "controllerBindingSha256": plan["controllerBindingSha256"],
        "renewalPlanSha256": plan["planSha256"],
        "renewalApprovalSha256": renewal_approval["authorizationSha256"],
        "attemptJournalSha256": journal_hash,
        "issuedAtUtc": issued_at,
        "expiresAtUtc": expires_at,
    }
    if source_head is not None:
        if not isinstance(source_head, str) or re.fullmatch(r"[a-f0-9]{40}", source_head) is None:
            raise CampaignError("controller reconciliation source head is malformed")
        payload["reconciliationSourceHead"] = source_head
    payload["authorizationSha256"] = admission.digest(
        "m7.8/controller-renewal-reconciliation-approval/v1", payload
    )
    return payload


def validate_attempt_journal(
    plan: dict[str, object], approval: dict[str, object], journal: object
) -> str:
    """Validate the complete ordered dispatch history, without inventing outcomes."""
    if not isinstance(journal, dict) or set(journal) != {
        "version",
        "renewalPlanSha256",
        "renewalApprovalSha256",
        "attempts",
    }:
        raise CampaignError("controller renewal attempt journal is incomplete")
    if (
        journal["version"] != "m7.8-controller-renewal-attempt-journal-v1"
        or journal["renewalPlanSha256"] != plan.get("planSha256")
        or journal["renewalApprovalSha256"] != approval.get("authorizationSha256")
    ):
        raise CampaignError("controller renewal attempt journal binding differs")
    requests = plan.get("requests")
    attempts = journal.get("attempts")
    if (
        not isinstance(requests, list)
        or len(requests) != 3
        or not isinstance(attempts, list)
        or len(attempts) != 3
    ):
        raise CampaignError("controller renewal attempt journal is incomplete")
    issued = parse_utc(str(approval.get("issuedAtUtc")))
    expiry = parse_utc(str(approval.get("expiresAtUtc")))
    previous = issued
    for index, (request, attempt) in enumerate(zip(requests, attempts, strict=True)):
        if not isinstance(attempt, dict) or set(attempt) != {
            "index",
            "requestSha256",
            "dispatchedAtUtc",
            "outcome",
        }:
            raise CampaignError("controller renewal attempt journal is incomplete")
        if (
            type(attempt["index"]) is not int
            or attempt["index"] != index
            or attempt["requestSha256"]
            != admission.digest("m7.8/controller-renewal-request/v1", request)
            or not isinstance(attempt["outcome"], str)
            or attempt["outcome"] not in {"success", "indeterminate"}
            or (index < 2 and attempt["outcome"] != "success")
            or not isinstance(attempt["dispatchedAtUtc"], str)
        ):
            raise CampaignError("controller renewal attempt journal binding differs")
        dispatched = parse_utc(attempt["dispatchedAtUtc"])
        if not previous <= dispatched < expiry:
            raise CampaignError("controller renewal dispatch outside approval window")
        previous = dispatched
    return admission.digest("m7.8/controller-renewal-attempt-journal/v1", journal)


def _validate_read_source(
    operation: str, renewed: ControllerConfig, authorization: dict[str, object],
    head: str, script_hash: str,
) -> None:
    authorized_head = authorization.get("reconciliationSourceHead")
    if (
        renewed.cleanup_script_sha256 != script_hash
        or (authorized_head is not None and authorized_head != head)
        or (
            renewed.source_head != head
            and not (operation == "reconcile" and authorized_head == head)
        )
    ):
        raise CampaignError("controller renewal source boundary differs")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--operation",
        choices=("plan", "execute", "before-snapshot", "reconcile"),
        default="plan",
    )
    parser.add_argument("--authority-evidence", required=True, type=Path)
    parser.add_argument("--source-head")
    parser.add_argument("--deadline")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--approval", type=Path)
    parser.add_argument("--before-readback", type=Path)
    parser.add_argument("--read-authorization", type=Path)
    parser.add_argument("--journal-dir", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        evidence = admission.load_authority_evidence(args.authority_evidence)
        if args.operation in {"before-snapshot", "reconcile"}:
            required = [args.plan, args.read_authorization, args.output]
            if args.operation == "reconcile":
                required.extend([args.approval, args.before_readback, args.journal_dir])
            if not args.execute or any(item is None for item in required):
                raise CampaignError(
                    "controller renewal reads require explicit execution and exact private inputs"
                )
            from infra.milestone_7_8.azure_cli import AzureCliLauncher
            from infra.milestone_7_8.controller import (
                REPOSITORY_ROOT,
                local_source_binding,
            )

            def read(path: Path | None) -> object:
                if path is None:
                    raise CampaignError("controller renewal input missing")
                return admission._json_document(path.read_text(encoding="utf-8"))

            plan_doc = read(args.plan)
            read_auth = read(args.read_authorization)
            if not isinstance(plan_doc, dict) or not isinstance(read_auth, dict):
                raise CampaignError("controller renewal read inputs are malformed")
            renewed = ControllerConfig.from_document(plan_doc.get("renewedConfig"))
            head, script_hash = local_source_binding()
            _validate_read_source(args.operation, renewed, read_auth, head, script_hash)
            assert args.output is not None
            runtime_root = (REPOSITORY_ROOT / ".runtime").resolve()
            target = args.output.resolve()
            if target == runtime_root or not target.is_relative_to(runtime_root):
                raise CampaignError(
                    "controller renewal output must be private and ignored"
                )
            runner = AzureCliLauncher.resolve()
            if args.operation == "before-snapshot":
                if target.exists():
                    raise CampaignError("controller renewal output already exists")
                snapshot = collect_before_snapshot(
                    evidence,
                    plan_doc,
                    read_auth,
                    runner=runner,
                    clock=lambda: datetime.now(UTC),
                )
                _durable_record(target, snapshot)
                print(
                    json.dumps(
                        {
                            "status": "before-snapshot-recorded",
                            "snapshotSha256": admission.digest(
                                "m7.8/controller-renewal-before/v1",
                                admission._snapshot_values(snapshot),
                            ),
                        }
                    )
                )
            else:
                mutation_auth = read(args.approval)
                if not isinstance(mutation_auth, dict) or args.journal_dir is None:
                    raise CampaignError(
                        "controller renewal mutation approval is malformed"
                    )
                journal = args.journal_dir.resolve()
                if journal == runtime_root or not journal.is_relative_to(runtime_root):
                    raise CampaignError(
                        "controller renewal journal must be private and ignored"
                    )
                result = reconcile_renewal(
                    evidence,
                    plan_doc,
                    read(args.before_readback),
                    mutation_auth,
                    read_auth,
                    journal_dir=journal,
                    output_dir=target,
                    runner=runner,
                    clock=lambda: datetime.now(UTC),
                )
                print(
                    json.dumps(
                        {
                            "status": "reconciled",
                            "evidenceSha256": admission.digest(
                                "m7.8/controller-authority-evidence/v1", result
                            ),
                        }
                    )
                )
            return 0
        if args.operation == "execute":
            if not args.execute or any(
                value is None
                for value in (
                    args.plan,
                    args.approval,
                    args.before_readback,
                    args.journal_dir,
                )
            ):
                raise CampaignError(
                    "controller renewal execution requires explicit authorization and private inputs"
                )
            from infra.milestone_7_8.azure_cli import AzureCliLauncher
            from infra.milestone_7_8.controller import (
                REPOSITORY_ROOT,
                local_source_binding,
            )

            plan_value = admission._json_document(args.plan.read_text(encoding="utf-8"))
            approval_value = admission._json_document(
                args.approval.read_text(encoding="utf-8")
            )
            before = admission._json_document(
                args.before_readback.read_text(encoding="utf-8")
            )
            if not isinstance(plan_value, dict) or not isinstance(approval_value, dict):
                raise CampaignError("controller renewal execution inputs are malformed")
            head, script_hash = local_source_binding()
            renewed = ControllerConfig.from_document(plan_value.get("renewedConfig"))
            if (
                renewed.source_head != head
                or renewed.cleanup_script_sha256 != script_hash
            ):
                raise CampaignError("controller renewal source boundary differs")
            runtime_root = (REPOSITORY_ROOT / ".runtime").resolve()
            target = args.journal_dir.resolve()
            if not target.is_relative_to(runtime_root) or target == runtime_root:
                raise CampaignError(
                    "controller renewal journal must be private and ignored"
                )
            journal = execute_renewal(
                evidence,
                cast(dict[str, object], plan_value),
                before,
                cast(dict[str, object], approval_value),
                output_dir=target,
                runner=AzureCliLauncher.resolve(),
                clock=lambda: datetime.now(UTC),
            )
            print(
                json.dumps(
                    {
                        "status": "updates-dispatched-awaiting-readback",
                        "journalSha256": validate_attempt_journal(
                            cast(dict[str, object], plan_value),
                            cast(dict[str, object], approval_value),
                            journal,
                        ),
                    }
                )
            )
            return 0
        if (
            args.execute
            or args.source_head is None
            or args.deadline is None
            or args.output is None
        ):
            raise CampaignError("controller renewal plan inputs are incomplete")
        plan = build_plan(
            evidence, source_head=args.source_head, deadline=args.deadline
        )
        descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(plan, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
        print(
            json.dumps(
                {"status": "plan-only", "planSha256": cast(str, plan["planSha256"])}
            )
        )
        return 0
    except (CampaignError, OSError, ValueError, subprocess.SubprocessError) as exc:
        status = (
            "indeterminate"
            if str(exc) == "controller renewal attempt is partial or indeterminate"
            else "blocked"
        )
        print(json.dumps({"status": status, "reason": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
