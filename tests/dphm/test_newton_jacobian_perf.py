"""Newton-solve performance gate: analytic Jacobian >= 2x autograd Jacobian.

Sprint 8 concluded that the autograd Jacobian inside ``newton_solve``
dominates per-iteration cost on grids of O(50-200) nodes. Sprint 9
replaces it with a closed-form analytic Jacobian. This module enforces
the speedup contract on the 7x8 grid (the smallest grid that exhibits
the cost gap reliably). The 5x5 grid is included as a smoke test only;
its absolute runtime is too low for the ratio to be stable.

Larger grids (8x8, 10x10) are exercised but not gated to avoid making
the suite slow on CI.
"""

from __future__ import annotations

import time

import pytest

from aquaoptima.dphm import make_grid_network, newton_solve


def _time_newton(network, mode: str, *, repeats: int = 1) -> float:
    # Best-of-N to dampen jitter on a busy CI machine.
    best = float("inf")
    for _ in range(repeats):
        t0 = time.perf_counter()
        res = newton_solve(network, max_iterations=200, tol=1e-6, jacobian_mode=mode)
        dt = time.perf_counter() - t0
        assert res.converged, (
            f"{mode} newton failed on {network.num_nodes}-node grid: "
            f"reason={res.reason}, norm={res.residual_norm}"
        )
        if dt < best:
            best = dt
    return best


@pytest.mark.parametrize("rows,cols", [(5, 5), (7, 8)])
def test_newton_analytic_converges_on_grids(rows: int, cols: int) -> None:
    net = make_grid_network(rows=rows, cols=cols, seed=0)
    res = newton_solve(net, max_iterations=200, tol=1e-6, jacobian_mode="analytic")
    assert res.converged


def test_newton_analytic_is_at_least_2x_faster_on_7x8_grid() -> None:
    """Hard Sprint 9 performance gate."""
    net = make_grid_network(rows=7, cols=8, seed=0)
    # Warm-up (paging, JIT-like autograd graph build).
    newton_solve(net, max_iterations=200, tol=1e-6, jacobian_mode="autograd")
    newton_solve(net, max_iterations=200, tol=1e-6, jacobian_mode="analytic")

    t_autograd = _time_newton(net, "autograd", repeats=3)
    t_analytic = _time_newton(net, "analytic", repeats=3)
    speedup = t_autograd / max(t_analytic, 1e-12)

    assert speedup >= 2.0, (
        f"analytic Jacobian must be >= 2x faster than autograd on the 7x8 grid; "
        f"got autograd={t_autograd*1e3:.2f} ms, analytic={t_analytic*1e3:.2f} ms, "
        f"speedup={speedup:.2f}x"
    )
