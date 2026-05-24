"""TDD slice E — deterministic JSON helpers.

Acceptance: encoding is deterministic and round-trips losslessly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aquaoptima_contracts import (
    dump_canonical_json,
    load_canonical_json,
    write_canonical_json,
)
from aquaoptima_contracts.testing.builders import (
    make_capability_declaration,
    make_default_safety_flag_set,
    make_envelope,
)


def test_shuffled_keys_render_stable_output() -> None:
    forward = {"alpha": 1, "beta": 2, "gamma": 3}
    backward = {"gamma": 3, "beta": 2, "alpha": 1}
    assert dump_canonical_json(forward) == dump_canonical_json(backward)


def test_encoding_a_float_twice_produces_identical_output() -> None:
    value = 1.0 / 7.0
    rendered_a = dump_canonical_json({"value": value})
    rendered_b = dump_canonical_json({"value": value})
    assert rendered_a == rendered_b
    decoded = load_canonical_json(rendered_a)
    assert decoded["value"] == value


def test_round_trip_lossless_for_supported_primitives() -> None:
    sample = {
        "bool_true": True,
        "bool_false": False,
        "int": 42,
        "neg_int": -7,
        "float": 3.14159,
        "small_float": 1e-12,
        "string": "hello",
        "none": None,
        "list": [1, 2.0, "three", False, None],
        "nested": {"inner": [{"k": "v"}]},
    }
    rendered = dump_canonical_json(sample)
    decoded = load_canonical_json(rendered)
    assert decoded == sample


def test_write_canonical_json_appends_trailing_newline(tmp_path: Path) -> None:
    out = write_canonical_json({"a": 1}, tmp_path / "out.json")
    raw = out.read_bytes()
    assert raw.endswith(b"\n")
    text_no_newline = raw.decode("utf-8").rstrip("\n")
    assert dump_canonical_json({"a": 1}) == text_no_newline


def test_write_then_reread_returns_byte_identical_content(tmp_path: Path) -> None:
    payload = {"z": 1, "a": 2, "m": [3, 2, 1]}
    out_a = write_canonical_json(payload, tmp_path / "a.json")
    out_b = write_canonical_json(payload, tmp_path / "b.json")
    assert out_a.read_bytes() == out_b.read_bytes()


def test_dump_round_trips_envelope_dict() -> None:
    envelope = make_envelope()
    payload = envelope.to_dict()
    raw = dump_canonical_json(payload)
    assert load_canonical_json(raw) == payload


def test_dump_round_trips_dataclass_via_to_dict() -> None:
    flags = make_default_safety_flag_set()
    raw_via_object = dump_canonical_json(flags)
    raw_via_dict = dump_canonical_json(flags.to_dict())
    assert raw_via_object == raw_via_dict


def test_dump_round_trips_frozenset_as_sorted_list() -> None:
    decl = make_capability_declaration(
        declared={
            "validate_manifest",
            "validate_safety_flags",
            "run_shadow_replay",
        }
    )
    rendered = dump_canonical_json(decl)
    decoded = load_canonical_json(rendered)
    assert decoded["declared"] == sorted(decoded["declared"])


def test_load_accepts_bytes() -> None:
    raw = dump_canonical_json({"a": 1}).encode("utf-8")
    assert load_canonical_json(raw) == {"a": 1}


def test_load_rejects_non_text() -> None:
    with pytest.raises(TypeError):
        load_canonical_json(123)  # type: ignore[arg-type]


def test_dump_rejects_unsupported_object() -> None:
    class _NotSerialisable:
        pass

    with pytest.raises(TypeError):
        dump_canonical_json({"x": _NotSerialisable()})


def test_write_rejects_non_path(tmp_path: Path) -> None:
    with pytest.raises(TypeError):
        write_canonical_json({"a": 1}, 123)  # type: ignore[arg-type]


def test_write_creates_missing_parent_directories(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "more" / "out.json"
    written = write_canonical_json({"a": 1}, target)
    assert written.read_text() == dump_canonical_json({"a": 1}) + "\n"


def test_dump_handles_nested_frozenset_in_dict() -> None:
    payload = {"declared": frozenset({"b", "a", "c"})}
    rendered = dump_canonical_json(payload)
    decoded = load_canonical_json(rendered)
    assert decoded == {"declared": ["a", "b", "c"]}
