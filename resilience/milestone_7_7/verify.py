"""CLI for deterministic local Milestone 7.7 failure-plan verification."""

from __future__ import annotations

import argparse
from pathlib import Path

from resilience.milestone_7_7.framework import report_bytes, verify_plan


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    args = parser.parse_args()
    report = verify_plan(args.plan)
    print(report_bytes(report).decode("utf-8"), end="")
    return 0 if report["status"] == "valid" else 1


if __name__ == "__main__":
    raise SystemExit(main())
