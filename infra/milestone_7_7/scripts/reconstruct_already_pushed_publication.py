"""Pure local reconstruction of already-pushed evidence; never contacts Azure."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from performance.milestone_7_7.framework import JsonValue, canonical_bytes, load_json
from preflight.milestone_7_7.managed_binding_contracts import REPOSITORY_ROOT

from infra.milestone_7_7 import api_image_publication as publication


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    historical = parser.add_mutually_exclusive_group(required=True)
    historical.add_argument("--historical-push-evidence", type=Path)
    historical.add_argument("--docker-push-evidence", type=Path)
    parser.add_argument("--prebuilt-image-evidence", type=Path)
    parser.add_argument("--prior-lifecycle-evidence-integrity")
    parser.add_argument("--live-registry-observation", required=True, type=Path)
    parser.add_argument("--reconstruction-authorization", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--repository-head", required=True)
    return parser


def _outside_repository(path: Path, label: str) -> Path:
    resolved = path.resolve()
    repository = REPOSITORY_ROOT.resolve()
    if resolved == repository or repository in resolved.parents:
        raise RuntimeError(f"{label}-inside-repository")
    return resolved


def _write_exclusive(path: Path, value: Mapping[str, JsonValue]) -> None:
    if path.exists() or not path.parent.is_dir():
        raise RuntimeError("already-pushed-reconstruction-output-state-invalid")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical_bytes(dict(value)))
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        path.unlink(missing_ok=True)
        raise RuntimeError("already-pushed-reconstruction-output-write-failed")


def main() -> int:
    args = _parser().parse_args()
    try:
        now = datetime.now(UTC).replace(microsecond=0)
        if args.historical_push_evidence is not None:
            historical_raw = load_json(
                _outside_repository(
                    args.historical_push_evidence, "historical-push-evidence"
                )
            )
            if not isinstance(historical_raw, dict):
                raise RuntimeError("already-pushed-reconstruction-input-malformed")
            historical = publication.validate_historical_push_evidence(
                cast(Mapping[str, JsonValue], historical_raw)
            )
        else:
            if (
                args.docker_push_evidence is None
                or args.prebuilt_image_evidence is None
                or args.prior_lifecycle_evidence_integrity is None
            ):
                raise RuntimeError("already-pushed-reconstruction-input-malformed")
            docker_raw = load_json(
                _outside_repository(args.docker_push_evidence, "docker-push-evidence")
            )
            prebuilt_raw = load_json(
                _outside_repository(
                    args.prebuilt_image_evidence, "prebuilt-image-evidence"
                )
            )
            if not isinstance(docker_raw, dict) or not isinstance(prebuilt_raw, dict):
                raise RuntimeError("already-pushed-reconstruction-input-malformed")
            historical = publication.historical_push_evidence_from_retained_artifacts(
                docker_push_evidence=cast(Mapping[str, JsonValue], docker_raw),
                prebuilt_image_evidence=cast(Mapping[str, JsonValue], prebuilt_raw),
                prior_lifecycle_evidence_integrity=args.prior_lifecycle_evidence_integrity,
            )
        observation_raw = load_json(
            _outside_repository(
                args.live_registry_observation, "live-registry-observation"
            )
        )
        authorization_raw = load_json(
            _outside_repository(
                args.reconstruction_authorization, "reconstruction-authorization"
            )
        )
        if not all(
            isinstance(value, dict) for value in (observation_raw, authorization_raw)
        ):
            raise RuntimeError("already-pushed-reconstruction-input-malformed")
        observation = publication.validate_live_registry_publication_observation(
            cast(Mapping[str, JsonValue], observation_raw), now_utc=now
        )
        authorization = (
            publication.validate_already_pushed_reconstruction_authorization(
                cast(Mapping[str, JsonValue], authorization_raw),
                now_utc=now,
                repository_head=args.repository_head,
            )
        )
        record = publication.reconstruct_already_pushed_publication_record(
            historical=historical,
            observation=observation,
            authorization=authorization,
            repository_head=args.repository_head,
            now_utc=now,
        )
        output = _outside_repository(args.output, "reconstructed-already-pushed-record")
        _write_exclusive(output, record.as_json())
        print(
            json.dumps(
                {
                    "integritySha256": str(record.as_json()["integritySha256"]),
                    "provenance": record.evidence_provenance,
                    "status": "reconstructed",
                },
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        return 0
    except Exception:
        print(
            json.dumps(
                {
                    "error": "already-pushed-reconstruction-failed",
                    "status": "blocked",
                },
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
