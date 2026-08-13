from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from enum import StrEnum
from os import environ
from typing import Final

from opencanvas_api.db.role_privileges import quote_identifier

MANIFEST_ENV: Final = "OPENCANVAS_DATABASE_PRINCIPAL_MANIFEST"
CAMPAIGN_ENV: Final = "OPENCANVAS_CAMPAIGN_ID"
GENERATION_ENV: Final = "OPENCANVAS_CAMPAIGN_GENERATION_ID"
CURRENT_PRINCIPAL_ID_ENV: Final = "OPENCANVAS_DATABASE_CURRENT_PRINCIPAL_ID"
_CAMPAIGN = re.compile(r"^[a-z][a-z0-9-]{7,47}$")
_GENERATION = re.compile(r"^g[1-9][0-9]{0,5}-[a-f0-9]{12}$")
_CORRELATION = re.compile(r"^[a-f0-9]{16}$")
_PRINCIPAL_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{2,62}$")


class PrincipalManifestError(RuntimeError):
    pass


class PrincipalSlot(StrEnum):
    BOOTSTRAP = "bootstrap"
    MIGRATION = "migration"
    API = "api"
    WORKER = "worker"
    EVIDENCE = "evidence"
    CLEANUP = "cleanup"


@dataclass(frozen=True, slots=True)
class PrincipalBinding:
    role: PrincipalSlot
    name: str
    object_id: str

    def __post_init__(self) -> None:
        if _PRINCIPAL_NAME.fullmatch(self.name) is None:
            raise PrincipalManifestError("principal label is malformed")
        try:
            parsed = uuid.UUID(self.object_id)
        except ValueError as exc:
            raise PrincipalManifestError("principal object binding is malformed") from exc
        if parsed.int == 0:
            raise PrincipalManifestError("principal object binding is malformed")
        quote_identifier(self.name)


@dataclass(frozen=True, slots=True)
class PrincipalManifest:
    campaign_id: str
    generation_id: str
    subscription_correlation: str
    principals: dict[PrincipalSlot, PrincipalBinding]

    def require_current(self, role: PrincipalSlot, *, current_name: str) -> PrincipalBinding:
        binding = self.principals[role]
        if current_name != binding.name:
            raise PrincipalManifestError(
                "current database identity does not match its semantic role"
            )
        observed_object_id = environ.get(CURRENT_PRINCIPAL_ID_ENV, "")
        try:
            observed = uuid.UUID(observed_object_id)
        except ValueError as exc:
            raise PrincipalManifestError(
                "current principal object binding is unverifiable"
            ) from exc
        if observed != uuid.UUID(binding.object_id):
            raise PrincipalManifestError("current principal object binding is unverifiable")
        return binding


def load_principal_manifest() -> PrincipalManifest:
    raw = environ.get(MANIFEST_ENV, "")
    if not raw or len(raw.encode("utf-8")) > 16_384:
        raise PrincipalManifestError("principal manifest is missing or oversized")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PrincipalManifestError("principal manifest is invalid JSON") from exc
    if not isinstance(value, dict) or set(value) != {
        "version",
        "campaignId",
        "generationId",
        "subscriptionCorrelation",
        "principals",
    }:
        raise PrincipalManifestError("principal manifest fields are invalid")
    if value["version"] != "m7.8-principal-manifest-v1":
        raise PrincipalManifestError("principal manifest version is invalid")
    campaign_id = _required_string(value, "campaignId", _CAMPAIGN)
    generation_id = _required_string(value, "generationId", _GENERATION)
    correlation = _required_string(value, "subscriptionCorrelation", _CORRELATION)
    if (
        environ.get(CAMPAIGN_ENV, "") != campaign_id
        or environ.get(GENERATION_ENV, "") != generation_id
    ):
        raise PrincipalManifestError("principal manifest campaign binding is stale or conflicting")
    raw_principals = value["principals"]
    expected = {slot.value for slot in PrincipalSlot}
    if not isinstance(raw_principals, dict) or set(raw_principals) != expected:
        raise PrincipalManifestError("principal semantic slots are invalid")
    principals: dict[PrincipalSlot, PrincipalBinding] = {}
    for slot in PrincipalSlot:
        item = raw_principals[slot.value]
        if not isinstance(item, dict) or set(item) != {"role", "name", "objectId"}:
            raise PrincipalManifestError("principal binding fields are invalid")
        if item["role"] != slot.value:
            raise PrincipalManifestError("principal semantic role is swapped")
        name = item["name"]
        object_id = item["objectId"]
        if not isinstance(name, str) or not isinstance(object_id, str):
            raise PrincipalManifestError("principal binding types are invalid")
        principals[slot] = PrincipalBinding(slot, name, object_id)
    if len({item.name for item in principals.values()}) != len(principals) or len(
        {item.object_id for item in principals.values()}
    ) != len(principals):
        raise PrincipalManifestError("principal bindings must be distinct")
    return PrincipalManifest(campaign_id, generation_id, correlation, principals)


def _required_string(value: dict[str, object], key: str, pattern: re.Pattern[str]) -> str:
    candidate = value[key]
    if not isinstance(candidate, str) or pattern.fullmatch(candidate) is None:
        raise PrincipalManifestError(f"principal manifest {key} is malformed")
    return candidate


__all__ = [
    "CAMPAIGN_ENV",
    "CURRENT_PRINCIPAL_ID_ENV",
    "GENERATION_ENV",
    "MANIFEST_ENV",
    "PrincipalBinding",
    "PrincipalManifest",
    "PrincipalManifestError",
    "PrincipalSlot",
    "load_principal_manifest",
]
