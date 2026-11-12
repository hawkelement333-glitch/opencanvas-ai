from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from infra.milestone_7_8.campaign import CampaignError, CommandRunner, utc
from infra.milestone_7_8.canonical_inputs import canonical_snapshot
from infra.milestone_7_8.operator import load_image_scan_evidence, load_runtime

ROOT = Path(__file__).resolve().parents[2]


def retry_report_path(report: Path) -> Path:
    first, separator, rest = report.name.partition(".")
    return report.with_name(first + ".retry" + separator + rest)


def retryable_transport_failure(response: dict[str, object], report: Path) -> bool:
    """Only a completed transport failure with no assessment may be repeated."""
    stdout, stderr = response.get("stdout"), response.get("stderr")
    if (
        type(response.get("exitCode")) is not int
        or response["exitCode"] != 1
        or not isinstance(stdout, str)
        or not isinstance(stderr, str)
        or report.exists()
    ):
        return False
    combined = (stdout + "\n" + stderr).casefold()
    if re.search(r"critical|\bhigh\b|cve-\d{4}-|vulnerabilit|sarif", combined) or any(
        marker in combined
        for marker in (
            "unknown flag", "unknown shorthand", "no matching manifest", "windows/amd64",
            "unauthorized", "forbidden", "permission denied", "manifest unknown",
            "invalid reference", "unsupported",
        )
    ):
        return False
    return any(
        marker in stderr.casefold()
        for marker in (
            "connection reset by peer", "tls handshake timeout", "i/o timeout", "unexpected eof",
        )
    )


def create_scout_receipt(
    runtime_path: Path,
    digest: str,
    report: Path,
    receipt: Path,
    *,
    runner: CommandRunner | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    recover_transport: bool = False,
) -> None:
    """Run one digest-pinned Scout scan and emit a receipt only for a clean result."""
    if recover_transport and runner is None:
        raise CampaignError("bounded scanner recovery requires the recording executor")
    if re.fullmatch(r"sha256:[a-f0-9]{64}", digest) is None:
        raise CampaignError("image digest is malformed")
    private_root = (ROOT / ".runtime" / "milestone_7_8").resolve()
    for path in (runtime_path, report, receipt):
        if not path.resolve().is_relative_to(private_root):
            raise CampaignError("scan artifacts must be in the private runtime directory")
    retry_report = retry_report_path(report)
    if (
        report.exists() or receipt.exists() or report == receipt
        or (recover_transport and (retry_report.exists() or retry_report == receipt))
    ):
        raise CampaignError("scan output already exists")
    runtime = load_runtime(runtime_path)

    def command_result(command: tuple[str, ...]) -> dict[str, object]:
        if runner is None:
            completed = subprocess.run(
                command,
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
                timeout=900,
            )
            result: dict[str, object] = {
                "exitCode": completed.returncode,
                "stdout": completed.stdout,
                "stderr": getattr(completed, "stderr", ""),
            }
        else:
            result = runner.run(command)
        if (
            type(result.get("exitCode")) is not int
            or not isinstance(result.get("stdout"), str)
            or not isinstance(result.get("stderr"), str)
        ):
            raise CampaignError("Docker Scout command response is incomplete")
        return result

    def run(command: tuple[str, ...]) -> str:
        result = command_result(command)
        if result["exitCode"] != 0:
            raise CampaignError("Docker Scout scan or source check failed")
        return cast(str, result["stdout"])

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
    selected_report = report
    for attempt in range(2 if recover_transport else 1):
        if selected_report.exists():
            raise CampaignError(
                "Docker Scout output appeared before dispatch; overwrite prohibited"
            )
        command = (
            "docker",
            "scout",
            "cves",
            reference,
            "--platform",
            "linux/amd64",
            "--only-severity",
            "critical,high",
            "--exit-code",
            "--format",
            "sarif",
            "--output",
            str(selected_report),
        )
        response = command_result(command)
        if response["exitCode"] == 0:
            break
        if attempt != 0 or not recover_transport or not retryable_transport_failure(
            response, selected_report
        ):
            raise CampaignError("Docker Scout assessment failed; retained result is not admissible")
        selected_report = retry_report
    try:
        sarif = json.loads(selected_report.read_text(encoding="utf-8"))
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
