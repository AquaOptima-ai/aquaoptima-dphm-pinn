"""TDD slice C — ``SafetyFlagSet``.

Acceptance: only the canonical token list is accepted; each token must
be ``True`` for the current product boundary.
"""

from __future__ import annotations

import pytest

from aquaoptima_contracts import (
    CANONICAL_SAFETY_FLAG_TOKENS,
    FORBIDDEN_VOCABULARY,
    SafetyFlagError,
    SafetyFlagSet,
    dump_canonical_json,
    load_canonical_json,
)
from aquaoptima_contracts.safety.flags import default_safety_flag_set


def _canonical_kwargs() -> dict[str, bool]:
    return {name: True for name in CANONICAL_SAFETY_FLAG_TOKENS}


def test_canonical_token_count_is_seven() -> None:
    assert len(CANONICAL_SAFETY_FLAG_TOKENS) == 7


def test_canonical_set_construction_succeeds() -> None:
    flags = SafetyFlagSet(**_canonical_kwargs())
    for name in CANONICAL_SAFETY_FLAG_TOKENS:
        assert getattr(flags, name) is True


def test_canonical_set_round_trips_through_canonical_json() -> None:
    flags = default_safety_flag_set()
    rendered = dump_canonical_json(flags)
    decoded = load_canonical_json(rendered)
    rebuilt = SafetyFlagSet.from_dict(decoded)
    assert rebuilt == flags


def test_canonical_set_to_dict_contains_only_canonical_keys() -> None:
    flags = default_safety_flag_set()
    payload = flags.to_dict()
    assert set(payload.keys()) == set(CANONICAL_SAFETY_FLAG_TOKENS)
    for name in CANONICAL_SAFETY_FLAG_TOKENS:
        assert payload[name] is True


@pytest.mark.parametrize("missing", list(CANONICAL_SAFETY_FLAG_TOKENS))
def test_missing_canonical_token_rejected_by_from_dict(missing: str) -> None:
    data = _canonical_kwargs()
    data.pop(missing)
    with pytest.raises(SafetyFlagError):
        SafetyFlagSet.from_dict(data)


@pytest.mark.parametrize("flag", list(CANONICAL_SAFETY_FLAG_TOKENS))
def test_false_canonical_token_rejected_at_construction(flag: str) -> None:
    kwargs = _canonical_kwargs()
    kwargs[flag] = False
    with pytest.raises(SafetyFlagError):
        SafetyFlagSet(**kwargs)


@pytest.mark.parametrize("flag", list(CANONICAL_SAFETY_FLAG_TOKENS))
def test_non_true_canonical_token_rejected_at_construction(flag: str) -> None:
    # Truthy-but-not-True values (e.g. 1, "yes") are still rejected
    # because the post-init guard tests for identity with ``True``.
    kwargs = _canonical_kwargs()
    kwargs[flag] = 1  # type: ignore[assignment]
    with pytest.raises(SafetyFlagError):
        SafetyFlagSet(**kwargs)


def test_unknown_token_rejected_by_from_dict() -> None:
    data = _canonical_kwargs()
    data["new_unrelated_flag"] = True
    with pytest.raises(SafetyFlagError):
        SafetyFlagSet.from_dict(data)


@pytest.mark.parametrize("forbidden_term", sorted(FORBIDDEN_VOCABULARY))
def test_forbidden_vocabulary_token_rejected_as_flag_name(
    forbidden_term: str,
) -> None:
    data = _canonical_kwargs()
    data[forbidden_term] = True
    with pytest.raises(SafetyFlagError):
        SafetyFlagSet.from_dict(data)


def test_non_snake_case_token_rejected() -> None:
    data = _canonical_kwargs()
    data["NotSnakeCase"] = True
    with pytest.raises(SafetyFlagError):
        SafetyFlagSet.from_dict(data)


def test_from_dict_rejects_non_mapping() -> None:
    with pytest.raises(SafetyFlagError):
        SafetyFlagSet.from_dict("not a mapping")  # type: ignore[arg-type]


def test_safety_flag_set_is_frozen_and_hashable() -> None:
    flags = default_safety_flag_set()
    assert hash(flags) == hash(default_safety_flag_set())
    with pytest.raises(Exception):
        flags.offline = False  # type: ignore[misc]
