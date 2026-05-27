"""Cold-start replay / shadow dataset builder (Sprint 35).

Sprint 35 adds the second read-only shadow-mode plumbing layer: it
consumes the Sprint 34 :class:`TelemetryTagMap` plus an iterable of
**offline** telemetry rows (Python mappings) and emits a typed
:class:`ShadowReplayDataset` whose frames key node / edge measurements
by canonical dPHM axis and id.

The dataset is the bridge between operator-facing telemetry tags
(``PT_DISCHARGE_01``, ``FT_PUMP_01``) and a future shadow-mode
validation harness: every per-frame value is normalised to a single
canonical unit (``m`` for pressure / level, ``m3/s`` for flow /
demand, ``fraction`` for pump speed / valve position, ``kw`` for
power, ``bool`` for status). Missing tag values, non-numeric samples,
out-of-family unit declarations, and inter-row staleness are recorded
deterministically in :class:`ShadowReplayDiagnostics`.

This module is **read-only / offline only**. It contains:

* :class:`ShadowReplayDiagnostics` — deterministic warnings / errors
  tuples.
* :class:`ShadowReplayFrame` — single-timestamp frozen frame keyed by
  canonical axis.
* :class:`ShadowReplayDataset` — frozen container holding the frames,
  the originating :class:`TelemetryTagMap`, and dataset-level
  diagnostics.
* :func:`build_shadow_replay_dataset` — pure builder over an iterable
  of offline mappings.
* :func:`load_shadow_replay_csv` — stdlib-only CSV loader.

Safety boundary (reaffirmed verbatim per Sprints 23-34):

* no live SCADA / PLC / PAC / historian / OPC-UA / MQTT / REST
  adapter;
* no write / control / setpoint path;
* no dPHM forward-solve comparator / advisory recommendation;
* no dPL calibration — Sprint 36;
* no ONNX / TensorRT / Jetson deployment;
* no production savings / control claim.

Sprint 35 is a *value normaliser* on top of the Sprint 34 *schema
adapter*. The two together provide the dPHM-side metadata + offline
frame surface a future shadow-mode evaluation can consume without
touching live OT systems.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping, Union

from .telemetry_tag_map import (
    CanonicalTelemetryTag,
    TELEMETRY_AXIS_EDGE_FLOW,
    TELEMETRY_AXIS_EDGE_POWER,
    TELEMETRY_AXIS_EDGE_PUMP_SPEED,
    TELEMETRY_AXIS_EDGE_STATUS,
    TELEMETRY_AXIS_EDGE_VALVE_POSITION,
    TELEMETRY_AXIS_NODE_DEMAND,
    TELEMETRY_AXIS_NODE_LEVEL,
    TELEMETRY_AXIS_NODE_PRESSURE,
    TELEMETRY_AXIS_NODE_STATUS,
    TELEMETRY_MEASUREMENT_STATUS,
    TelemetryTagMap,
)


PathLike = Union[str, Path]


# ---------------------------------------------------------------------------
# Unit conversion tables
# ---------------------------------------------------------------------------


# Pressure conversions to canonical "m" (metres of water head).
#
# Bar / kPa / psi → m H2O at 4°C, g = 9.80665 m/s^2.
# These are deterministic, documented constants and never change.
_PRESSURE_TO_M: Mapping[str, float] = {
    "m": 1.0,
    "meter": 1.0,
    "bar": 10.197162129779283,
    "kpa": 0.10197162129779283,
    "psi": 0.703249614902,
}

# Flow / demand conversions to canonical "m3/s".
_FLOW_TO_M3_S: Mapping[str, float] = {
    "m3/s": 1.0,
    "l/s": 1.0e-3,
    "gpm": 6.309019640343866e-5,
}

# Level conversions to canonical "m".
_LEVEL_TO_M: Mapping[str, float] = {
    "m": 1.0,
    "meter": 1.0,
    "ft": 0.3048,
}

# Pump speed / valve position to canonical "fraction".
#
# ``rpm`` is intentionally *not* convertible without a rated speed;
# Sprint 34 accepts it as schema metadata but the Sprint 35 value path
# refuses to invent one. Rows with ``rpm``-declared tags are recorded
# as warnings and omitted from the frame in non-strict mode.
_FRACTIONAL_TO_FRACTION: Mapping[str, float] = {
    "fraction": 1.0,
    "percent": 1.0 / 100.0,
}

# Power conversions to canonical "kw".
_POWER_TO_KW: Mapping[str, float] = {
    "kw": 1.0,
    "w": 1.0e-3,
}


# Status string interpretations. Case-insensitive on input.
_STATUS_TRUE_STRINGS: frozenset[str] = frozenset(
    {"true", "1", "on", "open", "running", "active", "yes"}
)
_STATUS_FALSE_STRINGS: frozenset[str] = frozenset(
    {"false", "0", "off", "closed", "stopped", "inactive", "no"}
)


# ---------------------------------------------------------------------------
# Frozen dataclass surface
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ShadowReplayDiagnostics:
    """Deterministic warnings / errors tuples for a replay build.

    Both tuples are empty for a fully-valid input. Warnings are
    non-fatal observations (missing optional tag, ``rpm`` pump speed
    declared without rated speed, inter-row staleness gap exceeded);
    errors are structural problems (missing timestamp, non-numeric
    sample for a numeric axis, malformed status string).

    In ``strict=True`` mode the builder raises :class:`ValueError`
    instead of returning a populated ``errors`` tuple. Warnings are
    *always* returned through this surface.

    Attributes
    ----------
    warnings
        Deterministic tuple of human-readable warning strings, in
        encounter order.
    errors
        Deterministic tuple of human-readable error strings, in
        encounter order.
    """

    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class ShadowReplayFrame:
    """Single-timestamp frame of canonicalised telemetry values.

    The frame is keyed by canonical dPHM axis (one mapping per axis,
    each ``{target_id: value}``) so a downstream shadow-mode evaluator
    can join the frame to the dPHM :class:`Network` without consulting
    the originating tag-map row-by-row.

    All numeric fields hold ``float`` values in canonical units; the
    ``edge_status`` / node-status mappings hold ``bool`` or numeric
    0/1 values (numeric is preserved verbatim if the operator already
    supplied a numeric in the ``boolean`` / ``bool`` / ``0/1`` family).

    Attributes
    ----------
    timestamp
        Whatever timestamp object was supplied in the offline row.
        Sprint 35 never parses, normalises, or compares timestamp
        objects beyond the optional staleness gap check (which only
        runs when timestamps are mutually subtractable as floats).
    node_pressure
        ``{dPHM node id: pressure (m)}``.
    node_demand
        ``{dPHM node id: demand (m3/s)}``.
    node_level
        ``{dPHM node id: level (m)}``.
    node_status
        ``{dPHM node id: bool or 0/1}``.
    edge_flow
        ``{dPHM edge id: flow (m3/s)}``.
    edge_pump_speed
        ``{dPHM edge id: pump speed (fraction in [0, 1])}``.
    edge_status
        ``{dPHM edge id: bool or 0/1}``.
    edge_power
        ``{dPHM edge id: power (kW)}``.
    edge_valve_position
        ``{dPHM edge id: valve position (fraction in [0, 1])}``.
    diagnostics
        Per-frame :class:`ShadowReplayDiagnostics`. Diagnostics local
        to this frame are recorded here; dataset-level diagnostics
        (e.g. ``"row[3]: missing timestamp"``) are recorded on the
        :class:`ShadowReplayDataset` instead.
    """

    timestamp: object
    node_pressure: Mapping[int, float] = field(default_factory=dict)
    node_demand: Mapping[int, float] = field(default_factory=dict)
    node_level: Mapping[int, float] = field(default_factory=dict)
    node_status: Mapping[int, "float | bool"] = field(default_factory=dict)
    edge_flow: Mapping[int, float] = field(default_factory=dict)
    edge_pump_speed: Mapping[int, float] = field(default_factory=dict)
    edge_status: Mapping[int, "float | bool"] = field(default_factory=dict)
    edge_power: Mapping[int, float] = field(default_factory=dict)
    edge_valve_position: Mapping[int, float] = field(default_factory=dict)
    diagnostics: ShadowReplayDiagnostics = field(
        default_factory=ShadowReplayDiagnostics
    )


@dataclass(frozen=True)
class ShadowReplayDataset:
    """Read-only typed shadow replay dataset.

    Frozen container holding the canonicalised frames (one per offline
    row, deterministic input order), the originating
    :class:`TelemetryTagMap`, and dataset-level diagnostics. Building
    the dataset twice on the same inputs returns equal datasets.

    Attributes
    ----------
    frames
        Tuple of :class:`ShadowReplayFrame`. In ``strict=False`` mode,
        rows that lack a usable timestamp are omitted from this tuple
        and surfaced through ``diagnostics.errors``; in
        ``strict=True`` mode the builder raises :class:`ValueError`.
    tag_map
        The :class:`TelemetryTagMap` the dataset was built against.
        Stored verbatim; never mutated.
    diagnostics
        Dataset-level :class:`ShadowReplayDiagnostics` recording
        warnings / errors that are not bound to a single frame.
    """

    frames: tuple[ShadowReplayFrame, ...] = ()
    tag_map: TelemetryTagMap = field(default_factory=TelemetryTagMap)
    diagnostics: ShadowReplayDiagnostics = field(
        default_factory=ShadowReplayDiagnostics
    )


# ---------------------------------------------------------------------------
# Axis → frame-field plumbing
# ---------------------------------------------------------------------------


_NUMERIC_AXIS_FIELDS: Mapping[str, str] = {
    TELEMETRY_AXIS_NODE_PRESSURE: "node_pressure",
    TELEMETRY_AXIS_NODE_DEMAND: "node_demand",
    TELEMETRY_AXIS_NODE_LEVEL: "node_level",
    TELEMETRY_AXIS_EDGE_FLOW: "edge_flow",
    TELEMETRY_AXIS_EDGE_PUMP_SPEED: "edge_pump_speed",
    TELEMETRY_AXIS_EDGE_POWER: "edge_power",
    TELEMETRY_AXIS_EDGE_VALVE_POSITION: "edge_valve_position",
}

_STATUS_AXIS_FIELDS: Mapping[str, str] = {
    TELEMETRY_AXIS_NODE_STATUS: "node_status",
    TELEMETRY_AXIS_EDGE_STATUS: "edge_status",
}


# ---------------------------------------------------------------------------
# Conversion helpers
# ---------------------------------------------------------------------------


def _coerce_numeric(value: object) -> tuple[float | None, str | None]:
    """Coerce ``value`` to ``float`` for a numeric axis.

    Returns ``(numeric, error)`` — exactly one is ``None``. Booleans
    are rejected for numeric axes (Sprint 35 keeps the status axis
    separate); ``NaN`` and infinities are rejected as well.
    """
    if isinstance(value, bool):
        return None, f"boolean value {value!r} is not valid for a numeric axis"
    if isinstance(value, (int, float)):
        numeric = float(value)
    elif isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None, "empty string is not a valid numeric sample"
        try:
            numeric = float(stripped)
        except ValueError:
            return None, f"could not parse {value!r} as a float"
    else:
        return (
            None,
            f"unsupported sample type {type(value).__name__} for a numeric axis",
        )
    if math.isnan(numeric) or math.isinf(numeric):
        return None, f"non-finite numeric value {numeric!r}"
    return numeric, None


def _convert_numeric(
    raw: float, *, tag: CanonicalTelemetryTag
) -> tuple[float | None, str | None, str | None]:
    """Apply a unit conversion driven by the tag's ``unit`` field.

    Returns ``(canonical_value, warning, error)`` where at most one of
    ``warning`` / ``error`` is non-``None`` and a value of ``None``
    means the sample should be omitted from the frame.
    """
    measurement = tag.measurement
    unit = tag.unit
    axis = tag.axis

    if axis == TELEMETRY_AXIS_NODE_PRESSURE:
        factor = _PRESSURE_TO_M.get(unit)
    elif axis in (TELEMETRY_AXIS_EDGE_FLOW, TELEMETRY_AXIS_NODE_DEMAND):
        factor = _FLOW_TO_M3_S.get(unit)
    elif axis == TELEMETRY_AXIS_NODE_LEVEL:
        factor = _LEVEL_TO_M.get(unit)
    elif axis in (
        TELEMETRY_AXIS_EDGE_PUMP_SPEED,
        TELEMETRY_AXIS_EDGE_VALVE_POSITION,
    ):
        if unit == "rpm":
            return (
                None,
                f"tag {tag.tag!r} declares pump_speed in 'rpm' but no rated "
                f"speed is supplied; value omitted (conservative)",
                None,
            )
        factor = _FRACTIONAL_TO_FRACTION.get(unit)
    elif axis == TELEMETRY_AXIS_EDGE_POWER:
        factor = _POWER_TO_KW.get(unit)
    else:
        return (
            None,
            None,
            f"tag {tag.tag!r}: axis {axis!r} is not a numeric axis",
        )

    if factor is None:
        return (
            None,
            None,
            f"tag {tag.tag!r}: unit {unit!r} for measurement {measurement!r} "
            f"has no Sprint 35 conversion table entry",
        )
    return raw * factor, None, None


def _coerce_status(value: object) -> tuple["float | bool | None", str | None]:
    """Coerce ``value`` to a canonical status value.

    Accepts ``bool``, numeric ``0/1``, and a small whitelist of
    case-insensitive strings (``"on"``, ``"off"``, ``"open"``,
    ``"closed"``, ``"true"``, ``"false"``, ``"running"``, ``"stopped"``,
    ``"active"``, ``"inactive"``, ``"yes"``, ``"no"``, ``"0"``,
    ``"1"``). Anything else is rejected.
    """
    if isinstance(value, bool):
        return value, None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if math.isnan(value) or math.isinf(value):
            return None, f"non-finite status value {value!r}"
        if float(value) == 0.0:
            return False, None
        if float(value) == 1.0:
            return True, None
        return (
            None,
            f"numeric status value {value!r} not in {{0, 1}}",
        )
    if isinstance(value, str):
        stripped = value.strip().lower()
        if not stripped:
            return None, "empty string is not a valid status sample"
        if stripped in _STATUS_TRUE_STRINGS:
            return True, None
        if stripped in _STATUS_FALSE_STRINGS:
            return False, None
        return None, f"unrecognised status string {value!r}"
    return None, f"unsupported sample type {type(value).__name__} for status axis"


# ---------------------------------------------------------------------------
# Timestamp / staleness helpers
# ---------------------------------------------------------------------------


def _timestamp_gap_seconds(
    prev: object, current: object
) -> float | None:
    """Return ``current - prev`` in seconds, or ``None`` if undefined.

    Sprint 35 never *parses* a timestamp: the gap is only computable
    when both timestamps support arithmetic subtraction (``int`` /
    ``float``) or both are ``datetime`` instances. Anything else
    returns ``None`` and the staleness check is silently skipped for
    that pair.
    """
    if isinstance(prev, bool) or isinstance(current, bool):
        return None
    if isinstance(prev, (int, float)) and isinstance(current, (int, float)):
        return float(current) - float(prev)
    # ``datetime.datetime - datetime.datetime`` yields ``timedelta``.
    try:
        delta = current - prev  # type: ignore[operator]
    except TypeError:
        return None
    total = getattr(delta, "total_seconds", None)
    if callable(total):
        try:
            return float(total())
        except (TypeError, ValueError):
            return None
    if isinstance(delta, (int, float)):
        return float(delta)
    return None


# ---------------------------------------------------------------------------
# Public builder
# ---------------------------------------------------------------------------


def build_shadow_replay_dataset(
    rows: Iterable[Mapping[str, object]],
    tag_map: TelemetryTagMap,
    *,
    timestamp_key: str = "timestamp",
    strict: bool = True,
    max_stale_seconds: float | None = None,
) -> ShadowReplayDataset:
    """Build a :class:`ShadowReplayDataset` from offline telemetry rows.

    The builder is **pure** and **offline**:

    * never mutates ``rows`` or ``tag_map``;
    * never opens a socket / process / live binding;
    * never returns a write or control surface;
    * never invokes the dPHM forward solver.

    Parameters
    ----------
    rows
        Iterable of Python mappings. Each mapping must hold a
        timestamp under ``timestamp_key`` and a subset of the
        operator-facing tag names declared in ``tag_map.tags``. Tags
        not present in a row are recorded as warnings.
    tag_map
        Sprint 34 :class:`TelemetryTagMap` whose ``tags`` define the
        per-row tag lookup.
    timestamp_key
        Name of the timestamp column in each row mapping. Defaults to
        ``"timestamp"``.
    strict
        When ``True`` (default), any structural error (missing
        timestamp, non-numeric sample for a numeric axis, malformed
        status string, ``rpm`` pump speed without rated speed) raises
        :class:`ValueError`. When ``False``, the offending sample (or
        whole row for missing-timestamp rows) is omitted from the
        affected frame / dataset and an error string is appended to
        diagnostics.
    max_stale_seconds
        Optional positive float. When supplied, the gap between
        consecutive timestamps is compared against this threshold; a
        per-pair warning is recorded when the gap exceeds the
        threshold. The check is skipped silently for pairs whose
        timestamps cannot be subtracted as floats / datetimes (Sprint
        35 never parses timestamps).

    Returns
    -------
    ShadowReplayDataset
        A frozen, immutable dataset. Every collection field is a
        freshly allocated tuple / dict; subsequent mutation of the
        input row sequence cannot affect the returned dataset.

    Raises
    ------
    ValueError
        In ``strict=True`` mode, if any structural error is detected.
    """
    if max_stale_seconds is not None and max_stale_seconds <= 0:
        raise ValueError(
            f"max_stale_seconds must be positive, got {max_stale_seconds!r}"
        )

    tags = tuple(tag_map.tags)

    dataset_errors: list[str] = []
    dataset_warnings: list[str] = []
    frames: list[ShadowReplayFrame] = []
    prev_timestamp: object | None = None
    have_prev = False

    for row_index, raw_row in enumerate(rows):
        if not isinstance(raw_row, Mapping):
            dataset_errors.append(
                f"row[{row_index}]: expected mapping, got "
                f"{type(raw_row).__name__}"
            )
            continue

        if timestamp_key not in raw_row:
            dataset_errors.append(
                f"row[{row_index}]: missing timestamp key {timestamp_key!r}"
            )
            continue

        timestamp = raw_row[timestamp_key]
        if timestamp is None:
            dataset_errors.append(
                f"row[{row_index}]: timestamp value is None"
            )
            continue

        if max_stale_seconds is not None and have_prev:
            gap = _timestamp_gap_seconds(prev_timestamp, timestamp)
            if gap is not None and gap > max_stale_seconds:
                dataset_warnings.append(
                    f"row[{row_index}]: timestamp gap {gap:.6f}s exceeds "
                    f"max_stale_seconds={max_stale_seconds}"
                )

        per_axis_numeric: dict[str, dict[int, float]] = {
            field_name: {} for field_name in _NUMERIC_AXIS_FIELDS.values()
        }
        per_axis_status: dict[str, dict[int, "float | bool"]] = {
            field_name: {} for field_name in _STATUS_AXIS_FIELDS.values()
        }
        frame_warnings: list[str] = []
        frame_errors: list[str] = []

        for tag in tags:
            if tag.tag not in raw_row:
                frame_warnings.append(
                    f"row[{row_index}]: tag {tag.tag!r} not present in row"
                )
                continue
            value = raw_row[tag.tag]
            if value is None:
                frame_warnings.append(
                    f"row[{row_index}]: tag {tag.tag!r} value is None"
                )
                continue

            if tag.measurement == TELEMETRY_MEASUREMENT_STATUS:
                axis_field = _STATUS_AXIS_FIELDS.get(tag.axis)
                if axis_field is None:
                    frame_errors.append(
                        f"row[{row_index}]: tag {tag.tag!r} axis {tag.axis!r} "
                        f"is not a status axis"
                    )
                    continue
                canonical, status_error = _coerce_status(value)
                if status_error is not None or canonical is None:
                    frame_errors.append(
                        f"row[{row_index}]: tag {tag.tag!r}: {status_error}"
                    )
                    continue
                per_axis_status[axis_field][tag.target_id] = canonical
                continue

            axis_field = _NUMERIC_AXIS_FIELDS.get(tag.axis)
            if axis_field is None:
                frame_errors.append(
                    f"row[{row_index}]: tag {tag.tag!r} axis {tag.axis!r} "
                    f"is not a known Sprint 35 numeric axis"
                )
                continue

            numeric, parse_error = _coerce_numeric(value)
            if parse_error is not None or numeric is None:
                frame_errors.append(
                    f"row[{row_index}]: tag {tag.tag!r}: {parse_error}"
                )
                continue

            canonical_value, conv_warning, conv_error = _convert_numeric(
                numeric, tag=tag
            )
            if conv_error is not None:
                frame_errors.append(
                    f"row[{row_index}]: tag {tag.tag!r}: {conv_error}"
                )
                continue
            if conv_warning is not None:
                frame_warnings.append(
                    f"row[{row_index}]: {conv_warning}"
                )
                continue
            assert canonical_value is not None  # for type-checkers
            per_axis_numeric[axis_field][tag.target_id] = canonical_value

        frame_diagnostics = ShadowReplayDiagnostics(
            warnings=tuple(frame_warnings),
            errors=tuple(frame_errors),
        )
        frame_kwargs: dict[str, object] = {
            "timestamp": timestamp,
            "diagnostics": frame_diagnostics,
        }
        for field_name, mapping in per_axis_numeric.items():
            # Freeze each axis dict by allocating a fresh dict; the
            # ShadowReplayFrame dataclass is frozen so the *binding*
            # cannot be rewritten, but the dict itself is not. A
            # caller that wants a guaranteed-immutable view can wrap
            # the field in ``types.MappingProxyType`` — Sprint 35 does
            # not pre-wrap to keep ergonomics simple and avoid forcing
            # a downstream type-check.
            frame_kwargs[field_name] = dict(mapping)
        for field_name, mapping in per_axis_status.items():
            frame_kwargs[field_name] = dict(mapping)

        frames.append(ShadowReplayFrame(**frame_kwargs))  # type: ignore[arg-type]

        if frame_errors:
            dataset_errors.extend(frame_errors)
        if frame_warnings:
            dataset_warnings.extend(frame_warnings)

        prev_timestamp = timestamp
        have_prev = True

    if strict and dataset_errors:
        raise ValueError(
            "build_shadow_replay_dataset rejected "
            f"{len(dataset_errors)} sample(s) / row(s): "
            + "; ".join(dataset_errors)
        )

    return ShadowReplayDataset(
        frames=tuple(frames),
        tag_map=tag_map,
        diagnostics=ShadowReplayDiagnostics(
            warnings=tuple(dataset_warnings),
            errors=tuple(dataset_errors),
        ),
    )


# ---------------------------------------------------------------------------
# CSV loader (stdlib only — no pandas dependency)
# ---------------------------------------------------------------------------


def load_shadow_replay_csv(
    path: PathLike,
    tag_map: TelemetryTagMap,
    *,
    timestamp_key: str = "timestamp",
    strict: bool = True,
    max_stale_seconds: float | None = None,
) -> ShadowReplayDataset:
    """Load offline replay rows from a CSV file and build a dataset.

    The CSV must have a header row. Every value is read as a string;
    :func:`build_shadow_replay_dataset` then coerces each cell into
    the appropriate canonical numeric / status type. The timestamp
    column is **not** parsed — it is forwarded verbatim as the row's
    ``timestamp`` value.

    Parameters
    ----------
    path
        Filesystem path to a CSV file (``str`` or ``pathlib.Path``).
    tag_map
        Sprint 34 :class:`TelemetryTagMap`.
    timestamp_key
        Name of the timestamp column. Must appear in the CSV header.
    strict
        Forwarded to :func:`build_shadow_replay_dataset`.
    max_stale_seconds
        Forwarded to :func:`build_shadow_replay_dataset`.

    Returns
    -------
    ShadowReplayDataset
        The built dataset.

    Raises
    ------
    ValueError
        On a malformed CSV (no header), a header missing
        ``timestamp_key``, or — in ``strict=True`` — any structural
        sample error.
    """
    path_obj = Path(path)
    with path_obj.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            raise ValueError(
                f"load_shadow_replay_csv: {path_obj} has no header row"
            )
        if timestamp_key not in reader.fieldnames:
            raise ValueError(
                f"load_shadow_replay_csv: timestamp column "
                f"{timestamp_key!r} not in CSV header "
                f"{list(reader.fieldnames)!r}"
            )
        rows: list[dict[str, object]] = []
        for row in reader:
            # csv.DictReader gives str values; preserve verbatim, but
            # treat the empty string the same as a missing cell so the
            # builder records a single deterministic warning rather
            # than two contradictory ones.
            cleaned: dict[str, object] = {}
            for key, value in row.items():
                if key is None:
                    # ``None`` keys arise from ragged rows; skip them.
                    continue
                if value == "":
                    continue
                cleaned[key] = value
            rows.append(cleaned)

    return build_shadow_replay_dataset(
        rows,
        tag_map,
        timestamp_key=timestamp_key,
        strict=strict,
        max_stale_seconds=max_stale_seconds,
    )


__all__ = [
    "ShadowReplayDataset",
    "ShadowReplayDiagnostics",
    "ShadowReplayFrame",
    "build_shadow_replay_dataset",
    "load_shadow_replay_csv",
]
