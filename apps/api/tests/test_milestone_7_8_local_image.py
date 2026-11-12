from __future__ import annotations

import copy
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tarfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path
from typing import cast

import pytest
from test_milestone_7_8_campaign_enablement import _config, _runtime

from infra.milestone_7_8 import canonical_inputs, local_image, operator, scout_admission
from infra.milestone_7_8.campaign import (
    ORDER,
    CampaignConfig,
    CampaignError,
    Ledger,
    Phase,
    SubprocessRunner,
)
from infra.milestone_7_8.canonical_inputs import BUILD_INPUTS, DOMAIN
from infra.milestone_7_8.controller_renewal import _durable_record

NOW = datetime(2030, 1, 1, tzinfo=UTC)
DIGEST = "sha256:" + "d" * 64


@dataclass
class Case:
    runtime: dict[str, str]
    config: CampaignConfig
    ledger: Ledger
    plan: dict[str, object]
    approval: dict[str, object]
    runtime_path: Path


@pytest.fixture
def case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Case:
    runtime, config = _runtime(), _config()
    directories = {"apps/api/opencanvas_api", "apps/api/scripts", "apps/api/alembic"}
    blob = hashlib.sha1(b"blob 4\0test", usedforsecurity=False).hexdigest()
    payload = {
        "inputs": list(BUILD_INPUTS),
        "treeEntries": [
            {
                "mode": "100644",
                "object": blob,
                "path": name + "/test.txt" if name in directories else name,
            }
            for name in BUILD_INPUTS
        ],
    }
    runtime["canonicalBuildInputSha256"] = hashlib.sha256(
        DOMAIN + json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    folder = tmp_path / ".runtime" / "milestone_7_8" / "campaign"
    folder.mkdir(parents=True)
    runtime_path = folder / "runtime.json"
    runtime_path.write_text(json.dumps(runtime), encoding="utf-8")
    before = {
        "id": f"/subscriptions/{runtime['subscriptionId']}/resourceGroups/"
        f"{config.target_resource_group}/providers/Microsoft.ContainerRegistry/"
        f"registries/{runtime['registryName']}",
        "name": runtime["registryName"],
        "type": "Microsoft.ContainerRegistry/registries",
        "location": "canadacentral",
        "sku": {"name": "Premium"},
        "tags": {"campaign": config.campaign_id},
        "properties": {
            "publicNetworkAccess": "Disabled",
            "adminUserEnabled": False,
            "anonymousPullEnabled": False,
            "provisioningState": "Succeeded",
            "networkRuleBypassOptions": "AzureServices",
            "networkRuleSet": {"defaultAction": "Allow", "ipRules": []},
            "privateEndpointConnections": [{"id": "synthetic-private-endpoint"}],
        },
    }
    plan = local_image.build_plan(runtime, config, before, egress_ipv4="8.8.4.4")
    approval = local_image.build_approval(
        plan,
        issued_at="2030-01-01T00:00:00Z",
        expires_at="2030-01-01T01:00:00Z",
        restore_until="2030-01-01T05:00:00Z",
    )
    ledger = Ledger(
        config.campaign_id,
        config.generation_id,
        conservative_estimate_usd=config.conservative_estimate_usd,
    )
    ledger.bind_cleanup_region(config)
    chain = ORDER[: ORDER.index(Phase.INFRASTRUCTURE_DEPLOYED) + 1]
    ledger.transitions = [
        {"from": before.value, "to": after.value, "atUtc": "2030-01-01T00:00:00Z"}
        for before, after in pairwise(chain)
    ]
    ledger.phase = Phase.INFRASTRUCTURE_DEPLOYED.value
    ledger.resource_generation_count = 1
    ledger.cleanup_arm_evidence_sha256 = "e" * 64
    monkeypatch.setattr(local_image, "ROOT", tmp_path)
    monkeypatch.setattr(scout_admission, "ROOT", tmp_path)
    monkeypatch.setattr(
        local_image, "local_source_binding", lambda: (runtime["sourceHead"], "f" * 64)
    )
    for module in (local_image, scout_admission):
        monkeypatch.setattr(
            module,
            "canonical_snapshot",
            lambda _head: {"buildInputSha256": runtime["canonicalBuildInputSha256"]},
        )
    return Case(runtime, config, ledger, plan, approval, runtime_path)


class Provider:
    def __init__(self, case: Case, *, fault: str = "") -> None:
        self.case = case
        self.registry = copy.deepcopy(cast(dict[str, object], case.plan["before"]))
        self.commands: list[tuple[str, ...]] = []
        self.fault = fault
        self.patch_count = 0

    def run(self, command: tuple[str, ...]) -> dict[str, object]:
        self.commands.append(command)
        result: object = {}
        raw: str | None = None
        if command[:2] == ("az", "rest"):
            assert (
                command[command.index("--subscription") + 1] == self.case.runtime["subscriptionId"]
            )
            assert command[command.index("--url") + 1] == self.case.plan["registryUrl"]
            if command[command.index("--method") + 1] == "patch":
                self.patch_count += 1
                body = json.loads(Path(command[command.index("--body") + 1][1:]).read_text())
                assert set(body) == {"properties"}
                assert set(body["properties"]) == {"publicNetworkAccess", "networkRuleSet"}
                if self.fault == "restore-failure" and self.patch_count == 2:
                    return {"exitCode": 1, "stdout": "", "stderr": "synthetic failure"}
                cast(dict[str, object], self.registry["properties"]).update(body["properties"])
                if self.fault == "not-succeeded":
                    cast(dict[str, object], self.registry["properties"])["provisioningState"] = (
                        "Updating" if self.patch_count == 1 else "Succeeded"
                    )
                if (self.fault, self.patch_count) in {("open-lost", 1), ("restore-lost", 2)}:
                    raise OSError("synthetic response loss")
            result = copy.deepcopy(self.registry)
        elif command[:2] == ("docker", "info"):
            result = {"OSType": "linux", "Architecture": "x86_64"}
        elif command[:2] == ("docker", "build"):
            assert Path(command[-1]) == self.case.runtime_path.parent / "local-image" / "source"
            assert Path(command[command.index("--file") + 1]).relative_to(
                command[-1]
            ).as_posix() == ("apps/api/Dockerfile")
            assert command[command.index("--platform") + 1] == "linux/amd64"
            if self.fault == "build-failure":
                return {"exitCode": 1, "stdout": "", "stderr": "synthetic build failure"}
        elif command[:3] == ("docker", "image", "inspect"):
            result = [
                {
                    "Id": None if self.fault == "missing-id" else "sha256:" + "c" * 64,
                    "RepoDigests": [
                        f"{self.case.runtime['registryName']}.azurecr.io/mobius-api@{DIGEST}"
                    ],
                    "Os": "linux",
                    "Architecture": "amd64",
                    "Size": local_image.MAX_IMAGE_BYTES + 1 if self.fault == "oversize" else 100,
                    "Config": {
                        "Labels": {
                            "org.opencontainers.image.revision": self.case.runtime["sourceHead"],
                            "mobius.canonical-input-sha256": self.case.runtime[
                                "canonicalBuildInputSha256"
                            ],
                        }
                    },
                }
            ]
        elif command[:2] == ("docker", "push"):
            raw = "m78-test: digest: " + DIGEST + " size: 1234"
        elif command[:4] == ("az", "acr", "manifest", "show-metadata"):
            assert command[command.index("--name") + 1] == "mobius-api@" + DIGEST
            result = {"digest": "sha256:" + "0" * 64 if self.fault == "digest" else DIGEST}
        elif command[:3] == ("az", "acr", "login"):
            raw = "Login Succeeded"
        elif command[:3] == ("git", "rev-parse", "HEAD"):
            raw = self.case.runtime["sourceHead"]
        elif command[:2] == ("git", "status"):
            raw = ""
        elif command[0] == "git" and "archive" in command:
            assert command[command.index("--output") + 2] == self.case.runtime["sourceHead"]
            with tarfile.open(command[command.index("--output") + 1], "w") as archive:
                directories = {"apps/api/opencanvas_api", "apps/api/scripts", "apps/api/alembic"}
                for name in BUILD_INPUTS:
                    member = tarfile.TarInfo(name + "/test.txt" if name in directories else name)
                    member.size = 4
                    archive.addfile(member, io.BytesIO(b"test"))
        elif command[0] == "git" and command[3] == "ls-tree":
            directories = {"apps/api/opencanvas_api", "apps/api/scripts", "apps/api/alembic"}
            blob = hashlib.sha1(b"blob 4\0test", usedforsecurity=False).hexdigest()
            raw = "\n".join(
                f"100644 blob {blob}\t{name + '/test.txt' if name in directories else name}"
                for name in BUILD_INPUTS
            )
        elif command[:3] == ("docker", "scout", "version"):
            raw = "version: v1.23.1"
        elif command[:3] == ("docker", "scout", "cves"):
            assert command[3].endswith("mobius-api@" + DIGEST)
            if self.fault == "scan-failure":
                return {"exitCode": 2, "stdout": "", "stderr": "synthetic critical finding"}
            Path(command[command.index("--output") + 1]).write_text(
                json.dumps({"version": "2.1.0", "runs": [{"results": []}]}),
                encoding="utf-8",
            )
            if self.fault == "preservation-drift":
                self.registry["tags"] = {"campaign": "changed"}
        else:
            raise AssertionError(command)
        return {
            "exitCode": 0,
            "stdout": raw if raw is not None else json.dumps(result),
            "stderr": "",
        }


class RuleReadbackProvider(Provider):
    def __init__(self, case: Case, rules: object, *, after_patch: int = 1) -> None:
        super().__init__(case)
        self.rules = rules
        self.after_patch = after_patch

    def run(self, command: tuple[str, ...]) -> dict[str, object]:
        response = super().run(command)
        if (
            command[:4] == ("az", "rest", "--method", "get")
            and self.patch_count == self.after_patch
        ):
            observed = json.loads(cast(str, response["stdout"]))
            observed["properties"]["networkRuleSet"]["ipRules"] = copy.deepcopy(self.rules)
            response = {**response, "stdout": json.dumps(observed)}
        return response


def execute(case: Case, provider: Provider) -> dict[str, object]:
    return local_image.execute_local_image(
        case.runtime_path,
        case.runtime,
        case.config,
        case.ledger,
        case.plan,
        case.approval,
        output=case.runtime_path.parent / "local-image",
        runner=provider,
        clock=lambda: NOW,
    )


def test_local_image_has_executable_entry_point() -> None:
    assert callable(local_image.main)


def test_staging_preflight_uses_full_private_output_and_leaves_no_attempt(case: Case) -> None:
    provider = Provider(case)
    local_image.preflight_image_staging(
        case.runtime_path.parent,
        source_head=case.runtime["sourceHead"],
        canonical_input_sha256=case.runtime["canonicalBuildInputSha256"],
        runner=provider,
    )
    assert not (case.runtime_path.parent / "local-image").exists()
    assert not (case.runtime_path.parent / "local-image-attempt.json").exists()
    assert case.runtime_path.exists()
    assert all(command[0] == "git" for command in provider.commands)


@pytest.mark.parametrize("existing", ["local-image", "local-image-attempt.json"])
def test_staging_preflight_preserves_existing_private_work(case: Case, existing: str) -> None:
    target = case.runtime_path.parent / existing
    if existing == "local-image":
        target.mkdir()
        protected = target / "retained.json"
    else:
        protected = target
    protected.write_text("retained evidence", encoding="utf-8")
    provider = Provider(case)
    with pytest.raises(CampaignError, match="already exists"):
        local_image.preflight_image_staging(
            case.runtime_path.parent,
            source_head=case.runtime["sourceHead"],
            canonical_input_sha256=case.runtime["canonicalBuildInputSha256"],
            runner=provider,
        )
    assert protected.read_text() == "retained evidence"
    assert provider.commands == []


def test_staging_preflight_cleanup_failure_is_blocking(
    case: Case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failed_remove(path: Path) -> None:
        assert path == case.runtime_path.parent / "local-image"
        raise OSError("synthetic removal failure")

    monkeypatch.setattr(shutil, "rmtree", failed_remove)
    with pytest.raises(CampaignError, match="cleanup failed"):
        local_image.preflight_image_staging(
            case.runtime_path.parent,
            source_head=case.runtime["sourceHead"],
            canonical_input_sha256=case.runtime["canonicalBuildInputSha256"],
            runner=Provider(case),
        )
    assert (case.runtime_path.parent / "local-image" / "source.tar").exists()
    assert case.runtime_path.exists()
    assert not (case.runtime_path.parent / "local-image-attempt.json").exists()


def test_staging_preflight_rejects_actual_canonical_tree_mismatch(case: Case) -> None:
    class AlteredTreeProvider(Provider):
        def run(self, command: tuple[str, ...]) -> dict[str, object]:
            result = super().run(command)
            if command[:1] == ("git",) and command[3] == "ls-tree":
                actual_blob = hashlib.sha1(b"blob 4\0test", usedforsecurity=False).hexdigest()
                result["stdout"] = str(result["stdout"]).replace(actual_blob, "f" * 40)
            return result

    provider = AlteredTreeProvider(case)
    with pytest.raises(CampaignError, match="bound canonical build inputs"):
        local_image.preflight_image_staging(
            case.runtime_path.parent,
            source_head=case.runtime["sourceHead"],
            canonical_input_sha256=case.runtime["canonicalBuildInputSha256"],
            runner=provider,
        )
    assert all(command[0] == "git" for command in provider.commands)
    assert case.runtime_path.exists()
    assert not (case.runtime_path.parent / "local-image").exists()
    assert not (case.runtime_path.parent / "local-image-attempt.json").exists()


def test_real_git_archive_ignores_workstation_autocrlf_without_changing_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "git-fixture"
    repository.mkdir()

    def git(*args: str) -> str:
        return subprocess.run(
            ("git", "-C", str(repository), *args),
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    git("init", "--quiet")
    directories = {"apps/api/opencanvas_api", "apps/api/alembic", "apps/api/scripts"}
    for name in BUILD_INPUTS:
        path = repository / name / "fixture.py" if name in directories else repository / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"first line\nsecond line\n")
    git("-c", "core.autocrlf=false", "add", "--", *BUILD_INPUTS)
    git("update-index", "--chmod=+x", "apps/api/scripts/fixture.py")
    git(
        "-c",
        "user.name=Synthetic Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "--quiet",
        "-m",
        "Synthetic canonical source",
    )
    source_head = git("rev-parse", "HEAD")
    config_before = (repository / ".git" / "config").read_bytes()
    monkeypatch.setattr(local_image, "ROOT", repository)
    monkeypatch.setattr(canonical_inputs, "REPOSITORY_ROOT", repository)
    input_hash = str(canonical_inputs.canonical_snapshot(source_head)["buildInputSha256"])
    tree = git("ls-tree", "-r", "--full-tree", source_head, "--", *BUILD_INPUTS)
    previous_archive = tmp_path / "previous.tar"
    git(
        "-c",
        "core.autocrlf=true",
        "archive",
        "--format=tar",
        "--output",
        str(previous_archive),
        source_head,
        "--",
        *BUILD_INPUTS,
    )
    with pytest.raises(CampaignError, match="content differs from the exact Git tree"):
        local_image._extract_source(
            previous_archive, tmp_path / "previous-source", tree, input_hash
        )

    class WindowsCheckoutRunner:
        def run(self, command: tuple[str, ...]) -> dict[str, object]:
            assert command[0] == "git"
            return SubprocessRunner().run(("git", "-c", "core.autocrlf=true", *command[1:]))

    output = tmp_path / "new-staging"
    output.mkdir()
    archive_path, context = local_image._stage_canonical_source(
        output,
        source_head,
        input_hash,
        WindowsCheckoutRunner().run,
    )
    local_image._extract_source(archive_path, context, tree, input_hash, extract=False)
    assert (context / "apps/api/scripts/fixture.py").read_bytes() == b"first line\nsecond line\n"
    assert (repository / ".git" / "config").read_bytes() == config_before


def test_scope_create_staging_path_failure_dispatches_zero_azure_and_keeps_ledger(
    case: Case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = case.ledger
    ledger.phase = Phase.COST_GATED.value
    ledger.transitions = ledger.transitions[: ORDER.index(Phase.COST_GATED)]
    ledger.resource_generation_count = 0
    ledger.cleanup_arm_evidence_sha256 = None
    ledger.validate_resume(case.config)
    previous = copy.deepcopy(ledger)
    provider = Provider(case)
    authorization_checks: list[str] = []
    ledger_writes: list[str] = []
    monkeypatch.setattr(CampaignConfig, "from_json", lambda _path, **_kwargs: case.config)
    monkeypatch.setattr(operator, "validate_prepared_bundle", lambda *_args: None)
    monkeypatch.setattr(operator, "load_bound_fresh_controller_admission", lambda *_args: None)
    monkeypatch.setattr(operator, "load_ledger", lambda *_args: ledger)
    monkeypatch.setattr(operator, "save_ledger", lambda *_args: ledger_writes.append("write"))
    monkeypatch.setattr(local_image, "SubprocessRunner", lambda: provider)

    def authorize(*_args: object, **kwargs: object) -> str:
        authorization_checks.append(str(kwargs["operation"]))
        return "approved"

    def no_azure_runner() -> None:
        raise AssertionError("Azure runner must not be constructed after local preflight failure")

    monkeypatch.setattr(operator, "load_execution_authorization", authorize)
    monkeypatch.setattr(operator, "SubprocessRunner", no_azure_runner)
    extract = tarfile.TarFile._extract_member
    observed_paths: list[Path] = []

    def fail_full_generated_path(
        archive: tarfile.TarFile,
        member: tarfile.TarInfo,
        targetpath: str,
        set_attrs: bool = True,
        numeric_owner: bool = False,
        *,
        filter_function: Callable[[tarfile.TarInfo, str], tarfile.TarInfo | None] | None = None,
        extraction_root: str | None = None,
    ) -> None:
        observed_paths.append(Path(targetpath))
        if member.name == "apps/api/scripts/test.txt":
            assert Path(targetpath) == (
                case.runtime_path.parent / "local-image" / "source" / member.name
            )
            raise OSError(206, "synthetic full generated filename too long", targetpath)
        extract(
            archive,
            member,
            targetpath,
            set_attrs=set_attrs,
            numeric_owner=numeric_owner,
            filter_function=filter_function,
            extraction_root=extraction_root,
        )

    monkeypatch.setattr(tarfile.TarFile, "_extract_member", fail_full_generated_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "operator",
            "scope-create",
            "--config",
            str(case.runtime_path.parent / "config.json"),
            "--runtime",
            str(case.runtime_path),
            "--ledger",
            str(case.runtime_path.parent / "ledger.json"),
            "--authorization",
            str(case.runtime_path.parent / "authorization.json"),
            "--execute",
        ],
    )
    assert operator.main() == 2
    assert authorization_checks == ["cleanup", "scope-create"]
    assert observed_paths
    assert all(command[0] == "git" for command in provider.commands)
    assert ledger_writes == []
    assert ledger == previous
    assert not (case.runtime_path.parent / "local-image").exists()
    assert not (case.runtime_path.parent / "local-image-attempt.json").exists()


def test_one_build_scan_and_exact_restoration_reaches_existing_scan_admission(case: Case) -> None:
    provider = Provider(case)
    result = execute(case, provider)
    output = case.runtime_path.parent / "local-image"
    assert result["imageDigest"] == DIGEST
    assert result["sourceHead"] == case.runtime["sourceHead"]
    assert result["canonicalBuildInputSha256"] == case.runtime["canonicalBuildInputSha256"]
    assert provider.registry == case.plan["before"]
    assert provider.patch_count == 2
    assert sum(command[:2] == ("docker", "build") for command in provider.commands) == 1
    operator.load_image_scan_evidence(
        output / "image-scan.json", digest=DIGEST, runtime=case.runtime
    )
    local_image.validate_completion(
        case.runtime_path,
        case.runtime,
        case.config,
        digest=DIGEST,
        scan_path=output / "image-scan.json",
    )
    with pytest.raises(CampaignError, match="already exists"):
        execute(case, provider)


def test_opened_bare_ipv4_readback_reaches_completion_without_rewriting_evidence(
    case: Case,
) -> None:
    provider = RuleReadbackProvider(case, [{"action": "Allow", "value": "8.8.4.4"}])
    assert execute(case, provider)["imageDigest"] == DIGEST
    output = case.runtime_path.parent / "local-image"
    observed = json.loads(json.loads((output / "03-response.json").read_text())["stdout"])
    assert observed["properties"]["networkRuleSet"]["ipRules"] == provider.rules
    assert cast(dict[str, object], case.plan["openBody"])["properties"] != local_image._network(
        observed
    )
    before = {path.name: path.read_bytes() for path in output.iterdir() if path.is_file()}
    local_image.validate_completion(
        case.runtime_path,
        case.runtime,
        case.config,
        digest=DIGEST,
        scan_path=output / "image-scan.json",
    )
    assert before == {path.name: path.read_bytes() for path in output.iterdir() if path.is_file()}
    assert provider.registry == case.plan["before"]
    assert provider.patch_count == 2


@pytest.mark.parametrize(
    "rules",
    [
        [{"action": "Allow", "value": "8.8.4.5"}],
        [{"action": "Allow", "value": "8.8.4.0/24"}],
        [{"action": "Allow", "value": "2001:4860:4860::8888/128"}],
        [{"action": "Allow", "value": "8.8.4.4"}] * 2,
        [],
        [{"action": "Allow"}],
        [{"value": "8.8.4.4"}],
        [{"action": "Deny", "value": "8.8.4.4"}],
        [{"action": "Allow", "value": "8.8.4.4", "unexpected": True}],
        None,
    ],
)
def test_opened_rule_drift_stops_before_build_and_restores(case: Case, rules: object) -> None:
    provider = RuleReadbackProvider(case, rules)
    with pytest.raises(CampaignError, match="cleanup required"):
        execute(case, provider)
    assert provider.registry == case.plan["before"]
    assert provider.patch_count == 2
    assert not any(command[0] == "docker" for command in provider.commands)
    assert not (case.runtime_path.parent / "local-image/completed.json").exists()


def test_bare_ipv4_rule_is_not_accepted_as_restoration(case: Case) -> None:
    provider = RuleReadbackProvider(case, [{"action": "Allow", "value": "8.8.4.4"}], after_patch=2)
    with pytest.raises(CampaignError, match="restoration unproved"):
        execute(case, provider)
    assert not (case.runtime_path.parent / "local-image/completed.json").exists()
    assert not (case.runtime_path.parent / "local-image/image-scan.json").exists()


@pytest.mark.parametrize(
    "fault",
    [
        "build-failure",
        "scan-failure",
        "digest",
        "oversize",
        "open-lost",
        "not-succeeded",
        "missing-id",
    ],
)
def test_failure_restores_exact_network_without_admitting(case: Case, fault: str) -> None:
    provider = Provider(case, fault=fault)
    with pytest.raises(CampaignError, match="cleanup required"):
        execute(case, provider)
    assert provider.registry == case.plan["before"]
    assert provider.patch_count == 2
    assert not (case.runtime_path.parent / "local-image" / "image-scan.json").exists()
    assert not (case.runtime_path.parent / "local-image" / "completed.json").exists()


def test_restore_response_loss_is_resolved_by_one_get_without_retry(case: Case) -> None:
    provider = Provider(case, fault="restore-lost")
    assert execute(case, provider)["imageDigest"] == DIGEST
    assert provider.patch_count == 2
    assert provider.registry == case.plan["before"]


def test_completion_rejects_tampered_raw_record_and_wrong_scan(case: Case) -> None:
    execute(case, Provider(case))
    output = case.runtime_path.parent / "local-image"
    with pytest.raises(CampaignError, match="binding differs"):
        local_image.validate_completion(
            case.runtime_path,
            case.runtime,
            case.config,
            digest=DIGEST,
            scan_path=output / "scan-pending.json",
        )
    (output / "restored.json").write_text("{}", encoding="utf-8")
    with pytest.raises(CampaignError, match="evidence differs"):
        local_image.validate_completion(
            case.runtime_path,
            case.runtime,
            case.config,
            digest=DIGEST,
            scan_path=output / "image-scan.json",
        )


@pytest.mark.parametrize(
    "field",
    [
        "bytes",
        "final-get",
        "source-command",
        "scan-command",
        "history",
        "inspect-scope",
        "manifest-scope",
        "opened-network",
        "opening-scope",
    ],
)
def test_completion_semantics_reject_even_self_consistent_file_hashes(
    case: Case, field: str
) -> None:
    execute(case, Provider(case))
    output = case.runtime_path.parent / "local-image"
    receipt = json.loads((output / "completed.json").read_text())
    if field == "bytes":
        receipt["imageBytes"] += 1
    elif field in {"final-get", "opened-network"}:
        path = (
            sorted(output.glob("*-response.json"))[-1]
            if field == "final-get"
            else output / "03-response.json"
        )
        response = json.loads(path.read_text())
        observed = json.loads(response["stdout"])
        if field == "final-get":
            observed["properties"]["publicNetworkAccess"] = "Enabled"
        else:
            observed["properties"]["networkRuleSet"]["ipRules"][0]["value"] = "8.8.4.5"
        response["stdout"] = json.dumps(observed)
        path.write_text(json.dumps(response), encoding="utf-8")
    else:
        for path in output.glob("*-intent.json"):
            intent = json.loads(path.read_text())
            command = intent["command"]
            if field == "source-command" and command[:1] == ["git"] and "archive" in command:
                command[command.index(case.runtime["sourceHead"])] = "f" * 40
            elif field == "scan-command" and command[:3] == ["docker", "scout", "cves"]:
                command[command.index("critical,high")] = "critical"
            elif field == "history" and command[:2] == ["docker", "build"]:
                path.with_name(path.name.replace("intent", "response")).unlink()
            elif field == "inspect-scope" and command[:3] == ["docker", "image", "inspect"]:
                command[-1] = "unrelated-image"
            elif field == "opening-scope" and path.name == "03-intent.json":
                command[command.index("--url") + 1] = "https://management.azure.com/unrelated"
            elif field == "manifest-scope" and command[:4] == [
                "az",
                "acr",
                "manifest",
                "show-metadata",
            ]:
                command[command.index("--registry") + 1] = "anotherregistry"
            else:
                continue
            path.write_text(json.dumps(intent), encoding="utf-8")
            break
    receipt["filesSha256"] = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in output.iterdir()
        if path.is_file() and path.name != "completed.json"
    }
    (output / "completed.json").write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(CampaignError):
        local_image.validate_completion(
            case.runtime_path,
            case.runtime,
            case.config,
            digest=DIGEST,
            scan_path=output / "image-scan.json",
        )


def test_legacy_registry_allow_rules_are_not_reopened(case: Case) -> None:
    before = copy.deepcopy(cast(dict[str, object], case.plan["before"]))
    properties = cast(dict[str, object], before["properties"])
    cast(dict[str, object], properties["networkRuleSet"])["virtualNetworkRules"] = [
        {"id": "legacy"}
    ]
    with pytest.raises(CampaignError, match="unexpected existing network rules"):
        local_image.build_plan(case.runtime, case.config, before, egress_ipv4="8.8.4.4")


@pytest.mark.parametrize("fault", ["restore-failure", "preservation-drift"])
def test_failed_restoration_blocks_pending_scan(case: Case, fault: str) -> None:
    provider = Provider(case, fault=fault)
    with pytest.raises(CampaignError, match="restoration unproved"):
        execute(case, provider)
    output = case.runtime_path.parent / "local-image"
    assert (output / "scan-pending.json").exists()
    assert not (output / "image-scan.json").exists()
    with pytest.raises(OSError):
        local_image.validate_completion(
            case.runtime_path,
            case.runtime,
            case.config,
            digest=DIGEST,
            scan_path=output / "scan-pending.json",
        )


@pytest.mark.parametrize("alteration", ["request", "approval", "expired", "source"])
def test_bad_bindings_rejected_before_any_provider_request(
    case: Case,
    alteration: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if alteration == "request":
        cast(dict[str, object], case.plan["openBody"])["properties"] = {
            "publicNetworkAccess": "Enabled"
        }
    elif alteration == "approval":
        case.approval["planSha256"] = "f" * 64
    elif alteration == "expired":
        case.approval = local_image.build_approval(
            case.plan,
            issued_at="2029-12-31T22:00:00Z",
            expires_at="2029-12-31T23:00:00Z",
            restore_until="2030-01-01T05:00:00Z",
        )
    else:
        monkeypatch.setattr(local_image, "local_source_binding", lambda: ("e" * 40, "f" * 64))
    provider = Provider(case)
    with pytest.raises(CampaignError):
        execute(case, provider)
    assert provider.commands == []


def test_expiry_after_build_stops_push_but_still_restores(case: Case) -> None:
    provider = Provider(case)

    def clock() -> datetime:
        if any(command[:2] == ("docker", "build") for command in provider.commands):
            return NOW + timedelta(hours=2)
        return NOW

    with pytest.raises(CampaignError, match="cleanup required"):
        local_image.execute_local_image(
            case.runtime_path,
            case.runtime,
            case.config,
            case.ledger,
            case.plan,
            case.approval,
            output=case.runtime_path.parent / "local-image",
            runner=provider,
            clock=clock,
        )
    assert provider.registry == case.plan["before"]
    assert not any(command[:2] == ("docker", "push") for command in provider.commands)


@pytest.mark.parametrize("failed_file", ["02-response.json", "restored.json"])
def test_persistence_failure_cannot_admit_and_attempts_restoration(
    case: Case,
    failed_file: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    persist = _durable_record

    def failing_persist(path: Path, value: object) -> None:
        if path.name == failed_file:
            raise OSError("synthetic disk error")
        persist(path, value)

    monkeypatch.setattr(local_image, "_durable_record", failing_persist)
    provider = Provider(case)
    with pytest.raises(CampaignError, match="cleanup required"):
        execute(case, provider)
    assert provider.registry == case.plan["before"]
    assert not (case.runtime_path.parent / "local-image" / "completed.json").exists()


@pytest.mark.parametrize("fault", ["", "scan-failure"])
def test_normal_cli_with_fake_provider_and_existing_failure_cleanup(
    case: Case,
    fault: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    folder = case.runtime_path.parent
    for name, value in (("plan", case.plan), ("approval", case.approval)):
        (folder / f"{name}.json").write_text(json.dumps(value), encoding="utf-8")
    provider = Provider(case, fault=fault)
    cleanup: list[str] = []
    monkeypatch.setattr(CampaignConfig, "from_json", lambda _path: case.config)
    monkeypatch.setattr(operator, "validate_prepared_bundle", lambda *_args: None)
    monkeypatch.setattr(local_image, "load_ledger", lambda *_args: case.ledger)
    monkeypatch.setattr(
        local_image, "load_execution_authorization", lambda *_args, **_kwargs: "approved"
    )
    monkeypatch.setattr(local_image, "SubprocessRunner", lambda **_kwargs: provider)
    monkeypatch.setattr(operator, "start_failure_cleanup", lambda *_args: cleanup.append("cleanup"))
    monkeypatch.setattr(local_image, "save_ledger", lambda *_args: None)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz: object = None) -> FrozenDateTime:
            return cls(2030, 1, 1, tzinfo=UTC)

    monkeypatch.setattr(local_image, "datetime", FrozenDateTime)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "local_image",
            "execute",
            "--runtime",
            str(case.runtime_path),
            "--config",
            str(folder / "config.json"),
            "--ledger",
            str(folder / "ledger.json"),
            "--plan",
            str(folder / "plan.json"),
            "--approval",
            str(folder / "approval.json"),
            "--cleanup-authorization",
            str(folder / "cleanup.json"),
            "--execute",
        ],
    )
    assert local_image.main() == (2 if fault else 0)
    assert cleanup == (["cleanup"] if fault else [])
    assert provider.registry == case.plan["before"]
