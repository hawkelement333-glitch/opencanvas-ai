from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Final, cast

REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[2]
BUILD_INPUTS: Final = (
    "apps/api/Dockerfile",
    "apps/api/Dockerfile.dockerignore",
    "apps/api/pyproject.toml",
    "apps/api/build-requirements.lock",
    "apps/api/requirements.lock",
    "apps/api/opencanvas_api",
    "apps/api/alembic.ini",
    "apps/api/alembic",
    "apps/api/scripts",
    "LICENSE",
    "COPYRIGHT",
    "NOTICE",
    "THIRD_PARTY_NOTICES.md",
)
DOMAIN: Final = b"solarplexus-mobius/canonical-api-image-build-input/v1\0"
TREEISH = re.compile(r"^[a-f0-9]{40}$")


class CanonicalInputError(RuntimeError):
    pass


def _git(*arguments: str, binary: bool = False) -> str | bytes:
    completed = subprocess.run(
        ("git", *arguments),
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=not binary,
    )
    if completed.returncode != 0:
        raise CanonicalInputError("canonical Git input read failed")
    return cast(str | bytes, completed.stdout)


def canonical_snapshot(treeish: str) -> dict[str, object]:
    if TREEISH.fullmatch(treeish) is None:
        raise CanonicalInputError("canonical tree identity is invalid")
    raw = str(_git("ls-tree", "-r", "--full-tree", treeish, "--", *BUILD_INPUTS))
    entries: list[dict[str, str]] = []
    for line in raw.splitlines():
        match = re.fullmatch(r"(100644|100755|120000) blob ([a-f0-9]{40})\t([^\x00\r\n]+)", line)
        if match is None:
            raise CanonicalInputError("canonical tree entry is malformed")
        entries.append({"mode": match.group(1), "object": match.group(2), "path": match.group(3)})
    observed = {entry["path"] for entry in entries}
    for relative in BUILD_INPUTS:
        candidate = REPOSITORY_ROOT / relative
        if candidate.is_file() and relative not in observed:
            raise CanonicalInputError("canonical file input is absent")
        if candidate.is_dir() and not any(path.startswith(relative + "/") for path in observed):
            raise CanonicalInputError("canonical directory input is absent")
    payload = {"inputs": list(BUILD_INPUTS), "treeEntries": entries}
    canonical = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()

    def content_hash(relative: str) -> str:
        content = _git("show", f"{treeish}:{relative}", binary=True)
        if not isinstance(content, bytes):
            raise CanonicalInputError("canonical content read is malformed")
        return hashlib.sha256(content).hexdigest()

    return {
        "version": "m7.8-canonical-api-image-input-v1",
        "inputs": list(BUILD_INPUTS),
        "buildInputSha256": hashlib.sha256(DOMAIN + canonical).hexdigest(),
        "dockerfileSha256": content_hash("apps/api/Dockerfile"),
        "dependencyHashes": {
            path: content_hash(path)
            for path in (
                "apps/api/pyproject.toml",
                "apps/api/build-requirements.lock",
                "apps/api/requirements.lock",
            )
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Canonical API image input inventory")
    parser.add_argument("--treeish", default="HEAD")
    args = parser.parse_args()
    try:
        treeish = str(_git("rev-parse", args.treeish)).strip()
        print(json.dumps(canonical_snapshot(treeish), separators=(",", ":"), sort_keys=True))
        return 0
    except CanonicalInputError as exc:
        print(
            json.dumps({"status": "blocked", "error": str(exc)}, sort_keys=True),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
