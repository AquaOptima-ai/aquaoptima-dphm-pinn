"""dPL calibration contract projections (Sprint 43).

The Sprint 43 SDK calibration module owns *shape* and deterministic
JSON for:

* :class:`DPLResidual` — single per-observation residual record.
* :class:`CalibrationLossSummary` — weighted MSE / per-axis MSE / MAE.
* :class:`DPLCalibrationDiagnostics` — deterministic warnings /
  errors tuples.
* :class:`DPLCalibrationLossReport` — frozen top-level container.

The Phase 1 builder
``aquaoptima.dphm.dpl_calibration.build_dpl_calibration_loss_report``
remains the authority for residual math; the SDK projection here
models the read-only audit shape only. No advisory emission,
no setpoint output, no control surface.
"""

from .loss_report import (
    CalibrationLossSummary,
    DPLCalibrationDiagnostics,
    DPLCalibrationLossReport,
    DPLResidual,
    project_phase1_dpl_calibration_loss_report,
)

__all__ = [
    "CalibrationLossSummary",
    "DPLCalibrationDiagnostics",
    "DPLCalibrationLossReport",
    "DPLResidual",
    "project_phase1_dpl_calibration_loss_report",
]
