"""Source-bound core proof and scanner recovery through the private ACA jobs."""

from __future__ import annotations

import argparse
import copy
import gzip
import json
import re
import subprocess
import sys
import time
import uuid
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from infra.milestone_7_8.azure_cli import AzureCliLauncher
from infra.milestone_7_8.campaign import CampaignConfig, CampaignError, parse_utc, utc
from infra.milestone_7_8.pilot import telemetry_first
from infra.milestone_7_8.pilot.pack_execution import pack
from infra.milestone_7_8.pilot.scanner_hold import POLICY, ProofOperator
from infra.milestone_7_8.pilot.scanner_operator import (
    ARM,
    DiagnosticUnavailable,
    collect_and_repair,
    collect_pending,
    console_markers,
    prepared_pending,
)
from infra.milestone_7_8.pilot_cleanup import file_hash, read, validate_live, write_new
from infra.milestone_7_8.pilot_validation import (
    CORE_DIAGNOSTIC_SCOPE,
    SCANNER_OBSERVATION,
    SCANNER_PENDING_MARKER,
    _private_host,
    admit_runtime_bindings,
)

STATES = {"Succeeded", "Failed", "Stopped", "Degraded", "Canceled"}
ACTUAL_VERSIONS = {
    "workspaceResourceId": "2023-09-01",
    "dcrResourceId": "2023-03-11",
    "dceResourceId": "2023-03-11",
    "applicationResourceId": "2025-01-01",
    "gatewayResourceId": "2025-01-01",
    "managedEnvironmentResourceId": "2025-01-01",
    "frontendResourceId": "2025-01-01",
}


class NativeFailure(CampaignError):
    pass


class Campaign:
    def __init__(self, package: Path, bound: Path) -> None:
        review_hash = file_hash(package / "review-package.json")
        self.package, self.bound = package.resolve(), bound.resolve()
        self.run = self.package.parent / ("run-" + review_hash[:8])
        runtime_path = self.bound / "runtime.json"
        self.runtime = read(runtime_path)
        model = CampaignConfig.from_json(
            self.bound / "campaign.json", allow_expired=True
        )
        self.window = validate_live(runtime_path, self.runtime, model)
        review = read(self.package / "review-package.json")
        if (
            Path(self.window["packageDirectory"]).resolve() != self.package
            or Path(review["boundRuntimeDirectory"]).resolve() != self.bound
            or review.get("scannerRecoveryPolicy") != POLICY
        ):
            raise CampaignError("operator package or scanner policy differs")
        self.plan = read(self.package / "planned-bindings.json")
        if self.plan.get("scannerObservation") not in (None, SCANNER_OBSERVATION):
            raise CampaignError("scanner observation package must be resealed for this runner")
        self.scope = self.plan["targetResourceGroupId"]
        self.rg, self.sub = (
            self.runtime["resourceGroupName"],
            self.runtime["subscriptionId"],
        )
        if (
            self.scope.casefold()
            != f"/subscriptions/{self.sub}/resourceGroups/{self.rg}".casefold()
        ):
            raise CampaignError("target differs from the bound runtime")
        deployment = {
            k: self.plan[k]
            for k in ("sourceCommit", "imageDigest", "release", "deployment")
        }
        self.model = model
        self.telemetry_first = review.get("telemetryFirstPolicy") == telemetry_first.POLICY
        self.policy = ProofOperator(
            self.run,
            self.window,
            deployment
            | {
                "campaignId": model.campaign_id,
                "generationId": model.generation_id,
                "executionStartAt": self.window["executionStartAt"],
                "resourceGroupId": self.scope,
            },
        )
        self.azure = AzureCliLauncher.resolve()

    def remaining(self, cutoff: datetime | None = None) -> float:
        self.policy.check()
        remaining = (
            min(cutoff or self.policy.stop_by, self.policy.stop_by) - datetime.now(UTC)
        ).total_seconds()
        if remaining <= 0:
            raise CampaignError("approved operation deadline reached")
        return remaining

    def call(
        self,
        directory,
        label,
        args,
        *,
        timeout=70,
        as_json=True,
        cutoff=None,
        allow_failure=False,
    ):
        arguments = (*args, "--subscription", self.sub)
        if as_json:
            arguments += ("--output", "json")
        result_path = directory / (label + ".native.json")
        if result_path.exists():
            raise CampaignError("native operation already exists; reconcile")
        try:
            result = self.azure.run(
                arguments, timeout=min(timeout, self.remaining(cutoff))
            )
        except subprocess.TimeoutExpired:
            write_new(
                result_path, {"atUtc": utc(datetime.now(UTC)), "status": "timed-out"}
            )
            raise NativeFailure(label + " requires native reconciliation") from None
        write_new(
            result_path,
            {
                "atUtc": utc(datetime.now(UTC)),
                "exitCode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            },
        )
        if result.returncode:
            if allow_failure:
                return None
            raise NativeFailure(label + " requires native reconciliation")
        if not as_json:
            return result.stdout
        return json.loads(result.stdout) if result.stdout.strip() else {}

    def get(self, folder, label, rid, version, *, cutoff=None):
        if not rid.casefold().startswith(self.scope.casefold() + "/providers/"):
            raise CampaignError("native resource escaped the campaign scope")
        return self.call(
            folder,
            label,
            ("rest", "--method", "get", "--url", f"{ARM}{rid}?api-version={version}"),
            cutoff=cutoff,
        )

    def admit(self):
        native = self.run / "native-admission-readbacks"
        protection = read(native / "cleanup-protection-accepted.json")
        from infra.milestone_7_8.operator import (
            validate_cleanup_bindings,
            validate_cleanup_schedule,
        )

        if protection["scheduleSha256"] != file_hash(
            native / "schedule.json"
        ) or protection["bindingSha256"] != file_hash(native / "exact-binding.json"):
            raise CampaignError("native protection evidence digest differs")

        def body(name):
            snapshot = read(native / name)
            if snapshot["exitCode"] != 0:
                raise CampaignError("native protection outcome unknown")
            return json.loads(snapshot["stdout"])

        validate_cleanup_schedule(
            body("schedule.json"), config=self.model, runtime=self.runtime
        )
        validate_cleanup_bindings(
            body("binding-list.json"),
            config=self.model,
            runtime=self.runtime,
            exact_binding=body("exact-binding.json"),
        )
        if not (
            read(self.bound / "ledger.json")["phase"] == "billable-started"
            and protection.get("exactBindingAccepted") is True
            and protection.get("exactScheduleAccepted") is True
            and read(self.run / "activation/runtime-activation-terminal.json")[
                "success"
            ]
            is True
            and read(self.run / "vpn/private-route-admission/accepted.json")[
                "privateDnsAndTls"
            ]
            is True
            and len(
                read(self.run / "corrected-alert-native-admission/accepted.json")[
                    "nativeRuleCreationAccepted"
                ]
            )
            == 2
        ):
            raise CampaignError("runtime protection or health admission differs")

    def native_readbacks(self, directory, cutoff=None):
        readbacks = {
            "planSha256": file_hash(self.package / "planned-bindings.json"),
            "resources": [],
        }
        for key, api in ACTUAL_VERSIONS.items():
            rid = self.plan[key]
            body = self.get(directory, key, rid, api, cutoff=cutoff)
            readbacks["resources"].append(
                {
                    "request": {"method": "GET", "resourceId": rid, "apiVersion": api},
                    "response": {"status": 200, "body": body},
                }
            )
        return readbacks

    def cleanup(self, reason: str):
        self.policy.stop(reason)
        marker = self.run / "proof-cleanup-dispatch-intent.json"
        if marker.exists():
            raise CampaignError(
                "cleanup dispatch already recorded; reconcile exact native job or schedule"
            )
        # At the scheduled cutoff the native job may already own deletion.
        # No second dispatch. Reconcile the original schedule via the existing operator.
        if self.policy.clock() >= self.policy.stop_by:
            write_new(marker, {"kind": "scheduled", "atUtc": utc(datetime.now(UTC))})
            return "scheduled-cleanup-due"
        write_new(marker, {"kind": "operator", "atUtc": utc(datetime.now(UTC))})
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "infra.milestone_7_8.operator",
                "cleanup",
                "--config",
                str(self.bound / "campaign.json"),
                "--runtime",
                str(self.bound / "runtime.json"),
                "--ledger",
                str(self.bound / "ledger.json"),
                "--authorization",
                str(self.bound / "operator-approval.json"),
                "--execute",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=max(
                1,
                min(
                    300,
                    (
                        parse_utc(self.window["automationBindingExpiresAt"])
                        - datetime.now(UTC)
                    ).total_seconds(),
                ),
            ),
        )
        write_new(
            self.run / "proof-cleanup-dispatch-result.json",
            {
                "exitCode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            },
        )
        if result.returncode:
            raise CampaignError("cleanup dispatch needs native reconciliation")
        return "early-cleanup-dispatched"


def artifact_receipt(text, expected):
    # The ACA extension can wrap CRI JSON and leave the inner JSON unescaped.
    found = {}

    def inspect(item):
        if isinstance(item, dict):
            if (
                item.get("sha256") == expected["artifactSha256"]
                and item.get("bytes") == expected["artifactBytes"]
                and item.get("versionId")
            ):
                found[item["versionId"]] = item
            for child in item.values():
                inspect(child)
        elif isinstance(item, list):
            for child in item:
                inspect(child)
        elif isinstance(item, str):
            for line in item.splitlines():
                inner = re.fullmatch(
                    r'\{"TimeStamp":"[0-9T:+.Z-]+","Log":"F (\{.*\})"\}', line
                )
                line = line.removeprefix("F ")
                try:
                    obj = json.loads(inner[1] if inner else line)
                except ValueError:
                    continue
                if isinstance(obj, (dict, list)):
                    inspect(obj)

    inspect(text)
    if len(found) != 1:
        raise CampaignError("artifact version must be reconciled before proof dispatch")
    return next(iter(found.values()))


def proof_disposition(payload, plan, execution, operation, native_state):
    if payload.get("executionId") != execution or payload.get("operation") != operation:
        raise CampaignError("proof export belongs to a different execution")
    if "errorClass" in payload or native_state != "Succeeded":
        raise CampaignError(
            "proof failed; reconcile the preserved execution and export"
        )
    if any(
        payload.get(key) != plan[key]
        for key in ("sourceCommit", "imageDigest", "release", "deployment")
    ):
        raise CampaignError("proof release binding differs")
    if not payload.get("finishedAt"):
        raise CampaignError("terminal proof evidence is missing")
    if operation == "core":
        if plan.get("coreDiagnosticScope") == CORE_DIAGNOSTIC_SCOPE:
            status = payload.get("status")
            upload = payload.get("upload", {})
            if (
                status not in {"scanner-diagnostic-completed", "scanner-diagnostic-deadline"}
                or payload.get("providerCalls") != 0
                or payload.get("managedAcceptance") != "scanner-diagnostic-only"
                or upload.get("suffix") != "primary"
                or (status == "scanner-diagnostic-completed" and upload.get("scanOutcome") != "clean")
            ):
                raise CampaignError("scanner diagnostic export differs from the sealed scope")
            return status
        if (
            payload.get("status") in {"scanner-paused", "scanner-retry-exhausted"}
            and payload.get("managedAcceptance") == "unproved"
        ):
            return payload["status"]
        if (
            payload.get("core", {}).get("status") != "accepted"
            or payload.get("managedAcceptance")
            != "only listed core observations accepted"
        ):
            raise CampaignError("core evidence incomplete")
    elif plan.get("coreDiagnosticScope") == CORE_DIAGNOSTIC_SCOPE:
        user_id = payload.get("userId")
        try:
            exact_primary_id = isinstance(user_id, str) and str(uuid.UUID(user_id)) == user_id
        except ValueError:
            exact_primary_id = False
        if (
            payload.get("accountsReady") is not True
            or payload.get("accountCreated") is not True
            or payload.get("accountActions") != {"primary": "signup"}
            or "secondaryUserId" in payload
            or not exact_primary_id
        ):
            raise CampaignError("account evidence incomplete")
    elif "consolidatedScope" in plan:
        from infra.milestone_7_8.pilot.consolidated import require_two_signups

        require_two_signups(payload)
    elif (
        payload.get("accountsReady") is not True
        or set(payload.get("accountActions", {})) != {"primary", "secondary"}
        or payload["userId"] == payload["secondaryUserId"]
    ):
        raise CampaignError("account evidence incomplete")
    return "accepted"


def read_export(context, path, proof, operation, cutoff):
    download = path / "export"
    download.mkdir()
    base = (
        "--account-name",
        "stm78oa712b8c940",
        "--container-name",
        "operational-evidence",
    )
    auth = ("--auth-mode", "login", "--only-show-errors")
    inventory = context.call(
        path,
        "evidence-export-inventory",
        (
            "storage",
            "blob",
            "list",
            *base,
            "--prefix",
            proof + "/",
            "--include",
            "v",
            *auth,
        ),
        cutoff=cutoff,
    )
    if not 0 < len(inventory) <= 2001:
        raise CampaignError("invalid native export inventory")
    seen = set()
    for index, blob in enumerate(inventory):
        name = blob["name"]
        suffix = name.removeprefix(proof + "/")
        relative = Path(suffix)
        if (
            suffix == name
            or suffix in seen
            or relative.is_absolute()
            or ".." in relative.parts
            or ":" in suffix
            or "\\" in suffix
            or not blob.get("versionId")
        ):
            raise CampaignError("export inventory omitted an exact safe version")
        seen.add(suffix)
        local = download / relative
        local.parent.mkdir(exist_ok=True, parents=True)
        context.call(
            path,
            f"download-{index:04}",
            (
                "storage",
                "blob",
                "download",
                *base,
                "--name",
                name,
                "--file",
                str(local.resolve()),
                "--version-id",
                blob["versionId"],
                *auth,
                "--no-progress",
            ),
            cutoff=cutoff,
        )
    manifest = read(download / "export-manifest.json")
    versions = {
        row["name"].removeprefix(proof + "/"): row["versionId"] for row in inventory
    }
    if manifest["executionId"] != proof or set(versions) != {
        "export-manifest.json",
        *(item["path"] for item in manifest["files"]),
    }:
        raise CampaignError("manifest differs from native export inventory")
    for item in manifest["files"]:
        file = download / item["path"]
        if (
            not file.resolve().is_relative_to(download.resolve())
            or file.stat().st_size != item["bytes"]
            or item["versionId"] != versions[item["path"]]
            or file_hash(file) != item["sha256"]
        ):
            raise CampaignError("export bytes, digest or version differs")
    return download / (operation + ".json")


def wait_private_api(context, path, endpoint):
    _private_host(urlsplit(endpoint).hostname)
    cutoff = parse_utc(context.window["readyBy"])
    with httpx.Client(
        base_url=endpoint, follow_redirects=False, trust_env=False
    ) as client:
        for attempt in range(1, 13):
            try:
                response = client.get(
                    "/api/v1/health/ready", timeout=min(10, context.remaining(cutoff))
                )
                if response.status_code == 200 and response.json() == {
                    "status": "ready",
                    "service": "opencanvas-api",
                }:
                    context.remaining(cutoff)
                    write_new(
                        path / "private-api-ready.json",
                        {
                            "status": 200,
                            "attempts": attempt,
                            "atUtc": utc(datetime.now(UTC)),
                        },
                    )
                    return
            except httpx.RequestError:
                pass
            time.sleep(min(5, context.remaining(cutoff)))
    raise CampaignError("private readiness missed before first signup")


def pending_observation(text, execution, plan, now, core_by):
    markers = console_markers(text, SCANNER_PENDING_MARKER)
    if not markers:
        return None
    if len(markers) != 1 or not isinstance(markers[0], dict):
        raise CampaignError("duplicate or invalid primary scanner marker")
    marker = markers[0]
    upload = marker["upload"]
    stamp = parse_utc(marker["pendingAt"])
    deadline = parse_utc(upload["scanDeadlineAt"])
    server_deadline = parse_utc(upload["serverScanDeadlineAt"])
    checksum = upload["contentSha256"]
    if (
        marker["executionId"] != execution
        or marker["binding"] != {
            key: plan[key] for key in ("imageDigest", "sourceCommit", "release", "deployment")
        }
        or upload["suffix"] != SCANNER_OBSERVATION["fixture"]
        or not re.fullmatch(r"[a-f0-9]{64}", checksum)
        or any(str(uuid.UUID(upload[key])) != upload[key]
               for key in ("sessionId", "documentId", "objectVersionId"))
        or not stamp <= now or not stamp < deadline <= server_deadline
        or deadline - stamp > timedelta(seconds=SCANNER_OBSERVATION["publishWhenSecondsRemaining"])
    ):
        raise CampaignError("primary scanner marker differs from the exact active execution")
    minimum = timedelta(seconds=SCANNER_OBSERVATION["minimumDispatchSecondsRemaining"])
    return marker if now + minimum < min(deadline, core_by) else None


def observe_while_core_runs(context, path, execution, native_args, index, cutoff, observe):
    if (context.run / "scanner-in-window/pending-marker.json").exists():
        return
    now = context.policy.clock()
    if now + timedelta(seconds=SCANNER_OBSERVATION["minimumDispatchSecondsRemaining"]) >= cutoff:
        return
    try:
        logs = context.call(
            path, f"pending-console-{index:04d}",
            ("containerapp", "job", "logs", "show", *native_args,
             "--execution", execution, "--container", "evidence",
             "--tail", "60", "--follow", "false", "--format", "json"),
            as_json=False, cutoff=cutoff, timeout=12,
        )
    except NativeFailure:
        # Log availability is not authorization to substitute a fixture or replay the upload.
        return
    marker = pending_observation(logs, execution, context.plan, context.policy.clock(), cutoff)
    if marker is None:
        return
    try:
        collect_pending(context, marker, observe)
    except (DiagnosticUnavailable, NativeFailure) as error:
        # A failed read or a missing console can coexist with normal proof.
        # Uncertain dispatch or restore is a CampaignError and reaches the hard stop.
        write_new(context.run / "scanner-in-window/unproved.json",
                  {"reason": str(error), "atUtc": utc(context.policy.clock())})


def dispatch_proof(context, phase, resume_path=None):
    operation = (
        "account"
        if phase == "account-recovery"
        else "core"
        if phase == "core-retry"
        else phase
    )
    policy, plan = context.policy, context.plan
    module = "infra.milestone_7_8.pilot_application_probe"
    cutoff = policy.core_by
    if phase == "transport":
        operation = "telemetry"
        module = "infra.milestone_7_8.pilot_validation"
        policy.check(seconds_needed=1500)
        cutoff = min(policy.stop_by, policy.clock() + timedelta(minutes=25))
    path = context.run / ("proof-" + phase)
    path.mkdir(exist_ok=False)
    if phase in {"core", "core-retry"}:
        accounts = [
            p
            for p in (
                context.run / "proof-account/accepted.json",
                context.run / "proof-account-recovery/accepted.json",
            )
            if p.is_file()
        ]
        if len(accounts) != 1 or read(accounts[0])["operation"] != "account":
            raise CampaignError("same-deployment synthetic account fixture required")
    # Readbacks shared by account and core. If bytes and manifest match, consume
    # the native artifact version already verified by the immediately prior job.
    carry = next(
        (
            p
            for p in (
                context.run / "proof-account",
                context.run / "proof-account-recovery",
            )
            if operation == "core" and (p / "accepted.json").is_file()
        ),
        None,
    )
    readbacks = (
        read(carry / "native-resource-readbacks.json")
        if carry
        else context.native_readbacks(path, cutoff)
    )
    admitted = admit_runtime_bindings(
        plan,
        readbacks,
        plan_sha256=file_hash(context.package / "planned-bindings.json"),
    )
    if phase == "account":
        wait_private_api(context, path, admitted["apiBaseUrl"])
    write_new(path / "native-resource-readbacks.json", readbacks)
    compact = path / "native-resource-readbacks.json.gz"
    raw = json.dumps(readbacks, separators=(",", ":"), ensure_ascii=False).encode()
    if len(raw) > 250_000:
        raise CampaignError("runtime readback exceeds proof artifact limit")
    with compact.open("xb") as stream:
        stream.write(gzip.compress(raw, mtime=0))
    args = [
        operation,
        "--bundle",
        "/tmp/m78-proof/package",
        "--authorization",
        "/tmp/m78-proof/approval.json",
        "--bindings",
        "/tmp/m78-proof/bindings.json",
        "--runtime-readbacks",
        "/tmp/m78-proof/" + compact.name,
        "--execution-id",
        "${EXECUTION_ID}",
        "--output",
        f"/tmp/m78-evidence/{operation}.json",
        "--execute",
    ]
    private = {compact.name: str(compact)}
    if phase == "account-recovery":
        reconciliation = context.run / "signup-reconciliation/accepted.json"
        if read(reconciliation)["writersQuiesced"] is not True:
            raise CampaignError("exact signup recovery snapshot required")
        private[reconciliation.name] = str(reconciliation)
        args.extend(
            ("--account-reconciliation", "/tmp/m78-proof/" + reconciliation.name)
        )
    if resume_path is not None:
        private["scanner-resume.json.gz"] = str(path / "scanner-resume.json.gz")
        (path / "scanner-resume.json.gz").write_bytes(
            gzip.compress(resume_path.read_bytes(), mtime=0)
        )
        args.extend(("--scanner-resume", "/tmp/m78-proof/scanner-resume.json.gz"))
    package = context.package
    packed = path / "transport.json"
    pack(
        package,
        context.bound / "approval.json",
        package / "planned-bindings.json",
        module,
        args,
        packed,
        package / "wheel-manifest.json",
        package / "wheels",
        private,
    )
    transport = read(packed)
    prefix = context.plan["deployment"].removeprefix("m78p-")
    shared = [
        {
            "name": "M78_PILOT_STORAGE_HOST",
            "value": "stm78oa712b8c940.blob.core.windows.net",
        },
        {"name": "M78_PILOT_SUFFIX", "value": prefix},
    ]

    def job(role, command, env, observe=None):
        name = "caj-m78p-" + prefix + "-" + role
        rid = context.scope + "/providers/Microsoft.App/jobs/" + name
        native_args = ("--resource-group", context.rg, "--name", name)
        executions = context.call(
            path,
            role + "-execution-list",
            ("containerapp", "job", "execution", "list", *native_args),
            cutoff=cutoff,
        )
        if any(
            (e.get("properties") or e).get("status") not in STATES for e in executions
        ):
            raise CampaignError("active proof job must be reconciled")
        original = context.get(
            path, role + "-template-before", rid, "2025-01-01", cutoff=cutoff
        )
        template = copy.deepcopy(original["properties"]["template"])
        (container,) = template["containers"]
        if container["name"] != role or not container["image"].endswith(
            "@" + plan["imageDigest"]
        ):
            raise CampaignError("proof job image binding changed")
        overlay = {item["name"]: item for item in env}
        container["env"] = [
            v for v in container.get("env", []) if v["name"] not in overlay
        ] + list(overlay.values())
        container["command"] = command
        container.pop("args", None)
        body = path / (role + "-patch.json")
        write_new(body, {"properties": {"template": template}})
        write_new(
            path / (role + "-patch-intent.json"),
            {"resourceId": rid, "bodySha256": file_hash(body)},
        )
        context.call(
            path,
            role + "-patch",
            (
                "rest",
                "--method",
                "patch",
                "--url",
                f"{ARM}{rid}?api-version=2025-01-01",
                "--body",
                "@" + str(body),
            ),
            cutoff=cutoff,
        )
        observed = context.get(
            path, role + "-template-readback", rid, "2025-01-01", cutoff=cutoff
        )
        (actual,) = observed["properties"]["template"]["containers"]
        values = {v["name"]: v for v in actual["env"]}
        if (
            actual["command"] != command
            or actual["image"] != container["image"]
            or any(values[key] != value for key, value in overlay.items())
        ):
            raise CampaignError("job native template readback differs")
        write_new(
            path / (role + "-start-intent.json"),
            {"job": name, "atUtc": utc(datetime.now(UTC))},
        )
        started = context.call(
            path,
            role + "-start",
            ("containerapp", "job", "start", *native_args),
            timeout=85,
            cutoff=cutoff,
        )
        execution = started["name"].rsplit("/", 1)[-1]
        if not execution.startswith(name + "-"):
            raise CampaignError("native proof execution does not match the exact job")
        write_new(
            path / (role + "-execution.json"),
            {
                "job": name,
                "execution": execution,
                "artifactSha256": transport["artifactSha256"],
            },
        )
        index = 0
        while context.remaining(cutoff):
            terminal = context.call(
                path,
                f"{role}-poll-{index:04}",
                (
                    "containerapp",
                    "job",
                    "execution",
                    "show",
                    *native_args,
                    "--job-execution-name",
                    execution,
                ),
                cutoff=cutoff,
            )
            index += 1
            state = terminal["properties"]["status"]
            if observe is not None:
                observe_while_core_runs(context, path, execution, native_args, index, cutoff, observe)
            if state in STATES:
                write_new(path / (role + "-terminal.json"), terminal)
                return execution, state
            time.sleep(min(8, context.remaining(cutoff)))

    prior = read(carry / "artifact-version-binding.json") if carry else {}
    if prior.get("artifactSha256") == transport["artifactSha256"]:
        version = prior | {
            "reusedFrom": carry.name,
            "priorReceiptSha256": file_hash(carry / "accepted.json"),
        }
    else:
        artifact, state = job(
            "artifact",
            transport["artifactStagingCommand"],
            transport["artifactStagingEnvironment"] + shared,
        )
        if state != "Succeeded":
            raise CampaignError(
                "artifact staging failed; preserve exact native receipt"
            )
        logs = context.call(
            path,
            "artifact-console",
            (
                "containerapp",
                "job",
                "logs",
                "show",
                "--resource-group",
                context.rg,
                "--name",
                "caj-m78p-" + prefix + "-artifact",
                "--execution",
                artifact,
                "--container",
                "artifact",
                "--tail",
                "100",
                "--follow",
                "false",
                "--format",
                "json",
            ),
            as_json=False,
            cutoff=cutoff,
        )
        version = {
            "versionId": artifact_receipt(logs, transport)["versionId"],
            "artifactSha256": transport["artifactSha256"],
            "nativeArtifactExecution": artifact,
        }
    write_new(path / "artifact-version-binding.json", version)
    preparation = (
        prepared_pending(context, cutoff)
        if phase == "core" and plan.get("scannerObservation") == SCANNER_OBSERVATION
        else nullcontext()
    )
    with preparation as observe:
        if observe is not None:
            policy.check(dependent=True, seconds_needed=1200)
        proof, state = job(
            "evidence",
            transport["proofCommand"],
            transport["proofEnvironment"]
            + shared
            + [{"name": "M78_PILOT_ARTIFACT_VERSION_ID", "value": version["versionId"]}],
            observe,
        )
    exported = read_export(context, path, proof, operation, cutoff)
    payload = read(exported)
    if phase == "transport":
        if payload["executionId"] != proof or payload["operation"] != "telemetry":
            raise CampaignError("transport receipt belongs to another execution")
        fixture = payload["result"]
        accepted = (
            state == "Succeeded"
            and fixture.get("classification") == "transport-fixture-only"
            and fixture.get("unauthenticatedStatus") == 401
            and fixture.get("forbiddenContentStatus") == 422
            and fixture.get("destination", {}).get("status") == 200
            and len(fixture.get("expectedRows", ())) == 4
        )
        write_new(path / "transport-summary.json", {
            "execution": proof, "resultSha256": file_hash(exported),
            "transportFixtureAccepted": accepted, "terminalState": state,
            "fullD003Accepted": False,
        })
        return "transport-fixture-accepted" if accepted else "transport-unproved"
    if (
        phase == "account"
        and state == "Failed"
        and payload.get("errorClass") == "ReadTimeout"
        and payload.get("executionId") == proof
        and payload.get("operation") == operation
        and any(
            read(intent).get("path") == "/api/v1/auth/signup"
            and not intent.with_name(intent.stem + "-result.json").is_file()
            for intent in (exported.parent / "account.steps").glob("*-http-intent.json")
        )
    ):
        # The existing signup reconciler accepts only an exact POST intent.
        # Do not infer a safe retry from this error class.
        write_new(
            path / "proof-outcome-unknown.json",
            {
                "execution": proof,
                "phase": "account",
                "errorClass": "ReadTimeout",
                "resultSha256": file_hash(exported),
            },
        )
        return "signup-reconciliation-required"
    status = proof_disposition(payload, plan, proof, operation, state)
    marker_path = context.run / "scanner-in-window/pending-marker.json"
    if phase == "core" and marker_path.exists():
        captured = read(marker_path)["upload"]
        primary = payload.get("fixture", {}).get("primary")
        if primary is None and payload.get("upload", {}).get("suffix") == "primary":
            primary = payload["upload"]
        if primary is None or any(
            primary[key] != captured[key]
            for key in ("sessionId", "documentId", "objectVersionId", "contentSha256")
        ):
            raise CampaignError("exported primary upload differs from the in-window marker")
        if (
            (plan.get("coreDiagnosticScope") == CORE_DIAGNOSTIC_SCOPE or "consolidatedScope" in plan)
            and primary["scanDeadlineAt"] != captured["scanDeadlineAt"]
        ):
            raise CampaignError("exported diagnostic cutoff differs from the upload marker")
    if status == "scanner-paused" and phase == "core":
        policy.hold(path, exported, proof)
    if status == "accepted":
        if phase == "account" and payload.get("accountCreated") is not True:
            raise CampaignError("account creation fixture missing")
        write_new(
            path / "accepted.json",
            {
                "operation": operation,
                "execution": proof,
                "artifactExecution": version["nativeArtifactExecution"],
                "resultSha256": file_hash(exported),
                "atUtc": utc(datetime.now(UTC)),
            },
        )
    return status


def validate_destination_sample(values, plan, begin, end):
    from infra.milestone_7_8.destination_acceptance import rows, validate_signal_row

    if isinstance(values, dict):
        values = rows(values)
    if not isinstance(values, list) or len(values) > 32:
        raise CampaignError("bounded native destination rows required")
    observed = set()
    ids = set()
    for row in values:
        if not isinstance(row, dict) or not isinstance(row.get("TimeGenerated"), str):
            raise CampaignError("native destination row has no valid timestamp")
        stamp = parse_utc(row["TimeGenerated"])
        if not begin <= stamp <= end:
            raise CampaignError("destination row out of time bounds")
        try:
            signal = validate_signal_row(row, plan["productionSources"], stamp, ids)
        except ValueError as error:
            raise CampaignError("destination privacy or integrity failure") from error
        observed.add(signal["service"])
    return observed, len(values)


def require_destination_hold(context):
    path = context.run / "destination-readiness"
    hold = read(path / "unproved.json")
    plan_path = context.package / "destination-plan.bound.json"
    label = hold["nativeReadback"]
    if (
        hold["deployment"] != context.policy.deployment
        or hold["executionStartAt"] != context.window["executionStartAt"]
        or hold["planSha256"] != file_hash(plan_path)
        or not re.fullmatch(r"production-rows-(0[0-9]|1[01])\.native\.json", label)
    ):
        raise CampaignError("destination hold differs from the bound deployment")
    witness = path / label
    if hold["nativeReadbackSha256"] != file_hash(witness):
        raise CampaignError("destination hold native evidence digest differs")
    result = read(witness)
    if result.get("exitCode") != 0 or not isinstance(result.get("atUtc"), str):
        raise CampaignError("destination hold native result is invalid")
    delivered = parse_utc(result["atUtc"])
    begin = parse_utc(hold["executionStartAt"])
    if not begin <= delivered <= context.policy.clock():
        raise CampaignError("destination hold native result is invalid")
    observed, count = validate_destination_sample(
        json.loads(result["stdout"]), read(plan_path), begin, delivered
    )
    if observed != {"mobius-worker"} or count != hold["rows"]:
        raise CampaignError("destination hold must show verified worker-only evidence")


def observe_infrastructure(context):
    from infra.milestone_7_8.destination_acceptance import rows

    plan = context.plan
    directory = context.run / "successor-native-categories"
    directory.mkdir(exist_ok=False)
    workspace = context.get(directory, "workspace", plan["workspaceResourceId"], "2023-09-01")
    if workspace["id"].casefold() != plan["workspaceResourceId"].casefold():
        raise CampaignError("infrastructure query workspace differs")
    customer = str(uuid.UUID(workspace["properties"]["customerId"]))
    begin = parse_utc(context.window["executionStartAt"])
    end = context.policy.clock()
    sql = plan["databaseResourceId"]
    blob = plan["targetResourceGroupId"] + (
        "/providers/Microsoft.Storage/storageAccounts/stm78oa712b8c940/blobServices/default"
    )
    results = {}
    for name, resource, category in (
        ("postgresql-logs", sql, "PostgreSQLLogs"),
        ("blob-delete", blob, "StorageDelete"),
    ):
        setting = (
            resource + "/providers/Microsoft.Insights/diagnosticSettings/pilot-category-proof"
        )
        native = context.get(directory, name + "-setting", setting, "2021-05-01-preview")
        props = native["properties"]
        if (
            native["id"].casefold() != setting.casefold()
            or props["workspaceId"].casefold() != plan["workspaceResourceId"].casefold()
            or props.get("logAnalyticsDestinationType") != "Dedicated"
            or not any(
                log.get("category") == category and log.get("enabled") is True
                for log in props["logs"]
            )
        ):
            raise CampaignError("native diagnostic setting or destination differs")
        query = context.package / "queries" / (name + ".kql")
        if file_hash(query) != plan["queryFiles"][name]:
            raise CampaignError("native category query does not match the package")
        request = directory / (name + "-query.json")
        write_new(request, {"query": query.read_text(), "timespan": f"{utc(begin)}/{utc(end)}"})
        reply = context.call(
            directory, name + "-query",
            ("rest", "--method", "post", "--url",
             f"https://api.loganalytics.io/v1/workspaces/{customer}/query",
             "--resource", "https://api.loganalytics.io/", "--body", "@" + str(request)),
            allow_failure=True,
        )
        query_succeeded = reply is not None and "error" not in reply
        found = rows({"status": 200, "result": reply}) if query_succeeded else []
        if len(found) > 1 or any(
            record.get("Category") != category or type(record.get("Count")) is not int
            or record["Count"] <= 0
            or not begin <= parse_utc(record["First"]) <= parse_utc(record["Last"]) <= end
            for record in found
        ):
            raise CampaignError("native category rows are outside the exact source or window")
        results[name] = {
            "category": category, "querySucceeded": query_succeeded,
            "observed": bool(found), "rows": found,
        }
    write_new(directory / "summary.json", {"observations": results, "fullD007Accepted": False})
    return "native-categories-observed-or-unproved"


def destination_readiness(context):
    path = context.run / "destination-readiness"
    path.mkdir(exist_ok=False)
    plan_path = context.package / "destination-plan.bound.json"
    plan = read(plan_path)
    begin = parse_utc(context.window["executionStartAt"])
    release, deployment = plan["release"], plan["deployment"]
    if not all(re.fullmatch(r"[a-z0-9-]+", v) for v in (release, deployment)):
        raise CampaignError("invalid destination release binding")
    # The Azure CLI launcher rejects control characters in arguments.
    start = utc(begin)
    query = (
        "union MobiusApplication_CL, MobiusMetric_CL, MobiusSpan_CL "
        f"| where TimeGenerated >= datetime({start}) "
        f'| where Release == "{release}" and Deployment == "{deployment}" '
        '| where Service in ("mobius-api", "mobius-worker") '
        "| summarize arg_max(TimeGenerated, *) by SignalId "
        "| partition by Service (top 16 by TimeGenerated desc) "
        "| project TimeGenerated, SignalId, Service, Environment, Release, Deployment, "
        "Kind, Name, Component, Payload"
    )
    if (context.run / "scanner-hold.json").exists():
        context.policy.require_hold()
        cutoff = context.policy.stop_by
    elif getattr(context, "telemetry_first", False):
        cutoff = context.policy.stop_by
    else:
        cutoff = context.policy.core_by
    if context.policy.clock() >= cutoff:
        return "destination-readiness-unproved"
    workspace_body = context.get(
        path, "workspace", plan["workspaceResourceId"], "2023-09-01", cutoff=cutoff
    )
    workspace = str(uuid.UUID(workspace_body["properties"]["customerId"]))
    worker_sample = None
    for index in range(12):
        if context.policy.clock() >= cutoff:
            break
        label = f"production-rows-{index:02}"
        try:
            values = context.call(
                path,
                label,
                (
                    "monitor",
                    "log-analytics",
                    "query",
                    "--workspace",
                    workspace,
                    "--analytics-query",
                    query,
                    "--timespan",
                    "PT12H",
                ),
                timeout=35,
                cutoff=cutoff,
            )
        except NativeFailure:
            if worker_sample is None:
                raise
            # This command only reads. Retain the verified sample even if a
            # follow-up read cannot supply stronger evidence.
            break
        observed, count = validate_destination_sample(
            values, plan, begin, context.policy.clock()
        )
        receipt = path / (label + ".native.json")
        if observed == {"mobius-api", "mobius-worker"}:
            context.remaining(cutoff)
            write_new(
                path / "accepted.json",
                {
                    "readinessOnly": True,
                    "productionSources": sorted(observed),
                    "rows": count,
                    "nativeReadbackSha256": file_hash(receipt),
                    "deployment": context.policy.deployment,
                    "atUtc": utc(datetime.now(UTC)),
                },
            )
            return "destination-readiness-observed"
        if observed == {"mobius-worker"}:
            worker_sample = (receipt, count)
        if index < 11:
            remaining = (cutoff - context.policy.clock()).total_seconds()
            if remaining > 0:
                time.sleep(min(15, remaining))
    if worker_sample is not None:
        receipt, count = worker_sample
        write_new(
            path / "unproved.json",
            {
                "deployment": context.policy.deployment,
                "executionStartAt": context.window["executionStartAt"],
                "planSha256": file_hash(plan_path),
                "nativeReadback": receipt.name,
                "nativeReadbackSha256": file_hash(receipt),
                "rows": count,
            },
        )
    return "destination-readiness-unproved"


def operate(context, action, *, stop_reason=None):
    if action == "stop":
        return context.cleanup(stop_reason or "operator-stop")
    if context.policy.clock() >= context.policy.stop_by:
        return context.cleanup("scheduled-proof-stop")
    if (context.run / "stop-proof-intent.json").exists():
        raise CampaignError("proof already stopped; reconcile the exact cleanup path")
    scanner_only = getattr(context, "plan", {}).get("coreDiagnosticScope") == CORE_DIAGNOSTIC_SCOPE
    if "consolidatedScope" in getattr(context, "plan", {}) and action in {
        "account-recovery", "diagnose", "repair", "core-retry"
    }:
        raise CampaignError("consolidated staging permits one account job and one in-window diagnostic")
    if scanner_only and action not in {"account", "core"}:
        raise CampaignError("the scanner diagnostic package only admits account, core and cleanup")
    if action in {"repair", "core-retry"} and getattr(context, "plan", {}).get(
        "scannerObservation"
    ) == SCANNER_OBSERVATION:
        raise CampaignError("successor scope allows one primary upload diagnostic and no retry")
    if action in {"transport", "infrastructure"} and getattr(context, "plan", {}).get(
        "scannerObservation"
    ) != SCANNER_OBSERVATION:
        raise CampaignError("independent operator action requires the sealed successor")
    telemetry_first_enabled = getattr(context, "telemetry_first", False)
    if not telemetry_first_enabled and action == "telemetry-first":
        raise CampaignError("telemetry-first requires its separately approved package")
    if action == "gate" and not telemetry_first_enabled:
        if context.policy.clock() < context.policy.core_by:
            raise CampaignError(
                "evaluate the core and destination gate at its bound cutoff"
            )
        candidates = [
            context.run / f"proof-{p}/accepted.json" for p in ("core", "core-retry")
        ]
        if (
            any(p.is_file() for p in candidates)
            and (context.run / "destination-readiness/accepted.json").is_file()
        ):
            return "acceptance-gate-admitted"
        if (context.run / "destination-readiness/unproved.json").is_file():
            try:
                require_destination_hold(context)
            except (ValueError, TypeError, OSError, KeyError, CampaignError):
                return context.cleanup("privacy-or-integrity-failure")
            try:
                context.admit()
            except (ValueError, OSError, KeyError, CampaignError):
                return context.cleanup("cleanup-protection-lost")
            return "destination-dependent-checks-held-independent-checks-may-continue"
        if (context.run / "scanner-hold.json").is_file():
            context.policy.require_hold()
            return "dependent-checks-held-independent-checks-may-continue"
        return context.cleanup("readiness-missed-without-scanner-hold")
    try:
        context.admit()
    except (ValueError, OSError, KeyError, CampaignError):
        return context.cleanup("cleanup-protection-lost")
    if telemetry_first_enabled and action != "telemetry-first" and not scanner_only:
        try:
            next_stage = telemetry_first.route(context)
        except (ValueError, TypeError, OSError, KeyError, CampaignError):
            return context.cleanup("privacy-or-integrity-failure")
        if next_stage == "telemetry-first-required":
            if context.policy.clock() >= context.policy.core_by:
                return context.cleanup("readiness-missed-without-scanner-hold")
            return next_stage
        if action == "gate":
            return next_stage
    if action in {"diagnose", "repair", "core-retry"}:
        context.policy.require_hold()
    if action == "repair":
        context.policy.check(dependent=True, seconds_needed=1500)
    previously_recorded = {
        "diagnose": "scanner-diagnostic",
        "repair": "scanner-repair",
        "destination-readiness": "destination-readiness",
        "telemetry-first": "telemetry-first",
        "account": "proof-account",
        "account-recovery": "proof-account-recovery",
        "core": "proof-core",
        "core-retry": "proof-core-retry",
        "transport": "proof-transport",
        "infrastructure": "successor-native-categories",
    }.get(action)
    if previously_recorded and (context.run / previously_recorded).exists():
        raise CampaignError("this stage already has a receipt or intent; reconcile it")
    # Admission errors issue no new writes and leave independent work available.
    resume_path = context.policy.resume() if action == "core-retry" else None
    try:
        if action in {"diagnose", "repair"}:
            return collect_and_repair(context, repair=action == "repair")
        if action == "destination-readiness":
            return destination_readiness(context)
        if action == "infrastructure":
            return observe_infrastructure(context)
        if action == "telemetry-first":
            return telemetry_first.run(context, validate_destination_sample, NativeFailure)
        status = dispatch_proof(context, action, resume_path)
        if status == "scanner-paused":
            if getattr(context, "plan", {}).get("scannerObservation") == SCANNER_OBSERVATION:
                hold = context.policy.require_hold()
                if (
                    (context.run / "scanner-in-window/worker-read-start-intent.json").exists()
                    or hold["upload"]["suffix"] != "primary"
                ):
                    return "scanner-paused-independent-operations-remain-available"
            return "scanner-paused-run-diagnose-and-destination-readiness"
        return status
    except (ValueError, OSError, KeyError, CampaignError) as error:
        if isinstance(error, (NativeFailure, DiagnosticUnavailable)) and (
            action in {"diagnose", "infrastructure"}
            or (
                action == "repair"
                and not (
                    context.run / "scanner-repair/assignment-write-intent.json"
                ).exists()
            )
            or (
                action == "destination-readiness"
                and (telemetry_first_enabled or (context.run / "scanner-hold.json").exists())
            )
        ):
            return "read-unproved-independent-operations-remain-available"
        write_new(
            context.run / "proof-hard-failure.json",
            {
                "action": action,
                "errorClass": type(error).__name__,
                "atUtc": utc(datetime.now(UTC)),
            },
        )
        return context.cleanup("unreconciled-operation")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=(
            "account",
            "account-recovery",
            "core",
            "diagnose",
            "repair",
            "core-retry",
            "transport",
            "infrastructure",
            "destination-readiness",
            "telemetry-first",
            "gate",
            "stop",
        ),
    )
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--bound", type=Path, required=True)
    parser.add_argument("--stop-reason", choices=POLICY["cleanupTriggers"])
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not args.execute or (args.stop_reason and args.action != "stop"):
        parser.error(
            "an exact live package, bound inputs, and explicit --execute are required"
        )
    print(
        operate(
            Campaign(args.package, args.bound),
            args.action,
            stop_reason=args.stop_reason,
        )
    )


if __name__ == "__main__":
    main()
