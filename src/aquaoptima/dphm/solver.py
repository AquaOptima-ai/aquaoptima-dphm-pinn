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
from .incidence import cached_incidence_matrix, incidence_matrix
from .network import Network
from .diagnostics import SolveFailureReason, SolveResult, classify_failure


JACOBIAN_MODES = ("autograd", "analytic")


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

    A = cached_incidence_matrix(network, flows.dtype)
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
    A = cached_incidence_matrix(network, dtype)
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
# analytic Jacobian
# ---------------------------------------------------------------------------


def _hazen_williams_dQ(
    flows: torch.Tensor,
    L: torch.Tensor,
    D: torch.Tensor,
    C: torch.Tensor,
    eps: float = 1e-6,
) -> torch.Tensor:
    """Derivative ``d h_f / dQ`` of the signed Hazen-Williams head loss.

    Mirrors :func:`hazen_williams_head_loss` term-for-term so the
    analytic Jacobian matches the autograd Jacobian within float64
    rounding. ``h_f(Q) = sign(Q) * k * (|Q| + eps)**1.852`` with
    ``k = 10.67 * L / (C**1.852 * D**4.87)`` is differentiated as

        d h_f / dQ = sign(Q)**2 * 1.852 * k * (|Q| + eps)**0.852

    so that the value at ``Q = 0`` matches the autograd subgradient
    convention (zero) rather than the one-sided limit.
    """
    abs_Q = torch.abs(flows)
    k = 10.67 * L / (C ** 1.852 * D ** 4.87)
    sign_sq = torch.sign(flows) ** 2
    return sign_sq * 1.852 * k * (abs_Q + eps) ** 0.852


def _pump_dQ(
    flows: torch.Tensor, pump_speeds: torch.Tensor, pump_coeffs: torch.Tensor
) -> torch.Tensor:
    """Derivative ``d H_pump / dQ`` of the quadratic pump gain.

    With ``H(Q, s) = a0 s^2 + a1 s Q + a2 Q^2`` the partial in Q is
    ``a1 s + 2 a2 Q``.
    """
    a1 = pump_coeffs[..., 1]
    a2 = pump_coeffs[..., 2]
    return a1 * pump_speeds + 2.0 * a2 * flows


def assemble_jacobian_analytic(
    network: Network, heads: torch.Tensor, flows: torch.Tensor
) -> torch.Tensor:
    """Analytic Jacobian of :func:`assemble_residuals` at ``(heads, flows)``.

    Row / column ordering matches the Newton solver's packed state
    ``x = [free_heads, flows]``:

    Rows
        ``0:num_free``                — mass-balance residuals for free nodes
        ``num_free:num_free + E``      — per-edge energy residuals

    Columns
        ``0:num_free``                — free-node heads
        ``num_free:num_free + E``      — per-edge flows

    Block structure::

        J = [ 0                  A_free,:                    ]
            [ H_e (signed)       diag(-dh_f/dQ | -dH_pump/dQ) ]

    where:

    * ``A_free,:`` is the dense incidence matrix restricted to free-node rows.
    * ``H_e`` carries ``+1`` on the upstream-free-head column and ``-1`` on
      the downstream-free-head column for pipe edges, with signs flipped
      for pump edges (because the pump energy convention is
      ``h_d - h_u - gain``). Fixed-head endpoints contribute no column.
    * The flow-derivative diagonal uses :func:`_hazen_williams_dQ` on
      pipe rows and :func:`_pump_dQ` on pump rows; the minus sign comes
      from the residual conventions ``h_u - h_d - h_f`` and
      ``h_d - h_u - gain``.

    The returned dense tensor has shape
    ``[num_free + E, num_free + E]`` and matches the dtype of ``flows``.
    """
    if heads.shape != (network.num_nodes,):
        raise ValueError(
            f"heads must have shape [{network.num_nodes}], got {tuple(heads.shape)}"
        )
    if flows.shape != (network.num_edges,):
        raise ValueError(
            f"flows must have shape [{network.num_edges}], got {tuple(flows.shape)}"
        )

    dtype = flows.dtype
    num_free = network.num_free_nodes
    E = network.num_edges
    N = num_free + E

    A = cached_incidence_matrix(network, dtype)
    free_mask = ~network.fixed_head_mask
    A_free = A[free_mask]  # [num_free, E]

    # Node-id -> column index in free_heads block, or -1 if fixed.
    node_to_free_col = torch.full((network.num_nodes,), -1, dtype=torch.long)
    node_to_free_col[network.free_node_indices] = torch.arange(
        num_free, dtype=torch.long
    )

    J = torch.zeros((N, N), dtype=dtype)

    # mass / flow block
    J[:num_free, num_free:] = A_free

    # energy / flow block — diagonal
    pipe_dQ = _hazen_williams_dQ(
        flows,
        network.lengths.to(dtype),
        network.diameters.to(dtype),
        network.c_factors.to(dtype),
    )
    pump_dQ = _pump_dQ(
        flows, network.pump_speeds.to(dtype), network.pump_coeffs.to(dtype)
    )
    edge_dQ = torch.where(network.pipe_mask, pipe_dQ, pump_dQ)  # [E]

    diag_idx = torch.arange(E, dtype=torch.long) + num_free
    J[diag_idx, diag_idx] = -edge_dQ

    # energy / free-head block — sparse pattern, one or two non-zeros per row.
    src = network.edge_index[0]
    dst = network.edge_index[1]
    src_col = node_to_free_col[src]
    dst_col = node_to_free_col[dst]

    # Pipe edges: r_e = h_u - h_d - h_f  =>  +1 wrt h_u, -1 wrt h_d.
    # Pump edges: r_e = h_d - h_u - gain =>  -1 wrt h_u, +1 wrt h_d.
    sign_u = torch.where(network.pipe_mask, torch.ones(E, dtype=dtype), -torch.ones(E, dtype=dtype))
    sign_d = -sign_u

    energy_row_offset = num_free
    for e in range(E):
        row = energy_row_offset + e
        s_col = int(src_col[e].item())
        d_col = int(dst_col[e].item())
        if s_col >= 0:
            J[row, s_col] = sign_u[e]
        if d_col >= 0:
            J[row, d_col] = sign_d[e]

    return J


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
    jacobian_mode: str = "autograd",
) -> SolveResult:
    """Damped Newton iteration on the packed state ``x = [free_heads, flows]``.

    Two Jacobian assemblers are supported:

    * ``jacobian_mode="autograd"`` (default, preserved from Sprint 1-2)
      — :func:`torch.autograd.functional.jacobian` over the residual.
      Adequate for the tiny synthetic fixtures but quadratic in cost
      on larger grids.
    * ``jacobian_mode="analytic"`` — :func:`assemble_jacobian_analytic`,
      a closed-form Jacobian from the Hazen-Williams and pump-gain
      derivatives. Same shape and (within float64 rounding) same value
      as the autograd version; the analytic version is materially
      faster on the Sprint 8 grid fixtures and is the Sprint 9
      performance gate.

    The solver never lies about convergence: if the final residual norm
    exceeds ``tol``, ``SolveResult.converged`` is ``False`` and ``reason``
    carries the matching :class:`SolveFailureReason` value.
    """
    if jacobian_mode not in JACOBIAN_MODES:
        raise ValueError(
            f"jacobian_mode must be one of {JACOBIAN_MODES}, got {jacobian_mode!r}"
        )

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
            if jacobian_mode == "analytic":
                heads_x, flows_x = _unpack(network, x)
                J = assemble_jacobian_analytic(network, heads_x, flows_x)
            else:
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
