"""Reproduce installation and validation from a source-only temporary worktree."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def source_files() -> list[Path]:
    completed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
    )
    return [
        REPOSITORY_ROOT / item.decode(errors="surrogateescape")
        for item in completed.stdout.split(b"\0")
        if item
    ]


def run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> None:
    print(f"+ {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=cwd, env=env, check=True)


def venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def remove_temporary_tree(path: Path, *, attempts: int = 8) -> None:
    """Remove build output after transient Windows file handles have settled."""

    cleanup_path = Path(f"\\\\?\\{path.resolve()}") if os.name == "nt" else path
    for attempt in range(attempts):
        error: OSError | None = None
        try:
            shutil.rmtree(cleanup_path)
        except OSError as exc:
            error = exc

        if not path.exists():
            time.sleep(0.25)
            if not path.exists():
                return

        if attempt == attempts - 1:
            if error is not None:
                raise error
            raise OSError(f"Temporary checkout was recreated during cleanup: {path}")
        time.sleep(0.25 * (attempt + 1))


def main() -> int:
    corepack = shutil.which("corepack")
    git = shutil.which("git")
    if corepack is None or git is None:
        print("Clean-clone validation requires git and Corepack on PATH.", file=sys.stderr)
        return 1

    files = source_files()
    temporary = Path(tempfile.mkdtemp(prefix="opencanvas-clean-clone-"))
    validation_succeeded = False
    try:
        checkout = temporary / "opencanvas-ai"
        checkout.mkdir()
        for source in files:
            relative = source.relative_to(REPOSITORY_ROOT)
            destination = checkout / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)

        print(f"Clean source checkout: {checkout}", flush=True)
        run([git, "init", "--quiet"], cwd=checkout)
        run([corepack, "pnpm", "install", "--frozen-lockfile"], cwd=checkout)
        run(
            [
                corepack,
                "pnpm",
                "--filter",
                "@opencanvas/web",
                "exec",
                "playwright",
                "install",
                "chromium",
            ],
            cwd=checkout,
        )

        venv = checkout / ".venv"
        run([sys.executable, "-m", "venv", str(venv)], cwd=checkout)
        python = venv_python(venv)
        run([str(python), "-m", "pip", "install", "-e", "apps/api[dev]"], cwd=checkout)

        environment = os.environ.copy()
        environment["CI"] = "true"
        environment["PATH"] = f"{python.parent}{os.pathsep}{environment.get('PATH', '')}"
        run([corepack, "pnpm", "validate"], cwd=checkout, env=environment)
        validation_succeeded = True
    finally:
        try:
            remove_temporary_tree(temporary)
        except OSError as exc:
            if validation_succeeded:
                raise
            print(f"Warning: could not remove failed clean-clone checkout: {exc}", file=sys.stderr)

    print("Clean-clone reproduction passed; temporary files were removed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
