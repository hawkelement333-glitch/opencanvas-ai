"""Inert lifecycle entry points for Milestone 7.7 Checkpoint 1."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from contract_validation import (
    ContractError,
    scope_binding_sha256,
    validate_bundle,
)

INERT_OPERATIONS = frozenset({"what-if", "deploy", "teardown", "zero-residue"})


def run_inert(operation: str) -> int:
    if operation not in INERT_OPERATIONS:
        raise ValueError("unknown lifecycle operation")
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-root", type=Path, required=True)
    parser.add_argument("--target-scope", required=True)
    parser.add_argument("--cleanup-control-scope", required=True)
    args = parser.parse_args()

    try:
        bundle = validate_bundle(args.bundle_root)
        scope_digest = scope_binding_sha256(
            args.target_scope, args.cleanup_control_scope
        )
    except ContractError as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}, sort_keys=True))
        return 2

    result = {
        "bundleSha256": bundle["bundleSha256"],
        "executionAuthorized": False,
        "operation": operation,
        "scopeBindingSha256": scope_digest,
        "status": "checkpoint_1_inert",
    }
    print(json.dumps(result, separators=(",", ":"), sort_keys=True))
    return 4
