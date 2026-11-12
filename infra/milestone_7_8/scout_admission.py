from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from infra.milestone_7_8.campaign import CampaignError, CommandRunner, utc
from infra.milestone_7_8.canonical_inputs import canonical_snapshot
from infra.milestone_7_8.operator import load_image_scan_evidence, load_runtime

ROOT = Path(__file__).resolve().parents[2]


def create_scout_receipt(
    runtime_path: Path,
    digest: str,
    report: Path,
    receipt: Path,
    *,
    runner: CommandRunner | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> None:
    """Run one digest-pinned Scout scan and emit a receipt only for a clean result."""
    if re.fullmatch(r"sha256:[a-f0-9]{64}", digest) is None:
        raise CampaignError("image digest is malformed")
    private_root = (ROOT / ".runtime" / "milestone_7_8").resolve()
    for path in (runtime_path, report, receipt):
        if not path.resolve().is_relative_to(private_root):
            raise CampaignError("scan artifacts must be in the private runtime directory")
    if report.exists() or receipt.exists() or report == receipt:
        raise CampaignError("scan output already exists")
    runtime = load_runtime(runtime_path)

    def run(command: tuple[str, ...]) -> str:
        exit_code: object
        stdout: object
        if runner is None:
            completed = subprocess.run(
                command,
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
                timeout=900,
            )
            exit_code, stdout = completed.returncode, completed.stdout
        else:
            result = runner.run(command)
            exit_code, stdout = result.get("exitCode"), result.get("stdout")
        if exit_code != 0 or not isinstance(stdout, str):
            raise CampaignError("Docker Scout scan or source check failed")
        return stdout

    head = run(("git", "rev-parse", "HEAD")).strip()
    status = run(("git", "status", "--porcelain=v1"))
    if (
        head != runtime["sourceHead"]
        or status.strip()
        or canonical_snapshot(head)["buildInputSha256"] != runtime["canonicalBuildInputSha256"]
    ):
        raise CampaignError("scan source or canonical input differs")
    registry = runtime["registryName"]
    if re.fullmatch(r"[a-z0-9]{5,50}", registry) is None:
        raise CampaignError("campaign registry name is malformed")
    version = run(("docker", "scout", "version"))
    version_match = re.search(r"(?m)^version:\s*(v?[0-9][^\s]*)", version)
    if version_match is None:
        raise CampaignError("Docker Scout version is unavailable")
    reference = f"registry://{registry}.azurecr.io/mobius-api@{digest}"
    run(
        (
            "docker",
            "scout",
            "cves",
            reference,
            "--only-severity",
            "critical,high",
            "--exit-code",
            "--format",
            "sarif",
            "--output",
            str(report),
        ),
    )
    try:
        sarif = json.loads(report.read_text(encoding="utf-8"))
        runs = sarif["runs"]
        if (
            sarif.get("version") != "2.1.0"
            or not isinstance(runs, list)
            or not runs
            or any(not isinstance(run, dict) or run.get("results") != [] for run in runs)
        ):
            raise ValueError("incomplete or nonempty SARIF")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise CampaignError("Docker Scout SARIF is missing, malformed, or nonempty") from exc
    document = {
        "version": "m7.8-image-admission-v1",
        "sourceHead": head,
        "canonicalBuildInputSha256": runtime["canonicalBuildInputSha256"],
        "imageDigest": digest,
        "scanner": "Docker Scout",
        "scannerVersion": version_match.group(1),
        "scannedAtUtc": utc(clock()),
        "result": "passed",
        "criticalFindings": 0,
        "highFindings": 0,
    }
    with receipt.open("x", encoding="utf-8") as stream:
        json.dump(document, stream, sort_keys=True, indent=2)
        stream.write("\n")
    load_image_scan_evidence(receipt, digest=digest, runtime=runtime)


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan one campaign image digest with Docker Scout")
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--digest", required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not args.execute:
        parser.error("explicit --execute is required")
    try:
        create_scout_receipt(args.runtime, args.digest, args.report, args.receipt)
    except (CampaignError, OSError, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "blocked", "error": type(exc).__name__}))
        return 2
    print(json.dumps({"status": "passed"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
