"""Run the local-only Milestone 7.7 Checkpoint 1 preflight."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from contract_validation import EXPECTED_GATES, ContractError, validate_bundle


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-root", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        manifest = validate_bundle(args.bundle_root)
    except ContractError as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}, sort_keys=True))
        return 2
    print(
        json.dumps(
            {
                "bundleSha256": manifest["bundleSha256"],
                "fileCount": len(manifest["files"]),
                "provisioningAuthorized": False,
                "status": "checkpoint_1_contract_valid",
                "unresolvedGateCount": len(EXPECTED_GATES),
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
