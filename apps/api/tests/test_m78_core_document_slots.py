from __future__ import annotations

import uuid

import pytest
from infra.milestone_7_8.capacity_validation import (
    core_recovery_document_slots,
    resolve_templates,
)


def fixture():
    return {
        "workspaceId": str(uuid.uuid4()),
        "canvasId": str(uuid.uuid4()),
        "userId": str(uuid.uuid4()),
        **{key: {"documentId": str(uuid.uuid4())} for key in ("primary", "queued", "deletion")},
    }


def test_refresh_slots_bind_only_distinct_retained_core_documents():
    retained = fixture()
    slots = core_recovery_document_slots(retained)
    assert resolve_templates("${QUEUED_DOCUMENT}", slots) == retained["queued"]["documentId"]
    assert resolve_templates("${DELETION_DOCUMENT}", slots) == retained["deletion"]["documentId"]


def test_absent_core_document_cannot_be_filled_by_arbitrary_template():
    retained = fixture()
    del retained["queued"]
    with pytest.raises(ValueError, match="unknown operation-template slot"):
        resolve_templates("${QUEUED_DOCUMENT}", core_recovery_document_slots(retained))


@pytest.mark.parametrize("field", ["workspaceId", "canvasId", "userId"])
def test_cross_scope_core_document_rejected(field):
    retained = fixture()
    retained["queued"][field] = str(uuid.uuid4())
    with pytest.raises(ValueError, match="scope differs"):
        core_recovery_document_slots(retained)


def test_recovery_alias_cannot_reindex_only_one_head():
    retained = fixture()
    retained["deletion"] = retained["queued"].copy()
    with pytest.raises(ValueError, match="distinct"):
        core_recovery_document_slots(retained)
