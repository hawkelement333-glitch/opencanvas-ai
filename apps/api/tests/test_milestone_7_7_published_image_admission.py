from __future__ import annotations

import subprocess

import pytest
from performance.milestone_7_7.framework import ContractError
from preflight.milestone_7_7 import managed_binding_contracts as contracts

CONTROL_PLANE_HEAD = "23bd360c9d25e66d76c5f371a5b05f04500eb7b3"


def test_published_image_identity_separates_control_and_image_commits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        contracts.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess((), 0),
    )

    identity = contracts.published_image_identity(control_plane_head=CONTROL_PLANE_HEAD)

    assert identity["controlPlaneHead"] == CONTROL_PLANE_HEAD
    assert identity["imageSourceCommit"] != CONTROL_PLANE_HEAD
    assert identity["imageBuildInputSha256"] == (
        "16758013417d703a9ebe661511ff1fc305653372286909cdbbc6e9c29a6e613c"
    )
    assert identity["registryManifestDigest"].startswith("sha256:")
    assert identity["platform"] == "linux/amd64"


def test_published_image_identity_rejects_changed_build_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        contracts.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess((), 1),
    )

    with pytest.raises(ContractError, match="build inputs changed"):
        contracts.published_image_identity(control_plane_head=CONTROL_PLANE_HEAD)
