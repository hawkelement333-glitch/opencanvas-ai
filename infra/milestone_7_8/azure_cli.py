from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[2]
AZURE_CLI_TOKEN: Final = "az"
WINDOWS_NATIVE_NAME: Final = "az.exe"
WINDOWS_BATCH_NAMES: Final = ("az.cmd", "az.bat")
POSIX_NATIVE_NAME: Final = "az"
WINDOWS_COMMAND_PROCESSOR_NAME: Final = "cmd.exe"
DEFAULT_TIMEOUT_SECONDS: Final = 900
SAFE_VERSION_PATTERN: Final = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.+_-]{0,63}$")

LauncherKind = Literal["native", "batch"]


class AzureCliError(RuntimeError):
    pass


class AzureCliResolutionError(AzureCliError):
    pass


def _is_within(candidate: Path, root: Path) -> bool:
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def _canonical_file(path: str | Path) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        raise AzureCliResolutionError("Azure CLI launcher path is not absolute")
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise AzureCliResolutionError("Azure CLI launcher path does not exist") from exc
    if not resolved.is_file():
        raise AzureCliResolutionError("Azure CLI launcher path is not a file")
    return resolved


def _validate_launcher_location(
    launcher: Path,
    *,
    repository_root: Path,
    working_directory: Path,
) -> None:
    forbidden_roots = {
        repository_root.resolve(strict=True),
        working_directory.resolve(strict=True),
        (repository_root / ".runtime").resolve(strict=False),
    }
    if any(_is_within(launcher, root) for root in forbidden_roots):
        raise AzureCliResolutionError(
            "Azure CLI launcher is inside a repository or campaign-controlled directory"
        )
    if any(part.casefold() in {".runtime", ".git"} for part in launcher.parts):
        raise AzureCliResolutionError("Azure CLI launcher is inside a campaign-controlled path")


def _windows_system_directory() -> Path:
    if os.name != "nt":
        raise AzureCliResolutionError("Windows command processor is unavailable on this platform")
    buffer = ctypes.create_unicode_buffer(32768)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_system_directory = kernel32.GetSystemDirectoryW
    get_system_directory.argtypes = [ctypes.c_wchar_p, ctypes.c_uint]
    get_system_directory.restype = ctypes.c_uint
    length = int(get_system_directory(buffer, len(buffer)))
    if length <= 0 or length >= len(buffer):
        raise AzureCliResolutionError("trusted Windows system directory could not be resolved")
    try:
        return Path(buffer.value).resolve(strict=True)
    except OSError as exc:
        raise AzureCliResolutionError("trusted Windows system directory is unavailable") from exc


def _trusted_windows_command_processor() -> Path:
    system_directory = _windows_system_directory()
    command_processor = _canonical_file(system_directory / WINDOWS_COMMAND_PROCESSOR_NAME)
    if (
        command_processor.name.casefold() != WINDOWS_COMMAND_PROCESSOR_NAME
        or command_processor.parent != system_directory
    ):
        raise AzureCliResolutionError("Windows command processor binding is not trusted")
    return command_processor


def _validate_argument(value: str) -> None:
    if "\x00" in value or "\r" in value or "\n" in value:
        raise AzureCliError("Azure CLI argument contains a forbidden control character")


def _windows_environment_argument(value: str) -> str:
    escaped: list[str] = []
    backslashes = 0
    for character in value:
        if character == "\\":
            backslashes += 1
            continue
        if character == '"':
            escaped.append("\\" * (backslashes * 2))
            escaped.append('""')
            backslashes = 0
            continue
        escaped.append("\\" * backslashes)
        backslashes = 0
        escaped.append(character)
    escaped.append("\\" * (backslashes * 2))
    return "".join(escaped)


def _windows_batch_command(
    command_processor: Path,
    launcher: Path,
    arguments: Sequence[str],
    environment: dict[str, str],
) -> str:
    prefix = f"M78_AZURE_CLI_{os.getpid()}_{secrets.token_hex(8).upper()}"
    launcher_name = f"{prefix}_LAUNCHER"
    bindings = {launcher_name: str(launcher)}
    references: list[str] = []
    for index, argument in enumerate(arguments):
        if argument == "":
            references.append('""')
            continue
        name = f"{prefix}_ARG_{index:04d}"
        bindings[name] = _windows_environment_argument(argument)
        references.append(f'"%{name}%"')
    if set(bindings) & set(environment):
        raise AzureCliError("temporary Azure CLI argument binding collided")
    environment.update(bindings)
    clears = "& ".join(f"set {name}=" for name in bindings)
    invocation = f'{clears}& "%{launcher_name}%"'
    if references:
        invocation += " " + " ".join(references)
    return f'"{command_processor}" /d /s /v:off /c "{invocation}"'


@dataclass(frozen=True, slots=True)
class AzureCliLauncher:
    path: Path
    kind: LauncherKind
    command_processor: Path | None = None

    @classmethod
    def resolve(
        cls,
        *,
        repository_root: Path = REPOSITORY_ROOT,
        working_directory: Path | None = None,
        search_path: str | None = None,
        platform: Literal["windows", "posix"] | None = None,
    ) -> AzureCliLauncher:
        effective_platform = platform or ("windows" if os.name == "nt" else "posix")
        cwd = (working_directory or Path.cwd()).resolve(strict=True)
        root = repository_root.resolve(strict=True)
        path_value = os.environ.get("PATH", "") if search_path is None else search_path
        forms = (
            (
                (WINDOWS_NATIVE_NAME, "native"),
                *((name, "batch") for name in WINDOWS_BATCH_NAMES),
            )
            if effective_platform == "windows"
            else ((POSIX_NATIVE_NAME, "native"),)
        )
        checked: list[str] = []
        for name, kind in forms:
            checked.append(name)
            discovered = shutil.which(name, path=path_value)
            if discovered is None:
                continue
            launcher = _canonical_file(discovered)
            _validate_launcher_location(
                launcher,
                repository_root=root,
                working_directory=cwd,
            )
            normalized_name = launcher.name.casefold()
            if kind == "native":
                expected_name = (
                    WINDOWS_NATIVE_NAME if effective_platform == "windows" else POSIX_NATIVE_NAME
                )
                if normalized_name != expected_name:
                    raise AzureCliResolutionError("Azure CLI native launcher name is invalid")
                if effective_platform == "posix" and not os.access(launcher, os.X_OK):
                    raise AzureCliResolutionError("Azure CLI native launcher is not executable")
                return cls(path=launcher, kind="native")
            if normalized_name not in WINDOWS_BATCH_NAMES:
                raise AzureCliResolutionError("Azure CLI batch launcher name is invalid")
            return cls(
                path=launcher,
                kind="batch",
                command_processor=_trusted_windows_command_processor(),
            )
        raise AzureCliResolutionError(
            "trusted Azure CLI launcher unavailable; checked launcher forms: " + ", ".join(checked)
        )

    def run(
        self,
        arguments: Sequence[str],
        *,
        timeout: int | float = DEFAULT_TIMEOUT_SECONDS,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        encoding: str = "utf-8",
    ) -> subprocess.CompletedProcess[str]:
        normalized_arguments = tuple(str(argument) for argument in arguments)
        for argument in normalized_arguments:
            _validate_argument(argument)
        process_environment = None if env is None else dict(env)
        if self.kind == "native":
            command: str | tuple[str, ...] = (str(self.path), *normalized_arguments)
        else:
            if self.command_processor is None:
                raise AzureCliResolutionError(
                    "trusted Windows command processor binding is missing"
                )
            process_environment = (
                os.environ.copy() if process_environment is None else process_environment
            )
            command = _windows_batch_command(
                self.command_processor,
                self.path,
                normalized_arguments,
                process_environment,
            )
        return subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding=encoding,
            errors="strict",
            timeout=timeout,
            cwd=cwd,
            env=process_environment,
            shell=False,
        )


def local_version_smoke() -> dict[str, str]:
    launcher = AzureCliLauncher.resolve()
    completed = launcher.run(("version", "--output", "json"), timeout=60)
    if completed.returncode != 0:
        raise AzureCliError("local Azure CLI version smoke failed")
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise AzureCliError("local Azure CLI version output is not valid JSON") from exc
    version = value.get("azure-cli") if isinstance(value, dict) else None
    if not isinstance(version, str) or SAFE_VERSION_PATTERN.fullmatch(version) is None:
        raise AzureCliError("local Azure CLI version is malformed")
    return {
        "status": "passed",
        "launcherType": launcher.kind,
        "azureCliVersion": version,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve the trusted local Azure CLI launcher")
    parser.add_argument("operation", choices=("version", "invoke"))
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    try:
        if args.operation == "version":
            if args.arguments:
                raise AzureCliError("local Azure CLI version smoke accepts no arguments")
            print(json.dumps(local_version_smoke(), separators=(",", ":"), sort_keys=True))
            return 0
        arguments = tuple(args.arguments)
        if arguments[:1] == ("--",):
            arguments = arguments[1:]
        if not arguments:
            raise AzureCliError("Azure CLI invocation requires arguments")
        completed = AzureCliLauncher.resolve().run(arguments)
        sys.stdout.write(completed.stdout)
        sys.stderr.write(completed.stderr)
        return completed.returncode
    except AzureCliError as exc:
        print(
            json.dumps({"status": "blocked", "error": str(exc)}, sort_keys=True),
            file=sys.stderr,
        )
        return 2
    except (OSError, subprocess.SubprocessError, UnicodeError):
        print(
            json.dumps(
                {"status": "blocked", "error": "Azure CLI process failed safely"},
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
