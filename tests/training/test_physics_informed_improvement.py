"""Sprint 5 science gate: sensor + physics beats sensor-only.

On physics-consistent telemetry, the sensor-plus-physics ablation arm
should drive the dPHM physics residual lower than the sensor-only arm.
Both arms share data, model architecture, optimizer, seed, and number
of iterations — the only difference is the lambda-weighted physics
loss (with a :class:`LinearRampLambda` warmup so the physics term does
not destabilise early training).

These tests are intentionally conservative — they assert a clear,
order-of-magnitude separation rather than tiny numeric deltas, so CI
stays reliable across PyTorch / hardware variation.
"""

from __future__ import annotations

import pytest

from aquaoptima.models.lambda_scheduler import LinearRampLambda
from aquaoptima.training.ablations import (
    DATA_KINDS,
    FIXTURES,
    run_ablation,
)


# Hyperparameters chosen so the gate is reproducible and the gap is
# large; see SPRINT5_REPORT.md for the empirical separation numbers.
_GATE_SEED = 0
_GATE_ITERS = 60
_GATE_NUM_STEPS = 40
_GATE_WINDOW = 32
_GATE_WARMUP = dict(start=0.0, end=1e-4, ramp_steps=20)


def _run_pair(fixture: str) -> tuple[dict, dict]:
    so = run_ablation(
        mode="sensor_only",
        num_iterations=_GATE_ITERS,
        seed=_GATE_SEED,
        fixture=fixture,
        data="physics_consistent",
        num_steps=_GATE_NUM_STEPS,
        window=_GATE_WINDOW,
    )
    sp = run_ablation(
        mode="sensor_plus_physics",
        num_iterations=_GATE_ITERS,
        seed=_GATE_SEED,
        fixture=fixture,
        data="physics_consistent",
        lambda_physics_schedule=LinearRampLambda(**_GATE_WARMUP),
        num_steps=_GATE_NUM_STEPS,
        window=_GATE_WINDOW,
    )
    return so, sp


def test_data_and_fixture_constants_are_exposed() -> None:
    # Hard-coded contract: harness consumers can introspect the
    # supported fixtures and data kinds. Sprint 8 added the larger
    # ``grid`` fixture alongside the original Sprint 1-2 toy networks.
    assert set(FIXTURES) == {"branch", "single_loop", "pump", "grid"}
    assert set(DATA_KINDS) == {"physics_consistent", "shape_only"}


def test_ablation_harness_accepts_branch_fixture() -> None:
    result = run_ablation(
        mode="sensor_only",
        num_iterations=2,
        seed=0,
        fixture="branch",
        data="physics_consistent",
    )
    assert result["fixture"] == "branch"
    assert result["data"] == "physics_consistent"


def test_ablation_harness_accepts_single_loop_fixture() -> None:
    result = run_ablation(
        mode="sensor_only",
        num_iterations=2,
        seed=0,
        fixture="single_loop",
        data="physics_consistent",
    )
    assert result["fixture"] == "single_loop"


def test_ablation_harness_accepts_pump_fixture() -> None:
    result = run_ablation(
        mode="sensor_only",
        num_iterations=2,
        seed=0,
        fixture="pump",
        data="physics_consistent",
    )
    assert result["fixture"] == "pump"


def test_ablation_harness_rejects_unknown_fixture() -> None:
    with pytest.raises(ValueError, match="unknown fixture"):
        run_ablation(
            mode="sensor_only",
            num_iterations=1,
            seed=0,
            fixture="not_a_real_fixture",
        )


def test_ablation_harness_rejects_unknown_data_kind() -> None:
    with pytest.raises(ValueError, match="unknown data kind"):
        run_ablation(
            mode="sensor_only",
            num_iterations=1,
            seed=0,
            data="not_a_real_kind",
        )


# ---------------------------------------------------------------------------
# lambda warmup recording
# ---------------------------------------------------------------------------


def test_linear_ramp_lambda_records_a_growing_physics_weight() -> None:
    """LinearRampLambda must surface ascending per-step ``lambda_physics``
    values in the training history — otherwise the warmup is invisible
    to downstream analysis.
    """
    result = run_ablation(
        mode="sensor_plus_physics",
        num_iterations=12,
        seed=0,
        fixture="branch",
        data="physics_consistent",
        lambda_physics_schedule=LinearRampLambda(
            start=0.0, end=1e-4, ramp_steps=10
        ),
    )
    lambdas = [rec["lambda_physics"] for rec in result["history"]]
    assert lambdas[0] == pytest.approx(0.0)
    # Strictly non-decreasing during the ramp.
    for i in range(1, 10):
        assert lambdas[i] >= lambdas[i - 1]
    # End value reached at step ramp_steps and held after.
    assert lambdas[-1] == pytest.approx(1e-4)
    # Initial / final values appear in summary too.
    assert result["summary"]["initial_lambda_physics"] == pytest.approx(0.0)
    assert result["summary"]["final_lambda_physics"] == pytest.approx(1e-4)


# ---------------------------------------------------------------------------
# the science gate
# ---------------------------------------------------------------------------


def test_sensor_plus_physics_improves_physics_residual_on_branch() -> None:
    so, sp = _run_pair("branch")
    so_phys = so["summary"]["final_physics"]
    sp_phys = sp["summary"]["final_physics"]

    # Order-of-magnitude separation: sensor + physics should drive the
    # physics residual at least 10x lower than the sensor-only arm.
    assert sp_phys < so_phys, (
        f"sensor_plus_physics did not reduce physics residual "
        f"(sensor_only={so_phys}, sensor_plus_physics={sp_phys})"
    )
    assert sp_phys < 0.1 * so_phys, (
        f"improvement margin too small: sensor_only={so_phys}, "
        f"sensor_plus_physics={sp_phys}"
    )
