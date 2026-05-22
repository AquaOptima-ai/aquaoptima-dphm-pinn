"""Tests for the QualityFlag enum and the ``is_usable`` helper."""

from __future__ import annotations

import pytest

from aquaoptima.dataio import QualityFlag
from aquaoptima.dataio.quality import is_usable


def test_quality_flag_members() -> None:
    expected = {
        "GOOD", "MISSING", "STALE", "FLATLINE",
        "OUTLIER", "BAD_QUALITY", "MANUAL_OVERRIDE",
    }
    actual = {m.name for m in QualityFlag}
    assert expected.issubset(actual)


def test_quality_flag_values_are_strings() -> None:
    # str Enum lets us serialise quality flags as plain strings without
    # extra glue code in any downstream telemetry exporter.
    for flag in QualityFlag:
        assert isinstance(flag.value, str)
        assert flag.value == flag.value.lower()


def test_is_usable_only_for_good() -> None:
    assert is_usable(QualityFlag.GOOD) is True


@pytest.mark.parametrize(
    "flag",
    [
        QualityFlag.MISSING,
        QualityFlag.STALE,
        QualityFlag.FLATLINE,
        QualityFlag.OUTLIER,
        QualityFlag.BAD_QUALITY,
        QualityFlag.MANUAL_OVERRIDE,
    ],
)
def test_is_usable_false_for_non_good(flag: QualityFlag) -> None:
    assert is_usable(flag) is False
