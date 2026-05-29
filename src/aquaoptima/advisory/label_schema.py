"""Shared label / axis schema for AquaOptima advisory artifacts (A+B).

The contracts SDK ``ModelArtifactRecord`` does not have a typed field for an axis/label
schema -- that goes in its free-form ``summary`` mapping. This module produces a
canonical, deterministic schema dict that both pillars embed, plus guards that keep that
dict clean of forbidden / accelerator vocabulary (the Edge package validator scans
``summary`` strings for accelerator tokens like ``cuda`` / ``arm64`` and rejects them).

Single source of truth for axis identity is ``aquaoptima.dataio.yilan_axis_map``; we never
re-spell the axis names here.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from ..dataio.yilan_axis_map import (
    BINARY_AXES,
    CANONICAL_AXES_ORDERED,
    CONTINUOUS_AXES,
)

# Axis that exists in the canonical taxonomy but has 0% telemetry coverage at the Yilan
# site. It is emitted as N/A and never scored. Mirrors evaluation.MASKED_AXIS.
MASKED_AXIS = "edge_valve_position"

# Accelerator substrings the AMAX edge package validator rejects anywhere in
# notes/description/summary. Kept here so the schema builder can self-check.
# (Lower-case substrings; we test membership case-insensitively.)
REJECTED_ACCELERATOR_SUBSTRINGS = (
    "cuda",
    "tensorrt",
    "jetson",
    "orin",
    "arm64",
    "aarch64",
)

# Physical unit per canonical axis. node_status is hydraulic head (m), NOT a status;
# edge_status is a near-constant on/off fraction handled as continuous (Sprint 26 fix).
AXIS_UNITS: Mapping[str, str] = {
    "edge_flow": "m3_per_h",
    "edge_power": "kW",
    "edge_pump_speed": "hz",
    "edge_status": "fraction_0_1",
    "node_demand": "m3_per_h",
    "node_level": "m",
    "node_pressure": "m_head",
    "node_status": "m_head",
    "edge_valve_position": "fraction_0_1",
}


def active_axes_ordered() -> list[str]:
    """Deterministic ordered list of axes that carry telemetry (masked axis excluded)."""
    return [a for a in CANONICAL_AXES_ORDERED if a != MASKED_AXIS]


def axis_kind(axis: str) -> str:
    """Return ``"binary"`` or ``"continuous"`` per the single-source-of-truth taxonomy."""
    if axis in BINARY_AXES:
        return "binary"
    if axis in CONTINUOUS_AXES:
        return "continuous"
    if axis == MASKED_AXIS:
        return "masked"
    raise KeyError(f"unknown axis {axis!r}")


def telemetry_axis_schema() -> dict[str, Any]:
    """Canonical input/telemetry axis schema embedded in a ModelArtifactRecord.summary.

    The ``axes`` list is ORDER-SIGNIFICANT: feature/prediction vector dimension ``i``
    corresponds to ``axes[i]["name"]``. This is the contract the offline evaluation
    harness relies on.
    """
    axes = [
        {
            "index": i,
            "name": name,
            "kind": axis_kind(name),
            "unit": AXIS_UNITS[name],
        }
        for i, name in enumerate(active_axes_ordered())
    ]
    return {
        "axis_order": active_axes_ordered(),
        "axes": axes,
        "masked": [{"name": MASKED_AXIS, "reason": "zero_telemetry_coverage", "scored": False}],
        "normalization": "zscore_per_axis_from_yilan_2025_train_stats",
    }


def telemetry_axis_schema_json() -> str:
    """The canonical axis schema as a compact JSON string.

    The contracts SDK only allows scalar (or flat-list-of-scalar) values in a
    ``ModelArtifactRecord.summary``; nested dicts are rejected. So the structured schema is
    embedded as a single JSON *string* value. Sorted keys for deterministic output.
    """
    return json.dumps(telemetry_axis_schema(), sort_keys=True, separators=(",", ":"))


def assert_summary_accelerator_clean(summary: Mapping[str, Any]) -> None:
    """Raise ``ValueError`` if any string in ``summary`` contains a rejected accelerator token.

    The Edge package validator would otherwise reject the whole package. We fail fast and
    locally so an artifact author sees the exact offending value.
    """
    def _walk(value: Any) -> None:
        if isinstance(value, str):
            low = value.lower()
            for tok in REJECTED_ACCELERATOR_SUBSTRINGS:
                if tok in low:
                    raise ValueError(
                        f"summary contains rejected accelerator token {tok!r} in value "
                        f"{value!r}; the AMAX edge profile would reject this package"
                    )
        elif isinstance(value, Mapping):
            for v in value.values():
                _walk(v)
        elif isinstance(value, (list, tuple)):
            for v in value:
                _walk(v)

    _walk(dict(summary))


__all__ = [
    "MASKED_AXIS",
    "REJECTED_ACCELERATOR_SUBSTRINGS",
    "AXIS_UNITS",
    "active_axes_ordered",
    "axis_kind",
    "telemetry_axis_schema",
    "telemetry_axis_schema_json",
    "assert_summary_accelerator_clean",
]
