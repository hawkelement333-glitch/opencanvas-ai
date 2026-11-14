"""One image-only update of the ten existing campaign workloads.

The caller supplies the separately validated continuation authority. This module
never starts a job, creates a resource, changes base infrastructure, or retries a
mutation. An interrupted directory is evidence, not a resumable mutation plan.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import time
import uuid
from collections.abc import Callable
from contextlib import suppress
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

from infra.milestone_7_8.campaign import (
    CampaignConfig,
    CampaignError,
    CommandRunner,
    parse_utc,
    sanitize,
)
from infra.milestone_7_8.controller_admission import digest as domain_hash
from infra.milestone_7_8.controller_renewal import _durable_record

API_VERSION = "2024-03-01"
MAXIMUM_SECONDS = 900
MAXIMUM_POLLS = 90
POLL_SECONDS = 2
JOB_FIELDS = (
    ("workerJobName", "worker", "workerIdentityName"),
    ("bootstrapJobName", "bootstrap", "administratorIdentityName"),
    ("migrationJobName", "migration", "migrationIdentityName"),
    ("evidenceJobName", "evidence", "evidenceIdentityName"),
    ("apiProbeJobName", "probe-api", "apiIdentityName"),
    ("workerProbeJobName", "probe-worker", "workerIdentityName"),
    ("migrationProbeJobName", "probe-migrate", "migrationIdentityName"),
    ("recoveryJobName", "revoke", "administratorIdentityName"),
    ("recoveryRestoreJobName", "restore", "administratorIdentityName"),
)
# These are provider-owned values, not writable template/settings exclusions.
# Presence and types remain exact. Every other field is compared recursively.
METADATA_PATHS = (
    ("etag",),
    ("systemData", "lastModifiedAt"),
    ("properties", "latestRevisionName"),
    ("properties", "latestRevisionFqdn"),
    ("properties", "latestReadyRevisionName"),
    ("properties", "runningStatus"),
)


def _hash(value: object) -> str:
    return domain_hash("m7.8/workload-image-update/v1", value)


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise CampaignError("workload image update object is malformed")
    return cast(dict[str, object], value)


def _load(path: Path) -> dict[str, object]:
    try:
        return _object(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        raise CampaignError("workload image update evidence is unavailable") from exc


def _decoded(result: dict[str, object]) -> dict[str, object]:
    if type(result.get("exitCode")) is not int or result["exitCode"] != 0:
        raise CampaignError("workload image update command failed")
    if not isinstance(result.get("stdout"), str) or not isinstance(result.get("stderr"), str):
        raise CampaignError("workload image update command envelope is malformed")
    try:
        return _object(json.loads(cast(str, result["stdout"])))
    except ValueError as exc:
        raise CampaignError("workload image update response is malformed") from exc


def _tags(runtime: dict[str, str], config: CampaignConfig) -> dict[str, str]:
    return {
        "mobius.milestone": "7.8", "mobius.campaign": config.campaign_id,
        "mobius.generation": config.generation_id,
        "mobius.cleanup-deadline-utc": config.cleanup_deadline_utc,
        "mobius.cost-ceiling-cents": "5000",
        "mobius.cleanup-region-selection-sha256": config.cleanup_region_selection_sha256,
        "mobius.cleanup-candidate-regions": config.cleanup_candidate_regions,
        "mobius.cleanup-offer-classification": config.cleanup_offer_classification,
        "mobius.cleanup-offer-disposition": config.cleanup_offer_eligibility_disposition,
        "mobius.cleanup-offer-regions": config.cleanup_offer_eligible_regions,
        "mobius.cleanup-offer-source": config.cleanup_offer_eligibility_source,
        "mobius.cleanup-offer-eligibility-sha256": config.cleanup_offer_eligibility_sha256,
        "mobius.fresh-controller-admission-sha256": (
            config.fresh_controller_admission_evidence_sha256
        ),
        "mobius.fresh-controller-admission-version": (
            runtime["freshControllerAdmissionEvidenceVersion"]
        ),
        "mobius.owner": "managed-postgresql-evidence",
        "mobius.expiry": config.cleanup_deadline_utc,
    }


def _scope(
    runtime: dict[str, str], config: CampaignConfig, previous_digest: str, digest: str,
) -> dict[str, object]:
    config.validate(allow_expired=True)
    try:
        uuid.UUID(runtime["subscriptionId"])
    except ValueError as exc:
        raise CampaignError("workload image update subscription is malformed") from exc
    if (previous_digest == digest
            or any(re.fullmatch(r"sha256:[a-f0-9]{64}", item) is None
                   for item in (previous_digest, digest))
            or runtime["resourceGroupName"] != config.target_resource_group
            or sanitize(runtime["subscriptionId"], domain="subscription")
            != config.subscription_correlation
            or re.fullmatch(r"[a-z0-9]{5,50}", runtime["registryName"]) is None):
        raise CampaignError("workload image update image or group binding differs")
    suffix_match = re.fullmatch(r"rg-m78-([a-f0-9]{10})-target", config.target_resource_group)
    if suffix_match is None:
        raise CampaignError("workload image update generation scope differs")
    suffix = suffix_match.group(1)
    parameter_path = Path(runtime["campaignParametersFile"]).resolve(strict=True)
    parameters = _object(_load(parameter_path).get("parameters"))
    values = {key: _object(value).get("value") for key, value in parameters.items()}
    if (values.get("targetResourceGroupName") != config.target_resource_group
            or values.get("resourceNameSuffix") != suffix
            or values.get("registryName") != runtime["registryName"]
            or values.get("lifecycleTags") != _tags(runtime, config)):
        raise CampaignError("workload image update prepared parameter binding differs")
    base = (
        f"/subscriptions/{runtime['subscriptionId']}/resourceGroups/{config.target_resource_group}"
    )
    targets: list[dict[str, str]] = []
    for name, kind, identity_parameter in [
        (f"app-m78-{suffix}", "containerApps", "apiIdentityName"),
        *[(runtime[field], "jobs", identity) for field, _ending, identity in JOB_FIELDS],
    ]:
        identity = values.get(identity_parameter)
        if not isinstance(identity, str) or re.fullmatch(r"[a-zA-Z0-9-]+", identity) is None:
            raise CampaignError("workload image update identity binding is malformed")
        targets.append({
            "name": name, "type": f"Microsoft.App/{kind}",
            "id": f"{base}/providers/Microsoft.App/{kind}/{name}",
            "identityId": (
                f"{base}/providers/Microsoft.ManagedIdentity/userAssignedIdentities/{identity}"
            ),
        })
    for target, (_field, ending, _identity) in zip(targets[1:], JOB_FIELDS, strict=True):
        if target["name"] != f"job-m78-{suffix}-{ending}":
            raise CampaignError("workload image update job name escaped the prepared scope")
    environment = values.get("containerAppsEnvironmentName")
    if not isinstance(environment, str) or not re.fullmatch(r"cae-m78-[a-f0-9]{10}", environment):
        raise CampaignError("workload image update environment binding differs")
    return {
        "version": "m7.8-workload-image-update-scope-v1",
        "runtimeSha256": _hash(runtime), "configSha256": _hash(asdict(config)),
        "parametersSha256": hashlib.sha256(parameter_path.read_bytes()).hexdigest(),
        "previousDigest": previous_digest, "digest": digest,
        "cleanupDeadlineUtc": config.cleanup_deadline_utc,
        "targets": targets,
        "environmentId": f"{base}/providers/Microsoft.App/managedEnvironments/{environment}",
    }


def _containers(resource: dict[str, object]) -> list[object]:
    template = _object(_object(resource.get("properties")).get("template"))
    value = template.get("containers")
    if not isinstance(value, list) or len(value) != 1:
        raise CampaignError("workload image update requires the exact single container")
    _object(value[0])
    return cast(list[object], value)


def _validate_resource(
    resource: dict[str, object], target: dict[str, str], scope: dict[str, object],
    runtime: dict[str, str], config: CampaignConfig, digest: str,
) -> None:
    properties = _object(resource.get("properties"))
    tags = _object(resource.get("tags"))
    identity = _object(resource.get("identity"))
    assigned = _object(identity.get("userAssignedIdentities"))
    if (
        str(resource.get("id", "")).casefold() != target["id"].casefold()
        or resource.get("name") != target["name"]
        or str(resource.get("type", "")).casefold() != target["type"].casefold()
        or str(resource.get("location", "")).replace(" ", "").casefold()
        != config.target_region.casefold()
        or resource.get("resourceGroup", config.target_resource_group)
        != config.target_resource_group
        or any(tags.get(key) != value for key, value in _tags(runtime, config).items())
        or identity.get("type") != "UserAssigned"
        or {key.casefold() for key in assigned} != {target["identityId"].casefold()}
        or str(properties.get("environmentId", "")).casefold()
        != str(scope["environmentId"]).casefold()
        or _object(_containers(resource)[0]).get("image")
        != f"{runtime['registryName']}.azurecr.io/mobius-api@{digest}"
    ):
        raise CampaignError("workload image update resource identity, tags or image differs")
    binding = _object(next(iter(assigned.values())))
    try:
        for key in ("clientId", "principalId"):
            uuid.UUID(str(binding.get(key, "")))
    except ValueError as exc:
        raise CampaignError(
            "workload image update managed identity readback is incomplete"
        ) from exc
    _validate_limits(resource, target, runtime)


def _validate_limits(
    resource: dict[str, object], target: dict[str, str], runtime: dict[str, str],
) -> None:
    properties = _object(resource.get("properties"))
    template = _object(properties.get("template"))
    container = _object(_containers(resource)[0])
    resources = _object(container.get("resources"))
    configuration = _object(properties.get("configuration"))
    cpu, memory = resources.get("cpu"), resources.get("memory")
    if template.get("initContainers") not in (None, []):
        raise CampaignError("workload image update includes unpriced init containers")
    large = target["name"] in {runtime["workerJobName"], runtime["evidenceJobName"]}
    if type(cpu) not in (int, float) or cpu != (2 if large else 0.5) or memory != (
        "4Gi" if large else "1Gi"
    ):
        raise CampaignError("workload image update CPU or memory exceeds the reviewed allocation")
    if target["type"].casefold() == "microsoft.app/containerapps":
        scale = _object(template.get("scale"))
        ingress = _object(configuration.get("ingress"))
        if (any(type(scale.get(key)) is not int or scale[key] != 4
                for key in ("minReplicas", "maxReplicas"))
                or configuration.get("activeRevisionsMode") != "Single"
                or ingress.get("external") is not False):
            raise CampaignError(
                "workload image update API replica or private ingress limit differs"
            )
        return
    manual = _object(configuration.get("manualTriggerConfig"))
    workers = 4 if target["name"] == runtime["workerJobName"] else 1
    maximum = 7200 if large else 1800 if target["name"] == runtime["migrationJobName"] else 900
    timeout = configuration.get("replicaTimeout")
    if (
        configuration.get("triggerType") != "Manual"
        or type(configuration.get("replicaRetryLimit")) is not int
        or configuration["replicaRetryLimit"] != 0
        or any(type(manual.get(key)) is not int or manual[key] != workers
               for key in ("parallelism", "replicaCompletionCount"))
        or type(timeout) is not int or not 0 < timeout <= maximum
        or (large and timeout != 7200)
    ):
        raise CampaignError("workload image update job concurrency or timeout limit differs")


def _patch_response(resource: dict[str, object], target: dict[str, str]) -> None:
    if (str(resource.get("id", "")).casefold() != target["id"].casefold()
            or resource.get("name") != target["name"]
            or str(resource.get("type", "")).casefold() != target["type"].casefold()):
        raise CampaignError("workload image update PATCH response identity is unproved")


def _preserved(before: dict[str, object], after: dict[str, object]) -> None:
    expected, actual = copy.deepcopy(before), copy.deepcopy(after)
    _object(_containers(actual)[0])["image"] = _object(_containers(expected)[0])["image"]
    paths = (METADATA_PATHS if str(before.get("type")).casefold()
             == "microsoft.app/containerapps" else METADATA_PATHS[:2])
    for path in paths:
        left, right = expected, actual
        for key in path[:-1]:
            if key not in left and key not in right:
                break
            left, right = _object(left.get(key)), _object(right.get(key))
        else:
            key = path[-1]
            if key not in left and key not in right:
                continue
            if not isinstance(left.get(key), str) or not isinstance(right.get(key), str):
                raise CampaignError("workload image update metadata presence or shape differs")
            right[key] = left[key]
    if expected != actual:
        raise CampaignError("workload image update changed another property or tag")


def _command(runtime: dict[str, str], target: dict[str, str], body: Path | None) -> tuple[str, ...]:
    command = (
        "az", "rest", "--method", "patch" if body is not None else "get", "--url",
        f"https://management.azure.com{target['id']}?api-version={API_VERSION}",
        "--subscription", runtime["subscriptionId"], "--output", "json", "--only-show-errors",
    )
    return command if body is None else (*command, "--body", "@" + str(body.resolve()))


def _body(before: dict[str, object], runtime: dict[str, str], digest: str) -> dict[str, object]:
    containers = copy.deepcopy(_containers(before))
    _object(containers[0])["image"] = f"{runtime['registryName']}.azurecr.io/mobius-api@{digest}"
    return {"properties": {"template": {"containers": containers}}}


def _replay(
    runtime: dict[str, str], config: CampaignConfig, scope: dict[str, object], output: Path,
) -> dict[str, object]:
    attempt = _load(output / "attempt.json")
    if set(attempt) != {"scope", "scopeSha256", "startedAtUtc", "untilUtc"} or (
        attempt["scope"] != scope or attempt["scopeSha256"] != _hash(scope)
    ):
        raise CampaignError("workload image update attempt binding differs")
    started, until = parse_utc(str(attempt["startedAtUtc"])), parse_utc(str(attempt["untilUtc"]))
    if not started < until <= min(started + timedelta(seconds=MAXIMUM_SECONDS),
                                 parse_utc(config.cleanup_deadline_utc)):
        raise CampaignError("workload image update attempt window differs")
    targets = cast(list[dict[str, str]], scope["targets"])
    allowed = {"attempt.json"}
    sequence = 0
    last = started

    def read(target: dict[str, str], phase: str, body: Path | None = None) -> dict[str, object]:
        nonlocal sequence, last
        sequence += 1
        stem = f"{sequence:03}"
        names = [f"{stem}-{suffix}.json"
                 for suffix in ("intent", "dispatch", "response", "completed")]
        allowed.update(names)
        intent, dispatch, result, completed = [_load(output / name) for name in names]
        if set(intent) != {"scopeSha256", "sequence", "phase", "command", "recordedAtUtc"} or (
            intent["scopeSha256"] != _hash(scope) or intent["sequence"] != sequence
            or intent["phase"] != phase
            or intent["command"] != list(_command(runtime, target, body))
            or set(dispatch) != {"intentSha256", "dispatchedAtUtc"}
            or dispatch["intentSha256"] != _hash(intent)
            or set(completed) != {"responseSha256", "completedAtUtc"}
            or completed["responseSha256"] != _hash(result)
        ):
            raise CampaignError("workload image update exact request history differs")
        recorded = parse_utc(str(intent["recordedAtUtc"]))
        sent = parse_utc(str(dispatch["dispatchedAtUtc"]))
        received = parse_utc(str(completed["completedAtUtc"]))
        if not last <= recorded <= sent <= received < until:
            raise CampaignError("workload image update dispatch time is invalid")
        last = received
        resource = _decoded(result)
        if body is not None:
            _patch_response(resource, target)
        return resource

    before = [read(target, "before") for target in targets]
    for target, value in zip(targets, before, strict=True):
        _validate_resource(value, target, scope, runtime, config, str(scope["previousDigest"]))
        if _object(value["properties"]).get("provisioningState") != "Succeeded":
            raise CampaignError("workload image update baseline is not stable")
    after: list[dict[str, object]] = []
    for index, (target, old) in enumerate(zip(targets, before, strict=True), 1):
        body_path = output / f"target-{index:02}-body.json"
        allowed.add(body_path.name)
        if _load(body_path) != _body(old, runtime, str(scope["digest"])):
            raise CampaignError("workload image update PATCH body differs")
        read(target, "patch", body_path)
        for _ in range(MAXIMUM_POLLS):
            observed = read(target, "after")
            state = _object(observed.get("properties")).get("provisioningState")
            if state == "Succeeded":
                _validate_resource(observed, target, scope, runtime, config, str(scope["digest"]))
                _preserved(old, observed)
                after.append(observed)
                break
            if state not in {"Updating", "InProgress", "Accepted"}:
                raise CampaignError("workload image update provider operation did not succeed")
        else:
            raise CampaignError("workload image update readback is incomplete")
    present = {path.name for path in output.iterdir()}
    if present - {"completion.json"} != allowed:
        raise CampaignError("workload image update history is incomplete or contradictory")
    result: dict[str, object] = {
        "version": "m7.8-workload-image-update-completion-v1",
        "scopeSha256": _hash(scope), "previousDigest": scope["previousDigest"],
        "digest": scope["digest"], "resourceCount": 10, "patchCount": 10,
        "jobStartCount": 0, "baseResourceMutationCount": 0,
        "beforeSha256": _hash(before), "afterSha256": _hash(after),
        "lastObservedAtUtc": last.isoformat(),
        "filesSha256": {name: hashlib.sha256((output / name).read_bytes()).hexdigest()
                        for name in sorted(allowed)},
    }
    return {**result, "completionSha256": _hash(result)}


def validate_completion(
    runtime: dict[str, str], config: CampaignConfig, *, previous_digest: str,
    digest: str, output: Path,
) -> dict[str, object]:
    """Replay exact requests and raw before/after state; file hashes alone never admit."""
    expected = _replay(runtime, config, _scope(runtime, config, previous_digest, digest), output)
    if _load(output / "completion.json") != expected:
        raise CampaignError("workload image update completion differs")
    return expected


def execute_updates(
    runtime: dict[str, str], config: CampaignConfig, *, previous_digest: str, digest: str,
    output: Path, runner: CommandRunner, clock: Callable[[], datetime],
    check_authority: Callable[[], None],
) -> dict[str, object]:
    scope = _scope(runtime, config, previous_digest, digest)
    started = clock().astimezone(UTC)
    until = min(
        started + timedelta(seconds=MAXIMUM_SECONDS), parse_utc(config.cleanup_deadline_utc)
    )
    if started >= until:
        raise CampaignError("workload image update window expired")
    check_authority()
    output.mkdir(mode=0o700, exist_ok=False)
    _durable_record(output / "attempt.json", {
        "scope": scope, "scopeSha256": _hash(scope),
        "startedAtUtc": started.isoformat(), "untilUtc": until.isoformat(),
    })
    sequence = 0

    def run(target: dict[str, str], phase: str, body: Path | None = None) -> dict[str, object]:
        nonlocal sequence
        if clock() >= until:
            raise CampaignError("workload image update window expired")
        sequence += 1
        command = _command(runtime, target, body)
        intent = {
            "scopeSha256": _hash(scope), "sequence": sequence, "phase": phase,
            "command": list(command), "recordedAtUtc": clock().isoformat(),
        }
        _durable_record(output / f"{sequence:03}-intent.json", intent)
        _durable_record(output / f"{sequence:03}-dispatch.json", {
            "intentSha256": _hash(intent), "dispatchedAtUtc": clock().isoformat(),
        })
        check_authority()
        if clock() >= until:
            raise CampaignError("workload image update window expired before dispatch")
        try:
            response = runner.run(command)
            _durable_record(output / f"{sequence:03}-response.json", response)
            _durable_record(output / f"{sequence:03}-completed.json", {
                "responseSha256": _hash(response), "completedAtUtc": clock().isoformat(),
            })
        except Exception as exc:
            with suppress(OSError):
                _durable_record(output / f"{sequence:03}-indeterminate.json", {
                    "intentSha256": _hash(intent), "exceptionClass": type(exc).__name__,
                    "status": "outcome-indeterminate-no-retry",
                })
            raise CampaignError("workload image update outcome is indeterminate; no retry") from exc
        resource = _decoded(response)
        if body is not None:
            _patch_response(resource, target)
        return resource

    targets = cast(list[dict[str, str]], scope["targets"])
    before = [run(target, "before") for target in targets]
    for target, resource in zip(targets, before, strict=True):
        _validate_resource(resource, target, scope, runtime, config, previous_digest)
        if _object(resource["properties"]).get("provisioningState") != "Succeeded":
            raise CampaignError("workload image update baseline is not stable")
    for index, (target, resource) in enumerate(zip(targets, before, strict=True), 1):
        body = output / f"target-{index:02}-body.json"
        _durable_record(body, _body(resource, runtime, digest))
        run(target, "patch", body)
        for _ in range(MAXIMUM_POLLS):
            observed = run(target, "after")
            state = _object(observed.get("properties")).get("provisioningState")
            if state == "Succeeded":
                _validate_resource(observed, target, scope, runtime, config, digest)
                _preserved(resource, observed)
                break
            if state not in {"Updating", "InProgress", "Accepted"}:
                raise CampaignError("workload image update provider operation did not succeed")
            time.sleep(POLL_SECONDS)
        else:
            raise CampaignError("workload image update readback is incomplete")
    if clock() >= until:
        raise CampaignError("workload image update window expired before completion")
    completion = _replay(runtime, config, scope, output)
    _durable_record(output / "completion.json", completion)
    return validate_completion(runtime, config, previous_digest=previous_digest,
                               digest=digest, output=output)
