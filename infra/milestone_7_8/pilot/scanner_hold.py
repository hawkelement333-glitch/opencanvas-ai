"""Durable scanner hold and hard-stop routing for the full-closure operator."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from infra.milestone_7_8.campaign import CampaignError, parse_utc, utc
from infra.milestone_7_8.pilot_cleanup import file_hash, read, write_new

POLICY = {
    "schema": "m78-scanner-hold-v1",
    "decisionSeconds": 900,
    "retryCapSeconds": 20,
    "freshUploadsAfterCorrection": 1,
    "authorizedRepair": "restore-exact-missing-scanner-table-assignment",
    "parallelToScanner": ["destination-readiness"],
    "requiresAcceptedCore": ["index", "capacity", "integrity-fixture", "restore"],
    "cleanupTriggers": [
        "scheduled-proof-stop",
        "readiness-missed-without-scanner-hold",
        "unreconciled-operation",
        "unsafe-binding",
        "cleanup-protection-lost",
        "cost-or-usage-limit",
        "privacy-or-integrity-failure",
        "operator-stop",
    ],
}


class ProofOperator:
    def __init__(self, run: Path, window: dict, deployment: dict, *, clock=None):
        self.run = run
        self.core_by = parse_utc(window["coreReadyBy"])
        self.stop_by = parse_utc(window["stopProofBy"])
        self.deployment = deployment
        self.clock = clock or (lambda: datetime.now(UTC))

    def check(self, *, dependent: bool = False, seconds_needed: int = 0):
        if (self.run / "stop-proof-intent.json").exists() or self.clock() + timedelta(
            seconds=seconds_needed
        ) >= self.stop_by:
            raise CampaignError("stop proof and reconcile scheduled cleanup")
        if (
            dependent
            and self.clock() + timedelta(seconds=seconds_needed) >= self.core_by
        ):
            raise CampaignError("insufficient time before the dependent phase cutoff")

    def hold(self, direction: Path, payload: Path, execution: str) -> None:
        result = read(payload)
        if (
            result.get("status") != "scanner-paused"
            or result.get("operation") != "core"
            or result.get("executionId") != execution
            or result.get("managedAcceptance") != "unproved"
            or any(
                result.get(key) != value
                for key, value in self.deployment.items()
                if key in {"sourceCommit", "imageDigest", "release", "deployment"}
            )
            or self.clock() < parse_utc(result["upload"]["scanDeadlineAt"])
        ):
            raise CampaignError("unbound or nonterminal scanner pause")
        write_new(
            self.run / "scanner-hold.json",
            {
                "atUtc": utc(self.clock()),
                "execution": execution,
                "deployment": self.deployment,
                "resultSha256": file_hash(payload),
                "proof": direction.name,
                "upload": result["upload"],
                "next": POLICY["parallelToScanner"],
            },
        )

    def require_hold(self) -> dict:
        hold = read(self.run / "scanner-hold.json")
        payload = self.run / "proof-core/export/core.json"
        if (
            hold["deployment"] != self.deployment
            or hold["proof"] != "proof-core"
            or hold["resultSha256"] != file_hash(payload)
        ):
            raise CampaignError("scanner hold is bound to another deployment or export")
        return hold

    def resume(self) -> Path:
        # Reserve the entire scanner and worker-publish allowance before write.
        self.check(dependent=True, seconds_needed=1200)
        hold = self.require_hold()
        repair = read(self.run / "scanner-repair/verified.json")
        if not (
            repair.get("repair") == POLICY["authorizedRepair"]
            and repair.get("deployment") == self.deployment
            and repair.get("pausedResultSha256") == hold["resultSha256"]
            and repair.get("objectVersionId") == hold["upload"]["objectVersionId"]
            and repair.get("exactLogReadVerified") is True
            and re.fullmatch(r"[0-9a-f]{64}", repair.get("verificationSha256", ""))
            and repair["verificationSha256"]
            == file_hash(self.run / "scanner-repair/after-worker-read.json")
        ):
            raise CampaignError(
                "the package requires a verified in-scope scanner repair"
            )
        write_new(
            self.run / "scanner-retry-intent.json",
            {
                "atUtc": utc(self.clock()),
                "pausedResultSha256": hold["resultSha256"],
                "repairSha256": file_hash(self.run / "scanner-repair/verified.json"),
                "maximumFreshUploads": 1,
                "maximumDecisionSeconds": 900,
            },
        )
        return self.run / "proof-core/export/core.json"

    def stop(self, reason: str) -> Path:
        if reason not in POLICY["cleanupTriggers"]:
            raise CampaignError("unrecognized hard stop")
        path = self.run / "stop-proof-intent.json"
        if not path.exists():
            write_new(
                path,
                {
                    "reason": reason,
                    "atUtc": utc(self.clock()),
                    "scheduledCleanupAtUtc": utc(self.stop_by),
                },
            )
        return path
