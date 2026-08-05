"""Narrow ledger-bound adapter for the canonical already-pushed entry."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from performance.milestone_7_7.framework import load_json
from preflight.milestone_7_7.managed_binding_contracts import (
    claim_operation_receipt,
    validate_authorization_ledger,
)

from infra.milestone_7_7.scripts import managed_binding_lifecycle as lifecycle


OPERATION_ID = "reconcile-already-pushed-publication"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--receipt-directory", required=True, type=Path)
    parser.add_argument("--already-pushed-record", required=True, type=Path)
    parser.add_argument("--registry-observation", required=True, type=Path)
    parser.add_argument("--repository-head", required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        now = lifecycle._utc_now()
        if lifecycle.HEX_SHA40.fullmatch(args.repository_head) is None:
            lifecycle._fail("repository-head-invalid")
        receipt_directory = lifecycle._outside_repository(
            args.receipt_directory, "receipt-directory"
        )
        receipt_directory.mkdir(parents=True, exist_ok=True)
        ledger = validate_authorization_ledger(
            load_json(lifecycle._outside_repository(args.ledger, "ledger")),
            now_utc=now,
            expected_repository_head=args.repository_head,
        )
        lifecycle._verify_repository_state(args.repository_head)
        subscription_id = lifecycle._account_binding(now)
        claim_operation_receipt(
            ledger=ledger,
            operation_id=OPERATION_ID,
            receipt_directory=receipt_directory,
            now_utc=now,
            expected_repository_head=args.repository_head,
        )
        result = (
            lifecycle._api_image_module()._reconcile_already_pushed_publication_stage(
                ledger=ledger,
                subscription_id=subscription_id,
                receipt_directory=receipt_directory,
                already_pushed_record_path=lifecycle._outside_repository(
                    args.already_pushed_record, "already-pushed-record"
                ),
                registry_observation_path=lifecycle._outside_repository(
                    args.registry_observation, "registry-observation"
                ),
            )
        )
        print(json.dumps(result, separators=(",", ":"), sort_keys=True))
        return 0
    except Exception as exc:
        error_code, _azure_error_code = lifecycle._sanitized_failure(exc)
        print(
            json.dumps(
                {
                    "azure-mutation-performed": False,
                    "error": error_code,
                    "status": "blocked",
                },
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
