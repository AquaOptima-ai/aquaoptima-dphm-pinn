"""Tests for the network incidence matrix and nodal mass balance."""

import math

import torch

from aquaoptima.dphm.incidence import incidence_matrix, node_flow_balance


def test_incidence_shape_and_signs_for_simple_chain():
    # Nodes: 0 -> 1 -> 2
    edge_index = torch.tensor([[0, 1], [1, 2]], dtype=torch.long)
    A = incidence_matrix(edge_index, num_nodes=3)
    assert A.shape == (3, 2)
    # Edge 0 leaves node 0, enters node 1.
    assert A[0, 0].item() == -1
    assert A[1, 0].item() == 1
    assert A[2, 0].item() == 0
    # Edge 1 leaves node 1, enters node 2.
    assert A[0, 1].item() == 0
    assert A[1, 1].item() == -1
    assert A[2, 1].item() == 1


def test_balanced_network_residual_is_zero():
    # Two pipes feeding a junction, one demand draw at node 2.
    # 0 -> 2 carries 0.04, 1 -> 2 carries 0.06, demand at node 2 is 0.10.
    edge_index = torch.tensor([[0, 1], [2, 2]], dtype=torch.long)
    flows = torch.tensor([0.04, 0.06])
    demands = torch.tensor([-0.04, -0.06, 0.10])  # negative demand = supply (source).
    res = node_flow_balance(edge_index, flows, demands, num_nodes=3)
    assert res.shape == (3,)
    assert torch.allclose(res, torch.zeros(3), atol=1e-6)


def test_imbalance_is_detected_with_correct_sign():
    # Single pipe 0 -> 1 carrying 0.05, demand 0.10 at node 1 -> shortfall 0.05.
    edge_index = torch.tensor([[0], [1]], dtype=torch.long)
    flows = torch.tensor([0.05])
    demands = torch.tensor([-0.05, 0.10])
    res = node_flow_balance(edge_index, flows, demands, num_nodes=2)
    # Node 0: inflow=0, outflow=0.05, demand=-0.05 -> residual = 0 - 0.05 - (-0.05) = 0
    # Node 1: inflow=0.05, outflow=0, demand=0.10 -> residual = 0.05 - 0 - 0.10 = -0.05
    assert math.isclose(res[0].item(), 0.0, abs_tol=1e-9)
    assert math.isclose(res[1].item(), -0.05, rel_tol=1e-6)


def test_residual_differentiable_w_r_t_flows():
    edge_index = torch.tensor([[0], [1]], dtype=torch.long)
    flows = torch.tensor([0.05], requires_grad=True)
    demands = torch.tensor([-0.05, 0.05])
    res = node_flow_balance(edge_index, flows, demands, num_nodes=2)
    res.pow(2).sum().backward()
    assert flows.grad is not None
    assert torch.isfinite(flows.grad).all().item()


def test_isolated_node_has_zero_residual_when_no_demand():
    edge_index = torch.tensor([[0], [1]], dtype=torch.long)
    flows = torch.tensor([0.0])
    demands = torch.tensor([0.0, 0.0, 0.0])  # node 2 isolated
    res = node_flow_balance(edge_index, flows, demands, num_nodes=3)
    assert torch.allclose(res, torch.zeros(3))
