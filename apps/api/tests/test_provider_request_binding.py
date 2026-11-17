import pytest
from infra.milestone_7_8.pilot_validation import provider_requests_for_approval


def test_forecast_calendar_days_are_derived_only_from_actual_approval_window():
    plan = {
        "relativeWindowHours": {"cleanupBy": 10},
        "providerObservationRequests": [
            {
                "method": "POST",
                "resourceId": "/exact-target/forecast",
                "body": {"timePeriod": {"from": "${APPROVAL_DAY_UTC}", "to": "${CLEANUP_DAY_UTC}"}},
            }
        ],
    }
    result = provider_requests_for_approval(plan, {"approvedAt": "2026-11-17T20:00:00Z"})
    assert result[0]["body"]["timePeriod"] == {
        "from": "2026-11-17T00:00:00+00:00",
        "to": "2026-11-18T23:59:59+00:00",
    }
    assert result[0]["resourceId"] == "/exact-target/forecast"
    assert (
        plan["providerObservationRequests"][0]["body"]["timePeriod"]["from"]
        == "${APPROVAL_DAY_UTC}"
    )
    plan["providerObservationRequests"][0]["resourceId"] = "${ARBITRARY_SCOPE}"
    with pytest.raises(ValueError, match="unknown provider"):
        provider_requests_for_approval(plan, {"approvedAt": "2026-11-17T20:00:00Z"})
