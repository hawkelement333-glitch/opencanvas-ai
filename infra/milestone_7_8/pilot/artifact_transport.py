"""Hash-bound transport for an isolated private probe; no package installation."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import runpy
import sys
from urllib.parse import quote, urlparse
import zipfile

import httpx


def checked_zip(raw: bytes, expected: str) -> dict[str, bytes]:
    if len(raw) > 2_000_000 or hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("artifact hash or byte bound mismatch")
    result = {}
    total = 0
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        for info in archive.infolist():
            path = PurePosixPath(info.filename)
            if (
                ":" in info.filename
                or path.is_absolute()
                or ".." in path.parts
                or "\\" in info.filename
                or info.filename in result
            ):
                raise ValueError("unsafe or duplicate artifact path")
            total += info.file_size
            if total > 32_000_000 or info.is_dir():
                raise ValueError("artifact expansion exceeds bound")
            result[info.filename] = archive.read(info)
    return result


def checked_source_zip(raw: bytes, expected: str) -> dict[str, bytes]:
    """Unwrap exactly one source layer without weakening either ZIP bound."""
    wrapper = checked_zip(raw, expected)
    if set(wrapper) != {"source-entries.zip"}:
        raise ValueError("exact solid source wrapper required")
    inner = wrapper["source-entries.zip"]
    # The verified outer digest binds these exact inner bytes transitively.
    entries = checked_zip(inner, hashlib.sha256(inner).hexdigest())
    if "source-entries.zip" in entries:
        raise ValueError("recursive source wrapper rejected")
    return entries


def artifact_url() -> str:
    host = os.environ["M78_PILOT_STORAGE_HOST"]
    suffix = os.environ["M78_PILOT_SUFFIX"]
    if len(suffix) != 10 or any(c not in "0123456789abcdef" for c in suffix):
        raise ValueError("isolated suffix required")
    if host != f"stm78o{suffix}.blob.core.windows.net":
        raise ValueError("artifact storage outside isolated scope")
    return f"https://{host}/operational-artifacts/{os.environ['M78_PILOT_ARTIFACT_SHA256']}.zip"


def token() -> str:
    endpoint = os.environ["IDENTITY_ENDPOINT"]
    parsed = urlparse(endpoint)
    if parsed.scheme != "http" or parsed.hostname not in {
        "127.0.0.1",
        "localhost",
        "169.254.169.254",
    }:
        raise ValueError("unexpected managed identity endpoint")
    with httpx.Client(timeout=15, trust_env=False, follow_redirects=False) as client:
        response = client.get(
            endpoint,
            params={
                "api-version": "2019-08-01",
                "resource": "https://storage.azure.com/",
                "client_id": os.environ["AZURE_CLIENT_ID"],
            },
            headers={"X-IDENTITY-HEADER": os.environ["IDENTITY_HEADER"]},
        )
        response.raise_for_status()
        return response.json()["access_token"]


def stage_artifact() -> None:
    count = int(os.environ["M78_PILOT_SOURCE_CHUNKS"])
    if not 1 <= count <= 8:
        raise ValueError("source chunk count exceeds bound")
    chunks = [os.environ[f"M78_PILOT_SOURCE_CHUNK_{i}"] for i in range(count)]
    if any(len(chunk) > 32768 for chunk in chunks) or sum(map(len, chunks)) > 240000:
        raise ValueError("source chunks exceed reviewed transport bound")
    source = base64.b64decode("".join(chunks), validate=True)
    entries = checked_source_zip(source, os.environ["M78_PILOT_SOURCE_ZIP_SHA256"])
    wheels = json.loads(entries["wheel-manifest.json"])["wheels"]
    if len(wheels) != 8:
        raise ValueError("exact wheel inventory required")
    with httpx.Client(timeout=30, follow_redirects=False, trust_env=False) as client:
        for wheel in wheels:
            parsed = urlparse(wheel["url"])
            if (
                parsed.scheme != "https"
                or parsed.hostname != "files.pythonhosted.org"
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("wheel origin is not approved")
            name = wheel["name"]
            if Path(name).name != name or not name.endswith("-py3-none-any.whl"):
                raise ValueError("universal wheel required")
            response = client.get(wheel["url"])
            response.raise_for_status()
            data = response.content
            if (
                len(data) != wheel["size"]
                or hashlib.sha256(data).hexdigest() != wheel["sha256"]
            ):
                raise ValueError("wheel binding mismatch")
            entries["wheels/" + name] = data
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as output:
        for name, data in sorted(entries.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.create_system = 3
            output.writestr(info, data)
    raw = stream.getvalue()
    expected = os.environ["M78_PILOT_ARTIFACT_SHA256"]
    checked_zip(raw, expected)
    with httpx.Client(timeout=30, trust_env=False, follow_redirects=False) as client:
        response = client.put(
            artifact_url(),
            content=raw,
            headers={
                "Authorization": "Bearer " + token(),
                "x-ms-version": "2023-11-03",
                "x-ms-blob-type": "BlockBlob",
                "If-None-Match": "*",
            },
        )
        # A 412 or uncertain write requires exact-version readback reconciliation.
        if response.status_code != 201 or not response.headers.get("x-ms-version-id"):
            raise ValueError("artifact staging requires reconciliation")
        print(
            json.dumps(
                {
                    "sha256": expected,
                    "bytes": len(raw),
                    "versionId": response.headers["x-ms-version-id"],
                }
            )
        )


def load_probe() -> None:
    version = os.environ["M78_PILOT_ARTIFACT_VERSION_ID"]
    with httpx.Client(timeout=30, trust_env=False, follow_redirects=False) as client:
        response = client.get(
            artifact_url() + "?versionid=" + quote(version, safe=""),
            headers={
                "Authorization": "Bearer " + token(),
                "x-ms-version": "2023-11-03",
            },
        )
        response.raise_for_status()
        if response.headers.get("x-ms-version-id") != version:
            raise ValueError("artifact version changed")
        entries = checked_zip(response.content, os.environ["M78_PILOT_ARTIFACT_SHA256"])
    root = Path("/tmp/m78-proof")
    root.mkdir(exist_ok=False)
    for name, data in entries.items():
        destination = root / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    sys.path.insert(0, str(root))
    overlay = root / "sdk"
    overlay.mkdir()
    for wheel in sorted((root / "wheels").glob("*.whl")):
        raw = wheel.read_bytes()
        for name, data in checked_zip(raw, hashlib.sha256(raw).hexdigest()).items():
            destination = overlay / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists() and destination.read_bytes() != data:
                raise ValueError("conflicting SDK module")
            destination.write_bytes(data)
    sys.path.insert(0, str(overlay))
    module = os.environ["M78_PILOT_MODULE"]
    if module not in {
        "infra.milestone_7_8.pilot_validation",
        "infra.milestone_7_8.pilot_application_probe",
        "infra.milestone_7_8.password_reset_validation",
        "infra.milestone_7_8.activity_delivery_validation",
        "infra.milestone_7_8.queue_grant_intervention",
    }:
        raise ValueError("unapproved probe module")
    sys.argv = [
        module,
        *[
            os.environ["CONTAINER_APP_JOB_EXECUTION_NAME"]
            if item == "${EXECUTION_ID}"
            else item
            for item in json.loads(os.environ["M78_PILOT_ARGUMENTS_JSON"])
        ],
    ]
    try:
        runpy.run_module(module, run_name="__main__")
    finally:
        export_evidence()


def export_evidence() -> None:
    evidence = Path("/tmp/m78-evidence")
    files = sorted(path for path in evidence.rglob("*") if path.is_file())
    if len(files) > 2000 or sum(path.stat().st_size for path in files) > 32_000_000:
        raise ValueError("evidence export exceeds reviewed bound")
    execution = os.environ["CONTAINER_APP_JOB_EXECUTION_NAME"]
    if not execution or any(
        char not in "abcdefghijklmnopqrstuvwxyz0123456789-" for char in execution
    ):
        raise ValueError("native execution ID required")
    base = (
        artifact_url().split("/operational-artifacts/", 1)[0]
        + "/operational-evidence/"
        + execution
        + "/"
    )
    records = []
    with httpx.Client(timeout=30, trust_env=False, follow_redirects=False) as client:
        headers = {
            "Authorization": "Bearer " + token(),
            "x-ms-version": "2023-11-03",
            "x-ms-blob-type": "BlockBlob",
            "If-None-Match": "*",
        }
        for path in files:
            data = path.read_bytes()
            relative = path.relative_to(evidence).as_posix()
            response = client.put(
                base + quote(relative, safe="/"), content=data, headers=headers
            )
            if response.status_code != 201:
                raise ValueError("export outcome must be reconciled before retry")
            records.append(
                {
                    "path": relative,
                    "bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "versionId": response.headers.get("x-ms-version-id"),
                }
            )
        manifest = json.dumps(
            {"executionId": execution, "files": records}, sort_keys=True
        ).encode()
        response = client.put(
            base + "export-manifest.json", content=manifest, headers=headers
        )
        if response.status_code != 201:
            raise ValueError("manifest export must be reconciled")
        print(
            json.dumps(
                {
                    "executionId": execution,
                    "exportManifestSha256": hashlib.sha256(manifest).hexdigest(),
                    "files": len(files),
                }
            )
        )
