"""TDD — ``UnitSpec`` (Sprint 42).

Acceptance: ``UnitSpec`` is a frozen ``(name, dimension)`` record.
The dimension token is bounded to a small canonical vocabulary
matching the Phase 1 conversion tables (``length``, ``flow``,
``fraction``, ``power``, ``boolean``).
"""

from __future__ import annotations

import pytest

from aquaoptima_contracts import (
    CANONICAL_UNIT_DIMENSIONS,
    ContractError,
    UnitSpec,
    dump_canonical_json,
    load_canonical_json,
)


def test_minimal_unit_spec_round_trip() -> None:
    spec = UnitSpec(name="m", dimension="length")
    raw = dump_canonical_json(spec)
    decoded = load_canonical_json(raw)
    assert decoded == {"name": "m", "dimension": "length"}
    restored = UnitSpec.from_dict(decoded)
    assert restored == spec


def test_dimensions_contain_phase1_canonical_units() -> None:
    for required in ("length", "flow", "fraction", "power", "boolean"):
        assert required in CANONICAL_UNIT_DIMENSIONS


def test_unit_spec_frozen() -> None:
    spec = UnitSpec(name="m3/s", dimension="flow")
    with pytest.raises(Exception):
        spec.name = "l/s"  # type: ignore[misc]


def test_unit_spec_rejects_unknown_dimension() -> None:
    with pytest.raises(ContractError):
        UnitSpec(name="m", dimension="not_a_dimension")


def test_unit_spec_rejects_empty_name() -> None:
    with pytest.raises(ContractError):
        UnitSpec(name="", dimension="length")


def test_unit_spec_from_dict_rejects_unknown_field() -> None:
    with pytest.raises(ContractError):
        UnitSpec.from_dict(
            {"name": "m", "dimension": "length", "extra": "rogue"}
        )
