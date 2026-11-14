from __future__ import annotations

import hashlib
import io
import json
import subprocess
import tarfile
from pathlib import Path

import pytest

from infra.milestone_7_8 import canonical_inputs, retained_image
from infra.milestone_7_8.campaign import CampaignError
from infra.milestone_7_8.local_image import ARCHIVE_OPTIONS


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout.strip()


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


@pytest.fixture
def provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, str, str, str, str, str]:
    root = tmp_path.resolve()
    monkeypatch.setattr(retained_image, "ROOT", root)
    monkeypatch.setattr(canonical_inputs, "REPOSITORY_ROOT", root)
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "fixture")
    _git(root, "config", "user.email", "fixture@example.invalid")
    _git(root, "config", "commit.gpgSign", "false")
    for name in canonical_inputs.BUILD_INPUTS:
        path = root / name
        if name in {"apps/api/opencanvas_api", "apps/api/alembic", "apps/api/scripts"}:
            path /= "fixture.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("canonical fixture\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "build inputs")
    build_head = _git(root, "rev-parse", "HEAD")
    snapshot = canonical_inputs.canonical_snapshot(build_head)
    canonical = str(snapshot["buildInputSha256"])
    (root / "operator.py").write_text("operator change\n", encoding="utf-8")
    _git(root, "add", "operator.py")
    _git(root, "commit", "-qm", "operator-only change")
    operator_head = _git(root, "rev-parse", "HEAD")
    folder = root / ".runtime" / "milestone_7_8" / "retained"
    folder.mkdir(parents=True)
    archive = folder / "source.tar"
    archive_args = [
        *ARCHIVE_OPTIONS,
        "archive",
        "--format=tar",
        f"--output={archive}",
        build_head,
        "--",
        *canonical_inputs.BUILD_INPUTS,
    ]
    _git(root, *archive_args)

    labels = {
        "org.opencontainers.image.revision": build_head,
        "mobius.canonical-input-sha256": canonical,
    }
    members: dict[str, bytes] = {}

    def blob(media: str, value: object) -> dict[str, object]:
        raw = json.dumps(value, sort_keys=True).encode()
        digest = hashlib.sha256(raw).hexdigest()
        members[f"blobs/sha256/{digest}"] = raw
        return {"mediaType": media, "digest": f"sha256:{digest}", "size": len(raw)}

    config = blob(
        retained_image.CONFIG,
        {
            "os": "linux",
            "architecture": "amd64",
            "config": {"Labels": labels},
        },
    )
    layer = blob("application/vnd.oci.image.layer.v1.tar+gzip", {"layer": "fixture"})
    manifest = {
        "schemaVersion": 2,
        "mediaType": retained_image.MANIFEST,
        "config": config,
        "layers": [layer],
    }
    child = blob(retained_image.MANIFEST, manifest)
    image = blob(
        retained_image.INDEX,
        {
            "schemaVersion": 2,
            "mediaType": retained_image.INDEX,
            "manifests": [{**child, "platform": {"os": "linux", "architecture": "amd64"}}],
        },
    )
    image_id = str(image["digest"])
    manifest_digest = str(child["digest"])
    members["index.json"] = json.dumps({"schemaVersion": 2, "manifests": [image]}).encode()
    members["oci-layout"] = b'{"imageLayoutVersion":"1.0.0"}'
    members["manifest.json"] = json.dumps(
        [
            {
                "Config": "blobs/sha256/" + str(config["digest"])[7:],
                "RepoTags": None,
                "Layers": ["blobs/sha256/" + str(layer["digest"])[7:]],
            }
        ]
    ).encode()
    image_archive = folder / "image.docker.tar"
    with tarfile.open(image_archive, "w") as out:
        for name, content in members.items():
            entry = tarfile.TarInfo(name)
            entry.size = len(content)
            out.addfile(entry, io.BytesIO(content))

    observed_at = "2026-11-14T00:00:00Z"
    tag = "fixture:retained"
    platform = retained_image.PLATFORM
    commands = {
        "archive": ["git", *archive_args],
        "build": [
            "docker",
            "build",
            "--platform",
            platform,
            "--file",
            str(folder / "source" / "apps" / "api" / "Dockerfile"),
            "--label",
            f"org.opencontainers.image.revision={build_head}",
            "--label",
            f"mobius.canonical-input-sha256={canonical}",
            "--tag",
            tag,
            str(folder / "source"),
        ],
        "inspect": ["docker", "image", "inspect", tag],
        "runtime-check": [
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
            "print('fixture')",
        ],
        "scout-version": ["docker", "scout", "version"],
        "scout": [
            "docker",
            "scout",
            "cves",
            f"local://{image_id}",
            "--platform",
            platform,
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
            str(image_archive),
            image_id,
        ],
    }
    inspect = json.dumps(
        [
            {
                "Id": image_id,
                "Size": 100,
                "Os": "linux",
                "Architecture": "amd64",
                "Config": {"Labels": labels},
                "Descriptor": image,
            }
        ]
    )
    for step, command in commands.items():
        _write(folder / f"{step}-intent.json", {"command": command, "startedAtUtc": observed_at})
        _write(
            folder / f"{step}-result.json",
            {
                "exitCode": 0,
                "stdout": inspect if "inspect" in step else "",
                "stderr": (
                    f"exporting manifest {manifest_digest}\n"
                    f"exporting config {config['digest']}\nexporting manifest list {image_id}"
                    if step == "build"
                    else ""
                ),
                "completedAtUtc": observed_at,
            },
        )
    sarif = folder / "scout.sarif.json"
    _write(sarif, {"version": "2.1.0", "runs": [{"results": []}]})
    _write(
        folder / "source-binding.json",
        {
            "classification": "local-remediation-not-campaign-admission",
            "sourceHead": build_head,
            "canonicalInputs": snapshot,
            "sourceArchiveSha256": _hash(archive),
            "platform": platform,
            "azureOperations": 0,
        },
    )
    summary = folder / "validation-summary.json"
    _write(
        summary,
        {
            "canonicalBuildInputSha256": canonical,
            "classification": "local-remediation-validation-not-campaign-admission",
            "completedAtUtc": observed_at,
            "imageBytes": 100,
            "imageId": image_id,
            "imageTag": tag,
            "platform": platform,
            "reportSha256": _hash(sarif),
            "runtimeChecksPassed": True,
            "sarifResultCount": 0,
            "scanExitCode": 0,
            "sourceHead": build_head,
            "zeroHighCriticalEstablished": True,
            "azureOperations": 0,
            "filesSha256": {name: _hash(folder / name) for name in retained_image.SUMMARY_FILES},
        },
    )
    _write(
        folder / "retention-validation.json",
        {
            "completedAtUtc": observed_at,
            "configDigest": config["digest"],
            "imageId": image_id,
            "linuxManifestDigest": manifest_digest,
            "sourceAndCanonicalLabelsMatch": True,
            "status": "passed",
            "verifiedBlobCount": 4,
            "verifiedRuntimeLayerCount": 1,
        },
    )
    record = folder / "retained-image.json"
    _write(
        record,
        {
            "archiveBytes": image_archive.stat().st_size,
            "archiveSha256": _hash(image_archive),
            "canonicalBuildInputSha256": canonical,
            "classification": "retained-local-image-not-campaign-admission",
            "imageId": image_id,
            "platform": platform,
            "sarifSha256": _hash(sarif),
            "sourceHead": build_head,
            "validationSummarySha256": _hash(summary),
        },
    )
    return record, build_head, operator_head, canonical, image_id, manifest_digest


def test_exact_retained_build_can_bind_new_operator_head(
    provenance: tuple[Path, str, str, str, str, str],
) -> None:
    record, build, operator, canonical, image, manifest = provenance
    bound = retained_image.load_retained_image(
        record,
        operator_head=operator,
        canonical_input_sha256=canonical,
    )
    assert build != operator
    assert bound == {
        "imageId": image,
        "imageBuildSourceHead": build,
        "canonicalBuildInputSha256": canonical,
        "platform": "linux/amd64",
        "runtimeManifestDigest": manifest,
        "provenanceFile": str(record),
        "filesSha256": {
            name: _hash(record.parent / name) for name in retained_image.EVIDENCE_FILES
        },
    }


def test_retained_build_rejects_changed_canonical_commit(
    provenance: tuple[Path, str, str, str, str, str],
    tmp_path: Path,
) -> None:
    record, _, _, canonical, _, _ = provenance
    (tmp_path / "apps/api/Dockerfile").write_text("changed\n", encoding="utf-8")
    _git(tmp_path, "add", "apps/api/Dockerfile")
    _git(tmp_path, "commit", "-qm", "changed input")
    with pytest.raises(CampaignError, match="different canonical inputs"):
        retained_image.load_retained_image(
            record,
            operator_head=_git(tmp_path, "rev-parse", "HEAD"),
            canonical_input_sha256=canonical,
        )


@pytest.mark.parametrize("fault", ["missing-result", "failed-result", "changed-blob"])
def test_retained_provenance_rejects_inconsistent_raw_evidence(
    provenance: tuple[Path, str, str, str, str, str],
    fault: str,
) -> None:
    record, _, operator, canonical, _, _ = provenance
    folder = record.parent
    details = json.loads(record.read_bytes())
    summary = folder / "validation-summary.json"
    if fault == "missing-result":
        (folder / "build-result.json").unlink()
        match = "cannot be read or verified"
    elif fault == "failed-result":
        build = folder / "build-result.json"
        outcome = json.loads(build.read_bytes())
        outcome["exitCode"] = 1
        _write(build, outcome)
        report = json.loads(summary.read_bytes())
        report["filesSha256"]["build-result.json"] = _hash(build)
        _write(summary, report)
        details["validationSummarySha256"] = _hash(summary)
        _write(record, details)
        match = "history is unsuccessful"
    else:
        archive = folder / "image.docker.tar"
        with tarfile.open(archive) as saved:
            member = next(item for item in saved if item.name.startswith("blobs/sha256/"))
        with archive.open("r+b") as stream:
            stream.seek(member.offset_data)
            stream.write(b"!")
        details["archiveSha256"] = _hash(archive)
        _write(record, details)
        match = "archive blob digest differs"
    with pytest.raises(CampaignError, match=match):
        retained_image.load_retained_image(
            record,
            operator_head=operator,
            canonical_input_sha256=canonical,
        )
