"""Validate immutable local build evidence before adopting its exact Docker image."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tarfile
from datetime import datetime
from pathlib import Path
from typing import cast

from infra.milestone_7_8.campaign import CampaignError, parse_utc
from infra.milestone_7_8.canonical_inputs import (
    BUILD_INPUTS,
    CanonicalInputError,
    canonical_snapshot,
)

ROOT = Path(__file__).resolve().parents[2]
PLATFORM = "linux/amd64"
MAX_IMAGE_BYTES = 2 * 1024**3
MAX_DOCUMENT_BYTES = 8 * 1024**2
INDEX = "application/vnd.oci.image.index.v1+json"
MANIFEST = "application/vnd.oci.image.manifest.v1+json"
CONFIG = "application/vnd.oci.image.config.v1+json"
BUILD_STEPS = ("archive", "build", "inspect", "runtime-check", "scout-version", "scout")
SAVE_STEPS = ("retention-inspect", "retention")
SUMMARY_FILES = frozenset(
    {
        "source.tar",
        "source-binding.json",
        "scout.sarif.json",
        *(f"{step}-{kind}.json" for step in BUILD_STEPS for kind in ("intent", "result")),
    }
)
EVIDENCE_FILES = SUMMARY_FILES | {
    "image.docker.tar",
    "retained-image.json",
    "retention-validation.json",
    "validation-summary.json",
    *(f"{step}-{kind}.json" for step in SAVE_STEPS for kind in ("intent", "result")),
}


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise CampaignError("retained image evidence object is malformed")
    return cast(dict[str, object], value)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value = dict(pairs)
    if len(value) != len(pairs):
        raise CampaignError("retained image evidence contains a duplicate JSON key")
    return value


def _json(value: bytes | str) -> object:
    return json.loads(value, object_pairs_hook=_unique_object)


def _objects(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise CampaignError("retained image evidence list is malformed")
    return [_object(item) for item in value]


def _file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _labels(value: object, head: str, canonical: str) -> None:
    labels = _object(value)
    if (
        labels.get("org.opencontainers.image.revision") != head
        or labels.get("mobius.canonical-input-sha256") != canonical
    ):
        raise CampaignError("retained image build labels differ")


def _archive_binding(path: Path, image_id: str, head: str, canonical: str) -> dict[str, object]:
    with tarfile.open(path, "r:") as archive:
        members: dict[str, tarfile.TarInfo] = {}
        blob_count = 0
        for member in archive:
            name = member.name
            if name in members:
                raise CampaignError("retained image archive contains duplicate paths")
            members[name] = member
            if member.isdir() and name in {"blobs", "blobs/sha256"}:
                continue
            if not member.isfile():
                raise CampaignError("retained image archive contains an unsafe entry")
            if name in {"index.json", "manifest.json", "oci-layout"}:
                continue
            if re.fullmatch(r"blobs/sha256/[0-9a-f]{64}", name) is None:
                raise CampaignError("retained image archive contains an unexpected file")
            stream = archive.extractfile(member)
            if stream is None:
                raise CampaignError("retained image archive blob is missing")
            digest = hashlib.sha256()
            while block := stream.read(1024**2):
                digest.update(block)
            if digest.hexdigest() != name[13:]:
                raise CampaignError("retained image archive blob digest differs")
            blob_count += 1

        def read(name: str) -> object:
            member = members[name]
            if not member.isfile() or not 0 < member.size <= MAX_DOCUMENT_BYTES:
                raise CampaignError("retained image archive document has invalid size")
            file = archive.extractfile(member)
            if file is None:
                raise CampaignError("retained image archive document is missing")
            return _json(file.read())

        visited: set[str] = set()

        def descriptor(value: dict[str, object], media: str | None = None) -> str:
            digest = value.get("digest")
            if (
                not isinstance(digest, str)
                or re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None
                or type(value.get("size")) is not int
                or (media is not None and value.get("mediaType") != media)
            ):
                raise CampaignError("retained image archive descriptor is malformed")
            name = "blobs/sha256/" + digest[7:]
            if name not in members or value["size"] != members[name].size:
                raise CampaignError("retained image archive descriptor has missing or wrong bytes")
            visited.add(name)
            return name

        if read("oci-layout") != {"imageLayoutVersion": "1.0.0"}:
            raise CampaignError("retained image archive is not an OCI layout")
        index = _object(read("index.json"))
        roots = _objects(index.get("manifests"))
        if index.get("schemaVersion") != 2 or len(roots) != 1 or roots[0].get("digest") != image_id:
            raise CampaignError("retained archive root differs from the inspected Docker image")
        root = roots[0]
        root_media = root.get("mediaType")
        node = _object(read(descriptor(root)))
        if root_media not in {INDEX, MANIFEST} or node.get("mediaType") != root_media:
            raise CampaignError("retained image archive root media differs")
        attestations: list[dict[str, object]] = []
        if root_media == INDEX:
            children = _objects(node.get("manifests"))
            runtime = [
                child
                for child in children
                if child.get("platform") == {"os": "linux", "architecture": "amd64"}
            ]
            if node.get("schemaVersion") != 2 or len(runtime) != 1:
                raise CampaignError("retained image has no unique Linux/amd64 runtime manifest")
            leaf = runtime[0]
            attestations = [child for child in children if child is not leaf]
        else:
            leaf = root
        manifest = _object(read(descriptor(leaf, MANIFEST)))
        if manifest.get("schemaVersion") != 2 or manifest.get("mediaType") != MANIFEST:
            raise CampaignError("retained image runtime manifest is malformed")
        config = _object(manifest.get("config"))
        config_path = descriptor(config, CONFIG)
        config_value = _object(read(config_path))
        if config_value.get("os") != "linux" or config_value.get("architecture") != "amd64":
            raise CampaignError("retained image config platform differs")
        _labels(_object(config_value.get("config")).get("Labels"), head, canonical)
        layers = [descriptor(layer) for layer in _objects(manifest.get("layers"))]
        if not layers or len(set(layers)) != len(layers):
            raise CampaignError("retained image runtime layer inventory is incomplete")
        for entry in attestations:
            annotations = _object(entry.get("annotations"))
            if (
                entry.get("platform") != {"os": "unknown", "architecture": "unknown"}
                or annotations.get("vnd.docker.reference.type") != "attestation-manifest"
                or annotations.get("vnd.docker.reference.digest") != leaf["digest"]
            ):
                raise CampaignError("retained image includes an unexpected platform")
            attestation = _object(read(descriptor(entry, MANIFEST)))
            if attestation.get("schemaVersion") != 2 or attestation.get("mediaType") != MANIFEST:
                raise CampaignError("retained image attestation manifest is malformed")
            descriptor(_object(attestation.get("config")), CONFIG)
            for layer in _objects(attestation.get("layers")):
                descriptor(layer, "application/vnd.in-toto+json")
        if len(visited) != blob_count:
            raise CampaignError("retained image has unreferenced archive blobs")
        legacy = _objects(read("manifest.json"))
        if legacy != [{"Config": config_path, "RepoTags": None, "Layers": layers}]:
            raise CampaignError("Docker save manifest differs from the verified OCI content")
        return {
            "linuxManifestDigest": leaf["digest"],
            "configDigest": config["digest"],
            "verifiedBlobCount": blob_count,
            "verifiedRuntimeLayerCount": len(layers),
        }


def _load(path: Path, operator_head: str, canonical: str) -> dict[str, object]:
    from infra.milestone_7_8.local_image import _extract_source

    resolved = path.resolve(strict=True)
    private_root = (ROOT / ".runtime" / "milestone_7_8").resolve()
    if (
        resolved != path.absolute()
        or path.is_symlink()
        or not resolved.is_relative_to(private_root)
        or resolved.name != "retained-image.json"
    ):
        raise CampaignError("retained image evidence must use its exact private path")
    folder = resolved.parent
    documents: dict[str, object] = {}
    hashes: dict[str, str] = {}
    for name in sorted(EVIDENCE_FILES):
        file = folder / name
        if file.is_symlink() or file.resolve(strict=True) != file or not file.is_file():
            raise CampaignError("retained image evidence file is invalid")
        if name.endswith(".json"):
            if file.stat().st_size > MAX_DOCUMENT_BYTES:
                raise CampaignError("retained image evidence document is oversized")
            content = file.read_bytes()
            hashes[name] = hashlib.sha256(content).hexdigest()
            documents[name] = _json(content)
        else:
            if not 0 < file.stat().st_size <= MAX_IMAGE_BYTES:
                raise CampaignError("retained image archive is missing or oversized")
            hashes[name] = _file_hash(file)

    retained = _object(documents["retained-image.json"])
    summary = _object(documents["validation-summary.json"])
    source = _object(documents["source-binding.json"])
    saved = _object(documents["retention-validation.json"])
    head, image_id, tag, size = (
        retained.get("sourceHead"),
        retained.get("imageId"),
        summary.get("imageTag"),
        summary.get("imageBytes"),
    )
    if (
        not isinstance(head, str)
        or re.fullmatch(r"[0-9a-f]{40}", head) is None
        or not isinstance(image_id, str)
        or re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) is None
        or not isinstance(tag, str)
        or re.fullmatch(r"[a-z0-9][a-z0-9._-]*:[a-z0-9._-]+", tag) is None
        or type(size) is not int
        or not 0 < size <= MAX_IMAGE_BYTES
    ):
        raise CampaignError("retained image identity is malformed")
    snapshot = canonical_snapshot(head)
    if (
        snapshot != canonical_snapshot(operator_head)
        or snapshot.get("buildInputSha256") != canonical
    ):
        raise CampaignError("retained build and operator commits have different canonical inputs")
    bindings = {
        "sourceHead": head,
        "platform": PLATFORM,
        "canonicalBuildInputSha256": canonical,
        "imageId": image_id,
    }
    if retained != {
        **bindings,
        "classification": "retained-local-image-not-campaign-admission",
        "archiveBytes": (folder / "image.docker.tar").stat().st_size,
        "archiveSha256": hashes["image.docker.tar"],
        "sarifSha256": hashes["scout.sarif.json"],
        "validationSummarySha256": hashes["validation-summary.json"],
    }:
        raise CampaignError("retained image archive or validation hash differs")
    if source != {
        "classification": "local-remediation-not-campaign-admission",
        "sourceHead": head,
        "canonicalInputs": snapshot,
        "sourceArchiveSha256": hashes["source.tar"],
        "platform": PLATFORM,
        "azureOperations": 0,
    }:
        raise CampaignError("retained image source binding differs")
    if summary != {
        **bindings,
        "classification": "local-remediation-validation-not-campaign-admission",
        "imageTag": tag,
        "imageBytes": size,
        "completedAtUtc": summary.get("completedAtUtc"),
        "scanExitCode": 0,
        "sarifResultCount": 0,
        "zeroHighCriticalEstablished": True,
        "runtimeChecksPassed": True,
        "azureOperations": 0,
        "reportSha256": hashes["scout.sarif.json"],
        "filesSha256": {name: hashes[name] for name in SUMMARY_FILES},
    }:
        raise CampaignError("retained image validation inventory or results differ")

    tree = subprocess.run(
        ("git", "ls-tree", "-r", "--full-tree", head, "--", *BUILD_INPUTS),
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    ).stdout
    _extract_source(folder / "source.tar", folder / "source", tree, canonical, extract=False)
    oci = _archive_binding(folder / "image.docker.tar", image_id, head, canonical)
    if saved != {
        **oci,
        "imageId": image_id,
        "status": "passed",
        "sourceAndCanonicalLabelsMatch": True,
        "completedAtUtc": saved.get("completedAtUtc"),
    }:
        raise CampaignError("retained Docker archive validation result differs")

    commands = {
        "archive": [
            "git",
            "-c",
            "core.autocrlf=false",
            "-c",
            "core.eol=lf",
            "archive",
            "--format=tar",
            f"--output={folder / 'source.tar'}",
            head,
            "--",
            *BUILD_INPUTS,
        ],
        "build": [
            "docker",
            "build",
            "--platform",
            PLATFORM,
            "--file",
            str(folder / "source" / "apps" / "api" / "Dockerfile"),
            "--label",
            f"org.opencontainers.image.revision={head}",
            "--label",
            f"mobius.canonical-input-sha256={canonical}",
            "--tag",
            tag,
            str(folder / "source"),
        ],
        "inspect": ["docker", "image", "inspect", tag],
        "scout-version": ["docker", "scout", "version"],
        "scout": [
            "docker",
            "scout",
            "cves",
            f"local://{image_id}",
            "--platform",
            PLATFORM,
            "--only-severity",
            "critical,high",
            "--exit-code",
            "--format",
            "sarif",
            "--output",
            str(folder / "scout.sarif.json"),
        ],
        "retention-inspect": ["docker", "image", "inspect", image_id],
        "retention": [
            "docker",
            "image",
            "save",
            "--output",
            str(folder / "image.docker.tar"),
            image_id,
        ],
    }
    last: datetime | None = None
    for step in (*BUILD_STEPS, *SAVE_STEPS):
        intent = _object(documents[f"{step}-intent.json"])
        outcome = _object(documents[f"{step}-result.json"])
        command, start = intent.get("command"), intent.get("startedAtUtc")
        end = outcome.get("completedAtUtc")
        if (
            set(intent) != {"command", "startedAtUtc"}
            or set(outcome) != {"exitCode", "stdout", "stderr", "completedAtUtc"}
            or type(outcome.get("exitCode")) is not int
            or outcome["exitCode"] != 0
            or not isinstance(outcome.get("stdout"), str)
            or not isinstance(outcome.get("stderr"), str)
            or not isinstance(start, str)
            or not isinstance(end, str)
            or (last is not None and parse_utc(start) < last)
            or parse_utc(end) < parse_utc(start)
        ):
            raise CampaignError("retained image command history is unsuccessful or out of order")
        last = parse_utc(end)
        if step == "runtime-check":
            if (
                not isinstance(command, list)
                or len(command) != 16
                or command[:15]
                != [
                    "docker",
                    "run",
                    "--rm",
                    "--network",
                    "none",
                    "--read-only",
                    "--tmpfs",
                    "/tmp:rw,noexec,nosuid,size=64m",
                    "--cap-drop",
                    "ALL",
                    "--security-opt",
                    "no-new-privileges",
                    image_id,
                    "python",
                    "-c",
                ]
                or not isinstance(command[15], str)
            ):
                raise CampaignError("retained runtime smoke check command differs")
        elif command != commands[step]:
            raise CampaignError("retained image command binding differs")

    for step in ("inspect", "retention-inspect"):
        rows = _objects(_json(cast(str, _object(documents[f"{step}-result.json"])["stdout"])))
        if len(rows) != 1:
            raise CampaignError("retained image inspect result is not unique")
        image = rows[0]
        if (
            image.get("Id") != image_id
            or image.get("Size") != size
            or image.get("Os") != "linux"
            or image.get("Architecture") != "amd64"
            or _object(image.get("Descriptor")).get("digest") != image_id
        ):
            raise CampaignError("retained image inspect result differs")
        _labels(_object(image.get("Config")).get("Labels"), head, canonical)
    build = _object(documents["build-result.json"])
    build_trace = f"{build['stdout']}\n{build['stderr']}"
    for digest in (image_id, oci["linuxManifestDigest"], oci["configDigest"]):
        if f"exporting manifest {digest}" not in build_trace and not any(
            f"exporting {kind} {digest}" in build_trace for kind in ("manifest list", "config")
        ):
            raise CampaignError("retained build result does not name the exported digests")
    sarif = _object(documents["scout.sarif.json"])
    runs = _objects(sarif.get("runs"))
    if sarif.get("version") != "2.1.0" or not runs or any(run.get("results") != [] for run in runs):
        raise CampaignError("retained Docker Scout assessment is incomplete or contains findings")
    return {
        "imageId": image_id,
        "imageBuildSourceHead": head,
        "canonicalBuildInputSha256": canonical,
        "platform": PLATFORM,
        "runtimeManifestDigest": oci["linuxManifestDigest"],
        "provenanceFile": str(resolved),
        "filesSha256": hashes,
    }


def load_retained_image(
    path: Path,
    *,
    operator_head: str,
    canonical_input_sha256: str,
) -> dict[str, object]:
    """Return the exact retained image and provenance files bound into approval."""
    try:
        return _load(path, operator_head, canonical_input_sha256)
    except (
        OSError,
        TypeError,
        ValueError,
        KeyError,
        tarfile.TarError,
        subprocess.SubprocessError,
        CanonicalInputError,
    ) as exc:
        raise CampaignError("retained image provenance cannot be read or verified") from exc
