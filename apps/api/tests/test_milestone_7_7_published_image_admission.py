from __future__ import annotations

import subprocess

import pytest
from performance.milestone_7_7.framework import ContractError
from preflight.milestone_7_7 import managed_binding_contracts as contracts

IMAGE_SOURCE_HEAD = "7321e69b8296660c53015a05e5b01b9adf1e302f"
CONTROL_PLANE_HEAD = "23bd360c9d25e66d76c5f371a5b05f04500eb7b3"


def _pending_image() -> dict[str, object]:
    return {
        "imageSourceCommit": IMAGE_SOURCE_HEAD,
        "imageBuildInputSha256": "a" * 64,
        "localImageId": "sha256:" + "b" * 64,
        "configDigest": "sha256:" + "b" * 64,
        "platform": "linux/amd64",
        "repository": "opencanvas-api",
        "sourceTag": f"source-{IMAGE_SOURCE_HEAD}",
        "registryManifestDigest": None,
    }


def test_pending_image_identity_separates_control_and_image_commits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        contracts.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess((), 0),
    )

    identity = contracts.pending_image_identity(
        control_plane_head=CONTROL_PLANE_HEAD, value=_pending_image()
    )

    assert identity["controlPlaneHead"] == CONTROL_PLANE_HEAD
    assert identity["imageSourceCommit"] != CONTROL_PLANE_HEAD
    assert identity["imageBuildInputSha256"] == "a" * 64
    assert identity["registryManifestDigest"] is None
    assert identity["publicationState"] == "pending"
    assert identity["platform"] == "linux/amd64"


def test_pending_image_identity_rejects_changed_build_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        contracts.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess((), 1),
    )

    with pytest.raises(ContractError, match="build inputs changed"):
        contracts.pending_image_identity(
            control_plane_head=CONTROL_PLANE_HEAD, value=_pending_image()
        )
