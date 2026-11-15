from datetime import UTC, datetime, timedelta

from infra.milestone_7_8.controller_renewal import _durable_record
from infra.milestone_7_8.evidence_console import (
    EvidenceConsole,
    _capture_path,
    _console_io_path,
)


class Runner:
    def run(self, command):
        return {"exitCode": 0, "stdout": "{}", "stderr": ""}


def test_deep_console_paths_retain_requests_results_and_short_capture_names(tmp_path):
    directory = tmp_path
    while len(str(directory)) < 270:
        directory /= "nested-campaign-evidence"
    _console_io_path(directory.parent).mkdir(parents=True)
    console = EvidenceConsole(
        Runner(),
        {"subscriptionId": "subscription"},
        image_digest="sha256:" + "a" * 64,
        directory=directory,
        deadline=datetime.now(UTC) + timedelta(minutes=1),
        authorize=lambda: None,
    )
    console.run(("az", "rest", "--method", "get"))
    capture = _capture_path(directory, console.sequence)
    assert capture.name == "c0001.json"
    record = {"execution": "long-job-execution-name-" * 8, "phase": "api", "token": "b" * 32}
    _durable_record(_console_io_path(capture), record)
    assert _console_io_path(capture).is_file()
    assert _console_io_path(directory / "0001.intent.json").is_file()
    assert _console_io_path(directory / "0001.result.json").is_file()
    assert capture.parent == directory
