"""dPL calibration loss prototype (Sprint 36).

Sprint 36 closes the offline / read-only loop opened by Sprints 34
and 35: it consumes a :class:`ShadowReplayDataset` (the Sprint 35
canonicalised offline frames) and a per-frame predictions sequence
keyed by canonical dPHM axis and id, and emits a frozen
:class:`DPLCalibrationLossReport` that carries the per-observation
residuals, the per-axis MSE / MAE, and a deterministic weighted MSE
suitable as a calibration loss term for a future dPL training loop.

This module is **read-only / offline only**. It contains:

* :class:`DPLCalibrationDiagnostics` — deterministic warnings /
  errors tuples.
* :class:`DPLResidual` — single per-observation residual record.
* :class:`DPLCalibrationLossReport` — frozen top-level container.
* :func:`build_dpl_calibration_loss_report` — pure builder over a
  :class:`ShadowReplayDataset` and a per-frame predictions sequence.

Safety boundary (reaffirmed verbatim per Sprints 23-35):

* no live SCADA / PLC / PAC / historian / OPC-UA / MQTT / REST
  adapter;
* no write / control / setpoint path;
* no advisory / control recommendation surface;
* no training loop / optimizer integration beyond deterministic loss
  reporting;
* no automatic setpoint recommendation;
* no ONNX / TensorRT / Jetson deployment;
* no production savings / control claim.

Sprint 36 only *measures* the disagreement between supplied
predictions and the Sprint 35 offline observations; it never invokes
the dPHM forward solver, never opens a live binding, and never emits
control output. A future dPL training loop would consume the
returned residuals / weighted MSE through its own loss API; that
training loop is **out of scope** for Sprint 36.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from .shadow_replay import ShadowReplayDataset, ShadowReplayFrame
from .telemetry_tag_map import (
    TELEMETRY_AXIS_EDGE_FLOW,
    TELEMETRY_AXIS_EDGE_POWER,
    TELEMETRY_AXIS_EDGE_PUMP_SPEED,
    TELEMETRY_AXIS_EDGE_STATUS,
    TELEMETRY_AXIS_EDGE_VALVE_POSITION,
    TELEMETRY_AXIS_NODE_DEMAND,
    TELEMETRY_AXIS_NODE_LEVEL,
    TELEMETRY_AXIS_NODE_PRESSURE,
    TELEMETRY_AXIS_NODE_STATUS,
)


# ---------------------------------------------------------------------------
# Axis tables (kept in a fixed deterministic order)
# ---------------------------------------------------------------------------


# Numeric axes (residual = predicted - observed, float arithmetic).
DPL_NUMERIC_AXES: tuple[str, ...] = (
    TELEMETRY_AXIS_NODE_PRESSURE,
    TELEMETRY_AXIS_NODE_DEMAND,
    TELEMETRY_AXIS_NODE_LEVEL,
    TELEMETRY_AXIS_EDGE_FLOW,
    TELEMETRY_AXIS_EDGE_PUMP_SPEED,
    TELEMETRY_AXIS_EDGE_POWER,
    TELEMETRY_AXIS_EDGE_VALVE_POSITION,
)

# Status axes (bool / 0|1 → coerced to 0.0 / 1.0 before residual math).
DPL_STATUS_AXES: tuple[str, ...] = (
    TELEMETRY_AXIS_NODE_STATUS,
    TELEMETRY_AXIS_EDGE_STATUS,
)

# Full deterministic axis order used everywhere the report sorts axes.
DPL_AXES: tuple[str, ...] = DPL_NUMERIC_AXES + DPL_STATUS_AXES

_FRAME_FIELD_BY_AXIS: Mapping[str, str] = {
    TELEMETRY_AXIS_NODE_PRESSURE: "node_pressure",
    TELEMETRY_AXIS_NODE_DEMAND: "node_demand",
    TELEMETRY_AXIS_NODE_LEVEL: "node_level",
    TELEMETRY_AXIS_NODE_STATUS: "node_status",
    TELEMETRY_AXIS_EDGE_FLOW: "edge_flow",
    TELEMETRY_AXIS_EDGE_PUMP_SPEED: "edge_pump_speed",
    TELEMETRY_AXIS_EDGE_STATUS: "edge_status",
    TELEMETRY_AXIS_EDGE_POWER: "edge_power",
    TELEMETRY_AXIS_EDGE_VALVE_POSITION: "edge_valve_position",
}


# ---------------------------------------------------------------------------
# Frozen dataclass surface
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DPLCalibrationDiagnostics:
    """Deterministic warnings / errors tuples for a calibration build.

    Both tuples are empty for a fully-matched input. Warnings are
    non-fatal observations (extra prediction with no observed value,
    unsupported prediction axis); errors are structural problems
    (missing prediction for an observed value when not strict,
    prediction sequence length mismatch when not strict, malformed
    bool / numeric prediction value).

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
class DPLResidual:
    """Single per-observation residual record.

    Carries enough metadata to reconstruct the (frame, axis, target)
    location of the residual without consulting the originating
    dataset. ``residual = predicted - observed``; ``weight`` is the
    axis weight (defaults to ``1.0``) and is used by the report's
    :attr:`DPLCalibrationLossReport.weighted_mse`.

    Attributes
    ----------
    frame_index
        Zero-based index into ``replay.frames``.
    timestamp
        Whatever timestamp object the originating
        :class:`ShadowReplayFrame` carried — forwarded verbatim.
    axis
        Canonical dPHM axis token (e.g. ``"node_pressure"``).
    target_id
        Zero-based dPHM node / edge id (the same id used by
        :class:`ShadowReplayFrame`).
    observed
        Canonical observed value (in the Sprint 35 canonical unit).
        Status bool observations are coerced to ``0.0`` / ``1.0``.
    predicted
        Canonical predicted value (caller-supplied; must already be
        in the same canonical unit as ``observed``).
    residual
        ``predicted - observed``.
    weight
        Per-axis weight applied to this residual in the weighted MSE.
        Defaults to ``1.0`` when no weight is supplied for the axis.
    """

    frame_index: int
    timestamp: object
    axis: str
    target_id: int
    observed: float
    predicted: float
    residual: float
    weight: float = 1.0


@dataclass(frozen=True)
class DPLCalibrationLossReport:
    """Frozen calibration-loss report.

    Returned by :func:`build_dpl_calibration_loss_report`. The
    ``residuals`` tuple is in *deterministic* order: outer key is the
    frame index, middle key is the canonical axis order
    (:data:`DPL_AXES`), inner key is the ascending ``target_id``.

    Attributes
    ----------
    residuals
        Tuple of :class:`DPLResidual` records.
    mse_by_axis
        Mean squared error per axis, restricted to axes that actually
        produced at least one residual. ``residual ** 2`` averaged
        over the residual count for that axis.
    mae_by_axis
        Mean absolute error per axis, restricted to axes that actually
        produced at least one residual.
    weighted_mse
        Deterministic weighted mean of ``residual ** 2`` over all
        residuals; each ``residual ** 2`` is multiplied by its axis
        weight before averaging by ``sum(weights)``. When no
        residuals are produced, ``weighted_mse`` is ``0.0``.
    observation_count
        Number of residuals in :attr:`residuals`.
    diagnostics
        Build-level :class:`DPLCalibrationDiagnostics`.
    """

    residuals: tuple[DPLResidual, ...] = ()
    mse_by_axis: Mapping[str, float] = field(default_factory=dict)
    mae_by_axis: Mapping[str, float] = field(default_factory=dict)
    weighted_mse: float = 0.0
    observation_count: int = 0
    diagnostics: DPLCalibrationDiagnostics = field(
        default_factory=DPLCalibrationDiagnostics
    )


# ---------------------------------------------------------------------------
# Coercion helpers
# ---------------------------------------------------------------------------


def _coerce_observed_numeric(value: object) -> float | None:
    """Coerce an observed numeric value into a finite float.

    The Sprint 35 builder already produces finite floats for numeric
    axes, but the helper exists so a future caller (or a hand-built
    test frame) cannot smuggle a NaN through the report surface.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        numeric = float(value)
        if math.isnan(numeric) or math.isinf(numeric):
            return None
        return numeric
    return None


def _coerce_status(value: object) -> float | None:
    """Coerce a status sample (``bool`` / ``0|1``) into 0.0 or 1.0."""
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        numeric = float(value)
        if math.isnan(numeric) or math.isinf(numeric):
            return None
        if numeric == 0.0:
            return 0.0
        if numeric == 1.0:
            return 1.0
        return None
    return None


def _coerce_predicted(value: object, *, is_status: bool) -> float | None:
    """Coerce a supplied predicted sample.

    Status axes accept ``bool`` / ``0|1`` (coerced to 0.0 / 1.0);
    numeric axes accept ``int`` / ``float`` (finite). Anything else
    is rejected.
    """
    if is_status:
        return _coerce_status(value)
    return _coerce_observed_numeric(value)


# ---------------------------------------------------------------------------
# Axis weight validation
# ---------------------------------------------------------------------------


def _validate_axis_weights(
    axis_weights: Mapping[str, float] | None,
) -> dict[str, float]:
    """Validate and return a copy of the axis-weights mapping.

    Rejects negative, zero, or non-finite weights, and rejects axes
    not in :data:`DPL_AXES`. Returns a freshly allocated ``dict`` so
    the caller's mapping is never aliased.
    """
    if axis_weights is None:
        return {}
    if not isinstance(axis_weights, Mapping):
        raise ValueError(
            f"axis_weights must be a Mapping, got {type(axis_weights).__name__}"
        )
    cleaned: dict[str, float] = {}
    for axis, weight in axis_weights.items():
        if axis not in DPL_AXES:
            raise ValueError(
                f"axis_weights: axis {axis!r} is not a recognised dPL "
                f"calibration axis; expected one of {list(DPL_AXES)!r}"
            )
        if isinstance(weight, bool) or not isinstance(weight, (int, float)):
            raise ValueError(
                f"axis_weights: weight for {axis!r} must be a finite "
                f"positive number, got {weight!r}"
            )
        numeric = float(weight)
        if math.isnan(numeric) or math.isinf(numeric):
            raise ValueError(
                f"axis_weights: weight for {axis!r} must be finite, got "
                f"{numeric!r}"
            )
        if numeric <= 0.0:
            raise ValueError(
                f"axis_weights: weight for {axis!r} must be strictly "
                f"positive, got {numeric!r}"
            )
        cleaned[axis] = numeric
    return cleaned


def _weight_for(
    axis: str, axis_weights: Mapping[str, float]
) -> float:
    """Return the axis weight, defaulting to ``1.0`` when absent."""
    return float(axis_weights.get(axis, 1.0))


# ---------------------------------------------------------------------------
# Public builder
# ---------------------------------------------------------------------------


def build_dpl_calibration_loss_report(
    replay: ShadowReplayDataset,
    predictions: Sequence[Mapping[str, Mapping[int, float]]],
    *,
    axis_weights: Mapping[str, float] | None = None,
    strict: bool = True,
) -> DPLCalibrationLossReport:
    """Build a :class:`DPLCalibrationLossReport` from replay + predictions.

    The builder is **pure** and **offline**:

    * never mutates ``replay`` or ``predictions``;
    * never opens a socket / process / live binding;
    * never returns a write or control surface;
    * never invokes the dPHM forward solver.

    Parameters
    ----------
    replay
        Sprint 35 :class:`ShadowReplayDataset` whose frames carry the
        canonicalised observation maps.
    predictions
        Sequence of mappings — one per replay frame, in the same
        order. Each entry maps an axis token (e.g. ``"node_pressure"``)
        to a ``{target_id: value}`` sub-mapping carrying the supplied
        predicted values in the *same canonical units* as the
        observations.
    axis_weights
        Optional ``{axis: weight}`` mapping. Missing axes default to
        ``1.0``. Negative, zero, non-finite, or unknown-axis weights
        always raise :class:`ValueError` (this is a programmer error
        and is *not* gated by ``strict``).
    strict
        When ``True`` (default), structural mismatches between
        predictions and observations raise :class:`ValueError`:

        * ``len(predictions) != len(replay.frames)``;
        * a predicted value is missing for an observed
          ``(axis, target_id)``;
        * a supplied predicted value is non-finite, the wrong type
          for the axis, or otherwise uncoercible;
        * a supplied prediction names an axis that is not in
          :data:`DPL_AXES`.

        When ``False``, the offending residual is omitted and the
        error string is appended to
        :attr:`DPLCalibrationDiagnostics.errors`.

        Extra predictions that do not match an observation are always
        a *warning* (in both strict and non-strict mode); they never
        raise.

    Returns
    -------
    DPLCalibrationLossReport
        Frozen, immutable report. The ``residuals`` tuple is in a
        deterministic order: frame index, then
        :data:`DPL_AXES` order, then ascending ``target_id``.

    Raises
    ------
    ValueError
        See ``strict`` and ``axis_weights`` above. The empty-replay
        case is *not* an error in either mode — it returns an empty
        report with empty diagnostics.
    """
    if not isinstance(replay, ShadowReplayDataset):
        raise ValueError(
            f"replay must be a ShadowReplayDataset, got {type(replay).__name__}"
        )

    weights = _validate_axis_weights(axis_weights)

    # Materialise predictions to a list so we can index by frame.
    if isinstance(predictions, (str, bytes)):
        raise ValueError(
            "predictions must be a sequence of mappings, not a string"
        )
    if not isinstance(predictions, Sequence):
        # Best-effort defensive check: a generator would silently
        # collapse after the first pass which would make
        # determinism / re-runs unsafe.
        raise ValueError(
            "predictions must be a Sequence (list, tuple, etc.); got "
            f"{type(predictions).__name__}"
        )
    predictions_list: list[Mapping[str, Mapping[int, float]]] = list(predictions)

    frames: tuple[ShadowReplayFrame, ...] = tuple(replay.frames)

    warnings: list[str] = []
    errors: list[str] = []

    length_mismatch_msg: str | None = None
    if len(predictions_list) != len(frames):
        length_mismatch_msg = (
            f"predictions length {len(predictions_list)} does not match "
            f"replay frame count {len(frames)}"
        )

    if length_mismatch_msg is not None:
        if strict:
            raise ValueError(length_mismatch_msg)
        errors.append(length_mismatch_msg)

    paired_count = min(len(predictions_list), len(frames))

    residuals: list[DPLResidual] = []

    # Track which axes / target ids we have observed values for in a
    # given frame so we can emit warnings for *extra* predictions
    # deterministically.
    for frame_index in range(paired_count):
        frame = frames[frame_index]
        prediction = predictions_list[frame_index]

        if not isinstance(prediction, Mapping):
            msg = (
                f"predictions[{frame_index}]: expected Mapping, got "
                f"{type(prediction).__name__}"
            )
            if strict:
                raise ValueError(msg)
            errors.append(msg)
            continue

        # Per-frame observation set, in canonical axis order.
        observed_seen: set[tuple[str, int]] = set()

        for axis in DPL_AXES:
            field_name = _FRAME_FIELD_BY_AXIS[axis]
            observed_map = getattr(frame, field_name)
            if not observed_map:
                continue

            is_status = axis in DPL_STATUS_AXES
            predicted_map = prediction.get(axis, {})
            if predicted_map is None:
                predicted_map = {}
            if not isinstance(predicted_map, Mapping):
                msg = (
                    f"predictions[{frame_index}][{axis!r}]: expected "
                    f"Mapping[int, value], got "
                    f"{type(predicted_map).__name__}"
                )
                if strict:
                    raise ValueError(msg)
                errors.append(msg)
                continue

            for target_id in sorted(observed_map.keys()):
                observed_raw = observed_map[target_id]
                if is_status:
                    observed_value = _coerce_status(observed_raw)
                else:
                    observed_value = _coerce_observed_numeric(observed_raw)
                if observed_value is None:
                    msg = (
                        f"frame[{frame_index}] axis {axis!r} target "
                        f"{target_id}: observed value {observed_raw!r} "
                        f"is not coercible to a finite numeric"
                    )
                    if strict:
                        raise ValueError(msg)
                    errors.append(msg)
                    continue

                observed_seen.add((axis, target_id))
                if target_id not in predicted_map:
                    msg = (
                        f"frame[{frame_index}] axis {axis!r} target "
                        f"{target_id}: no prediction supplied"
                    )
                    if strict:
                        raise ValueError(msg)
                    errors.append(msg)
                    continue

                predicted_raw = predicted_map[target_id]
                predicted_value = _coerce_predicted(
                    predicted_raw, is_status=is_status
                )
                if predicted_value is None:
                    msg = (
                        f"frame[{frame_index}] axis {axis!r} target "
                        f"{target_id}: predicted value {predicted_raw!r} "
                        f"is not coercible (axis is "
                        f"{'status' if is_status else 'numeric'})"
                    )
                    if strict:
                        raise ValueError(msg)
                    errors.append(msg)
                    continue

                residual = predicted_value - observed_value
                weight = _weight_for(axis, weights)
                residuals.append(
                    DPLResidual(
                        frame_index=frame_index,
                        timestamp=frame.timestamp,
                        axis=axis,
                        target_id=int(target_id),
                        observed=observed_value,
                        predicted=predicted_value,
                        residual=residual,
                        weight=weight,
                    )
                )

        # Extra predictions → warnings (deterministic ordering: axis
        # order from DPL_AXES, then ascending target_id; unknown
        # axes are appended last in sorted order).
        for axis in DPL_AXES:
            predicted_map = prediction.get(axis, {})
            if not isinstance(predicted_map, Mapping):
                continue
            for target_id in sorted(predicted_map.keys()):
                if (axis, int(target_id)) in observed_seen:
                    continue
                warnings.append(
                    f"frame[{frame_index}] axis {axis!r} target "
                    f"{int(target_id)}: prediction supplied but no "
                    f"observed value present; residual omitted"
                )

        # Predictions naming axes outside DPL_AXES are also warnings.
        for axis in sorted(prediction.keys()):
            if axis in DPL_AXES:
                continue
            warnings.append(
                f"frame[{frame_index}]: prediction names unsupported "
                f"axis {axis!r}; ignored"
            )

    # Aggregate MSE / MAE per axis (deterministic — DPL_AXES order).
    sum_sq_by_axis: dict[str, float] = {}
    sum_abs_by_axis: dict[str, float] = {}
    count_by_axis: dict[str, int] = {}
    sum_weighted_sq = 0.0
    sum_weights = 0.0
    for r in residuals:
        sum_sq_by_axis[r.axis] = sum_sq_by_axis.get(r.axis, 0.0) + r.residual ** 2
        sum_abs_by_axis[r.axis] = sum_abs_by_axis.get(r.axis, 0.0) + abs(r.residual)
        count_by_axis[r.axis] = count_by_axis.get(r.axis, 0) + 1
        sum_weighted_sq += r.weight * r.residual ** 2
        sum_weights += r.weight

    mse_by_axis: dict[str, float] = {}
    mae_by_axis: dict[str, float] = {}
    for axis in DPL_AXES:
        n = count_by_axis.get(axis, 0)
        if n == 0:
            continue
        mse_by_axis[axis] = sum_sq_by_axis[axis] / n
        mae_by_axis[axis] = sum_abs_by_axis[axis] / n

    if sum_weights > 0.0:
        weighted_mse = sum_weighted_sq / sum_weights
    else:
        weighted_mse = 0.0

    diagnostics = DPLCalibrationDiagnostics(
        warnings=tuple(warnings),
        errors=tuple(errors),
    )
    return DPLCalibrationLossReport(
        residuals=tuple(residuals),
        mse_by_axis=mse_by_axis,
        mae_by_axis=mae_by_axis,
        weighted_mse=weighted_mse,
        observation_count=len(residuals),
        diagnostics=diagnostics,
    )


__all__ = [
    "DPL_AXES",
    "DPL_NUMERIC_AXES",
    "DPL_STATUS_AXES",
    "DPLCalibrationDiagnostics",
    "DPLCalibrationLossReport",
    "DPLResidual",
    "build_dpl_calibration_loss_report",
]
