from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from test_milestone_7_8_campaign_enablement import _manifest, _write_execution_authorization
from test_milestone_7_8_local_image import DIGEST, Case, Provider, execute
from test_milestone_7_8_local_image import case as imported_case  # noqa: F401

from infra.milestone_7_8 import local_image, operator, retained_image
from infra.milestone_7_8.campaign import (
    CampaignConfig,
    CampaignError,
    Phase,
    load_ledger,
    save_ledger,
)

BUILD_HEAD = "9" * 40
IMAGE_ID = "sha256:" + "c" * 64


class RetainedProvider(Provider):
    def __init__(self, case: Case, *, fault: str = "") -> None:
        super().__init__(case, fault=fault)
        self.tagged = False
        self.pushed = False

    def run(self, command: tuple[str, ...]) -> dict[str, object]:
        reference = str(self.case.plan["imageReference"])
        if command[:2] in {("docker", "build"), ("docker", "load")}:
            pytest.fail("retained image must never build or load an image")
        if command[:2] == ("docker", "tag"):
            self.commands.append(command)
            assert command == ("docker", "tag", IMAGE_ID, reference)
            assert not self.tagged
            self.tagged = True
            return {"exitCode": 0, "stdout": "", "stderr": ""}
        if command[:3] == ("docker", "image", "inspect"):
            self.commands.append(command)
            if command[-1] == IMAGE_ID:
                assert self.patch_count == 0
            else:
                assert self.tagged and command[-1] == reference
            digest = "sha256:" + "f" * 64 if self.fault == "detached-push" else DIGEST
            image_id = (
                "sha256:" + "f" * 64
                if self.fault == "image-id" or (self.pushed and self.fault == "replaced-tag")
                else IMAGE_ID
            )
            result = [
                {
                    "Id": image_id,
                    "RepoDigests": [
                        f"{self.case.runtime['registryName']}.azurecr.io/mobius-api@{digest}",
                    ]
                    if self.pushed
                    else [],
                    "Os": "linux",
                    "Architecture": "amd64",
                    "Size": 100,
                    "Config": {
                        "Labels": {
                            "org.opencontainers.image.revision": (
                                self.case.runtime["sourceHead"]
                                if self.fault == "source-label"
                                else BUILD_HEAD
                            ),
                            "mobius.canonical-input-sha256": (
                                "1" * 64
                                if self.fault == "changed-inputs"
                                else self.case.runtime["canonicalBuildInputSha256"]
                            ),
                        }
                    },
                }
            ]
            return {"exitCode": 0, "stdout": json.dumps(result), "stderr": ""}
        if command[:2] == ("docker", "push"):
            assert command == ("docker", "push", reference) and self.tagged
            self.pushed = True
            if self.fault == "detached-push":
                self.commands.append(command)
                return {"exitCode": 0, "stdout": f"digest: sha256:{'f' * 64}", "stderr": ""}
        return super().run(command)


@pytest.fixture(name="case")
def retained_case(imported_case: Case) -> Case:  # noqa: F811
    return imported_case


@pytest.fixture
def retained_path(case: Case, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = case.runtime_path.with_name("retained-image.json")
    path.write_text('{"fixture":"already verified provenance"}', encoding="utf-8")
    approved_hash = hashlib.sha256(path.read_bytes()).hexdigest()

    def load_retained_image(
        provenance: Path,
        *,
        operator_head: str,
        canonical_input_sha256: str,
    ) -> dict[str, object]:
        assert provenance.resolve() == path.resolve()
        assert operator_head == case.runtime["sourceHead"]
        assert canonical_input_sha256 == case.runtime["canonicalBuildInputSha256"]
        if hashlib.sha256(provenance.read_bytes()).hexdigest() != approved_hash:
            raise CampaignError("retained provenance changed")
        return {
            "imageId": IMAGE_ID,
            "imageBuildSourceHead": BUILD_HEAD,
            "canonicalBuildInputSha256": canonical_input_sha256,
            "platform": "linux/amd64",
            "runtimeManifestDigest": DIGEST,
            "provenanceFile": str(path),
            "filesSha256": {path.name: approved_hash},
        }

    # The provenance module has separate archive/lineage tests; integrate its
    # closed output contract with the actual plan, executor, and receipt gates.
    monkeypatch.setattr(retained_image, "load_retained_image", load_retained_image)
    return path


def make_retained_plan(case: Case, retained_path: Path) -> None:
    case.plan = local_image.build_plan(
        case.runtime,
        case.config,
        case.plan["before"],
        egress_ipv4="8.8.4.4",
        retained_image=retained_path,
    )
    case.approval = local_image.build_approval(
        case.plan,
        issued_at="2030-01-01T00:00:00Z",
        expires_at="2030-01-01T01:00:00Z",
        restore_until="2030-01-01T05:00:00Z",
    )


def test_retained_image_reaches_normal_admission_without_building(
    case: Case,
    retained_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    folder = case.runtime_path.parent
    manifest = _manifest()
    principals = cast(dict[str, dict[str, str]], manifest["principals"])
    planned_principals = {
        "campaignId": case.config.campaign_id,
        "generationId": case.config.generation_id,
        "principals": {
            slot: principals[slot]["name"]
            for slot in (
                "bootstrap",
                "migration",
                "api",
                "worker",
                "evidence",
            )
        },
        "cleanup": principals["cleanup"]["name"],
    }
    case.config = replace(
        case.config,
        principal_manifest_sha256=hashlib.sha256(
            json.dumps(planned_principals, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    )
    binding: dict[str, object] = {
        "campaignId": case.config.campaign_id,
        "generationId": case.config.generation_id,
        "subscriptionCorrelation": case.config.subscription_correlation,
        "cleanupDeadlineUtc": case.config.cleanup_deadline_utc,
        "maximumHours": 4,
        "costCeilingCents": 5000,
        "principalManifest": json.dumps(manifest),
    }
    for field, key in (
        ("cleanupResourceGroupName", "cleanup_resource_group"),
        ("cleanupLocation", "cleanup_region"),
        ("cleanupRegionSelectionSha256", "cleanup_region_selection_sha256"),
        ("cleanupCandidateRegions", "cleanup_candidate_regions"),
        ("cleanupOfferClassification", "cleanup_offer_classification"),
        ("cleanupOfferEligibilityDisposition", "cleanup_offer_eligibility_disposition"),
        ("cleanupOfferEligibleRegions", "cleanup_offer_eligible_regions"),
        ("cleanupOfferEligibilitySource", "cleanup_offer_eligibility_source"),
        ("cleanupOfferEligibilitySha256", "cleanup_offer_eligibility_sha256"),
        ("freshControllerAdmissionEvidenceSha256", "fresh_controller_admission_evidence_sha256"),
    ):
        binding[field] = getattr(case.config, key)

    class WorkloadProvider(RetainedProvider):
        def run(self, command: tuple[str, ...]) -> dict[str, object]:
            if command[:4] != ("az", "deployment", "sub", "create"):
                return super().run(command)
            assert self.registry == case.plan["before"]
            assert "deploymentStage=workload" in command and f"imageDigest={DIGEST}" in command
            self.commands.append(command)
            outputs = {
                "campaignId": case.config.campaign_id,
                "generationId": case.config.generation_id,
                "deploymentStage": "workload",
                "imageDigest": DIGEST,
                "campaignBinding": binding,
            }
            response = {
                "properties": {"outputs": {key: {"value": value} for key, value in outputs.items()}}
            }
            return {"exitCode": 0, "stderr": "", "stdout": json.dumps(response)}

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz: object = None) -> FrozenDateTime:
            return cls(2030, 1, 1, tzinfo=UTC)

    case.ledger.bind_deadline(case.config.cleanup_deadline_utc)
    case.ledger.first_billable_mutation_utc = "2030-01-01T00:00:00Z"
    save_ledger(folder / "ledger.json", case.ledger)
    _write_execution_authorization(
        folder / "execution.json",
        case.config,
        case.runtime,
        expires_at="2030-01-01T01:00:00Z",
        operations=["cleanup", "image-decision"],
    )
    (folder / "before.json").write_text(json.dumps(case.plan["before"]), encoding="utf-8")
    # This fixture starts at the validated prepared/deployed boundary. Registry,
    # scan, ledger, execution authorization and workload output checks are real.
    monkeypatch.setattr(CampaignConfig, "from_json", lambda _path, **_kwargs: case.config)
    monkeypatch.setattr(operator, "validate_prepared_bundle", lambda *_args: None)
    monkeypatch.setattr(operator, "load_bound_fresh_controller_admission", lambda *_args: None)
    provider = WorkloadProvider(case)
    for module in (local_image, operator):
        monkeypatch.setattr(module, "SubprocessRunner", lambda **_kwargs: provider)
        monkeypatch.setattr(module, "datetime", FrozenDateTime)
    common = [
        "--runtime",
        str(case.runtime_path),
        "--config",
        str(folder / "config.json"),
        "--ledger",
        str(folder / "ledger.json"),
    ]
    image_common = [*common, "--plan", str(folder / "plan.json")]
    approval = ["--approval", str(folder / "approval.json")]
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "local_image",
            "plan",
            *image_common,
            "--registry-before",
            str(folder / "before.json"),
            "--egress-ipv4",
            "8.8.4.4",
            "--retained-image",
            str(retained_path),
        ],
    )
    assert local_image.main() == 0
    case.plan = json.loads((folder / "plan.json").read_text())
    assert case.plan["retainedImage"] != {}
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "local_image",
            "approve",
            *image_common,
            *approval,
            "--expires-at",
            "2030-01-01T01:00:00Z",
            "--restore-until",
            "2030-01-01T05:00:00Z",
        ],
    )
    assert local_image.main() == 0
    case.approval = json.loads((folder / "approval.json").read_text())
    assert case.approval["operation"] == (
        "one-retained-image-push-scout-with-exact-network-restoration"
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "local_image",
            "execute",
            *image_common,
            *approval,
            "--cleanup-authorization",
            str(folder / "execution.json"),
            "--execute",
        ],
    )
    assert local_image.main() == 0
    output = case.runtime_path.parent / "local-image"
    result = json.loads((output / "completed.json").read_text())
    assert result["version"] == "m7.8-local-image-result-v2"
    assert result["imageBuildCount"] == 0
    assert result["imageBuildSourceHead"] == BUILD_HEAD
    assert result["sourceHead"] == case.runtime["sourceHead"]
    assert result["retainedImageId"] == IMAGE_ID
    assert result["imageDigest"] == DIGEST
    assert [cmd[-1] for cmd in provider.commands if cmd[:3] == ("docker", "image", "inspect")] == [
        IMAGE_ID,
        case.plan["imageReference"],
        case.plan["imageReference"],
    ]
    assert provider.registry == case.plan["before"]
    assert provider.patch_count == 2
    scans = [cmd for cmd in provider.commands if cmd[:3] == ("docker", "scout", "cves")]
    assert len(scans) == 1
    assert scans[0][3].endswith("mobius-api@" + DIGEST)
    assert scans[0][scans[0].index("--platform") + 1] == "linux/amd64"
    operator.load_image_scan_evidence(
        output / "image-scan.json",
        digest=DIGEST,
        runtime=case.runtime,
    )
    local_image.validate_completion(
        case.runtime_path,
        case.runtime,
        case.config,
        digest=DIGEST,
        scan_path=output / "image-scan.json",
    )
    image_decision = [
        "operator",
        "image-decision",
        *common,
        "--authorization",
        str(folder / "execution.json"),
        "--image-digest",
        DIGEST,
        "--image-scan-evidence",
        str(output / "image-scan.json"),
        "--execute",
    ]
    scan_path = output / "image-scan.json"
    scan = scan_path.read_bytes()
    scan_path.unlink()
    monkeypatch.setattr(sys, "argv", image_decision)
    assert operator.main() == 2
    missing_scan = load_ledger(folder / "ledger.json", case.config)
    assert missing_scan.phase == Phase.INFRASTRUCTURE_DEPLOYED.value
    assert missing_scan.image_scan_count == 0
    scan_path.write_bytes(scan)
    monkeypatch.setattr(sys, "argv", [*image_decision, "--image-built"])
    assert operator.main() == 2
    untouched = load_ledger(folder / "ledger.json", case.config)
    assert untouched.phase == Phase.INFRASTRUCTURE_DEPLOYED.value
    assert untouched.image_digest is None and untouched.image_generation_count == 0
    monkeypatch.setattr(sys, "argv", image_decision)
    assert operator.main() == 0
    admitted = load_ledger(folder / "ledger.json", case.config)
    assert admitted.phase == Phase.IMAGE_DECIDED.value and admitted.image_digest == DIGEST
    assert admitted.image_scan_count == 1 and admitted.image_generation_count == 0
    assert admitted.cleanup_arm_evidence_sha256 == case.ledger.cleanup_arm_evidence_sha256


@pytest.mark.parametrize(
    "fault,push_expected,patch_count",
    [
        ("image-id", False, 0),
        ("source-label", False, 0),
        ("changed-inputs", False, 0),
        ("replaced-tag", True, 2),
        ("detached-push", True, 2),
    ],
)
def test_retained_execution_rejects_misbound_images_and_restores_registry(
    case: Case,
    retained_path: Path,
    fault: str,
    push_expected: bool,
    patch_count: int,
) -> None:
    make_retained_plan(case, retained_path)
    provider = RetainedProvider(case, fault=fault)
    with pytest.raises(CampaignError):
        execute(case, provider)
    assert provider.registry == case.plan["before"]
    assert provider.patch_count == patch_count
    assert provider.pushed is push_expected
    assert not (case.runtime_path.parent / "local-image/image-scan.json").exists()
    assert not any(command[:3] == ("docker", "scout", "cves") for command in provider.commands)


def test_retained_execution_rechecks_approved_provenance_before_commands(
    case: Case,
    retained_path: Path,
) -> None:
    make_retained_plan(case, retained_path)
    retained_path.write_text('{"fixture":"altered after plan"}', encoding="utf-8")
    provider = RetainedProvider(case)
    with pytest.raises(CampaignError, match="retained provenance"):
        execute(case, provider)
    assert provider.commands == []


def test_retained_registry_restoration_failure_blocks_admission(
    case: Case,
    retained_path: Path,
) -> None:
    make_retained_plan(case, retained_path)
    provider = RetainedProvider(case, fault="restore-failure")
    with pytest.raises(local_image.RegistryRestorationUnproved):
        execute(case, provider)
    output = case.runtime_path.parent / "local-image"
    assert provider.pushed and provider.patch_count == 2
    assert (output / "scan-pending.json").is_file()
    assert not (output / "completed.json").exists()
    assert not (output / "image-scan.json").exists()


def test_retained_replay_cannot_relabel_retained_tag_as_a_build(
    case: Case,
    retained_path: Path,
) -> None:
    make_retained_plan(case, retained_path)
    execute(case, RetainedProvider(case))
    output = case.runtime_path.parent / "local-image"
    receipt_path = output / "completed.json"
    receipt = json.loads(receipt_path.read_text())
    tag_path = next(
        path
        for path in output.glob("*-intent.json")
        if json.loads(path.read_text())["command"][:2] == ["docker", "tag"]
    )
    intent = json.loads(tag_path.read_text())
    intent["command"] = ["docker", "build", "--tag", case.plan["imageReference"], "."]
    tag_path.write_text(json.dumps(intent), encoding="utf-8")
    # Refresh the mechanical inventory hash. Replay must still reject this
    # history based on its command semantics.
    receipt["filesSha256"][tag_path.name] = hashlib.sha256(tag_path.read_bytes()).hexdigest()
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(CampaignError):
        local_image.validate_completion(
            case.runtime_path,
            case.runtime,
            case.config,
            digest=DIGEST,
            scan_path=output / "image-scan.json",
        )


@pytest.mark.parametrize("tamper", ["reorder", "extra"])
def test_retained_replay_requires_exact_command_sequence(
    case: Case,
    retained_path: Path,
    tamper: str,
) -> None:
    make_retained_plan(case, retained_path)
    execute(case, RetainedProvider(case))
    output = case.runtime_path.parent / "local-image"
    receipt_path = output / "completed.json"
    receipt = json.loads(receipt_path.read_text())
    intents = sorted(output.glob("*-intent.json"))
    selected = {tuple(json.loads(path.read_text())["command"][:2]): path for path in intents}
    tag = selected["docker", "tag"]
    info = selected["docker", "info"]
    if tamper == "reorder":
        for suffix in ("intent", "response"):
            first = tag.with_name(tag.name.replace("intent", suffix))
            second = info.with_name(info.name.replace("intent", suffix))
            left, right = first.read_bytes(), second.read_bytes()
            first.write_bytes(right)
            second.write_bytes(left)
    else:
        # An unrelated successful read with a matching approval and receipt
        # hash still falls outside the exact retained-image command sequence.
        for suffix in ("intent", "response"):
            original = info.with_name(info.name.replace("intent", suffix))
            extra = info.with_name(info.name.replace("-", "a-", 1).replace("intent", suffix))
            extra.write_bytes(original.read_bytes())
    receipt["filesSha256"] = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in output.iterdir()
        if p.is_file() and p != receipt_path
    }
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(CampaignError, match="retained image command sequence differs"):
        local_image.validate_completion(
            case.runtime_path,
            case.runtime,
            case.config,
            digest=DIGEST,
            scan_path=output / "image-scan.json",
        )
