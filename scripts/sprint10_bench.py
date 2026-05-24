"""Sprint 10 timing benchmark — physics-consistent telemetry generation
across grid sizes, using the analytic Jacobian Newton solver.

Run from the repo root::

    python scripts/sprint10_bench.py

Prints a table of grid size, residual norm, and wall-clock to generate
a 32-step physics-consistent telemetry series at each grid size. Not
part of the test suite; used to populate the timing table in
``SPRINT10_REPORT.md``.
"""

from __future__ import annotations

import time

import torch

from aquaoptima.dataio.telemetry import generate_physics_consistent_telemetry
from aquaoptima.dphm import (
    assemble_residuals,
    make_grid_network,
    newton_solve,
)
from dataclasses import replace


GRIDS = [(7, 8), (8, 8), (10, 10), (12, 12)]
NUM_STEPS = 32
WINDOW = 24
SEED = 0
SOLVER_TOL = 1e-7


def _max_residual_norm(net, series) -> float:
    worst = 0.0
    for t in range(series.num_steps):
        net_t = replace(net, demands=series.demand[t].to(torch.float64))
        r = assemble_residuals(
            net_t,
            series.pressure[t].to(torch.float64),
            series.flow[t].to(torch.float64),
        )
        worst = max(worst, float(torch.linalg.vector_norm(r).item()))
    return worst


def _bench_one(rows: int, cols: int) -> dict:
    net = make_grid_network(rows=rows, cols=cols, seed=SEED)
    # warm-up: prime the analytic Newton path + incidence cache.
    newton_solve(
        net, max_iterations=200, tol=SOLVER_TOL, jacobian_mode="analytic"
    )

    t0 = time.perf_counter()
    series = generate_physics_consistent_telemetry(
        net,
        num_steps=NUM_STEPS,
        seed=SEED,
        window=WINDOW,
        solver_tol=SOLVER_TOL,
        jacobian_mode="analytic",
    )
    dt = time.perf_counter() - t0

    worst = _max_residual_norm(net, series)
    return {
        "rows": rows,
        "cols": cols,
        "nodes": net.num_nodes,
        "edges": net.num_edges,
        "total_s": dt,
        "per_step_ms": dt * 1000.0 / NUM_STEPS,
        "worst_residual": worst,
    }


def main() -> None:
    print(
        f"{'grid':<8} {'nodes':>6} {'edges':>6} "
        f"{'total_s':>10} {'per_step_ms':>13} {'max_residual':>14}"
    )
    for r, c in GRIDS:
        row = _bench_one(r, c)
        print(
            f"{r}x{c:<6} {row['nodes']:>6} {row['edges']:>6} "
            f"{row['total_s']:>10.3f} {row['per_step_ms']:>13.2f} "
            f"{row['worst_residual']:>14.2e}"
        )


if __name__ == "__main__":
    main()
