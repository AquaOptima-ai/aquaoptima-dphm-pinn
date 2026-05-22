"""Sprint 9 timing benchmark — autograd vs. analytic Newton Jacobian.

Run from the repo root::

    python scripts/sprint9_bench.py

Prints a table of grid size, autograd vs. analytic best-of-N runtime,
and the analytic speedup ratio. Not part of the test suite; used to
populate ``SPRINT9_REPORT.md``.
"""

from __future__ import annotations

import time

from aquaoptima.dphm import make_grid_network, newton_solve


GRIDS = [(5, 5), (7, 8), (8, 8), (10, 10), (12, 12)]


def _best_of(network, mode: str, repeats: int = 3) -> tuple[float, int]:
    best = float("inf")
    iters = 0
    for _ in range(repeats):
        t0 = time.perf_counter()
        res = newton_solve(network, max_iterations=200, tol=1e-6, jacobian_mode=mode)
        dt = time.perf_counter() - t0
        if not res.converged:
            return float("nan"), -1
        if dt < best:
            best = dt
            iters = res.iterations
    return best, iters


def main() -> None:
    print(
        f"{'grid':<8} {'nodes':>6} {'edges':>6} {'iters':>6} "
        f"{'autograd_ms':>13} {'analytic_ms':>13} {'speedup':>8}"
    )
    for r, c in GRIDS:
        net = make_grid_network(rows=r, cols=c, seed=0)
        # warm-up
        newton_solve(net, max_iterations=200, tol=1e-6, jacobian_mode="autograd")
        newton_solve(net, max_iterations=200, tol=1e-6, jacobian_mode="analytic")

        t_a, _ = _best_of(net, "autograd", repeats=3)
        t_b, iters = _best_of(net, "analytic", repeats=3)
        sp = t_a / t_b if t_b > 0 else float("nan")
        print(
            f"{r}x{c:<6} {net.num_nodes:>6} {net.num_edges:>6} {iters:>6} "
            f"{t_a*1e3:>13.2f} {t_b*1e3:>13.2f} {sp:>7.2f}x"
        )


if __name__ == "__main__":
    main()
