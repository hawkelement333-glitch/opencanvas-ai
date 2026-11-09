from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

from infra.milestone_7_8.campaign import (
    CAMPAIGN_PATTERN,
    CampaignError,
    GENERATION_PATTERN,
    SubprocessRunner,
    parse_utc,
    sanitize,
)
from infra.milestone_7_8.cleanup_controller import (
    ARCHITECTURE,
    CONTROLLER_RUNBOOK_NAME,
    controller_names,
)
from infra.milestone_7_8.predeployment import (
    EVIDENCE_VERSION as FRESH_CONTROLLER_ADMISSION_EVIDENCE_VERSION,
    PredeploymentVerificationError,
    load_validated_admission,
)

OPERATIONS = frozenset({"controller-bootstrap", "controller-verify"})
CONFIG_OPERATION = "controller-config"
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True, slots=True)
class ControllerConfig:
    subscription_id: str
    tenant_id: str
    campaign_id: str
    generation_id: str
    subscription_correlation: str
    source_head: str
    controller_location: str
    controller_resource_group_name: str
    automation_account_name: str
    runbook_name: str
    controller_authorized_until_utc: str
    cleanup_script_sha256: str
    fresh_controller_admission_evidence_sha256: str
    fresh_controller_admission_evidence_version: str
    deployment_name: str

    @classmethod
    def load(cls, path: Path) -> ControllerConfig:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CampaignError("controller configuration is unreadable") from exc
        fields = {
            "subscriptionId",
            "tenantId",
            "campaignId",
            "generationId",
            "subscriptionCorrelation",
            "sourceHead",
            "controllerLocation",
            "controllerResourceGroupName",
            "automationAccountName",
            "runbookName",
            "controllerAuthorizedUntilUtc",
            "cleanupScriptSha256",
            "freshControllerAdmissionEvidenceSha256",
            "freshControllerAdmissionEvidenceVersion",
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
            tenant_id=cast(str, value["tenantId"]),
            campaign_id=cast(str, value["campaignId"]),
            generation_id=cast(str, value["generationId"]),
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
            fresh_controller_admission_evidence_sha256=cast(
                str, value["freshControllerAdmissionEvidenceSha256"]
            ),
            fresh_controller_admission_evidence_version=cast(
                str, value["freshControllerAdmissionEvidenceVersion"]
            ),
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
            or re.fullmatch(
                r"[a-f0-9]{64}", self.fresh_controller_admission_evidence_sha256
            )
            is None
            or self.fresh_controller_admission_evidence_version
            != FRESH_CONTROLLER_ADMISSION_EVIDENCE_VERSION
            or self.deployment_name
            != f"m78-controller-{self.subscription_correlation[:10]}"
        ):
            raise CampaignError("controller configuration binding is malformed")
        try:
            tenant = uuid.UUID(self.tenant_id)
        except ValueError as exc:
            raise CampaignError("controller tenant is malformed") from exc
        if (
            tenant.int == 0
            or CAMPAIGN_PATTERN.fullmatch(self.campaign_id) is None
            or GENERATION_PATTERN.fullmatch(self.generation_id) is None
        ):
            raise CampaignError("controller fresh admission binding is malformed")
        parse_utc(self.controller_authorized_until_utc)


def controller_config_document(config: ControllerConfig) -> dict[str, str]:
    """Return the closed private configuration payload for one controller."""

    config.validate()
    return {
        "subscriptionId": config.subscription_id,
        "tenantId": config.tenant_id,
        "campaignId": config.campaign_id,
        "generationId": config.generation_id,
        "subscriptionCorrelation": config.subscription_correlation,
        "sourceHead": config.source_head,
        "controllerLocation": config.controller_location,
        "controllerResourceGroupName": config.controller_resource_group_name,
        "automationAccountName": config.automation_account_name,
        "runbookName": config.runbook_name,
        "controllerAuthorizedUntilUtc": config.controller_authorized_until_utc,
        "cleanupScriptSha256": config.cleanup_script_sha256,
        "freshControllerAdmissionEvidenceSha256": (
            config.fresh_controller_admission_evidence_sha256
        ),
        "freshControllerAdmissionEvidenceVersion": (
            config.fresh_controller_admission_evidence_version
        ),
        "deploymentName": config.deployment_name,
    }


def controller_config_sha256(config: ControllerConfig) -> str:
    return hashlib.sha256(
        b"m7.8/controller-config/v1\0"
        + json.dumps(
            controller_config_document(config), sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def build_controller_config(
    *,
    subscription_id: str,
    tenant_id: str,
    campaign_id: str,
    generation_id: str,
    controller_location: str,
    source_head: str,
    cleanup_script_sha256: str,
    controller_authorized_until_utc: str,
    fresh_subscription_runtime: Path,
    fresh_subscription_authorization: Path,
    fresh_subscription_evidence: Path,
    require_current_admission: bool = False,
) -> ControllerConfig:
    """Build the pre-bootstrap controller config from exact fresh evidence.

    This is deliberately a local writer step.  It creates no campaign bundle,
    no authorization, and no Azure operation; the later bootstrap remains
    separately authorized and must revalidate this exact config.
    """

    correlation = sanitize(subscription_id, domain="subscription")
    names = controller_names(correlation)
    try:
        admission = load_validated_admission(
            runtime_path=fresh_subscription_runtime,
            authorization_path=fresh_subscription_authorization,
            evidence_path=fresh_subscription_evidence,
            subscription_id=subscription_id,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            generation_id=generation_id,
            region=controller_location,
            controller_resource_group_name=names.resource_group,
            automation_account_name=names.account,
            require_current=require_current_admission,
        )
    except PredeploymentVerificationError as exc:
        raise CampaignError(str(exc)) from exc
    config = ControllerConfig(
        subscription_id=subscription_id,
        tenant_id=tenant_id,
        campaign_id=campaign_id,
        generation_id=generation_id,
        subscription_correlation=correlation,
        source_head=source_head,
        controller_location=controller_location,
        controller_resource_group_name=names.resource_group,
        automation_account_name=names.account,
        runbook_name=CONTROLLER_RUNBOOK_NAME,
        controller_authorized_until_utc=controller_authorized_until_utc,
        cleanup_script_sha256=cleanup_script_sha256,
        fresh_controller_admission_evidence_sha256=admission.evidence_sha256,
        fresh_controller_admission_evidence_version=FRESH_CONTROLLER_ADMISSION_EVIDENCE_VERSION,
        deployment_name=f"m78-controller-{correlation[:10]}",
    )
    config.validate()
    return config


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
        "freshControllerAdmissionEvidenceSha256",
        "freshControllerAdmissionEvidenceVersion",
        "expiresAtUtc",
        "authorizationSha256",
    }
    unsigned = (
        {key: item for key, item in value.items() if key != "authorizationSha256"}
        if isinstance(value, dict)
        else {}
    )
    expected_hash = hashlib.sha256(
        b"m7.8/controller-execution-authorization/v4\0"
        + json.dumps(unsigned, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    if (
        not isinstance(value, dict)
        or set(value) != fields
        or operation not in OPERATIONS
        or value.get("version") != "m7.8-controller-execution-authorization-v4"
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
        or value.get("freshControllerAdmissionEvidenceSha256")
        != config.fresh_controller_admission_evidence_sha256
        or value.get("freshControllerAdmissionEvidenceVersion")
        != config.fresh_controller_admission_evidence_version
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


def local_source_binding() -> tuple[str, str]:
    """Return the clean source head and cleanup-script digest for a live plan."""

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

    source_head = git("rev-parse", "HEAD")
    script_sha256 = hashlib.sha256(
        (
            REPOSITORY_ROOT / "infra/milestone_7_8/scripts/Remove-M78Campaign.ps1"
        ).read_bytes()
    ).hexdigest()
    if (
        git("status", "--porcelain=v1")
        or git("branch", "--show-current")
        != "milestone-7-8-production-readiness-audit-local"
        or git(
            "for-each-ref",
            "--format=%(upstream)",
            "refs/heads/milestone-7-8-production-readiness-audit-local",
        )
        != "refs/remotes/origin/milestone-7-8-production-readiness-audit-local"
        or len(git("stash", "list", "--format=%H").splitlines()) != 5
    ):
        raise CampaignError("controller local source boundary differs")
    return source_head, script_sha256


def validate_local_boundary(config: ControllerConfig) -> None:
    source_head, script_sha256 = local_source_binding()
    if (
        source_head != config.source_head
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
            "freshControllerAdmissionEvidenceSha256="
            f"{config.fresh_controller_admission_evidence_sha256}",
            "freshControllerAdmissionEvidenceVersion="
            f"{config.fresh_controller_admission_evidence_version}",
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
        "mobius.fresh-controller-admission-sha256": (
            config.fresh_controller_admission_evidence_sha256
        ),
        "mobius.fresh-controller-admission-version": (
            config.fresh_controller_admission_evidence_version
        ),
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
        "freshControllerAdmissionEvidenceSha256": (
            config.fresh_controller_admission_evidence_sha256
        ),
        "freshControllerAdmissionEvidenceVersion": (
            config.fresh_controller_admission_evidence_version
        ),
        "scheduleCount": 0,
        "bindingCount": 0,
    }
    return hashlib.sha256(
        b"m7.8/controller-baseline-proof/v1\0"
        + json.dumps(evidence, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def write_controller_config(
    output: Path,
    *,
    campaign_id: str,
    generation_id: str,
    controller_region: str,
    fresh_subscription_runtime: Path,
    fresh_subscription_authorization: Path,
    fresh_subscription_evidence: Path,
    now: datetime | None = None,
) -> ControllerConfig:
    """Write exactly one private bootstrap config from the fresh admission proof."""

    if output.exists():
        raise CampaignError("refusing to replace existing controller configuration")
    subscription_id = os.environ.get("M78_SUBSCRIPTION_ID", "")
    tenant_id = os.environ.get("M78_TENANT_ID", "")
    try:
        if uuid.UUID(subscription_id).int == 0 or uuid.UUID(tenant_id).int == 0:
            raise ValueError
    except ValueError as exc:
        raise CampaignError("controller subscription or tenant binding is missing") from exc
    source_head, cleanup_script_sha256 = local_source_binding()
    issued_at = (now or datetime.now(UTC)).astimezone(UTC)
    config = build_controller_config(
        subscription_id=subscription_id,
        tenant_id=tenant_id,
        campaign_id=campaign_id,
        generation_id=generation_id,
        controller_location=controller_region,
        source_head=source_head,
        cleanup_script_sha256=cleanup_script_sha256,
        controller_authorized_until_utc=(
            (issued_at + timedelta(hours=1))
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z")
        ),
        fresh_subscription_runtime=fresh_subscription_runtime,
        fresh_subscription_authorization=fresh_subscription_authorization,
        fresh_subscription_evidence=fresh_subscription_evidence,
        require_current_admission=True,
    )
    output.write_text(
        json.dumps(controller_config_document(config), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return config


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Plan or separately authorize the reusable M7.8 cleanup controller"
    )
    parser.add_argument("operation", choices=sorted({*OPERATIONS, CONFIG_OPERATION}))
    parser.add_argument("--config", type=Path)
    parser.add_argument("--authorization", type=Path)
    parser.add_argument("--fresh-subscription-runtime", type=Path)
    parser.add_argument("--fresh-subscription-authorization", type=Path)
    parser.add_argument("--fresh-subscription-evidence", type=Path)
    parser.add_argument("--campaign-id")
    parser.add_argument("--generation-id")
    parser.add_argument("--controller-region")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        if args.operation == CONFIG_OPERATION:
            if args.execute or args.authorization is not None:
                raise CampaignError("controller config creation cannot execute Azure work")
            if (
                args.output is None
                or args.campaign_id is None
                or args.generation_id is None
                or args.controller_region is None
                or args.fresh_subscription_runtime is None
                or args.fresh_subscription_authorization is None
                or args.fresh_subscription_evidence is None
            ):
                raise CampaignError("controller config creation inputs are incomplete")
            config = write_controller_config(
                args.output,
                campaign_id=args.campaign_id,
                generation_id=args.generation_id,
                controller_region=args.controller_region,
                fresh_subscription_runtime=args.fresh_subscription_runtime,
                fresh_subscription_authorization=args.fresh_subscription_authorization,
                fresh_subscription_evidence=args.fresh_subscription_evidence,
            )
            print(
                json.dumps(
                    {
                        "status": "controller-config-written-local-only",
                        "controllerConfigSha256": controller_config_sha256(config),
                        "controllerAuthorizedUntilUtc": config.controller_authorized_until_utc,
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
            return 0
        if args.config is None:
            raise CampaignError("controller operation requires a configuration")
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
        if (
            args.fresh_subscription_runtime is None
            or args.fresh_subscription_authorization is None
            or args.fresh_subscription_evidence is None
        ):
            raise CampaignError(
                "controller execution requires fresh controller admission evidence"
            )
        try:
            admission = load_validated_admission(
                runtime_path=args.fresh_subscription_runtime,
                authorization_path=args.fresh_subscription_authorization,
                evidence_path=args.fresh_subscription_evidence,
                subscription_id=config.subscription_id,
                tenant_id=config.tenant_id,
                campaign_id=config.campaign_id,
                generation_id=config.generation_id,
                region=config.controller_location,
                controller_resource_group_name=config.controller_resource_group_name,
                automation_account_name=config.automation_account_name,
                require_current=args.operation == "controller-bootstrap",
            )
        except PredeploymentVerificationError as exc:
            raise CampaignError(str(exc)) from exc
        if admission.evidence_sha256 != config.fresh_controller_admission_evidence_sha256:
            raise CampaignError("controller fresh admission binding differs")
        if admission.document.get("version") != config.fresh_controller_admission_evidence_version:
            raise CampaignError("controller fresh admission version differs")
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
