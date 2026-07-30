"""CLI for deterministic Milestone 7.7 aggregate local validation."""

from __future__ import annotations

import argparse
from pathlib import Path

from validation.milestone_7_7.framework import report_bytes, verify_report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    report = verify_report(args.report)
    print(report_bytes(report).decode("utf-8"), end="")
    return 0 if report["status"] == "valid" else 1


if __name__ == "__main__":
    raise SystemExit(main())
