from __future__ import annotations

import copy
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from test_milestone_7_8_campaign_enablement import _config

from infra.milestone_7_8 import workload_image_update as update
from infra.milestone_7_8.campaign import CampaignConfig, CampaignError, sanitize
from infra.milestone_7_8.controller_renewal import _durable_record

NOW = datetime(2030, 1, 1, tzinfo=UTC)
OLD = "sha256:" + "a" * 64
NEW = "sha256:" + "b" * 64
SUBSCRIPTION = "11111111-1111-4111-8111-111111111111"


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


def fixture(tmp_path: Path) -> tuple[dict[str, str], CampaignConfig, dict[str, object]]:
    correlation = sanitize(SUBSCRIPTION, domain="subscription")
    config = _config(subscription_correlation=correlation,
                     cleanup_resource_group=f"rg-m78-controller-{correlation[:10]}")
    runtime = {
        "subscriptionId": SUBSCRIPTION, "resourceGroupName": config.target_resource_group,
        "registryName": "acrm78aabbccddee", "sourceHead": "c" * 40,
        "canonicalBuildInputSha256": "d" * 64,
        "freshControllerAdmissionEvidenceVersion": "fresh-v1",
        "campaignParametersFile": str(tmp_path / "campaign.parameters.json"),
        **{field: f"job-m78-aabbccddee-{suffix}" for field, suffix, _ in update.JOB_FIELDS},
    }
    values: dict[str, object] = {
        "targetResourceGroupName": config.target_resource_group,
        "resourceNameSuffix": "aabbccddee", "registryName": runtime["registryName"],
        "containerAppsEnvironmentName": "cae-m78-aabbccddee",
        "lifecycleTags": update._tags(runtime, config),
        **{key: "id-m78-" + key.removesuffix("IdentityName").lower()
           for _, _, key in update.JOB_FIELDS},
    }
    Path(runtime["campaignParametersFile"]).write_text(json.dumps({
        "parameters": {key: {"value": value} for key, value in values.items()},
    }), encoding="utf-8")
    return runtime, config, update._scope(runtime, config, OLD, NEW)


class Provider:
    def __init__(self, runtime: dict[str, str], config: CampaignConfig,
                 scope: dict[str, object]) -> None:
        self.runtime = runtime
        self.commands: list[tuple[str, ...]] = []
        self.patches = 0
        self.failure: int | None = None
        self.lost = False
        self.drift: str | None = None
        self.pending = 0
        self.states: dict[str, dict[str, object]] = {}
        for target in cast(list[dict[str, str]], scope["targets"]):
            large = target["name"] in {runtime["workerJobName"], runtime["evidenceJobName"]}
            replicas = 4 if target["name"] == runtime["workerJobName"] else 1
            timeout = (7200 if large else 1800
                       if target["name"] == runtime["migrationJobName"] else 900)
            configuration: dict[str, object] = {
                "untouched": True, "triggerType": "Manual", "replicaTimeout": timeout,
                "replicaRetryLimit": 0,
                "manualTriggerConfig": {
                    "parallelism": replicas, "replicaCompletionCount": replicas,
                },
            }
            if target["type"] == "Microsoft.App/containerApps":
                configuration = {
                    "untouched": True, "activeRevisionsMode": "Single",
                    "ingress": {"external": False, "targetPort": 8000, "allowInsecure": False},
                }
            self.states[target["id"]] = {
                "id": target["id"], "name": target["name"], "type": target["type"],
                "location": config.target_region, "tags": update._tags(runtime, config),
                "etag": "before", "systemData": {"lastModifiedAt": NOW.isoformat()},
                "identity": {"type": "UserAssigned", "userAssignedIdentities": {
                    target["identityId"]: {
                        "clientId": "22222222-2222-4222-8222-222222222222",
                        "principalId": "33333333-3333-4333-8333-333333333333",
                    },
                }},
                "properties": {
                    "provisioningState": "Succeeded", "environmentId": scope["environmentId"],
                    "configuration": configuration,
                    "template": {"scale": {"minReplicas": 4, "maxReplicas": 4},
                                 "containers": [{"name": "main", "command": ["python"],
                                                 "env": [{"name": "BOUND", "value": "value"}],
                                                 "resources": {"cpu": 2 if large else 0.5,
                                                               "memory": "4Gi" if large else "1Gi"},
                                                 "image": self.image(OLD)}]},
                },
            }

    def image(self, digest: str) -> str:
        return f"{self.runtime['registryName']}.azurecr.io/mobius-api@{digest}"

    def run(self, command: tuple[str, ...]) -> dict[str, object]:
        self.commands.append(command)
        assert command[:2] == ("az", "rest")
        assert command[command.index("--subscription") + 1] == SUBSCRIPTION
        method = command[command.index("--method") + 1]
        assert method in {"get", "patch"}
        url = command[command.index("--url") + 1]
        assert url.endswith("?api-version=2024-03-01")
        resource_id = url.removeprefix("https://management.azure.com").split("?", 1)[0]
        state = self.states[resource_id]
        if method == "patch":
            assert len(self.commands) >= 11
            self.patches += 1
            body = json.loads(Path(command[-1].removeprefix("@")).read_text())
            assert set(body) == {"properties"}
            assert set(body["properties"]) == {"template"}
            assert set(body["properties"]["template"]) == {"containers"}
            if self.failure == self.patches and not self.lost:
                return {"exitCode": 1, "stdout": "", "stderr": "synthetic failure"}
            properties = update._object(state["properties"])
            update._object(properties["template"])["containers"] = (
                body["properties"]["template"]["containers"]
            )
            state["etag"] = "after"
            update._object(state["systemData"])["lastModifiedAt"] = (
                NOW + timedelta(seconds=1)
            ).isoformat()
            if self.drift == "tags":
                update._object(state["tags"])["unexpected"] = "changed"
            elif self.drift == "settings":
                update._object(properties["configuration"])["untouched"] = False
            elif self.drift == "template":
                update._object(update._containers(state)[0])["command"] = ["other"]
            if self.failure == self.patches:
                raise TimeoutError("synthetic successful response loss")
        result = copy.deepcopy(state)
        if method == "get" and self.patches and self.pending:
            self.pending -= 1
            update._object(result["properties"])["provisioningState"] = "Updating"
        return {"exitCode": 0, "stdout": json.dumps(result), "stderr": ""}


def execute(tmp_path: Path, provider: Provider, runtime: dict[str, str],
            config: CampaignConfig, clock: Clock | None = None) -> dict[str, object]:
    return update.execute_updates(runtime, config, previous_digest=OLD, digest=NEW,
                                  output=tmp_path / "updates", runner=provider,
                                  clock=clock or Clock(), check_authority=lambda: None)


def test_exact_ten_image_updates_and_raw_evidence_replay(tmp_path: Path) -> None:
    runtime, config, scope = fixture(tmp_path)
    provider = Provider(runtime, config, scope)
    receipt = execute(tmp_path, provider, runtime, config)
    assert receipt["resourceCount"] == receipt["patchCount"] == 10
    assert receipt["jobStartCount"] == receipt["baseResourceMutationCount"] == 0
    assert [cmd[3] for cmd in provider.commands] == ["get"] * 10 + ["patch", "get"] * 10
    assert len(provider.commands) == 30
    assert update.validate_completion(runtime, config, previous_digest=OLD, digest=NEW,
                                      output=tmp_path / "updates") == receipt
    with pytest.raises(FileExistsError):
        execute(tmp_path, provider, runtime, config)
    assert len(provider.commands) == 30


@pytest.mark.parametrize("drift", ["id", "image", "tags", "identity", "environment"])
def test_all_baselines_validate_before_any_patch(tmp_path: Path, drift: str) -> None:
    runtime, config, scope = fixture(tmp_path)
    provider = Provider(runtime, config, scope)
    target = list(provider.states.values())[-1]
    if drift == "id":
        target["id"] = "wrong"
    elif drift == "image":
        update._object(update._containers(target)[0])["image"] = provider.image(NEW)
    elif drift == "tags":
        update._object(target["tags"])["mobius.generation"] = "wrong"
    elif drift == "identity":
        target["identity"] = {"type": "SystemAssigned"}
    else:
        update._object(target["properties"])["environmentId"] = "wrong"
    with pytest.raises(CampaignError):
        execute(tmp_path, provider, runtime, config)
    assert provider.patches == 0
    assert not (tmp_path / "updates/completion.json").exists()


@pytest.mark.parametrize("drift", ["tags", "settings", "template"])
def test_preservation_drift_never_produces_completion(tmp_path: Path, drift: str) -> None:
    runtime, config, scope = fixture(tmp_path)
    provider = Provider(runtime, config, scope)
    provider.drift = drift
    with pytest.raises(CampaignError):
        execute(tmp_path, provider, runtime, config)
    assert provider.patches == 1
    assert not (tmp_path / "updates/completion.json").exists()


@pytest.mark.parametrize("boundary", range(1, 11))
@pytest.mark.parametrize("lost", [False, True])
def test_failed_or_lost_patch_never_repeats_or_completes(
    tmp_path: Path, boundary: int, lost: bool,
) -> None:
    runtime, config, scope = fixture(tmp_path)
    provider = Provider(runtime, config, scope)
    provider.failure, provider.lost = boundary, lost
    with pytest.raises(CampaignError):
        execute(tmp_path, provider, runtime, config)
    assert provider.patches == boundary
    assert not (tmp_path / "updates/completion.json").exists()
    assert bool(list((tmp_path / "updates").glob("*-indeterminate.json"))) is lost


def test_authority_checked_after_durable_dispatch_boundary(tmp_path: Path) -> None:
    runtime, config, scope = fixture(tmp_path)
    provider = Provider(runtime, config, scope)

    def authority() -> None:
        if (tmp_path / "updates/011-dispatch.json").exists():
            raise CampaignError("synthetic authority expired")

    with pytest.raises(CampaignError, match="authority expired"):
        update.execute_updates(runtime, config, previous_digest=OLD, digest=NEW,
                               output=tmp_path / "updates", runner=provider,
                               clock=Clock(), check_authority=authority)
    assert provider.patches == 0


def test_polling_is_exact_scoped_and_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, config, scope = fixture(tmp_path)
    provider = Provider(runtime, config, scope)
    provider.pending = 2
    monkeypatch.setattr(
        "infra.milestone_7_8.workload_image_update.time.sleep", lambda _seconds: None,
    )
    receipt = execute(tmp_path, provider, runtime, config)
    assert provider.patches == 10
    assert len(provider.commands) == 32
    assert receipt["jobStartCount"] == 0


def test_persistence_failure_cannot_dispatch_a_patch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, config, scope = fixture(tmp_path)
    provider = Provider(runtime, config, scope)

    def broken(path: Path, value: object) -> None:
        if path.name == "011-dispatch.json":
            raise OSError("synthetic disk failure")
        _durable_record(path, value)

    monkeypatch.setattr(update, "_durable_record", broken)
    with pytest.raises(OSError):
        execute(tmp_path, provider, runtime, config)
    assert provider.patches == 0


@pytest.mark.parametrize("tamper", ["command", "body", "response", "missing", "extra"])
def test_replay_rejects_altered_history_even_with_rehashed_receipt(
    tmp_path: Path, tamper: str,
) -> None:
    runtime, config, scope = fixture(tmp_path)
    provider = Provider(runtime, config, scope)
    execute(tmp_path, provider, runtime, config)
    output = tmp_path / "updates"
    if tamper == "command":
        path = output / "011-intent.json"
        value = json.loads(path.read_text())
        value["command"][3] = "post"
    elif tamper == "body":
        path = output / "target-01-body.json"
        value = json.loads(path.read_text())
        value["tags"] = {}
    elif tamper == "response":
        path = output / "012-response.json"
        value = json.loads(path.read_text())
        raw = json.loads(value["stdout"])
        raw["tags"]["drift"] = "unexpected"
        value["stdout"] = json.dumps(raw)
    elif tamper == "missing":
        (output / "011-dispatch.json").unlink()
        path, value = output / "unrelated.json", {}
    else:
        path, value = output / "unrecorded-mutation.json", {}
    path.write_text(json.dumps(value), encoding="utf-8")
    receipt_path = output / "completion.json"
    receipt = json.loads(receipt_path.read_text())
    receipt["filesSha256"] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in output.iterdir() if p.name != "completion.json"}
    receipt["completionSha256"] = update._hash(
        {key: value for key, value in receipt.items() if key != "completionSha256"}
    )
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(CampaignError):
        update.validate_completion(runtime, config, previous_digest=OLD, digest=NEW, output=output)


def test_expiry_between_updates_stops_without_retry(tmp_path: Path) -> None:
    runtime, config, scope = fixture(tmp_path)
    clock = Clock()

    class SlowProvider(Provider):
        def run(self, command: tuple[str, ...]) -> dict[str, object]:
            response = super().run(command)
            if len(self.commands) == 12:
                clock.now += timedelta(seconds=update.MAXIMUM_SECONDS)
            return response

    provider = SlowProvider(runtime, config, scope)
    with pytest.raises(CampaignError, match="window expired"):
        execute(tmp_path, provider, runtime, config, clock)
    assert provider.patches == 1
    assert not (tmp_path / "updates/completion.json").exists()


def test_complete_readback_records_receive_time_not_dispatch_time(tmp_path: Path) -> None:
    runtime, config, scope = fixture(tmp_path)
    clock = Clock()

    class SlowProvider(Provider):
        def run(self, command: tuple[str, ...]) -> dict[str, object]:
            response = super().run(command)
            clock.now += timedelta(seconds=1)
            return response

    result = execute(tmp_path, SlowProvider(runtime, config, scope), runtime, config, clock)
    assert result["lastObservedAtUtc"] == (NOW + timedelta(seconds=30)).isoformat()


def test_unproved_patch_response_cannot_admit_matching_later_state(tmp_path: Path) -> None:
    runtime, config, scope = fixture(tmp_path)

    class WrongResponse(Provider):
        def run(self, command: tuple[str, ...]) -> dict[str, object]:
            result = super().run(command)
            if command[3] == "patch":
                value = json.loads(cast(str, result["stdout"]))
                value["id"] = "wrong"
                result["stdout"] = json.dumps(value)
            return result

    provider = WrongResponse(runtime, config, scope)
    with pytest.raises(CampaignError, match="PATCH response identity"):
        execute(tmp_path, provider, runtime, config)
    assert provider.patches == 1
    assert not (tmp_path / "updates/completion.json").exists()


def test_incomplete_provider_operation_exhausts_read_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, config, scope = fixture(tmp_path)
    provider = Provider(runtime, config, scope)
    provider.pending = update.MAXIMUM_POLLS + 1
    monkeypatch.setattr(
        "infra.milestone_7_8.workload_image_update.time.sleep", lambda _seconds: None,
    )
    with pytest.raises(CampaignError, match="readback is incomplete"):
        execute(tmp_path, provider, runtime, config)
    assert provider.patches == 1
    assert len(provider.commands) == 11 + update.MAXIMUM_POLLS


def test_optional_metadata_presence_drift_is_not_ignored(tmp_path: Path) -> None:
    runtime, config, scope = fixture(tmp_path)

    class MissingEtag(Provider):
        def run(self, command: tuple[str, ...]) -> dict[str, object]:
            result = super().run(command)
            if command[3] == "get" and self.patches:
                value = json.loads(cast(str, result["stdout"]))
                del value["etag"]
                result["stdout"] = json.dumps(value)
            return result

    provider = MissingEtag(runtime, config, scope)
    with pytest.raises(CampaignError, match="metadata presence or shape"):
        execute(tmp_path, provider, runtime, config)
    assert provider.patches == 1


@pytest.mark.parametrize("target_index", range(10))
@pytest.mark.parametrize("defect", ["cpu", "memory", "initContainers"])
def test_every_baseline_rejects_unpriced_container_allocation_before_writes(
    tmp_path: Path, target_index: int, defect: str,
) -> None:
    runtime, config, scope = fixture(tmp_path)
    provider = Provider(runtime, config, scope)
    resource = list(provider.states.values())[target_index]
    template = update._object(update._object(resource["properties"])["template"])
    if defect == "initContainers":
        template["initContainers"] = [{"name": "extra", "image": provider.image(OLD)}]
    else:
        resources = update._object(update._object(update._containers(resource)[0])["resources"])
        resources[defect] = 4 if defect == "cpu" else "8Gi"
    with pytest.raises(CampaignError, match=r"unpriced|allocation"):
        execute(tmp_path, provider, runtime, config)
    assert provider.patches == 0


@pytest.mark.parametrize("target_index", range(1, 10))
@pytest.mark.parametrize("defect", ["parallelism", "replicaCompletionCount", "timeout", "retry"])
def test_every_job_rejects_unpriced_execution_limits_before_writes(
    tmp_path: Path, target_index: int, defect: str,
) -> None:
    runtime, config, scope = fixture(tmp_path)
    provider = Provider(runtime, config, scope)
    resource = list(provider.states.values())[target_index]
    configuration = update._object(update._object(resource["properties"])["configuration"])
    if defect in {"parallelism", "replicaCompletionCount"}:
        update._object(configuration["manualTriggerConfig"])[defect] = 9
    elif defect == "timeout":
        configuration["replicaTimeout"] = 7201
    else:
        configuration["replicaRetryLimit"] = 1
    with pytest.raises(CampaignError, match="concurrency or timeout"):
        execute(tmp_path, provider, runtime, config)
    assert provider.patches == 0


@pytest.mark.parametrize("defect", ["maxReplicas", "minReplicas", "public", "multiple"])
def test_api_replica_and_network_bounds_are_required(tmp_path: Path, defect: str) -> None:
    runtime, config, scope = fixture(tmp_path)
    provider = Provider(runtime, config, scope)
    resource = next(iter(provider.states.values()))
    properties = update._object(resource["properties"])
    configuration = update._object(properties["configuration"])
    if defect in {"maxReplicas", "minReplicas"}:
        update._object(update._object(properties["template"])["scale"])[defect] = 5
    elif defect == "public":
        update._object(configuration["ingress"])["external"] = True
    else:
        configuration["activeRevisionsMode"] = "Multiple"
    with pytest.raises(CampaignError, match="API replica or private ingress"):
        execute(tmp_path, provider, runtime, config)
    assert provider.patches == 0


@pytest.mark.parametrize("empty", [None, []])
def test_empty_optional_init_container_shapes_are_accepted(tmp_path: Path, empty: object) -> None:
    runtime, config, scope = fixture(tmp_path)
    provider = Provider(runtime, config, scope)
    for resource in provider.states.values():
        update._object(update._object(resource["properties"])["template"])["initContainers"] = empty
    assert execute(tmp_path, provider, runtime, config)["patchCount"] == 10


def test_after_readback_cannot_change_into_unpriced_allocation(tmp_path: Path) -> None:
    runtime, config, scope = fixture(tmp_path)

    class Overallocated(Provider):
        def run(self, command: tuple[str, ...]) -> dict[str, object]:
            response = super().run(command)
            if command[3] == "get" and self.patches:
                resource = json.loads(cast(str, response["stdout"]))
                resource["properties"]["template"]["containers"][0]["resources"]["cpu"] = 4
                response["stdout"] = json.dumps(resource)
            return response

    provider = Overallocated(runtime, config, scope)
    with pytest.raises(CampaignError, match="allocation"):
        execute(tmp_path, provider, runtime, config)
    assert provider.patches == 1
    assert not (tmp_path / "updates/completion.json").exists()
