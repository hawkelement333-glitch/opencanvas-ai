from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from infra.milestone_7_8.pilot.artifact_transport import checked_zip
from infra.milestone_7_8.pilot_application_probe import (
    SNAPSHOT_TABLES,
    Api,
    Journal,
    compare_snapshots,
)

from opencanvas_api.db.models import Base


def test_restore_inventory_uses_real_workspace_scoped_tables() -> None:
    for name in SNAPSHOT_TABLES:
        assert "workspace_id" in Base.metadata.tables[name].c


def test_snapshot_equality_never_claims_runtime_role_or_recovery_acceptance() -> None:
    tables = {
        name: [{"identity": {"id": "synthetic"}, "sha256": "a" * 64}] for name in SNAPSHOT_TABLES
    }
    before = {
        "workspaceId": "synthetic",
        "schemaRevision": "20260726_0029",
        "tables": tables,
        "grants": [],
    }
    result = compare_snapshots(before, before)
    assert result["R3NonterminalRecovery"] == "unproved"
    assert result["R2ApiWorkerOwnershipAndScope"] == "unproved"
    changed = json.loads(json.dumps(before))
    changed["tables"]["malware_scan_results"][0]["sha256"] = "b" * 64
    with pytest.raises(ValueError, match="restored rows differ"):
        compare_snapshots(before, changed)


def test_archive_hash_and_path_escape_are_rejected() -> None:
    for name in ("../escape", "/absolute", "C:escape"):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr(name, "synthetic")
        data = stream.getvalue()
        with pytest.raises(ValueError, match="unsafe"):
            checked_zip(data, hashlib.sha256(data).hexdigest())
    with pytest.raises(ValueError, match="hash"):
        checked_zip(b"not the approved artifact", "a" * 64)


async def test_mutation_uncertainty_keeps_intent_and_does_not_retry(tmp_path) -> None:
    calls = 0

    async def transport(request):
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("fixture", request=request)

    bindings = {
        "imageDigest": "sha256:" + "a" * 64,
        "sourceCommit": "b" * 40,
        "release": "fixture",
        "deployment": "fixture",
    }
    output = tmp_path / "result.json"
    journal = Journal(
        output, "fixture-execution", "core", bindings, datetime.now(UTC) + timedelta(minutes=1)
    )
    async with httpx.AsyncClient(
        base_url="https://fixture.invalid", transport=httpx.MockTransport(transport)
    ) as client:
        api = Api(client, journal, "fixture-execution")
        with pytest.raises(httpx.ReadTimeout):
            await api.request("POST", "/api/v1/canvases", data={"name": "synthetic"})
    assert calls == 1 and output.with_suffix(".intent.json").exists()
    assert len(list(output.with_suffix(".steps").glob("*http-intent.json"))) == 1
    assert not output.exists()
    with pytest.raises(FileExistsError):
        Journal(
            output, "fixture-execution", "core", bindings, datetime.now(UTC) + timedelta(minutes=1)
        )


async def test_mixed_workload_enforces_provider_and_write_bounds() -> None:
    from infra.milestone_7_8.pilot_application_probe import workload

    class FixtureApi:
        execution = "local-probe-test"
        model_calls = 0
        writes = 0

        async def signin(self):
            return {}

        async def ground(self, fixture, **kwargs):
            self.model_calls += 1
            return {"citations": []}

        async def request(self, method, path, **kwargs):
            if path.endswith("/nodes"):
                self.writes += 1
                return {"id": "local-fixture"}
            return {"nodes": [], "matches": [{"id": "local-fixture"}]}

    fixture = {"canvasId": "fixture", "primary": {"documentId": "fixture"}}
    api = FixtureApi()
    result = await workload(
        api, fixture, {"applicationProofCaps": {"requests": 200, "concurrency": 8}}
    )
    assert api.model_calls == 2 and api.writes == 10
    assert len(result["measurements"]) == 200
    with pytest.raises(ValueError, match="exceeds prepared bound"):
        await workload(api, fixture, {"applicationProofCaps": {"requests": 201, "concurrency": 8}})


def test_application_dispatch_is_fully_covered_by_bound_authority() -> None:
    from infra.milestone_7_8.pilot_application_probe import OPERATIONS
    from infra.milestone_7_8.pilot_validation import APPLICATION_OPERATIONS

    assert OPERATIONS == APPLICATION_OPERATIONS
    assert {"account", "restore-fixture", "restore-fence", "restore-resume"} <= set(OPERATIONS)
