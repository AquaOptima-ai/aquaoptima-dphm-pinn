# Calibration Validation

## Purpose

Validate dPL calibration losses against replay observations before any optimization/control workflow.

## Initial focus

- Deterministic residuals by axis and target id.
- MSE/MAE/weighted MSE reports.
- Missing prediction diagnostics.
- Compatibility with `ShadowReplayDataset`.

Calibration must remain offline/read-only in the shadow-mode MVP.
