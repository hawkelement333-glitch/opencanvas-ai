"""Application password-reset proof, requiring a separately obtained native inbox receipt.

This module never sends SMTP directly. It calls the production application and
accepts delivery only from the exact approved receiver's raw message/receipt.
Raw MIME, token and passwords stay in private inputs and are never in results.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
from datetime import UTC, datetime
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
from pydantic import SecretStr

from infra.milestone_7_8.pilot_application_probe import Api, Journal, require
from infra.milestone_7_8.pilot_validation import (
    _private_host,
    admit_runtime_bindings,
    authorize,
    digest,
    utc,
    write_new,
)

OPERATIONS = (
    "password-reset-request",
    "password-reset-confirm",
    "password-reset-expiry",
)


def received_token(
    raw_message: bytes, native_receipt: dict, request_receipt: dict, plan: dict
) -> SecretStr:
    config = plan["passwordResetProof"]
    require(len(raw_message) <= 64_000, "bounded native message required")
    require(
        native_receipt.get("receiverId") == config["receiverId"]
        and native_receipt.get("source") == "native-inbox"
        and native_receipt.get("rawMessageSha256")
        == hashlib.sha256(raw_message).hexdigest()
        and native_receipt.get("recipient") == config["recipient"]
        and utc(native_receipt["receivedAt"]) >= utc(request_receipt["requestedAt"]),
        "native inbox receipt does not bind the approved request/receiver",
    )
    message = BytesParser(policy=policy.default).parsebytes(raw_message)
    require(
        len(message.get_all("Message-ID", [])) == 1
        and message["Message-ID"] == native_receipt.get("messageId")
        and message["Subject"] == "Reset your SolarPlexus Mobius password"
        and getaddresses(message.get_all("To", [])) == [("", config["recipient"])]
        and getaddresses(message.get_all("From", [])) == [("", config["sender"])],
        "received message identity/recipient is not the approved application reset",
    )
    body = message.get_body(preferencelist=("plain",))
    require(body is not None, "native plain message body required")
    assert body is not None
    text = body.get_content()
    require(isinstance(text, str), "plain reset body required")
    links = re.findall(r"https?://[^\s]+", str(text))
    require(len(links) == 1, "exactly one reset URL required")
    actual = urlparse(links[0])
    expected = urlparse(config["appOrigin"])
    query = parse_qs(actual.query)
    require(
        actual.scheme == "https"
        and actual.netloc == expected.netloc
        and actual.path == "/reset-password"
        and not actual.fragment
        and not actual.username
        and not actual.password
        and set(query) == {"token"}
        and len(query["token"]) == 1
        and re.fullmatch(r"[A-Za-z0-9_-]{43}", query["token"][0]) is not None,
        "reset token origin or shape differs from the application contract",
    )
    return SecretStr(query["token"][0])


async def request_reset(api: Api, plan: dict) -> dict:
    config = plan["passwordResetProof"]
    require(
        os.environ["OPENCANVAS_PILOT_EMAIL"] == config["recipient"],
        "only the approved synthetic account may receive reset evidence",
    )
    user = await api.signin()
    started = datetime.now(UTC).isoformat()
    response = await api.request(
        "POST",
        "/api/v1/auth/password-reset/request",
        secret=True,
        data={"email": config["recipient"]},
    )
    require(
        response.get("accepted") is True and not response.get("developmentToken"),
        "managed API must not return reset tokens",
    )
    return {
        "requestedAt": started,
        "expectedUserId": user["id"],
        "recipientSha256": hashlib.sha256(config["recipient"].encode()).hexdigest(),
        "delivery": "unproved until native inbox receipt",
    }


async def confirm_reset(
    api: Api, plan: dict, request_receipt: dict, native_receipt: dict, raw: bytes
) -> dict:
    token = received_token(raw, native_receipt, request_receipt, plan)
    original = await api.signin()
    require(
        original["id"] == request_receipt["expectedUserId"], "reset account changed"
    )
    replacement = os.environ["OPENCANVAS_PILOT_REPLACEMENT_PASSWORD"]
    require(
        replacement != os.environ["OPENCANVAS_PILOT_PASSWORD"],
        "replacement must differ",
    )
    await api.request(
        "POST",
        "/api/v1/auth/password-reset/confirm",
        secret=True,
        data={"token": token.get_secret_value(), "password": replacement},
        statuses=(204,),
    )
    await api.request("GET", "/api/v1/auth/me", secret=True, statuses=(401,))
    await api.request(
        "POST",
        "/api/v1/auth/password-reset/confirm",
        secret=True,
        data={"token": token.get_secret_value(), "password": replacement},
        statuses=(400,),
    )
    await api.request(
        "POST",
        "/api/v1/auth/signin",
        secret=True,
        data={
            "email": plan["passwordResetProof"]["recipient"],
            "password": os.environ["OPENCANVAS_PILOT_PASSWORD"],
        },
        statuses=(401,),
    )
    changed = await api.request(
        "POST",
        "/api/v1/auth/signin",
        secret=True,
        data={
            "email": plan["passwordResetProof"]["recipient"],
            "password": replacement,
        },
    )
    require(
        changed["user"]["id"] == original["id"],
        "new credentials selected another account",
    )
    return {
        "assertions": {
            "applicationRequestToNativeInbox": "accepted",
            "singleUseReset": "accepted",
            "oldSessionsRevoked": "accepted",
            "oldPasswordRejected": "accepted",
            "newPasswordAccepted": "accepted",
        },
        "nativeReceiptSha256": hashlib.sha256(
            json.dumps(native_receipt, sort_keys=True).encode()
        ).hexdigest(),
        "requestExecutionId": request_receipt["executionId"],
        "messageIdSha256": hashlib.sha256(
            native_receipt["messageId"].encode()
        ).hexdigest(),
        "nextCredential": "replacement secret; reconcile before any later account operation",
    }


async def reject_expired_reset(
    api: Api,
    plan: dict,
    request_receipt: dict,
    native_receipt: dict,
    raw: bytes,
    *,
    confirmed_receipt: dict,
    now: datetime | None = None,
) -> dict:
    token = received_token(raw, native_receipt, request_receipt, plan)
    require(
        request_receipt["executionId"] != confirmed_receipt["requestExecutionId"]
        and hashlib.sha256(native_receipt["messageId"].encode()).hexdigest()
        != confirmed_receipt["messageIdSha256"],
        "expiry proof needs a separate never-confirmed reset request",
    )
    # response completion + configured lifetime is conservative versus creation;
    # metadata comes from the bound request result, not a client-chosen token age.
    completed = utc(request_receipt["finishedAt"])
    elapsed = ((now or datetime.now(UTC)) - completed).total_seconds()
    require(
        elapsed > plan["passwordResetProof"]["ttlMinutes"] * 60,
        "actual server token lifetime has not elapsed",
    )
    await api.request(
        "POST",
        "/api/v1/auth/password-reset/confirm",
        secret=True,
        data={
            "token": token.get_secret_value(),
            "password": os.environ["OPENCANVAS_PILOT_REPLACEMENT_PASSWORD"],
        },
        statuses=(400,),
    )
    user = await api.signin()
    require(
        user["id"] == request_receipt["expectedUserId"], "expired token changed account"
    )
    return {"assertions": {"expiredTokenRejectedWithoutPasswordChange": "accepted"}}


async def run(args: argparse.Namespace) -> dict:
    _, plan, deadline = authorize(
        args.bundle, args.authorization, args.bindings, args.operation
    )
    require(
        args.execute
        and args.execution_id == os.environ.get("CONTAINER_APP_JOB_EXECUTION_NAME"),
        "actual authorized managed job required",
    )
    runtime = admit_runtime_bindings(
        plan,
        json.loads(args.runtime_readbacks.read_text()),
        plan_sha256=digest(args.bindings),
    )
    plan = runtime
    require(
        plan.get("passwordResetProof", {}).get("ttlMinutes") == 30
        and plan.get("frontendOrigin") is not None
        and plan["passwordResetProof"].get("appOrigin") == plan["frontendOrigin"],
        "native frontend origin and unchanged 30-minute reset contract required",
    )
    host = urlparse(runtime["apiBaseUrl"]).hostname
    require(host is not None, "private application endpoint required")
    assert host is not None
    _private_host(host)
    journal = Journal(args.output, args.execution_id, args.operation, plan, deadline)
    async with httpx.AsyncClient(
        base_url=runtime["apiBaseUrl"],
        timeout=45,
        trust_env=False,
        follow_redirects=False,
    ) as client:
        api = Api(client, journal, args.execution_id)
        if args.operation == "password-reset-request":
            return journal.finish(await request_reset(api, plan))
        require(
            args.request_receipt is not None and args.inbox_receipt is not None
            and args.raw_message is not None
            and (args.operation != "password-reset-expiry" or args.confirmed_receipt is not None),
            "confirmation or expiry requires the bound native inbox and request receipts",
        )
        request = json.loads(args.request_receipt.read_text())
        require(
            request.get("operation") == "password-reset-request"
            and request.get("sourceCommit") == plan["sourceCommit"]
            and request.get("imageDigest") == plan["imageDigest"],
            "exact request receipt required",
        )
        native = json.loads(args.inbox_receipt.read_text())
        raw = args.raw_message.read_bytes()
        if args.operation == "password-reset-confirm":
            return journal.finish(await confirm_reset(api, plan, request, native, raw))
        return journal.finish(
            await reject_expired_reset(
                api,
                plan,
                request,
                native,
                raw,
                confirmed_receipt=json.loads(args.confirmed_receipt.read_text()),
            )
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=OPERATIONS)
    for name in ("bundle", "authorization", "bindings", "runtime-readbacks", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in (
        "request-receipt",
        "inbox-receipt",
        "raw-message",
        "confirmed-receipt",
    ):
        parser.add_argument("--" + name, type=Path)
    parser.add_argument("--execution-id", required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except Exception as error:
        if not args.output.exists():
            write_new(
                args.output,
                {
                    "operation": args.operation,
                    "status": "failed",
                    "errorClass": type(error).__name__,
                    "managedAcceptance": "unproved",
                    "reconcileBeforeRetry": True,
                },
            )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
