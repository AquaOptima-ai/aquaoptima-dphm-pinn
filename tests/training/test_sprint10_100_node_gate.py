"""Sprint 10 — 100-node science gate on the 10x10 grid.

Re-runs the sensor-only vs sensor+physics ablation on the larger
10x10 = 100-node / 180-edge grid fixture, using the Sprint 9
analytic-Jacobian Newton solver to make telemetry generation tractable
inside the automated test budget. Gate bar is the same 10x conservative
separation used since Sprint 5 (sensor+physics drives the physics
residual to <10% of sensor-only).

Runtime notes
-------------

* Module-scoped fixtures: the network and physics-consistent telemetry
  are generated exactly once and shared across every assertion below.
* ``jacobian_mode="analytic"`` is required here — the autograd path is
  roughly 20x slower on the 10x10 grid (see ``SPRINT9_REPORT.md``).
* The two ablation arms use the same dataset / features / sensor mask
  to keep the comparison apples-to-apples; only ``lambda_physics``
  differs.
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
from aquaoptima.training.train import TrainConfig, train_loop


_GATE_SEED = 0
_GATE_ITERS = 60
_GATE_NUM_STEPS = 32
_GATE_WINDOW = 24
_GATE_BATCH = 8
_GATE_ROWS = 10
_GATE_COLS = 10
_GATE_WARMUP = dict(start=0.0, end=1e-4, ramp_steps=20)


# ---------------------------------------------------------------------------
# shared fixtures (module-scoped so telemetry is generated once)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def grid_net():
    """10x10 = 100 nodes / 180 edges — the Sprint 10 target fixture."""
    return make_grid_network(rows=_GATE_ROWS, cols=_GATE_COLS, seed=_GATE_SEED)


@pytest.fixture(scope="module")
def grid_series(grid_net):
    return generate_physics_consistent_telemetry(
        grid_net,
        num_steps=_GATE_NUM_STEPS,
        seed=_GATE_SEED,
        window=_GATE_WINDOW,
        solver_tol=1e-6,
        jacobian_mode="analytic",
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
# topology sanity
# ---------------------------------------------------------------------------


def test_sprint10_grid_is_100_nodes(grid_net) -> None:
    assert grid_net.num_nodes == 100
    assert grid_net.num_edges == 180
    assert int(grid_net.fixed_head_mask.sum().item()) == 1


# ---------------------------------------------------------------------------
# 100-node batched residual at B=8
# ---------------------------------------------------------------------------


def test_sprint10_batched_residual_on_100_node_grid(grid_net) -> None:
    """Sprint 10 — batched residual must work at ``B>=8`` on the 10x10 grid.

    Asserts (a) the contract shape ``[B, num_free + num_edges]``,
    (b) every element finite, and (c) for ``B=8`` the batched residual
    equals the stacked unbatched residual within float64 rounding.
    """
    heads0, flows0 = initial_guess(grid_net, dtype=torch.float64)
    B = 8
    heads = heads0.unsqueeze(0).expand(B, -1).contiguous()
    flows = flows0.unsqueeze(0).expand(B, -1).contiguous()

    r_batched = assemble_residuals_batched(grid_net, heads, flows)
    assert r_batched.shape == (B, grid_net.num_free_nodes + grid_net.num_edges)
    assert torch.isfinite(r_batched).all().item()

    # Full parity against stacked unbatched residuals: same heads/flows
    # in every batch row -> every row of r_batched must be identical to
    # the per-row unbatched call.
    from aquaoptima.dphm import assemble_residuals

    r_single = assemble_residuals(grid_net, heads0, flows0)
    for b in range(B):
        assert torch.allclose(r_batched[b], r_single, atol=1e-12, rtol=0.0)


# ---------------------------------------------------------------------------
# science gate
# ---------------------------------------------------------------------------


def test_sprint10_100_node_science_gate_sensor_plus_physics_wins(
    grid_net, grid_series
) -> None:
    """Sprint 10 — sensor+physics must beat sensor_only on the 100-node grid.

    Same conservative 10x separation bar as Sprint 5-8 — the Sprint 9
    Newton speedup is what makes this gate tractable inside the
    automated test budget.
    """
    so = _run_arm(mode="sensor_only", grid_net=grid_net, grid_series=grid_series)
    sp = _run_arm(
        mode="sensor_plus_physics", grid_net=grid_net, grid_series=grid_series
    )

    so_phys = so["summary"]["final_physics"]
    sp_phys = sp["summary"]["final_physics"]
    assert math.isfinite(so_phys) and math.isfinite(sp_phys)
    assert sp_phys < so_phys, (
        f"sensor_plus_physics did not reduce 100-node physics residual "
        f"(sensor_only={so_phys}, sensor_plus_physics={sp_phys})"
    )
    assert sp_phys < 0.1 * so_phys, (
        f"100-node science gate margin too small: sensor_only={so_phys}, "
        f"sensor_plus_physics={sp_phys}"
    )


# ---------------------------------------------------------------------------
# bounded smoke gate — short variant guarding against runtime regressions
# ---------------------------------------------------------------------------


def test_sprint10_100_node_smoke_gate(grid_net, grid_series) -> None:
    """A short (20-iteration) sensor+physics arm must still finish finite.

    The full 60-iteration science gate above is the real assertion; this
    smoke variant exists so a Sprint 11 regression that breaks training
    on the 100-node grid is caught quickly with a clear error message.
    """
    sp = _run_arm(
        mode="sensor_plus_physics",
        grid_net=grid_net,
        grid_series=grid_series,
        iters=20,
    )
    summary = sp["summary"]
    assert math.isfinite(summary["final_physics"])
    assert math.isfinite(summary["final_data"])
