"""Sprint 7 — Larger-batch science gate + timing metrics.

Re-runs the sensor-only vs sensor+physics ablation at a Sprint 7 batch
size (``B=8``) and asserts the same conservative separation bar used
by Sprint 5 / Sprint 6 (sensor+physics drives the physics residual at
least 10x below sensor-only). The harness also records new timing /
convergence summary fields so downstream tooling can compare runs at
different batch sizes without re-running training.
"""

from __future__ import annotations

import math

import pytest

from aquaoptima.models.lambda_scheduler import LinearRampLambda
from aquaoptima.training.ablations import run_ablation


_GATE_SEED = 0
_GATE_ITERS = 60
_GATE_NUM_STEPS = 48
_GATE_WINDOW = 32
_GATE_BATCH = 8
_GATE_WARMUP = dict(start=0.0, end=1e-4, ramp_steps=20)


def _run_pair(batch_size: int) -> tuple[dict, dict]:
    so = run_ablation(
        mode="sensor_only",
        num_iterations=_GATE_ITERS,
        seed=_GATE_SEED,
        fixture="branch",
        data="physics_consistent",
        num_steps=_GATE_NUM_STEPS,
        window=_GATE_WINDOW,
        batch_size=batch_size,
    )
    sp = run_ablation(
        mode="sensor_plus_physics",
        num_iterations=_GATE_ITERS,
        seed=_GATE_SEED,
        fixture="branch",
        data="physics_consistent",
        lambda_physics_schedule=LinearRampLambda(**_GATE_WARMUP),
        num_steps=_GATE_NUM_STEPS,
        window=_GATE_WINDOW,
        batch_size=batch_size,
    )
    return so, sp


def test_sprint7_science_gate_b8_sensor_plus_physics_wins() -> None:
    so, sp = _run_pair(_GATE_BATCH)
    so_phys = so["summary"]["final_physics"]
    sp_phys = sp["summary"]["final_physics"]
    assert sp_phys < so_phys, (
        f"sensor_plus_physics did not reduce physics residual at B={_GATE_BATCH} "
        f"(sensor_only={so_phys}, sensor_plus_physics={sp_phys})"
    )
    assert sp_phys < 0.1 * so_phys, (
        f"science gate margin too small at B={_GATE_BATCH}: "
        f"sensor_only={so_phys}, sensor_plus_physics={sp_phys}"
    )


def test_sprint7_run_ablation_reports_timing_fields() -> None:
    result = run_ablation(
        mode="sensor_only",
        num_iterations=3,
        seed=0,
        fixture="branch",
        data="physics_consistent",
        batch_size=_GATE_BATCH,
    )
    summary = result["summary"]
    assert "elapsed_seconds" in summary
    assert summary["elapsed_seconds"] >= 0.0
    assert math.isfinite(summary["elapsed_seconds"])
    assert result["batch_size"] == _GATE_BATCH
    # initial_lambda_physics is already part of the summary; final_data and
    # final_physics complete the convergence picture.
    assert "final_data" in summary
    assert "final_physics" in summary
    assert "initial_lambda_physics" in summary
    assert "final_lambda_physics" in summary


def test_sprint7_run_ablation_records_batch_size() -> None:
    result = run_ablation(
        mode="sensor_plus_physics",
        num_iterations=2,
        seed=0,
        fixture="branch",
        data="physics_consistent",
        batch_size=_GATE_BATCH,
        lambda_physics_schedule=LinearRampLambda(**_GATE_WARMUP),
    )
    assert result["batch_size"] == _GATE_BATCH
    assert result["summary"]["batch_size"] == _GATE_BATCH
