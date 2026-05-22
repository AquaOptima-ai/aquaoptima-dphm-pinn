"""Sprint 6 — First-class PyG/GATv2Conv graph encoder tests.

Coverage:

* PyG is importable in this environment; ``GATv2Conv`` forward over a
  small fixture is finite.
* ``GraphEncoder(...)`` factory returns the PyG implementation when PyG
  is available and ``force_fallback=False``.
* ``force_fallback=True`` still routes through ``FallbackGraphEncoder``.
* ``PyGGraphEncoder`` defaults to a 3-layer ``GATv2Conv`` stack and
  exposes the ``num_layers`` knob.
* The PyG encoder respects ``edge_dim`` and produces finite outputs of
  the configured hidden dimension when called via ``DPHMPINN``.
"""

from __future__ import annotations

import pytest
import torch

pyg = pytest.importorskip("torch_geometric")

from torch_geometric.nn import GATv2Conv  # noqa: E402

from aquaoptima.dphm import make_branch_network  # noqa: E402
from aquaoptima.models import (  # noqa: E402
    DPHMPINN,
    FallbackGraphEncoder,
    GraphEncoder,
    PyGGraphEncoder,
)
from aquaoptima.topology import build_graph_features  # noqa: E402


def test_pyg_gatv2conv_smoke_with_edge_attr() -> None:
    conv = GATv2Conv(3, 4, heads=2, edge_dim=2, concat=False)
    x = torch.randn(5, 3)
    edge_index = torch.tensor([[0, 1, 2, 3], [1, 2, 3, 4]])
    edge_attr = torch.randn(4, 2)
    y = conv(x, edge_index, edge_attr)
    assert y.shape == (5, 4)
    assert torch.isfinite(y).all().item()


def test_graph_encoder_factory_returns_pyg_when_available() -> None:
    enc = GraphEncoder(node_in_dim=3, edge_in_dim=8, hidden_dim=16)
    assert isinstance(enc, PyGGraphEncoder)


def test_graph_encoder_factory_respects_force_fallback() -> None:
    enc = GraphEncoder(
        node_in_dim=3, edge_in_dim=8, hidden_dim=16, force_fallback=True
    )
    assert isinstance(enc, FallbackGraphEncoder)


def test_pyg_graph_encoder_defaults_to_three_layers() -> None:
    enc = PyGGraphEncoder(node_in_dim=3, edge_in_dim=8, hidden_dim=16)
    assert enc.num_layers == 3
    assert len(enc.convs) == 3
    for conv in enc.convs:
        assert isinstance(conv, GATv2Conv)


def test_pyg_graph_encoder_num_layers_configurable() -> None:
    enc = PyGGraphEncoder(
        node_in_dim=3, edge_in_dim=8, hidden_dim=16, num_layers=2
    )
    assert enc.num_layers == 2
    assert len(enc.convs) == 2


def test_pyg_graph_encoder_rejects_zero_layers() -> None:
    with pytest.raises(ValueError):
        PyGGraphEncoder(
            node_in_dim=3, edge_in_dim=8, hidden_dim=16, num_layers=0
        )


def test_pyg_graph_encoder_forward_shape_branch() -> None:
    net = make_branch_network()
    features = build_graph_features(net)
    enc = PyGGraphEncoder(
        node_in_dim=features.node_feature_dim,
        edge_in_dim=features.edge_feature_dim,
        hidden_dim=12,
    )
    out = enc(features.x_node, features.edge_index, features.edge_attr)
    assert out.shape == (features.num_nodes, 12)
    assert torch.isfinite(out).all().item()


def test_pyg_graph_encoder_uses_edge_dim() -> None:
    enc = PyGGraphEncoder(node_in_dim=3, edge_in_dim=8, hidden_dim=12)
    # Every internal GATv2Conv should be edge-conditioned via edge_dim=8.
    for conv in enc.convs:
        # ``GATv2Conv`` stores the edge_dim on the module after construction.
        assert getattr(conv, "edge_dim", None) == 8


def test_dphm_pinn_uses_pyg_path_by_default() -> None:
    net = make_branch_network()
    features = build_graph_features(net)
    x_seq = torch.randn(32, features.num_nodes, 2)
    model = DPHMPINN(
        node_in_dim=features.node_feature_dim,
        edge_in_dim=features.edge_feature_dim,
        seq_in_dim=x_seq.shape[-1],
        hidden_dim=12,
    )
    assert isinstance(model.graph_encoder, PyGGraphEncoder)
    out = model(x_seq, features)
    assert out["pressure"].shape == (features.num_nodes,)
    assert torch.isfinite(out["pressure"]).all().item()
