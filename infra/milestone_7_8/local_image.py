"""One campaign-local Linux build, push and scan with bounded registry access.

No operation is inferred from a successful plan. Execution needs a separate exact
approval and the campaign's existing failure-cleanup authorization. Raw results,
the network baseline and command intents remain in the private campaign folder.
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import re
import shutil
import tarfile
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import cast

from infra.milestone_7_8 import operator, scout_admission
from infra.milestone_7_8.campaign import (
    CampaignConfig,
    CampaignError,
    CommandRunner,
    Ledger,
    Phase,
    SubprocessRunner,
    load_ledger,
    parse_utc,
    save_ledger,
    utc,
)
from infra.milestone_7_8.canonical_inputs import BUILD_INPUTS, DOMAIN, canonical_snapshot
from infra.milestone_7_8.cleanup_controller import load_execution_authorization
from infra.milestone_7_8.controller import local_source_binding
from infra.milestone_7_8.controller_renewal import _durable_record

ROOT = Path(__file__).resolve().parents[2]
MAX_IMAGE_BYTES = 2 * 1024**3
API_VERSION = "2025-11-01"
NETWORK_FIELDS = ("publicNetworkAccess", "networkRuleSet")
# Git archive otherwise applies the workstation's checkout newline conversion.
# These command-local settings leave repository configuration untouched.
ARCHIVE_OPTIONS = ("-c", "core.autocrlf=false", "-c", "core.eol=lf")


class RegistryRestorationUnproved(CampaignError):
    """The required private-registry boundary could not be re-established."""


def _hash(value: object) -> str:
    return hashlib.sha256(
        b"m7.8/local-image/v1\0"
        + json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise CampaignError("local image object is malformed")
    return cast(dict[str, object], value)


def _result(value: dict[str, object]) -> object:
    if value.get("exitCode") != 0 or not isinstance(value.get("stdout"), str):
        raise CampaignError("local image command failed; inspect the private response")
    try:
        return json.loads(cast(str, value["stdout"]))
    except (ValueError, TypeError) as exc:
        raise CampaignError("local image response is malformed") from exc


def _network(value: object) -> dict[str, object]:
    properties = _object(_object(value).get("properties"))
    if any(field not in properties for field in NETWORK_FIELDS):
        raise CampaignError("registry network snapshot is incomplete")
    return {field: properties[field] for field in NETWORK_FIELDS}


def _preserved(value: object) -> dict[str, object]:
    # ARM etag/systemData and provisioningState are server bookkeeping. Every
    # identity, role-mode, SKU, tag and other registry property stays exact.
    result = dict(_object(value))
    result.pop("etag", None)
    result.pop("systemData", None)
    properties = dict(_object(result.get("properties")))
    for field in (*NETWORK_FIELDS, "provisioningState"):
        properties.pop(field, None)
    result["properties"] = properties
    return result


def _verify_registry(observed: object, plan: dict[str, object], *, opened: bool = False) -> None:
    expected_network = (
        _object(plan["openBody"])["properties"] if opened else _network(plan["before"])
    )
    actual_network = _network(observed)
    if opened:
        rules = _object(actual_network["networkRuleSet"])
        # ARM can serialize a single IPv4 /32 as its bare address. Accept only
        # that exact approved host; every other rule and network field stays exact.
        if rules.get("ipRules") == [{"action": "Allow", "value": plan["egressIpv4"]}]:
            actual_network = {
                **actual_network,
                "networkRuleSet": {
                    **rules,
                    "ipRules": [{"action": "Allow", "value": f"{plan['egressIpv4']}/32"}],
                },
            }
    if actual_network != expected_network or _preserved(observed) != _preserved(plan["before"]):
        raise CampaignError("registry network or preserved properties differ")
    if _object(_object(observed).get("properties")).get("provisioningState") != "Succeeded":
        raise CampaignError("registry network readback is not provisioned successfully")


def build_plan(
    runtime: dict[str, str],
    config: CampaignConfig,
    before: object,
    *,
    egress_ipv4: str,
    retained_image: Path | None = None,
) -> dict[str, object]:
    """Create a reviewable exact plan from a separately captured registry GET."""
    try:
        address = ipaddress.IPv4Address(egress_ipv4)
    except ipaddress.AddressValueError as exc:
        raise CampaignError("one verified public IPv4 egress address is required") from exc
    registry = runtime["registryName"]
    if not address.is_global or re.fullmatch(r"[a-z0-9]{5,50}", registry) is None:
        raise CampaignError("registry or verified egress binding is invalid")
    resource_id = (
        f"/subscriptions/{runtime['subscriptionId']}/resourceGroups/"
        f"{config.target_resource_group}/providers/Microsoft.ContainerRegistry/"
        f"registries/{registry}"
    )
    record = _object(before)
    properties = _object(record.get("properties"))
    if (
        record.get("id") != resource_id
        or record.get("name") != registry
        or record.get("type") != "Microsoft.ContainerRegistry/registries"
        or _object(record.get("sku")).get("name") != "Premium"
        or properties.get("publicNetworkAccess") != "Disabled"
        or properties.get("adminUserEnabled") is not False
        or properties.get("anonymousPullEnabled") is not False
        or properties.get("provisioningState") != "Succeeded"
        or runtime["resourceGroupName"] != config.target_resource_group
    ):
        raise CampaignError("registry baseline is not the exact private campaign registry")
    original = _network(before)
    rules = _object(original["networkRuleSet"])
    if (
        rules.get("defaultAction") not in {"Allow", "Deny"}
        or rules.get("ipRules") != []
        or rules.get("virtualNetworkRules", []) != []
        or not set(rules) <= {"defaultAction", "ipRules", "virtualNetworkRules"}
    ):
        raise CampaignError("registry baseline has unexpected existing network rules")
    opened = {
        "publicNetworkAccess": "Enabled",
        "networkRuleSet": {
            **rules,
            "defaultAction": "Deny",
            "ipRules": [{"action": "Allow", "value": f"{address}/32"}],
        },
    }
    plan: dict[str, object] = {
        "version": "m7.8-local-image-plan-v1",
        "sourceHead": runtime["sourceHead"],
        "canonicalBuildInputSha256": runtime["canonicalBuildInputSha256"],
        "runtimeSha256": _hash(runtime),
        "configSha256": _hash(config_document(config)),
        "campaignId": config.campaign_id,
        "generationId": config.generation_id,
        "cleanupDeadlineUtc": config.cleanup_deadline_utc,
        "cleanupAuthorityExpiresUtc": runtime["cleanupAuthorityExpiresUtc"],
        "registryId": resource_id,
        "registryUrl": f"https://management.azure.com{resource_id}?api-version={API_VERSION}",
        "imageReference": f"{registry}.azurecr.io/mobius-api:m78-{config.generation_id}",
        "maximumImageBytes": MAX_IMAGE_BYTES,
        "egressIpv4": str(address),
        "before": before,
        "beforeSha256": _hash(before),
        "openBody": {"properties": opened},
        "restoreBody": {"properties": original},
    }
    if retained_image is not None:
        from infra.milestone_7_8.retained_image import load_retained_image

        plan["retainedImage"] = load_retained_image(
            retained_image,
            operator_head=runtime["sourceHead"],
            canonical_input_sha256=runtime["canonicalBuildInputSha256"],
        )
    plan["planSha256"] = _hash(plan)
    return plan


def _rebuild_plan(
    runtime: dict[str, str], config: CampaignConfig, plan: dict[str, object]
) -> dict[str, object]:
    retained = _object(plan["retainedImage"]) if "retainedImage" in plan else None
    return build_plan(
        runtime,
        config,
        plan.get("before"),
        egress_ipv4=str(plan["egressIpv4"]),
        retained_image=Path(str(retained["provenanceFile"])) if retained else None,
    )


def _image_build_head(plan: dict[str, object]) -> str:
    if "retainedImage" in plan:
        return str(_object(plan["retainedImage"])["imageBuildSourceHead"])
    return str(plan["sourceHead"])


def _validate_retained_inspection(value: object, plan: dict[str, object]) -> None:
    retained = _object(plan["retainedImage"])
    if not isinstance(value, list) or len(value) != 1:
        raise CampaignError("retained image inspection is incomplete")
    image = _object(value[0])
    labels = _object(_object(image.get("Config")).get("Labels"))
    size = image.get("Size")
    if (
        image.get("Id") != retained["imageId"]
        or image.get("Os") != "linux"
        or image.get("Architecture") != "amd64"
        or type(size) is not int
        or not 0 < size <= MAX_IMAGE_BYTES
        or labels.get("org.opencontainers.image.revision") != retained["imageBuildSourceHead"]
        or labels.get("mobius.canonical-input-sha256") != plan["canonicalBuildInputSha256"]
    ):
        raise CampaignError("retained image identity, platform or build provenance differs")


def config_document(config: CampaignConfig) -> object:
    from dataclasses import asdict

    return asdict(config)


def _extract_source(
    archive_path: Path,
    context: Path,
    tree: str,
    expected_input_hash: str,
    *,
    extract: bool = True,
) -> None:
    """Use only tracked canonical inputs, never ignored workstation residue."""
    observed: set[str] = set()
    expected: dict[str, tuple[str, str]] = {}
    for line in tree.splitlines():
        match = re.fullmatch(r"(100644|100755) blob ([a-f0-9]{40})\t([^\x00\r\n]+)", line)
        if match is None or match[3] in expected:
            raise CampaignError("canonical source tree contains unsupported entries")
        expected[match[3]] = (match[1], match[2])
    payload = {
        "inputs": list(BUILD_INPUTS),
        "treeEntries": [
            {"mode": mode, "object": object_id, "path": path}
            for path, (mode, object_id) in expected.items()
        ],
    }
    canonical_hash = hashlib.sha256(
        DOMAIN + json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if canonical_hash != expected_input_hash:
        raise CampaignError("source tree differs from bound canonical build inputs")
    with tarfile.open(archive_path) as archive:
        members = archive.getmembers()
        for member in members:
            path = PurePosixPath(member.name)
            if (
                path.is_absolute()
                or ".." in path.parts
                or "\\" in member.name
                or not (member.isfile() or member.isdir())
                or not (context / member.name).resolve().is_relative_to(context.resolve())
            ):
                raise CampaignError("source archive has an unsafe or unsupported entry")
            if member.isfile():
                if member.name in observed or not any(
                    member.name == allowed or member.name.startswith(allowed + "/")
                    for allowed in BUILD_INPUTS
                ):
                    raise CampaignError("source archive differs from canonical inputs")
                observed.add(member.name)
                stream = archive.extractfile(member)
                if stream is None or member.name not in expected:
                    raise CampaignError("source archive file is absent from the canonical tree")
                content = stream.read()
                blob = hashlib.sha1(
                    f"blob {len(content)}\0".encode() + content,
                    usedforsecurity=False,
                ).hexdigest()
                mode, object_id = expected[member.name]
                if blob != object_id or bool(member.mode & 0o111) != (mode == "100755"):
                    raise CampaignError("source archive content differs from the exact Git tree")
        if not all(
            allowed in observed or any(path.startswith(allowed + "/") for path in observed)
            for allowed in BUILD_INPUTS
        ):
            raise CampaignError("source archive omits canonical inputs")
        if observed != set(expected):
            raise CampaignError("source archive differs from the complete canonical tree")
        if extract:
            archive.extractall(context, filter="data")


def _stage_canonical_source(
    output: Path,
    source_head: str,
    canonical_input_sha256: str,
    run: Callable[[tuple[str, ...]], dict[str, object]],
) -> tuple[Path, Path]:
    """Use the same full source paths during preflight and the actual build."""
    archive_path = output / "source.tar"
    archive_result = run(
        (
            "git",
            "-C",
            str(ROOT),
            *ARCHIVE_OPTIONS,
            "archive",
            "--format=tar",
            "--output",
            str(archive_path),
            source_head,
            "--",
            *BUILD_INPUTS,
        )
    )
    tree = run(
        (
            "git",
            "-C",
            str(ROOT),
            "ls-tree",
            "-r",
            "--full-tree",
            source_head,
            "--",
            *BUILD_INPUTS,
        )
    )
    if (
        archive_result.get("exitCode") != 0
        or tree.get("exitCode") != 0
        or not isinstance(tree.get("stdout"), str)
    ):
        raise CampaignError("canonical source staging commands failed")
    context = output / "source"
    _extract_source(archive_path, context, cast(str, tree["stdout"]), canonical_input_sha256)
    return archive_path, context


def preflight_image_staging(
    bundle_directory: Path,
    *,
    source_head: str,
    canonical_input_sha256: str,
    runner: CommandRunner | None = None,
) -> None:
    """Exercise every actual generated source path before a target group is created.

    No image, attempt marker, authorization or persistent receipt is produced.
    Only the newly created staging tree is removed, including after a failed probe.
    """
    bundle_directory = bundle_directory.resolve()
    private_root = (ROOT / ".runtime" / "milestone_7_8").resolve()
    if not bundle_directory.is_relative_to(private_root) or not bundle_directory.is_dir():
        raise CampaignError("image staging preflight requires the exact private bundle directory")
    output = bundle_directory / "local-image"
    if output.exists() or (bundle_directory / "local-image-attempt.json").exists():
        raise CampaignError("image staging or an image attempt already exists")
    head, _script = local_source_binding()
    if (
        head != source_head
        or canonical_snapshot(head)["buildInputSha256"] != canonical_input_sha256
    ):
        raise CampaignError("image staging source or canonical build inputs differ")
    # mkdir must succeed exclusively before the cleanup block owns this path.
    output.mkdir(mode=0o700)
    identity = output.stat(follow_symlinks=False)
    try:
        _stage_canonical_source(
            output,
            source_head,
            canonical_input_sha256,
            (runner if runner is not None else SubprocessRunner()).run,
        )
    except (OSError, tarfile.TarError) as exc:
        raise CampaignError("full generated image staging path preflight failed") from exc
    finally:
        try:
            current = output.stat(follow_symlinks=False)
            if (
                output.is_symlink()
                or output.is_junction()
                or output.resolve().parent != bundle_directory
                or (current.st_dev, current.st_ino) != (identity.st_dev, identity.st_ino)
            ):
                raise CampaignError("image staging ownership changed; private probe retained")
            shutil.rmtree(output)
        except OSError as exc:
            raise CampaignError("image staging preflight cleanup failed; probe retained") from exc


def build_approval(
    plan: dict[str, object], *, issued_at: str, expires_at: str, restore_until: str
) -> dict[str, object]:
    issued, expires, restore = map(parse_utc, (issued_at, expires_at, restore_until))
    if not (
        issued < expires <= issued + timedelta(hours=1)
        and expires <= parse_utc(str(plan["cleanupDeadlineUtc"]))
        and expires <= restore <= parse_utc(str(plan["cleanupAuthorityExpiresUtc"]))
    ):
        raise CampaignError("local image approval or restoration window is invalid")
    document: dict[str, object] = {
        "version": "m7.8-local-image-approval-v1",
        "operation": (
            "one-retained-image-push-scout-with-exact-network-restoration"
            if "retainedImage" in plan
            else "one-local-build-push-scout-with-exact-network-restoration"
        ),
        "planSha256": plan["planSha256"],
        "issuedAtUtc": issued_at,
        "expiresAtUtc": expires_at,
        "restoreUntilUtc": restore_until,
    }
    document["approvalSha256"] = _hash(document)
    return document


def validate_inputs(
    runtime: dict[str, str],
    config: CampaignConfig,
    ledger: Ledger,
    plan: dict[str, object],
    approval: dict[str, object],
    now: datetime,
) -> None:
    if plan != _rebuild_plan(runtime, config, plan):
        raise CampaignError("local image plan binding differs")
    expected = build_approval(
        plan,
        issued_at=str(approval.get("issuedAtUtc")),
        expires_at=str(approval.get("expiresAtUtc")),
        restore_until=str(approval.get("restoreUntilUtc")),
    )
    if approval != expected or not (
        parse_utc(str(approval["issuedAtUtc"])) <= now < parse_utc(str(approval["expiresAtUtc"]))
    ):
        raise CampaignError("local image approval is expired or differs")
    ledger.validate_resume(config)
    if (
        ledger.phase != Phase.INFRASTRUCTURE_DEPLOYED.value
        or ledger.image_generation_count != 0
        or ledger.image_digest is not None
        or ledger.image_scan_count != 0
        or ledger.cleanup_arm_evidence_sha256 is None
    ):
        raise CampaignError("local image requires one unused build and verified cleanup")


def execute_local_image(
    runtime_path: Path,
    runtime: dict[str, str],
    config: CampaignConfig,
    ledger: Ledger,
    plan: dict[str, object],
    approval: dict[str, object],
    *,
    output: Path,
    runner: CommandRunner,
    clock: Callable[[], datetime],
) -> dict[str, object]:
    """Build once; restore networking even on failure; emit admission only afterwards."""
    validate_inputs(runtime, config, ledger, plan, approval, clock())
    if not runtime_path.resolve().is_relative_to((ROOT / ".runtime" / "milestone_7_8").resolve()):
        raise CampaignError("image artifacts must remain in the ignored private root")
    if output.resolve().parent != runtime_path.resolve().parent or output.name != "local-image":
        raise CampaignError("image output must be the single private local-image directory")
    if output.exists():
        raise CampaignError("image attempt already exists; automatic retry is prohibited")
    head, _script = local_source_binding()
    if (
        head != runtime["sourceHead"]
        or canonical_snapshot(head)["buildInputSha256"] != runtime["canonicalBuildInputSha256"]
    ):
        raise CampaignError("image source or canonical build inputs differ")
    _durable_record(
        runtime_path.parent / "local-image-attempt.json",
        {
            "planSha256": plan["planSha256"],
            "approvalSha256": approval["approvalSha256"],
        },
    )
    output.mkdir(mode=0o700)
    _durable_record(output / "plan.json", plan)
    _durable_record(output / "approval.json", approval)
    sequence = 0

    def run(command: tuple[str, ...], *, restore: bool = False) -> dict[str, object]:
        nonlocal sequence
        limit = "restoreUntilUtc" if restore else "expiresAtUtc"
        if clock() >= parse_utc(str(approval[limit])):
            raise CampaignError("image dispatch authorization expired")
        sequence += 1
        stem = f"{sequence:02d}"
        _durable_record(
            output / f"{stem}-intent.json",
            {
                "command": command,
                "approvalSha256": approval["approvalSha256"],
                "intentAtUtc": utc(clock()),
            },
        )
        if clock() >= parse_utc(str(approval[limit])):
            raise CampaignError("image authorization expired before dispatch")
        try:
            response = runner.run(command)
        except Exception as exc:
            _durable_record(output / f"{stem}-indeterminate.json", {"error": type(exc).__name__})
            raise CampaignError("image command outcome is indeterminate") from exc
        _durable_record(output / f"{stem}-response.json", response)
        if response.get("exitCode") != 0 and command[:3] != ("docker", "scout", "cves"):
            raise CampaignError("image command failed; private response retained")
        return response

    def get(*, restore: bool = False) -> object:
        return _result(
            run(
                (
                    "az",
                    "rest",
                    "--method",
                    "get",
                    "--url",
                    str(plan["registryUrl"]),
                    "--subscription",
                    runtime["subscriptionId"],
                    "--output",
                    "json",
                ),
                restore=restore,
            )
        )

    def patch(field: str, *, restore: bool = False) -> None:
        body_path = output / f"{field}.json"
        _durable_record(body_path, plan[field])
        run(
            (
                "az",
                "rest",
                "--method",
                "patch",
                "--url",
                str(plan["registryUrl"]),
                "--subscription",
                runtime["subscriptionId"],
                "--body",
                f"@{body_path}",
                "--output",
                "json",
            ),
            restore=restore,
        )

    retained = _object(plan["retainedImage"]) if "retainedImage" in plan else None
    if retained is not None:
        _validate_retained_inspection(
            _result(run(("docker", "image", "inspect", str(retained["imageId"])))),
            plan,
        )
    baseline = get()
    _verify_registry(baseline, plan)
    _durable_record(output / "fresh-before.json", baseline)
    # Record restoration scope before any network mutation. An interruption can
    # be inspected using plan.json, openBody.json and the retained intents.
    _durable_record(output / "restore-scope.json", plan["restoreBody"])
    opened = False
    failure: Exception | None = None
    receipt: dict[str, object] | None = None
    try:
        opened = True  # even a lost PATCH response must take the restoration path
        patch("openBody")
        _verify_registry(get(), plan, opened=True)
        info = _object(_result(run(("docker", "info", "--format", "{{json .}}"))))
        if info.get("OSType") != "linux" or info.get("Architecture") not in {"amd64", "x86_64"}:
            raise CampaignError("the campaign requires a Linux amd64 Docker engine")
        reference = str(plan["imageReference"])
        archive_path, context = _stage_canonical_source(
            output,
            head,
            runtime["canonicalBuildInputSha256"],
            run,
        )
        if retained is not None:
            run(("docker", "tag", str(retained["imageId"]), reference))
        else:
            run(
                (
                    "docker",
                    "build",
                    "--platform",
                    "linux/amd64",
                    "--file",
                    str(context / "apps/api/Dockerfile"),
                    "--label",
                    f"org.opencontainers.image.revision={head}",
                    "--label",
                    f"mobius.canonical-input-sha256={runtime['canonicalBuildInputSha256']}",
                    "--tag",
                    reference,
                    str(context),
                )
            )
        image = _result(run(("docker", "image", "inspect", reference)))
        if not isinstance(image, list) or len(image) != 1:
            raise CampaignError("built image identity is missing")
        metadata = _object(image[0])
        if retained is not None:
            _validate_retained_inspection(image, plan)
        labels = _object(_object(metadata.get("Config")).get("Labels"))
        size = metadata.get("Size")
        if (
            metadata.get("Os") != "linux"
            or re.fullmatch(r"sha256:[a-f0-9]{64}", str(metadata.get("Id"))) is None
            or metadata.get("Architecture") != "amd64"
            or type(size) is not int
            or not 0 < size <= MAX_IMAGE_BYTES
            or labels.get("org.opencontainers.image.revision") != _image_build_head(plan)
            or labels.get("mobius.canonical-input-sha256") != runtime["canonicalBuildInputSha256"]
        ):
            raise CampaignError("built image platform, source labels or size bound differs")
        # Source may not change while Docker reads its context.
        if local_source_binding()[0] != head:
            raise CampaignError("build source changed during execution")
        run(
            (
                "az",
                "acr",
                "login",
                "--name",
                runtime["registryName"],
                "--subscription",
                runtime["subscriptionId"],
            )
        )
        pushed = run(("docker", "push", reference))
        digests = re.findall(r"digest:\s*(sha256:[a-f0-9]{64})", str(pushed["stdout"]))
        if len(set(digests)) != 1:
            raise CampaignError("one exact pushed manifest digest is required")
        digest = digests[0]
        if retained is not None and digest not in {
            retained["imageId"],
            retained["runtimeManifestDigest"],
        }:
            raise CampaignError("pushed digest differs from the retained image archive")
        pushed_image = _result(run(("docker", "image", "inspect", reference)))
        if retained is not None:
            _validate_retained_inspection(pushed_image, plan)
        if (
            not isinstance(pushed_image, list)
            or len(pushed_image) != 1
            or _object(pushed_image[0]).get("Id") != metadata.get("Id")
            or not isinstance(_object(pushed_image[0]).get("RepoDigests"), list)
            or f"{runtime['registryName']}.azurecr.io/mobius-api@{digest}"
            not in cast(list[object], _object(pushed_image[0])["RepoDigests"])
        ):
            raise CampaignError("pushed digest is not the exact locally built image")
        manifest = _object(
            _result(
                run(
                    (
                        "az",
                        "acr",
                        "manifest",
                        "show-metadata",
                        "--registry",
                        runtime["registryName"],
                        "--subscription",
                        runtime["subscriptionId"],
                        "--name",
                        f"mobius-api@{digest}",
                        "--output",
                        "json",
                    )
                )
            )
        )
        if manifest.get("digest") != digest:
            raise CampaignError("registry manifest differs from the pushed digest")
        scout_admission.create_scout_receipt(
            runtime_path,
            digest,
            output / "scout.sarif.json",
            output / "scan-pending.json",
            runner=_RecordingRunner(run),
            clock=clock,
            recover_transport=True,
        )
        receipt = {
            "version": "m7.8-local-image-result-v2" if retained else "m7.8-local-image-result-v1",
            "planSha256": plan["planSha256"],
            "approvalSha256": approval["approvalSha256"],
            "sourceHead": head,
            "canonicalBuildInputSha256": runtime["canonicalBuildInputSha256"],
            "imageDigest": digest,
            "imageBytes": size,
            "imageBuildCount": 0 if retained else 1,
            "sourceArchiveSha256": hashlib.sha256(archive_path.read_bytes()).hexdigest(),
        }
        if retained is not None:
            receipt.update(
                {
                    "imageBuildSourceHead": retained["imageBuildSourceHead"],
                    "retainedImageId": retained["imageId"],
                }
            )
    except Exception as exc:
        failure = exc
    finally:
        if opened:
            try:
                # A lost response is not a reason to repeat the PATCH. One GET
                # can establish restoration; otherwise cleanup stays required.
                with suppress(CampaignError):
                    patch("restoreBody", restore=True)
                restored = get(restore=True)
                _verify_registry(restored, plan)
                _durable_record(output / "restored.json", restored)
            except Exception as exc:
                # Failed diagnostic persistence cannot erase the established
                # loss of the registry restoration boundary.
                with suppress(Exception):
                    _durable_record(
                        output / "restoration-failed.json",
                        {
                            "error": type(exc).__name__,
                            "originalError": type(failure).__name__ if failure else None,
                            "cleanupRequired": True,
                        },
                    )
                raise RegistryRestorationUnproved(
                    "registry restoration unproved; campaign cleanup required"
                ) from exc
    if failure is not None:
        raise CampaignError(
            "image attempt failed after verified restoration; stage recovery review required"
        ) from failure
    if receipt is None:
        raise CampaignError("image receipt is unavailable")
    receipt["restorationSha256"] = _hash(json.loads((output / "restored.json").read_text()))
    scan = json.loads((output / "scan-pending.json").read_text())
    _durable_record(output / "image-scan.json", scan)
    operator.load_image_scan_evidence(
        output / "image-scan.json", digest=str(receipt["imageDigest"]), runtime=runtime
    )
    receipt["scanFileSha256"] = hashlib.sha256(
        (output / "image-scan.json").read_bytes()
    ).hexdigest()
    receipt["filesSha256"] = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in output.iterdir()
        if path.is_file()
    }
    _durable_record(output / "completed.json", receipt)
    return receipt


def validate_completion(
    runtime_path: Path,
    runtime: dict[str, str],
    config: CampaignConfig,
    *,
    digest: str,
    scan_path: Path,
) -> int:
    """An attempted local route cannot admit its pending scan before restoration."""
    output = runtime_path.parent / "local-image"
    marker = _object(json.loads((runtime_path.parent / "local-image-attempt.json").read_text()))
    receipt = _object(json.loads((output / "completed.json").read_text()))
    plan = _object(json.loads((output / "plan.json").read_text()))
    approval = _object(json.loads((output / "approval.json").read_text()))
    retained = _object(plan["retainedImage"]) if "retainedImage" in plan else None
    retained_fields = {"imageBuildSourceHead", "retainedImageId"} if retained else set()
    if (
        set(receipt)
        != {
            "version",
            "planSha256",
            "approvalSha256",
            "sourceHead",
            "canonicalBuildInputSha256",
            "imageDigest",
            "imageBytes",
            "imageBuildCount",
            "sourceArchiveSha256",
            "restorationSha256",
            "scanFileSha256",
            "filesSha256",
        }
        | retained_fields
        or plan != _rebuild_plan(runtime, config, plan)
        or marker
        != {"planSha256": plan["planSha256"], "approvalSha256": approval["approvalSha256"]}
        or receipt.get("version")
        != ("m7.8-local-image-result-v2" if retained else "m7.8-local-image-result-v1")
        or receipt.get("planSha256") != plan["planSha256"]
        or receipt.get("approvalSha256") != approval["approvalSha256"]
        or receipt.get("sourceHead") != runtime["sourceHead"]
        or receipt.get("canonicalBuildInputSha256") != runtime["canonicalBuildInputSha256"]
        or receipt.get("imageDigest") != digest
        or type(receipt.get("imageBuildCount")) is not int
        or receipt.get("imageBuildCount") != (0 if retained else 1)
        or (
            retained is not None
            and (
                receipt.get("retainedImageId") != retained["imageId"]
                or receipt.get("imageBuildSourceHead") != retained["imageBuildSourceHead"]
                or digest not in {retained["imageId"], retained["runtimeManifestDigest"]}
            )
        )
        or approval
        != build_approval(
            plan,
            issued_at=str(approval.get("issuedAtUtc")),
            expires_at=str(approval.get("expiresAtUtc")),
            restore_until=str(approval.get("restoreUntilUtc")),
        )
        or scan_path.resolve() != (output / "image-scan.json").resolve()
    ):
        raise CampaignError("local image completion binding differs")
    files = _object(receipt.get("filesSha256"))
    if receipt.get("sourceArchiveSha256") != files.get("source.tar"):
        raise CampaignError("local image source archive binding differs")
    if set(files) != {
        path.name for path in output.iterdir() if path.is_file() and path.name != "completed.json"
    }:
        raise CampaignError("local image retained evidence inventory differs")
    for name, expected in files.items():
        if (
            Path(name).name != name
            or hashlib.sha256((output / name).read_bytes()).hexdigest() != expected
        ):
            raise CampaignError("local image retained evidence differs")
    records: list[tuple[list[object], dict[str, object]]] = []
    intents: list[list[object]] = []
    scan_times: list[datetime] = []
    for path in sorted(output.glob("*-intent.json")):
        intent = _object(json.loads(path.read_text()))
        command = intent.get("command")
        if (
            not isinstance(command, list)
            or intent.get("approvalSha256") != approval["approvalSha256"]
        ):
            raise CampaignError("local image command binding differs")
        intents.append(command)
        response_path = path.with_name(path.name.replace("-intent.json", "-response.json"))
        if command[:3] == ["docker", "scout", "cves"]:
            intent_time = intent.get("intentAtUtc")
            if (
                not isinstance(intent_time, str)
                or not parse_utc(str(approval["issuedAtUtc"])) <= parse_utc(intent_time)
                < parse_utc(str(approval["expiresAtUtc"]))
                or not response_path.exists()
                or path.with_name(path.name.replace("-intent.json", "-indeterminate.json")).exists()
            ):
                raise CampaignError("local image scanner dispatch history is incomplete or expired")
            scan_times.append(parse_utc(intent_time))
        if response_path.exists():
            records.append((command, _object(json.loads(response_path.read_text()))))

    def required(
        prefix: tuple[str, ...], count: int = 1
    ) -> list[tuple[list[object], dict[str, object]]]:
        selected = [row for row in records if row[0][: len(prefix)] == list(prefix)]
        if len(selected) != count or any(row[1].get("exitCode") != 0 for row in selected):
            raise CampaignError("local image successful command history is incomplete")
        return selected

    registry_get = [
        "az",
        "rest",
        "--method",
        "get",
        "--url",
        plan["registryUrl"],
        "--subscription",
        runtime["subscriptionId"],
        "--output",
        "json",
    ]
    registry_open = [
        "az",
        "rest",
        "--method",
        "patch",
        "--url",
        plan["registryUrl"],
        "--subscription",
        runtime["subscriptionId"],
        "--body",
        f"@{output / 'openBody.json'}",
        "--output",
        "json",
    ]
    opening_commands = [registry_get, registry_open, registry_get]
    offset = 1 if retained else 0
    opening_records = records[offset : offset + 3]
    if (
        intents[offset : offset + 3] != opening_commands
        or [command for command, _response in opening_records] != opening_commands
        or any(response.get("exitCode") != 0 for _command, response in opening_records)
        or json.loads((output / "openBody.json").read_text()) != plan["openBody"]
        or json.loads((output / "fresh-before.json").read_text()) != _result(opening_records[0][1])
    ):
        raise CampaignError("local image exact opening command or raw readback differs")
    _verify_registry(_result(opening_records[0][1]), plan)
    _verify_registry(_result(opening_records[2][1]), plan, opened=True)

    source = str(output / "source")
    archive_command, _archive_response = required(
        ("git", "-C", str(ROOT), *ARCHIVE_OPTIONS, "archive")
    )[0]
    tree_command, tree_response = required(("git", "-C", str(ROOT), "ls-tree"))[0]
    if (
        archive_command
        != [
            "git",
            "-C",
            str(ROOT),
            *ARCHIVE_OPTIONS,
            "archive",
            "--format=tar",
            "--output",
            str(output / "source.tar"),
            runtime["sourceHead"],
            "--",
            *BUILD_INPUTS,
        ]
        or tree_command
        != [
            "git",
            "-C",
            str(ROOT),
            "ls-tree",
            "-r",
            "--full-tree",
            runtime["sourceHead"],
            "--",
            *BUILD_INPUTS,
        ]
        or not isinstance(tree_response.get("stdout"), str)
    ):
        raise CampaignError("local image canonical source command differs")
    _extract_source(
        output / "source.tar",
        Path(source),
        cast(str, tree_response["stdout"]),
        runtime["canonicalBuildInputSha256"],
        extract=False,
    )
    if retained is not None:
        if any(
            command[:2] in (["docker", "build"], ["docker", "buildx"]) for command in intents
        ) or required(("docker", "tag"))[0][0] != [
            "docker",
            "tag",
            retained["imageId"],
            plan["imageReference"],
        ]:
            raise CampaignError("retained image route rebuilt or retagged another image")
        if not intents or intents[0] != ["docker", "image", "inspect", retained["imageId"]]:
            raise CampaignError("retained image pre-mutation inspection is missing")
    elif required(("docker", "build"))[0][0] != [
        "docker",
        "build",
        "--platform",
        "linux/amd64",
        "--file",
        str(output / "source" / "apps/api/Dockerfile"),
        "--label",
        f"org.opencontainers.image.revision={runtime['sourceHead']}",
        "--label",
        f"mobius.canonical-input-sha256={runtime['canonicalBuildInputSha256']}",
        "--tag",
        plan["imageReference"],
        source,
    ]:
        raise CampaignError("local image build source or tag differs")
    inspected = required(("docker", "image", "inspect"), 3 if retained else 2)
    if retained is not None:
        if inspected[0][0] != intents[0] or records[0] != inspected[0]:
            raise CampaignError("retained image initial inspection binding differs")
        for _command, response in inspected:
            _validate_retained_inspection(_result(response), plan)
        inspected = inspected[1:]
    if any(row[0] != ["docker", "image", "inspect", plan["imageReference"]] for row in inspected):
        raise CampaignError("local image inspection target differs")
    image_results = [_result(row[1]) for row in inspected]
    if any(not isinstance(value, list) or len(value) != 1 for value in image_results):
        raise CampaignError("local image inspection history is incomplete")
    original = _object(cast(list[object], image_results[0])[0])
    pushed = _object(cast(list[object], image_results[1])[0])
    labels = _object(_object(original.get("Config")).get("Labels"))
    if (
        original.get("Size") != receipt.get("imageBytes")
        or type(original.get("Size")) is not int
        or not 0 < cast(int, original["Size"]) <= MAX_IMAGE_BYTES
        or original.get("Id") != pushed.get("Id")
        or re.fullmatch(r"sha256:[a-f0-9]{64}", str(original.get("Id"))) is None
        or original.get("Os") != "linux"
        or original.get("Architecture") != "amd64"
        or labels.get("org.opencontainers.image.revision") != _image_build_head(plan)
        or labels.get("mobius.canonical-input-sha256") != runtime["canonicalBuildInputSha256"]
        or f"{runtime['registryName']}.azurecr.io/mobius-api@{digest}"
        not in cast(list[object], pushed.get("RepoDigests", []))
    ):
        raise CampaignError("local image source, size or pushed digest evidence differs")
    push_command, push_response = required(("docker", "push"))[0]
    manifest_command, manifest_response = required(("az", "acr", "manifest", "show-metadata"))[0]
    scan_records = [row for row in records if row[0][:3] == ["docker", "scout", "cves"]]
    scan_intents = [command for command in intents if command[:3] == ["docker", "scout", "cves"]]
    if (
        len(scan_records) not in {1, 2}
        or len(scan_records) != len(scan_intents)
        or scan_times != sorted(scan_times)
    ):
        raise CampaignError("local image scanner attempt history is incomplete")
    final_report = output / "scout.sarif.json"
    for index, (scan_command, scan_response) in enumerate(scan_records):
        report = final_report if index == 0 else scout_admission.retry_report_path(final_report)
        expected_scan = [
            "docker", "scout", "cves",
            f"registry://{runtime['registryName']}.azurecr.io/mobius-api@{digest}",
            "--platform", "linux/amd64", "--only-severity", "critical,high",
            "--exit-code", "--format", "sarif", "--output", str(report),
        ]
        if (
            scan_command != expected_scan
            or type(scan_response.get("exitCode")) is not int
            or not isinstance(scan_response.get("stdout"), str)
            or not isinstance(scan_response.get("stderr"), str)
        ):
            raise CampaignError("local image scan request or response differs")
        if index == len(scan_records) - 1:
            if scan_response["exitCode"] != 0:
                raise CampaignError("local image final scan is unsuccessful")
        elif not scout_admission.retryable_transport_failure(scan_response, report):
            raise CampaignError(
                "local image scanner recovery is not an unassessed transport failure"
            )
    if len(scan_records) == 2:
        if intents.index(scan_intents[1]) != intents.index(scan_intents[0]) + 1:
            raise CampaignError("local image scanner recovery is not the same bounded step")
        final_report = scout_admission.retry_report_path(final_report)
    if (
        push_command != ["docker", "push", plan["imageReference"]]
        or set(re.findall(r"digest:\s*(sha256:[a-f0-9]{64})", str(push_response["stdout"])))
        != {digest}
        or manifest_command
        != [
            "az",
            "acr",
            "manifest",
            "show-metadata",
            "--registry",
            runtime["registryName"],
            "--subscription",
            runtime["subscriptionId"],
            "--name",
            f"mobius-api@{digest}",
            "--output",
            "json",
        ]
        or _object(_result(manifest_response)).get("digest") != digest
    ):
        raise CampaignError("local image push, registry or scan digest evidence differs")
    sarif = _object(json.loads(final_report.read_text()))
    runs = sarif.get("runs")
    if (
        sarif.get("version") != "2.1.0"
        or not isinstance(runs, list)
        or not runs
        or any(_object(run).get("results") != [] for run in runs)
    ):
        raise CampaignError("local image raw scan is incomplete or contains findings")
    restored = json.loads((output / "restored.json").read_text())
    if (
        intents[-2:]
        != [
            [
                "az",
                "rest",
                "--method",
                "patch",
                "--url",
                plan["registryUrl"],
                "--subscription",
                runtime["subscriptionId"],
                "--body",
                f"@{output / 'restoreBody.json'}",
                "--output",
                "json",
            ],
            [
                "az",
                "rest",
                "--method",
                "get",
                "--url",
                plan["registryUrl"],
                "--subscription",
                runtime["subscriptionId"],
                "--output",
                "json",
            ],
        ]
        or records[-1][0] != intents[-1]
        or _result(records[-1][1]) != restored
        or json.loads((output / "restoreBody.json").read_text()) != plan["restoreBody"]
    ):
        raise CampaignError("local image exact restoration command or raw readback differs")
    if (
        _hash(restored) != receipt.get("restorationSha256")
        or _network(restored) != _network(plan["before"])
        or _preserved(restored) != _preserved(plan["before"])
        or _object(_object(restored).get("properties")).get("provisioningState") != "Succeeded"
        or operator.load_image_scan_evidence(scan_path, digest=digest, runtime=runtime)
        != receipt.get("scanFileSha256")
    ):
        raise CampaignError("local image restoration or scan binding differs")
    if retained is not None:
        expected_commands = [
            ["docker", "image", "inspect", retained["imageId"]],
            *opening_commands,
            ["docker", "info", "--format", "{{json .}}"],
            archive_command,
            tree_command,
            ["docker", "tag", retained["imageId"], plan["imageReference"]],
            ["docker", "image", "inspect", plan["imageReference"]],
            [
                "az",
                "acr",
                "login",
                "--name",
                runtime["registryName"],
                "--subscription",
                runtime["subscriptionId"],
            ],
            push_command,
            ["docker", "image", "inspect", plan["imageReference"]],
            manifest_command,
            ["git", "rev-parse", "HEAD"],
            ["git", "status", "--porcelain=v1"],
            ["docker", "scout", "version"],
            *scan_intents,
            *intents[-2:],
        ]
        if intents != expected_commands:
            raise CampaignError("retained image command sequence differs")
        last_time = parse_utc(str(approval["issuedAtUtc"]))
        paths = sorted(output.glob("*-intent.json"))
        for index, path in enumerate(paths):
            intent = _object(json.loads(path.read_text()))
            observed = parse_utc(str(intent.get("intentAtUtc")))
            limit = "restoreUntilUtc" if index >= len(paths) - 2 else "expiresAtUtc"
            if not last_time <= observed < parse_utc(str(approval[limit])):
                raise CampaignError("retained image command window or order differs")
            last_time = observed
            # A lost restoration response is resolved only by the final exact GET.
            # All other successful steps must have their original command result.
            if index != len(paths) - 2 and intents[index][:3] != ["docker", "scout", "cves"]:
                response_path = path.with_name(path.name.replace("-intent.json", "-response.json"))
                response = _object(json.loads(response_path.read_text()))
                uncertain = path.with_name(path.name.replace("-intent.json", "-indeterminate.json"))
                if (
                    type(response.get("exitCode")) is not int
                    or response["exitCode"] != 0
                    or not isinstance(response.get("stdout"), str)
                    or not isinstance(response.get("stderr"), str)
                    or uncertain.exists()
                ):
                    raise CampaignError("retained image successful command result is incomplete")
    return cast(int, receipt["imageBuildCount"])


class _RecordingRunner:
    def __init__(self, run: Callable[[tuple[str, ...]], dict[str, object]]) -> None:
        self._run = run

    def run(self, command: tuple[str, ...]) -> dict[str, object]:
        return self._run(command)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("plan", "approve", "execute"))
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--approval", type=Path)
    parser.add_argument("--registry-before", type=Path)
    parser.add_argument("--retained-image", type=Path)
    parser.add_argument("--egress-ipv4")
    parser.add_argument("--expires-at")
    parser.add_argument("--restore-until")
    parser.add_argument("--cleanup-authorization", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        root = (ROOT / ".runtime" / "milestone_7_8").resolve()
        for path in (
            args.runtime,
            args.config,
            args.ledger,
            args.plan,
            args.approval,
            args.registry_before,
            args.cleanup_authorization,
            args.retained_image,
        ):
            if path is not None and not path.resolve().is_relative_to(root):
                raise CampaignError("image artifacts must remain in the ignored private root")
        runtime = operator.load_runtime(args.runtime)
        if args.retained_image is not None and args.operation != "plan":
            raise CampaignError("retained image selection must be bound by the reviewed plan")
        config = CampaignConfig.from_json(args.config)
        operator.validate_prepared_bundle(args.runtime, runtime, config)
        ledger = load_ledger(args.ledger, config)
        if args.operation == "plan":
            if args.registry_before is None or args.egress_ipv4 is None:
                raise CampaignError("registry baseline and verified egress address are required")
            plan = build_plan(
                runtime,
                config,
                json.loads(args.registry_before.read_text()),
                egress_ipv4=args.egress_ipv4,
                retained_image=args.retained_image,
            )
            _durable_record(args.plan, plan)
        else:
            plan = _object(json.loads(args.plan.read_text()))
            if args.approval is None:
                raise CampaignError("exact separate image approval is required")
            if args.operation == "approve":
                approval = build_approval(
                    plan,
                    issued_at=utc(datetime.now(UTC)),
                    expires_at=args.expires_at,
                    restore_until=args.restore_until,
                )
                validate_inputs(runtime, config, ledger, plan, approval, datetime.now(UTC))
                _durable_record(args.approval, approval)
            else:
                if not args.execute or args.cleanup_authorization is None:
                    raise CampaignError("explicit execution and failure cleanup authority required")
                load_execution_authorization(
                    args.cleanup_authorization, config=config, runtime=runtime, operation="cleanup"
                )
                runner = SubprocessRunner(timeout_seconds=900)
                try:
                    execute_local_image(
                        args.runtime,
                        runtime,
                        config,
                        ledger,
                        plan,
                        _object(json.loads(args.approval.read_text())),
                        output=args.runtime.parent / "local-image",
                        runner=runner,
                        clock=lambda: datetime.now(UTC),
                    )
                except Exception as image_error:
                    # A restored, protected image failure pauses admission. Only
                    # established loss of the private registry boundary or the
                    # existing protection limits require immediate cleanup.
                    cleanup_required = isinstance(image_error, RegistryRestorationUnproved)
                    if not cleanup_required:
                        # Check protection even if the diagnostic/attempt files
                        # are missing. Unknown history blocks replay; it cannot
                        # conceal an exhausted budget or an expired deadline.
                        attempt_sha256 = ""
                        approval_sha256 = ""
                        with suppress(OSError, ValueError, TypeError):
                            attempt_path = args.runtime.parent / "local-image-attempt.json"
                            attempt_sha256 = hashlib.sha256(attempt_path.read_bytes()).hexdigest()
                        with suppress(OSError, ValueError, TypeError):
                            image_approval = _object(json.loads(args.approval.read_text()))
                            approval_sha256 = str(image_approval.get("approvalSha256", ""))
                        try:
                            pause = operator.preserve_protected_stage_failure(
                                "local-image", config, runtime, ledger, args.ledger.parent,
                                attempt_sha256, approval_sha256,
                            )
                            cleanup_required = pause is None
                            if pause is not None:
                                print(json.dumps({
                                    "status": "stage-paused", "operation": "local-image",
                                }))
                        except Exception:
                            # Missing local diagnostics/history is not proof that
                            # healthy infrastructure needs deletion. The existing
                            # attempt barrier and absent scan receipt block replay
                            # and admission; scheduled cleanup remains armed.
                            print(json.dumps({"status": "stage-pause-recording-incomplete"}))
                    if not cleanup_required:
                        raise
                    # The original failure is re-raised if cleanup recording fails.
                    try:
                        def require_cleanup_authority() -> None:
                            load_execution_authorization(
                                args.cleanup_authorization, config=config, runtime=runtime,
                                operation="cleanup",
                            )

                        operator.start_failure_cleanup(
                            runner, config, runtime, before_dispatch=require_cleanup_authority,
                        )
                        ledger.transition(Phase.CLEANING, datetime.now(UTC))
                        save_ledger(args.ledger, ledger)
                    except Exception as cleanup_error:
                        print(
                            json.dumps(
                                {"cleanup": "unconfirmed", "error": type(cleanup_error).__name__}
                            )
                        )
                    raise
    except (CampaignError, OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "blocked", "error": type(exc).__name__}))
        return 2
    print(json.dumps({"status": "passed", "operation": args.operation}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
