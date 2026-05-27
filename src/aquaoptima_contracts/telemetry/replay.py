"""``ShadowReplayFrame`` / ``ShadowReplayDataset`` SDK projections (Sprint 42).

These types capture the *shape* of the Phase 1 shadow replay artifact.
The Phase 1 runtime module ``aquaoptima.dphm.shadow_replay`` continues
to own ``build_shadow_replay_dataset`` and ``load_shadow_replay_csv``,
including the unit conversion tables and timestamp staleness checks.
The SDK projection only validates canonical axis tokens and
structural fields so that any deployable can read the artifact
without a runtime ``Network`` instance in scope.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from ..base.envelope import ContractError
from .axis import CANONICAL_TELEMETRY_AXES


# Axes that hold numeric scalar values (vs status axes that hold
# bool / 0/1). The Phase 1 runtime keeps the authoritative numeric
# vs status table; the SDK projection only enforces that numeric
# axes carry finite floats.
_NUMERIC_AXES: frozenset[str] = frozenset(
    {
        "node_pressure",
        "node_demand",
        "node_level",
        "edge_flow",
        "edge_pump_speed",
        "edge_power",
        "edge_valve_position",
    }
)


_STATUS_AXES: frozenset[str] = frozenset({"node_status", "edge_status"})


@dataclass(frozen=True)
class ShadowReplayDiagnostics:
    """Deterministic warnings / errors tuples for an SDK replay
    dataset projection."""

    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("warnings", "errors"):
            value = getattr(self, name)
            if not isinstance(value, tuple) or not all(
                isinstance(v, str) for v in value
            ):
                raise ContractError(
                    f"ShadowReplayDiagnostics.{name} must be a tuple of strings"
                )

    def to_dict(self) -> dict[str, list[str]]:
        return {
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ShadowReplayDiagnostics":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"ShadowReplayDiagnostics.from_dict requires a mapping, got "
                f"{type(data).__name__}"
            )
        unknown = set(data.keys()) - {"warnings", "errors"}
        if unknown:
            raise ContractError(
                f"ShadowReplayDiagnostics received unknown fields: "
                f"{sorted(unknown)}"
            )
        warnings = tuple(str(w) for w in data.get("warnings", ()))
        errors = tuple(str(e) for e in data.get("errors", ()))
        return cls(warnings=warnings, errors=errors)


@dataclass(frozen=True)
class ShadowReplayFrame:
    """Single-timestamp frame keyed by canonical axis.

    Attributes
    ----------
    timestamp
        Non-empty timestamp string. The SDK stores timestamps as
        strings for deterministic JSON; callers wanting numeric
        timestamps can stringify them at the boundary.
    values
        ``{axis: {target_id: float}}`` mapping. Status axes may
        carry ``bool`` or numeric ``0/1`` values; numeric axes must
        carry finite floats. Empty axes are allowed.
    """

    timestamp: str
    values: Mapping[str, Mapping[int, float]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.timestamp, str) or not self.timestamp:
            raise ContractError(
                "ShadowReplayFrame.timestamp must be a non-empty string"
            )
        if not isinstance(self.values, Mapping):
            raise ContractError(
                f"ShadowReplayFrame.values must be a mapping, got "
                f"{type(self.values).__name__}"
            )
        normalised: dict[str, dict[int, float]] = {}
        for axis, axis_values in self.values.items():
            if axis not in CANONICAL_TELEMETRY_AXES:
                raise ContractError(
                    f"ShadowReplayFrame.values: axis {axis!r} is not a "
                    f"canonical telemetry axis"
                )
            if not isinstance(axis_values, Mapping):
                raise ContractError(
                    f"ShadowReplayFrame.values[{axis!r}] must be a mapping"
                )
            cleaned: dict[int, float] = {}
            for target_id, value in axis_values.items():
                if isinstance(target_id, bool) or not isinstance(target_id, int):
                    raise ContractError(
                        f"ShadowReplayFrame.values[{axis!r}] target_id must be "
                        f"int, got {type(target_id).__name__}"
                    )
                if target_id < 0:
                    raise ContractError(
                        f"ShadowReplayFrame.values[{axis!r}] target_id must be "
                        f"non-negative, got {target_id}"
                    )
                if axis in _STATUS_AXES:
                    if isinstance(value, bool):
                        cleaned[target_id] = bool(value)  # type: ignore[assignment]
                        continue
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        if float(value) in (0.0, 1.0):
                            cleaned[target_id] = float(value)
                            continue
                    raise ContractError(
                        f"ShadowReplayFrame.values[{axis!r}][{target_id}]: "
                        f"status value must be bool or 0/1, got {value!r}"
                    )
                # numeric axis
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ContractError(
                        f"ShadowReplayFrame.values[{axis!r}][{target_id}]: "
                        f"numeric axis requires a finite float, got "
                        f"{type(value).__name__}"
                    )
                numeric = float(value)
                if math.isnan(numeric) or math.isinf(numeric):
                    raise ContractError(
                        f"ShadowReplayFrame.values[{axis!r}][{target_id}]: "
                        f"non-finite numeric value {numeric!r}"
                    )
                cleaned[target_id] = numeric
            normalised[axis] = cleaned
        # Reassign through ``object.__setattr__`` because the dataclass
        # is frozen; normalisation to fresh dicts is harmless and
        # makes equality deterministic.
        object.__setattr__(self, "values", normalised)

    def to_dict(self) -> dict[str, Any]:
        out_values: dict[str, dict[str, Any]] = {}
        for axis in sorted(self.values.keys()):
            axis_map = self.values[axis]
            out_values[axis] = {
                str(target_id): axis_map[target_id]
                for target_id in sorted(axis_map.keys())
            }
        return {"timestamp": self.timestamp, "values": out_values}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ShadowReplayFrame":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"ShadowReplayFrame.from_dict requires a mapping, got "
                f"{type(data).__name__}"
            )
        missing = {"timestamp", "values"} - set(data.keys())
        if missing:
            raise ContractError(
                f"ShadowReplayFrame missing fields: {sorted(missing)}"
            )
        unknown = set(data.keys()) - {"timestamp", "values"}
        if unknown:
            raise ContractError(
                f"ShadowReplayFrame received unknown fields: {sorted(unknown)}"
            )
        raw_values = data["values"]
        if not isinstance(raw_values, Mapping):
            raise ContractError(
                "ShadowReplayFrame.from_dict: 'values' must be a mapping"
            )
        values: dict[str, dict[int, float]] = {}
        for axis, axis_map in raw_values.items():
            if not isinstance(axis_map, Mapping):
                raise ContractError(
                    f"ShadowReplayFrame.values[{axis!r}] must be a mapping"
                )
            values[str(axis)] = {
                int(target_id): axis_map[target_id]
                for target_id in axis_map
            }
        return cls(timestamp=str(data["timestamp"]), values=values)


@dataclass(frozen=True)
class ShadowReplayDataset:
    """Frozen SDK projection of a Phase 1 shadow replay dataset."""

    frames: tuple[ShadowReplayFrame, ...] = ()
    diagnostics: ShadowReplayDiagnostics = field(
        default_factory=ShadowReplayDiagnostics
    )

    def __post_init__(self) -> None:
        if not isinstance(self.frames, tuple):
            raise ContractError("ShadowReplayDataset.frames must be a tuple")
        for frame in self.frames:
            if not isinstance(frame, ShadowReplayFrame):
                raise ContractError(
                    "ShadowReplayDataset.frames entries must be "
                    "ShadowReplayFrame instances"
                )
        if not isinstance(self.diagnostics, ShadowReplayDiagnostics):
            raise ContractError(
                "ShadowReplayDataset.diagnostics must be a "
                "ShadowReplayDiagnostics instance"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "frames": [frame.to_dict() for frame in self.frames],
            "diagnostics": self.diagnostics.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ShadowReplayDataset":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"ShadowReplayDataset.from_dict requires a mapping, got "
                f"{type(data).__name__}"
            )
        unknown = set(data.keys()) - {"frames", "diagnostics"}
        if unknown:
            raise ContractError(
                f"ShadowReplayDataset received unknown fields: {sorted(unknown)}"
            )
        raw_frames = data.get("frames", ())
        if not isinstance(raw_frames, Sequence) or isinstance(raw_frames, (str, bytes)):
            raise ContractError("ShadowReplayDataset.frames must be a sequence")
        frames = tuple(ShadowReplayFrame.from_dict(f) for f in raw_frames)
        diagnostics = ShadowReplayDiagnostics.from_dict(
            data.get("diagnostics", {})
        )
        return cls(frames=frames, diagnostics=diagnostics)
