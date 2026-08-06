from datetime import UTC, datetime

import pytest
from preflight.milestone_7_7.cleanup_control_recovery import (
    CleanupControlRecoveryError,
    build_cleanup_control_recovery_authorization,
)

SUBSCRIPTION = "/subscriptions/opaque"
CLEANUP_GROUP = f"{SUBSCRIPTION}/resourceGroups/rg-solarplexus-mobius-77-cleanup-control"
TARGET_GROUP = f"{SUBSCRIPTION}/resourceGroups/rg-solarplexus-mobius-77-staging"
AUTOMATION_PREFIX = f"{CLEANUP_GROUP}/providers/Microsoft.Automation/automationAccounts"


def _authorization():
    return build_cleanup_control_recovery_authorization(
        repository_head="a" * 40,
        subscription_id="opaque-subscription",
        cleanup_resource_group_id=CLEANUP_GROUP,
        corrupted_automation_account_id=f"{AUTOMATION_PREFIX}/aa-mobius77-cleanup",
        replacement_automation_account_id=f"{AUTOMATION_PREFIX}/aa-mobius77-cleanup-recovery",
        target_resource_group_id=TARGET_GROUP,
        runbook_content_sha256="b" * 64,
        now_utc=datetime(2026, 8, 6, tzinfo=UTC),
    )


def test_cleanup_recovery_authorization_is_image_free_and_exact() -> None:
    authorization = _authorization()
    serialized = authorization.__dict__
    assert authorization.replacementAutomationAccount == "aa-mobius77-cleanup-recovery"
    assert authorization.bindingId == "f61544fe-cd79-5247-ac8b-ee9697b6ffd6"
    assert authorization.roleScope.endswith("rg-solarplexus-mobius-77-staging")
    assert all("image" not in key.casefold() for key in serialized)
    assert all("acr" not in operation for operation in authorization.allowedOperations)
    assert (
        "build_authorization_ledger"
        not in build_cleanup_control_recovery_authorization.__code__.co_names
    )


@pytest.mark.parametrize("field", ["replacement", "target"])
def test_cleanup_recovery_rejects_scope_drift(field: str) -> None:
    kwargs = {
        "repository_head": "a" * 40,
        "subscription_id": "opaque-subscription",
        "cleanup_resource_group_id": CLEANUP_GROUP,
        "corrupted_automation_account_id": f"{AUTOMATION_PREFIX}/aa-mobius77-cleanup",
        "replacement_automation_account_id": f"{AUTOMATION_PREFIX}/aa-mobius77-cleanup-recovery",
        "target_resource_group_id": TARGET_GROUP,
        "runbook_content_sha256": "b" * 64,
        "now_utc": datetime(2026, 8, 6, tzinfo=UTC),
    }
    if field == "replacement":
        kwargs["replacement_automation_account_id"] = (
            f"{SUBSCRIPTION}/providers/Microsoft.Automation/automationAccounts/other"
        )
    else:
        kwargs["target_resource_group_id"] = f"{SUBSCRIPTION}/resourceGroups/other"
    with pytest.raises(CleanupControlRecoveryError):
        build_cleanup_control_recovery_authorization(**kwargs)
