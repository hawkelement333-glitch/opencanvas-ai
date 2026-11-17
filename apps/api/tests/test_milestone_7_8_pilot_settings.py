from pathlib import Path

import pytest

from opencanvas_api.core.config import Settings


def test_pilot_scanner_overlay_does_not_change_defaults_or_upload_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "OPENCANVAS_MALWARE_SCAN_TIMEOUT_SECONDS",
        "OPENCANVAS_SCANNER_RESULT_BRIDGE_RETRY_MAX_SECONDS",
        "OPENCANVAS_UPLOAD_CAPABILITY_TTL_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)
    defaults = Settings(environment="test", _env_file=None)
    overlay = Path(__file__).resolve().parents[3] / "infra/milestone_7_8/pilot/.env.example"
    pilot = Settings(environment="test", _env_file=overlay)

    assert defaults.malware_scan_timeout_seconds == 300
    assert defaults.scanner_result_bridge_retry_max_seconds == 300
    assert pilot.malware_scan_timeout_seconds == 900
    assert pilot.scanner_result_bridge_retry_max_seconds == 20
    assert pilot.upload_capability_ttl_seconds == defaults.upload_capability_ttl_seconds == 300
    assert pilot.object_ingestion_mode == defaults.object_ingestion_mode
    assert pilot.scanner_result_bridge_mode == defaults.scanner_result_bridge_mode
    assert pilot.malware_policy_version == defaults.malware_policy_version
