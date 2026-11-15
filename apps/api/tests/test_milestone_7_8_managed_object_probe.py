"""New probe safety/fixture tests; these do not stand in for managed acceptance."""

from __future__ import annotations

import importlib.util
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import func, select

from opencanvas_api.core.config import Settings
from opencanvas_api.db import models as m
from opencanvas_api.services.auth import Principal
from opencanvas_api.services.documents.errors import DocumentStorageError
from opencanvas_api.services.documents.storage import MemoryVersionedObjectStorage

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "managed_object_probe", ROOT / "infra/milestone_7_8/managed_object_probe.py"
)
assert SPEC is not None and SPEC.loader is not None
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


def configured(database, tmp_path):
    instance = object.__new__(probe.Probe)
    instance.db = database
    instance.campaign = uuid.uuid4()
    instance.workspace = uuid.uuid5(instance.campaign, "workspace")
    instance.canvas = uuid.uuid5(instance.campaign, "canvas")
    instance.user = uuid.uuid5(instance.campaign, "owner")
    instance.principal = Principal(
        user_id=instance.user,
        email="proof@mobius.invalid",
        display_name="Proof",
        session_id=None,
        csrf_token_hash=None,
        synthetic=False,
    )
    instance.settings = Settings(
        environment="test",
        database_url="sqlite+aiosqlite:///:memory:",
        storage_provider="memory",
        document_storage_root=tmp_path / "documents",
        object_ingestion_mode="deterministic",
        upload_capability_secret="probe-test-upload-secret-000000000000000",
        scanner_result_secret="probe-test-scanner-secret-000000000000000",
        malware_scanner_identity="deterministic-test-scanner",
        malware_scanner_version="test-v1",
        malware_policy_version="test-policy-v1",
        indexer_publication_mode="private_clean",
    )
    instance.api = instance.worker = MemoryVersionedObjectStorage()
    return instance


async def install_registration_triggers(database):
    # Base.metadata.create_all does not install migration 0023's registration
    # trigger. Use the shipped migration implementation to model managed setup.
    migration_spec = importlib.util.spec_from_file_location(
        "resource_registration_migration",
        ROOT / "apps/api/alembic/versions/20260725_0023_resource_sharing_ownership_revocation.py",
    )
    assert migration_spec is not None and migration_spec.loader is not None
    migration = importlib.util.module_from_spec(migration_spec)
    migration_spec.loader.exec_module(migration)

    def install_registration(connection):
        with Operations.context(MigrationContext.configure(connection)):
            migration._install_resource_registration_triggers()

    async with database.engine.begin() as connection:
        await connection.run_sync(install_registration)


async def test_seed_and_upload_use_real_lifecycle_and_idempotent_provider(database, tmp_path):
    await install_registration_triggers(database)
    instance = configured(database, tmp_path)
    await instance.seed_fixture()
    await instance.seed_fixture()
    first = await instance.upload_one("clean", probe.CLEAN)
    second = await instance.upload_one("clean", probe.CLEAN)
    assert first == second
    async with database.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(m.UploadSession)) == 1
        assert await session.scalar(select(func.count()).select_from(m.StorageObjectVersion)) == 1
        assert await session.scalar(select(func.count()).select_from(m.MalwareScanRequest)) == 1
        assert await session.scalar(select(func.count()).select_from(m.ObjectPromotion)) == 0
        registrations = list(
            (
                await session.scalars(
                    select(m.CollaborationResource).where(
                        m.CollaborationResource.resource_id == instance.canvas
                    )
                )
            ).all()
        )
        ownership = list(
            (
                await session.scalars(
                    select(m.CollaborationResourceOwnershipTransition).where(
                        m.CollaborationResourceOwnershipTransition.resource_id == instance.canvas
                    )
                )
            ).all()
        )
        assert len(registrations) == len(ownership) == 1
        assert ownership[0].reason_code == "resource_created"


@pytest.mark.parametrize("legacy_first", [False, True])
async def test_distinct_upload_completion_events_and_legacy_replay_history(
    database, tmp_path, monkeypatch, legacy_first
):
    await install_registration_triggers(database)
    instance = configured(database, tmp_path)
    await instance.seed_fixture()
    original_event = probe.UploadLifecycleService._event

    async def legacy_event(service, **arguments):
        if arguments["event_type"] == "upload.completed":
            arguments["source"] = "completed:2"
        return await original_event(service, **arguments)

    with monkeypatch.context() as context:
        if legacy_first:
            # Record a real event under the pre-correction identity; never mutate
            # append-only historical rows to emulate older successful work.
            context.setattr(probe.UploadLifecycleService, "_event", legacy_event)
        first = await instance.upload_one("clean", probe.CLEAN)
    second = await instance.upload_one("infected", probe.EICAR)
    assert first["session_id"] != second["session_id"]
    async with database.sessions() as session:
        events = list(
            (
                await session.scalars(
                    select(m.DomainEventRecord).where(
                        m.DomainEventRecord.event_type == "upload.completed"
                    )
                )
            ).all()
        )
        assert len(events) == 2
        before = {
            event.event_id: (event.source_identity, event.request_digest, event.payload_digest)
            for event in events
        }
        assert len({event.source_identity for event in events}) == 2
        assert any(
            event.source_identity.startswith(f"completed:{second['session_id']}:")
            for event in events
        )
        if legacy_first:
            assert any(event.source_identity == "completed:2" for event in events)
    assert await instance.upload_one("clean", probe.CLEAN) == first
    assert await instance.upload_one("infected", probe.EICAR) == second
    async with database.sessions() as session:
        events = list(
            (
                await session.scalars(
                    select(m.DomainEventRecord).where(
                        m.DomainEventRecord.event_type == "upload.completed"
                    )
                )
            ).all()
        )
        after = {
            event.event_id: (event.source_identity, event.request_digest, event.payload_digest)
            for event in events
        }
        assert after == before


async def test_ambiguous_injection_requires_real_delete_success():
    storage = SimpleNamespace(delete_version=AsyncMock())
    ambiguous = probe.AmbiguousDelete(storage)
    with pytest.raises(DocumentStorageError):
        await ambiguous.delete_version(
            physical_key="clean/private", provider_version_id="private-version"
        )
    assert ambiguous.deleted
    storage.delete_version.assert_awaited_once()
    storage.delete_version.side_effect = DocumentStorageError(
        "denied", code="storage_authorization_failed"
    )
    denied = probe.AmbiguousDelete(storage)
    with pytest.raises(DocumentStorageError):
        await denied.delete_version(
            physical_key="clean/private", provider_version_id="private-version"
        )
    assert not denied.deleted


def test_public_receipt_does_not_leak_provider_or_payload():
    result = {
        "assertions": ["exact-version"],
        "provider_version_id": "PRIVATE-VERSION",
        "physical_key": "PRIVATE-PATH",
        "nested": {"token": "PRIVATE-TOKEN"},
    }
    rendered = json.dumps(probe.public_receipt("upload", result))
    assert "PRIVATE" not in rendered
    assert probe.digest(result) in rendered
    assert probe.digest({"b": 2, "a": 1}) == probe.digest({"a": 1, "b": 2})


async def test_accepted_phase_is_never_reexecuted_and_failure_is_preserved():
    instance = object.__new__(probe.Probe)
    instance.read_receipt = AsyncMock(return_value={"assertions": ["already-accepted"]})
    instance.scan = AsyncMock()
    instance.record = AsyncMock()
    assert await instance.execute("scan") == {"assertions": ["already-accepted"]}
    instance.scan.assert_not_awaited()
    instance.read_receipt.return_value = None
    instance.scan.side_effect = probe.ProbeFailure("defender-evidence-not-yet-complete")
    with pytest.raises(probe.ProbeFailure):
        await instance.execute("scan")
    instance.record.assert_awaited_once_with(
        "scan",
        "failed",
        {
            "safe_code": "defender-evidence-not-yet-complete",
            "diagnostic": {"code": "defender-evidence-not-yet-complete"},
        },
    )


@pytest.mark.parametrize(
    "wrong_version,wrong_bytes", [(False, False), (True, False), (False, True)]
)
async def test_recovery_requires_exact_original_version_etag_and_bytes(wrong_version, wrong_bytes):
    instance = object.__new__(probe.Probe)
    target = dict(
        object_version_id=str(uuid.uuid4()),
        physical_key="clean/private",
        provider_version_id="private-version",
        etag="private-etag",
        content_sha256=probe.digest(probe.CLEAN),
    )
    instance.required = AsyncMock(return_value={"target": target})
    instance.read_receipt = AsyncMock(return_value=None)
    instance.record = AsyncMock()
    response = httpx.Response(
        200,
        headers={
            "x-ms-version-id": "different" if wrong_version else "private-version",
            "etag": "private-etag",
        },
    )
    storage = SimpleNamespace(
        version_exists=AsyncMock(side_effect=[False, False]),
        _request=AsyncMock(side_effect=[httpx.Response(200), response]),
        read_version=AsyncMock(return_value=b"substitute" if wrong_bytes else probe.CLEAN),
        delete_version=AsyncMock(),
    )
    instance.recovery_storage = storage
    instance.verify_recovered_policy = AsyncMock(return_value={"api_clean_read": "denied"})
    if wrong_version or wrong_bytes:
        with pytest.raises(probe.ProbeFailure):
            await instance.recovery()
        storage.delete_version.assert_not_awaited()
    else:
        result = await instance.recovery()
        assert "original-version-etag-bytes-restored" in result["assertions"]
        instance.verify_recovered_policy.assert_awaited_once_with(target)
        storage.delete_version.assert_awaited_once_with(
            physical_key="clean/private", provider_version_id="private-version"
        )
    assert storage._request.await_args_list[0].kwargs == {"query": {"comp": "undelete"}}


async def test_reconciled_upload_reuses_observed_version_without_new_provider_put():
    provider = probe.ProviderObjectVersion(
        "quarantine/private",
        "azure",
        "private-version",
        "private-etag",
        len(probe.CLEAN),
        probe.digest(probe.CLEAN),
    )
    storage = SimpleNamespace(put_immutable=AsyncMock())
    reconciled = probe.ReconciledUpload(storage, provider)
    assert (
        await reconciled.put_immutable(
            content=probe.CLEAN, expected_sha256=probe.digest(probe.CLEAN)
        )
        == provider
    )
    with pytest.raises(probe.ProbeFailure, match="reconciled-upload-contract-differed"):
        await reconciled.put_immutable(
            content=b"different", expected_sha256=probe.digest(probe.CLEAN)
        )
    storage.put_immutable.assert_not_awaited()


def test_normalized_version_observation_retains_binding_without_raw_private_identifiers():
    version = dict(
        object_version_id=str(uuid.uuid4()),
        physical_key="PRIVATE-KEY",
        provider_version_id="PRIVATE-VERSION",
        etag="PRIVATE-ETAG",
        content_sha256=probe.digest(probe.CLEAN),
    )
    observation = probe.version_observation(version)
    assert "PRIVATE" not in json.dumps(observation)
    assert observation["provider_version_sha256"] == probe.digest("PRIVATE-VERSION")
    assert observation["etag_sha256"] == probe.digest("PRIVATE-ETAG")


async def test_recovery_resume_keeps_accepted_observation_without_restoring_again():
    instance = object.__new__(probe.Probe)
    target = {"physical_key": "clean/private", "provider_version_id": "private-version"}
    instance.required = AsyncMock(return_value={"target": target})
    accepted = {
        "observations": {
            "recovered_sha256": probe.digest(probe.CLEAN),
            "head_status": 200,
            "recovered_size_bytes": len(probe.CLEAN),
        }
    }
    instance.read_receipt = AsyncMock(return_value=accepted)
    instance.record = AsyncMock()
    storage = SimpleNamespace(
        version_exists=AsyncMock(return_value=False),
        _request=AsyncMock(),
        read_version=AsyncMock(),
        delete_version=AsyncMock(),
    )
    instance.recovery_storage = storage
    result = await instance.recovery()
    assert (
        result["observations"]["recovered_sha256"] == accepted["observations"]["recovered_sha256"]
    )
    storage._request.assert_not_awaited()
    storage.read_version.assert_not_awaited()
    storage.delete_version.assert_not_awaited()
    instance.record.assert_not_awaited()


@pytest.mark.parametrize("changed", [None, "promotion", "scan", "lifecycle", "api-read"])
async def test_recovery_keeps_original_scan_binding_and_deleted_api_policy(changed):
    instance = object.__new__(probe.Probe)
    source_id, target_id, result_id, request_id, promotion_id = (uuid.uuid4() for _ in range(5))
    content_hash = probe.digest(probe.CLEAN)
    source = {
        "object_version_id": str(source_id),
        "provider_version_id": "original-version",
        "etag": "original-etag",
        "content_sha256": content_hash,
        "session_id": str(uuid.uuid4()),
    }
    target = {"object_version_id": str(target_id), "content_sha256": content_hash}
    original = {
        "scan_result_id": str(result_id),
        "scan_request_id": str(request_id),
        "promotion_id": str(promotion_id),
        "result_digest": "a" * 64,
        "provider_record_digest": "b" * 64,
    }
    receipts = {"upload": {"clean": source}, "scan": {"observations": {"clean": original}}}
    instance.required = AsyncMock(side_effect=lambda phase: receipts[phase])
    result = SimpleNamespace(
        object_version_id=source_id,
        scan_request_id=request_id,
        outcome="clean",
        result_digest="changed" if changed == "scan" else "a" * 64,
        provider_record_digest="b" * 64,
        provider_version_id="original-version",
        etag="original-etag",
        content_sha256=content_hash,
        scan_result_id=result_id,
    )
    promotion = SimpleNamespace(
        scan_result_id=result_id,
        source_object_version_id=source_id,
        target_object_version_id=uuid.uuid4() if changed == "promotion" else target_id,
        source_sha256=content_hash,
        target_sha256=content_hash,
        promotion_id=promotion_id,
    )
    session = SimpleNamespace(
        get=AsyncMock(side_effect=[result, promotion]),
        scalar=AsyncMock(return_value="clean" if changed == "lifecycle" else "deleted"),
    )
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=session)
    context.__aexit__ = AsyncMock(return_value=False)
    instance.db = SimpleNamespace(sessions=lambda: context)
    denied = probe.ObjectIngestionNotFoundError()
    clean_bytes = AsyncMock(side_effect=None if changed == "api-read" else denied)
    instance.service = lambda session: SimpleNamespace(clean_bytes=clean_bytes)
    instance.scope = lambda sid: {"session_id": sid}
    if changed:
        with pytest.raises(probe.ProbeFailure):
            await instance.verify_recovered_policy(target)
    else:
        observation = await instance.verify_recovered_policy(target)
        assert observation["lifecycle_state"] == "deleted"
        assert observation["api_clean_read"] == "denied"
        assert observation["promotion_id"] == str(promotion_id)
        clean_bytes.assert_awaited_once_with(session_id=uuid.UUID(source["session_id"]))


def test_safe_failure_extracts_nested_known_identifiers_without_reading_exception_text():
    class NoStringError(Exception):
        def __str__(self):
            raise AssertionError("Exception text must never be inspected")

    error = NoStringError()
    driver = SimpleNamespace(
        sqlstate="23503",
        table_name="workspace_memberships",
        column_name="creation_audit_event_id",
        constraint_name="workspace_memberships_creation_audit_event_id_fkey",
        detail="SECRET parameter data",
        query="SECRET SQL",
        orig=error,
    )
    error.orig = SimpleNamespace(orig=driver)
    diagnostic = probe.safe_failure(error)
    assert diagnostic == {
        "code": "NoStringError",
        "sqlstate": "23503",
        "table_name": "workspace_memberships",
        "column_name": "creation_audit_event_id",
        "constraint_name": "workspace_memberships_creation_audit_event_id_fkey",
    }
    assert "SECRET" not in json.dumps(diagnostic)


@pytest.mark.parametrize(
    "value", ["secret_identifier", "users; SELECT token", "12345678-1234-1234-1234-123456789abc"]
)
def test_safe_failure_rejects_unknown_or_unsafe_database_metadata(value):
    error = RuntimeError("SECRET SQL parameters")
    error.orig = SimpleNamespace(
        sqlstate=value,
        table_name=value,
        column_name=value,
        constraint_name=value,
        message="SECRET provider payload",
    )
    assert probe.safe_failure(error) == {"code": "RuntimeError"}


@pytest.mark.parametrize(
    "message,expected",
    [
        ("permission denied for table upload_sessions", {"table_name": "upload_sessions"}),
        ('permission denied for schema "m78_object_probe"', {"schema_name": "m78_object_probe"}),
        ("permission denied for sequence users_id_seq", {"sequence_name": "users_id_seq"}),
        ("permission denied for table secret_runtime_identifier", {}),
        ("permission denied for table users; SELECT secret", {}),
        (
            "permission denied for table upload_sessions\nDETAIL: SECRET_PARAMETERS",
            {"table_name": "upload_sessions"},
        ),
    ],
)
def test_safe_failure_permission_clause_is_narrowly_allowlisted(message, expected):
    error = RuntimeError("SECRET SQLAlchemy statement and bound parameters")
    error.orig = SimpleNamespace(sqlstate="42501", message=message, args=())
    result = probe.safe_failure(error)
    assert result == {"code": "RuntimeError", "sqlstate": "42501", **expected}
    assert "SECRET" not in json.dumps(result)


def replacement_environment(campaign):
    old = {
        "idempotency_key_sha256": probe.digest(f"{campaign}:clean"),
        "session_id": str(uuid.uuid4()),
        "object_version_id": str(uuid.uuid4()),
        "state": "requested",
        "expired": True,
        "database_version_present": False,
        "scan_request_count": 0,
        "scan_result_count": 0,
        "promotion_count": 0,
        "provider_head_status": 404,
        "provider_exact_version_count": 0,
        "provider_versions": [],
        "expected_sha256": probe.digest(probe.CLEAN),
        "expected_size_bytes": len(probe.CLEAN),
    }
    snapshot = {
        "campaign": str(campaign),
        "read_only": True,
        "classification": "read-only-upload-resume-inspection",
        "inspector_sha256": "058225ff961261e862e948f1cffec9089043017dd3f39ce37ddcfcc808f7ab49",
        "execution_id": "actual-inspection-execution",
        "sessions": [old],
        "journal": [],
    }
    environment = {
        "OPENCANVAS_OBJECT_PROBE_CLEAN_REPLACEMENT_TOKEN": "permission-fix-1",
        "OPENCANVAS_OBJECT_PROBE_RESUME_INSPECTION_JSON": json.dumps(snapshot),
        "OPENCANVAS_OBJECT_PROBE_RESUME_INSPECTION_SHA256": probe.digest(snapshot),
        "OPENCANVAS_OBJECT_PROBE_RESUME_INSPECTION_EXECUTION": snapshot["execution_id"],
    }
    return environment, snapshot


@pytest.mark.parametrize("changed", [None, "hash", "provider", "accepted", "campaign"])
def test_clean_replacement_requires_bound_empty_expired_inspection(changed):
    campaign = uuid.uuid4()
    environment, snapshot = replacement_environment(campaign)
    if changed == "provider":
        snapshot["sessions"][0]["provider_exact_version_count"] = 1
    elif changed == "accepted":
        snapshot["journal"] = [{"phase": "upload-clean", "status": "accepted"}]
    elif changed == "campaign":
        snapshot["campaign"] = str(uuid.uuid4())
    environment["OPENCANVAS_OBJECT_PROBE_RESUME_INSPECTION_JSON"] = json.dumps(snapshot)
    environment["OPENCANVAS_OBJECT_PROBE_RESUME_INSPECTION_SHA256"] = (
        "0" * 64 if changed == "hash" else probe.digest(snapshot)
    )
    if changed:
        with pytest.raises(probe.ProbeFailure):
            probe.clean_replacement_authority(environment, campaign)
    else:
        assert (
            probe.clean_replacement_authority(environment, campaign)["token"] == "permission-fix-1"
        )
        assert probe.clean_replacement_authority({}, campaign) is None


@pytest.mark.parametrize("provider_state", ["absent", "live", "retained"])
async def test_clean_replacement_rechecks_provider_before_recording_new_key(
    monkeypatch, provider_state
):
    instance = object.__new__(probe.Probe)
    instance.campaign, instance.workspace, instance.user = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    environment, snapshot = replacement_environment(instance.campaign)
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    old = snapshot["sessions"][0]
    row = SimpleNamespace(
        session_id=uuid.UUID(old["session_id"]),
        workspace_id=instance.workspace,
        user_id=instance.user,
        idempotency_key=f"{instance.campaign}:clean",
        object_version_id=uuid.UUID(old["object_version_id"]),
        object_id=uuid.uuid4(),
        expected_sha256=probe.digest(probe.CLEAN),
        expected_size_bytes=len(probe.CLEAN),
        expires_at=datetime.now(UTC) - timedelta(minutes=10),
    )
    session = SimpleNamespace(
        scalar=AsyncMock(side_effect=[0, "requested", 0, 0, 0]),
        get=AsyncMock(side_effect=[row, None]),
        rollback=AsyncMock(),
    )
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=session)
    context.__aexit__ = AsyncMock(return_value=False)
    instance.db = SimpleNamespace(sessions=lambda: context)
    instance.read_receipt = AsyncMock(return_value=None)
    instance.record = AsyncMock()
    key = f"{row.object_id.hex}/{row.object_version_id.hex}"
    content = (
        (
            f"<EnumerationResults><Blobs><Blob><Name>{key}</Name><Deleted>true</Deleted>"
            "</Blob></Blobs></EnumerationResults>"
        ).encode()
        if provider_state == "retained"
        else b"<EnumerationResults/>"
    )
    instance.api = SimpleNamespace(
        _request=AsyncMock(
            side_effect=[
                httpx.Response(200 if provider_state == "live" else 404),
                httpx.Response(200, content=content),
            ]
        )
    )
    if provider_state != "absent":
        with pytest.raises(probe.ProbeFailure):
            await instance.upload_key("clean")
        instance.record.assert_not_awaited()
    else:
        assert await instance.upload_key("clean") == f"{instance.campaign}:clean:permission-fix-1"
        instance.record.assert_awaited_once()
        assert instance.record.await_args.args[2]["original_session_id"] == old["session_id"]
        assert instance.record.await_args.args[2]["observations"]["exact_version_count"] == 0


@pytest.mark.parametrize("same_token", [True, False])
async def test_clean_replacement_reuses_same_token_and_rejects_new_token(monkeypatch, same_token):
    instance = object.__new__(probe.Probe)
    instance.campaign = uuid.uuid4()
    environment, _ = replacement_environment(instance.campaign)
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    key = f"{instance.campaign}:clean:permission-fix-1"
    receipt = {
        "inspection_sha256": environment["OPENCANVAS_OBJECT_PROBE_RESUME_INSPECTION_SHA256"],
        "replacement_key_sha256": probe.digest(key),
    }
    instance.read_receipt = AsyncMock(return_value=receipt if same_token else None)
    instance.api = SimpleNamespace(_request=AsyncMock())
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=SimpleNamespace(scalar=AsyncMock(return_value=1)))
    context.__aexit__ = AsyncMock(return_value=False)
    instance.db = SimpleNamespace(sessions=lambda: context)
    if same_token:
        assert await instance.upload_key("clean") == key
        context.__aenter__.assert_not_awaited()
    else:
        with pytest.raises(probe.ProbeFailure, match="new-token-would-repeat-work"):
            await instance.upload_key("clean")
    instance.api._request.assert_not_awaited()


@pytest.mark.parametrize(
    "changed", [None, "registration", "admission", "inspection-hash", "result", "deadline"]
)
def test_managed_resume_requires_admission_and_original_expired_unaccepted_evidence(changed):
    campaign = uuid.uuid4()
    inspection = {
        "campaign": str(campaign),
        "read_only": True,
        "classification": "read-only-upload-resume-inspection",
        "execution_id": "actual-inspection",
        "inspector_sha256": "058225ff961261e862e948f1cffec9089043017dd3f39ce37ddcfcc808f7ab49",
    }
    diagnostic = {
        "campaign": str(campaign),
        "accepted": False,
        "classification": "read-only-scanner-evidence-diagnostic",
        "execution_id": "actual-diagnostic",
        "diagnostic_sha256": "23cb70cee664bfa7f6f71561ee1c5afb9b109a5ecc34babbf5d1613c5a078748",
        "consumer_deadline_open": changed == "deadline",
        "scan_result_count": 1 if changed == "result" else 0,
    }
    manifest = {
        "schema_version": "m78-object-managed-resume-v1",
        "campaign": str(campaign),
        "token": "scanner-admitted-1",
        "scanner_admission_state": "Failed" if changed == "admission" else "Succeeded",
        "event_grid_registration_state": "NotRegistered"
        if changed == "registration"
        else "Registered",
        "failed_scanner_operation_receipt_sha256": "a" * 64,
        "scanner_admission_receipt_sha256": "b" * 64,
        "upload_inspection": inspection,
        "upload_inspection_sha256": "c" * 64
        if changed == "inspection-hash"
        else probe.digest(inspection),
        "scanner_diagnostic": diagnostic,
        "scanner_diagnostic_sha256": probe.digest(diagnostic),
    }
    environment = {
        "OPENCANVAS_OBJECT_PROBE_MANAGED_RESUME_JSON": json.dumps(manifest),
        "OPENCANVAS_OBJECT_PROBE_MANAGED_RESUME_SHA256": probe.digest(manifest),
    }
    if changed:
        with pytest.raises(probe.ProbeFailure):
            probe.managed_resume_authority(environment, campaign)
    else:
        assert probe.managed_resume_authority(environment, campaign) == manifest
        assert probe.managed_resume_authority({}, campaign) is None


async def test_scanner_only_fixture_keeps_positive_checks_without_repeating_authorization_negatives(
    database, tmp_path, monkeypatch
):
    await install_registration_triggers(database)
    instance = configured(database, tmp_path)
    await instance.seed_fixture()
    original_upload = probe.UploadLifecycleService.upload_bytes
    submitted = []

    async def checked_upload(service, **arguments):
        submitted.append(arguments["content"])
        return await original_upload(service, **arguments)

    monkeypatch.setattr(probe.UploadLifecycleService, "upload_bytes", checked_upload)
    monkeypatch.setattr(
        probe.UploadLifecycleService,
        "get",
        AsyncMock(side_effect=AssertionError("Accepted authorization scenario must not rerun")),
    )
    result = await instance.upload_one("scanner-clean", probe.CLEAN, verify_authorization=False)
    assert submitted == [probe.CLEAN]
    assert result["content_sha256"] == probe.digest(probe.CLEAN)


@pytest.mark.parametrize("name", ["infected", "scanner-clean"])
@pytest.mark.parametrize("wrong_bytes", [False, True])
async def test_managed_replacement_preserves_and_verifies_original_provider_bytes(
    name, wrong_bytes
):
    instance = object.__new__(probe.Probe)
    instance.campaign, instance.workspace, instance.user = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    sid, vid = uuid.uuid4(), uuid.uuid4()
    content = probe.CLEAN if name == "scanner-clean" else probe.EICAR
    state = "completed" if name == "scanner-clean" else "uploaded"
    old = {
        "session_id": str(sid),
        "object_version_id": str(vid),
        "state": state,
        "idempotency_key_sha256": probe.digest(f"{instance.campaign}:infected"),
        "expired": True,
        "database_version_present": True,
        "scan_result_count": 0,
        "promotion_count": 0,
        "provider_head_status": 200,
        "provider_exact_version_count": 1,
        "provider_version_sha256": probe.digest("provider-version"),
        "provider_etag_sha256": probe.digest("etag"),
    }
    manifest = {
        "token": "scanner-admitted-1",
        "upload_inspection": {"sessions": [old], "execution_id": "inspection"},
        "scanner_diagnostic": {"object_version_id": str(vid), "execution_id": "diagnostic"},
        "failed_scanner_operation_receipt_sha256": "a" * 64,
        "scanner_admission_receipt_sha256": "b" * 64,
    }
    row = SimpleNamespace(
        session_id=sid,
        object_version_id=vid,
        workspace_id=instance.workspace,
        user_id=instance.user,
        expected_sha256=probe.digest(content),
        expected_size_bytes=len(content),
        expires_at=datetime.now(UTC) - timedelta(minutes=10),
    )
    version = SimpleNamespace(
        object_version_id=vid,
        workspace_id=instance.workspace,
        content_sha256=probe.digest(content),
        provider_version_id="provider-version",
        etag="etag",
        physical_key="quarantine/private",
    )
    requests = (
        [SimpleNamespace(deadline_at=datetime.now(UTC) - timedelta(minutes=5))]
        if name == "scanner-clean"
        else []
    )
    session = SimpleNamespace(
        get=AsyncMock(side_effect=[row, version]),
        scalar=AsyncMock(side_effect=[state, 0, 0]),
        scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: requests)),
        rollback=AsyncMock(),
    )
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=session)
    context.__aexit__ = AsyncMock(return_value=False)
    instance.db = SimpleNamespace(sessions=lambda: context)
    instance.required = AsyncMock(return_value={"session_id": str(sid)})
    instance.read_receipt = AsyncMock(return_value=None)
    instance.record = AsyncMock()
    instance.worker = SimpleNamespace(
        read_version_properties=AsyncMock(),
        read_version=AsyncMock(return_value=b"changed" if wrong_bytes else content),
        delete_version=AsyncMock(),
        put_immutable=AsyncMock(),
    )
    if wrong_bytes:
        with pytest.raises(probe.ProbeFailure, match="original-provider-bytes-differ"):
            await instance.managed_replacement_key(name, manifest)
        instance.record.assert_not_awaited()
    else:
        assert (
            await instance.managed_replacement_key(name, manifest)
            == f"{instance.campaign}:{name}:scanner-admitted-1"
        )
        assert instance.record.await_args.args[2]["observations"]["original_bytes_retained"]
    instance.worker.delete_version.assert_not_awaited()
    instance.worker.put_immutable.assert_not_awaited()


@pytest.mark.parametrize(
    "accepted_count,seconds,allowed",
    [(2, -1, True), (0, 0, False), (0, 1, True), (1, -1, False), (1, 1, True)],
)
def test_scan_progress_boundary_preserves_existing_results(accepted_count, seconds, allowed):
    first, second = uuid.uuid4(), uuid.uuid4()
    now = datetime.now(UTC)
    accepted = set([first, second][:accepted_count])
    deadlines = {first: now, second: now + timedelta(seconds=seconds)}
    if allowed:
        probe.require_possible_scan_progress({first, second}, accepted, deadlines, now)
    else:
        with pytest.raises(probe.ProbeFailure, match="managed-scan-windows-closed-without-results"):
            probe.require_possible_scan_progress({first, second}, accepted, deadlines, now)


def test_scan_progress_requires_actual_request_and_accepts_completed_without_deadlines():
    version = uuid.uuid4()
    probe.require_possible_scan_progress({version}, {version}, {}, datetime.now(UTC))
    with pytest.raises(probe.ProbeFailure, match="managed-scan-required-request-missing"):
        probe.require_possible_scan_progress({version}, set(), {}, datetime.now(UTC))


@pytest.mark.parametrize("name", ["warm-clean", "warm-infected"])
@pytest.mark.parametrize("wrong_log", [False, True])
async def test_warm_scan_reconciles_delayed_exact_originals_without_mutation(name, wrong_log):
    instance = object.__new__(probe.Probe)
    instance.campaign, instance.workspace, instance.user = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    sid, vid = uuid.uuid4(), uuid.uuid4()
    content = probe.CLEAN if name == "warm-clean" else probe.EICAR
    prior = {"session_id": str(sid), "object_version_id": str(vid)}
    uploads = {"clean": prior, "infected": prior}
    deadline = datetime.now(UTC) - timedelta(minutes=5)
    row = SimpleNamespace(
        session_id=sid,
        object_version_id=vid,
        workspace_id=instance.workspace,
        user_id=instance.user,
    )
    version = SimpleNamespace(
        object_version_id=vid,
        content_sha256=probe.digest(content),
        provider_version_id="version",
        etag='"0x8D123456789ABCD"',
        physical_key="quarantine/private",
    )
    uri = "https://private.example/quarantine/private"
    manifest = {
        "token": "warm-log-1",
        "accepted_upload_receipt_sha256": probe.digest(uploads),
        "scanner_admission_receipt_sha256": "a" * 64,
        "delayed_log_diagnostic": {
            "execution_id": "actual-delayed-log-execution",
            "rows": [
                {
                    "effective_uri_sha256": "b" * 64 if wrong_log else probe.digest(uri),
                    "normalized_etag_sha256": probe.digest(
                        probe._normalize_azure_etag(version.etag)
                    ),
                    "scan_result": "No threats found" if name == "warm-clean" else "Malicious",
                    "ingested_at": (deadline + timedelta(seconds=10)).isoformat(),
                    "row_sha256": "c" * 64,
                }
            ],
        },
    }
    instance.required = AsyncMock(
        side_effect=[uploads, prior] if name == "warm-clean" else [uploads]
    )
    instance.read_receipt = AsyncMock(return_value=None)
    instance.record = AsyncMock()
    session = SimpleNamespace(
        get=AsyncMock(side_effect=[row, version]),
        scalar=AsyncMock(side_effect=["completed", 0, 0]),
        scalars=AsyncMock(
            return_value=SimpleNamespace(all=lambda: [SimpleNamespace(deadline_at=deadline)])
        ),
        rollback=AsyncMock(),
    )
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=session)
    context.__aexit__ = AsyncMock(return_value=False)
    instance.db = SimpleNamespace(sessions=lambda: context)
    instance.worker = SimpleNamespace(
        object_url=lambda key: uri,
        read_version_properties=AsyncMock(),
        read_version=AsyncMock(return_value=content),
        put_immutable=AsyncMock(),
        delete_version=AsyncMock(),
    )
    if wrong_log:
        with pytest.raises(
            probe.ProbeFailure, match="warm-scan-original-delayed-log-binding-differs"
        ):
            await instance.warm_scan_key(name, manifest)
        instance.record.assert_not_awaited()
        instance.worker.read_version.assert_not_awaited()
    else:
        assert (
            await instance.warm_scan_key(name, manifest) == f"{instance.campaign}:{name}:warm-log-1"
        )
        assert instance.record.await_args.args[2]["original"]["object_version_id"] == str(vid)
        instance.worker.read_version_properties.assert_awaited_once_with(
            physical_key=version.physical_key,
            provider_version_id="version",
            expected_etag=version.etag,
        )
    instance.worker.put_immutable.assert_not_awaited()
    instance.worker.delete_version.assert_not_awaited()
