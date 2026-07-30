"""Network-incapable CLI for a bounded Milestone 7.7 evidence package."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from evidence.milestone_7_7.framework import report_bytes, verify_package


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify a local Milestone 7.7 evidence package without network access."
    )
    parser.add_argument("package", type=Path)
    parser.add_argument("--artifact-root", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    report = verify_package(args.package, artifact_root=args.artifact_root)
    sys.stdout.buffer.write(report_bytes(report))
    return 0 if report["status"] == "valid" else 2


if __name__ == "__main__":
    raise SystemExit(main())
