"""Sprint 36 — dPL calibration prototype.

Sprint 36 turns Sprint 35 :class:`ShadowReplayDataset` frames plus a
per-frame predictions sequence into a deterministic, frozen
:class:`DPLCalibrationLossReport`. These tests cover, in order:

1. Frozen dataclass surfaces.
2. Empty replay behaviour.
3. Single node-pressure residual + MSE / MAE.
4. Multiple axes + multiple target ids.
5. Weighted MSE by axis.
6. Missing prediction strict raises.
7. Missing prediction non-strict records error and skips residual.
8. Extra prediction records warning.
9. Invalid axis weight rejected.
10. Bool status observed / predicted coercion.
11. Prediction sequence length mismatch strict / non-strict.
12. Deterministic residual ordering: frame, axis, target id.
13. Read-only: replay and predictions unchanged.
14. Compatibility with ``build_shadow_replay_dataset`` from Sprint 35.
15. No live adapter / write / control / advisory surface exposed.
"""

from __future__ import annotations

import copy
import dataclasses
import math

import pytest

from aquaoptima.dphm import (
    DPL_AXES,
    DPL_NUMERIC_AXES,
    DPL_STATUS_AXES,
    DPLCalibrationDiagnostics,
    DPLCalibrationLossReport,
    DPLResidual,
    Network,
    ShadowReplayDataset,
    ShadowReplayDiagnostics,
    ShadowReplayFrame,
    TELEMETRY_AXIS_EDGE_FLOW,
    TELEMETRY_AXIS_EDGE_POWER,
    TELEMETRY_AXIS_EDGE_PUMP_SPEED,
    TELEMETRY_AXIS_EDGE_STATUS,
    TELEMETRY_AXIS_EDGE_VALVE_POSITION,
    TELEMETRY_AXIS_NODE_DEMAND,
    TELEMETRY_AXIS_NODE_LEVEL,
    TELEMETRY_AXIS_NODE_PRESSURE,
    TELEMETRY_AXIS_NODE_STATUS,
    TELEMETRY_ROLE_CONTROL_INPUT,
    TELEMETRY_TARGET_EDGE,
    TELEMETRY_TARGET_NODE,
    TelemetryTagMap,
    TelemetryTagSpec,
    build_dpl_calibration_loss_report,
    build_shadow_replay_dataset,
    build_telemetry_tag_map,
    make_branch_network,
    make_pump_network,
)
import aquaoptima.dphm as dphm
import aquaoptima.dphm.dpl_calibration as dpl_calibration_module


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _replay_from_frames(frames: tuple[ShadowReplayFrame, ...]) -> ShadowReplayDataset:
    return ShadowReplayDataset(
        frames=frames,
        tag_map=TelemetryTagMap(),
        diagnostics=ShadowReplayDiagnostics(),
    )


def _single_pressure_replay(
    *, target_id: int = 1, observed: float = 30.0, timestamp: object = 0.0
) -> ShadowReplayDataset:
    frame = ShadowReplayFrame(
        timestamp=timestamp,
        node_pressure={target_id: observed},
    )
    return _replay_from_frames((frame,))


# ---------------------------------------------------------------------------
# 1. Frozen dataclass surfaces
# ---------------------------------------------------------------------------


def test_dpl_calibration_dataclasses_are_frozen() -> None:
    replay = _single_pressure_replay()
    report = build_dpl_calibration_loss_report(
        replay, [{"node_pressure": {1: 31.0}}]
    )
    diagnostics = report.diagnostics
    residual = report.residuals[0]

    for instance in (report, diagnostics, residual):
        cls = type(instance)
        assert dataclasses.is_dataclass(cls)
        params = getattr(cls, "__dataclass_params__")
        assert params.frozen is True, f"{cls.__name__} must be frozen"

    with pytest.raises(dataclasses.FrozenInstanceError):
        report.weighted_mse = 0.0  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        diagnostics.warnings = ()  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        residual.residual = 0.0  # type: ignore[misc]


def test_default_dpl_calibration_dataclasses_are_constructible() -> None:
    diagnostics = DPLCalibrationDiagnostics()
    assert diagnostics.warnings == ()
    assert diagnostics.errors == ()

    report = DPLCalibrationLossReport()
    assert report.residuals == ()
    assert report.mse_by_axis == {}
    assert report.mae_by_axis == {}
    assert report.weighted_mse == 0.0
    assert report.observation_count == 0
    assert report.diagnostics == DPLCalibrationDiagnostics()


# ---------------------------------------------------------------------------
# 2. Empty replay
# ---------------------------------------------------------------------------


def test_empty_replay_returns_empty_report() -> None:
    replay = _replay_from_frames(())
    report = build_dpl_calibration_loss_report(replay, [])
    assert report.residuals == ()
    assert report.mse_by_axis == {}
    assert report.mae_by_axis == {}
    assert report.weighted_mse == 0.0
    assert report.observation_count == 0
    assert report.diagnostics == DPLCalibrationDiagnostics()


def test_empty_replay_non_strict_returns_empty_report() -> None:
    replay = _replay_from_frames(())
    report = build_dpl_calibration_loss_report(replay, [], strict=False)
    assert report.observation_count == 0
    assert report.diagnostics.errors == ()
    assert report.diagnostics.warnings == ()


# ---------------------------------------------------------------------------
# 3. Single node-pressure residual + MSE / MAE
# ---------------------------------------------------------------------------


def test_single_node_pressure_residual_basic() -> None:
    replay = _single_pressure_replay(target_id=2, observed=30.0, timestamp=42.0)
    report = build_dpl_calibration_loss_report(
        replay, [{"node_pressure": {2: 32.0}}]
    )
    assert report.observation_count == 1
    residual = report.residuals[0]
    assert residual.frame_index == 0
    assert residual.timestamp == 42.0
    assert residual.axis == TELEMETRY_AXIS_NODE_PRESSURE
    assert residual.target_id == 2
    assert residual.observed == pytest.approx(30.0)
    assert residual.predicted == pytest.approx(32.0)
    assert residual.residual == pytest.approx(2.0)
    assert residual.weight == pytest.approx(1.0)

    assert report.mse_by_axis == {TELEMETRY_AXIS_NODE_PRESSURE: pytest.approx(4.0)}
    assert report.mae_by_axis == {TELEMETRY_AXIS_NODE_PRESSURE: pytest.approx(2.0)}
    assert report.weighted_mse == pytest.approx(4.0)


def test_zero_residual_when_prediction_matches_observation() -> None:
    replay = _single_pressure_replay(target_id=1, observed=10.0)
    report = build_dpl_calibration_loss_report(
        replay, [{"node_pressure": {1: 10.0}}]
    )
    assert report.observation_count == 1
    assert report.residuals[0].residual == 0.0
    assert report.mse_by_axis[TELEMETRY_AXIS_NODE_PRESSURE] == 0.0
    assert report.mae_by_axis[TELEMETRY_AXIS_NODE_PRESSURE] == 0.0
    assert report.weighted_mse == 0.0


# ---------------------------------------------------------------------------
# 4. Multiple axes and target ids
# ---------------------------------------------------------------------------


def test_multiple_axes_and_target_ids() -> None:
    frame = ShadowReplayFrame(
        timestamp=0.0,
        node_pressure={1: 30.0, 2: 40.0},
        edge_flow={0: 0.010, 1: 0.020},
        edge_pump_speed={0: 0.80},
    )
    replay = _replay_from_frames((frame,))
    predictions = [
        {
            "node_pressure": {1: 31.0, 2: 39.0},
            "edge_flow": {0: 0.011, 1: 0.019},
            "edge_pump_speed": {0: 0.75},
        }
    ]
    report = build_dpl_calibration_loss_report(replay, predictions)

    assert report.observation_count == 5

    # MSE for node_pressure: ((31-30)^2 + (39-40)^2) / 2 = (1 + 1) / 2 = 1.0
    assert report.mse_by_axis[TELEMETRY_AXIS_NODE_PRESSURE] == pytest.approx(1.0)
    # MAE for node_pressure: (1 + 1) / 2 = 1.0
    assert report.mae_by_axis[TELEMETRY_AXIS_NODE_PRESSURE] == pytest.approx(1.0)

    # MSE for edge_flow: ((0.001)^2 + (-0.001)^2) / 2 = 1e-6
    assert report.mse_by_axis[TELEMETRY_AXIS_EDGE_FLOW] == pytest.approx(1.0e-6)
    # MAE for edge_flow: (0.001 + 0.001) / 2 = 0.001
    assert report.mae_by_axis[TELEMETRY_AXIS_EDGE_FLOW] == pytest.approx(0.001)

    # MSE for edge_pump_speed: (0.75 - 0.80)^2 = 0.0025
    assert report.mse_by_axis[TELEMETRY_AXIS_EDGE_PUMP_SPEED] == pytest.approx(0.0025)


# ---------------------------------------------------------------------------
# 5. Weighted MSE by axis
# ---------------------------------------------------------------------------


def test_weighted_mse_uses_axis_weights() -> None:
    frame = ShadowReplayFrame(
        timestamp=0.0,
        node_pressure={1: 30.0},
        edge_flow={0: 0.010},
    )
    replay = _replay_from_frames((frame,))
    predictions = [
        {
            "node_pressure": {1: 32.0},   # residual 2.0  → sq = 4.0
            "edge_flow": {0: 0.012},      # residual 0.002 → sq = 4e-6
        }
    ]
    weights = {TELEMETRY_AXIS_NODE_PRESSURE: 1.0, TELEMETRY_AXIS_EDGE_FLOW: 10.0}
    report = build_dpl_calibration_loss_report(
        replay, predictions, axis_weights=weights
    )

    # weighted_mse = (1.0 * 4.0 + 10.0 * 4e-6) / (1.0 + 10.0)
    expected = (1.0 * 4.0 + 10.0 * 4.0e-6) / 11.0
    assert report.weighted_mse == pytest.approx(expected)
    # Each residual carries its axis weight.
    axis_weights_by_residual = {r.axis: r.weight for r in report.residuals}
    assert axis_weights_by_residual[TELEMETRY_AXIS_NODE_PRESSURE] == 1.0
    assert axis_weights_by_residual[TELEMETRY_AXIS_EDGE_FLOW] == 10.0


def test_axis_weight_default_is_one() -> None:
    replay = _single_pressure_replay(target_id=1, observed=10.0)
    report = build_dpl_calibration_loss_report(
        replay, [{"node_pressure": {1: 13.0}}]
    )
    assert report.residuals[0].weight == 1.0
    # weighted_mse with weight=1.0 reduces to ordinary mean square.
    assert report.weighted_mse == pytest.approx(9.0)


# ---------------------------------------------------------------------------
# 6. Missing prediction strict raises
# ---------------------------------------------------------------------------


def test_missing_prediction_strict_raises() -> None:
    replay = _single_pressure_replay(target_id=1, observed=30.0)
    with pytest.raises(ValueError, match="no prediction supplied"):
        build_dpl_calibration_loss_report(replay, [{}])


def test_missing_axis_in_prediction_strict_raises() -> None:
    frame = ShadowReplayFrame(
        timestamp=0.0,
        node_pressure={1: 30.0},
        edge_flow={0: 0.010},
    )
    replay = _replay_from_frames((frame,))
    # Supplies node_pressure but not edge_flow.
    with pytest.raises(ValueError, match="no prediction supplied"):
        build_dpl_calibration_loss_report(
            replay, [{"node_pressure": {1: 31.0}}]
        )


# ---------------------------------------------------------------------------
# 7. Missing prediction non-strict records error
# ---------------------------------------------------------------------------


def test_missing_prediction_non_strict_records_error_and_skips() -> None:
    frame = ShadowReplayFrame(
        timestamp="t0",
        node_pressure={1: 30.0, 2: 40.0},
    )
    replay = _replay_from_frames((frame,))
    report = build_dpl_calibration_loss_report(
        replay,
        [{"node_pressure": {1: 32.0}}],  # missing 2
        strict=False,
    )
    assert report.observation_count == 1
    assert report.residuals[0].target_id == 1
    assert any("no prediction supplied" in e for e in report.diagnostics.errors)
    assert any("target 2" in e for e in report.diagnostics.errors)


# ---------------------------------------------------------------------------
# 8. Extra prediction warning
# ---------------------------------------------------------------------------


def test_extra_prediction_records_warning() -> None:
    replay = _single_pressure_replay(target_id=1, observed=30.0)
    report = build_dpl_calibration_loss_report(
        replay,
        [{"node_pressure": {1: 31.0, 99: 100.0}}],  # 99 is extra
    )
    # Residual for target 1 is produced; target 99 is a warning only.
    assert report.observation_count == 1
    assert report.residuals[0].target_id == 1
    assert any(
        "target 99" in w and "no observed value" in w
        for w in report.diagnostics.warnings
    )
    # Extra prediction is never an error and never raises in strict.
    assert report.diagnostics.errors == ()


def test_extra_prediction_axis_unsupported_records_warning() -> None:
    replay = _single_pressure_replay(target_id=1, observed=30.0)
    report = build_dpl_calibration_loss_report(
        replay,
        [
            {
                "node_pressure": {1: 31.0},
                "not_an_axis": {0: 1.0},  # warning, ignored
            }
        ],
    )
    assert report.observation_count == 1
    assert any(
        "unsupported axis" in w and "'not_an_axis'" in w
        for w in report.diagnostics.warnings
    )


# ---------------------------------------------------------------------------
# 9. Invalid axis weight rejected
# ---------------------------------------------------------------------------


def test_axis_weight_negative_rejected() -> None:
    replay = _single_pressure_replay()
    with pytest.raises(ValueError, match="strictly positive"):
        build_dpl_calibration_loss_report(
            replay,
            [{"node_pressure": {1: 31.0}}],
            axis_weights={TELEMETRY_AXIS_NODE_PRESSURE: -1.0},
        )


def test_axis_weight_zero_rejected() -> None:
    replay = _single_pressure_replay()
    with pytest.raises(ValueError, match="strictly positive"):
        build_dpl_calibration_loss_report(
            replay,
            [{"node_pressure": {1: 31.0}}],
            axis_weights={TELEMETRY_AXIS_NODE_PRESSURE: 0.0},
        )


def test_axis_weight_nan_rejected() -> None:
    replay = _single_pressure_replay()
    with pytest.raises(ValueError, match="finite"):
        build_dpl_calibration_loss_report(
            replay,
            [{"node_pressure": {1: 31.0}}],
            axis_weights={TELEMETRY_AXIS_NODE_PRESSURE: math.nan},
        )


def test_axis_weight_inf_rejected() -> None:
    replay = _single_pressure_replay()
    with pytest.raises(ValueError, match="finite"):
        build_dpl_calibration_loss_report(
            replay,
            [{"node_pressure": {1: 31.0}}],
            axis_weights={TELEMETRY_AXIS_NODE_PRESSURE: math.inf},
        )


def test_axis_weight_unknown_axis_rejected() -> None:
    replay = _single_pressure_replay()
    with pytest.raises(ValueError, match="not a recognised"):
        build_dpl_calibration_loss_report(
            replay,
            [{"node_pressure": {1: 31.0}}],
            axis_weights={"not_an_axis": 1.0},
        )


def test_axis_weight_bool_rejected() -> None:
    replay = _single_pressure_replay()
    with pytest.raises(ValueError, match="positive number"):
        build_dpl_calibration_loss_report(
            replay,
            [{"node_pressure": {1: 31.0}}],
            axis_weights={TELEMETRY_AXIS_NODE_PRESSURE: True},  # type: ignore[dict-item]
        )


def test_axis_weights_not_a_mapping_rejected() -> None:
    replay = _single_pressure_replay()
    with pytest.raises(ValueError, match="must be a Mapping"):
        build_dpl_calibration_loss_report(
            replay,
            [{"node_pressure": {1: 31.0}}],
            axis_weights=[(TELEMETRY_AXIS_NODE_PRESSURE, 1.0)],  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# 10. Bool status observed / predicted conversion
# ---------------------------------------------------------------------------


def test_status_bool_observation_and_prediction() -> None:
    frame = ShadowReplayFrame(
        timestamp=0.0,
        node_status={1: True, 2: False},
        edge_status={0: True},
    )
    replay = _replay_from_frames((frame,))
    predictions = [
        {
            "node_status": {1: True, 2: True},  # second mispredicted
            "edge_status": {0: 1.0},            # numeric 1 → True
        }
    ]
    report = build_dpl_calibration_loss_report(replay, predictions)
    assert report.observation_count == 3

    by_target = {
        (r.axis, r.target_id): r for r in report.residuals
    }
    # node 1: observed True (1.0), predicted True (1.0), residual 0.0
    assert by_target[(TELEMETRY_AXIS_NODE_STATUS, 1)].residual == 0.0
    # node 2: observed False (0.0), predicted True (1.0), residual 1.0
    assert by_target[(TELEMETRY_AXIS_NODE_STATUS, 2)].residual == 1.0
    # edge 0: 1.0 - 1.0 = 0
    assert by_target[(TELEMETRY_AXIS_EDGE_STATUS, 0)].residual == 0.0

    # MSE for node_status: (0^2 + 1^2) / 2 = 0.5
    assert report.mse_by_axis[TELEMETRY_AXIS_NODE_STATUS] == pytest.approx(0.5)
    # MAE for node_status: (0 + 1) / 2 = 0.5
    assert report.mae_by_axis[TELEMETRY_AXIS_NODE_STATUS] == pytest.approx(0.5)


def test_status_bool_observation_int_prediction() -> None:
    frame = ShadowReplayFrame(
        timestamp=0.0,
        edge_status={0: True},
    )
    replay = _replay_from_frames((frame,))
    report = build_dpl_calibration_loss_report(
        replay, [{"edge_status": {0: 0}}]  # int 0 → False
    )
    assert report.residuals[0].observed == 1.0
    assert report.residuals[0].predicted == 0.0
    assert report.residuals[0].residual == -1.0


def test_status_prediction_invalid_strict_raises() -> None:
    frame = ShadowReplayFrame(timestamp=0.0, edge_status={0: True})
    replay = _replay_from_frames((frame,))
    with pytest.raises(ValueError, match="not coercible"):
        build_dpl_calibration_loss_report(
            replay, [{"edge_status": {0: 2}}]  # numeric outside {0,1}
        )


def test_status_prediction_invalid_non_strict_recorded() -> None:
    frame = ShadowReplayFrame(timestamp=0.0, edge_status={0: True})
    replay = _replay_from_frames((frame,))
    report = build_dpl_calibration_loss_report(
        replay, [{"edge_status": {0: 5}}], strict=False
    )
    assert report.observation_count == 0
    assert any("not coercible" in e for e in report.diagnostics.errors)


# ---------------------------------------------------------------------------
# 11. Prediction sequence length mismatch
# ---------------------------------------------------------------------------


def test_length_mismatch_strict_raises() -> None:
    frame = ShadowReplayFrame(timestamp=0.0, node_pressure={1: 10.0})
    replay = _replay_from_frames((frame, frame))
    with pytest.raises(ValueError, match="does not match"):
        build_dpl_calibration_loss_report(
            replay, [{"node_pressure": {1: 11.0}}]
        )


def test_length_mismatch_non_strict_records_error() -> None:
    frame = ShadowReplayFrame(timestamp=0.0, node_pressure={1: 10.0})
    replay = _replay_from_frames((frame, frame))
    report = build_dpl_calibration_loss_report(
        replay,
        [{"node_pressure": {1: 11.0}}],
        strict=False,
    )
    # We still pair the overlapping prefix and emit the length error.
    assert report.observation_count == 1
    assert report.residuals[0].frame_index == 0
    assert any("does not match" in e for e in report.diagnostics.errors)


def test_excess_predictions_non_strict_records_error() -> None:
    frame = ShadowReplayFrame(timestamp=0.0, node_pressure={1: 10.0})
    replay = _replay_from_frames((frame,))
    report = build_dpl_calibration_loss_report(
        replay,
        [
            {"node_pressure": {1: 11.0}},
            {"node_pressure": {1: 12.0}},  # excess
        ],
        strict=False,
    )
    assert report.observation_count == 1
    assert any("does not match" in e for e in report.diagnostics.errors)


# ---------------------------------------------------------------------------
# 12. Deterministic residual ordering
# ---------------------------------------------------------------------------


def test_residuals_are_ordered_by_frame_then_axis_then_target() -> None:
    frame0 = ShadowReplayFrame(
        timestamp=0.0,
        # Deliberately give axes / targets in non-canonical order.
        edge_flow={1: 0.02, 0: 0.01},
        node_pressure={2: 30.0, 1: 25.0},
    )
    frame1 = ShadowReplayFrame(
        timestamp=1.0,
        node_pressure={3: 50.0},
    )
    replay = _replay_from_frames((frame0, frame1))
    predictions = [
        {
            "edge_flow": {1: 0.025, 0: 0.011},
            "node_pressure": {2: 31.0, 1: 26.0},
        },
        {"node_pressure": {3: 49.0}},
    ]
    report = build_dpl_calibration_loss_report(replay, predictions)

    ordered = [(r.frame_index, r.axis, r.target_id) for r in report.residuals]
    expected = [
        (0, TELEMETRY_AXIS_NODE_PRESSURE, 1),
        (0, TELEMETRY_AXIS_NODE_PRESSURE, 2),
        (0, TELEMETRY_AXIS_EDGE_FLOW, 0),
        (0, TELEMETRY_AXIS_EDGE_FLOW, 1),
        (1, TELEMETRY_AXIS_NODE_PRESSURE, 3),
    ]
    assert ordered == expected


def test_repeat_build_produces_equal_reports() -> None:
    frame = ShadowReplayFrame(
        timestamp=0.0,
        node_pressure={1: 10.0, 2: 20.0},
        edge_flow={0: 0.01},
    )
    replay = _replay_from_frames((frame,))
    predictions = [
        {
            "node_pressure": {1: 11.0, 2: 22.0},
            "edge_flow": {0: 0.011},
        }
    ]
    a = build_dpl_calibration_loss_report(replay, predictions)
    b = build_dpl_calibration_loss_report(replay, predictions)
    assert a == b


# ---------------------------------------------------------------------------
# 13. Read-only: replay and predictions unchanged
# ---------------------------------------------------------------------------


def test_builder_does_not_mutate_predictions_or_replay() -> None:
    frame = ShadowReplayFrame(
        timestamp=0.0,
        node_pressure={1: 30.0},
        edge_flow={0: 0.010},
    )
    replay = _replay_from_frames((frame,))
    predictions = [
        {
            "node_pressure": {1: 31.0},
            "edge_flow": {0: 0.011},
        }
    ]
    replay_snapshot = copy.deepcopy(replay)
    predictions_snapshot = copy.deepcopy(predictions)

    build_dpl_calibration_loss_report(replay, predictions)

    assert replay == replay_snapshot
    assert predictions == predictions_snapshot


def test_input_mutation_after_build_does_not_affect_report() -> None:
    frame = ShadowReplayFrame(
        timestamp=0.0,
        node_pressure={1: 30.0},
    )
    replay = _replay_from_frames((frame,))
    predictions = [{"node_pressure": {1: 31.0}}]

    report = build_dpl_calibration_loss_report(replay, predictions)
    # Mutate the input prediction dict after build.
    predictions[0]["node_pressure"][1] = 999.0  # type: ignore[index]

    assert report.residuals[0].predicted == pytest.approx(31.0)
    assert report.residuals[0].residual == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 14. Compatibility with Sprint 35 build_shadow_replay_dataset
# ---------------------------------------------------------------------------


def test_compatible_with_shadow_replay_dataset_pipeline() -> None:
    network = make_pump_network()
    specs = [
        TelemetryTagSpec(
            "PT1", TELEMETRY_TARGET_NODE, 1, "pressure", "bar"
        ),
        TelemetryTagSpec(
            "FT0", TELEMETRY_TARGET_EDGE, 0, "flow", "l/s"
        ),
        TelemetryTagSpec(
            "PUMP0_SPEED",
            TELEMETRY_TARGET_EDGE,
            0,
            "pump_speed",
            "percent",
            role=TELEMETRY_ROLE_CONTROL_INPUT,
        ),
    ]
    tag_map = build_telemetry_tag_map(specs, network)
    rows = [
        {
            "timestamp": "2026-05-23T00:00:00Z",
            "PT1": 1.0,            # 1 bar = 10.197... m
            "FT0": 25.0,           # 25 L/s = 0.025 m3/s
            "PUMP0_SPEED": 80.0,   # 80% → 0.80
        }
    ]
    replay = build_shadow_replay_dataset(rows, tag_map)
    assert len(replay.frames) == 1
    frame = replay.frames[0]
    predictions = [
        {
            "node_pressure": {1: frame.node_pressure[1] + 0.5},
            "edge_flow": {0: frame.edge_flow[0] * 1.10},
            "edge_pump_speed": {0: 0.75},
        }
    ]
    report = build_dpl_calibration_loss_report(replay, predictions)

    assert report.observation_count == 3
    # Residual for node_pressure is exactly the offset we added.
    pressure_residual = next(
        r for r in report.residuals if r.axis == TELEMETRY_AXIS_NODE_PRESSURE
    )
    assert pressure_residual.residual == pytest.approx(0.5)


def test_shadow_replay_with_no_observations_is_no_op() -> None:
    # An empty TelemetryTagMap and empty rows produce an empty Sprint
    # 35 dataset; the calibration report on it must be empty too.
    network = make_branch_network()
    tag_map = build_telemetry_tag_map([], network)
    replay = build_shadow_replay_dataset([], tag_map)
    report = build_dpl_calibration_loss_report(replay, [])
    assert report.observation_count == 0
    assert report.diagnostics.errors == ()
    assert report.diagnostics.warnings == ()


# ---------------------------------------------------------------------------
# 15. No live adapter / write / control surface exposed
# ---------------------------------------------------------------------------


def test_dpl_calibration_module_exports_no_live_adapter_surface() -> None:
    forbidden_substrings = (
        "write",
        "control",
        "setpoint",
        "advisory",
        "ingest",
        "publish",
        "subscribe",
        "poll",
        "actuate",
        "open_socket",
        "open_connection",
        "mqtt",
        "opcua",
        "scada",
        "historian",
        "http",
        "train",
        "optim",
    )
    for name in dpl_calibration_module.__all__:
        symbol = getattr(dpl_calibration_module, name)
        if not callable(symbol):
            continue
        if isinstance(symbol, type):
            continue
        lname = name.lower()
        for needle in forbidden_substrings:
            assert needle not in lname, (
                f"dpl_calibration exposes callable {name!r} containing "
                f"forbidden substring {needle!r}"
            )

    for name in (
        "build_dpl_calibration_loss_report",
        "DPLCalibrationDiagnostics",
        "DPLCalibrationLossReport",
        "DPLResidual",
    ):
        assert name in dphm.__all__

    # The module must not pull in any live-ingestion / network stdlib
    # modules.
    for forbidden in ("socket", "asyncio", "ssl", "urllib", "smtplib"):
        attr = forbidden.split(".")[0]
        assert not hasattr(dpl_calibration_module, attr), (
            f"dpl_calibration unexpectedly references {forbidden!r}"
        )


# ---------------------------------------------------------------------------
# Extra: argument validation
# ---------------------------------------------------------------------------


def test_predictions_must_be_a_sequence() -> None:
    replay = _single_pressure_replay()

    def gen() -> object:
        yield {"node_pressure": {1: 31.0}}

    with pytest.raises(ValueError, match="Sequence"):
        build_dpl_calibration_loss_report(replay, gen())  # type: ignore[arg-type]


def test_predictions_string_rejected() -> None:
    replay = _single_pressure_replay()
    with pytest.raises(ValueError, match="not a string"):
        build_dpl_calibration_loss_report(replay, "")  # type: ignore[arg-type]


def test_replay_must_be_a_shadow_replay_dataset() -> None:
    with pytest.raises(ValueError, match="ShadowReplayDataset"):
        build_dpl_calibration_loss_report(
            object(),  # type: ignore[arg-type]
            [],
        )


def test_per_frame_prediction_must_be_mapping_strict() -> None:
    frame = ShadowReplayFrame(timestamp=0.0, node_pressure={1: 1.0})
    replay = _replay_from_frames((frame,))
    with pytest.raises(ValueError, match="expected Mapping"):
        build_dpl_calibration_loss_report(replay, [["not", "a", "mapping"]])  # type: ignore[list-item]


def test_per_axis_prediction_must_be_mapping_strict() -> None:
    frame = ShadowReplayFrame(timestamp=0.0, node_pressure={1: 1.0})
    replay = _replay_from_frames((frame,))
    with pytest.raises(ValueError, match="expected"):
        build_dpl_calibration_loss_report(
            replay, [{"node_pressure": [(1, 2.0)]}]  # type: ignore[list-item]
        )


def test_numeric_prediction_for_status_axis_outside_01_rejected() -> None:
    frame = ShadowReplayFrame(timestamp=0.0, node_status={1: True})
    replay = _replay_from_frames((frame,))
    with pytest.raises(ValueError, match="not coercible"):
        build_dpl_calibration_loss_report(
            replay, [{"node_status": {1: 0.5}}]
        )


def test_bool_prediction_for_numeric_axis_rejected() -> None:
    replay = _single_pressure_replay(target_id=1, observed=30.0)
    with pytest.raises(ValueError, match="not coercible"):
        build_dpl_calibration_loss_report(
            replay, [{"node_pressure": {1: True}}]
        )


def test_nan_prediction_rejected() -> None:
    replay = _single_pressure_replay()
    with pytest.raises(ValueError, match="not coercible"):
        build_dpl_calibration_loss_report(
            replay, [{"node_pressure": {1: math.nan}}]
        )


def test_inf_prediction_rejected() -> None:
    replay = _single_pressure_replay()
    with pytest.raises(ValueError, match="not coercible"):
        build_dpl_calibration_loss_report(
            replay, [{"node_pressure": {1: math.inf}}]
        )


# ---------------------------------------------------------------------------
# Extra: per-axis residual count and timestamp passthrough
# ---------------------------------------------------------------------------


def test_per_axis_aggregates_skip_axes_with_no_residuals() -> None:
    replay = _single_pressure_replay(target_id=1, observed=30.0)
    report = build_dpl_calibration_loss_report(
        replay, [{"node_pressure": {1: 31.0}}]
    )
    # Only node_pressure appears in the aggregate maps.
    assert set(report.mse_by_axis) == {TELEMETRY_AXIS_NODE_PRESSURE}
    assert set(report.mae_by_axis) == {TELEMETRY_AXIS_NODE_PRESSURE}


def test_timestamp_is_passed_through_verbatim() -> None:
    sentinel = object()
    frame = ShadowReplayFrame(timestamp=sentinel, node_pressure={0: 1.0})
    replay = _replay_from_frames((frame,))
    report = build_dpl_calibration_loss_report(
        replay, [{"node_pressure": {0: 2.0}}]
    )
    assert report.residuals[0].timestamp is sentinel


def test_dpl_axes_constants_are_complete() -> None:
    # DPL_AXES should be the union of numeric + status axes, and
    # cover the canonical axes Sprint 36 supports.
    assert set(DPL_AXES) == set(DPL_NUMERIC_AXES) | set(DPL_STATUS_AXES)
    expected = {
        TELEMETRY_AXIS_NODE_PRESSURE,
        TELEMETRY_AXIS_NODE_DEMAND,
        TELEMETRY_AXIS_NODE_LEVEL,
        TELEMETRY_AXIS_NODE_STATUS,
        TELEMETRY_AXIS_EDGE_FLOW,
        TELEMETRY_AXIS_EDGE_PUMP_SPEED,
        TELEMETRY_AXIS_EDGE_STATUS,
        TELEMETRY_AXIS_EDGE_POWER,
        TELEMETRY_AXIS_EDGE_VALVE_POSITION,
    }
    assert set(DPL_AXES) == expected
