"""Verify the local Checkpoint 6 scope contract without Azure or network access."""

from __future__ import annotations

import json

from performance.milestone_7_7.framework import ContractError, canonical_bytes
from preflight.milestone_7_7.framework import (
    MAX_VERIFIER_BYTES,
    scope_verification_result,
)


def main() -> int:
    try:
        result = scope_verification_result()
        output = canonical_bytes(result)
        if len(output) > MAX_VERIFIER_BYTES:
            raise ContractError("verifier output exceeds its byte limit")
    except (ContractError, OSError, UnicodeError, ValueError):
        output = (
            json.dumps(
                {
                    "status": "invalid",
                    "errorCode": "scope-contract-invalid",
                    "azureExecutionAuthorized": False,
                    "provisioningAuthorized": False,
                },
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode()
        print(output.decode(), end="")
        return 2
    print(output.decode(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
