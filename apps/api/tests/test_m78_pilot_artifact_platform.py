"""The host and job reconstruct byte-identical signed-input probe archives."""

import base64
import hashlib
import io
import json
import zipfile
from types import SimpleNamespace

from infra.milestone_7_8.pilot import artifact_transport, pack_execution


def test_staging_reconstructs_the_host_archive_with_stable_zip_metadata(monkeypatch):
    class WindowsZipInfo(zipfile.ZipInfo):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.create_system = 0

    monkeypatch.setattr(zipfile, "ZipInfo", WindowsZipInfo)
    wheel_bytes = {}
    wheels = []
    for index in range(8):
        name = f"fixture{index}-1.0-py3-none-any.whl"
        data = f"fixed test bytes {index}".encode()
        wheel_bytes[name] = data
        wheels.append(
            {
                "name": name,
                "url": f"https://files.pythonhosted.org/packages/{name}",
                "sha256": hashlib.sha256(data).hexdigest(),
                "size": len(data),
            }
        )
    source_entries = {"wheel-manifest.json": json.dumps({"wheels": wheels}).encode()}
    source = pack_execution.archive(source_entries, compressed=True)
    expected = pack_execution.archive(
        {**source_entries, **{f"wheels/{name}": data for name, data in wheel_bytes.items()}}
    )
    with zipfile.ZipFile(io.BytesIO(expected)) as raw:
        assert {item.create_system for item in raw.infolist()} == {3}

    uploaded = []

    class LocalClient:
        def __init__(self, **kwargs):
            assert kwargs["trust_env"] is False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url):
            return SimpleNamespace(
                content=wheel_bytes[url.rsplit("/", 1)[-1]],
                raise_for_status=lambda: None,
            )

        def put(self, url, *, content, headers):
            uploaded.append((content, headers["If-None-Match"]))
            return SimpleNamespace(status_code=201, headers={"x-ms-version-id": "test"})

    monkeypatch.setattr(artifact_transport.httpx, "Client", LocalClient)
    monkeypatch.setattr(artifact_transport, "token", lambda: "fixture-only")
    monkeypatch.setenv("M78_PILOT_SOURCE_CHUNKS", "1")
    monkeypatch.setenv("M78_PILOT_SOURCE_CHUNK_0", base64.b64encode(source).decode())
    monkeypatch.setenv("M78_PILOT_SOURCE_ZIP_SHA256", hashlib.sha256(source).hexdigest())
    monkeypatch.setenv("M78_PILOT_ARTIFACT_SHA256", hashlib.sha256(expected).hexdigest())
    suffix = "0123456789"
    monkeypatch.setenv("M78_PILOT_SUFFIX", suffix)
    monkeypatch.setenv("M78_PILOT_STORAGE_HOST", f"stm78o{suffix}.blob.core.windows.net")
    artifact_transport.stage_artifact()
    assert uploaded == [(expected, "*")]
