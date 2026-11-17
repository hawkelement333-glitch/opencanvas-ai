from __future__ import annotations

import hashlib
import io
import zipfile

import pytest
from infra.milestone_7_8.pilot.artifact_transport import (
    checked_source_zip,
    checked_zip,
    stage_artifact,
)
from infra.milestone_7_8.pilot.pack_execution import archive


def test_lossless_inline_compression_preserves_exact_artifact_and_existing_bounds(monkeypatch):
    entries = {
        "infra/module.py": b"def measured_operation():\n    return 'exact bytes'\n" * 1000,
        "package/manifest.json": b'{"sourceBindings":{"immutable":"binding"}}',
        "opaque.bin": bytes(range(256)) * 100,
    }
    source = archive(entries, compressed=True)
    assert source == archive(entries, compressed=True)
    with zipfile.ZipFile(io.BytesIO(source)) as opened:
        assert all(row.compress_type == zipfile.ZIP_LZMA for row in opened.infolist())
    decoded = checked_source_zip(source, hashlib.sha256(source).hexdigest())
    assert decoded == entries
    assert archive(decoded) == archive(entries)
    with pytest.raises(ValueError, match="hash or byte bound"):
        checked_zip(source, "0" * 64)
    with pytest.raises(ValueError, match="hash or byte bound"):
        checked_zip(b"x" * 2_000_001, hashlib.sha256(b"x" * 2_000_001).hexdigest())
    # Keep the independent inline transport bound; rejection occurs before I/O.
    monkeypatch.setenv("M78_PILOT_SOURCE_CHUNKS", "8")
    for index in range(8):
        monkeypatch.setenv(f"M78_PILOT_SOURCE_CHUNK_{index}", "A" * 31_000)
    with pytest.raises(ValueError, match="reviewed transport bound"):
        stage_artifact()


@pytest.mark.parametrize("case", ["extra-outer", "recursive", "unsafe-inner", "oversize-inner"])
def test_solid_source_rejects_ambiguous_recursive_unsafe_and_oversize_inputs(case):
    if case == "extra-outer":
        raw = archive({"source-entries.zip": archive({"valid.py": b"pass"}), "extra": b"x"})
    elif case == "recursive":
        raw = archive({"source-entries.zip": archive({"valid.py": b"pass"})}, compressed=True)
    elif case == "unsafe-inner":
        raw = archive({"../outside.py": b"pass"}, compressed=True)
    else:
        raw = archive({"large.py": b"x" * 2_000_001}, compressed=True)
    with pytest.raises(ValueError):
        checked_source_zip(raw, hashlib.sha256(raw).hexdigest())
