"""Tests for the dPHM Network dataclass.

The Network dataclass collects topology and per-edge / per-node physical
parameters so that solver primitives stop juggling tensors positionally.
Validation is strict: incompatible shapes, overlapping pipe/pump masks,
or out-of-range node ids must raise ``ValueError`` at construction time,
not silently corrupt downstream physics.
"""

import pytest
import torch

from aquaoptima.dphm.network import Network


def _basic_kwargs():
    """Minimal valid network: reservoir -> junction -> demand, two pipes."""
    edge_index = torch.tensor([[0, 1], [1, 2]], dtype=torch.long)
    num_nodes = 3
    pipe_mask = torch.tensor([True, True])
    pump_mask = torch.tensor([False, False])
    lengths = torch.tensor([100.0, 80.0])
    diameters = torch.tensor([0.15, 0.10])
    c_factors = torch.tensor([130.0, 130.0])
    pump_coeffs = torch.zeros((2, 3))
    pump_speeds = torch.zeros(2)
    demands = torch.tensor([-0.05, 0.0, 0.05])
    fixed_head_mask = torch.tensor([True, False, False])
    fixed_head_values = torch.tensor([100.0, 0.0, 0.0])
    return dict(
        edge_index=edge_index,
        num_nodes=num_nodes,
        pipe_mask=pipe_mask,
        pump_mask=pump_mask,
        lengths=lengths,
        diameters=diameters,
        c_factors=c_factors,
        pump_coeffs=pump_coeffs,
        pump_speeds=pump_speeds,
        demands=demands,
        fixed_head_mask=fixed_head_mask,
        fixed_head_values=fixed_head_values,
    )


def test_network_constructs_with_valid_inputs():
    net = Network(**_basic_kwargs())
    assert net.num_edges == 2
    assert net.num_nodes == 3
    assert net.num_fixed_heads == 1
    assert net.num_free_nodes == 2


def test_network_rejects_bad_edge_index_shape():
    kw = _basic_kwargs()
    kw["edge_index"] = torch.tensor([0, 1, 2], dtype=torch.long)
    with pytest.raises(ValueError, match="edge_index"):
        Network(**kw)


def test_network_rejects_node_id_out_of_range():
    kw = _basic_kwargs()
    kw["edge_index"] = torch.tensor([[0, 1], [1, 99]], dtype=torch.long)
    with pytest.raises(ValueError, match="num_nodes"):
        Network(**kw)


def test_network_rejects_pipe_pump_overlap():
    kw = _basic_kwargs()
    kw["pipe_mask"] = torch.tensor([True, True])
    kw["pump_mask"] = torch.tensor([True, False])
    with pytest.raises(ValueError, match="overlap"):
        Network(**kw)


def test_network_rejects_unclassified_edge():
    # Every edge must be either a pipe or a pump.
    kw = _basic_kwargs()
    kw["pipe_mask"] = torch.tensor([True, False])
    kw["pump_mask"] = torch.tensor([False, False])
    with pytest.raises(ValueError, match="unclassified"):
        Network(**kw)


def test_network_rejects_mismatched_edge_arrays():
    kw = _basic_kwargs()
    kw["lengths"] = torch.tensor([100.0])  # wrong length
    with pytest.raises(ValueError, match="lengths"):
        Network(**kw)


def test_network_rejects_mismatched_pump_coeffs_shape():
    kw = _basic_kwargs()
    kw["pump_coeffs"] = torch.zeros((2, 2))  # last dim must be 3
    with pytest.raises(ValueError, match="pump_coeffs"):
        Network(**kw)


def test_network_rejects_mismatched_demand_length():
    kw = _basic_kwargs()
    kw["demands"] = torch.tensor([-0.05, 0.05])  # length 2 instead of 3
    with pytest.raises(ValueError, match="demands"):
        Network(**kw)


def test_network_rejects_mismatched_fixed_head_arrays():
    kw = _basic_kwargs()
    kw["fixed_head_mask"] = torch.tensor([True, False])  # length 2 instead of 3
    with pytest.raises(ValueError, match="fixed_head"):
        Network(**kw)


def test_network_rejects_non_positive_pipe_parameters():
    kw = _basic_kwargs()
    kw["lengths"] = torch.tensor([100.0, -1.0])
    with pytest.raises(ValueError, match="lengths"):
        Network(**kw)


def test_network_free_node_indices_matches_mask():
    net = Network(**_basic_kwargs())
    assert torch.equal(net.free_node_indices, torch.tensor([1, 2], dtype=torch.long))


def test_network_pipe_and_pump_edge_indices_match_masks():
    kw = _basic_kwargs()
    kw["pipe_mask"] = torch.tensor([False, True])
    kw["pump_mask"] = torch.tensor([True, False])
    kw["lengths"] = torch.tensor([1.0, 80.0])  # length-1 placeholder for pump edge is okay
    kw["pump_coeffs"] = torch.tensor([[40.0, 0.0, -1000.0], [0.0, 0.0, 0.0]])
    kw["pump_speeds"] = torch.tensor([1.0, 0.0])
    net = Network(**kw)
    assert torch.equal(net.pipe_edge_indices, torch.tensor([1], dtype=torch.long))
    assert torch.equal(net.pump_edge_indices, torch.tensor([0], dtype=torch.long))
