"""Checksum one non-sensitive Milestone 7.7 JSON manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from contract_validation import (
    ContractError,
    canonical_json_bytes,
    load_json,
    manifest_sha256,
    validate_manifest,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--bundle-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        value = load_json(args.input)
        kind, version = validate_manifest(args.bundle_root, value)
        canonical = canonical_json_bytes(value)
        digest = manifest_sha256(kind, version, value)
    except ContractError as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}, sort_keys=True))
        return 2
    print(
        json.dumps(
            {
                "canonicalByteCount": len(canonical),
                "sha256": digest,
                "status": "canonicalized",
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
