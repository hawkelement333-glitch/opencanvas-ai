from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from opencanvas_api.core.config import Settings, get_settings
from opencanvas_api.db.models import User, UserSession
from opencanvas_api.db.session import Database

JsonObject = dict[str, Any]


def _enable_real_auth(app: FastAPI) -> Settings:
    current = cast(Settings, app.dependency_overrides[get_settings]())
    settings = current.model_copy(
        update={
            "auth_test_bypass": False,
            "session_secret": "test-session-secret-that-is-long-enough-2026",
            "auth_requests_per_ip_per_minute": 100,
        }
    )
    app.dependency_overrides[get_settings] = lambda: settings
    return settings


async def _sign_up(
    client: httpx.AsyncClient,
    prefix: str,
    *,
    email: str,
    display_name: str,
) -> JsonObject:
    response = await client.post(
        f"{prefix}/auth/signup",
        json={
            "email": email,
            "password": "Correct-Horse-2026",
            "displayName": display_name,
        },
    )
    assert response.status_code == 201, response.text
    return cast(JsonObject, response.json())


def _csrf(session: JsonObject) -> dict[str, str]:
    return {"X-CSRF-Token": cast(str, session["csrfToken"])}


@pytest.mark.security
async def test_authentication_csrf_generic_failures_and_session_expiration(
    app: FastAPI,
    database: Database,
    api_prefix: str,
) -> None:
    settings = _enable_real_auth(app)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as user:
        await _sign_up(
            user,
            api_prefix,
            email="session-owner@example.test",
            display_name="Session Owner",
        )
        me = await user.get(f"{api_prefix}/auth/me")
        assert me.status_code == 200
        assert me.json()["email"] == "session-owner@example.test"
        assert settings.session_cookie_name in user.cookies

        missing_csrf = await user.post(f"{api_prefix}/auth/signout")
        assert missing_csrf.status_code == 403
        assert missing_csrf.json()["code"] == "csrf_validation_failed"

        wrong_email = await user.post(
            f"{api_prefix}/auth/signin",
            json={"email": "absent@example.test", "password": "Wrong-Password-2026"},
        )
        wrong_password = await user.post(
            f"{api_prefix}/auth/signin",
            json={"email": "session-owner@example.test", "password": "Wrong-Password-2026"},
        )
        assert wrong_email.status_code == wrong_password.status_code == 401
        assert (
            wrong_email.json()
            == wrong_password.json()
            == {
                "code": "invalid_credentials",
                "detail": "The email address or password is invalid.",
            }
        )

        async with database.sessions() as db_session:
            stored = await db_session.scalar(
                select(UserSession).where(UserSession.token_hash.is_not(None))
            )
            assert stored is not None
            stored.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await db_session.commit()
        expired = await user.get(f"{api_prefix}/auth/me")
        assert expired.status_code == 401
        assert expired.json()["code"] == "session_expired"

        signed_in = await user.post(
            f"{api_prefix}/auth/signin",
            json={
                "email": "session-owner@example.test",
                "password": "Correct-Horse-2026",
            },
        )
        assert signed_in.status_code == 200
        signed_out = await user.post(
            f"{api_prefix}/auth/signout", headers=_csrf(cast(JsonObject, signed_in.json()))
        )
        assert signed_out.status_code == 204
        assert (await user.get(f"{api_prefix}/auth/me")).status_code == 401

        reset_requested = await user.post(
            f"{api_prefix}/auth/password-reset/request",
            json={"email": "session-owner@example.test"},
        )
        assert reset_requested.status_code == 200
        reset_token = reset_requested.json()["developmentToken"]
        assert reset_token
        reset = await user.post(
            f"{api_prefix}/auth/password-reset/confirm",
            json={"token": reset_token, "password": "New-Correct-Horse-2026"},
        )
        assert reset.status_code == 204
        old_password = await user.post(
            f"{api_prefix}/auth/signin",
            json={
                "email": "session-owner@example.test",
                "password": "Correct-Horse-2026",
            },
        )
        assert old_password.status_code == 401
        new_sign_in = await user.post(
            f"{api_prefix}/auth/signin",
            json={
                "email": "session-owner@example.test",
                "password": "New-Correct-Horse-2026",
            },
        )
        assert new_sign_in.status_code == 200
        lifecycle_headers = _csrf(cast(JsonObject, new_sign_in.json()))
        updated = await user.patch(
            f"{api_prefix}/account",
            json={"displayName": "Updated Owner"},
            headers=lifecycle_headers,
        )
        assert updated.status_code == 200
        assert updated.json()["displayName"] == "Updated Owner"
        export = await user.post(f"{api_prefix}/account/export", headers=lifecycle_headers)
        assert export.status_code == 202
        assert export.json()["status"] == "requested"
        wrong_delete = await user.request(
            "DELETE",
            f"{api_prefix}/account",
            json={"password": "Wrong-Password-2026", "confirmation": "DELETE MY ACCOUNT"},
            headers=lifecycle_headers,
        )
        assert wrong_delete.status_code == 400
        deleted = await user.request(
            "DELETE",
            f"{api_prefix}/account",
            json={
                "password": "New-Correct-Horse-2026",
                "confirmation": "DELETE MY ACCOUNT",
            },
            headers=lifecycle_headers,
        )
        assert deleted.status_code == 204
        assert (await user.get(f"{api_prefix}/auth/me")).status_code == 401
        async with database.sessions() as db_session:
            assert (
                await db_session.scalar(
                    select(User.id).where(User.email_normalized == "session-owner@example.test")
                )
                is None
            )


@pytest.mark.security
async def test_two_users_cannot_cross_workspace_canvas_document_file_or_trace_boundaries(
    app: FastAPI,
    api_prefix: str,
) -> None:
    _enable_real_auth(app)
    transport = httpx.ASGITransport(app=app)
    async with (
        httpx.AsyncClient(transport=transport, base_url="http://test") as alice,
        httpx.AsyncClient(transport=transport, base_url="http://test") as bob,
    ):
        alice_session = await _sign_up(
            alice, api_prefix, email="alice@example.test", display_name="Alice"
        )
        bob_session = await _sign_up(bob, api_prefix, email="bob@example.test", display_name="Bob")
        alice_headers = _csrf(alice_session)
        bob_headers = _csrf(bob_session)
        alice_workspace = (await alice.get(f"{api_prefix}/workspaces")).json()[0]
        bob_workspace = (await bob.get(f"{api_prefix}/workspaces")).json()[0]
        assert alice_workspace["id"] != bob_workspace["id"]

        alice_canvas_response = await alice.post(
            f"{api_prefix}/canvases",
            json={"name": "Alice private", "workspaceId": alice_workspace["id"]},
            headers=alice_headers,
        )
        bob_canvas_response = await bob.post(
            f"{api_prefix}/canvases",
            json={"name": "Bob private", "workspaceId": bob_workspace["id"]},
            headers=bob_headers,
        )
        assert alice_canvas_response.status_code == bob_canvas_response.status_code == 201
        alice_canvas = alice_canvas_response.json()
        bob_canvas = bob_canvas_response.json()

        alice_node_response = await alice.post(
            f"{api_prefix}/canvases/{alice_canvas['id']}/nodes",
            json={
                "type": "note",
                "title": "Alice evidence",
                "text": "Private launch evidence.",
                "position": {"x": 10, "y": 20},
            },
            headers=alice_headers,
        )
        assert alice_node_response.status_code == 201
        alice_node = alice_node_response.json()
        uploaded = await alice.post(
            f"{api_prefix}/canvases/{alice_canvas['id']}/documents",
            files={"file": ("private.txt", b"Alice private source.", "text/plain")},
            data={"x": "400", "y": "20"},
            headers=alice_headers,
        )
        assert uploaded.status_code == 201, uploaded.text
        alice_document = uploaded.json()["document"]
        execution = await alice.post(
            f"{api_prefix}/canvases/{alice_canvas['id']}/ai",
            json={
                "instruction": "Restate the private launch evidence.",
                "selectedNodeIds": [alice_node["id"]],
            },
            headers=alice_headers,
        )
        assert execution.status_code == 201, execution.text

        denials = [
            await bob.get(f"{api_prefix}/workspaces/{alice_workspace['id']}"),
            await bob.get(f"{api_prefix}/canvases/{alice_canvas['id']}"),
            await bob.get(f"{api_prefix}/canvases/{alice_canvas['id']}/snapshot"),
            await bob.get(f"{api_prefix}/documents/{alice_document['id']}"),
            await bob.get(f"{api_prefix}/documents/{alice_document['id']}/file"),
            await bob.get(f"{api_prefix}/traces/{execution.json()['traceId']}"),
            await bob.post(
                f"{api_prefix}/canvases/{alice_canvas['id']}/ai/{execution.json()['requestId']}"
                "/rerun-original",
                headers=bob_headers,
            ),
        ]
        assert all(response.status_code == 404 for response in denials)

        cross_node = await bob.post(
            f"{api_prefix}/canvases/{bob_canvas['id']}/ai",
            json={
                "instruction": "Use Alice's node.",
                "selectedNodeIds": [alice_node["id"]],
            },
            headers=bob_headers,
        )
        assert cross_node.status_code == 400
        assert cross_node.json()["code"] == "invalid_selected_nodes"
        alice_can_still_read = await alice.get(
            f"{api_prefix}/documents/{alice_document['id']}/file"
        )
        assert alice_can_still_read.status_code == 200
        assert alice_can_still_read.content == b"Alice private source."

        listed_for_bob = await bob.get(
            f"{api_prefix}/canvases", params={"workspaceId": alice_workspace["id"]}
        )
        assert listed_for_bob.status_code == 404
        assert uuid.UUID(alice_canvas["id"]) != uuid.UUID(bob_canvas["id"])


@pytest.mark.security
async def test_authentication_endpoints_enforce_per_ip_rate_limit(
    app: FastAPI,
    api_prefix: str,
) -> None:
    current = _enable_real_auth(app)
    limited = current.model_copy(update={"auth_requests_per_ip_per_minute": 2})
    app.dependency_overrides[get_settings] = lambda: limited
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await _sign_up(client, api_prefix, email="limited@example.test", display_name="Limited")
        first_failure = await client.post(
            f"{api_prefix}/auth/signin",
            json={"email": "limited@example.test", "password": "Wrong-Password-2026"},
        )
        limited_response = await client.post(
            f"{api_prefix}/auth/signin",
            json={"email": "limited@example.test", "password": "Wrong-Password-2026"},
        )
    assert first_failure.status_code == 401
    assert limited_response.status_code == 429
    assert limited_response.json()["code"] == "rate_limit_exceeded"
    assert int(limited_response.headers["Retry-After"]) >= 1
