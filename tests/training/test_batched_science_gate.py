"""Sprint 6 — Batched science gate.

Re-run the Sprint 5 sensor-only-vs-sensor+physics gate under the
Sprint 6 batched training path (``batch_size=4``). The gate is
intentionally conservative: we require sensor+physics to reduce the
physics residual versus sensor-only by *at least* an order of
magnitude — the same separation bar the unbatched gate held to in
Sprint 5 — which keeps CI reliable across hardware.

We also assert that the harness now records the ``batch_size`` it ran
under, so downstream analysis can distinguish unbatched vs batched
runs.
"""

from __future__ import annotations

import pytest

from aquaoptima.models.lambda_scheduler import LinearRampLambda
from aquaoptima.training.ablations import run_ablation


_GATE_SEED = 0
_GATE_ITERS = 60
_GATE_NUM_STEPS = 48
_GATE_WINDOW = 32
_GATE_BATCH = 4
_GATE_WARMUP = dict(start=0.0, end=1e-4, ramp_steps=20)


def _run_batched_pair(fixture: str) -> tuple[dict, dict]:
    so = run_ablation(
        mode="sensor_only",
        num_iterations=_GATE_ITERS,
        seed=_GATE_SEED,
        fixture=fixture,
        data="physics_consistent",
        num_steps=_GATE_NUM_STEPS,
        window=_GATE_WINDOW,
        batch_size=_GATE_BATCH,
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
        batch_size=_GATE_BATCH,
    )
    return so, sp


def test_run_ablation_records_batch_size() -> None:
    result = run_ablation(
        mode="sensor_only",
        num_iterations=2,
        seed=0,
        fixture="branch",
        data="physics_consistent",
        batch_size=2,
    )
    assert result["batch_size"] == 2


def test_batched_sensor_plus_physics_improves_physics_on_branch() -> None:
    so, sp = _run_batched_pair("branch")
    so_phys = so["summary"]["final_physics"]
    sp_phys = sp["summary"]["final_physics"]
    assert sp_phys < so_phys, (
        f"sensor_plus_physics did not reduce batched physics residual "
        f"(sensor_only={so_phys}, sensor_plus_physics={sp_phys})"
    )
    assert sp_phys < 0.1 * so_phys, (
        f"batched improvement margin too small: sensor_only={so_phys}, "
        f"sensor_plus_physics={sp_phys}"
    )


def test_batched_b1_recovers_unbatched_gate() -> None:
    """A batched ``B=1`` run should reproduce the Sprint 5 separation on
    the branch fixture — confirming the new code path is just a wrapper
    around the legacy semantics."""
    so = run_ablation(
        mode="sensor_only",
        num_iterations=_GATE_ITERS,
        seed=_GATE_SEED,
        fixture="branch",
        data="physics_consistent",
        num_steps=_GATE_NUM_STEPS,
        window=_GATE_WINDOW,
        batch_size=1,
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
        batch_size=1,
    )
    assert sp["summary"]["final_physics"] < 0.1 * so["summary"]["final_physics"]
