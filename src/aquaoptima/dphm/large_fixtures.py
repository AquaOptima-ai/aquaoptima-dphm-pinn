"""Deterministic larger synthetic / reference networks for Sprint 8.

The Sprint 1-2 fixtures (``make_branch_network``, ``make_single_loop_network``,
``make_pump_network``) intentionally use 3-4 node topologies so the
solver tests stay hand-traceable. Sprint 8 needs a network that is
materially larger — O(50-200) nodes — to validate scale behavior of
the existing residual assembly, batched residual, Newton solver, and
graph feature builder without introducing real-world EPANET assets
or field adapters.

The grid builder here:

* Lays out ``rows * cols`` nodes on a regular mesh.
* Connects every horizontally / vertically adjacent pair with a pipe
  edge, directed toward increasing index (top-to-bottom, left-to-right).
* Pins node ``(0, 0)`` as the only fixed-head reservoir.
* Assigns a small positive demand at every non-reservoir node and
  balances the reservoir to ``-sum(demands)`` so ``sum(demands) == 0``.
* Draws per-edge pipe parameters (length / diameter / c_factor) from
  a seeded uniform distribution around physically reasonable defaults.

The result is purely synthetic — no claim of field accuracy — but is
shaped like an EPANET-style distribution network the existing dPHM
solver and downstream ML pipeline can consume unchanged.
"""

from __future__ import annotations

from typing import Optional

import torch

from .network import Network


_DEFAULT_RESERVOIR_HEAD_M = 100.0


def _grid_edge_index(rows: int, cols: int) -> torch.Tensor:
    """Edge list for a ``rows x cols`` grid, directed toward higher index."""
    edges: list[tuple[int, int]] = []
    for r in range(rows):
        for c in range(cols):
            n = r * cols + c
            if c + 1 < cols:
                edges.append((n, n + 1))            # horizontal -> right
            if r + 1 < rows:
                edges.append((n, n + cols))         # vertical   -> down
    src, dst = zip(*edges)
    return torch.tensor([list(src), list(dst)], dtype=torch.long)


def make_grid_network(
    rows: int = 8,
    cols: int = 8,
    seed: int = 0,
    *,
    reservoir_head_m: float = _DEFAULT_RESERVOIR_HEAD_M,
    base_demand: float = 3.0e-3,
    demand_jitter: float = 0.5,
    length_range: tuple[float, float] = (60.0, 180.0),
    diameter_range: tuple[float, float] = (0.15, 0.30),
    c_factor_range: tuple[float, float] = (120.0, 135.0),
    with_pump: bool = False,
    pump_coeffs: Optional[list[float]] = None,
) -> Network:
    """Deterministic ``rows x cols`` synthetic distribution mesh.

    Parameters
    ----------
    rows, cols
        Mesh dimensions. ``rows * cols`` nodes will be created. The
        defaults give a 64-node grid; ``10 x 10`` gives 100 nodes, etc.
    seed
        Master seed for the parameter / demand jitter generator.
        Different seeds produce different but equally valid networks.
    reservoir_head_m
        Fixed head value pinned at node 0 (the (0, 0) corner of the grid).
    base_demand
        Nominal positive demand (m^3/s) at every non-reservoir node.
    demand_jitter
        Fractional jitter applied multiplicatively to ``base_demand``;
        e.g. ``0.5`` yields demands in roughly
        ``base_demand * [1 - 0.5/2, 1 + 0.5/2]``.
    length_range, diameter_range, c_factor_range
        Per-edge pipe parameter ranges (uniformly sampled, seeded).
    with_pump
        If True, the first edge from the reservoir is converted to a
        pump edge. Pumps inside a grid can affect solver convergence;
        the default is pipe-only so the larger fixture stays a
        reliable convergence target.
    pump_coeffs
        ``[a0, a1, a2]`` curve coefficients for the optional pump edge.
        Defaults to ``[60.0, 0.0, -2000.0]`` when ``with_pump`` is True.

    Returns
    -------
    Network
        A validated :class:`Network` suitable for
        :func:`assemble_residuals`, :func:`assemble_residuals_batched`,
        :func:`newton_solve`, and :func:`build_graph_features`.
    """
    if rows < 2 or cols < 2:
        raise ValueError(
            f"grid network requires rows >= 2 and cols >= 2, got {rows}x{cols}"
        )

    N = rows * cols
    edge_index = _grid_edge_index(rows, cols)
    E = int(edge_index.shape[1])

    gen = torch.Generator(device="cpu").manual_seed(int(seed))

    # Per-edge pipe parameters, uniformly seeded.
    def _uniform(lo: float, hi: float) -> torch.Tensor:
        return lo + (hi - lo) * torch.rand(E, generator=gen)

    lengths = _uniform(*length_range)
    diameters = _uniform(*diameter_range)
    c_factors = _uniform(*c_factor_range)

    # Per-node demand jitter on a positive baseline. Reservoir absorbs the
    # rest so ``sum(demands) == 0``. We cast to the default dtype first
    # and then re-balance so the casted tensor — the one we actually
    # hand to ``Network`` — sums to zero in its own precision.
    jitter = 1.0 + demand_jitter * (torch.rand(N, generator=gen) - 0.5)
    demands = (base_demand * jitter).to(torch.get_default_dtype())
    demands[0] = 0.0
    demands[0] = -demands.sum()

    fixed_head_mask = torch.zeros(N, dtype=torch.bool)
    fixed_head_mask[0] = True
    fixed_head_values = torch.zeros(N, dtype=torch.get_default_dtype())
    fixed_head_values[0] = float(reservoir_head_m)

    pipe_mask = torch.ones(E, dtype=torch.bool)
    pump_mask = torch.zeros(E, dtype=torch.bool)
    pump_coeffs_tensor = torch.zeros((E, 3), dtype=torch.get_default_dtype())
    pump_speeds = torch.zeros(E, dtype=torch.get_default_dtype())

    if with_pump:
        if pump_coeffs is None:
            pump_coeffs = [60.0, 0.0, -2000.0]
        if pump_coeffs[0] <= 0:
            raise ValueError(
                f"pump shut-off head a0 must be > 0, got {pump_coeffs[0]}"
            )
        # First edge leaves the reservoir; convert it to a pump.
        pipe_mask[0] = False
        pump_mask[0] = True
        pump_coeffs_tensor[0] = torch.tensor(pump_coeffs)
        pump_speeds[0] = 1.0
        # Keep a positive placeholder pipe parameters on row 0 (the pipe
        # mask is False here, so the Network "positive on pipe edges"
        # check ignores it).
        lengths[0] = 1.0
        diameters[0] = 1.0
        c_factors[0] = 1.0

    return Network(
        edge_index=edge_index,
        num_nodes=N,
        pipe_mask=pipe_mask,
        pump_mask=pump_mask,
        lengths=lengths.to(torch.get_default_dtype()),
        diameters=diameters.to(torch.get_default_dtype()),
        c_factors=c_factors.to(torch.get_default_dtype()),
        pump_coeffs=pump_coeffs_tensor,
        pump_speeds=pump_speeds,
        demands=demands.to(torch.get_default_dtype()),
        fixed_head_mask=fixed_head_mask,
        fixed_head_values=fixed_head_values,
    )


__all__ = ["make_grid_network"]
