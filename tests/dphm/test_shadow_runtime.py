"""Sprint 38 — shadow-mode runtime harness.

Sprint 38 wires the Sprint 35 :class:`ShadowReplayDataset`, the Sprint
36 :class:`DPLCalibrationLossReport` builder, and the Sprint 37
:class:`AdvisoryContract` / :func:`evaluate_advisory_proposals`
evaluator into a single typed, offline / read-only / no-write /
no-control runtime *audit* harness.

These tests cover, in order:

1. Public exports (re-exported via ``aquaoptima.dphm``).
2. Frozen dataclass surface.
3. Default-constructed dataclasses are constructible.
4. Minimal run over an empty replay produces an empty report.
5. Minimal run over a populated replay with predictions produces
   a deterministic per-frame step report.
6. Loss-report integration: the run's loss report equals the one
   produced by :func:`build_dpl_calibration_loss_report` directly.
7. Per-step report shape: timestamps, observation counts, prediction
   counts, residual indexing, per-frame MSE / MAE.
8. Per-step ordering matches replay frame order.
9. ``proposals_by_frame`` path integrates with the advisory contract.
10. ``proposal_builder`` callback path integrates with the advisory
    contract.
11. Both proposal sources supplied → :class:`ValueError`.
12. Proposals without a contract → run warning, no decisions.
13. Strict / non-strict diagnostics for malformed proposal sources.
14. Deterministic ordering of advisory decisions (frame order then
    per-frame input order).
15. Type-check raises (``replay`` / ``advisory_contract`` /
    ``proposal_builder`` / ``proposals_by_frame`` / ``proposals_by_frame``
    length mismatch).
16. No live adapter / write / control / setpoint substrings in module
    source or ``__all__``.
17. Docs / report contain safety-boundary and API evidence.
18. Run is repeat-stable on the same inputs.
"""

from __future__ import annotations

import copy
import dataclasses
import math
from pathlib import Path

import pytest

from aquaoptima.dphm import (
    ADVISORY_AXIS_PUMP_SPEED,
    ADVISORY_STATUS_ACCEPTED,
    ADVISORY_STATUS_REJECTED,
    AdvisoryContract,
    AdvisoryDecision,
    AdvisoryProposal,
    AdvisoryRule,
    DPLCalibrationLossReport,
    DPLResidual,
    Network,
    ShadowReplayDataset,
    ShadowReplayDiagnostics,
    ShadowReplayFrame,
    ShadowRuntimeDiagnostics,
    ShadowRuntimeReport,
    ShadowRuntimeStepReport,
    TELEMETRY_AXIS_EDGE_FLOW,
    TELEMETRY_AXIS_EDGE_PUMP_SPEED,
    TELEMETRY_AXIS_NODE_PRESSURE,
    TELEMETRY_ROLE_CONTROL_INPUT,
    TELEMETRY_TARGET_EDGE,
    TELEMETRY_TARGET_NODE,
    TelemetryTagMap,
    TelemetryTagSpec,
    build_advisory_contract,
    build_dpl_calibration_loss_report,
    build_shadow_replay_dataset,
    build_telemetry_tag_map,
    make_pump_network,
    run_shadow_runtime,
)
import aquaoptima.dphm as dphm
import aquaoptima.dphm.shadow_runtime as shadow_runtime_module


REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pump_replay(rows: int = 2) -> ShadowReplayDataset:
    """Build a Sprint 35 dataset over a small pump fixture.

    Pressure at node 1, flow at edge 1, pump speed at edge 0.
    Sprint 35 canonical units: ``m``, ``m3/s``, ``fraction``.
    """
    network = make_pump_network()
    specs = [
        TelemetryTagSpec(
            "PT_NODE1",
            TELEMETRY_TARGET_NODE,
            1,
            "pressure",
            "m",
        ),
        TelemetryTagSpec(
            "FT_EDGE1",
            TELEMETRY_TARGET_EDGE,
            1,
            "flow",
            "m3/s",
        ),
        TelemetryTagSpec(
            "PUMP_SPEED",
            TELEMETRY_TARGET_EDGE,
            0,
            "pump_speed",
            "fraction",
            role=TELEMETRY_ROLE_CONTROL_INPUT,
        ),
    ]
    tag_map = build_telemetry_tag_map(specs, network)
    rows_list: list[dict[str, object]] = []
    for i in range(rows):
        rows_list.append(
            {
                "timestamp": float(i),
                "PT_NODE1": 10.0 + float(i),
                "FT_EDGE1": 0.020 + 0.001 * i,
                "PUMP_SPEED": 0.80 + 0.01 * i,
            }
        )
    return build_shadow_replay_dataset(rows_list, tag_map)


def _predictions_matching(
    replay: ShadowReplayDataset, *, bias: float = 0.0
) -> list[dict[str, dict[int, float]]]:
    """Build a per-frame prediction sequence that matches the frame."""
    predictions: list[dict[str, dict[int, float]]] = []
    for frame in replay.frames:
        entry: dict[str, dict[int, float]] = {}
        for axis_name, frame_attr in (
            (TELEMETRY_AXIS_NODE_PRESSURE, "node_pressure"),
            (TELEMETRY_AXIS_EDGE_FLOW, "edge_flow"),
            (TELEMETRY_AXIS_EDGE_PUMP_SPEED, "edge_pump_speed"),
        ):
            obs = getattr(frame, frame_attr)
            if not obs:
                continue
            entry[axis_name] = {tid: obs[tid] + bias for tid in obs}
        predictions.append(entry)
    return predictions


def _pump_proposal(
    *,
    proposal_id: str = "P1",
    target_id: int = 0,
    proposed_value: float = 0.78,
    current_value: float | None = 0.80,
) -> AdvisoryProposal:
    return AdvisoryProposal(
        proposal_id=proposal_id,
        axis=ADVISORY_AXIS_PUMP_SPEED,
        target_id=target_id,
        proposed_value=proposed_value,
        current_value=current_value,
    )


def _pump_contract() -> AdvisoryContract:
    return build_advisory_contract(
        name="pump-envelope",
        allow_rules=[
            AdvisoryRule(
                axis=ADVISORY_AXIS_PUMP_SPEED,
                target_id=0,
                min_value=0.10,
                max_value=0.95,
                max_abs_delta=0.30,
            )
        ],
    )


# ---------------------------------------------------------------------------
# 1. Public exports
# ---------------------------------------------------------------------------


def test_shadow_runtime_public_exports() -> None:
    expected_names = (
        "ShadowRuntimeDiagnostics",
        "ShadowRuntimeReport",
        "ShadowRuntimeStepReport",
        "run_shadow_runtime",
    )
    for name in expected_names:
        assert hasattr(dphm, name), f"aquaoptima.dphm missing {name}"
        assert name in dphm.__all__, (
            f"aquaoptima.dphm.__all__ missing {name}"
        )
        assert name in shadow_runtime_module.__all__, (
            f"shadow_runtime module __all__ missing {name}"
        )


# ---------------------------------------------------------------------------
# 2. Frozen dataclasses
# ---------------------------------------------------------------------------


def test_shadow_runtime_dataclasses_are_frozen() -> None:
    replay = _pump_replay()
    predictions = _predictions_matching(replay)
    report = run_shadow_runtime(replay, predictions)
    step = report.steps[0]
    diagnostics = report.diagnostics

    for instance in (report, step, diagnostics):
        cls = type(instance)
        assert dataclasses.is_dataclass(cls)
        params = getattr(cls, "__dataclass_params__")
        assert params.frozen is True, f"{cls.__name__} must be frozen"

    with pytest.raises(dataclasses.FrozenInstanceError):
        report.frame_count = 99  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        step.frame_index = 99  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        diagnostics.warnings = ()  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 3. Default-constructed dataclasses
# ---------------------------------------------------------------------------


def test_default_shadow_runtime_dataclasses_are_constructible() -> None:
    diagnostics = ShadowRuntimeDiagnostics()
    assert diagnostics.warnings == ()
    assert diagnostics.errors == ()

    step = ShadowRuntimeStepReport(frame_index=0, timestamp=None)
    assert step.frame_index == 0
    assert step.timestamp is None
    assert step.observation_counts == {}
    assert step.prediction_axes == ()
    assert step.prediction_counts == {}
    assert step.residuals == ()
    assert step.observation_count == 0
    assert step.mse_by_axis == {}
    assert step.mae_by_axis == {}
    assert step.advisory_decisions == ()
    assert step.diagnostics == ShadowRuntimeDiagnostics()

    report = ShadowRuntimeReport()
    assert report.steps == ()
    assert isinstance(report.loss_report, DPLCalibrationLossReport)
    assert report.advisory_decisions == ()
    assert report.frame_count == 0
    assert report.observation_count == 0
    assert report.proposal_count == 0
    assert report.accepted_count == 0
    assert report.rejected_count == 0
    assert report.diagnostics == ShadowRuntimeDiagnostics()


# ---------------------------------------------------------------------------
# 4. Empty replay → empty report
# ---------------------------------------------------------------------------


def test_empty_replay_produces_empty_report() -> None:
    empty = ShadowReplayDataset()
    report = run_shadow_runtime(empty, [])
    assert report.steps == ()
    assert report.advisory_decisions == ()
    assert report.frame_count == 0
    assert report.observation_count == 0
    assert report.proposal_count == 0
    assert report.accepted_count == 0
    assert report.rejected_count == 0
    assert report.diagnostics == ShadowRuntimeDiagnostics()
    assert report.loss_report.observation_count == 0


# ---------------------------------------------------------------------------
# 5. Minimal happy-path run
# ---------------------------------------------------------------------------


def test_minimal_run_with_matching_predictions() -> None:
    replay = _pump_replay(rows=2)
    predictions = _predictions_matching(replay)
    report = run_shadow_runtime(replay, predictions)
    assert report.frame_count == 2
    assert len(report.steps) == 2
    # All residuals are zero — predictions match observations exactly.
    assert report.loss_report.weighted_mse == 0.0
    assert all(r.residual == 0.0 for r in report.loss_report.residuals)
    assert report.observation_count == report.loss_report.observation_count


# ---------------------------------------------------------------------------
# 6. Loss report integration
# ---------------------------------------------------------------------------


def test_run_reuses_dpl_calibration_loss_report_math() -> None:
    replay = _pump_replay(rows=3)
    predictions = _predictions_matching(replay, bias=0.05)
    report = run_shadow_runtime(replay, predictions)

    direct = build_dpl_calibration_loss_report(replay, predictions)
    assert report.loss_report == direct
    assert report.loss_report.observation_count == direct.observation_count
    assert report.loss_report.mse_by_axis == direct.mse_by_axis
    assert report.loss_report.mae_by_axis == direct.mae_by_axis
    assert report.loss_report.weighted_mse == direct.weighted_mse


def test_axis_weights_forwarded_to_loss_report() -> None:
    replay = _pump_replay(rows=2)
    predictions = _predictions_matching(replay, bias=0.10)
    weights = {TELEMETRY_AXIS_NODE_PRESSURE: 5.0}
    report = run_shadow_runtime(
        replay, predictions, axis_weights=weights
    )
    direct = build_dpl_calibration_loss_report(
        replay, predictions, axis_weights=weights
    )
    assert report.loss_report.weighted_mse == direct.weighted_mse


# ---------------------------------------------------------------------------
# 7. Per-step report shape
# ---------------------------------------------------------------------------


def test_step_report_carries_frame_metadata_and_axis_summaries() -> None:
    replay = _pump_replay(rows=2)
    predictions = _predictions_matching(replay, bias=0.10)
    report = run_shadow_runtime(replay, predictions)
    for frame_index, step in enumerate(report.steps):
        assert step.frame_index == frame_index
        assert step.timestamp == replay.frames[frame_index].timestamp
        # 3 axes were populated in the dataset.
        assert set(step.observation_counts.keys()) == {
            TELEMETRY_AXIS_NODE_PRESSURE,
            TELEMETRY_AXIS_EDGE_FLOW,
            TELEMETRY_AXIS_EDGE_PUMP_SPEED,
        }
        assert all(v == 1 for v in step.observation_counts.values())
        # Predictions cover the same axes.
        assert set(step.prediction_axes) == set(step.observation_counts.keys())
        assert step.prediction_counts == step.observation_counts


def test_step_residuals_index_by_frame_and_match_loss_report() -> None:
    replay = _pump_replay(rows=2)
    predictions = _predictions_matching(replay, bias=0.10)
    report = run_shadow_runtime(replay, predictions)

    flat_from_steps = tuple(r for step in report.steps for r in step.residuals)
    assert flat_from_steps == report.loss_report.residuals
    for step in report.steps:
        for r in step.residuals:
            assert r.frame_index == step.frame_index


def test_step_mse_mae_match_per_frame_aggregation() -> None:
    replay = _pump_replay(rows=2)
    predictions = _predictions_matching(replay, bias=0.10)
    report = run_shadow_runtime(replay, predictions)
    for step in report.steps:
        # Recompute MSE / MAE from the step's residuals.
        sums_sq: dict[str, float] = {}
        sums_abs: dict[str, float] = {}
        counts: dict[str, int] = {}
        for r in step.residuals:
            sums_sq[r.axis] = sums_sq.get(r.axis, 0.0) + r.residual ** 2
            sums_abs[r.axis] = sums_abs.get(r.axis, 0.0) + abs(r.residual)
            counts[r.axis] = counts.get(r.axis, 0) + 1
        for axis, n in counts.items():
            assert step.mse_by_axis[axis] == pytest.approx(sums_sq[axis] / n)
            assert step.mae_by_axis[axis] == pytest.approx(sums_abs[axis] / n)
        assert set(step.mse_by_axis.keys()) == set(counts.keys())
        assert set(step.mae_by_axis.keys()) == set(counts.keys())


# ---------------------------------------------------------------------------
# 8. Frame ordering
# ---------------------------------------------------------------------------


def test_steps_follow_replay_frame_order() -> None:
    replay = _pump_replay(rows=4)
    predictions = _predictions_matching(replay)
    report = run_shadow_runtime(replay, predictions)
    expected_timestamps = [f.timestamp for f in replay.frames]
    actual_timestamps = [s.timestamp for s in report.steps]
    assert actual_timestamps == expected_timestamps
    assert [s.frame_index for s in report.steps] == list(range(4))


# ---------------------------------------------------------------------------
# 9. proposals_by_frame path
# ---------------------------------------------------------------------------


def test_proposals_by_frame_routes_decisions_per_frame() -> None:
    replay = _pump_replay(rows=2)
    predictions = _predictions_matching(replay)
    contract = _pump_contract()
    proposals = [
        [_pump_proposal(proposal_id="F0_P0", proposed_value=0.75)],
        [
            _pump_proposal(proposal_id="F1_P0", proposed_value=0.78),
            _pump_proposal(proposal_id="F1_P1", proposed_value=0.82),
        ],
    ]
    report = run_shadow_runtime(
        replay,
        predictions,
        advisory_contract=contract,
        proposals_by_frame=proposals,
    )
    assert len(report.steps[0].advisory_decisions) == 1
    assert len(report.steps[1].advisory_decisions) == 2
    assert report.proposal_count == 3
    assert report.accepted_count == 3
    assert report.rejected_count == 0
    assert all(
        d.status == ADVISORY_STATUS_ACCEPTED
        for d in report.advisory_decisions
    )
    # Flat ordering = frame order, then per-frame input order.
    ids = [d.proposal.proposal_id for d in report.advisory_decisions]
    assert ids == ["F0_P0", "F1_P0", "F1_P1"]


def test_proposals_by_frame_rejection_propagates() -> None:
    replay = _pump_replay(rows=1)
    predictions = _predictions_matching(replay)
    contract = _pump_contract()
    # 1.10 is above max_value=0.95.
    proposals = [[_pump_proposal(proposed_value=1.10)]]
    report = run_shadow_runtime(
        replay,
        predictions,
        advisory_contract=contract,
        proposals_by_frame=proposals,
    )
    assert report.accepted_count == 0
    assert report.rejected_count == 1
    decision = report.advisory_decisions[0]
    assert decision.status == ADVISORY_STATUS_REJECTED
    assert any("max_value" in r for r in decision.violated_rules)


# ---------------------------------------------------------------------------
# 10. proposal_builder callback path
# ---------------------------------------------------------------------------


def test_proposal_builder_callback_path() -> None:
    replay = _pump_replay(rows=3)
    predictions = _predictions_matching(replay)
    contract = _pump_contract()
    call_log: list[int] = []

    def builder(
        frame_index: int, frame: ShadowReplayFrame
    ) -> list[AdvisoryProposal]:
        call_log.append(frame_index)
        # Only emit a proposal for odd frames; even frames get nothing.
        if frame_index % 2 == 0:
            return []
        return [
            _pump_proposal(
                proposal_id=f"frame{frame_index}",
                proposed_value=0.70 + 0.01 * frame_index,
            )
        ]

    report = run_shadow_runtime(
        replay,
        predictions,
        advisory_contract=contract,
        proposal_builder=builder,
    )
    assert call_log == [0, 1, 2]
    assert len(report.steps[0].advisory_decisions) == 0
    assert len(report.steps[1].advisory_decisions) == 1
    assert len(report.steps[2].advisory_decisions) == 0
    assert report.proposal_count == 1
    assert report.advisory_decisions[0].proposal.proposal_id == "frame1"


def test_proposal_builder_returning_none_means_no_proposals() -> None:
    replay = _pump_replay(rows=2)
    predictions = _predictions_matching(replay)
    contract = _pump_contract()

    def builder(
        frame_index: int, frame: ShadowReplayFrame
    ) -> None:
        return None  # type: ignore[return-value]

    report = run_shadow_runtime(
        replay,
        predictions,
        advisory_contract=contract,
        proposal_builder=builder,  # type: ignore[arg-type]
    )
    assert report.proposal_count == 0


# ---------------------------------------------------------------------------
# 11. Both proposal sources rejected
# ---------------------------------------------------------------------------


def test_both_proposal_sources_supplied_raises() -> None:
    replay = _pump_replay(rows=1)
    predictions = _predictions_matching(replay)
    contract = _pump_contract()
    with pytest.raises(ValueError, match="at most one"):
        run_shadow_runtime(
            replay,
            predictions,
            advisory_contract=contract,
            proposal_builder=lambda i, f: [],
            proposals_by_frame=[[]],
        )


# ---------------------------------------------------------------------------
# 12. Proposals without a contract → warning, no decisions
# ---------------------------------------------------------------------------


def test_proposals_without_contract_records_warning() -> None:
    replay = _pump_replay(rows=1)
    predictions = _predictions_matching(replay)
    proposals = [[_pump_proposal()]]
    report = run_shadow_runtime(
        replay,
        predictions,
        proposals_by_frame=proposals,
    )
    assert report.proposal_count == 0
    assert report.advisory_decisions == ()
    assert any(
        "no advisory_contract was provided" in w
        for w in report.diagnostics.warnings
    )


# ---------------------------------------------------------------------------
# 13. Strict / non-strict diagnostics
# ---------------------------------------------------------------------------


def test_proposal_builder_returning_non_sequence_strict_raises() -> None:
    replay = _pump_replay(rows=1)
    predictions = _predictions_matching(replay)
    contract = _pump_contract()

    def bad_builder(frame_index: int, frame: ShadowReplayFrame) -> object:
        return 12345  # not a sequence

    with pytest.raises(ValueError, match="Sequence"):
        run_shadow_runtime(
            replay,
            predictions,
            advisory_contract=contract,
            proposal_builder=bad_builder,  # type: ignore[arg-type]
        )


def test_proposal_builder_returning_non_sequence_non_strict_records_error() -> None:
    replay = _pump_replay(rows=1)
    predictions = _predictions_matching(replay)
    contract = _pump_contract()

    def bad_builder(frame_index: int, frame: ShadowReplayFrame) -> object:
        return 12345

    report = run_shadow_runtime(
        replay,
        predictions,
        advisory_contract=contract,
        proposal_builder=bad_builder,  # type: ignore[arg-type]
        strict=False,
    )
    assert report.proposal_count == 0
    assert any("Sequence" in e for e in report.diagnostics.errors)


def test_proposal_builder_raising_strict_raises() -> None:
    replay = _pump_replay(rows=1)
    predictions = _predictions_matching(replay)
    contract = _pump_contract()

    def boom(frame_index: int, frame: ShadowReplayFrame) -> list[AdvisoryProposal]:
        raise RuntimeError("nope")

    with pytest.raises(ValueError, match="RuntimeError"):
        run_shadow_runtime(
            replay,
            predictions,
            advisory_contract=contract,
            proposal_builder=boom,
        )


def test_proposal_builder_raising_non_strict_records_error() -> None:
    replay = _pump_replay(rows=1)
    predictions = _predictions_matching(replay)
    contract = _pump_contract()

    def boom(frame_index: int, frame: ShadowReplayFrame) -> list[AdvisoryProposal]:
        raise RuntimeError("nope")

    report = run_shadow_runtime(
        replay,
        predictions,
        advisory_contract=contract,
        proposal_builder=boom,
        strict=False,
    )
    assert report.proposal_count == 0
    assert any("RuntimeError" in e for e in report.diagnostics.errors)


def test_proposals_by_frame_entry_wrong_type_strict_raises() -> None:
    replay = _pump_replay(rows=2)
    predictions = _predictions_matching(replay)
    contract = _pump_contract()
    bad = [[_pump_proposal()], "not a sequence"]
    with pytest.raises(ValueError, match="Sequence"):
        run_shadow_runtime(
            replay,
            predictions,
            advisory_contract=contract,
            proposals_by_frame=bad,  # type: ignore[arg-type]
        )


def test_proposals_by_frame_entry_wrong_type_non_strict_records_error() -> None:
    replay = _pump_replay(rows=2)
    predictions = _predictions_matching(replay)
    contract = _pump_contract()
    bad = [[_pump_proposal()], 12345]
    report = run_shadow_runtime(
        replay,
        predictions,
        advisory_contract=contract,
        proposals_by_frame=bad,  # type: ignore[arg-type]
        strict=False,
    )
    assert report.proposal_count == 1
    assert any(
        "proposals_by_frame[1]" in e for e in report.diagnostics.errors
    )


def test_proposals_by_frame_length_mismatch_strict_raises() -> None:
    replay = _pump_replay(rows=2)
    predictions = _predictions_matching(replay)
    contract = _pump_contract()
    with pytest.raises(ValueError, match="frame count"):
        run_shadow_runtime(
            replay,
            predictions,
            advisory_contract=contract,
            proposals_by_frame=[[]],  # only 1 entry, 2 frames
        )


def test_proposals_by_frame_length_mismatch_non_strict_warns() -> None:
    replay = _pump_replay(rows=2)
    predictions = _predictions_matching(replay)
    contract = _pump_contract()
    report = run_shadow_runtime(
        replay,
        predictions,
        advisory_contract=contract,
        proposals_by_frame=[[_pump_proposal(proposal_id="F0")]],
        strict=False,
    )
    assert report.proposal_count == 1
    assert any("frame count" in w for w in report.diagnostics.warnings)


def test_strict_false_forwarded_to_loss_report_path() -> None:
    replay = _pump_replay(rows=2)
    # Only one prediction supplied for two frames — Sprint 36 length
    # mismatch must absorb into diagnostics in non-strict mode.
    predictions = _predictions_matching(replay)[:1]
    report = run_shadow_runtime(replay, predictions, strict=False)
    assert any(
        "predictions length" in e
        for e in report.loss_report.diagnostics.errors
    )


# ---------------------------------------------------------------------------
# 14. Deterministic ordering of advisory decisions
# ---------------------------------------------------------------------------


def test_advisory_decisions_are_deterministically_ordered() -> None:
    replay = _pump_replay(rows=3)
    predictions = _predictions_matching(replay)
    contract = _pump_contract()
    proposals = [
        [_pump_proposal(proposal_id="A0"), _pump_proposal(proposal_id="A1")],
        [],
        [
            _pump_proposal(proposal_id="C0"),
            _pump_proposal(proposal_id="C1"),
            _pump_proposal(proposal_id="C2"),
        ],
    ]
    report = run_shadow_runtime(
        replay,
        predictions,
        advisory_contract=contract,
        proposals_by_frame=proposals,
    )
    ids = [d.proposal.proposal_id for d in report.advisory_decisions]
    assert ids == ["A0", "A1", "C0", "C1", "C2"]


def test_run_is_repeat_stable() -> None:
    replay = _pump_replay(rows=2)
    predictions = _predictions_matching(replay, bias=0.05)
    contract = _pump_contract()
    proposals = [[_pump_proposal()], [_pump_proposal()]]
    a = run_shadow_runtime(
        replay,
        predictions,
        advisory_contract=contract,
        proposals_by_frame=proposals,
    )
    b = run_shadow_runtime(
        replay,
        predictions,
        advisory_contract=contract,
        proposals_by_frame=proposals,
    )
    assert a == b


# ---------------------------------------------------------------------------
# 15. Type-check raises
# ---------------------------------------------------------------------------


def test_replay_must_be_shadow_replay_dataset() -> None:
    with pytest.raises(ValueError, match="ShadowReplayDataset"):
        run_shadow_runtime(object(), [])  # type: ignore[arg-type]


def test_advisory_contract_must_be_advisory_contract_or_none() -> None:
    replay = _pump_replay(rows=1)
    predictions = _predictions_matching(replay)
    with pytest.raises(ValueError, match="AdvisoryContract"):
        run_shadow_runtime(
            replay,
            predictions,
            advisory_contract=object(),  # type: ignore[arg-type]
        )


def test_proposal_builder_must_be_callable() -> None:
    replay = _pump_replay(rows=1)
    predictions = _predictions_matching(replay)
    contract = _pump_contract()
    with pytest.raises(ValueError, match="callable"):
        run_shadow_runtime(
            replay,
            predictions,
            advisory_contract=contract,
            proposal_builder=object(),  # type: ignore[arg-type]
        )


def test_proposals_by_frame_must_be_sequence() -> None:
    replay = _pump_replay(rows=1)
    predictions = _predictions_matching(replay)
    contract = _pump_contract()
    with pytest.raises(ValueError, match="Sequence"):
        run_shadow_runtime(
            replay,
            predictions,
            advisory_contract=contract,
            proposals_by_frame=12345,  # type: ignore[arg-type]
        )


def test_proposals_by_frame_must_not_be_string() -> None:
    replay = _pump_replay(rows=1)
    predictions = _predictions_matching(replay)
    contract = _pump_contract()
    with pytest.raises(ValueError, match="not a string"):
        run_shadow_runtime(
            replay,
            predictions,
            advisory_contract=contract,
            proposals_by_frame="bad",  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# 16. No live-adapter / write / control surface in module
# ---------------------------------------------------------------------------


def test_shadow_runtime_module_exports_no_live_surface() -> None:
    forbidden_substrings = (
        "write",
        "control",
        "setpoint",
        "actuate",
        "publish",
        "subscribe",
        "ingest",
        "poll",
        "scada",
        "plc",
        "historian",
        "opcua",
        "mqtt",
        "rest_client",
        "http_client",
        "open_socket",
        "open_connection",
        "train",
        "optim",
    )
    for name in shadow_runtime_module.__all__:
        lname = name.lower()
        for needle in forbidden_substrings:
            assert needle not in lname, (
                f"shadow_runtime exposes symbol {name!r} containing "
                f"forbidden substring {needle!r}"
            )

    for forbidden in ("socket", "asyncio", "ssl", "urllib", "smtplib"):
        assert not hasattr(shadow_runtime_module, forbidden), (
            f"shadow_runtime unexpectedly references {forbidden!r}"
        )


def test_shadow_runtime_module_source_has_safety_phrases() -> None:
    source = Path(shadow_runtime_module.__file__).read_text(encoding="utf-8")
    for phrase in (
        "offline",
        "read-only",
        "no-write",
        "no-control",
        "no live OT binding",
        "no setpoint output",
        "replay/audit only",
    ):
        assert phrase in source, (
            f"shadow_runtime source must contain {phrase!r} safety phrase"
        )


def test_shadow_runtime_module_no_live_adapter_substrings_in_source() -> None:
    source = Path(shadow_runtime_module.__file__).read_text(encoding="utf-8")
    forbidden_callables = (
        "socket.socket(",
        "subprocess.Popen(",
        "urllib.request.urlopen(",
        "smtplib.SMTP(",
        "asyncio.run(",
        "open_connection(",
        "publish(",
        "subscribe(",
    )
    for needle in forbidden_callables:
        assert needle not in source, (
            f"shadow_runtime source contains forbidden call {needle!r}"
        )


# ---------------------------------------------------------------------------
# 17. Docs / report evidence
# ---------------------------------------------------------------------------


def test_docs_shadow_runtime_has_safety_boundary_and_api() -> None:
    doc = (REPO_ROOT / "docs" / "shadow-runtime.md").read_text(
        encoding="utf-8"
    )
    for phrase in (
        "offline",
        "read-only",
        "no-write",
        "no-control",
        "no live OT binding",
        "no setpoint output",
        "replay/audit only",
    ):
        assert phrase in doc, f"docs/shadow-runtime.md missing {phrase!r}"
    for name in (
        "ShadowRuntimeDiagnostics",
        "ShadowRuntimeReport",
        "ShadowRuntimeStepReport",
        "run_shadow_runtime",
    ):
        assert name in doc, f"docs/shadow-runtime.md missing API name {name!r}"


def test_sprint38_report_has_safety_boundary_and_api() -> None:
    report = (REPO_ROOT / "SPRINT38_REPORT.md").read_text(encoding="utf-8")
    for phrase in (
        "offline",
        "read-only",
        "no-write",
        "no-control",
        "no live OT binding",
        "no setpoint output",
        "replay/audit only",
    ):
        assert phrase in report, f"SPRINT38_REPORT.md missing {phrase!r}"
    for name in (
        "ShadowRuntimeDiagnostics",
        "ShadowRuntimeReport",
        "ShadowRuntimeStepReport",
        "run_shadow_runtime",
    ):
        assert name in report, f"SPRINT38_REPORT.md missing API name {name!r}"


# ---------------------------------------------------------------------------
# 18. Harness does not mutate inputs
# ---------------------------------------------------------------------------


def test_run_shadow_runtime_does_not_mutate_inputs() -> None:
    replay = _pump_replay(rows=2)
    predictions = _predictions_matching(replay, bias=0.05)
    contract = _pump_contract()
    proposals = [
        [_pump_proposal(proposal_id="F0")],
        [_pump_proposal(proposal_id="F1")],
    ]
    snapshot_predictions = copy.deepcopy(predictions)
    snapshot_proposals = copy.deepcopy(proposals)
    snapshot_contract = copy.deepcopy(contract)

    run_shadow_runtime(
        replay,
        predictions,
        advisory_contract=contract,
        proposals_by_frame=proposals,
    )

    assert predictions == snapshot_predictions
    assert proposals == snapshot_proposals
    assert contract == snapshot_contract


# ---------------------------------------------------------------------------
# Extra: integration combining loss-report-driven advisory gate.
# ---------------------------------------------------------------------------


def test_loss_report_axis_loss_gate_rejects_per_frame_proposal() -> None:
    replay = _pump_replay(rows=2)
    # Large bias → DPL pump-speed MSE > 0.001 will trip the contract.
    predictions = _predictions_matching(replay, bias=0.10)
    contract = build_advisory_contract(
        allow_rules=[
            AdvisoryRule(
                axis=ADVISORY_AXIS_PUMP_SPEED,
                target_id=0,
                min_value=0.0,
                max_value=1.0,
                max_axis_loss=0.001,
            )
        ]
    )
    proposals = [[_pump_proposal()], [_pump_proposal(proposal_id="P2")]]
    report = run_shadow_runtime(
        replay,
        predictions,
        advisory_contract=contract,
        proposals_by_frame=proposals,
    )
    assert report.rejected_count == 2
    assert report.accepted_count == 0
    for d in report.advisory_decisions:
        assert any("max_axis_loss" in r for r in d.violated_rules)
