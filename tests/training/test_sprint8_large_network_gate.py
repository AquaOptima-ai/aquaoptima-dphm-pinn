"""Sprint 8 — Larger-network science gate + scaling timing.

Re-runs the sensor-only vs sensor+physics ablation on a deterministic
larger fixture (:func:`make_grid_network`) instead of the toy
branch / single_loop / pump networks. The gate keeps the same
conservative separation bar used by Sprint 5-7 (sensor+physics drives
the physics residual to <10% of sensor-only).

Runtime notes
-------------

The Sprint 1-2 Newton solver uses a dense Jacobian, so building
physics-consistent telemetry for an O(50) node grid is the bottleneck
(roughly an order of magnitude slower per timestep than the toy
fixtures). To keep this test under a few seconds, we generate one
shared :class:`TelemetrySeries` (module-scoped fixture) and call
:func:`train_loop` directly with the two lambda schedules — instead of
two independent :func:`run_ablation` calls that would each regenerate
telemetry from scratch.

The harness change in ``src/aquaoptima/training/ablations.py`` still
exposes ``fixture="grid"`` for callers that want the
regenerate-every-call behavior (e.g. one-off manual runs documented in
``SPRINT8_REPORT.md``).
"""

from __future__ import annotations

import math
import time

import pytest
import torch

from aquaoptima.dataio import WindowDataset
from aquaoptima.dataio.telemetry import generate_physics_consistent_telemetry
from aquaoptima.dphm import (
    assemble_residuals_batched,
    initial_guess,
    make_grid_network,
)
from aquaoptima.models import DPHMPINN
from aquaoptima.models.lambda_scheduler import FixedLambda, LinearRampLambda
from aquaoptima.topology import build_graph_features, sensor_mask_from_indices
from aquaoptima.training.ablations import FIXTURES
from aquaoptima.training.train import TrainConfig, train_loop


_GATE_SEED = 0
_GATE_ITERS = 60
_GATE_NUM_STEPS = 48
_GATE_WINDOW = 32
_GATE_BATCH = 8
_GATE_WARMUP = dict(start=0.0, end=1e-4, ramp_steps=20)


# ---------------------------------------------------------------------------
# shared fixtures (module-scoped so telemetry is generated once)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def grid_net():
    # 7x8 = 56 nodes, 97 edges — sits in the O(50-200) target range.
    return make_grid_network(rows=7, cols=8, seed=_GATE_SEED)


@pytest.fixture(scope="module")
def grid_series(grid_net):
    return generate_physics_consistent_telemetry(
        grid_net,
        num_steps=_GATE_NUM_STEPS,
        seed=_GATE_SEED,
        window=_GATE_WINDOW,
        solver_tol=1e-6,
    )


def _run_arm(
    *,
    mode: str,
    grid_net,
    grid_series,
    iters: int = _GATE_ITERS,
    batch_size: int = _GATE_BATCH,
) -> dict:
    torch.manual_seed(_GATE_SEED)
    sensor_mask = sensor_mask_from_indices(
        grid_net.num_nodes,
        [0, grid_net.num_nodes // 2, grid_net.num_nodes - 1],
    )
    features = build_graph_features(grid_net, sensor_mask=sensor_mask)
    dataset = WindowDataset(grid_series, window=_GATE_WINDOW)

    model = DPHMPINN(
        node_in_dim=features.node_feature_dim,
        edge_in_dim=features.edge_feature_dim,
        seq_in_dim=dataset.node_feature_dim,
        hidden_dim=16,
        force_fallback=True,
    )
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)

    if mode == "sensor_only":
        lam_physics = FixedLambda(0.0)
    elif mode == "sensor_plus_physics":
        lam_physics = LinearRampLambda(**_GATE_WARMUP)
    else:
        raise ValueError(f"unknown mode {mode!r}")

    config = TrainConfig(
        num_iterations=iters,
        lambda_data=FixedLambda(1.0),
        lambda_physics=lam_physics,
        batch_size=batch_size,
    )

    t0 = time.perf_counter()
    metrics = train_loop(
        model=model,
        dataset=dataset,
        features=features,
        network=grid_net,
        optimizer=optimizer,
        config=config,
    )
    elapsed = time.perf_counter() - t0
    metrics.elapsed_seconds = float(elapsed)
    metrics.batch_size = int(batch_size)
    return {"mode": mode, "summary": metrics.summary()}


# ---------------------------------------------------------------------------
# harness extension visibility
# ---------------------------------------------------------------------------


def test_grid_fixture_is_registered_in_ablation_harness() -> None:
    assert "grid" in FIXTURES


# ---------------------------------------------------------------------------
# science gate
# ---------------------------------------------------------------------------


def test_sprint8_grid_science_gate_sensor_plus_physics_wins(
    grid_net, grid_series
) -> None:
    so = _run_arm(mode="sensor_only", grid_net=grid_net, grid_series=grid_series)
    sp = _run_arm(
        mode="sensor_plus_physics", grid_net=grid_net, grid_series=grid_series
    )

    so_phys = so["summary"]["final_physics"]
    sp_phys = sp["summary"]["final_physics"]
    assert math.isfinite(so_phys) and math.isfinite(sp_phys)
    assert sp_phys < so_phys, (
        f"sensor_plus_physics did not reduce grid physics residual "
        f"(sensor_only={so_phys}, sensor_plus_physics={sp_phys})"
    )
    assert sp_phys < 0.1 * so_phys, (
        f"grid science gate margin too small: sensor_only={so_phys}, "
        f"sensor_plus_physics={sp_phys}"
    )


# ---------------------------------------------------------------------------
# residual-assembly scaling timing
# ---------------------------------------------------------------------------


def test_sprint8_batched_residual_scales_to_larger_batch(grid_net) -> None:
    """Sanity check: the batched residual handles ``B in {1, 8, 16}`` on the
    larger fixture without producing NaN/Inf and without blowing up
    wall time. Wall-time numbers are dumped to ``SPRINT8_REPORT.md``;
    here we just assert the contract still holds at scale.
    """
    heads0, flows0 = initial_guess(grid_net, dtype=torch.float64)
    for B in (1, 8, 16):
        heads = heads0.unsqueeze(0).expand(B, -1).contiguous()
        flows = flows0.unsqueeze(0).expand(B, -1).contiguous()
        r = assemble_residuals_batched(grid_net, heads, flows)
        assert r.shape == (B, grid_net.num_free_nodes + grid_net.num_edges)
        assert torch.isfinite(r).all().item()
