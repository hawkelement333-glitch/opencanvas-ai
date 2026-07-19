from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from collections.abc import Mapping
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = API_ROOT.parents[1]
sys.path.insert(0, str(API_ROOT))

from opencanvas_api.core.config import (  # noqa: E402
    DEMO_DATABASE_PATH,
    DEMO_DATABASE_URL,
    DEMO_DOCUMENT_STORAGE_ROOT,
    DEMO_RUNTIME_ROOT,
    Settings,
)
from opencanvas_api.db.session import Database  # noqa: E402
from opencanvas_api.services.demo import seed_demo, validate_demo_seed  # noqa: E402


def build_demo_environment(source: Mapping[str, str] | None = None) -> dict[str, str]:
    environment = dict(source or os.environ)
    environment.update(
        {
            "OPENCANVAS_ENVIRONMENT": "development",
            "OPENCANVAS_DEMO_MODE": "true",
            "OPENCANVAS_DATABASE_URL": DEMO_DATABASE_URL,
            "OPENCANVAS_AI_PROVIDER": "mock",
            "OPENCANVAS_EMBEDDING_PROVIDER": "mock",
            "OPENCANVAS_DOCUMENT_STORAGE_ROOT": str(DEMO_DOCUMENT_STORAGE_ROOT),
            "NEXT_PUBLIC_API_URL": "http://localhost:8000/api/v1",
            "OPENAI_API_KEY": "",
            "OPENCANVAS_OPENAI_API_KEY": "",
        }
    )
    return environment


def validate_demo_environment(environment: Mapping[str, str]) -> Settings:
    expected = build_demo_environment({})
    protected_keys = (
        "OPENCANVAS_ENVIRONMENT",
        "OPENCANVAS_DEMO_MODE",
        "OPENCANVAS_DATABASE_URL",
        "OPENCANVAS_AI_PROVIDER",
        "OPENCANVAS_EMBEDDING_PROVIDER",
        "OPENCANVAS_DOCUMENT_STORAGE_ROOT",
    )
    if any(environment.get(key) != expected[key] for key in protected_keys):
        raise RuntimeError("The demo environment does not match the isolated startup contract.")
    if environment.get("OPENAI_API_KEY") or environment.get("OPENCANVAS_OPENAI_API_KEY"):
        raise RuntimeError("The demo environment must not contain OpenAI credentials.")
    settings = Settings(
        environment="development",
        demo_mode=True,
        database_url=DEMO_DATABASE_URL,
        ai_provider="mock",
        embedding_provider="mock",
        document_storage_root=DEMO_DOCUMENT_STORAGE_ROOT,
        openai_api_key=None,
    )
    if not settings.demo_mode:
        raise RuntimeError("The demo environment did not enable demo mode.")
    return settings


def _migrate(environment: Mapping[str, str]) -> None:
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=API_ROOT,
        env=dict(environment),
        check=True,
    )


async def _seed(environment: Mapping[str, str]) -> None:
    settings = validate_demo_environment(environment)
    database = Database(settings.database_url)
    try:
        async with database.sessions() as session:
            result = await seed_demo(session, settings.document_storage_root)
            await validate_demo_seed(session, settings.document_storage_root)
    finally:
        await database.dispose()
    action = "created" if result.created else "already present"
    print(f"Demo workspace {action}: {result.canvas_id}")
    print(f"Replay Trace: http://localhost:8000/api/v1/traces/{result.trace_id}")


def _reset_runtime() -> None:
    target = DEMO_RUNTIME_ROOT.resolve()
    validate_reset_target(target, PROJECT_ROOT)
    if target.exists():
        shutil.rmtree(target)


def validate_reset_target(target: Path, project_root: Path) -> None:
    expected = (project_root / ".runtime" / "demo").resolve()
    if target.resolve() != expected or target.resolve() == project_root.resolve():
        raise RuntimeError("Refusing to reset an unexpected demo runtime path.")


def _prepare(environment: Mapping[str, str], *, reset: bool = False) -> None:
    validate_demo_environment(environment)
    if reset:
        _reset_runtime()
    DEMO_RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    _migrate(environment)
    asyncio.run(_seed(environment))


def _spawn_services(
    environment: Mapping[str, str],
) -> tuple[subprocess.Popen[bytes], subprocess.Popen[bytes]]:
    corepack = shutil.which("corepack")
    if corepack is None:
        raise RuntimeError("Corepack is required to run the repository-pinned pnpm version.")
    api = _spawn_process(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "opencanvas_api.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
        ],
        cwd=API_ROOT,
        environment=environment,
    )
    web = _spawn_process(
        build_web_command(corepack),
        cwd=PROJECT_ROOT,
        environment=environment,
    )
    return api, web


def _spawn_process(
    command: list[str], *, cwd: Path, environment: Mapping[str, str]
) -> subprocess.Popen[bytes]:
    if os.name == "nt":
        return subprocess.Popen(
            command,
            cwd=cwd,
            env=dict(environment),
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
    return subprocess.Popen(
        command,
        cwd=cwd,
        env=dict(environment),
        start_new_session=True,
    )


def build_web_command(corepack: str) -> list[str]:
    return [corepack, "pnpm", "--filter", "@opencanvas/web", "dev"]


def _start(environment: Mapping[str, str]) -> int:
    _prepare(environment)
    api, web = _spawn_services(environment)
    print("SolarPlexus Mobius Build Week demo: http://localhost:3000")
    print("Mode: deterministic replay fixture + local mock AI; no external AI calls")
    try:
        while api.poll() is None and web.poll() is None:
            api.wait(timeout=0.5)
    except subprocess.TimeoutExpired:
        return _start_wait(api, web)
    except KeyboardInterrupt:
        pass
    finally:
        _stop(api)
        _stop(web)
    return api.returncode or web.returncode or 0


def _smoke(environment: Mapping[str, str]) -> int:
    _prepare(environment, reset=True)
    api, web = _spawn_services(environment)
    try:
        _wait_for_url("http://127.0.0.1:8000/api/v1/health/ready")
        runtime = _wait_for_url("http://127.0.0.1:8000/api/v1/health/runtime")
        payload = json.loads(runtime)
        if payload.get("mode") != "deterministic_replay":
            raise RuntimeError("Demo smoke test reached an API that is not in replay mode.")
        if payload.get("externalAiEnabled") is not False:
            raise RuntimeError("Demo smoke test found external AI enabled.")
        page = _wait_for_url("http://127.0.0.1:3000")
        if "SolarPlexus Mobius" not in page:
            raise RuntimeError(
                "Demo web page did not contain the SolarPlexus Mobius application shell."
            )
        print("Demo startup smoke test passed: API, replay runtime, and web page are ready.")
        return 0
    finally:
        _stop(api)
        _stop(web)


def _wait_for_url(url: str, timeout_seconds: float = 90.0) -> str:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return response.read().decode("utf-8")
        except Exception as exc:
            last_error = exc
        time.sleep(0.5)
    raise RuntimeError(f"Timed out waiting for {url}: {last_error}")


def _start_wait(api: subprocess.Popen[bytes], web: subprocess.Popen[bytes]) -> int:
    try:
        while api.poll() is None and web.poll() is None:
            try:
                api.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                continue
    except KeyboardInterrupt:
        return 0
    return api.returncode or web.returncode or 0


def _stop(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            process.kill()
        else:
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)


def main() -> int:
    parser = argparse.ArgumentParser(description="Safe SolarPlexus Mobius Build Week demo runner")
    parser.add_argument("command", choices=("start", "seed", "reset", "check", "smoke"))
    args = parser.parse_args()
    environment = build_demo_environment()
    validate_demo_environment(environment)

    if args.command == "check":
        _prepare(environment)
        print(f"Demo isolation and persisted-provenance checks passed: {DEMO_DATABASE_PATH}")
        return 0
    if args.command == "smoke":
        return _smoke(environment)
    if args.command == "start":
        return _start(environment)
    _prepare(environment, reset=args.command == "reset")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
