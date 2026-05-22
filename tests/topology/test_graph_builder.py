"""Tests for ``aquaoptima.topology.graph_builder`` and ``masks``."""

from __future__ import annotations

import pytest
import torch

from aquaoptima.dphm import (
    make_branch_network,
    make_pump_network,
    make_single_loop_network,
)
from aquaoptima.topology import (
    GraphFeatures,
    build_graph_features,
    sensor_mask_from_indices,
    virtual_node_mask,
)


# --- graph_builder --------------------------------------------------------


def test_build_graph_features_branch_shapes() -> None:
    net = make_branch_network()
    features = build_graph_features(net)

    assert isinstance(features, GraphFeatures)
    assert features.x_node.shape[0] == net.num_nodes
    assert features.x_node.shape[1] >= 3  # at least demand + fixed-head flag + value
    assert features.edge_index.shape == (2, net.num_edges)
    assert features.edge_index.dtype == torch.long
    assert features.edge_attr.shape[0] == net.num_edges
    assert features.edge_attr.shape[1] >= 4  # at least length/diameter/c/pump_flag


def test_build_graph_features_edge_index_matches_network() -> None:
    net = make_branch_network()
    features = build_graph_features(net)
    assert torch.equal(features.edge_index, net.edge_index)


def test_build_graph_features_encodes_demands_and_fixed_heads() -> None:
    net = make_branch_network()
    features = build_graph_features(net)

    # First column should be the per-node demand.
    assert torch.allclose(features.x_node[:, 0], net.demands)
    # A fixed-head flag column should be 1.0 exactly on the reservoir node.
    flag_col = features.x_node[:, 1]
    assert flag_col[0].item() == pytest.approx(1.0)
    assert flag_col[1:].sum().item() == pytest.approx(0.0)


def test_build_graph_features_pump_edge_attrs() -> None:
    net = make_pump_network()
    features = build_graph_features(net)

    # Pump edges should carry a non-zero pump_a0 and a positive pump_speed
    # in their edge-attribute row; pipe edges should have pump_speed==0.
    # Locate the pump flag column (4th column by contract).
    pump_flag_col = 3
    pump_flags = features.edge_attr[:, pump_flag_col]
    assert pump_flags[net.pump_edge_indices].sum().item() > 0
    assert pump_flags[net.pipe_edge_indices].sum().item() == pytest.approx(0.0)


def test_build_graph_features_single_loop_shapes() -> None:
    net = make_single_loop_network()
    features = build_graph_features(net)
    assert features.x_node.shape[0] == net.num_nodes
    assert features.edge_attr.shape[0] == net.num_edges


# --- masks ----------------------------------------------------------------


def test_sensor_mask_from_indices_marks_observed() -> None:
    mask = sensor_mask_from_indices(num_nodes=5, observed=[0, 2, 4])
    assert mask.dtype == torch.bool
    assert mask.shape == (5,)
    assert mask.tolist() == [True, False, True, False, True]


def test_sensor_mask_rejects_out_of_range() -> None:
    with pytest.raises(ValueError):
        sensor_mask_from_indices(num_nodes=3, observed=[0, 3])


def test_virtual_node_mask_is_complement() -> None:
    mask = sensor_mask_from_indices(num_nodes=4, observed=[1, 3])
    virt = virtual_node_mask(mask)
    assert virt.dtype == torch.bool
    assert virt.tolist() == [True, False, True, False]
    assert bool((mask & virt).any().item()) is False
    assert bool((mask | virt).all().item()) is True
