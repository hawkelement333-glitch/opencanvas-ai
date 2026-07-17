"""Fail release validation when repository-source hygiene regresses."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_DIRECTORIES = {
    ".cache",
    ".idea",
    ".mypy_cache",
    ".next",
    ".pytest_cache",
    ".ruff_cache",
    ".runtime",
    ".venv",
    ".vscode",
    "__pycache__",
    "build",
    "coverage",
    "data",
    "dist",
    "logs",
    "node_modules",
    "out",
    "playwright-report",
    "temp",
    "test-results",
    "tmp",
    "uploads",
}
FORBIDDEN_SUFFIXES = {
    ".db",
    ".cer",
    ".crt",
    ".der",
    ".jks",
    ".key",
    ".keystore",
    ".log",
    ".p12",
    ".pem",
    ".pfx",
    ".sqlite",
    ".sqlite3",
}
FORBIDDEN_NAMES = {
    "credentials.json",
    "id_ed25519",
    "id_rsa",
    "service-account.json",
}
ALLOWED_ENV_FILES = {".env.example", ".env.demo.example"}
REQUIRED_RELEASE_FILES = {
    ".env.example",
    ".github/workflows/ci.yml",
    "BUILD_WEEK_CHECKLIST.md",
    "CHANGELOG.md",
    "CODE_OF_CONDUCT.md",
    "CONTRIBUTING.md",
    "COPYRIGHT",
    "LICENSE_RECOMMENDATION.md",
    "NOTICE",
    "README.md",
    "RELEASE_CHECKLIST.md",
    "SECURITY.md",
    "THIRD_PARTY_NOTICES.md",
    "docs/ARCHITECTURE.md",
    "docs/BUILD_WEEK.md",
    "docs/DEMO_GUIDE.md",
    "docs/JUDGE_SETUP.md",
    "docs/KNOWN_LIMITATIONS.md",
    "docs/SECURITY_MODEL.md",
    "docs/TRACE.md",
}
SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("OpenAI-style API key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("GitHub access token", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{30,}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b")),
    ("private key block", re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----")),
)


def source_files() -> list[Path]:
    """Return tracked and non-ignored untracked files, including a pre-first-commit worktree."""
    completed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        message = completed.stderr.decode(errors="replace").strip()
        raise RuntimeError(f"git file inventory failed: {message}")
    return [
        REPOSITORY_ROOT / item.decode(errors="surrogateescape")
        for item in completed.stdout.split(b"\0")
        if item
    ]


def path_violations(paths: list[Path]) -> list[str]:
    violations: list[str] = []
    for path in paths:
        relative = path.relative_to(REPOSITORY_ROOT)
        normalized_parts = {part.lower() for part in relative.parts[:-1]}
        forbidden_parts = normalized_parts & FORBIDDEN_DIRECTORIES
        if forbidden_parts:
            violations.append(
                f"generated/private directory is included: {relative.as_posix()} "
                f"({', '.join(sorted(forbidden_parts))})"
            )
        lower_name = relative.name.lower()
        if lower_name.startswith(".env") and lower_name not in ALLOWED_ENV_FILES:
            violations.append(f"environment file is included: {relative.as_posix()}")
        if lower_name in FORBIDDEN_NAMES:
            violations.append(f"credential-like file is included: {relative.as_posix()}")
        if relative.suffix.lower() in FORBIDDEN_SUFFIXES:
            violations.append(f"private/generated file is included: {relative.as_posix()}")
    return violations


def secret_violations(paths: list[Path]) -> list[str]:
    violations: list[str] = []
    for path in paths:
        if not path.is_file() or path.stat().st_size > 2_000_000:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        relative = path.relative_to(REPOSITORY_ROOT).as_posix()
        for label, pattern in SECRET_PATTERNS:
            if pattern.search(content):
                violations.append(f"{label} pattern detected in {relative}")
    return violations


def configuration_violations() -> list[str]:
    violations: list[str] = []
    env_example = REPOSITORY_ROOT / ".env.example"
    if env_example.is_file():
        for line in env_example.read_text(encoding="utf-8").splitlines():
            if line.startswith("OPENAI_API_KEY=") and line != "OPENAI_API_KEY=":
                violations.append(".env.example must leave OPENAI_API_KEY empty")
    else:
        violations.append(".env.example is missing")

    for relative in sorted(REQUIRED_RELEASE_FILES):
        if not (REPOSITORY_ROOT / relative).is_file():
            violations.append(f"required release file is missing: {relative}")
    return violations


def main() -> int:
    try:
        paths = source_files()
    except RuntimeError as exc:
        print(f"Repository hygiene check failed: {exc}", file=sys.stderr)
        return 1

    violations = [
        *path_violations(paths),
        *secret_violations(paths),
        *configuration_violations(),
    ]
    if violations:
        print("Repository hygiene check failed:", file=sys.stderr)
        for violation in sorted(set(violations)):
            print(f"- {violation}", file=sys.stderr)
        return 1

    print(f"Repository hygiene check passed for {len(paths)} source files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
