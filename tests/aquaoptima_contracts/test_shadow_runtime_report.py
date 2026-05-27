"""TDD — shadow runtime report SDK projections (Sprint 42).

Acceptance: SDK ``ShadowRuntimeStepReport`` / ``ShadowRuntimeReport``
/ ``ShadowRuntimeDiagnostics`` types capture the *shape* of the
Phase 1 Sprint 38 report. The harness driver (``run_shadow_runtime``)
remains in ``aquaoptima.dphm.shadow_runtime``.
"""

from __future__ import annotations

import pytest

from aquaoptima_contracts import (
    ContractError,
    ShadowRuntimeDiagnostics,
    ShadowRuntimeReport,
    ShadowRuntimeStepReport,
    dump_canonical_json,
    load_canonical_json,
)


def test_step_report_minimal_round_trip() -> None:
    step = ShadowRuntimeStepReport(
        frame_index=0,
        timestamp="0.0",
        observation_counts={"node_pressure": 2, "edge_flow": 2},
    )
    decoded = load_canonical_json(dump_canonical_json(step))
    assert decoded["frame_index"] == 0
    assert decoded["observation_counts"]["node_pressure"] == 2
    restored = ShadowRuntimeStepReport.from_dict(decoded)
    assert restored == step


def test_step_report_rejects_negative_frame_index() -> None:
    with pytest.raises(ContractError):
        ShadowRuntimeStepReport(frame_index=-1, timestamp="0.0")


def test_step_report_rejects_unknown_axis_in_counts() -> None:
    with pytest.raises(ContractError):
        ShadowRuntimeStepReport(
            frame_index=0,
            timestamp="0.0",
            observation_counts={"not_an_axis": 1},
        )


def test_step_report_rejects_negative_counts() -> None:
    with pytest.raises(ContractError):
        ShadowRuntimeStepReport(
            frame_index=0,
            timestamp="0.0",
            observation_counts={"node_pressure": -1},
        )


def test_step_report_with_mse_and_decisions_round_trips() -> None:
    step = ShadowRuntimeStepReport(
        frame_index=2,
        timestamp="2.0",
        observation_counts={"node_pressure": 2},
        prediction_axes=("node_pressure",),
        prediction_counts={"node_pressure": 2},
        observation_count=2,
        mse_by_axis={"node_pressure": 0.04},
        mae_by_axis={"node_pressure": 0.2},
        accepted_count=1,
        rejected_count=0,
    )
    decoded = load_canonical_json(dump_canonical_json(step))
    restored = ShadowRuntimeStepReport.from_dict(decoded)
    assert restored == step


def test_runtime_report_minimal_round_trip() -> None:
    step = ShadowRuntimeStepReport(frame_index=0, timestamp="0.0")
    report = ShadowRuntimeReport(steps=(step,), frame_count=1)
    decoded = load_canonical_json(dump_canonical_json(report))
    assert decoded["frame_count"] == 1
    restored = ShadowRuntimeReport.from_dict(decoded)
    assert restored == report


def test_runtime_report_rejects_inconsistent_frame_count() -> None:
    step = ShadowRuntimeStepReport(frame_index=0, timestamp="0.0")
    with pytest.raises(ContractError):
        ShadowRuntimeReport(steps=(step,), frame_count=2)


def test_runtime_report_diagnostics_round_trip() -> None:
    diagnostics = ShadowRuntimeDiagnostics(
        warnings=("frame 0 had no proposals",),
        errors=(),
    )
    report = ShadowRuntimeReport(diagnostics=diagnostics)
    decoded = load_canonical_json(dump_canonical_json(report))
    restored = ShadowRuntimeReport.from_dict(decoded)
    assert restored == report


def test_step_report_to_dict_does_not_carry_setpoint_field() -> None:
    step = ShadowRuntimeStepReport(frame_index=0, timestamp="0.0")
    raw = dump_canonical_json(step)
    # Defensive check: the SDK projection never models a setpoint /
    # write / control field, even as an optional. (The forbidden
    # vocabulary scan catches the token form, this asserts the field
    # name does not exist in the projection JSON.)
    decoded = load_canonical_json(raw)
    for key in decoded:
        assert "setpoint" not in key
        assert "write" not in key
        assert "control" not in key
