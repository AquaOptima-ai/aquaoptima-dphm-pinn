"""TDD — dPL calibration SDK projections (Sprint 43).

Acceptance: the SDK ``DPLResidual`` / ``CalibrationLossSummary`` /
``DPLCalibrationDiagnostics`` / ``DPLCalibrationLossReport`` types
capture the *shape* of the Phase 1 Sprint 36 calibration loss
report. The Phase 1 builder
``aquaoptima.dphm.dpl_calibration.build_dpl_calibration_loss_report``
remains the authority for residual math; the SDK projection here
only models the read-only audit shape.
"""

from __future__ import annotations

import math

import pytest

from aquaoptima_contracts import (
    CalibrationLossSummary,
    ContractError,
    DPLCalibrationDiagnostics,
    DPLCalibrationLossReport,
    DPLResidual,
    dump_canonical_json,
    load_canonical_json,
)
from aquaoptima_contracts.calibration.loss_report import (
    project_phase1_dpl_calibration_loss_report,
)


def test_residual_minimal_round_trip() -> None:
    residual = DPLResidual(
        frame_index=0,
        timestamp="0.0",
        axis="node_pressure",
        target_id=2,
        observed=1.0,
        predicted=1.2,
        residual=0.2,
        weight=1.0,
    )
    decoded = load_canonical_json(dump_canonical_json(residual))
    assert decoded["axis"] == "node_pressure"
    assert decoded["target_id"] == 2
    restored = DPLResidual.from_dict(decoded)
    assert restored == residual


def test_residual_rejects_unknown_axis() -> None:
    with pytest.raises(ContractError):
        DPLResidual(
            frame_index=0,
            timestamp="0.0",
            axis="not_a_real_axis",
            target_id=0,
            observed=1.0,
            predicted=1.0,
            residual=0.0,
        )


def test_residual_rejects_negative_target_id() -> None:
    with pytest.raises(ContractError):
        DPLResidual(
            frame_index=0,
            timestamp="0.0",
            axis="node_pressure",
            target_id=-1,
            observed=1.0,
            predicted=1.0,
            residual=0.0,
        )


def test_residual_rejects_negative_frame_index() -> None:
    with pytest.raises(ContractError):
        DPLResidual(
            frame_index=-1,
            timestamp="0.0",
            axis="node_pressure",
            target_id=0,
            observed=1.0,
            predicted=1.0,
            residual=0.0,
        )


def test_residual_rejects_non_finite_value() -> None:
    with pytest.raises(ContractError):
        DPLResidual(
            frame_index=0,
            timestamp="0.0",
            axis="node_pressure",
            target_id=0,
            observed=float("nan"),
            predicted=1.0,
            residual=float("nan"),
        )


def test_residual_rejects_negative_or_non_finite_weight() -> None:
    with pytest.raises(ContractError):
        DPLResidual(
            frame_index=0,
            timestamp="0.0",
            axis="node_pressure",
            target_id=0,
            observed=1.0,
            predicted=1.0,
            residual=0.0,
            weight=-1.0,
        )
    with pytest.raises(ContractError):
        DPLResidual(
            frame_index=0,
            timestamp="0.0",
            axis="node_pressure",
            target_id=0,
            observed=1.0,
            predicted=1.0,
            residual=0.0,
            weight=float("inf"),
        )


def test_residual_rejects_unknown_fields_from_dict() -> None:
    with pytest.raises(ContractError):
        DPLResidual.from_dict(
            {
                "frame_index": 0,
                "timestamp": "0.0",
                "axis": "node_pressure",
                "target_id": 0,
                "observed": 1.0,
                "predicted": 1.0,
                "residual": 0.0,
                "weight": 1.0,
                "extra_unknown_field": 42,
            }
        )


def test_summary_minimal_round_trip() -> None:
    summary = CalibrationLossSummary(
        weighted_mse=0.04,
        mse_by_axis={"node_pressure": 0.04},
        mae_by_axis={"node_pressure": 0.2},
        observation_count=1,
    )
    decoded = load_canonical_json(dump_canonical_json(summary))
    assert decoded["weighted_mse"] == 0.04
    restored = CalibrationLossSummary.from_dict(decoded)
    assert restored == summary


def test_summary_rejects_unknown_axis() -> None:
    with pytest.raises(ContractError):
        CalibrationLossSummary(
            weighted_mse=0.0,
            mse_by_axis={"not_a_real_axis": 0.0},
        )


def test_summary_rejects_negative_observation_count() -> None:
    with pytest.raises(ContractError):
        CalibrationLossSummary(
            weighted_mse=0.0,
            observation_count=-1,
        )


def test_summary_rejects_negative_mse() -> None:
    with pytest.raises(ContractError):
        CalibrationLossSummary(
            weighted_mse=-0.1,
        )
    with pytest.raises(ContractError):
        CalibrationLossSummary(
            weighted_mse=0.0,
            mse_by_axis={"node_pressure": -0.5},
        )


def test_summary_rejects_non_finite() -> None:
    with pytest.raises(ContractError):
        CalibrationLossSummary(weighted_mse=float("nan"))


def test_diagnostics_round_trip() -> None:
    diagnostics = DPLCalibrationDiagnostics(
        warnings=("frame[0] extra prediction ignored",),
        errors=(),
    )
    decoded = load_canonical_json(dump_canonical_json(diagnostics))
    assert decoded["warnings"] == ["frame[0] extra prediction ignored"]
    restored = DPLCalibrationDiagnostics.from_dict(decoded)
    assert restored == diagnostics


def test_diagnostics_rejects_unknown_fields() -> None:
    with pytest.raises(ContractError):
        DPLCalibrationDiagnostics.from_dict({"warnings": [], "errors": [], "x": 1})


def test_report_minimal_round_trip() -> None:
    report = DPLCalibrationLossReport(
        residuals=(),
        summary=CalibrationLossSummary(weighted_mse=0.0, observation_count=0),
        diagnostics=DPLCalibrationDiagnostics(),
    )
    decoded = load_canonical_json(dump_canonical_json(report))
    assert decoded["summary"]["weighted_mse"] == 0.0
    restored = DPLCalibrationLossReport.from_dict(decoded)
    assert restored == report


def test_report_with_residuals_round_trip() -> None:
    residual = DPLResidual(
        frame_index=0,
        timestamp="0.0",
        axis="node_pressure",
        target_id=1,
        observed=2.0,
        predicted=2.2,
        residual=0.2,
        weight=1.0,
    )
    summary = CalibrationLossSummary(
        weighted_mse=0.04,
        mse_by_axis={"node_pressure": 0.04},
        mae_by_axis={"node_pressure": 0.2},
        observation_count=1,
    )
    report = DPLCalibrationLossReport(
        residuals=(residual,),
        summary=summary,
        diagnostics=DPLCalibrationDiagnostics(),
    )
    decoded = load_canonical_json(dump_canonical_json(report))
    restored = DPLCalibrationLossReport.from_dict(decoded)
    assert restored == report
    assert decoded["residuals"][0]["axis"] == "node_pressure"


def test_report_rejects_inconsistent_observation_count() -> None:
    residual = DPLResidual(
        frame_index=0,
        timestamp="0.0",
        axis="node_pressure",
        target_id=1,
        observed=2.0,
        predicted=2.2,
        residual=0.2,
        weight=1.0,
    )
    summary = CalibrationLossSummary(weighted_mse=0.04, observation_count=2)
    with pytest.raises(ContractError):
        DPLCalibrationLossReport(
            residuals=(residual,),
            summary=summary,
        )


def test_report_rejects_unknown_top_level_fields() -> None:
    with pytest.raises(ContractError):
        DPLCalibrationLossReport.from_dict(
            {
                "residuals": [],
                "summary": {"weighted_mse": 0.0, "observation_count": 0},
                "diagnostics": {"warnings": [], "errors": []},
                "actuated_setpoint": 1.0,
            }
        )


def test_report_to_dict_does_not_carry_control_field() -> None:
    report = DPLCalibrationLossReport(
        summary=CalibrationLossSummary(weighted_mse=0.0, observation_count=0),
    )
    decoded = load_canonical_json(dump_canonical_json(report))
    for key in decoded:
        assert "setpoint" not in key
        assert "write" not in key
        assert "control" not in key
        assert "command" not in key
        assert "actuate" not in key


def test_phase1_projection_round_trips() -> None:
    """The duck-typed projection adapter converts a Phase 1
    ``DPLCalibrationLossReport`` into the SDK shape without importing
    the Phase 1 module from inside the SDK package code."""

    from aquaoptima.dphm.shadow_replay import ShadowReplayDataset, ShadowReplayFrame
    from aquaoptima.dphm.dpl_calibration import build_dpl_calibration_loss_report

    frame = ShadowReplayFrame(
        timestamp="0.0",
        node_pressure={0: 1.0, 1: 1.5},
    )
    replay = ShadowReplayDataset(frames=(frame,))
    phase1_report = build_dpl_calibration_loss_report(
        replay,
        predictions=[{"node_pressure": {0: 1.1, 1: 1.4}}],
    )

    sdk_report = project_phase1_dpl_calibration_loss_report(phase1_report)
    assert isinstance(sdk_report, DPLCalibrationLossReport)
    assert sdk_report.summary.observation_count == 2
    # MSE for node_pressure = (0.01 + 0.01) / 2 = 0.01
    assert math.isclose(
        sdk_report.summary.mse_by_axis["node_pressure"], 0.01, rel_tol=1e-9
    )
    assert math.isclose(
        sdk_report.summary.weighted_mse, 0.01, rel_tol=1e-9
    )
    # JSON round-trip
    decoded = load_canonical_json(dump_canonical_json(sdk_report))
    restored = DPLCalibrationLossReport.from_dict(decoded)
    assert restored == sdk_report


def test_phase1_projection_preserves_diagnostics() -> None:
    from aquaoptima.dphm.shadow_replay import ShadowReplayDataset, ShadowReplayFrame
    from aquaoptima.dphm.dpl_calibration import build_dpl_calibration_loss_report

    frame = ShadowReplayFrame(
        timestamp="0.0",
        node_pressure={0: 1.0},
    )
    replay = ShadowReplayDataset(frames=(frame,))
    phase1_report = build_dpl_calibration_loss_report(
        replay,
        predictions=[
            {
                "node_pressure": {0: 1.0, 99: 5.0},
                "not_a_real_axis": {0: 0.0},
            }
        ],
    )
    sdk_report = project_phase1_dpl_calibration_loss_report(phase1_report)
    assert sdk_report.diagnostics.warnings  # at least one warning
    assert sdk_report.diagnostics.errors == ()
