from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta
from email import policy
from email.parser import BytesParser

import httpx
import pytest
from infra.milestone_7_8.password_reset_validation import (
    confirm_reset,
    received_token,
    reject_expired_reset,
    request_reset,
)
from infra.milestone_7_8.pilot_application_probe import Api, Journal
from sqlalchemy import select

from opencanvas_api.core.config import AppMode, get_settings
from opencanvas_api.db.models import PasswordResetToken


async def test_application_to_smtp_inbox_reset_replay_sessions_and_expiry(
    app, database, tmp_path, monkeypatch
):
    inbox = []

    async def smtp(reader, writer):
        writer.write(b"220 local-test ESMTP\r\n")
        await writer.drain()
        while line := await reader.readline():
            verb = line.split(b" ", 1)[0].strip().upper()
            if verb in (b"EHLO", b"HELO"):
                writer.write(b"250-local-test\r\n250 SIZE 64000\r\n")
            elif verb in (b"MAIL", b"RCPT", b"RSET", b"NOOP"):
                writer.write(b"250 OK\r\n")
            elif verb == b"DATA":
                writer.write(b"354 End with dot\r\n")
                await writer.drain()
                raw = bytearray()
                while (data := await reader.readline()) != b".\r\n":
                    if not data:
                        raise AssertionError("SMTP peer disconnected before receipt")
                    raw.extend(data[1:] if data.startswith(b"..") else data)
                inbox.append((bytes(raw), datetime.now(UTC).isoformat()))
                writer.write(b"250 committed local-inbox\r\n")
            elif verb == b"QUIT":
                writer.write(b"221 Bye\r\n")
                await writer.drain()
                break
            else:
                writer.write(b"500 Unknown\r\n")
            await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(smtp, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    current = app.dependency_overrides[get_settings]()
    settings = current.model_copy(
        update={
            "app_mode": AppMode.STAGING,
            "auth_test_bypass": False,
            "session_secret": "local-reset-test-session-secret-2026-independent",
            "password_reset_provider": "smtp",
            "smtp_host": "127.0.0.1",
            "smtp_port": port,
            "smtp_from_address": "sender@pilot.test",
            "smtp_starttls": False,
            "smtp_username": None,
            "smtp_password": None,
            "app_url": "https://pilot.test",
            "auth_requests_per_ip_per_minute": 100,
        }
    )
    app.dependency_overrides[get_settings] = lambda: settings
    monkeypatch.setenv("OPENCANVAS_PILOT_EMAIL", "recipient@pilot.test")
    monkeypatch.setenv("OPENCANVAS_PILOT_PASSWORD", "Initial-Horse-2026-Secret")
    monkeypatch.setenv("OPENCANVAS_PILOT_REPLACEMENT_PASSWORD", "Replacement-Horse-2026-Secret")
    plan = {
        "sourceCommit": "a" * 40,
        "imageDigest": "sha256:" + "b" * 64,
        "release": "local",
        "deployment": "local",
        "passwordResetProof": {
            "receiverId": "local-test-inbox",
            "recipient": "recipient@pilot.test",
            "sender": "sender@pilot.test",
            "appOrigin": "https://pilot.test",
            "ttlMinutes": 30,
        },
    }

    def receipt(raw, received):
        return {
            "source": "native-inbox",
            "receiverId": "local-test-inbox",
            "recipient": "recipient@pilot.test",
            "receivedAt": received,
            "rawMessageSha256": hashlib.sha256(raw).hexdigest(),
            "messageId": BytesParser(policy=policy.default).parsebytes(raw)["Message-ID"],
        }

    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://pilot.test"
        ) as client:
            signup = await client.post(
                "/api/v1/auth/signup",
                json={
                    "email": "recipient@pilot.test",
                    "password": "Initial-Horse-2026-Secret",
                    "displayName": "Local synthetic fixture",
                },
            )
            assert signup.status_code == 201
            journal = Journal(
                tmp_path / "request.json",
                "local-request-1",
                "password-reset-request",
                plan,
                datetime.now(UTC) + timedelta(hours=1),
            )
            api = Api(client, journal, "local-request-1")
            request = journal.finish(await request_reset(api, plan))
            assert len(inbox) == 1
            raw, received = inbox[0]
            native = receipt(raw, received)
            confirmation = await confirm_reset(api, plan, request, native, raw)
            assert set(confirmation["assertions"].values()) == {"accepted"}
            # A distinct untouched reset is needed for expiry, not replay of the used token.
            monkeypatch.setenv("OPENCANVAS_PILOT_PASSWORD", "Replacement-Horse-2026-Secret")
            monkeypatch.setenv("OPENCANVAS_PILOT_REPLACEMENT_PASSWORD", "Never-Applied-Horse-2026")
            pending = await request_reset(api, plan)
            pending.update(executionId="local-request-2", finishedAt=datetime.now(UTC).isoformat())
            raw2, received2 = inbox[1]
            async with database.sessions() as session:
                token = await session.scalar(
                    select(PasswordResetToken).where(PasswordResetToken.used_at.is_(None))
                )
                assert token is not None
                token.expires_at = datetime.now(UTC) - timedelta(seconds=1)
                await session.commit()
            expired = await reject_expired_reset(
                api,
                plan,
                pending,
                receipt(raw2, received2),
                raw2,
                confirmed_receipt=confirmation,
                now=datetime.now(UTC) + timedelta(minutes=31),
            )
            assert expired["assertions"]["expiredTokenRejectedWithoutPasswordChange"] == "accepted"
            saved = "".join(p.read_text() for p in tmp_path.rglob("*.json"))
            assert "Initial-Horse" not in saved and "Replacement-Horse" not in saved
            assert received_token(raw, native, request, plan).get_secret_value() not in saved
            for changed in (
                {**native, "recipient": "other@pilot.test"},
                {**native, "rawMessageSha256": "0" * 64},
                {**native, "receiverId": "unapproved-inbox"},
            ):
                with pytest.raises(ValueError):
                    received_token(raw, changed, request, plan)
            assert "rawMessage" not in json.dumps(confirmation)
    finally:
        server.close()
        await server.wait_closed()
