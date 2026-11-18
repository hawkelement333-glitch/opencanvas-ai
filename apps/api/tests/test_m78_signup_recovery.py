import gzip
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from infra.milestone_7_8.pilot_application_probe import (
    Api,
    Journal,
    read_runtime_evidence,
    run_account,
)
from infra.milestone_7_8.pilot_cleanup import SIGNUP_REVIEW_SCHEMA, approved_window
from infra.milestone_7_8.signup_reconcile import (
    SLOTS,
    account_actions,
    email_binding,
    inspect_signup,
)
from sqlalchemy import delete, update

from opencanvas_api.db.models import SYSTEM_USER_ID, DomainEventOutbox, User

EMAILS = {"primary": "pilot@example.test", "secondary": "isolation@example.test"}
NONCE = "ef" * 32


@pytest.mark.parametrize(
    ("case", "states", "actions"),
    [
        ("seed-only", ("absent", "absent"), ("retry", "retry")),
        ("primary-complete", ("complete", "absent"), ("resume", "retry")),
        ("both-complete", ("complete", "complete"), ("resume", "resume")),
        ("missing-outbox", ("ambiguous", "absent"), ("hold", "hold")),
        ("different-account", ("ambiguous", "ambiguous"), ("hold", "hold")),
        ("seed-mismatch", ("ambiguous", "ambiguous"), ("hold", "hold")),
    ],
)
async def test_signup_snapshot_uses_actual_committed_signup_effects(
    database, client, api_prefix, case, states, actions
):
    not_before = datetime.now(UTC) - timedelta(seconds=5)
    if case != "seed-mismatch":
        async with database.sessions() as session:
            await session.execute(
                update(User)
                .where(User.id == SYSTEM_USER_ID)
                .values(
                    email="migration-principal@mobius.invalid",
                    email_normalized="migration-principal@mobius.invalid",
                    password_hash="login-disabled",
                    display_name="Migrated local data",
                    settings_payload={"migrationPrincipal": True},
                )
            )
            await session.commit()
    ids = {}
    if case in {"primary-complete", "both-complete", "missing-outbox", "different-account"}:
        slots = SLOTS if case == "both-complete" else ("primary",)
        for slot in slots:
            response = await client.post(
                f"{api_prefix}/auth/signup",
                json={
                    "email": "different@example.test"
                    if case == "different-account"
                    else EMAILS[slot],
                    "password": "Local-Test-Password-7",
                    "displayName": SLOTS[slot],
                },
            )
            assert response.status_code == 201
            ids[slot] = response.json()["user"]["id"]
    if case == "missing-outbox":
        async with database.sessions() as session:
            await session.execute(delete(DomainEventOutbox))
            await session.commit()
    async with database.sessions() as session:
        snapshot = await inspect_signup(
            session,
            {slot: email_binding(email, NONCE) for slot, email in EMAILS.items()},
            NONCE,
            not_before,
        )
    assert snapshot["seedMatched"] is (case != "seed-mismatch")
    assert [result["state"] for result in snapshot["slots"].values()] == list(states)
    assert account_actions(snapshot["slots"], writers_quiesced=True) == dict(
        zip(SLOTS, actions, strict=True)
    )
    assert account_actions(snapshot["slots"], writers_quiesced=False) == dict.fromkeys(
        SLOTS, "hold"
    )
    for slot, state in zip(SLOTS, states, strict=True):
        if state == "complete":
            assert snapshot["slots"][slot]["userId"] == ids[slot]


@pytest.mark.parametrize("ready", [True, False])
async def test_recovery_checks_readiness_then_signs_in_existing_and_creates_absent(
    tmp_path, monkeypatch, ready
):
    existing, new = str(uuid4()), str(uuid4())
    observed = []

    def reply(request):
        observed.append((request.method, request.url.path))
        if request.url.path.endswith("/ready"):
            return httpx.Response(
                200,
                json={
                    "status": "ready" if ready else "unavailable",
                    "service": "opencanvas-api",
                },
            )
        if request.url.path.endswith("/signin"):
            return httpx.Response(200, json={"user": {"id": existing}, "csrfToken": "local"})
        return httpx.Response(201, json={"user": {"id": new}})

    for slot, prefix in (
        ("primary", "OPENCANVAS_PILOT_"),
        ("secondary", "OPENCANVAS_PILOT_SECONDARY_"),
    ):
        monkeypatch.setenv(prefix + "EMAIL", EMAILS[slot])
        monkeypatch.setenv(prefix + "PASSWORD", "Local-Test-Password-7")
    bindings = dict(
        imageDigest="fixture", sourceCommit="fixture", release="fixture", deployment="fixture"
    )
    journal = Journal(
        tmp_path / "account.json",
        "local",
        "account",
        bindings,
        datetime.now(UTC) + timedelta(minutes=1),
    )
    snapshot = {
        "seedMatched": True,
        "otherDatabaseClients": 0,
        "slots": {
            "primary": {"state": "complete", "userId": existing},
            "secondary": {"state": "absent"},
        },
    }
    async with httpx.AsyncClient(
        base_url="https://fixture.example.test",
        transport=httpx.MockTransport(reply),
    ) as client:
        api = Api(client, journal, "local")
        if ready:
            result = await run_account(api, dict(snapshot=snapshot, writersQuiesced=True))
            assert result["userId"] == existing and result["secondaryUserId"] == new
            assert result["accountActions"] == {"primary": "resume", "secondary": "retry"}
            assert observed == [
                ("GET", "/api/v1/health/ready"),
                ("POST", "/api/v1/auth/signin"),
                ("POST", "/api/v1/auth/signup"),
            ]
        else:
            with pytest.raises(ValueError, match="private API readiness"):
                await run_account(api, dict(snapshot=snapshot, writersQuiesced=True))
            assert observed == [("GET", "/api/v1/health/ready")]


def test_signup_window_uses_whole_minute_and_leaves_provisioning_at_two_hours():
    approval = dict(approvedAt="2030-01-01T00:00:37Z", executionStartAt="2030-01-01T00:01:00Z")
    result = approved_window(
        dict(
            schema=SIGNUP_REVIEW_SCHEMA, executionStartRule="first-whole-utc-minute-after-approval"
        ),
        approval,
    )
    assert result["readyBy"] == "2030-01-01T02:01:00Z"
    assert result["coreReadyBy"] == "2030-01-01T03:01:00Z"
    assert result["stopProofBy"] == "2030-01-01T11:01:00Z"
    assert result["automationBindingExpiresAt"] == "2030-01-01T12:01:00Z"
    assert result["operatorCleanupExpiresAt"] == "2030-01-01T13:01:00Z"


def test_compact_readback_transport_roundtrips_and_bounds_expansion(tmp_path):
    path = tmp_path / "native-readbacks.json.gz"
    path.write_bytes(gzip.compress(b'{"readback":{"status":200}}', mtime=0))
    assert read_runtime_evidence(path) == {"readback": {"status": 200}}
    path.write_bytes(gzip.compress(b" " * 250_001, mtime=0))
    with pytest.raises(ValueError, match="expanded native readbacks"):
        read_runtime_evidence(path)
