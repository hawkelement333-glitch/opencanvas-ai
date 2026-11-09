from __future__ import annotations

import ast
import inspect
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPOSITORY_ROOT))

# The API test root is normally the import root; this focused infrastructure contract
# imports the repository-level campaign package after adding that explicit root.
# ruff: noqa: E402
from infra.milestone_7_8.azure_cli import (
    AzureCliError,
    AzureCliLauncher,
    AzureCliResolutionError,
    _canonical_file,
    local_version_smoke,
    main,
)
from infra.milestone_7_8.campaign import (
    CLEANUP_CANDIDATE_REGIONS_BINDING,
    CampaignConfig,
    CostItem,
    SubprocessRunner,
    load_ledger,
)
from infra.milestone_7_8.operator import command_plan, execute_commands


def _write_recorder(directory: Path) -> Path:
    recorder = directory / "record_argv.py"
    recorder.write_text(
        """from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sleep_seconds = float(os.environ.get("M78_TEST_SLEEP", "0"))
if sleep_seconds:
    time.sleep(sleep_seconds)
payload = {
    "arguments": sys.argv[1:],
    "environment": os.environ.get("M78_TEST_VALUE"),
    "temporaryBindings": sorted(
        name for name in os.environ if name.startswith("M78_AZURE_CLI_")
    ),
}
capture = os.environ.get("M78_TEST_CAPTURE")
if capture:
    Path(capture).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
stderr = os.environ.get("M78_TEST_STDERR")
if stderr:
    print(stderr, file=sys.stderr)
print(json.dumps(payload, ensure_ascii=False))
raise SystemExit(int(os.environ.get("M78_TEST_EXIT", "0")))
""",
        encoding="utf-8",
    )
    return recorder


def _test_environment(recorder: Path, **values: str) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "M78_TEST_PYTHON": sys.executable,
            "M78_TEST_RECORDER": str(recorder),
            "PYTHONUTF8": "1",
            **values,
        }
    )
    return environment


def _write_batch_launcher(directory: Path, suffix: str) -> Path:
    launcher = directory / f"az.{suffix}"
    launcher.write_text(
        '@echo off\n"%M78_TEST_PYTHON%" "%M78_TEST_RECORDER%" %*\nexit /b %ERRORLEVEL%\n',
        encoding="utf-8",
    )
    return launcher


def _write_native_launcher(directory: Path) -> Path:
    launcher = directory / ("az.exe" if os.name == "nt" else "az")
    try:
        os.link(sys.executable, launcher)
    except OSError:
        shutil.copy2(sys.executable, launcher)
    if os.name != "nt":
        launcher.chmod(0o755)
    return launcher


def _resolve_windows(directory: Path) -> AzureCliLauncher:
    return AzureCliLauncher.resolve(
        repository_root=REPOSITORY_ROOT,
        working_directory=REPOSITORY_ROOT,
        search_path=str(directory),
        platform="windows",
    )


@pytest.mark.skipif(os.name != "nt", reason="Windows batch launch contract")
@pytest.mark.parametrize("suffix", ["cmd", "bat"])
def test_windows_batch_launcher_preserves_exact_arguments_and_environment(
    tmp_path: Path, suffix: str
) -> None:
    launcher_directory = tmp_path / "Azure CLI with spaces"
    launcher_directory.mkdir()
    recorder = _write_recorder(tmp_path)
    _write_batch_launcher(launcher_directory, suffix)
    launcher = _resolve_windows(launcher_directory)
    sentinel = tmp_path / "must-not-exist.txt"
    odd_quote_sentinel = tmp_path / "odd-quote-must-not-exist.txt"
    arguments = (
        "plain",
        "two words",
        'quote"inside',
        'backslash\\"quote',
        "trailing\\",
        "Unicode-雪-café",
        "",
        json.dumps({"nested": ["value", 7]}, separators=(",", ":")),
        "&",
        "|",
        "<",
        ">",
        "^",
        "%PATH%",
        "(group)",
        "!bang!",
        f'& type nul > "{sentinel}"',
        f'odd" & type nul > {odd_quote_sentinel}',
    )
    capture = tmp_path / "captured.json"
    completed = launcher.run(
        arguments,
        cwd=tmp_path,
        env=_test_environment(
            recorder,
            M78_TEST_CAPTURE=str(capture),
            M78_TEST_VALUE="propagated-雪",
        ),
        timeout=10,
    )

    assert completed.returncode == 0
    assert completed.stderr == ""
    assert json.loads(completed.stdout) == {
        "arguments": list(arguments),
        "environment": "propagated-雪",
        "temporaryBindings": [],
    }
    assert json.loads(capture.read_text(encoding="utf-8"))["arguments"] == list(arguments)
    assert not sentinel.exists()
    assert not odd_quote_sentinel.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows batch launch contract")
def test_windows_batch_launcher_preserves_stderr_exit_and_timeout(tmp_path: Path) -> None:
    launcher_directory = tmp_path / "bin"
    launcher_directory.mkdir()
    recorder = _write_recorder(tmp_path)
    _write_batch_launcher(launcher_directory, "cmd")
    launcher = _resolve_windows(launcher_directory)

    failed = launcher.run(
        ("version",),
        env=_test_environment(
            recorder,
            M78_TEST_STDERR="expected stderr",
            M78_TEST_EXIT="23",
        ),
        timeout=10,
    )
    assert failed.returncode == 23
    assert failed.stderr.strip() == "expected stderr"
    assert json.loads(failed.stdout)["arguments"] == ["version"]

    with pytest.raises(subprocess.TimeoutExpired):
        launcher.run(
            ("version",),
            env=_test_environment(recorder, M78_TEST_SLEEP="1"),
            timeout=0.05,
        )


def test_native_launcher_executes_with_exact_arguments_and_json_stdout(tmp_path: Path) -> None:
    launcher_directory = tmp_path / "native bin"
    launcher_directory.mkdir()
    recorder = _write_recorder(tmp_path)
    native = _write_native_launcher(launcher_directory)
    resolved = AzureCliLauncher.resolve(
        repository_root=REPOSITORY_ROOT,
        working_directory=REPOSITORY_ROOT,
        search_path=str(launcher_directory),
        platform="windows" if os.name == "nt" else "posix",
    )
    launcher = AzureCliLauncher(path=Path(sys.executable), kind="native")
    completed = launcher.run(
        (str(recorder), "", "two words", "Unicode-雪", '{"key":"value"}'),
        env=_test_environment(recorder, M78_TEST_VALUE="native"),
        timeout=10,
    )

    assert resolved.path == native.resolve()
    assert resolved.kind == "native"
    assert completed.returncode == 0
    assert json.loads(completed.stdout) == {
        "arguments": ["", "two words", "Unicode-雪", '{"key":"value"}'],
        "environment": "native",
        "temporaryBindings": [],
    }


@pytest.mark.skipif(os.name != "nt", reason="Windows launcher preference")
def test_windows_native_launcher_is_preferred_over_batch(tmp_path: Path) -> None:
    launcher_directory = tmp_path / "bin"
    launcher_directory.mkdir()
    native = _write_native_launcher(launcher_directory)
    _write_batch_launcher(launcher_directory, "cmd")

    launcher = _resolve_windows(launcher_directory)

    assert launcher.kind == "native"
    assert launcher.path == native.resolve()


def test_resolution_rejects_missing_spoofed_relative_and_arbitrary_launchers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(AzureCliResolutionError, match=r"az\.exe, az\.cmd, az\.bat"):
        AzureCliLauncher.resolve(
            repository_root=REPOSITORY_ROOT,
            working_directory=REPOSITORY_ROOT,
            search_path=str(empty),
            platform="windows",
        )

    fake_repository = tmp_path / "repository"
    fake_bin = fake_repository / ".runtime" / "campaign" / "bin"
    fake_bin.mkdir(parents=True)
    _write_batch_launcher(fake_bin, "cmd")
    with pytest.raises(AzureCliResolutionError, match="campaign-controlled"):
        AzureCliLauncher.resolve(
            repository_root=fake_repository,
            working_directory=REPOSITORY_ROOT,
            search_path=str(fake_bin),
            platform="windows",
        )

    with pytest.raises(AzureCliResolutionError, match="not absolute"):
        _canonical_file(Path("relative") / "az.cmd")

    arbitrary = tmp_path / "tool.exe"
    arbitrary.write_bytes(b"not an Azure CLI launcher")
    monkeypatch.setattr(
        "infra.milestone_7_8.azure_cli.shutil.which",
        lambda *_args, **_kwargs: str(arbitrary),
    )
    with pytest.raises(AzureCliResolutionError, match="name is invalid"):
        AzureCliLauncher.resolve(
            repository_root=REPOSITORY_ROOT,
            working_directory=REPOSITORY_ROOT,
            search_path=str(tmp_path),
            platform="windows",
        )
    assert "override" not in inspect.signature(AzureCliLauncher.resolve).parameters


def test_subprocess_invocations_are_shell_false_and_launcher_is_resolved_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str | tuple[str, ...], dict[str, object]]] = []

    def fake_run(
        command: str | tuple[str, ...], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, "{}", "")

    def timeout_value(
        call: tuple[str | tuple[str, ...], dict[str, object]],
    ) -> object:
        return call[1]["timeout"]

    monkeypatch.setattr("infra.milestone_7_8.azure_cli.subprocess.run", fake_run)
    launcher = AzureCliLauncher(path=Path(sys.executable), kind="native")
    launcher.run(("version",), timeout=7)
    assert calls[0][1]["shell"] is False
    assert timeout_value(calls[0]) == 7

    calls.clear()
    batch = AzureCliLauncher(
        path=Path("C:/Program Files/Microsoft SDKs/Azure/CLI2/wbin/az.cmd"),
        kind="batch",
        command_processor=Path("C:/Windows/System32/cmd.exe"),
    )
    batch.run(("version", "&"), timeout=8)
    assert calls[0][1]["shell"] is False
    assert timeout_value(calls[0]) == 8
    assert " /d /s /v:off /c " in calls[0][0]

    class FakeLauncher:
        def run(
            self, arguments: tuple[str, ...], **_kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(arguments, 0, "{}", "")

    resolutions = 0

    def resolve_once() -> FakeLauncher:
        nonlocal resolutions
        resolutions += 1
        return FakeLauncher()

    monkeypatch.setattr(AzureCliLauncher, "resolve", resolve_once)
    runner = SubprocessRunner()
    assert runner.run(("az", "version"))["exitCode"] == 0
    assert runner.run(("az", "group", "list"))["exitCode"] == 0
    assert resolutions == 1


def test_missing_cli_and_invalid_arguments_fail_before_runtime_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = tmp_path / "ledger.json"
    config = CampaignConfig(
        campaign_id="mobius78-launch-test",
        generation_id="g1-aabbccddeeff",
        subscription_correlation="a" * 16,
        tenant_correlation="b" * 16,
        target_resource_group="rg-m78-aabbccddee-target",
        cleanup_resource_group="rg-m78-aabbccddee-cleanup",
        target_region="centralus",
        cleanup_region="eastus2",
        postgres_region="centralus",
        cleanup_deadline_utc="2030-01-01T04:00:00Z",
        conservative_estimate_usd="25.6832",
        contingency_percent="25",
        resource_items=(CostItem("bounded-campaign", "5.13664", 4),),
        principal_manifest_sha256="c" * 64,
        cleanup_region_selection_sha256="f" * 64,
        cleanup_candidate_regions=CLEANUP_CANDIDATE_REGIONS_BINDING,
        cleanup_offer_classification="restricted-public-offer",
        cleanup_offer_eligibility_disposition=("restricted-offer-metadata-confirmed"),
        cleanup_offer_eligible_regions=("eastus,eastus2,northeurope,southeastasia,westus"),
        cleanup_offer_eligibility_source=(
            "microsoft-automation-restricted-public-offer-regions-2026-08-v1"
        ),
        cleanup_offer_eligibility_sha256="e" * 64,
        fresh_controller_admission_evidence_sha256="0" * 64,
    )
    load_ledger(ledger, config)
    assert not ledger.exists()

    def unavailable() -> AzureCliLauncher:
        raise AzureCliResolutionError("trusted Azure CLI launcher unavailable")

    monkeypatch.setattr(AzureCliLauncher, "resolve", unavailable)
    with pytest.raises(AzureCliResolutionError, match="launcher unavailable"):
        SubprocessRunner().run(("az", "version"))
    assert not ledger.exists()

    launcher = AzureCliLauncher(
        path=Path("C:/Azure/az.cmd"),
        kind="batch",
        command_processor=Path("C:/Windows/System32/cmd.exe"),
    )
    with pytest.raises(AzureCliError, match="control character"):
        launcher.run(("bad\nargument",))
    with pytest.raises(AzureCliError, match="control character"):
        AzureCliLauncher(path=Path(sys.executable), kind="native").run(("bad\rargument",))


def test_local_version_smoke_is_bounded_and_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeLauncher:
        kind = "batch"

        def __init__(self) -> None:
            self.calls: list[tuple[tuple[str, ...], object]] = []

        def run(
            self, arguments: tuple[str, ...], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            self.calls.append((arguments, kwargs["timeout"]))
            return subprocess.CompletedProcess(
                arguments,
                0,
                json.dumps({"azure-cli": "2.77.0", "extensions": {"private": "value"}}),
                "",
            )

    fake = FakeLauncher()
    monkeypatch.setattr(AzureCliLauncher, "resolve", lambda: fake)
    assert local_version_smoke() == {
        "status": "passed",
        "launcherType": "batch",
        "azureCliVersion": "2.77.0",
    }
    assert fake.calls == [(("version", "--output", "json"), 60)]

    class MalformedLauncher:
        kind = "batch"

        def run(
            self, _arguments: tuple[str, ...], **_kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess((), 0, '{"azure-cli":"secret value"}', "")

    monkeypatch.setattr(AzureCliLauncher, "resolve", lambda: MalformedLauncher())
    with pytest.raises(AzureCliError, match="malformed"):
        local_version_smoke()


def test_cli_invoke_forwards_exact_arguments_streams_and_exit_code(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class FakeLauncher:
        def run(
            self, arguments: tuple[str, ...], **_kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            assert arguments == ("version", "--output", "json", "two words", "&")
            return subprocess.CompletedProcess(
                arguments, 19, "expected stdout\n", "expected stderr\n"
            )

    monkeypatch.setattr(AzureCliLauncher, "resolve", lambda: FakeLauncher())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "azure_cli",
            "invoke",
            "--",
            "version",
            "--output",
            "json",
            "two words",
            "&",
        ],
    )

    assert main() == 19
    captured = capsys.readouterr()
    assert captured.out == "expected stdout\n"
    assert captured.err == "expected stderr\n"


def test_process_failures_are_redacted_at_cli_and_campaign_boundaries(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class FailingLauncher:
        def run(
            self, _arguments: tuple[str, ...], **_kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            raise subprocess.TimeoutExpired(
                cmd=("az", "--client-secret", "must-not-leak"), timeout=1
            )

    failing = FailingLauncher()
    monkeypatch.setattr(AzureCliLauncher, "resolve", lambda: failing)
    monkeypatch.setattr(sys, "argv", ["azure_cli", "invoke", "--", "version"])
    assert main() == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Azure CLI process failed safely" in captured.err
    assert "must-not-leak" not in captured.err

    with pytest.raises(AzureCliError, match="process failed safely") as failure:
        SubprocessRunner(azure_cli=failing).run(("az", "version"))  # type: ignore[arg-type]
    assert "must-not-leak" not in str(failure.value)


@pytest.mark.skipif(os.name != "nt", reason="Windows operator launch contract")
def test_operator_preflight_executes_fake_batch_through_central_launcher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    launcher_directory = tmp_path / "operator bin"
    launcher_directory.mkdir()
    recorder = _write_recorder(tmp_path)
    _write_batch_launcher(launcher_directory, "cmd")
    launcher = _resolve_windows(launcher_directory)
    for name, value in _test_environment(recorder).items():
        monkeypatch.setenv(name, value)
    monkeypatch.chdir(REPOSITORY_ROOT)
    runtime = {
        "resourceGroupName": "rg-m78-aabbccddee-target",
        "cleanupResourceGroupName": "rg-m78-aabbccddee-cleanup",
        "automationAccountName": "aa-m78-proof",
        "runbookName": "rb-m78-proof",
    }

    results = execute_commands(
        SubprocessRunner(azure_cli=launcher, timeout_seconds=30),
        command_plan("preflight", object(), runtime),  # type: ignore[arg-type]
    )

    assert len(results) == 7
    assert results[5]["exitCode"] == 0
    assert json.loads(str(results[5]["stdout"]))["arguments"] == [
        "version",
        "--output",
        "json",
    ]


def test_no_milestone_7_8_call_site_directly_executes_literal_az() -> None:
    violations: list[str] = []
    for source_path in sorted((REPOSITORY_ROOT / "infra" / "milestone_7_8").glob("*.py")):
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            direct_subprocess = (
                isinstance(function, ast.Attribute)
                and function.attr in {"run", "Popen", "call", "check_call", "check_output"}
                and isinstance(function.value, ast.Name)
                and function.value.id == "subprocess"
            )
            if direct_subprocess and any(
                isinstance(item, ast.Constant) and item.value == "az"
                for argument in node.args
                for item in ast.walk(argument)
            ):
                violations.append(f"{source_path.name}:{node.lineno}")
    assert violations == []

    sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((REPOSITORY_ROOT / "infra" / "milestone_7_8").glob("*.py"))
    )
    assert "shell=True" not in sources
    assert "Invoke-Expression" not in sources
    assert "Start-Process" not in sources

    current_runbooks = (
        REPOSITORY_ROOT / "infra" / "milestone_7_8" / "README.md",
        REPOSITORY_ROOT / "docs" / "MILESTONE_7_8_MANAGED_POSTGRESQL_CAMPAIGN_OPERATOR_RUNBOOK.md",
    )
    direct_documented_invocations = [
        f"{path.name}:{line_number}"
        for path in current_runbooks
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if line.lstrip().startswith("az ") or " = az " in line
    ]
    assert direct_documented_invocations == []
