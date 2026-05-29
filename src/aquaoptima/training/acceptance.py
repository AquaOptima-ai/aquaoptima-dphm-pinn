"""Acceptance gate ("good enough to package") for the dPHM offline eval (AOPSO Sprint 25).

A machine-checkable PASS/FAIL gate over the per-axis metrics produced by
:mod:`aquaoptima.training.evaluation`. The gate encodes the Sprint 25 packaging
criteria:

* **Continuous axes** (the 6 non-binary active axes): per-axis *normalized*
  ``MSE <= mse_max`` (default 0.15) AND ``MAE <= mae_max`` (default 0.30).
* **Binary axes** (``node_status``, ``edge_status``): ``accuracy >= acc_min``
  (default 0.95).
* **Beats baseline**: dPHM must have *lower* MSE than the MVP-v1 persistence
  baseline on ``>= beats_baseline_min`` (default 5) of the 6 continuous axes.

The gate returns a structured result with per-criterion detail so a human (or
CI) can see exactly which criteria passed/failed. ``edge_valve_position`` is
N/A/masked and never participates.

THRESHOLDS ARE READ FROM CONFIG when available (``configs/yilan_dphm_v1.yaml``
``eval:`` block) and fall back to these defaults; they are NOT illustrative
example numbers — they are the contractually-encoded packaging bar.

Safety: pure-Python decision logic over already-computed metrics. No I/O beyond
optional config reading, no edge imports, no control influence, advisory only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

__all__ = [
    "AcceptanceThresholds",
    "CriterionResult",
    "GateResult",
    "evaluate_gate",
    "BINARY_AXES",
    "CONTINUOUS_AXES",
]

# Axis routing -- single source of truth in the axis map (Sprint 26). Imported
# (not redefined) so loss / trainer / evaluation / gate cannot drift. This
# sprint ``BINARY_AXES`` is EMPTY (node_status reclassified continuous,
# edge_status dropped as a binary target); the binary-gating branch below stays
# correct for any axis re-listed in ``BINARY_AXES`` and now gates on BALANCED
# accuracy / F1 rather than raw accuracy (DEFECT 2 fix).
from ..dataio.yilan_axis_map import BINARY_AXES, CONTINUOUS_AXES


@dataclass(frozen=True)
class AcceptanceThresholds:
    """The encoded "good enough to package" bar (defaults are the Sprint 25 spec).

    Sprint 26 (DEFECT 2 fix): binary axes are gated on BALANCED accuracy / F1,
    NOT raw accuracy. Raw accuracy is meaningless on the 99.85%-imbalanced pump
    status (always-on scores 0.9985). ``binary_balanced_accuracy_min`` /
    ``binary_f1_min`` are the new imbalance-aware bars. ``binary_accuracy_min``
    is retained for backward-compatible reporting only and is NOT the gate.
    """

    continuous_mse_max: float = 0.15
    continuous_mae_max: float = 0.30
    binary_accuracy_min: float = 0.95
    # Imbalance-aware gate bars (Sprint 26). Default 0.70 balanced-accuracy /
    # 0.70 F1 -- a do-nothing always-on predictor scores 0.5 balanced accuracy.
    binary_balanced_accuracy_min: float = 0.70
    binary_f1_min: float = 0.70
    beats_baseline_min: int = 5
    n_continuous_axes: int = 6

    @classmethod
    def from_config(cls, config: Mapping | None) -> "AcceptanceThresholds":
        """Build thresholds from a config dict's ``eval`` block (with fallbacks)."""
        if not config:
            return cls()
        ev = config.get("eval") or {}
        defaults = cls()
        return cls(
            continuous_mse_max=float(
                ev.get("continuous_mse_max", defaults.continuous_mse_max)
            ),
            continuous_mae_max=float(
                ev.get("continuous_mae_max", defaults.continuous_mae_max)
            ),
            binary_accuracy_min=float(
                ev.get("binary_accuracy_min", defaults.binary_accuracy_min)
            ),
            binary_balanced_accuracy_min=float(
                ev.get(
                    "binary_balanced_accuracy_min",
                    defaults.binary_balanced_accuracy_min,
                )
            ),
            binary_f1_min=float(ev.get("binary_f1_min", defaults.binary_f1_min)),
            beats_baseline_min=int(
                ev.get("beats_baseline_min", defaults.beats_baseline_min)
            ),
            n_continuous_axes=int(
                ev.get("n_continuous_axes", defaults.n_continuous_axes)
            ),
        )

    def to_dict(self) -> dict:
        return {
            "continuous_mse_max": self.continuous_mse_max,
            "continuous_mae_max": self.continuous_mae_max,
            "binary_accuracy_min": self.binary_accuracy_min,
            "binary_balanced_accuracy_min": self.binary_balanced_accuracy_min,
            "binary_f1_min": self.binary_f1_min,
            "beats_baseline_min": self.beats_baseline_min,
            "n_continuous_axes": self.n_continuous_axes,
        }


@dataclass(frozen=True)
class CriterionResult:
    """One named criterion's PASS/FAIL with the detail behind the decision."""

    name: str
    passed: bool
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"name": self.name, "passed": self.passed, "detail": self.detail}


@dataclass(frozen=True)
class GateResult:
    """Aggregate gate verdict + per-criterion breakdown."""

    passed: bool
    criteria: tuple[CriterionResult, ...]
    thresholds: AcceptanceThresholds

    @property
    def verdict(self) -> str:
        return "PASS" if self.passed else "FAIL"

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "passed": self.passed,
            "thresholds": self.thresholds.to_dict(),
            "criteria": [c.to_dict() for c in self.criteria],
        }


def _continuous_axes_in(metrics: Mapping[str, Mapping]) -> list[str]:
    return sorted(a for a in metrics if a in CONTINUOUS_AXES)


def _binary_axes_in(metrics: Mapping[str, Mapping]) -> list[str]:
    return sorted(a for a in metrics if a in BINARY_AXES)


def evaluate_gate(
    dphm_metrics: Mapping[str, Mapping],
    baseline_metrics: Mapping[str, Mapping] | None = None,
    *,
    thresholds: AcceptanceThresholds | None = None,
) -> GateResult:
    """Evaluate the acceptance gate over per-axis metrics.

    Parameters
    ----------
    dphm_metrics
        ``{axis: {"mse": float, "mae": float, "accuracy": float|None}}`` for the
        active axes (continuous axes carry mse/mae; binary axes carry accuracy).
    baseline_metrics
        Same shape, for the MVP-v1 persistence baseline. Required for the
        beats-baseline criterion; if ``None`` that criterion FAILS (cannot
        justify packaging without a baseline comparison).
    thresholds
        Override thresholds; defaults to :class:`AcceptanceThresholds`.
    """
    th = thresholds or AcceptanceThresholds()
    criteria: list[CriterionResult] = []

    # --- Criterion 1: continuous-axis MSE <= max, per active continuous axis ---
    cont_axes = _continuous_axes_in(dphm_metrics)
    mse_detail: dict[str, dict] = {}
    mse_ok = True
    for axis in cont_axes:
        mse = float(dphm_metrics[axis].get("mse"))
        ok = mse <= th.continuous_mse_max
        mse_detail[axis] = {"mse": mse, "max": th.continuous_mse_max, "passed": ok}
        mse_ok = mse_ok and ok
    criteria.append(
        CriterionResult(
            name="continuous_mse_within_threshold",
            passed=mse_ok and bool(cont_axes),
            detail={"per_axis": mse_detail, "n_axes": len(cont_axes)},
        )
    )

    # --- Criterion 2: continuous-axis MAE <= max, per active continuous axis ---
    mae_detail: dict[str, dict] = {}
    mae_ok = True
    for axis in cont_axes:
        mae = float(dphm_metrics[axis].get("mae"))
        ok = mae <= th.continuous_mae_max
        mae_detail[axis] = {"mae": mae, "max": th.continuous_mae_max, "passed": ok}
        mae_ok = mae_ok and ok
    criteria.append(
        CriterionResult(
            name="continuous_mae_within_threshold",
            passed=mae_ok and bool(cont_axes),
            detail={"per_axis": mae_detail, "n_axes": len(cont_axes)},
        )
    )

    # --- Criterion 3: binary-axis BALANCED-accuracy / F1 >= min (DEFECT 2 fix) ---
    # Raw accuracy is meaningless on the 99.85%-imbalanced pump status. We gate
    # on balanced accuracy AND F1 instead. If there are NO binary axes (the
    # Sprint 26 default -- node_status reclassified continuous, edge_status
    # dropped), this criterion passes VACUOUSLY (there is nothing to gate).
    bin_axes = _binary_axes_in(dphm_metrics)
    acc_detail: dict[str, dict] = {}
    acc_ok = True
    for axis in bin_axes:
        m = dphm_metrics[axis]
        bal = m.get("balanced_accuracy")
        f1 = m.get("f1")
        if bal is None or f1 is None:
            acc_detail[axis] = {
                "balanced_accuracy": bal,
                "f1": f1,
                "balanced_accuracy_min": th.binary_balanced_accuracy_min,
                "f1_min": th.binary_f1_min,
                "accuracy": m.get("accuracy"),
                "passed": False,
                "note": "missing balanced_accuracy/f1 -> cannot gate",
            }
            acc_ok = False
            continue
        bal = float(bal)
        f1 = float(f1)
        ok = bal >= th.binary_balanced_accuracy_min and f1 >= th.binary_f1_min
        acc_detail[axis] = {
            "balanced_accuracy": bal,
            "f1": f1,
            "balanced_accuracy_min": th.binary_balanced_accuracy_min,
            "f1_min": th.binary_f1_min,
            # Raw accuracy reported for context but NOT gated on.
            "accuracy": m.get("accuracy"),
            "passed": ok,
        }
        acc_ok = acc_ok and ok
    criteria.append(
        CriterionResult(
            name="binary_balanced_accuracy_within_threshold",
            # Vacuously true when no binary axes exist (nothing to gate).
            passed=acc_ok,
            detail={
                "per_axis": acc_detail,
                "n_axes": len(bin_axes),
                "metric": "balanced_accuracy_and_f1",
                "note": (
                    "no binary axes this sprint -> criterion vacuously satisfied"
                    if not bin_axes
                    else "gated on balanced accuracy + F1 (NOT raw accuracy)"
                ),
            },
        )
    )

    # --- Criterion 4: dPHM beats baseline (lower MSE) on >= N of 6 continuous axes ---
    beats_detail: dict[str, dict] = {}
    n_beats = 0
    if baseline_metrics is None:
        beats_passed = False
        beats_detail = {"error": "no baseline metrics provided"}
    else:
        for axis in cont_axes:
            dphm_mse = float(dphm_metrics[axis].get("mse"))
            base_mse = baseline_metrics.get(axis, {}).get("mse")
            if base_mse is None:
                beats = False
                base_val = None
            else:
                base_val = float(base_mse)
                beats = dphm_mse < base_val
            if beats:
                n_beats += 1
            beats_detail[axis] = {
                "dphm_mse": dphm_mse,
                "baseline_mse": base_val,
                "beats_baseline": beats,
            }
        beats_passed = n_beats >= th.beats_baseline_min
    criteria.append(
        CriterionResult(
            name="beats_baseline_on_continuous_axes",
            passed=beats_passed,
            detail={
                "per_axis": beats_detail,
                "n_beats": n_beats,
                "required": th.beats_baseline_min,
            },
        )
    )

    passed = all(c.passed for c in criteria)
    return GateResult(passed=passed, criteria=tuple(criteria), thresholds=th)
