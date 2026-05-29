"""Assemble eval metrics into a ``ShadowRuntimeReport``-shaped dict (AOPSO Sprint 25).

This module is the *serialization target* layer: it takes the per-axis MSE/MAE
(and binary accuracy) computed by :mod:`aquaoptima.training.evaluation` and
projects them onto the SHARED ``ShadowRuntimeReport`` contract shape, importing
the real contract classes to validate field names/types. We do NOT fork or edit
the contract; we only consume its shape.

Mapping decisions
-----------------
* The whole holdout score is emitted as a single ``ShadowRuntimeStepReport``
  (``frame_index=0``) carrying ``mse_by_axis`` / ``mae_by_axis`` for every
  scored axis. The contract's axis-keyed float maps validate that every axis
  name is a canonical telemetry axis.
* ``prediction_axes`` lists the active axes that were scored (continuous +
  binary). ``observation_count`` / report ``observation_count`` carry the
  number of holdout windows scored.
* Binary-axis accuracy is NOT a contract field; it is preserved alongside the
  contract-shaped payload in a sibling ``scorecard`` envelope (advisory),
  never inside the contract object, so the contract validation stays clean.

Safety: offline only; assembles advisory scorecards. No edge imports, no ONNX,
no writes to contracts.
"""

from __future__ import annotations

from typing import Mapping

from aquaoptima_contracts.runtime.shadow_report import (
    ShadowRuntimeDiagnostics,
    ShadowRuntimeReport,
    ShadowRuntimeStepReport,
)

__all__ = [
    "build_shadow_report",
    "validate_shadow_report_shape",
]


def build_shadow_report(
    *,
    mse_by_axis: Mapping[str, float],
    mae_by_axis: Mapping[str, float],
    prediction_axes: list[str],
    observation_count: int,
    timestamp: str,
    warnings: list[str] | None = None,
) -> ShadowRuntimeReport:
    """Build a single-step ``ShadowRuntimeReport`` from per-axis metrics.

    Only continuous axes carry MSE/MAE; binary axes are reported via the sibling
    scorecard (accuracy) and are still listed in ``prediction_axes``. The
    contract's float-map validation runs on construction, so a malformed axis
    name raises ``ContractError`` immediately (a STOP condition upstream).
    """
    step = ShadowRuntimeStepReport(
        frame_index=0,
        timestamp=timestamp,
        prediction_axes=tuple(prediction_axes),
        observation_count=int(observation_count),
        mse_by_axis=dict(mse_by_axis),
        mae_by_axis=dict(mae_by_axis),
    )
    diagnostics = ShadowRuntimeDiagnostics(
        warnings=tuple(warnings or ()),
        errors=(),
    )
    report = ShadowRuntimeReport(
        steps=(step,),
        frame_count=1,
        observation_count=int(observation_count),
        proposal_count=0,
        accepted_count=0,
        rejected_count=0,
        diagnostics=diagnostics,
    )
    return report


def validate_shadow_report_shape(payload: Mapping) -> ShadowRuntimeReport:
    """Round-trip a dict through the real contract to assert it conforms.

    Raises ``ContractError`` (from the contract) if any field name/type is
    wrong. Returns the reconstructed contract object on success. This is the
    STOP-condition guard: a scorecard that does not validate must not ship.
    """
    return ShadowRuntimeReport.from_dict(payload)
