"""Tests for residual assembly and Newton-style solver on small networks."""

import math

import pytest
import torch

from aquaoptima.dphm.fixtures import (
    make_branch_network,
    make_single_loop_network,
    make_pump_network,
)
from aquaoptima.dphm.network import Network
from aquaoptima.dphm.diagnostics import SolveFailureReason, SolveResult
from aquaoptima.dphm.solver import (
    assemble_residuals,
    residual_norm,
    newton_solve,
    initial_guess,
)


# ---------------------------------------------------------------------------
# residual assembly
# ---------------------------------------------------------------------------


def test_assemble_residuals_returns_finite_vector_on_initial_guess():
    net = make_branch_network()
    heads, flows = initial_guess(net)
    r = assemble_residuals(net, heads, flows)
    assert r.dim() == 1
    assert torch.isfinite(r).all().item()


def test_assemble_residuals_size_matches_unknowns():
    """The residual vector must be square: ``len(r) == free_heads + edges``."""
    net = make_branch_network()
    heads, flows = initial_guess(net)
    r = assemble_residuals(net, heads, flows)
    expected = net.num_free_nodes + net.num_edges
    assert r.shape == (expected,)


def test_assemble_residuals_zero_for_balanced_branch_at_consistent_state():
    """Hand-calibrate a branch state so mass + energy residuals are ~0."""
    net = make_branch_network()
    # Mass-balanced flows: pipe 0 carries all supply, pipes 1 and 2 carry demands.
    flows = torch.tensor([0.05, 0.03, 0.02])
    # Heads that close the energy balance for each pipe.
    from aquaoptima.dphm.hazen_williams import hazen_williams_head_loss

    hf = hazen_williams_head_loss(flows, net.lengths, net.diameters, net.c_factors)
    h0 = 100.0  # reservoir
    h1 = h0 - hf[0].item()
    h2 = h1 - hf[1].item()
    h3 = h1 - hf[2].item()
    heads = torch.tensor([h0, h1, h2, h3])
    r = assemble_residuals(net, heads, flows)
    assert torch.allclose(r, torch.zeros_like(r), atol=1e-5)


def test_residual_norm_is_nonnegative_scalar():
    net = make_branch_network()
    heads, flows = initial_guess(net)
    n = residual_norm(net, heads, flows)
    assert n.dim() == 0
    assert n.item() >= 0.0


def test_residual_norm_is_differentiable_in_flows():
    net = make_branch_network()
    heads, _ = initial_guess(net)
    flows = torch.tensor([0.05, 0.03, 0.02], requires_grad=True)
    n = residual_norm(net, heads, flows)
    n.backward()
    assert flows.grad is not None
    assert torch.isfinite(flows.grad).all().item()


# ---------------------------------------------------------------------------
# Newton solve
# ---------------------------------------------------------------------------


def test_newton_solve_converges_on_branch_network():
    net = make_branch_network()
    res = newton_solve(net, max_iterations=200, tol=1e-6)
    assert isinstance(res, SolveResult)
    assert res.converged is True
    assert res.reason is None
    assert math.isfinite(res.residual_norm)
    assert res.residual_norm <= 1e-6
    # Reservoir head preserved.
    assert math.isclose(res.heads[0].item(), 100.0, abs_tol=1e-5)
    # Mass conservation: sum of pipe flows out of reservoir equals supply.
    assert math.isclose(res.flows[0].item(), 0.05, abs_tol=1e-4)


def test_newton_solve_converges_on_pump_network():
    net = make_pump_network()
    res = newton_solve(net, max_iterations=200, tol=1e-6)
    assert res.converged is True
    assert res.residual_norm <= 1e-6
    # Pump should raise head from the 5 m reservoir above the suction level.
    assert res.heads[1].item() > 5.0


def test_newton_solve_reports_max_iterations_when_budget_exhausted():
    net = make_branch_network()
    res = newton_solve(net, max_iterations=1, tol=1e-12)
    assert res.converged is False
    assert res.reason == SolveFailureReason.MAX_ITERATIONS.value


def test_newton_solve_does_not_lie_about_convergence_on_failure():
    """A failed solve must not return its iterate as if it were converged."""
    net = make_branch_network()
    res = newton_solve(net, max_iterations=1, tol=1e-12)
    assert res.converged is False
    # Residual norm reported should match the actual residual of the returned state.
    r = assemble_residuals(net, res.heads, res.flows)
    actual = torch.linalg.vector_norm(r).item()
    assert math.isclose(res.residual_norm, actual, rel_tol=1e-5, abs_tol=1e-8)


def test_newton_solve_residual_norm_is_differentiable_wrt_demands():
    """End-to-end gradient flow: changing demands changes the converged residual.

    We solve once, then re-evaluate residual_norm at the converged state with
    a demands tensor that requires_grad — backprop must produce finite grads.
    """
    net = make_branch_network()
    res = newton_solve(net, max_iterations=200, tol=1e-6)
    assert res.converged

    demands = net.demands.detach().clone().requires_grad_(True)
    # Rebuild a Network-like view that uses the grad-tracked demands.
    perturbed = Network(
        edge_index=net.edge_index,
        num_nodes=net.num_nodes,
        pipe_mask=net.pipe_mask,
        pump_mask=net.pump_mask,
        lengths=net.lengths,
        diameters=net.diameters,
        c_factors=net.c_factors,
        pump_coeffs=net.pump_coeffs,
        pump_speeds=net.pump_speeds,
        demands=demands,
        fixed_head_mask=net.fixed_head_mask,
        fixed_head_values=net.fixed_head_values,
    )
    n = residual_norm(perturbed, res.heads.detach(), res.flows.detach())
    n.backward()
    assert demands.grad is not None
    assert torch.isfinite(demands.grad).all().item()


def test_newton_solve_converges_on_single_loop_network():
    net = make_single_loop_network()
    res = newton_solve(net, max_iterations=200, tol=1e-6)
    assert res.converged is True
    assert res.residual_norm <= 1e-6


def test_assemble_residuals_rejects_wrong_head_or_flow_shape():
    net = make_branch_network()
    with pytest.raises(ValueError, match="heads"):
        assemble_residuals(net, torch.zeros(net.num_nodes + 1), torch.zeros(net.num_edges))
    with pytest.raises(ValueError, match="flows"):
        assemble_residuals(net, torch.zeros(net.num_nodes), torch.zeros(net.num_edges + 1))
