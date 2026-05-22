"""Parity tests: analytic Jacobian vs. ``torch.autograd.functional.jacobian``.

The Sprint 8 audit showed the Newton solver's autograd Jacobian is the
dominant per-iteration cost on larger grids. Sprint 9 introduces an
analytic Jacobian assembled from the same residual formulas. These
tests pin the analytic version to the autograd oracle on every Sprint
1-2 fixture plus the Sprint 8 grid fixture, and also exercise the
``newton_solve(jacobian_mode="analytic")`` convergence path.
"""

from __future__ import annotations

import math

import pytest
import torch

from aquaoptima.dphm import (
    assemble_residuals,
    initial_guess,
    make_branch_network,
    make_grid_network,
    make_pump_network,
    make_single_loop_network,
    newton_solve,
)
from aquaoptima.dphm.solver import (
    assemble_jacobian_analytic,
    _pack,
    _unpack,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _autograd_jacobian(network, x):
    def f(x_):
        heads, flows = _unpack(network, x_)
        return assemble_residuals(network, heads, flows)

    return torch.autograd.functional.jacobian(f, x, create_graph=False)


def _packed_state(network, dtype=torch.float64):
    heads, flows = initial_guess(network, dtype=dtype)
    return _pack(network, heads, flows).detach()


# ---------------------------------------------------------------------------
# shape parity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fixture",
    [
        ("branch", make_branch_network),
        ("single_loop", make_single_loop_network),
        ("pump", make_pump_network),
        ("grid5x5", lambda: make_grid_network(rows=5, cols=5, seed=0)),
    ],
    ids=lambda p: p[0],
)
def test_analytic_jacobian_shape_matches_autograd(fixture) -> None:
    _, builder = fixture
    net = builder()
    x = _packed_state(net)
    heads, flows = _unpack(net, x)

    J_a = assemble_jacobian_analytic(net, heads, flows)
    J_g = _autograd_jacobian(net, x)

    assert J_a.shape == J_g.shape
    expected = (net.num_free_nodes + net.num_edges,) * 2
    assert J_a.shape == expected


# ---------------------------------------------------------------------------
# numerical parity at the initial guess
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fixture",
    [
        ("branch", make_branch_network),
        ("single_loop", make_single_loop_network),
        ("pump", make_pump_network),
        ("grid5x5", lambda: make_grid_network(rows=5, cols=5, seed=0)),
    ],
    ids=lambda p: p[0],
)
def test_analytic_jacobian_matches_autograd_at_initial_guess(fixture) -> None:
    _, builder = fixture
    net = builder()
    x = _packed_state(net)
    heads, flows = _unpack(net, x)

    J_a = assemble_jacobian_analytic(net, heads, flows)
    J_g = _autograd_jacobian(net, x)

    assert torch.allclose(J_a, J_g, atol=1e-9, rtol=1e-7)


# ---------------------------------------------------------------------------
# numerical parity at a perturbed (non-initial) state
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fixture",
    [
        ("branch", make_branch_network),
        ("single_loop", make_single_loop_network),
        ("pump", make_pump_network),
        ("grid5x5", lambda: make_grid_network(rows=5, cols=5, seed=0)),
    ],
    ids=lambda p: p[0],
)
def test_analytic_jacobian_matches_autograd_at_perturbed_state(fixture) -> None:
    _, builder = fixture
    net = builder()
    x = _packed_state(net)

    # Perturb both free heads and flows away from the smooth initial guess.
    gen = torch.Generator(device="cpu").manual_seed(0)
    delta = 0.05 * torch.randn(x.shape, generator=gen, dtype=x.dtype)
    x_p = x + delta
    heads, flows = _unpack(net, x_p)

    J_a = assemble_jacobian_analytic(net, heads, flows)
    J_g = _autograd_jacobian(net, x_p)

    assert torch.allclose(J_a, J_g, atol=1e-8, rtol=1e-6)


# ---------------------------------------------------------------------------
# solver convergence parity
# ---------------------------------------------------------------------------


def test_newton_solve_analytic_converges_on_branch_network() -> None:
    net = make_branch_network()
    res = newton_solve(net, max_iterations=200, tol=1e-6, jacobian_mode="analytic")
    assert res.converged is True
    assert res.reason is None
    assert math.isfinite(res.residual_norm)
    assert res.residual_norm <= 1e-6


def test_newton_solve_analytic_converges_on_single_loop() -> None:
    net = make_single_loop_network()
    res = newton_solve(net, max_iterations=200, tol=1e-6, jacobian_mode="analytic")
    assert res.converged is True
    assert res.residual_norm <= 1e-6


def test_newton_solve_analytic_converges_on_pump_network() -> None:
    net = make_pump_network()
    res = newton_solve(net, max_iterations=200, tol=1e-6, jacobian_mode="analytic")
    assert res.converged is True
    assert res.residual_norm <= 1e-6


def test_newton_solve_analytic_matches_autograd_solution_on_branch() -> None:
    net = make_branch_network()
    ag = newton_solve(net, max_iterations=200, tol=1e-8, jacobian_mode="autograd")
    an = newton_solve(net, max_iterations=200, tol=1e-8, jacobian_mode="analytic")

    assert ag.converged and an.converged
    assert torch.allclose(an.heads, ag.heads, atol=1e-6)
    assert torch.allclose(an.flows, ag.flows, atol=1e-6)


def test_newton_solve_analytic_converges_on_grid_5x5() -> None:
    net = make_grid_network(rows=5, cols=5, seed=0)
    res = newton_solve(net, max_iterations=200, tol=1e-6, jacobian_mode="analytic")
    assert res.converged is True, (
        f"analytic newton failed on 5x5 grid: reason={res.reason}, "
        f"norm={res.residual_norm}"
    )


def test_newton_solve_analytic_converges_on_grid_7x8() -> None:
    net = make_grid_network(rows=7, cols=8, seed=0)
    res = newton_solve(net, max_iterations=200, tol=1e-6, jacobian_mode="analytic")
    assert res.converged is True, (
        f"analytic newton failed on 7x8 grid: reason={res.reason}, "
        f"norm={res.residual_norm}"
    )


def test_newton_solve_rejects_unknown_jacobian_mode() -> None:
    net = make_branch_network()
    with pytest.raises(ValueError, match="jacobian_mode"):
        newton_solve(net, jacobian_mode="bogus")


def test_newton_solve_default_mode_preserves_autograd_behavior() -> None:
    """Backwards-compat: omitting jacobian_mode must still solve correctly."""
    net = make_branch_network()
    res = newton_solve(net, max_iterations=200, tol=1e-6)
    assert res.converged is True
