from __future__ import annotations

import hashlib

import pytest
from infra.milestone_7_8.pilot_application_probe import save_editable_artifact

from opencanvas_api.api.routes.agents import _draft_out
from tests.test_draft_artifacts import generated, original_evidence


@pytest.mark.parametrize("corruption", [None, "text", "citations", "insufficientEvidence"])
async def test_managed_artifact_probe_checks_actual_api_evidence(client, database, corruption):
    bundle, source, _, result, _, _ = await generated(database)
    original = await original_evidence(database)
    observed = _draft_out(result).model_dump(mode="json", by_alias=True)
    observed["textSha256"] = hashlib.sha256(result.text.encode()).hexdigest()

    class LocalApi:
        calls = 0

        async def request(self, method, path, *, statuses=(200,), data=None):
            self.calls += 1
            response = await client.request(method, path, json=data)
            assert response.status_code in statuses, response.text
            body = response.json()
            if self.calls == 1:
                if corruption == "text":
                    body["text"] = "not the generated response"
                elif corruption == "citations":
                    body["draftProvenance"]["citations"] = []
                elif corruption == "insufficientEvidence":
                    body["draftProvenance"]["insufficientEvidence"] = True
            return body

    api = LocalApi()
    fixture = {"workspaceId": str(bundle.execution.workspace_id), "canvasId": str(source.canvas_id)}
    if corruption:
        with pytest.raises(ValueError, match="original evidence differs"):
            await save_editable_artifact(api, fixture, observed)
        assert api.calls == 1  # Reject bad original evidence before editing.
    else:
        receipt = await save_editable_artifact(api, fixture, observed)
        assert receipt["explicitSaveDuplicateEditReloadOriginalEvidence"] == "accepted"
        assert api.calls == 5
    assert await original_evidence(database) == original
