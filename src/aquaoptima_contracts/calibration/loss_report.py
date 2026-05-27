"""``DPLCalibrationLossReport`` SDK projection (Sprint 43).

These types capture the *shape* of the Phase 1 Sprint 36 dPL
calibration loss report. The Phase 1 module
``aquaoptima.dphm.dpl_calibration`` continues to own
``build_dpl_calibration_loss_report`` and the actual residual /
MSE / MAE math.

The SDK projection is audit-only: it models the per-observation
residual records and per-axis loss summary that downstream
consumers (Operations Console, AI/Optimization Server, audit
harnesses) need to display a calibration report. No advisory
field, no setpoint, no command, no write field is modeled here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from ..base.envelope import ContractError
from ..telemetry.axis import CANONICAL_TELEMETRY_AXES


_RESIDUAL_FIELDS: tuple[str, ...] = (
    "frame_index",
    "timestamp",
    "axis",
    "target_id",
    "observed",
    "predicted",
    "residual",
    "weight",
)


_SUMMARY_FIELDS: tuple[str, ...] = (
    "weighted_mse",
    "mse_by_axis",
    "mae_by_axis",
    "observation_count",
)


_REPORT_FIELDS: tuple[str, ...] = (
    "residuals",
    "summary",
    "diagnostics",
)


def _ensure_finite_float(value: object, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(
            f"{label} must be a finite float, got {type(value).__name__}"
        )
    numeric = float(value)
    if math.isnan(numeric) or math.isinf(numeric):
        raise ContractError(f"{label} must be finite, got {value!r}")
    return numeric


def _ensure_non_negative_finite_float(value: object, *, label: str) -> float:
    numeric = _ensure_finite_float(value, label=label)
    if numeric < 0.0:
        raise ContractError(f"{label} must be non-negative, got {numeric}")
    return numeric


def _ensure_positive_finite_weight(value: object, *, label: str) -> float:
    numeric = _ensure_finite_float(value, label=label)
    if numeric < 0.0:
        raise ContractError(f"{label} must be non-negative, got {numeric}")
    return numeric


def _validate_axis_float_map(
    raw: object, *, label: str
) -> dict[str, float]:
    if not isinstance(raw, Mapping):
        raise ContractError(f"{label} must be a mapping")
    out: dict[str, float] = {}
    for axis, value in raw.items():
        if not isinstance(axis, str):
            raise ContractError(f"{label} keys must be strings")
        if axis not in CANONICAL_TELEMETRY_AXES:
            raise ContractError(f"{label} contains unknown axis {axis!r}")
        numeric = _ensure_non_negative_finite_float(
            value, label=f"{label}[{axis!r}]"
        )
        out[axis] = numeric
    return out


@dataclass(frozen=True)
class DPLResidual:
    """SDK per-observation residual record."""

    frame_index: int
    timestamp: str
    axis: str
    target_id: int
    observed: float
    predicted: float
    residual: float
    weight: float = 1.0

    def __post_init__(self) -> None:
        if isinstance(self.frame_index, bool) or not isinstance(
            self.frame_index, int
        ):
            raise ContractError("DPLResidual.frame_index must be int")
        if self.frame_index < 0:
            raise ContractError(
                "DPLResidual.frame_index must be non-negative"
            )
        if not isinstance(self.timestamp, str) or not self.timestamp:
            raise ContractError(
                "DPLResidual.timestamp must be a non-empty string"
            )
        if not isinstance(self.axis, str):
            raise ContractError("DPLResidual.axis must be a string")
        if self.axis not in CANONICAL_TELEMETRY_AXES:
            raise ContractError(
                f"DPLResidual.axis {self.axis!r} is not a canonical "
                f"telemetry axis; allowed: {sorted(CANONICAL_TELEMETRY_AXES)}"
            )
        if isinstance(self.target_id, bool) or not isinstance(
            self.target_id, int
        ):
            raise ContractError("DPLResidual.target_id must be int")
        if self.target_id < 0:
            raise ContractError(
                "DPLResidual.target_id must be non-negative"
            )
        observed = _ensure_finite_float(
            self.observed, label="DPLResidual.observed"
        )
        predicted = _ensure_finite_float(
            self.predicted, label="DPLResidual.predicted"
        )
        residual = _ensure_finite_float(
            self.residual, label="DPLResidual.residual"
        )
        weight = _ensure_positive_finite_weight(
            self.weight, label="DPLResidual.weight"
        )
        object.__setattr__(self, "observed", observed)
        object.__setattr__(self, "predicted", predicted)
        object.__setattr__(self, "residual", residual)
        object.__setattr__(self, "weight", weight)

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame_index": self.frame_index,
            "timestamp": self.timestamp,
            "axis": self.axis,
            "target_id": self.target_id,
            "observed": self.observed,
            "predicted": self.predicted,
            "residual": self.residual,
            "weight": self.weight,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DPLResidual":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"DPLResidual.from_dict requires a mapping, got "
                f"{type(data).__name__}"
            )
        missing = {
            "frame_index",
            "timestamp",
            "axis",
            "target_id",
            "observed",
            "predicted",
            "residual",
        } - set(data.keys())
        if missing:
            raise ContractError(
                f"DPLResidual missing fields: {sorted(missing)}"
            )
        unknown = set(data.keys()) - set(_RESIDUAL_FIELDS)
        if unknown:
            raise ContractError(
                f"DPLResidual received unknown fields: {sorted(unknown)}"
            )
        return cls(
            frame_index=int(data["frame_index"]),
            timestamp=str(data["timestamp"]),
            axis=str(data["axis"]),
            target_id=int(data["target_id"]),
            observed=float(data["observed"]),
            predicted=float(data["predicted"]),
            residual=float(data["residual"]),
            weight=float(data.get("weight", 1.0)),
        )


@dataclass(frozen=True)
class CalibrationLossSummary:
    """Weighted MSE plus per-axis MSE / MAE summary."""

    weighted_mse: float = 0.0
    mse_by_axis: Mapping[str, float] = field(default_factory=dict)
    mae_by_axis: Mapping[str, float] = field(default_factory=dict)
    observation_count: int = 0

    def __post_init__(self) -> None:
        weighted = _ensure_non_negative_finite_float(
            self.weighted_mse, label="CalibrationLossSummary.weighted_mse"
        )
        object.__setattr__(self, "weighted_mse", weighted)
        object.__setattr__(
            self,
            "mse_by_axis",
            _validate_axis_float_map(
                self.mse_by_axis,
                label="CalibrationLossSummary.mse_by_axis",
            ),
        )
        object.__setattr__(
            self,
            "mae_by_axis",
            _validate_axis_float_map(
                self.mae_by_axis,
                label="CalibrationLossSummary.mae_by_axis",
            ),
        )
        if isinstance(self.observation_count, bool) or not isinstance(
            self.observation_count, int
        ):
            raise ContractError(
                "CalibrationLossSummary.observation_count must be int"
            )
        if self.observation_count < 0:
            raise ContractError(
                "CalibrationLossSummary.observation_count must be non-negative"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "weighted_mse": self.weighted_mse,
            "mse_by_axis": dict(self.mse_by_axis),
            "mae_by_axis": dict(self.mae_by_axis),
            "observation_count": self.observation_count,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CalibrationLossSummary":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"CalibrationLossSummary.from_dict requires a mapping, got "
                f"{type(data).__name__}"
            )
        unknown = set(data.keys()) - set(_SUMMARY_FIELDS)
        if unknown:
            raise ContractError(
                f"CalibrationLossSummary received unknown fields: "
                f"{sorted(unknown)}"
            )
        return cls(
            weighted_mse=float(data.get("weighted_mse", 0.0)),
            mse_by_axis=dict(data.get("mse_by_axis", {}) or {}),
            mae_by_axis=dict(data.get("mae_by_axis", {}) or {}),
            observation_count=int(data.get("observation_count", 0)),
        )


@dataclass(frozen=True)
class DPLCalibrationDiagnostics:
    """Deterministic warnings / errors tuples for the calibration report."""

    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("warnings", "errors"):
            value = getattr(self, name)
            if not isinstance(value, tuple) or not all(
                isinstance(v, str) for v in value
            ):
                raise ContractError(
                    f"DPLCalibrationDiagnostics.{name} must be a tuple of strings"
                )

    def to_dict(self) -> dict[str, list[str]]:
        return {
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }

    @classmethod
    def from_dict(
        cls, data: Mapping[str, Any]
    ) -> "DPLCalibrationDiagnostics":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"DPLCalibrationDiagnostics.from_dict requires a mapping, got "
                f"{type(data).__name__}"
            )
        unknown = set(data.keys()) - {"warnings", "errors"}
        if unknown:
            raise ContractError(
                f"DPLCalibrationDiagnostics received unknown fields: "
                f"{sorted(unknown)}"
            )
        return cls(
            warnings=tuple(str(w) for w in data.get("warnings", ())),
            errors=tuple(str(e) for e in data.get("errors", ())),
        )


@dataclass(frozen=True)
class DPLCalibrationLossReport:
    """Frozen SDK projection of a Phase 1 dPL calibration loss report."""

    residuals: tuple[DPLResidual, ...] = ()
    summary: CalibrationLossSummary = field(
        default_factory=CalibrationLossSummary
    )
    diagnostics: DPLCalibrationDiagnostics = field(
        default_factory=DPLCalibrationDiagnostics
    )

    def __post_init__(self) -> None:
        if not isinstance(self.residuals, tuple):
            raise ContractError(
                "DPLCalibrationLossReport.residuals must be a tuple"
            )
        for residual in self.residuals:
            if not isinstance(residual, DPLResidual):
                raise ContractError(
                    "DPLCalibrationLossReport.residuals entries must be "
                    "DPLResidual instances"
                )
        if not isinstance(self.summary, CalibrationLossSummary):
            raise ContractError(
                "DPLCalibrationLossReport.summary must be a "
                "CalibrationLossSummary instance"
            )
        if not isinstance(self.diagnostics, DPLCalibrationDiagnostics):
            raise ContractError(
                "DPLCalibrationLossReport.diagnostics must be a "
                "DPLCalibrationDiagnostics instance"
            )
        if self.summary.observation_count != len(self.residuals):
            raise ContractError(
                f"DPLCalibrationLossReport.summary.observation_count "
                f"{self.summary.observation_count} does not match "
                f"len(residuals)={len(self.residuals)}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "residuals": [r.to_dict() for r in self.residuals],
            "summary": self.summary.to_dict(),
            "diagnostics": self.diagnostics.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DPLCalibrationLossReport":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"DPLCalibrationLossReport.from_dict requires a mapping, got "
                f"{type(data).__name__}"
            )
        unknown = set(data.keys()) - set(_REPORT_FIELDS)
        if unknown:
            raise ContractError(
                f"DPLCalibrationLossReport received unknown fields: "
                f"{sorted(unknown)}"
            )
        raw_residuals = data.get("residuals", ())
        if not isinstance(raw_residuals, Sequence) or isinstance(
            raw_residuals, (str, bytes)
        ):
            raise ContractError(
                "DPLCalibrationLossReport.residuals must be a sequence"
            )
        residuals = tuple(
            DPLResidual.from_dict(r) for r in raw_residuals
        )
        return cls(
            residuals=residuals,
            summary=CalibrationLossSummary.from_dict(
                data.get("summary", {}) or {}
            ),
            diagnostics=DPLCalibrationDiagnostics.from_dict(
                data.get("diagnostics", {}) or {}
            ),
        )


# ---------------------------------------------------------------------------
# Phase 1 projection adapter
# ---------------------------------------------------------------------------


def project_phase1_dpl_calibration_loss_report(
    phase1_report: Any,
) -> DPLCalibrationLossReport:
    """Project a Phase 1 dPL calibration loss report into the SDK shape.

    Duck-typed: the adapter only reads the documented attributes
    (``residuals``, ``mse_by_axis``, ``mae_by_axis``, ``weighted_mse``,
    ``observation_count``, ``diagnostics``) and does not import
    ``aquaoptima.*`` from inside the SDK package code, preserving the
    no-runtime-dependency boundary.

    The supplied object is never mutated. The SDK report's deterministic
    JSON shape is the only output surface.
    """

    residuals_attr = getattr(phase1_report, "residuals", ())
    summary_mse = getattr(phase1_report, "mse_by_axis", {}) or {}
    summary_mae = getattr(phase1_report, "mae_by_axis", {}) or {}
    weighted_mse = getattr(phase1_report, "weighted_mse", 0.0)
    observation_count = getattr(phase1_report, "observation_count", None)
    diagnostics_attr = getattr(phase1_report, "diagnostics", None)

    projected_residuals: list[DPLResidual] = []
    for r in residuals_attr:
        timestamp_raw = getattr(r, "timestamp", None)
        timestamp_str = (
            str(timestamp_raw)
            if timestamp_raw is not None and timestamp_raw != ""
            else "0"
        )
        projected_residuals.append(
            DPLResidual(
                frame_index=int(getattr(r, "frame_index")),
                timestamp=timestamp_str,
                axis=str(getattr(r, "axis")),
                target_id=int(getattr(r, "target_id")),
                observed=float(getattr(r, "observed")),
                predicted=float(getattr(r, "predicted")),
                residual=float(getattr(r, "residual")),
                weight=float(getattr(r, "weight", 1.0)),
            )
        )

    if observation_count is None:
        observation_count = len(projected_residuals)

    summary = CalibrationLossSummary(
        weighted_mse=float(weighted_mse),
        mse_by_axis={str(k): float(v) for k, v in summary_mse.items()},
        mae_by_axis={str(k): float(v) for k, v in summary_mae.items()},
        observation_count=int(observation_count),
    )

    if diagnostics_attr is None:
        diagnostics = DPLCalibrationDiagnostics()
    else:
        diagnostics = DPLCalibrationDiagnostics(
            warnings=tuple(
                str(w) for w in getattr(diagnostics_attr, "warnings", ())
            ),
            errors=tuple(
                str(e) for e in getattr(diagnostics_attr, "errors", ())
            ),
        )

    return DPLCalibrationLossReport(
        residuals=tuple(projected_residuals),
        summary=summary,
        diagnostics=diagnostics,
    )


__all__ = [
    "CalibrationLossSummary",
    "DPLCalibrationDiagnostics",
    "DPLCalibrationLossReport",
    "DPLResidual",
    "project_phase1_dpl_calibration_loss_report",
]
