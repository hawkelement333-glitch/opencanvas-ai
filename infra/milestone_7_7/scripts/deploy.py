"""Describe the inert future deploy boundary without contacting Azure."""

from __future__ import annotations

from lifecycle_contract import run_inert

if __name__ == "__main__":
    raise SystemExit(run_inert("deploy"))
