"""Residual assembly and a Newton-style steady-state solver for small dPHM
networks.

The unknowns are partitioned as ``x = [free_heads, flows]`` where:

* ``free_heads`` are the heads at nodes whose ``fixed_head_mask`` entry is
  ``False`` (everything that is not a reservoir / boundary).
* ``flows`` are the volumetric flow rates on every directed edge.

The residual vector has matching length ``num_free_nodes + num_edges``:

* ``num_free_nodes`` mass-balance residuals (one per non-fixed node).
* ``num_edges`` energy residuals — Hazen-Williams for pipe edges, the
  affinity-style pump curve for pump edges.

The solver is intentionally conservative: dense Jacobian via
:func:`torch.autograd.functional.jacobian`, dense linear solve, no
acceleration. It is sufficient for branch / single-loop / pump fixtures
and provides structured diagnostics (see :class:`SolveResult`). It is not
yet validated against real EPANET networks — that lands in Sprint 3.
"""

from __future__ import annotations

import math
from typing import Tuple

import torch

from .hazen_williams import hazen_williams_head_loss
from .pump_affinity import pump_head_gain
from .incidence import incidence_matrix
from .network import Network
from .diagnostics import SolveFailureReason, SolveResult, classify_failure


# ---------------------------------------------------------------------------
# residual assembly
# ---------------------------------------------------------------------------


def assemble_residuals(
    network: Network, heads: torch.Tensor, flows: torch.Tensor
) -> torch.Tensor:
    """Stack mass + energy residuals into a single 1-D tensor.

    Parameters
    ----------
    network
        The ``Network`` describing topology and physical parameters.
    heads
        Per-node hydraulic head, shape ``[num_nodes]``. Fixed-head entries
        must already carry their boundary values.
    flows
        Per-edge volumetric flow rate, shape ``[num_edges]``.

    Returns
    -------
    torch.Tensor
        Shape ``[num_free_nodes + num_edges]`` — mass-balance residuals
        for free nodes first, then per-edge energy residuals.
    """
    if heads.shape != (network.num_nodes,):
        raise ValueError(
            f"heads must have shape [{network.num_nodes}], got {tuple(heads.shape)}"
        )
    if flows.shape != (network.num_edges,):
        raise ValueError(
            f"flows must have shape [{network.num_edges}], got {tuple(flows.shape)}"
        )

    A = incidence_matrix(network.edge_index, network.num_nodes).to(flows.dtype)
    mass = A @ flows - network.demands.to(flows.dtype)
    mass_free = mass[~network.fixed_head_mask]

    src = network.edge_index[0]
    dst = network.edge_index[1]
    h_u = heads[src]
    h_d = heads[dst]

    pipe_hf = hazen_williams_head_loss(
        flows,
        network.lengths.to(flows.dtype),
        network.diameters.to(flows.dtype),
        network.c_factors.to(flows.dtype),
    )
    gain = pump_head_gain(
        flows,
        network.pump_speeds.to(flows.dtype),
        network.pump_coeffs.to(flows.dtype),
    )

    pipe_residual = h_u - h_d - pipe_hf
    pump_residual = h_d - h_u - gain
    edge_residual = torch.where(network.pipe_mask, pipe_residual, pump_residual)

    return torch.cat([mass_free, edge_residual])


def assemble_residuals_batched(
    network: Network, heads: torch.Tensor, flows: torch.Tensor
) -> torch.Tensor:
    """Vectorized residual assembly across a batch axis.

    Parameters
    ----------
    network
        Fixed topology and per-edge / per-node parameters. The topology
        (incidence matrix, edge endpoints, masks, demands, fixed-head
        mask) is shared across the batch; only ``heads`` and ``flows``
        carry batch-varying state.
    heads
        Per-node head, shape ``[B, num_nodes]``. Fixed-head entries
        must already carry their boundary values for every batch row.
    flows
        Per-edge volumetric flow rate, shape ``[B, num_edges]``.

    Returns
    -------
    torch.Tensor
        Shape ``[B, num_free_nodes + num_edges]``. For ``B=1`` this is
        equal (within machine precision) to
        ``assemble_residuals(...).unsqueeze(0)`` on the same row.

    Notes
    -----
    Implementation uses a single dense incidence multiply (``flows @
    A.T`` broadcast over ``B``) for the mass-balance block and a
    single :func:`torch.where` to merge pipe- vs pump-edge energy
    residuals. There is no Python loop over the batch axis.
    """
    if heads.dim() != 2 or flows.dim() != 2:
        raise ValueError(
            "assemble_residuals_batched requires rank-2 inputs "
            f"[B, num_nodes] and [B, num_edges]; got heads={tuple(heads.shape)}, "
            f"flows={tuple(flows.shape)}"
        )
    if heads.shape[0] != flows.shape[0]:
        raise ValueError(
            "batch dimensions must match; got "
            f"heads.shape[0]={heads.shape[0]} vs flows.shape[0]={flows.shape[0]}"
        )
    if heads.shape[1] != network.num_nodes:
        raise ValueError(
            f"heads must have shape [B, {network.num_nodes}], got {tuple(heads.shape)}"
        )
    if flows.shape[1] != network.num_edges:
        raise ValueError(
            f"flows must have shape [B, {network.num_edges}], got {tuple(flows.shape)}"
        )

    dtype = flows.dtype
    A = incidence_matrix(network.edge_index, network.num_nodes).to(dtype)
    # mass[b, n] = sum_e A[n, e] * flows[b, e] - demands[n]
    mass = flows @ A.T - network.demands.to(dtype).unsqueeze(0)  # [B, N]
    mass_free = mass[:, ~network.fixed_head_mask]  # [B, num_free]

    src = network.edge_index[0]
    dst = network.edge_index[1]
    h_u = heads.index_select(1, src)  # [B, E]
    h_d = heads.index_select(1, dst)  # [B, E]

    pipe_hf = hazen_williams_head_loss(
        flows,
        network.lengths.to(dtype),
        network.diameters.to(dtype),
        network.c_factors.to(dtype),
    )  # broadcasts [E] over [B, E] -> [B, E]
    gain = pump_head_gain(
        flows,
        network.pump_speeds.to(dtype),
        network.pump_coeffs.to(dtype),
    )  # broadcasts similarly -> [B, E]

    pipe_residual = h_u - h_d - pipe_hf
    pump_residual = h_d - h_u - gain
    edge_residual = torch.where(
        network.pipe_mask.unsqueeze(0), pipe_residual, pump_residual
    )  # [B, E]

    return torch.cat([mass_free, edge_residual], dim=1)


def residual_norm(
    network: Network, heads: torch.Tensor, flows: torch.Tensor
) -> torch.Tensor:
    """Scalar L2 norm of :func:`assemble_residuals`."""
    return torch.linalg.vector_norm(assemble_residuals(network, heads, flows))


# ---------------------------------------------------------------------------
# initial guess + state packing
# ---------------------------------------------------------------------------


def initial_guess(
    network: Network, default_flow: float = 0.01, dtype: torch.dtype = torch.float64
) -> Tuple[torch.Tensor, torch.Tensor]:
    """Smooth, non-zero starting point for the Newton iteration.

    Free heads default to the mean of the fixed-head values, and every
    edge starts with a small positive flow. Both are picked so that
    Hazen-Williams head loss is well-defined and small at iteration 0.
    """
    fixed_vals = network.fixed_head_values[network.fixed_head_mask].to(dtype)
    if fixed_vals.numel() == 0:
        free_default = torch.tensor(0.0, dtype=dtype)
    else:
        free_default = fixed_vals.mean()

    heads = network.fixed_head_values.to(dtype).clone()
    heads = torch.where(
        network.fixed_head_mask,
        heads,
        torch.full_like(heads, fill_value=float(free_default.item())),
    )
    flows = torch.full((network.num_edges,), float(default_flow), dtype=dtype)
    return heads, flows


def _pack(network: Network, heads: torch.Tensor, flows: torch.Tensor) -> torch.Tensor:
    free_heads = heads[~network.fixed_head_mask]
    return torch.cat([free_heads, flows])


def _unpack(
    network: Network, x: torch.Tensor
) -> Tuple[torch.Tensor, torch.Tensor]:
    num_free = network.num_free_nodes
    free_heads = x[:num_free]
    flows = x[num_free:]

    zeros = torch.zeros(network.num_nodes, dtype=x.dtype)
    free_part = zeros.index_copy(0, network.free_node_indices, free_heads)
    fixed_part = torch.where(
        network.fixed_head_mask,
        network.fixed_head_values.to(x.dtype),
        torch.zeros_like(free_part),
    )
    heads = free_part + fixed_part
    return heads, flows


# ---------------------------------------------------------------------------
# Newton solver
# ---------------------------------------------------------------------------


def newton_solve(
    network: Network,
    *,
    max_iterations: int = 100,
    tol: float = 1e-6,
    damping: float = 1.0,
    dtype: torch.dtype = torch.float64,
) -> SolveResult:
    """Damped Newton iteration on the packed state ``x = [free_heads, flows]``.

    Uses dense :func:`torch.autograd.functional.jacobian` evaluations and a
    direct linear solve — adequate for the synthetic Sprint 2 fixtures but
    not intended for production-sized networks.

    The solver never lies about convergence: if the final residual norm
    exceeds ``tol``, ``SolveResult.converged`` is ``False`` and ``reason``
    carries the matching :class:`SolveFailureReason` value.
    """
    heads0, flows0 = initial_guess(network, dtype=dtype)
    x = _pack(network, heads0, flows0).detach()

    def f(x_: torch.Tensor) -> torch.Tensor:
        heads, flows = _unpack(network, x_)
        return assemble_residuals(network, heads, flows)

    iterations = 0
    diverged = False
    singular = False
    final_norm = float("nan")

    for it in range(1, max_iterations + 1):
        iterations = it
        r = f(x)
        n = float(torch.linalg.vector_norm(r).item())
        final_norm = n

        if math.isnan(n):
            break
        if math.isinf(n):
            diverged = True
            break
        if n <= tol:
            break

        try:
            J = torch.autograd.functional.jacobian(f, x, create_graph=False)
        except RuntimeError:
            singular = True
            break

        try:
            dx = torch.linalg.solve(J, -r)
        except RuntimeError:
            try:
                dx = torch.linalg.lstsq(J, -r.unsqueeze(-1)).solution.squeeze(-1)
            except RuntimeError:
                singular = True
                break

        if not torch.isfinite(dx).all():
            diverged = True
            break

        x = (x + damping * dx).detach()

    heads_final, flows_final = _unpack(network, x)
    r_final = assemble_residuals(network, heads_final, flows_final)
    final_norm = float(torch.linalg.vector_norm(r_final).item())

    reason = classify_failure(
        residual_norm=final_norm,
        iterations=iterations,
        max_iterations=max_iterations,
        tol=tol,
        diverged=diverged,
        singular=singular,
    )
    converged = reason is None

    return SolveResult(
        converged=converged,
        heads=heads_final.detach(),
        flows=flows_final.detach(),
        residual_norm=final_norm,
        iterations=iterations,
        reason=reason.value if reason is not None else None,
    )
