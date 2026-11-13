from __future__ import annotations

import copy
from collections import Counter
from collections.abc import Callable
from dataclasses import FrozenInstanceError, fields
from pathlib import Path
from typing import cast

import pytest
from test_milestone_7_8_controller_admission import (
    alternating_transition_fixture,
    authority_fixture,
)

from infra.milestone_7_8 import controller_admission as admission
from infra.milestone_7_8.campaign import CampaignError
from infra.milestone_7_8.controller import ControllerConfig


def test_each_distinct_transition_is_validated_once_per_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # This fixture executes publication -> renewal -> publication -> renewal
    # through the real planners, fake-provider executors, reconciler and adoption.
    build = cast(Callable[[Path], dict[str, object]], alternating_transition_fixture)
    evidence = build(tmp_path)
    saved = copy.deepcopy(evidence)
    counts: Counter[str] = Counter()
    original = admission._validate_authority_evidence_uncached

    def count(value: object) -> ControllerConfig:
        counts[admission.digest("test-history", value)] += 1
        return original(value)

    monkeypatch.setattr(admission, "_validate_authority_evidence_uncached", count)
    first = admission.validate_authority_evidence(evidence)
    assert len(counts) == 5
    assert set(counts.values()) == {1}
    assert admission._VALIDATED_HISTORY.get() is None
    second = admission.validate_authority_evidence(evidence)
    assert first == second and first is not second
    assert set(counts.values()) == {2}
    assert evidence == saved
    for field in fields(first):
        with pytest.raises(FrozenInstanceError):
            setattr(first, field.name, "changed")


def test_mutated_history_cannot_reuse_success_in_the_same_traversal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    build = cast(Callable[[Path], dict[str, object]], alternating_transition_fixture)
    evidence = build(tmp_path)
    saved = copy.deepcopy(evidence)
    renewal = cast(dict[str, object], evidence["renewal"])
    child = copy.deepcopy(cast(dict[str, object], renewal["priorAuthorityEvidence"]))
    original = admission._validate_authority_evidence_uncached
    checked = False

    def alter(value: object) -> ControllerConfig:
        nonlocal checked
        if value is evidence and not checked:
            checked = True
            admission.validate_authority_evidence(child)
            verification = cast(dict[str, object], child["verificationResult"])
            verification["status"] = "not-verified"
            with pytest.raises(CampaignError):
                admission.validate_authority_evidence(child)
        return original(value)

    monkeypatch.setattr(admission, "_validate_authority_evidence_uncached", alter)
    admission.validate_authority_evidence(evidence)
    assert checked and evidence == saved
    assert admission._VALIDATED_HISTORY.get() is None


def test_exception_does_not_cache_or_leak_validation_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence = authority_fixture()
    original = admission._validate_authority_evidence_uncached
    calls = 0

    def once(value: object) -> ControllerConfig:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise CampaignError("injected validation failure")
        return original(value)

    monkeypatch.setattr(admission, "_validate_authority_evidence_uncached", once)
    with pytest.raises(CampaignError, match="injected validation failure"):
        admission.validate_authority_evidence(evidence)
    assert admission._VALIDATED_HISTORY.get() is None
    admission.validate_authority_evidence(evidence)
    assert calls == 2
    assert admission._VALIDATED_HISTORY.get() is None


def test_mutation_during_validation_is_not_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    evidence = authority_fixture()
    original = admission._validate_authority_evidence_uncached

    def mutate(value: object) -> ControllerConfig:
        result = original(value)
        document = cast(dict[str, object], value)
        verification = cast(dict[str, object], document["verificationResult"])
        verification["status"] = "not-verified"
        return result

    monkeypatch.setattr(admission, "_validate_authority_evidence_uncached", mutate)
    with pytest.raises(CampaignError, match="changed during validation"):
        admission.validate_authority_evidence(evidence)
    assert admission._VALIDATED_HISTORY.get() is None
    with pytest.raises(CampaignError):
        admission.validate_authority_evidence(evidence)


def test_cycle_is_rejected_before_cache_key_and_does_not_leak_context() -> None:
    evidence = authority_fixture()
    evidence["renewal"] = {"priorAuthorityEvidence": evidence}
    with pytest.raises(CampaignError, match="cyclic"):
        admission.validate_authority_evidence(evidence)
    assert admission._VALIDATED_HISTORY.get() is None
    admission.validate_authority_evidence(authority_fixture())
