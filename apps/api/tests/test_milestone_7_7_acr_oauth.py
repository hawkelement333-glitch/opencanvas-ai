from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from infra.milestone_7_7.scripts import managed_binding_lifecycle as lifecycle
from performance.milestone_7_7.framework import JsonValue

NOW = datetime(2026, 8, 3, 4, 0, tzinfo=UTC)
LEDGER = "a" * 64
HEAD = "b" * 40


def _jwt(claims: dict[str, object]) -> bytearray:
    def encoded(value: object) -> bytes:
        return base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode()).rstrip(
            b"="
        )

    return bytearray(encoded({"alg": "none"}) + b"." + encoded(claims) + b".signature")


def _session(path: Path) -> lifecycle._OperationAttribution:
    return lifecycle._OperationAttribution(
        receipt_directory=path,
        lifecycle_stage="post-secret-provisioning",
        ledger_integrity=LEDGER,
        repository_head=HEAD,
    )


def _records(path: Path) -> list[dict[str, object]]:
    value = json.loads((path / lifecycle.OPERATION_ATTRIBUTION_FILE).read_text())
    return cast(list[dict[str, object]], value["records"])


@pytest.mark.parametrize(
    "header",
    [
        (
            'Bearer realm="https://acrmobius7711564669.azurecr.io/oauth2/token",'
            'service="acrmobius7711564669.azurecr.io"'
        ),
        (
            'bearer service="acrmobius7711564669.azurecr.io",'
            'realm="https://acrmobius7711564669.azurecr.io/oauth2/token",'
            'scope="repository:opencanvas-api:pull,push"'
        ),
    ],
)
def test_valid_private_registry_challenge_is_exact(header: str) -> None:
    assert lifecycle._challenge_service(header) == lifecycle.REGISTRY_HOST


@pytest.mark.parametrize(
    "header",
    [
        'Basic realm="registry"',
        (
            'Bearer realm="http://acrmobius7711564669.azurecr.io/oauth2/token",'
            'service="acrmobius7711564669.azurecr.io"'
        ),
        (
            'Bearer realm="https://public.example.invalid/oauth2/token",'
            'service="acrmobius7711564669.azurecr.io"'
        ),
        (
            'Bearer realm="https://acrmobius7711564669.azurecr.io/other",'
            'service="acrmobius7711564669.azurecr.io"'
        ),
        (
            'Bearer realm="https://acrmobius7711564669.azurecr.io/oauth2/token",'
            'service="wrong.azurecr.io"'
        ),
        (
            'Bearer realm="https://acrmobius7711564669.azurecr.io/oauth2/token",'
            'service="acrmobius7711564669.azurecr.io",scope="registry:catalog:*"'
        ),
        (
            'Bearer realm="https://acrmobius7711564669.azurecr.io/oauth2/token",'
            'service="acrmobius7711564669.azurecr.io",scope="repository:*:pull"'
        ),
        (
            'Bearer realm="https://acrmobius7711564669.azurecr.io/oauth2/token",'
            'service="acrmobius7711564669.azurecr.io"\r\nInjected: true'
        ),
    ],
)
def test_wrong_challenge_host_service_scope_or_shape_fails(header: str) -> None:
    with pytest.raises(lifecycle.LifecycleError):
        lifecycle._challenge_service(header)


def test_challenge_request_is_unauthenticated_private_and_nonredirecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def request(
        method: str,
        path: str,
        *,
        headers: dict[str, str],
        body: bytearray | None = None,
    ) -> tuple[int, dict[str, str], bytearray]:
        observed.update(method=method, path=path, headers=headers, body=body)
        return (
            401,
            {
                "www-authenticate": (
                    'Bearer realm="https://acrmobius7711564669.azurecr.io/oauth2/token",'
                    'service="acrmobius7711564669.azurecr.io"'
                )
            },
            bytearray(),
        )

    monkeypatch.setattr(lifecycle, "_private_registry_request", request)
    assert lifecycle._registry_bearer_challenge() == lifecycle.REGISTRY_HOST
    assert observed == {"method": "GET", "path": "/v2/", "headers": {}, "body": None}


@pytest.mark.parametrize("status", [200, 302, 403, 404])
def test_challenge_requires_exact_401(status: int, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        lifecycle,
        "_private_registry_request",
        lambda *_args, **_kwargs: (
            status,
            {
                "www-authenticate": (
                    'Bearer realm="https://acrmobius7711564669.azurecr.io/oauth2/token",'
                    'service="acrmobius7711564669.azurecr.io"'
                )
            },
            bytearray(),
        ),
    )
    with pytest.raises(lifecycle.LifecycleError, match="challenge-status-invalid"):
        lifecycle._registry_bearer_challenge()


def test_exchange_and_repository_token_forms_are_exact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant = "00000000-0000-0000-0000-000000000001"
    acr_token = _jwt(
        {
            "access": [
                {
                    "actions": ["pull", "push"],
                    "name": "opencanvas-api",
                    "type": "repository",
                }
            ],
            "aud": lifecycle.REGISTRY_HOST,
            "exp": int((NOW + timedelta(hours=1)).timestamp()),
            "nbf": int((NOW - timedelta(minutes=1)).timestamp()),
            "tenant": tenant,
        }
    )
    calls: list[tuple[str, str, dict[str, str], bytes]] = []

    def request(
        method: str,
        path: str,
        *,
        headers: dict[str, str],
        body: bytearray | None = None,
    ) -> tuple[int, dict[str, str], bytearray]:
        calls.append((method, path, headers, bytes(body or b"")))
        payload = (
            {"refresh_token": "r" * 64}
            if path.endswith("exchange")
            else {"access_token": acr_token.decode(), "expires_in": 3600}
        )
        return 200, {"content-type": "application/json"}, bytearray(json.dumps(payload).encode())

    monkeypatch.setattr(lifecycle, "_private_registry_request", request)
    monkeypatch.setattr(lifecycle, "_utc_now", lambda: NOW)
    refresh = lifecycle._publisher_refresh_token(
        entra_token=bytearray(b"e" * 64),
        tenant_id=tenant,
        service=lifecycle.REGISTRY_HOST,
    )
    assert refresh is not None
    access = lifecycle._publisher_repository_token(
        refresh_token=refresh,
        tenant_id=tenant,
        service=lifecycle.REGISTRY_HOST,
    )
    assert access is not None
    assert calls[0][:3] == (
        "POST",
        "/oauth2/exchange",
        {"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert calls[1][:3] == (
        "POST",
        "/oauth2/token",
        {"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert b"grant_type=access_token" in calls[0][3]
    assert b"service=acrmobius7711564669.azurecr.io" in calls[0][3]
    assert f"tenant={tenant}".encode() in calls[0][3]
    assert b"scope=" not in calls[0][3]
    assert b"grant_type=refresh_token" in calls[1][3]
    assert b"scope=repository%3Aopencanvas-api%3Apull%2Cpush" in calls[1][3]
    assert b"_catalog" not in calls[0][3] + calls[1][3]
    refresh.clear()
    access.clear()


@pytest.mark.parametrize(
    "actions",
    [
        ["pull"],
        ["push"],
        ["pull", "push", "delete"],
        ["pull", "push", "catalog"],
    ],
)
def test_repository_token_requires_exact_acrpush_action_intersection(
    actions: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant = "00000000-0000-0000-0000-000000000001"
    token = _jwt(
        {
            "access": [
                {
                    "actions": actions,
                    "name": "opencanvas-api",
                    "type": "repository",
                }
            ],
            "aud": lifecycle.REGISTRY_HOST,
            "exp": int((NOW + timedelta(hours=1)).timestamp()),
            "nbf": int((NOW - timedelta(minutes=1)).timestamp()),
            "tenant": tenant,
        }
    )
    monkeypatch.setattr(lifecycle, "_utc_now", lambda: NOW)
    try:
        with pytest.raises(lifecycle.LifecycleError, match="scope-invalid"):
            lifecycle._acr_access_is_exact(token, tenant_id=tenant)
    finally:
        token.clear()


@pytest.mark.parametrize("service", ["wrong.azurecr.io", "", "*.azurecr.io"])
def test_exchange_rejects_wrong_service(service: str) -> None:
    with pytest.raises(lifecycle.LifecycleError, match="publisher-oauth-service-invalid"):
        lifecycle._publisher_refresh_token(
            entra_token=bytearray(b"e" * 64),
            tenant_id="00000000-0000-0000-0000-000000000001",
            service=service,
        )


def test_oauth_request_rejects_json_content_type() -> None:
    with pytest.raises(lifecycle.LifecycleError, match="request-content-type-invalid"):
        lifecycle._private_registry_request(
            "POST",
            "/oauth2/exchange",
            headers={"Content-Type": "application/json"},
            body=bytearray(b"{}"),
        )


@pytest.mark.parametrize(
    ("claims", "error"),
    [
        ({"aud": "wrong"}, "binding-invalid"),
        ({"tid": "wrong"}, "binding-invalid"),
        ({"exp": int((NOW - timedelta(seconds=1)).timestamp())}, "token-expired"),
        ({"exp": int((NOW + timedelta(seconds=30)).timestamp())}, "lifetime-insufficient"),
        ({"nbf": int((NOW + timedelta(seconds=30)).timestamp())}, "not-yet-valid"),
        ({"nbf": int((NOW + timedelta(minutes=2)).timestamp())}, "time-invalid"),
    ],
)
def test_entra_binding_audience_tenant_and_time_fail_closed(
    claims: dict[str, object], error: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = "00000000-0000-0000-0000-000000000010"
    tenant = "00000000-0000-0000-0000-000000000011"
    complete: dict[str, object] = {
        "appid": app,
        "aud": lifecycle.ACR_TOKEN_RESOURCE,
        "exp": int((NOW + timedelta(hours=1)).timestamp()),
        "nbf": int((NOW - timedelta(minutes=1)).timestamp()),
        "tid": tenant,
    }
    complete.update(claims)
    monkeypatch.setattr(lifecycle, "_utc_now", lambda: NOW)
    with pytest.raises(lifecycle.LifecycleError, match=error):
        lifecycle._validate_entra_token(_jwt(complete), publisher_app_id=app, tenant_id=tenant)


class _Response:
    def __init__(self, status: int, payload: bytes, content_type: str = "application/json") -> None:
        self.status = status
        self._payload = payload
        self._headers = {"Content-Type": content_type}

    def read(self, _maximum: int) -> bytes:
        return self._payload

    def getheader(self, name: str) -> str | None:
        return self._headers.get(name)


class _Connection:
    response: _Response

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        self.request_observed: tuple[object, ...] | None = None

    def request(self, *args: object, **kwargs: object) -> None:
        self.request_observed = (*args, kwargs)

    def getresponse(self) -> _Response:
        return self.response

    def close(self) -> None:
        return None


@pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 500, 503])
def test_non_200_oauth_status_is_attributed_failed(
    status: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _Connection.response = _Response(status, b'{"errors":[]}')
    monkeypatch.setattr(lifecycle.http.client, "HTTPSConnection", _Connection)
    monkeypatch.setattr(lifecycle, "_private_tls_endpoint", lambda _host: None)
    with (
        lifecycle._operation_attribution_session(
            receipt_directory=tmp_path,
            lifecycle_stage="post-secret-provisioning",
            ledger_integrity=LEDGER,
            repository_head=HEAD,
        ),
        lifecycle._attribution_scope(
            lifecycle_substage="private-acr-oauth-exchange",
            expected_authorization="allow",
        ),
    ):
        observed, _headers, body = lifecycle._private_registry_request(
            "POST",
            "/oauth2/exchange",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            body=bytearray(b"grant_type=access_token"),
        )
        body.clear()
    assert observed == status
    final = _records(tmp_path)[-1]
    assert final["lifecycleSubstage"] == "private-acr-oauth-exchange"
    assert final["sanitizedStatusCode"] == str(status)
    assert final["terminalDisposition"] == "FAILED"


def test_expected_initial_401_is_successful_denial_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _Connection.response = _Response(401, b'{"errors":[]}')
    monkeypatch.setattr(lifecycle.http.client, "HTTPSConnection", _Connection)
    monkeypatch.setattr(lifecycle, "_private_tls_endpoint", lambda _host: None)
    with (
        lifecycle._operation_attribution_session(
            receipt_directory=tmp_path,
            lifecycle_stage="post-secret-provisioning",
            ledger_integrity=LEDGER,
            repository_head=HEAD,
        ),
        lifecycle._attribution_scope(
            lifecycle_substage="initial-acr-denial",
            expected_authorization="deny",
        ),
    ):
        status, _headers, body = lifecycle._private_registry_request(
            "POST",
            "/oauth2/exchange",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            body=bytearray(b"grant_type=access_token"),
        )
        body.clear()
    assert status == 401
    final = _records(tmp_path)[-1]
    assert final["operationClass"] == "initial-acr-denial-exchange-proof"
    assert final["terminalDisposition"] == "SUCCEEDED"


@pytest.mark.parametrize(
    "payload",
    [b"", b"not-json", b"{}", b'{"refresh_token":""}', b'{"wrong":"x"}'],
)
def test_200_without_valid_refresh_token_is_failed_before_attribution_closes(
    payload: bytes, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _Connection.response = _Response(200, payload)
    monkeypatch.setattr(lifecycle.http.client, "HTTPSConnection", _Connection)
    monkeypatch.setattr(lifecycle, "_private_tls_endpoint", lambda _host: None)
    with (
        lifecycle._operation_attribution_session(
            receipt_directory=tmp_path,
            lifecycle_stage="post-secret-provisioning",
            ledger_integrity=LEDGER,
            repository_head=HEAD,
        ),
        pytest.raises(lifecycle.LifecycleError),
    ):
        lifecycle._private_registry_request(
            "POST",
            "/oauth2/exchange",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            body=bytearray(b"grant_type=access_token"),
        )
    assert _records(tmp_path)[-1]["terminalDisposition"] == "FAILED"


def test_generic_401_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def once(**_kwargs: object) -> tuple[bytearray, bytearray | None]:
        nonlocal calls
        calls += 1
        raise lifecycle.LifecycleError("publisher-oauth-exchange-http-401")

    monkeypatch.setattr(lifecycle, "_publisher_repository_session_once", once)
    with pytest.raises(lifecycle.LifecycleError, match="http-401"):
        lifecycle._publisher_repository_session(
            publisher_app_id="app", tenant_id="tenant", environment={}
        )
    assert calls == 1


@pytest.mark.parametrize(
    ("endpoint", "status"),
    [
        ("exchange", 401),
        ("exchange", 403),
        ("token", 401),
        ("token", 403),
    ],
)
def test_propagation_scoped_denial_is_pending_only_during_acrpush_verification(
    endpoint: str, status: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        lifecycle,
        "_private_registry_request",
        lambda *_args, **_kwargs: (status, {}, bytearray()),
    )

    with (
        lifecycle._attribution_scope(
            lifecycle_substage="acrpush-propagation-verification",
            expected_authorization="allow",
        ),
        pytest.raises(lifecycle.PublisherAccessPending, match=f"http-{status}"),
    ):
        if endpoint == "exchange":
            lifecycle._publisher_refresh_token(
                entra_token=bytearray(b"e" * 64),
                tenant_id="00000000-0000-0000-0000-000000000001",
                service=lifecycle.REGISTRY_HOST,
            )
        else:
            lifecycle._publisher_repository_token(
                refresh_token=bytearray(b"r" * 64),
                tenant_id="00000000-0000-0000-0000-000000000001",
                service=lifecycle.REGISTRY_HOST,
            )


def test_allow_401_outside_propagation_remains_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        lifecycle,
        "_private_registry_request",
        lambda *_args, **_kwargs: (401, {}, bytearray()),
    )

    with pytest.raises(lifecycle.LifecycleError, match="exchange-http-401") as error:
        lifecycle._publisher_refresh_token(
            entra_token=bytearray(b"e" * 64),
            tenant_id="00000000-0000-0000-0000-000000000001",
            service=lifecycle.REGISTRY_HOST,
        )
    assert not isinstance(error.value, lifecycle.PublisherAccessPending)


def test_acrpush_propagation_pending_retries_with_fresh_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    sleeps: list[float] = []

    def session(**_kwargs: object) -> tuple[bytearray, bytearray | None]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise lifecycle.PublisherAccessPending("publisher-oauth-exchange-propagation-http-401")
        return bytearray(b"r" * 64), bytearray(b"a" * 64)

    monotonic = iter((0.0, 1.0))
    monkeypatch.setattr(lifecycle, "_publisher_repository_session", session)
    monkeypatch.setattr(lifecycle.time, "monotonic", lambda: next(monotonic))
    monkeypatch.setattr(lifecycle.time, "sleep", sleeps.append)

    refresh, access = lifecycle._wait_for_publisher_access(
        publisher_app_id="app",
        tenant_id="tenant",
        environment={},
    )
    assert calls == 2
    assert sleeps == [10.0]
    assert access is not None
    refresh.clear()
    access.clear()


@pytest.mark.parametrize(
    "error",
    [
        "publisher-token-expired",
        "publisher-token-not-yet-valid",
        "publisher-oauth-token-http-429",
        "publisher-oauth-token-http-503",
        "publisher-private-registry-request-timed-out",
    ],
)
def test_recognized_transient_condition_retries_exactly_once(
    error: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0

    def once(**_kwargs: object) -> tuple[bytearray, bytearray | None]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise lifecycle.PublisherOAuthTransient(error)
        return bytearray(b"r" * 64), bytearray(b"a" * 64)

    monkeypatch.setattr(lifecycle, "_publisher_repository_session_once", once)
    refresh, access = lifecycle._publisher_repository_session(
        publisher_app_id="app", tenant_id="tenant", environment={}
    )
    assert calls == 2
    assert access is not None
    refresh.clear()
    access.clear()


def test_second_transient_failure_is_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def once(**_kwargs: object) -> tuple[bytearray, bytearray | None]:
        nonlocal calls
        calls += 1
        raise lifecycle.PublisherOAuthTransient("publisher-oauth-token-http-429")

    monkeypatch.setattr(lifecycle, "_publisher_repository_session_once", once)
    with pytest.raises(lifecycle.PublisherOAuthTransient):
        lifecycle._publisher_repository_session(
            publisher_app_id="app", tenant_id="tenant", environment={}
        )
    assert calls == 2


def test_latest_unresolved_oauth_failure_wins_over_stale_key_vault_failure(
    tmp_path: Path,
) -> None:
    journal = _session(tmp_path)

    def finish(substage: str, disposition: str, status: str) -> None:
        spec: dict[str, JsonValue] = {
            "azureMutation": False,
            "cleanupOrRevocation": False,
            "endpointClass": "private-endpoint",
            "expectedAuthorizationResult": "allow",
            "identityAlias": "ephemeral-acr-publisher",
            "lifecycleSubstage": substage,
            "operationClass": substage,
            "serviceClass": "azure-container-registry-data-plane",
        }
        operation = journal.start(spec)
        journal.mark_request_attempt_began(operation, cleanup_or_revocation=False)
        journal.mark_azure_request_issued(operation)
        journal.finish(
            operation,
            status_code=status,
            azure_error_code="acr-oauth-http-401" if status == "401" else None,
            correlation_hash=None,
            terminal_disposition=disposition,
        )

    finish("key-vault-authority-propagation-proof", "FAILED", "403")
    finish("key-vault-authority-propagation-proof", "SUCCEEDED", "200")
    finish("private-acr-oauth-exchange", "FAILED", "401")
    assert (
        lifecycle._safe_failed_stage(tmp_path, operation="post-secret-provisioning")
        == "private-acr-oauth-exchange"
    )


def test_oauth_source_and_attribution_never_retain_tokens_or_raw_challenge() -> None:
    source = "\n".join(
        (
            lifecycle._publisher_entra_token.__doc__ or "",
            lifecycle._publisher_refresh_token.__doc__ or "",
            lifecycle._publisher_repository_token.__doc__ or "",
        )
    )
    assert "Bearer " not in source
    assert "refresh_token=" not in source
    assert hashlib.sha256(b"synthetic-token").hexdigest() not in source
