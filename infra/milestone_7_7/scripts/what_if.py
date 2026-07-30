"""Describe the inert future what-if boundary without contacting Azure."""

from __future__ import annotations

from lifecycle_contract import run_inert

if __name__ == "__main__":
    raise SystemExit(run_inert("what-if"))
