from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from infra.milestone_7_8.campaign import (
    CampaignError,
    SubprocessRunner,
    parse_utc,
    sanitize,
)
from infra.milestone_7_8.cleanup_controller import (
    ARCHITECTURE,
    CONTROLLER_RUNBOOK_NAME,
    controller_names,
)

OPERATIONS = frozenset({"controller-bootstrap", "controller-verify"})
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True, slots=True)
class ControllerConfig:
    subscription_id: str
    subscription_correlation: str
    source_head: str
    controller_location: str
    controller_resource_group_name: str
    automation_account_name: str
    runbook_name: str
    controller_authorized_until_utc: str
    cleanup_script_sha256: str
    deployment_name: str

    @classmethod
    def load(cls, path: Path) -> ControllerConfig:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CampaignError("controller configuration is unreadable") from exc
        fields = {
            "subscriptionId",
            "subscriptionCorrelation",
            "sourceHead",
            "controllerLocation",
            "controllerResourceGroupName",
            "automationAccountName",
            "runbookName",
            "controllerAuthorizedUntilUtc",
            "cleanupScriptSha256",
            "deploymentName",
        }
        if (
            not isinstance(value, dict)
            or set(value) != fields
            or not all(isinstance(item, str) and item for item in value.values())
        ):
            raise CampaignError("controller configuration fields are invalid")
        config = cls(
            subscription_id=cast(str, value["subscriptionId"]),
            subscription_correlation=cast(str, value["subscriptionCorrelation"]),
            source_head=cast(str, value["sourceHead"]),
            controller_location=cast(str, value["controllerLocation"]),
            controller_resource_group_name=cast(
                str, value["controllerResourceGroupName"]
            ),
            automation_account_name=cast(str, value["automationAccountName"]),
            runbook_name=cast(str, value["runbookName"]),
            controller_authorized_until_utc=cast(
                str, value["controllerAuthorizedUntilUtc"]
            ),
            cleanup_script_sha256=cast(str, value["cleanupScriptSha256"]),
            deployment_name=cast(str, value["deploymentName"]),
        )
        config.validate()
        return config

    def validate(self) -> None:
        try:
            parsed_subscription = uuid.UUID(self.subscription_id)
        except ValueError as exc:
            raise CampaignError("controller subscription is malformed") from exc
        expected_names = controller_names(self.subscription_correlation)
        if (
            parsed_subscription.int == 0
            or sanitize(self.subscription_id, domain="subscription")
            != self.subscription_correlation
            or re.fullmatch(r"[a-f0-9]{40}", self.source_head) is None
            or re.fullmatch(r"[a-z][a-z0-9]{2,31}", self.controller_location) is None
            or self.controller_resource_group_name != expected_names.resource_group
            or self.automation_account_name != expected_names.account
            or self.runbook_name != CONTROLLER_RUNBOOK_NAME
            or re.fullmatch(r"[a-f0-9]{64}", self.cleanup_script_sha256) is None
            or self.deployment_name
            != f"m78-controller-{self.subscription_correlation[:10]}"
        ):
            raise CampaignError("controller configuration binding is malformed")
        parse_utc(self.controller_authorized_until_utc)


def load_controller_authorization(
    path: Path,
    *,
    config: ControllerConfig,
    operation: str,
    now: datetime | None = None,
) -> str:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CampaignError("controller execution authorization is unreadable") from exc
    fields = {
        "version",
        "disposition",
        "operation",
        "subscriptionCorrelation",
        "sourceHead",
        "controllerArchitecture",
        "controllerLocation",
        "controllerResourceGroupName",
        "automationAccountName",
        "controllerAuthorizedUntilUtc",
        "expiresAtUtc",
        "authorizationSha256",
    }
    unsigned = (
        {key: item for key, item in value.items() if key != "authorizationSha256"}
        if isinstance(value, dict)
        else {}
    )
    expected_hash = hashlib.sha256(
        b"m7.8/controller-execution-authorization/v1\0"
        + json.dumps(unsigned, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    if (
        not isinstance(value, dict)
        or set(value) != fields
        or operation not in OPERATIONS
        or value.get("version") != "m7.8-controller-execution-authorization-v1"
        or value.get("disposition") != "separately-authorized-controller-execution"
        or value.get("operation") != operation
        or value.get("subscriptionCorrelation") != config.subscription_correlation
        or value.get("sourceHead") != config.source_head
        or value.get("controllerArchitecture") != ARCHITECTURE
        or value.get("controllerLocation") != config.controller_location
        or value.get("controllerResourceGroupName")
        != config.controller_resource_group_name
        or value.get("automationAccountName") != config.automation_account_name
        or value.get("controllerAuthorizedUntilUtc")
        != config.controller_authorized_until_utc
        or value.get("authorizationSha256") != expected_hash
    ):
        raise CampaignError("controller execution authorization is not exact")
    expires = value.get("expiresAtUtc")
    if not isinstance(expires, str):
        raise CampaignError("controller execution authorization expiry is malformed")
    observed_now = (now or datetime.now(UTC)).astimezone(UTC)
    if parse_utc(expires) <= observed_now or parse_utc(expires) > parse_utc(
        config.controller_authorized_until_utc
    ):
        raise CampaignError(
            "controller execution authorization is expired or overbroad"
        )
    return expected_hash


def validate_local_boundary(config: ControllerConfig) -> None:
    def git(*arguments: str) -> str:
        completed = subprocess.run(
            ("git", *arguments),
            cwd=REPOSITORY_ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if completed.returncode != 0:
            raise CampaignError("controller Git preflight failed")
        return completed.stdout.strip()

    script_sha256 = hashlib.sha256(
        (
            REPOSITORY_ROOT / "infra/milestone_7_8/scripts/Remove-M78Campaign.ps1"
        ).read_bytes()
    ).hexdigest()
    if (
        git("status", "--porcelain=v1")
        or git("rev-parse", "HEAD") != config.source_head
        or git("branch", "--show-current")
        != "milestone-7-8-production-readiness-audit-local"
        or git(
            "for-each-ref",
            "--format=%(upstream)",
            "refs/heads/milestone-7-8-production-readiness-audit-local",
        )
        or len(git("stash", "list", "--format=%H").splitlines()) != 5
        or script_sha256 != config.cleanup_script_sha256
    ):
        raise CampaignError("controller local source boundary differs")


def controller_command_plan(
    operation: str, config: ControllerConfig
) -> tuple[tuple[str, ...], ...]:
    config.validate()
    if operation not in OPERATIONS:
        raise CampaignError("controller operation is unsupported")
    base = (
        "https://management.azure.com/subscriptions/"
        f"{config.subscription_id}/resourceGroups/{config.controller_resource_group_name}/"
        "providers/Microsoft.Automation/automationAccounts/"
        f"{config.automation_account_name}"
    )
    reads = (
        (
            "az",
            "group",
            "show",
            "--name",
            config.controller_resource_group_name,
            "--output",
            "json",
        ),
        (
            "az",
            "automation",
            "account",
            "show",
            "--resource-group",
            config.controller_resource_group_name,
            "--name",
            config.automation_account_name,
            "--output",
            "json",
        ),
        (
            "az",
            "role",
            "assignment",
            "list",
            "--scope",
            f"/subscriptions/{config.subscription_id}/resourceGroups/"
            f"{config.controller_resource_group_name}",
            "--output",
            "json",
        ),
        (
            "az",
            "rest",
            "--method",
            "get",
            "--url",
            f"{base}/runbooks/{config.runbook_name}?api-version=2024-10-23",
            "--output",
            "json",
        ),
        (
            "az",
            "rest",
            "--method",
            "get",
            "--url",
            f"{base}/runbooks/{config.runbook_name}/content?api-version=2024-10-23",
            "--output",
            "tsv",
        ),
        (
            "az",
            "rest",
            "--method",
            "get",
            "--url",
            f"{base}/schedules?api-version=2024-10-23",
            "--output",
            "json",
        ),
        (
            "az",
            "rest",
            "--method",
            "get",
            "--url",
            f"{base}/jobSchedules?api-version=2024-10-23",
            "--output",
            "json",
        ),
    )
    if operation == "controller-verify":
        return reads
    return (
        (
            "az",
            "deployment",
            "sub",
            "create",
            "--name",
            config.deployment_name,
            "--location",
            config.controller_location,
            "--template-file",
            "infra/milestone_7_8/controller.bicep",
            "--parameters",
            f"subscriptionCorrelation={config.subscription_correlation}",
            f"controllerResourceGroupName={config.controller_resource_group_name}",
            f"controllerLocation={config.controller_location}",
            f"automationAccountName={config.automation_account_name}",
            f"cleanupRunbookName={config.runbook_name}",
            f"controllerAuthorizedUntilUtc={config.controller_authorized_until_utc}",
            f"cleanupScriptSha256={config.cleanup_script_sha256}",
            "--output",
            "json",
        ),
        (
            "az",
            "automation",
            "runbook",
            "replace-content",
            "--resource-group",
            config.controller_resource_group_name,
            "--automation-account-name",
            config.automation_account_name,
            "--name",
            config.runbook_name,
            "--content",
            "@infra/milestone_7_8/scripts/Remove-M78Campaign.ps1",
        ),
        (
            "az",
            "automation",
            "runbook",
            "publish",
            "--resource-group",
            config.controller_resource_group_name,
            "--automation-account-name",
            config.automation_account_name,
            "--name",
            config.runbook_name,
        ),
        *reads,
    )


def _run_required(
    runner: SubprocessRunner, command: tuple[str, ...]
) -> dict[str, object]:
    result = runner.run(command)
    if result.get("exitCode") != 0:
        raise CampaignError("controller command failed safely")
    return result


def _json_result(result: dict[str, object]) -> object:
    raw = result.get("stdout")
    if not isinstance(raw, str):
        raise CampaignError("controller readback is unavailable")
    try:
        return cast(object, json.loads(raw))
    except json.JSONDecodeError as exc:
        raise CampaignError("controller readback is malformed") from exc


def validate_controller_results(
    results: list[dict[str, object]], config: ControllerConfig
) -> str:
    if len(results) != 7:
        raise CampaignError("controller readback sequence is incomplete")
    group = _json_result(results[0])
    account = _json_result(results[1])
    assignments = _json_result(results[2])
    runbook = _json_result(results[3])
    content = results[4].get("stdout")
    schedules = _json_result(results[5])
    bindings = _json_result(results[6])
    expected_tags = {
        "mobius.milestone": "7.8",
        "mobius.owner": "managed-postgresql-evidence",
        "mobius.cleanup-controller": ARCHITECTURE,
        "mobius.subscription-correlation": config.subscription_correlation,
        "mobius.controller-authorized-until-utc": (
            config.controller_authorized_until_utc
        ),
        "mobius.cleanup-script-sha256": config.cleanup_script_sha256,
    }
    if not isinstance(group, dict) or not isinstance(account, dict):
        raise CampaignError("controller group or account readback is malformed")
    for resource, expected_name in (
        (group, config.controller_resource_group_name),
        (account, config.automation_account_name),
    ):
        tags = resource.get("tags")
        location = resource.get("location")
        if (
            resource.get("name") != expected_name
            or not isinstance(location, str)
            or re.sub(r"[^a-z0-9]", "", location.casefold())
            != config.controller_location
            or not isinstance(tags, dict)
            or any(tags.get(key) != value for key, value in expected_tags.items())
        ):
            raise CampaignError("controller ownership or location readback differs")
    identity = account.get("identity")
    properties = account.get("properties")
    principal_id = identity.get("principalId") if isinstance(identity, dict) else None
    try:
        parsed_principal = uuid.UUID(str(principal_id))
    except ValueError as exc:
        raise CampaignError("controller principal readback is malformed") from exc
    if (
        parsed_principal.int == 0
        or not isinstance(properties, dict)
        or properties.get("disableLocalAuth") is not True
        or not isinstance(runbook, dict)
        or runbook.get("name") != config.runbook_name
        or not isinstance(runbook.get("properties"), dict)
        or runbook["properties"].get("state") != "Published"
        or not isinstance(runbook["properties"].get("lastModifiedTime"), str)
        or not isinstance(content, str)
        or hashlib.sha256(content.encode()).hexdigest() != config.cleanup_script_sha256
    ):
        raise CampaignError("controller identity or publication readback differs")
    controller_scope = (
        f"/subscriptions/{config.subscription_id}/resourceGroups/"
        f"{config.controller_resource_group_name}"
    )
    reader_role = "acdd72a7-3385-48ef-bd42-f606fba81ae7"
    principal_assignments = (
        [
            item
            for item in assignments
            if isinstance(item, dict)
            and str(item.get("principalId", "")).casefold()
            == str(principal_id).casefold()
        ]
        if isinstance(assignments, list)
        else []
    )
    if (
        not isinstance(assignments, list)
        or len(principal_assignments) != 1
        or str(principal_assignments[0].get("scope", "")).casefold()
        != controller_scope.casefold()
        or not str(principal_assignments[0].get("roleDefinitionId", ""))
        .casefold()
        .endswith(reader_role)
    ):
        raise CampaignError("controller permanent Reader authority differs")
    for value, label in ((schedules, "schedule"), (bindings, "binding")):
        if (
            not isinstance(value, dict)
            or set(value) - {"value", "nextLink"}
            or value.get("value") != []
            or value.get("nextLink") not in {None, ""}
        ):
            raise CampaignError(
                f"controller {label} inventory is not empty and complete"
            )
    evidence = {
        "version": "m7.8-controller-baseline-proof-v1",
        "subscriptionCorrelation": config.subscription_correlation,
        "sourceHead": config.source_head,
        "controllerArchitecture": ARCHITECTURE,
        "controllerLocation": config.controller_location,
        "controllerAuthorizedUntilUtc": config.controller_authorized_until_utc,
        "cleanupScriptSha256": config.cleanup_script_sha256,
        "scheduleCount": 0,
        "bindingCount": 0,
    }
    return hashlib.sha256(
        b"m7.8/controller-baseline-proof/v1\0"
        + json.dumps(evidence, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Plan or separately authorize the reusable M7.8 cleanup controller"
    )
    parser.add_argument("operation", choices=sorted(OPERATIONS))
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--authorization", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        config = ControllerConfig.load(args.config)
        commands = controller_command_plan(args.operation, config)
        if not args.execute:
            print(
                json.dumps(
                    {
                        "status": "architecture-corrected-live-execution-not-authorized",
                        "operation": args.operation,
                        "commandCount": len(commands),
                        "azureOperationCount": 0,
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
            return 0
        if args.authorization is None:
            raise CampaignError("controller execution requires separate authorization")
        validate_local_boundary(config)
        authorization_sha256 = load_controller_authorization(
            args.authorization, config=config, operation=args.operation
        )
        runner = SubprocessRunner()
        results = [_run_required(runner, command) for command in commands]
        proof_sha256 = validate_controller_results(results[-7:], config)
        print(
            json.dumps(
                {
                    "status": "controller-baseline-verified",
                    "operation": args.operation,
                    "commandCount": len(results),
                    "authorizationSha256": authorization_sha256,
                    "controllerProofSha256": proof_sha256,
                },
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        return 0
    except CampaignError as exc:
        print(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
