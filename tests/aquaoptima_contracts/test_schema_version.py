"""TDD slice A — ``SchemaVersion``.

Acceptance: parsing, rendering, and compatibility-check helpers are
total functions that reject malformed input.
"""

from __future__ import annotations

import pytest

from aquaoptima_contracts import SchemaVersion


def test_parse_render_round_trip() -> None:
    parsed = SchemaVersion.parse("1.0.0")
    assert parsed == SchemaVersion(1, 0, 0)
    assert parsed.render() == "1.0.0"


def test_parse_handles_multi_digit_components() -> None:
    parsed = SchemaVersion.parse("12.34.56")
    assert parsed.render() == "12.34.56"


@pytest.mark.parametrize(
    "raw",
    [
        "1.0",
        "1",
        "v1.0.0",
        "1.0.0-pre",
        "1.0.0+meta",
        "01.0.0",
        "1.01.0",
        "1.0.0.0",
        "",
        " 1.0.0",
        "1.0.0 ",
    ],
)
def test_parse_rejects_malformed_input(raw: str) -> None:
    with pytest.raises(ValueError):
        SchemaVersion.parse(raw)


@pytest.mark.parametrize("raw", [None, 1.0, 100, (1, 0, 0), object()])
def test_parse_rejects_non_string_input(raw: object) -> None:
    with pytest.raises(ValueError):
        SchemaVersion.parse(raw)  # type: ignore[arg-type]


def test_negative_components_rejected() -> None:
    with pytest.raises(ValueError):
        SchemaVersion(-1, 0, 0)
    with pytest.raises(ValueError):
        SchemaVersion(0, -2, 0)
    with pytest.raises(ValueError):
        SchemaVersion(0, 0, -3)


def test_bool_components_rejected() -> None:
    with pytest.raises(ValueError):
        SchemaVersion(True, 0, 0)  # type: ignore[arg-type]


def test_is_compatible_reader_reflexive_within_major() -> None:
    reader = SchemaVersion(1, 4, 0)
    assert reader.is_compatible_reader(reader) is True
    assert reader.is_compatible_reader(SchemaVersion(1, 0, 0)) is True
    assert reader.is_compatible_reader(SchemaVersion(1, 4, 9)) is True
    assert reader.is_compatible_reader(SchemaVersion(1, 9, 9)) is True


def test_is_compatible_reader_rejects_across_majors() -> None:
    reader = SchemaVersion(1, 0, 0)
    assert reader.is_compatible_reader(SchemaVersion(2, 0, 0)) is False
    assert reader.is_compatible_reader(SchemaVersion(0, 9, 9)) is False


def test_is_compatible_reader_requires_schema_version_arg() -> None:
    with pytest.raises(TypeError):
        SchemaVersion(1, 0, 0).is_compatible_reader("1.0.0")  # type: ignore[arg-type]


def test_frozen_hashable() -> None:
    version = SchemaVersion(1, 2, 3)
    assert hash(version) == hash(SchemaVersion(1, 2, 3))
    with pytest.raises(Exception):
        version.major = 9  # type: ignore[misc]
