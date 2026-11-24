"""Prepare private Blob probe transport locally; no cloud access or proof execution."""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[3]
MODULES = (
    "infra.milestone_7_8.pilot_validation",
    "infra.milestone_7_8.pilot_application_probe",
    "infra.milestone_7_8.password_reset_validation",
    "infra.milestone_7_8.activity_delivery_validation",
    "infra.milestone_7_8.queue_grant_intervention",
)
SOURCE_VERIFIER = 'import hashlib,os; s=os.environ["M78_EXECUTION_SOURCE"]; assert hashlib.sha256(s.encode()).hexdigest()==os.environ["M78_EXECUTION_SHA256"],"source binding mismatch"; exec(compile(s,"<bound-pilot-artifact-transport>","exec"))'


def archive(entries: dict[str, bytes], *, compressed: bool = False) -> bytes:
    # One lossless dictionary spans reviewed source files. The final wheel
    # artifact remains the exact original stored ZIP and retains its own hash.
    if compressed:
        entries = {"source-entries.zip": archive(entries)}
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w") as output:
        for name, data in sorted(entries.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            # Match the Linux Container Apps runtime ZIP platform metadata.
            info.create_system = 3
            info.compress_type = (
                zipfile.ZIP_LZMA if compressed else zipfile.ZIP_STORED
            )
            output.writestr(info, data)
    return target.getvalue()


def private_path(path: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(ROOT / ".runtime"):
        raise ValueError(
            "execution transport must stay in ignored private runtime storage"
        )
    return resolved


def pack(
    bundle: Path,
    authorization: Path,
    bindings: Path,
    module: str,
    arguments: list[str],
    output: Path,
    wheel_manifest: Path,
    wheel_directory: Path,
    private_inputs: dict[str, str] | None = None,
) -> dict:
    if module not in MODULES:
        raise ValueError("unsupported proof module")
    output = private_path(output)
    manifest = json.loads((bundle / "manifest.json").read_text())
    if "consolidatedScope" in manifest:
        from infra.milestone_7_8.pilot.consolidated import guard_dispatch

        guard_dispatch(bundle, arguments, private_inputs or {})
    entries: dict[str, bytes] = {}
    for relative, expected in manifest["sourceBindings"].items():
        path = (ROOT / relative).resolve()
        if not path.is_relative_to(ROOT) or path.is_relative_to(ROOT / ".runtime"):
            raise ValueError("bound source is outside repository inputs")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError("source changed after package preparation")
        entries[relative] = data
    required = {
        "infra/milestone_7_8/pilot_validation.py",
        "infra/milestone_7_8/pilot_alerts.py",
        "infra/milestone_7_8/pilot_application_probe.py",
        "infra/milestone_7_8/pilot/probe-requirements.txt",
    }
    if not required.issubset(entries):
        raise ValueError("package must bind all probe implementations and SDK lock")
    entries.update({"infra/__init__.py": b"", "infra/milestone_7_8/__init__.py": b""})
    for name in ("manifest.json", "catalog.json"):
        entries[f"package/{name}"] = (bundle / name).read_bytes()
    entries["approval.json"] = private_path(authorization).read_bytes()
    entries["bindings.json"] = private_path(bindings).read_bytes()
    for target, source_path in (private_inputs or {}).items():
        if Path(target).name != target or target in {
            "approval.json",
            "bindings.json",
            "manifest.json",
        }:
            raise ValueError("private input must have a distinct simple basename")
        data = private_path(Path(source_path)).read_bytes()
        if len(data) > 250_000:
            raise ValueError("private input exceeds reviewed bound")
        entries[target] = data
    wheels = json.loads(wheel_manifest.read_text())["wheels"]
    if len(wheels) != 8:
        raise ValueError("exact eight-wheel lock required")
    lock = entries["infra/milestone_7_8/pilot/probe-requirements.txt"].decode()
    entries["wheel-manifest.json"] = json.dumps(
        {"wheels": wheels}, sort_keys=True
    ).encode()
    source = archive(entries, compressed=True)
    for wheel in wheels:
        name = wheel["name"]
        if Path(name).name != name or not name.endswith("-py3-none-any.whl"):
            raise ValueError("only exact pure Python wheels are permitted")
        data = (wheel_directory / name).read_bytes()
        if (
            hashlib.sha256(data).hexdigest() != wheel["sha256"]
            or len(data) != wheel["size"]
            or wheel["sha256"] not in lock
        ):
            raise ValueError("wheel does not match source-bound lock")
        entries[f"wheels/{name}"] = data
    raw = archive(entries)
    archive_hash = hashlib.sha256(raw).hexdigest()
    encoded_source = base64.b64encode(source).decode()
    if len(encoded_source) > 240_000 or len(raw) > 2_000_000:
        raise ValueError(
            "prepared source or private Blob artifact exceeds reviewed transport bounds"
        )
    program = (Path(__file__).parent / "artifact_transport.py").read_text()
    loader = program + "\nload_probe()\n"
    staging = program + "\nstage_artifact()\n"

    def bound_environment(source_text: str) -> list[dict[str, str]]:
        return [
            {"name": "M78_EXECUTION_SOURCE", "value": source_text},
            {
                "name": "M78_EXECUTION_SHA256",
                "value": hashlib.sha256(source_text.encode()).hexdigest(),
            },
        ]

    result = {
        "artifactSha256": archive_hash,
        "artifactName": archive_hash + ".zip",
        "artifactBytes": len(raw),
        "artifactStagingCommand": ["python", "-c", SOURCE_VERIFIER],
        "artifactStagingEnvironment": bound_environment(staging)
        + [
            {
                "name": "M78_PILOT_SOURCE_CHUNKS",
                "value": str((len(encoded_source) + 32767) // 32768),
            }
        ]
        + [
            {
                "name": f"M78_PILOT_SOURCE_CHUNK_{i // 32768}",
                "value": encoded_source[i : i + 32768],
            }
            for i in range(0, len(encoded_source), 32768)
        ]
        + [
            {
                "name": "M78_PILOT_SOURCE_ZIP_SHA256",
                "value": hashlib.sha256(source).hexdigest(),
            },
            {"name": "M78_PILOT_ARTIFACT_SHA256", "value": archive_hash},
        ],
        "proofCommand": ["python", "-c", SOURCE_VERIFIER],
        "proofEnvironment": bound_environment(loader)
        + [
            {"name": "M78_PILOT_ARTIFACT_SHA256", "value": archive_hash},
            {"name": "M78_PILOT_MODULE", "value": module},
            {"name": "M78_PILOT_ARGUMENTS_JSON", "value": json.dumps(arguments)},
        ],
        "requiredRuntimeBinding": "M78_PILOT_ARTIFACT_VERSION_ID from verified staging receipt",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle)
    output.with_suffix(".zip").write_bytes(raw)
    return {
        "artifactSha256": archive_hash,
        "artifactBytes": len(raw),
        "sourceEnvironmentBytes": len(encoded_source),
        "files": len(entries),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "bundle",
        "authorization",
        "bindings",
        "output",
        "wheel-manifest",
        "wheel-directory",
    ):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--module", choices=MODULES, required=True)
    parser.add_argument("--arguments-json", required=True)
    parser.add_argument("--private-inputs-json", default="{}")
    args = parser.parse_args()
    arguments = json.loads(args.arguments_json)
    if not isinstance(arguments, list) or not all(
        isinstance(item, str) for item in arguments
    ):
        parser.error("arguments-json must contain a string array")
    print(
        json.dumps(
            pack(
                args.bundle,
                args.authorization,
                args.bindings,
                args.module,
                arguments,
                args.output,
                args.wheel_manifest,
                args.wheel_directory,
                json.loads(args.private_inputs_json),
            ),
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
