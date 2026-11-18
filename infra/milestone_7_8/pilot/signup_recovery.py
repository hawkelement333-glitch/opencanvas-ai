"""Reconcile one timed-out account probe in the approved private campaign."""

from __future__ import annotations

import argparse
import copy
import json
import secrets
import time
from datetime import UTC, datetime
from pathlib import Path
from infra.milestone_7_8.azure_cli import AzureCliLauncher
from infra.milestone_7_8.campaign import CampaignConfig, CampaignError, parse_utc, utc
from infra.milestone_7_8.pilot_cleanup import (
    SIGNUP_REVIEW_SCHEMA,
    file_hash,
    read,
    validate_live,
    validate_review,
    write_new,
)
from infra.milestone_7_8.signup_reconcile import account_actions, email_binding

TERMINAL = {"Succeeded", "Failed", "Canceled", "Stopped", "Degraded"}


def recover(package: Path, bound: Path) -> None:
    review = validate_review(package, read(bound / "replacement-approval.json"))
    runtime = read(bound / "runtime.json")
    window = validate_live(
        bound / "runtime.json",
        runtime,
        CampaignConfig.from_json(bound / "campaign.json"),
    )
    group = runtime["resourceGroupName"]
    if (
        review["schema"] != SIGNUP_REVIEW_SCHEMA
        or bound.resolve() != Path(review["boundRuntimeDirectory"]).resolve()
        or Path(window["packageDirectory"]).resolve() != package.resolve()
        or group != review["targetResourceGroup"]
        or read(bound / "ledger.json")["phase"] != "billable-started"
        or review.get("signupRecoveryDriverSha256") != file_hash(Path(__file__))
    ):
        raise CampaignError("unbound signup recovery invocation")
    run = package.parent / ("run-" + file_hash(package / "review-package.json")[:8])
    prior = run / "proof-account"
    deadline = parse_utc(window["coreReadyBy"])
    failure = read(prior / "export/account.json")
    original = read(prior / "evidence-terminal.json")
    if (
        failure.get("errorClass") != "ReadTimeout"
        or failure.get("executionId") != original["name"].rsplit("/", 1)[-1]
        or original["properties"]["status"] != "Failed"
        or (prior / "accepted.json").exists()
        or (run / "proof-account-recovery").exists()
    ):
        raise CampaignError("one exact terminal account timeout is required")
    attempted = [
        read(path)
        for path in (prior / "export/account.steps").glob("*-account-intent.json")
    ]
    if not attempted or any(row["action"] != "signup" for row in attempted):
        raise CampaignError("bound original signup intents are required")
    latest = max(parse_utc(row["at"]) for row in attempted)
    uncertain_post = any(
        read(path).get("path") == "/api/v1/auth/signup"
        and parse_utc(read(path)["at"]) >= latest
        and not path.with_name(path.stem + "-result.json").exists()
        for path in (prior / "export/account.steps").glob("*-http-intent.json")
    )
    if not uncertain_post:
        raise CampaignError("no unresolved signup POST in the validated export")
    plan = read(package / "planned-bindings.json")
    scope = f"/subscriptions/{runtime['subscriptionId']}/resourceGroups/{group}"
    app_ids = [plan["applicationResourceId"], plan["workerResourceId"]]
    dispatcher = plan["activityDispatcherResourceId"]
    migration = scope + "/providers/Microsoft.App/jobs/caj-m78p-a712b8c940-migration"
    evidence = scope + "/providers/Microsoft.App/jobs/caj-m78p-a712b8c940-evidence"
    if any(
        not rid.casefold().startswith((scope + "/providers/Microsoft.App/").casefold())
        for rid in (*app_ids, dispatcher, migration, evidence)
    ):
        raise CampaignError("signup recovery target escaped the campaign")
    output = run / "signup-reconciliation"
    output.mkdir(exist_ok=False)
    azure = AzureCliLauncher.resolve()
    seq = 0

    def call(label, args, *, timeout=75):
        nonlocal seq
        remaining = (deadline - datetime.now(UTC)).total_seconds()
        if remaining <= 0 or (run / "stop-proof-intent.json").exists():
            raise CampaignError("signup recovery deadline reached")
        seq += 1
        reply = azure.run(
            (*args, "--subscription", runtime["subscriptionId"], "--output", "json"),
            timeout=min(timeout, remaining),
        )
        write_new(
            output / f"{seq:03d}-{label}.json",
            {
                "exitCode": reply.returncode,
                "stdout": reply.stdout,
                "stderr": reply.stderr,
                "atUtc": utc(datetime.now(UTC)),
            },
        )
        if reply.returncode:
            raise CampaignError(f"{label} requires exact native reconciliation")
        return reply.stdout

    def arm(label, rid, *, method="get", body=None):
        if method != "get":
            write_new(
                output / f"{seq + 1:03d}-{label}-intent.json",
                {
                    "target": rid,
                    "method": method,
                    "atUtc": utc(datetime.now(UTC)),
                    "bodySha256": file_hash(body) if body else None,
                },
            )
        args = (
            "rest",
            "--method",
            method,
            "--url",
            "https://management.azure.com" + rid + "?api-version=2025-01-01",
        )
        if body:
            args += ("--body", "@" + str(body.resolve()))
        raw = call(label, args)
        return json.loads(raw) if raw.strip() else {}

    def inventory(rid):
        result = arm("job-inventory", rid + "/executions")
        if result.get("nextLink") or any(
            row["properties"]["status"] not in TERMINAL for row in result["value"]
        ):
            raise CampaignError("job inventory is incomplete or has active writers")
        return result["value"]

    evidence_inventory = inventory(evidence)
    if (
        len(evidence_inventory) != 1
        or evidence_inventory[0]["id"].casefold() != original["id"].casefold()
        or evidence_inventory[0]["properties"]["status"] != "Failed"
    ):
        raise CampaignError(
            "original evidence execution is not the sole terminal probe"
        )
    inventory(migration)
    if arm("dispatcher-paused", dispatcher)["properties"]["runningStatus"] != "Stopped":
        raise CampaignError("dispatcher must remain paused for signup recovery")
    before = [arm("writer-before", rid)["properties"] for rid in app_ids]
    if any(
        row["runningStatus"] != "Running"
        or not row["latestRevisionName"]
        or not any(
            c["image"].endswith("@" + plan["imageDigest"])
            for c in row["template"]["containers"]
        )
        for row in before
    ):
        raise CampaignError("exact private writer revisions are required")
    for rid in app_ids:
        arm("stop-writer", rid + "/stop", method="post")
    for rid in app_ids:
        while arm("writer-stopped", rid)["properties"]["runningStatus"] != "Stopped":
            time.sleep(4)
    inventory(evidence)

    job = arm("migration-original", migration)
    template = copy.deepcopy(job["properties"]["template"])
    if template.get("volumes") is None:
        template.pop("volumes", None)
    (container,) = template["containers"]
    if (
        job["id"].casefold() != migration.casefold()
        or container["command"] != ["python", "-m", "scripts.migrate_and_grant"]
        or not container["image"].endswith("@" + plan["imageDigest"])
        or [
            row.get("value")
            for row in container["env"]
            if row["name"] == "OPENCANVAS_DATABASE_ROLE"
        ]
        != ["migration"]
    ):
        raise CampaignError(
            "retained migration job command or identity binding changed"
        )
    secrets_map = read(package / "credentials/application-secrets.parameters.json")[
        "parameters"
    ]["applicationSecrets"]["value"]
    nonce = secrets.token_hex(32)
    instruction = {
        "nonce": nonce,
        "emailBindings": {
            "primary": email_binding(secrets_map["opencanvas-pilot-email"], nonce),
            "secondary": email_binding(
                secrets_map["opencanvas-pilot-secondary-email"], nonce
            ),
        },
        "notBefore": read(prior / "export/account.intent.json")["startedAt"],
        "databaseHost": plan["databaseResourceId"].rsplit("/", 1)[-1]
        + ".postgres.database.azure.com",
        "attempt": failure["executionId"],
    }
    source = Path(__file__).resolve().parents[1] / "signup_reconcile.py"
    if (
        file_hash(source)
        != read(package / "manifest.json")["sourceBindings"][
            "infra/milestone_7_8/signup_reconcile.py"
        ]
    ):
        raise CampaignError("signup verifier source differs from the approved snapshot")
    container["command"] = [
        "python",
        "-c",
        source.read_text(encoding="utf-8")
        + "\nimport asyncio, json\n"
        + f"instruction = json.loads({json.dumps(instruction)!r})\n"
        + "print('M78_SIGNUP_SNAPSHOT ' + json.dumps(asyncio.run(native_snapshot(instruction))))",
    ]
    container.pop("args", None)
    body = output / "one-read-only-migration-execution.json"
    write_new(body, template)
    started = arm("snapshot-start", migration + "/start", method="post", body=body)
    execution = started["name"].rsplit("/", 1)[-1]
    if not execution.startswith("caj-m78p-a712b8c940-migration-"):
        raise CampaignError("unexpected native signup snapshot execution")
    while True:
        terminal = arm("snapshot-execution", migration + "/executions/" + execution)
        if terminal["properties"]["status"] == "Succeeded":
            break
        if terminal["properties"]["status"] in TERMINAL:
            raise CampaignError("read-only signup snapshot did not succeed")
        time.sleep(5)
    console = call(
        "snapshot-console",
        (
            "containerapp",
            "job",
            "logs",
            "show",
            "--resource-group",
            group,
            "--name",
            "caj-m78p-a712b8c940-migration",
            "--execution",
            execution,
            "--container",
            "migration",
            "--tail",
            "35",
            "--follow",
            "false",
            "--format",
            "json",
        ),
    )
    rows = [
        json.loads(line)
        for line in console.splitlines()
        if line.lstrip().startswith("{")
    ]
    snapshots = [
        json.loads(log.removeprefix("M78_SIGNUP_SNAPSHOT "))
        for row in rows
        for log in [row.get("Log", "")]
        if log.startswith("M78_SIGNUP_SNAPSHOT ")
    ]
    if len(snapshots) != 1:
        raise CampaignError("exact read-only native signup evidence is missing")
    snapshot = snapshots[0]
    if (
        snapshot["executionId"] != execution
        or snapshot["attempt"] != failure["executionId"]
        or snapshot["seedMatched"] is not True
        or "hold"
        in account_actions(
            snapshot["slots"],
            writers_quiesced=snapshot["otherDatabaseClients"] == 0,
        ).values()
    ):
        write_new(output / "hold.json", snapshot)
        raise CampaignError("signup remains ambiguous; preserve evidence and clean up")
    for rid, baseline in zip(app_ids, before, strict=True):
        arm("start-writer", rid + "/start", method="post")
        while True:
            state = arm("writer-restored", rid)["properties"]
            if state["runningStatus"] == "Running":
                if state["latestRevisionName"] != baseline["latestRevisionName"]:
                    raise CampaignError("writer returned on a different revision")
                break
            time.sleep(4)
    write_new(
        output / "accepted.json",
        {
            "writersQuiesced": True,
            "snapshot": snapshot,
            "priorExecution": failure["executionId"],
            "bindingsSha256": file_hash(package / "planned-bindings.json"),
            "authorizationSha256": file_hash(bound / "approval.json"),
            "atUtc": utc(datetime.now(UTC)),
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", required=True, type=Path)
    parser.add_argument("--bound", required=True, type=Path)
    parser.add_argument("--execute", action="store_true", required=True)
    arguments = parser.parse_args()
    recover(arguments.package, arguments.bound)
