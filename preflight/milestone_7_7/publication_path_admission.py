"""Fail-closed admission for the exact private ACR publication path."""

from __future__ import annotations

import hashlib
import ipaddress
import os
import re
import shutil
import socket
import ssl
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Final, NoReturn

from performance.milestone_7_7.framework import JsonValue

REGISTRY_HOST: Final = "acrmobius7711564669.azurecr.io"
REGISTRY_REPOSITORY: Final = "opencanvas-api"
EXPECTED_PRIVATE_SUBNET: Final = ipaddress.ip_network("10.77.2.0/24")
LINUX_PLATFORM: Final = "linux/amd64"
MAXIMUM_OUTPUT_BYTES: Final = 65_536
PROBE_TIMEOUT_SECONDS: Final = 30
HEX_SHA40: Final = re.compile(r"^[0-9a-f]{40}$")
SAFE_CONTEXT: Final = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
PROXY_VARIABLES: Final = (
    "ALL_PROXY",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "all_proxy",
    "http_proxy",
    "https_proxy",
    "no_proxy",
)
CONTAINER_NETWORK_PROBE: Final = """\
import ipaddress
import socket
import ssl
import sys

hostname = sys.argv[1]
expected = ipaddress.ip_network(sys.argv[2])
try:
    rows = socket.getaddrinfo(
        hostname, 443, family=socket.AF_INET, type=socket.SOCK_STREAM
    )
except socket.gaierror:
    print("dns-unavailable")
    raise SystemExit(41)
addresses = {ipaddress.ip_address(row[4][0]) for row in rows}
if not addresses or any(address not in expected for address in addresses):
    print("dns-not-private")
    raise SystemExit(42)
try:
    raw_socket = socket.create_connection((hostname, 443), timeout=5.0)
except OSError:
    print("route-unavailable")
    raise SystemExit(43)
try:
    with raw_socket, ssl.create_default_context().wrap_socket(
        raw_socket, server_hostname=hostname
    ) as tls_socket:
        if tls_socket.version() is None:
            raise ssl.SSLError("tls-unproved")
except ssl.SSLError:
    print("tls-failed")
    raise SystemExit(44)
print("proved")
"""


class PublicationPathAdmissionError(RuntimeError):
    """Sanitized fail-closed publication-path admission error."""

    def __init__(self, error_code: str) -> None:
        if re.fullmatch(r"[a-z0-9-]{1,96}", error_code) is None:
            error_code = "publication-path-admission-failed-closed"
        self.error_code = error_code
        super().__init__(error_code)


def _fail(error_code: str) -> NoReturn:
    raise PublicationPathAdmissionError(error_code)


def _decode_output(completed: subprocess.CompletedProcess[bytes]) -> str:
    raw = completed.stdout + b"\n" + completed.stderr
    if len(raw) > MAXIMUM_OUTPUT_BYTES:
        _fail("publication-path-probe-output-oversized")
    try:
        return raw.decode("utf-8", errors="strict").casefold()
    except UnicodeError:
        _fail("publication-path-probe-output-malformed")


def _classify_daemon_registry_result(
    completed: subprocess.CompletedProcess[bytes],
) -> str:
    """Accept only a reached-registry denial for the credential-free probe."""

    output = _decode_output(completed)
    if completed.returncode == 0:
        _fail("publication-path-probe-image-unexpectedly-readable")
    if any(
        marker in output
        for marker in (
            "no such host",
            "server misbehaving",
            "temporary failure in name resolution",
            "name resolution",
            "dns name not found",
        )
    ):
        _fail("publication-path-daemon-dns-unavailable")
    if any(
        marker in output
        for marker in (
            "x509:",
            "certificate signed by unknown authority",
            "certificate is not valid",
            "tls handshake",
        )
    ):
        _fail("publication-path-daemon-tls-failed")
    if any(
        marker in output
        for marker in (
            "no route to host",
            "network is unreachable",
            "connection refused",
            "connection reset",
            "i/o timeout",
            "context deadline exceeded",
            "request canceled while waiting for connection",
        )
    ):
        _fail("publication-path-daemon-route-failed")
    if any(
        marker in output
        for marker in (
            "unauthorized",
            "authentication required",
            "pull access denied",
            "requested access to the resource is denied",
            "manifest unknown",
        )
    ):
        return "registry-reached-without-credentials"
    if "failed to resolve reference" in output and ": not found" in output:
        return "registry-reached-without-credentials"
    _fail("publication-path-registry-response-unrecognized")


def _classify_container_network_result(
    completed: subprocess.CompletedProcess[bytes],
) -> None:
    output = _decode_output(completed).strip()
    if completed.returncode == 0 and output == "proved":
        return
    if completed.returncode == 41 and output == "dns-unavailable":
        _fail("publication-path-daemon-dns-unavailable")
    if completed.returncode == 42 and output == "dns-not-private":
        _fail("publication-path-daemon-resolved-publicly")
    if completed.returncode == 43 and output == "route-unavailable":
        _fail("publication-path-daemon-route-failed")
    if completed.returncode == 44 and output == "tls-failed":
        _fail("publication-path-daemon-tls-failed")
    _fail("publication-path-daemon-probe-result-malformed")


def _verify_host_private_tls(hostname: str) -> None:
    try:
        resolved = socket.getaddrinfo(
            hostname,
            443,
            family=socket.AF_INET,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror:
        _fail("publication-path-host-dns-unavailable")
    addresses = {
        str(item[4][0]) for item in resolved if isinstance(item[4], tuple) and item[4]
    }
    if not addresses:
        _fail("publication-path-host-dns-unavailable")
    try:
        parsed = tuple(ipaddress.ip_address(address) for address in addresses)
    except ValueError:
        _fail("publication-path-host-dns-malformed")
    if any(
        not isinstance(address, ipaddress.IPv4Address)
        or address not in EXPECTED_PRIVATE_SUBNET
        for address in parsed
    ):
        _fail("publication-path-host-resolved-publicly")
    try:
        with (
            socket.create_connection((hostname, 443), timeout=5.0) as raw_socket,
            ssl.create_default_context().wrap_socket(
                raw_socket, server_hostname=hostname
            ) as tls_socket,
        ):
            if tls_socket.version() is None:
                _fail("publication-path-host-tls-unproved")
    except (OSError, ssl.SSLError):
        _fail("publication-path-host-tls-unproved")


def _run(
    runner: Callable[..., subprocess.CompletedProcess[bytes]],
    argv: Sequence[str],
    *,
    environment: Mapping[str, str],
) -> subprocess.CompletedProcess[bytes]:
    try:
        completed = runner(
            tuple(argv),
            cwd=Path.cwd(),
            env=dict(environment),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            shell=False,
            timeout=PROBE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        _fail("publication-path-daemon-probe-timed-out")
    except OSError:
        _fail("publication-path-docker-launch-failed")
    if not isinstance(completed.stdout, bytes) or not isinstance(
        completed.stderr, bytes
    ):
        _fail("publication-path-probe-output-malformed")
    return completed


def verify_private_registry_publication_path(
    *,
    repository_head: str,
    runner: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run,
    host_probe: Callable[[str], None] = _verify_host_private_tls,
    base_environment: Mapping[str, str] | None = None,
) -> dict[str, JsonValue]:
    """Prove host and Docker-daemon reachability before a ledger can exist."""

    if HEX_SHA40.fullmatch(repository_head) is None:
        _fail("publication-path-repository-head-invalid")
    environment = dict(os.environ if base_environment is None else base_environment)
    if any(environment.get(name) for name in PROXY_VARIABLES):
        _fail("publication-path-proxy-environment-unapproved")
    docker = shutil.which("docker", path=environment.get("PATH"))
    if docker is None:
        _fail("publication-path-docker-executable-missing")
    if Path(docker).name.casefold() not in {"docker", "docker.exe"}:
        _fail("publication-path-docker-executable-missing")

    host_probe(REGISTRY_HOST)
    source_reference = f"{REGISTRY_HOST}/{REGISTRY_REPOSITORY}:source-{repository_head}"
    reference = (
        f"{REGISTRY_HOST}/{REGISTRY_REPOSITORY}:"
        f"mobius77-publication-path-probe-{repository_head}"
    )
    with tempfile.TemporaryDirectory(
        prefix="mobius77-publication-path-admission-"
    ) as raw_config:
        docker_config = Path(raw_config).resolve()
        try:
            os.chmod(docker_config, 0o700)
        except OSError:
            _fail("publication-path-docker-config-permissions-failed")
        probe_environment = {**environment, "DOCKER_CONFIG": str(docker_config)}

        context_result = _run(
            runner, (docker, "context", "show"), environment=probe_environment
        )
        if context_result.returncode != 0:
            _fail("publication-path-docker-context-unavailable")
        try:
            context = context_result.stdout.decode("utf-8", errors="strict").strip()
        except UnicodeError:
            _fail("publication-path-docker-context-malformed")
        if SAFE_CONTEXT.fullmatch(context) is None:
            _fail("publication-path-docker-context-malformed")

        daemon_result = _run(
            runner,
            (docker, "version", "--format", "{{.Server.Os}}"),
            environment=probe_environment,
        )
        if daemon_result.returncode != 0:
            _fail("publication-path-docker-daemon-unavailable")
        try:
            daemon_os = daemon_result.stdout.decode("ascii", errors="strict").strip()
        except UnicodeError:
            _fail("publication-path-docker-daemon-malformed")
        if daemon_os != "linux":
            _fail("publication-path-docker-daemon-unapproved")

        source_image = _run(
            runner,
            (docker, "image", "inspect", source_reference),
            environment=probe_environment,
        )
        if source_image.returncode != 0:
            _fail("publication-path-prebuilt-image-unavailable")
        container_name = f"mobius77-publication-path-{repository_head[:12]}"
        container_before = _run(
            runner,
            (docker, "container", "inspect", container_name),
            environment=probe_environment,
        )
        if container_before.returncode == 0:
            _fail("publication-path-probe-container-collision")
        container_result: subprocess.CompletedProcess[bytes] | None = None
        container_error: BaseException | None = None
        try:
            container_result = _run(
                runner,
                (
                    docker,
                    "run",
                    "--name",
                    container_name,
                    "--rm",
                    "--pull",
                    "never",
                    "--network",
                    "bridge",
                    "--read-only",
                    "--cap-drop",
                    "ALL",
                    "--security-opt",
                    "no-new-privileges",
                    source_reference,
                    "python",
                    "-c",
                    CONTAINER_NETWORK_PROBE,
                    REGISTRY_HOST,
                    str(EXPECTED_PRIVATE_SUBNET),
                ),
                environment=probe_environment,
            )
        except BaseException as error:
            container_error = error
        container_after = _run(
            runner,
            (docker, "container", "inspect", container_name),
            environment=probe_environment,
        )
        if container_after.returncode == 0:
            cleanup_result = _run(
                runner,
                (docker, "container", "rm", "--force", container_name),
                environment=probe_environment,
            )
            if cleanup_result.returncode != 0:
                _fail("publication-path-probe-container-cleanup-failed")
            if container_error is None:
                _fail("publication-path-probe-container-residue")
        if container_error is not None:
            raise container_error
        if container_result is None:
            _fail("publication-path-daemon-probe-result-malformed")
        _classify_container_network_result(container_result)

        inspect_before = _run(
            runner,
            (docker, "image", "inspect", reference),
            environment=probe_environment,
        )
        if inspect_before.returncode == 0:
            _fail("publication-path-probe-local-image-collision")
        pull_result = _run(
            runner,
            (docker, "pull", "--platform", LINUX_PLATFORM, reference),
            environment=probe_environment,
        )
        if pull_result.returncode == 0:
            cleanup_result = _run(
                runner,
                (docker, "image", "rm", "--force", reference),
                environment=probe_environment,
            )
            if cleanup_result.returncode != 0:
                _fail("publication-path-probe-local-cleanup-failed")
            _fail("publication-path-probe-image-unexpectedly-readable")
        outcome = _classify_daemon_registry_result(pull_result)
        inspect_after = _run(
            runner,
            (docker, "image", "inspect", reference),
            environment=probe_environment,
        )
        if inspect_after.returncode == 0:
            _fail("publication-path-probe-created-local-image")

    return {
        "credentialsUsed": False,
        "dockerContext": context,
        "dockerDaemonOs": daemon_os,
        "dockerNetworkPathProved": True,
        "dockerPrivateDnsAndTlsProved": True,
        "hostPrivateDnsAndTlsProved": True,
        "mutationPerformed": False,
        "probeOutcome": outcome,
        "registryHostSha256": hashlib.sha256(REGISTRY_HOST.encode("ascii")).hexdigest(),
        "repository": REGISTRY_REPOSITORY,
        "status": "proved",
    }
