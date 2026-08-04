from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest
from preflight.milestone_7_7 import managed_binding_execution
from preflight.milestone_7_7 import publication_path_admission as admission

HEAD = "a" * 40


def _completed(
    argv: Sequence[str],
    *,
    returncode: int,
    stdout: bytes = b"",
    stderr: bytes = b"",
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.CompletedProcess(tuple(argv), returncode, stdout, stderr)


def _runner(
    pull_error: bytes = b"unauthorized: authentication required",
    *,
    container_returncode: int = 0,
    container_output: bytes = b"proved\n",
) -> tuple[Callable[..., subprocess.CompletedProcess[bytes]], list[dict[str, object]]]:
    calls: list[dict[str, object]] = []

    def run(argv: Sequence[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        command = tuple(argv)
        calls.append({"argv": command, **kwargs})
        if command[1:] == ("context", "show"):
            return _completed(command, returncode=0, stdout=b"default\n")
        if command[1:3] == ("version", "--format"):
            return _completed(command, returncode=0, stdout=b"linux\n")
        if command[1:3] == ("image", "inspect"):
            if ":source-" in command[-1]:
                return _completed(command, returncode=0, stdout=b"[]")
            return _completed(command, returncode=1, stderr=b"No such image")
        if command[1:3] == ("container", "inspect"):
            return _completed(command, returncode=1, stderr=b"No such container")
        if command[1] == "run":
            return _completed(
                command,
                returncode=container_returncode,
                stdout=container_output,
            )
        if command[1:3] == ("pull", "--platform"):
            return _completed(command, returncode=1, stderr=pull_error)
        raise AssertionError(command)

    return run, calls


def _base_environment() -> dict[str, str]:
    return {"PATH": "synthetic-path"}


def test_exact_host_and_daemon_publication_path_passes_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run, calls = _runner()
    host_probes: list[str] = []
    monkeypatch.setattr(admission.shutil, "which", lambda *_args, **_kwargs: "C:/docker.exe")

    result = admission.verify_private_registry_publication_path(
        repository_head=HEAD,
        runner=run,
        host_probe=host_probes.append,
        base_environment=_base_environment(),
    )

    assert result["status"] == "proved"
    assert result["credentialsUsed"] is False
    assert result["mutationPerformed"] is False
    assert result["dockerNetworkPathProved"] is True
    assert result["probeOutcome"] == "registry-reached-without-credentials"
    assert host_probes == [admission.REGISTRY_HOST]
    pull = next(call for call in calls if tuple(call["argv"])[1] == "pull")
    assert tuple(pull["argv"])[1:] == (
        "pull",
        "--platform",
        "linux/amd64",
        (
            f"{admission.REGISTRY_HOST}/{admission.REGISTRY_REPOSITORY}:"
            f"mobius77-publication-path-probe-{HEAD}"
        ),
    )
    docker_configs = {str(call["env"]["DOCKER_CONFIG"]) for call in calls}  # type: ignore[index]
    assert len(docker_configs) == 1
    assert all(not Path(path).exists() for path in docker_configs)
    container = next(call for call in calls if tuple(call["argv"])[1] == "run")
    container_argv = tuple(container["argv"])
    assert "--pull" in container_argv
    assert container_argv[container_argv.index("--pull") + 1] == "never"
    assert "--network" in container_argv
    assert container_argv[container_argv.index("--network") + 1] == "bridge"
    assert "--read-only" in container_argv
    assert "--cap-drop" in container_argv
    assert container_argv[container_argv.index("--cap-drop") + 1] == "ALL"
    assert container_argv[-2:] == (
        admission.REGISTRY_HOST,
        str(admission.EXPECTED_PRIVATE_SUBNET),
    )


@pytest.mark.parametrize(
    ("message", "error_code"),
    [
        (b"dial tcp: lookup registry: no such host", "publication-path-daemon-dns-unavailable"),
        (b"x509: certificate signed by unknown authority", "publication-path-daemon-tls-failed"),
        (b"dial tcp: no route to host", "publication-path-daemon-route-failed"),
        (b"unexpected registry response", "publication-path-registry-response-unrecognized"),
    ],
)
def test_daemon_path_failures_are_distinct_and_fail_closed(
    monkeypatch: pytest.MonkeyPatch, message: bytes, error_code: str
) -> None:
    run, _calls = _runner(message)
    monkeypatch.setattr(admission.shutil, "which", lambda *_args, **_kwargs: "C:/docker.exe")

    with pytest.raises(admission.PublicationPathAdmissionError, match=error_code):
        admission.verify_private_registry_publication_path(
            repository_head=HEAD,
            runner=run,
            host_probe=lambda _hostname: None,
            base_environment=_base_environment(),
        )


def test_host_success_does_not_substitute_for_daemon_dns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run, _calls = _runner(b"lookup registry: no such host")
    host_probes: list[str] = []
    monkeypatch.setattr(admission.shutil, "which", lambda *_args, **_kwargs: "C:/docker.exe")

    with pytest.raises(
        admission.PublicationPathAdmissionError,
        match="publication-path-daemon-dns-unavailable",
    ):
        admission.verify_private_registry_publication_path(
            repository_head=HEAD,
            runner=run,
            host_probe=host_probes.append,
            base_environment=_base_environment(),
        )
    assert host_probes == [admission.REGISTRY_HOST]


@pytest.mark.parametrize(
    ("returncode", "output", "error_code"),
    [
        (41, b"dns-unavailable\n", "publication-path-daemon-dns-unavailable"),
        (42, b"dns-not-private\n", "publication-path-daemon-resolved-publicly"),
        (43, b"route-unavailable\n", "publication-path-daemon-route-failed"),
        (44, b"tls-failed\n", "publication-path-daemon-tls-failed"),
        (1, b"unexpected\n", "publication-path-daemon-probe-result-malformed"),
    ],
)
def test_container_network_probe_proves_private_dns_route_and_tls(
    monkeypatch: pytest.MonkeyPatch,
    returncode: int,
    output: bytes,
    error_code: str,
) -> None:
    run, _calls = _runner(
        container_returncode=returncode,
        container_output=output,
    )
    monkeypatch.setattr(admission.shutil, "which", lambda *_args, **_kwargs: "C:/docker.exe")

    with pytest.raises(admission.PublicationPathAdmissionError, match=error_code):
        admission.verify_private_registry_publication_path(
            repository_head=HEAD,
            runner=run,
            host_probe=lambda _hostname: None,
            base_environment=_base_environment(),
        )


def test_path_is_reproved_and_later_dns_loss_is_detected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first, _calls = _runner()
    second, _second_calls = _runner(b"lookup registry: no such host")
    monkeypatch.setattr(admission.shutil, "which", lambda *_args, **_kwargs: "C:/docker.exe")

    admission.verify_private_registry_publication_path(
        repository_head=HEAD,
        runner=first,
        host_probe=lambda _hostname: None,
        base_environment=_base_environment(),
    )
    with pytest.raises(
        admission.PublicationPathAdmissionError,
        match="publication-path-daemon-dns-unavailable",
    ):
        admission.verify_private_registry_publication_path(
            repository_head=HEAD,
            runner=second,
            host_probe=lambda _hostname: None,
            base_environment=_base_environment(),
        )


def test_proxy_environment_is_rejected_before_any_docker_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run, calls = _runner()
    monkeypatch.setattr(admission.shutil, "which", lambda *_args, **_kwargs: "C:/docker.exe")

    with pytest.raises(
        admission.PublicationPathAdmissionError,
        match="publication-path-proxy-environment-unapproved",
    ):
        admission.verify_private_registry_publication_path(
            repository_head=HEAD,
            runner=run,
            host_probe=lambda _hostname: None,
            base_environment={"PATH": "synthetic", "HTTPS_PROXY": "redacted"},
        )
    assert calls == []


def test_unexpected_probe_pull_is_removed_before_failing_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []

    def run(argv: Sequence[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        command = tuple(argv)
        calls.append(command)
        if command[1:] == ("context", "show"):
            return _completed(command, returncode=0, stdout=b"default\n")
        if command[1:3] == ("version", "--format"):
            return _completed(command, returncode=0, stdout=b"linux\n")
        if command[1:3] == ("image", "inspect"):
            if ":source-" in command[-1]:
                return _completed(command, returncode=0, stdout=b"[]")
            return _completed(command, returncode=1, stderr=b"No such image")
        if command[1:3] == ("container", "inspect"):
            return _completed(command, returncode=1, stderr=b"No such container")
        if command[1] == "run":
            return _completed(command, returncode=0, stdout=b"proved\n")
        if command[1:3] == ("pull", "--platform"):
            return _completed(command, returncode=0)
        if command[1:4] == ("image", "rm", "--force"):
            return _completed(command, returncode=0)
        raise AssertionError(command)

    monkeypatch.setattr(admission.shutil, "which", lambda *_args, **_kwargs: "C:/docker.exe")

    with pytest.raises(
        admission.PublicationPathAdmissionError,
        match="publication-path-probe-image-unexpectedly-readable",
    ):
        admission.verify_private_registry_publication_path(
            repository_head=HEAD,
            runner=run,
            host_probe=lambda _hostname: None,
            base_environment=_base_environment(),
        )
    cleanup = next(command for command in calls if command[1:4] == ("image", "rm", "--force"))
    assert cleanup[-1].endswith(f"mobius77-publication-path-probe-{HEAD}")


def test_ledger_is_not_written_when_publication_path_is_unproved(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ledger_path = tmp_path / "authorization-ledger.json"

    def blocked(*, repository_head: str) -> dict[str, object]:
        assert repository_head == HEAD
        raise admission.PublicationPathAdmissionError("publication-path-daemon-dns-unavailable")

    monkeypatch.setattr(
        managed_binding_execution,
        "verify_private_registry_publication_path",
        blocked,
    )

    with pytest.raises(
        admission.PublicationPathAdmissionError,
        match="publication-path-daemon-dns-unavailable",
    ):
        managed_binding_execution.materialize_ledger(ledger_path=ledger_path, repository_head=HEAD)
    assert not ledger_path.exists()
