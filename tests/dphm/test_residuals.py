"""Tests for mass and energy residual primitives."""

import math

import torch

from aquaoptima.dphm.residuals import (
    mass_residual,
    pipe_energy_residual,
    pump_energy_residual,
)


def test_mass_residual_wraps_node_flow_balance():
    edge_index = torch.tensor([[0], [1]], dtype=torch.long)
    flows = torch.tensor([0.05])
    demands = torch.tensor([-0.05, 0.05])
    r = mass_residual(edge_index, flows, demands, num_nodes=2)
    assert torch.allclose(r, torch.zeros(2), atol=1e-6)


def test_pipe_energy_residual_zero_when_consistent():
    # Upstream head 50, downstream 45, friction loss 5 -> residual ~ 0.
    hu = torch.tensor(50.0)
    hd = torch.tensor(45.0)
    hf = torch.tensor(5.0)
    r = pipe_energy_residual(hu, hd, hf)
    assert math.isclose(r.item(), 0.0, abs_tol=1e-6)


def test_pipe_energy_residual_sign_and_magnitude():
    # h_u - h_d - h_f, so under-loss yields positive residual.
    r = pipe_energy_residual(
        torch.tensor(50.0), torch.tensor(40.0), torch.tensor(3.0)
    )
    assert math.isclose(r.item(), 7.0, rel_tol=1e-6)


def test_pump_energy_residual_zero_when_consistent():
    # Pump lifts head from 20 to 60, gain 40 -> residual ~ 0.
    r = pump_energy_residual(
        torch.tensor(20.0), torch.tensor(60.0), torch.tensor(40.0)
    )
    assert math.isclose(r.item(), 0.0, abs_tol=1e-6)


def test_pump_energy_residual_sign_and_magnitude():
    # h_d - h_u - gain, so over-stated gain yields negative residual.
    r = pump_energy_residual(
        torch.tensor(20.0), torch.tensor(60.0), torch.tensor(50.0)
    )
    assert math.isclose(r.item(), -10.0, rel_tol=1e-6)


def test_residuals_are_differentiable():
    hu = torch.tensor(50.0, requires_grad=True)
    hd = torch.tensor(45.0, requires_grad=True)
    hf = torch.tensor(5.0, requires_grad=True)
    r = pipe_energy_residual(hu, hd, hf)
    r.pow(2).backward()
    for t in (hu, hd, hf):
        assert t.grad is not None and torch.isfinite(t.grad).item()


def test_residuals_broadcast_over_edges():
    hu = torch.tensor([50.0, 30.0])
    hd = torch.tensor([45.0, 28.0])
    hf = torch.tensor([5.0, 2.0])
    r = pipe_energy_residual(hu, hd, hf)
    assert r.shape == (2,)
    assert torch.allclose(r, torch.zeros(2), atol=1e-6)
