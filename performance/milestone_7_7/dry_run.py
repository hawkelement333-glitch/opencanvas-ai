"""Emit one deterministic local-only Milestone 7.7 validation result."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from performance.milestone_7_7.framework import (
    ContractError,
    canonical_bytes,
    load_json,
    simulate_local,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate and simulate a bounded synthetic workload without network access."
    )
    parser.add_argument("manifest", type=Path)
    parser.add_argument(
        "--print-plan",
        action="store_true",
        help="Print the bounded request plan instead of the aggregate result.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        plan, result = simulate_local(load_json(args.manifest))
    except (ContractError, OSError) as exc:
        print(f"local workload validation failed: {exc}", file=sys.stderr)
        return 2
    sys.stdout.buffer.write(canonical_bytes(plan if args.print_plan else result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
