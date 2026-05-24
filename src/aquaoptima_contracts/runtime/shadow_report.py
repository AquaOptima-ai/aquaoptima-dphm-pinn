"""``ShadowRuntimeReport`` SDK projection (Sprint 42).

These types capture the *shape* of the Phase 1 Sprint 38 shadow
runtime report. The Phase 1 module ``aquaoptima.dphm.shadow_runtime``
continues to own ``run_shadow_runtime`` and the actual residual /
advisory math.

The SDK projection is audit-only: it models the canonical axis
observation / prediction counts and per-axis MSE / MAE summaries
that downstream consumers (Operations Console, audit harnesses)
need to display a runtime report. No advisory rule body, no
setpoint, no command, no write field is modeled here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from ..base.envelope import ContractError
from ..telemetry.axis import CANONICAL_TELEMETRY_AXES


_STEP_FIELDS: tuple[str, ...] = (
    "frame_index",
    "timestamp",
    "observation_counts",
    "prediction_axes",
    "prediction_counts",
    "observation_count",
    "mse_by_axis",
    "mae_by_axis",
    "accepted_count",
    "rejected_count",
)


_REPORT_FIELDS: tuple[str, ...] = (
    "steps",
    "frame_count",
    "observation_count",
    "proposal_count",
    "accepted_count",
    "rejected_count",
    "diagnostics",
)


def _validate_axis_count_map(
    raw: object, *, label: str
) -> dict[str, int]:
    if not isinstance(raw, Mapping):
        raise ContractError(f"{label} must be a mapping")
    out: dict[str, int] = {}
    for axis, value in raw.items():
        if axis not in CANONICAL_TELEMETRY_AXES:
            raise ContractError(
                f"{label} contains unknown axis {axis!r}"
            )
        if isinstance(value, bool) or not isinstance(value, int):
            raise ContractError(
                f"{label}[{axis!r}] must be int, got {type(value).__name__}"
            )
        if value < 0:
            raise ContractError(
                f"{label}[{axis!r}] must be non-negative, got {value}"
            )
        out[axis] = value
    return out


def _validate_axis_float_map(
    raw: object, *, label: str
) -> dict[str, float]:
    if not isinstance(raw, Mapping):
        raise ContractError(f"{label} must be a mapping")
    out: dict[str, float] = {}
    for axis, value in raw.items():
        if axis not in CANONICAL_TELEMETRY_AXES:
            raise ContractError(
                f"{label} contains unknown axis {axis!r}"
            )
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ContractError(
                f"{label}[{axis!r}] must be a finite float, got "
                f"{type(value).__name__}"
            )
        out[axis] = float(value)
    return out


@dataclass(frozen=True)
class ShadowRuntimeDiagnostics:
    """Deterministic warnings / errors tuples for the SDK runtime report."""

    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("warnings", "errors"):
            value = getattr(self, name)
            if not isinstance(value, tuple) or not all(
                isinstance(v, str) for v in value
            ):
                raise ContractError(
                    f"ShadowRuntimeDiagnostics.{name} must be a tuple of strings"
                )

    def to_dict(self) -> dict[str, list[str]]:
        return {
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ShadowRuntimeDiagnostics":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"ShadowRuntimeDiagnostics.from_dict requires a mapping, got "
                f"{type(data).__name__}"
            )
        unknown = set(data.keys()) - {"warnings", "errors"}
        if unknown:
            raise ContractError(
                f"ShadowRuntimeDiagnostics received unknown fields: "
                f"{sorted(unknown)}"
            )
        return cls(
            warnings=tuple(str(w) for w in data.get("warnings", ())),
            errors=tuple(str(e) for e in data.get("errors", ())),
        )


@dataclass(frozen=True)
class ShadowRuntimeStepReport:
    """SDK per-frame projection of a Phase 1 shadow runtime step."""

    frame_index: int
    timestamp: str
    observation_counts: Mapping[str, int] = field(default_factory=dict)
    prediction_axes: tuple[str, ...] = ()
    prediction_counts: Mapping[str, int] = field(default_factory=dict)
    observation_count: int = 0
    mse_by_axis: Mapping[str, float] = field(default_factory=dict)
    mae_by_axis: Mapping[str, float] = field(default_factory=dict)
    accepted_count: int = 0
    rejected_count: int = 0

    def __post_init__(self) -> None:
        if isinstance(self.frame_index, bool) or not isinstance(
            self.frame_index, int
        ):
            raise ContractError(
                "ShadowRuntimeStepReport.frame_index must be int"
            )
        if self.frame_index < 0:
            raise ContractError(
                "ShadowRuntimeStepReport.frame_index must be non-negative"
            )
        if not isinstance(self.timestamp, str) or not self.timestamp:
            raise ContractError(
                "ShadowRuntimeStepReport.timestamp must be a non-empty string"
            )
        object.__setattr__(
            self,
            "observation_counts",
            _validate_axis_count_map(
                self.observation_counts,
                label="ShadowRuntimeStepReport.observation_counts",
            ),
        )
        object.__setattr__(
            self,
            "prediction_counts",
            _validate_axis_count_map(
                self.prediction_counts,
                label="ShadowRuntimeStepReport.prediction_counts",
            ),
        )
        if not isinstance(self.prediction_axes, tuple) or not all(
            isinstance(a, str) for a in self.prediction_axes
        ):
            raise ContractError(
                "ShadowRuntimeStepReport.prediction_axes must be a tuple of strings"
            )
        for axis in self.prediction_axes:
            if axis not in CANONICAL_TELEMETRY_AXES:
                raise ContractError(
                    f"ShadowRuntimeStepReport.prediction_axes contains "
                    f"unknown axis {axis!r}"
                )
        for name in ("observation_count", "accepted_count", "rejected_count"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ContractError(
                    f"ShadowRuntimeStepReport.{name} must be int"
                )
            if value < 0:
                raise ContractError(
                    f"ShadowRuntimeStepReport.{name} must be non-negative"
                )
        object.__setattr__(
            self,
            "mse_by_axis",
            _validate_axis_float_map(
                self.mse_by_axis,
                label="ShadowRuntimeStepReport.mse_by_axis",
            ),
        )
        object.__setattr__(
            self,
            "mae_by_axis",
            _validate_axis_float_map(
                self.mae_by_axis,
                label="ShadowRuntimeStepReport.mae_by_axis",
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame_index": self.frame_index,
            "timestamp": self.timestamp,
            "observation_counts": dict(self.observation_counts),
            "prediction_axes": list(self.prediction_axes),
            "prediction_counts": dict(self.prediction_counts),
            "observation_count": self.observation_count,
            "mse_by_axis": dict(self.mse_by_axis),
            "mae_by_axis": dict(self.mae_by_axis),
            "accepted_count": self.accepted_count,
            "rejected_count": self.rejected_count,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ShadowRuntimeStepReport":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"ShadowRuntimeStepReport.from_dict requires a mapping, got "
                f"{type(data).__name__}"
            )
        missing = {"frame_index", "timestamp"} - set(data.keys())
        if missing:
            raise ContractError(
                f"ShadowRuntimeStepReport missing fields: {sorted(missing)}"
            )
        unknown = set(data.keys()) - set(_STEP_FIELDS)
        if unknown:
            raise ContractError(
                f"ShadowRuntimeStepReport received unknown fields: "
                f"{sorted(unknown)}"
            )
        return cls(
            frame_index=int(data["frame_index"]),
            timestamp=str(data["timestamp"]),
            observation_counts=dict(data.get("observation_counts", {}) or {}),
            prediction_axes=tuple(
                str(a) for a in data.get("prediction_axes", ()) or ()
            ),
            prediction_counts=dict(data.get("prediction_counts", {}) or {}),
            observation_count=int(data.get("observation_count", 0)),
            mse_by_axis=dict(data.get("mse_by_axis", {}) or {}),
            mae_by_axis=dict(data.get("mae_by_axis", {}) or {}),
            accepted_count=int(data.get("accepted_count", 0)),
            rejected_count=int(data.get("rejected_count", 0)),
        )


@dataclass(frozen=True)
class ShadowRuntimeReport:
    """SDK projection of a Phase 1 shadow runtime report."""

    steps: tuple[ShadowRuntimeStepReport, ...] = ()
    frame_count: int = 0
    observation_count: int = 0
    proposal_count: int = 0
    accepted_count: int = 0
    rejected_count: int = 0
    diagnostics: ShadowRuntimeDiagnostics = field(
        default_factory=ShadowRuntimeDiagnostics
    )

    def __post_init__(self) -> None:
        if not isinstance(self.steps, tuple):
            raise ContractError("ShadowRuntimeReport.steps must be a tuple")
        for step in self.steps:
            if not isinstance(step, ShadowRuntimeStepReport):
                raise ContractError(
                    "ShadowRuntimeReport.steps entries must be "
                    "ShadowRuntimeStepReport instances"
                )
        for name in (
            "frame_count",
            "observation_count",
            "proposal_count",
            "accepted_count",
            "rejected_count",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ContractError(
                    f"ShadowRuntimeReport.{name} must be int"
                )
            if value < 0:
                raise ContractError(
                    f"ShadowRuntimeReport.{name} must be non-negative"
                )
        if self.frame_count != len(self.steps):
            raise ContractError(
                f"ShadowRuntimeReport.frame_count {self.frame_count} does not "
                f"match len(steps)={len(self.steps)}"
            )
        if not isinstance(self.diagnostics, ShadowRuntimeDiagnostics):
            raise ContractError(
                "ShadowRuntimeReport.diagnostics must be a "
                "ShadowRuntimeDiagnostics instance"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "steps": [s.to_dict() for s in self.steps],
            "frame_count": self.frame_count,
            "observation_count": self.observation_count,
            "proposal_count": self.proposal_count,
            "accepted_count": self.accepted_count,
            "rejected_count": self.rejected_count,
            "diagnostics": self.diagnostics.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ShadowRuntimeReport":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"ShadowRuntimeReport.from_dict requires a mapping, got "
                f"{type(data).__name__}"
            )
        unknown = set(data.keys()) - set(_REPORT_FIELDS)
        if unknown:
            raise ContractError(
                f"ShadowRuntimeReport received unknown fields: "
                f"{sorted(unknown)}"
            )
        raw_steps = data.get("steps", ())
        if not isinstance(raw_steps, Sequence) or isinstance(raw_steps, (str, bytes)):
            raise ContractError("ShadowRuntimeReport.steps must be a sequence")
        steps = tuple(
            ShadowRuntimeStepReport.from_dict(s) for s in raw_steps
        )
        return cls(
            steps=steps,
            frame_count=int(data.get("frame_count", len(steps))),
            observation_count=int(data.get("observation_count", 0)),
            proposal_count=int(data.get("proposal_count", 0)),
            accepted_count=int(data.get("accepted_count", 0)),
            rejected_count=int(data.get("rejected_count", 0)),
            diagnostics=ShadowRuntimeDiagnostics.from_dict(
                data.get("diagnostics", {}) or {}
            ),
        )
