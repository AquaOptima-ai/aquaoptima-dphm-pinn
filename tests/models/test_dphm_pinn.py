"""Forward / backward smoke tests for the Sprint 3 dPHM-PINN skeleton."""

from __future__ import annotations

import pytest
import torch

from aquaoptima.dphm import (
    make_branch_network,
    make_pump_network,
    make_single_loop_network,
)
from aquaoptima.models import (
    DPHMPINN,
    FallbackGraphEncoder,
    GraphEncoder,
    GRUTemporalEncoder,
)
from aquaoptima.topology import build_graph_features


# --- graph encoder --------------------------------------------------------


def test_graph_encoder_forward_shape_branch() -> None:
    net = make_branch_network()
    features = build_graph_features(net)
    enc = GraphEncoder(
        node_in_dim=features.node_feature_dim,
        edge_in_dim=features.edge_feature_dim,
        hidden_dim=16,
    )
    out = enc(features.x_node, features.edge_index, features.edge_attr)
    assert out.shape == (features.num_nodes, 16)
    assert torch.isfinite(out).all().item()


def test_fallback_graph_encoder_does_not_require_pyg() -> None:
    # The fallback message-passing encoder must work without torch_geometric.
    net = make_single_loop_network()
    features = build_graph_features(net)
    enc = FallbackGraphEncoder(
        node_in_dim=features.node_feature_dim,
        edge_in_dim=features.edge_feature_dim,
        hidden_dim=8,
    )
    out = enc(features.x_node, features.edge_index, features.edge_attr)
    assert out.shape == (features.num_nodes, 8)
    assert torch.isfinite(out).all().item()


# --- gru temporal encoder -------------------------------------------------


def test_gru_temporal_encoder_returns_per_node_hidden() -> None:
    enc = GRUTemporalEncoder(input_dim=2, hidden_dim=12)
    x_seq = torch.randn(32, 4, 2)  # [T, N, F]
    out = enc(x_seq)
    assert out.shape == (4, 12)
    assert torch.isfinite(out).all().item()


# --- full dPHM-PINN skeleton ---------------------------------------------


@pytest.fixture(scope="module")
def windowed_branch() -> tuple:
    net = make_branch_network()
    features = build_graph_features(net)
    x_seq = torch.randn(32, features.num_nodes, 2)  # [T, N, F_seq]
    return net, features, x_seq


def test_dphm_pinn_forward_branch_shapes(windowed_branch) -> None:
    net, features, x_seq = windowed_branch
    model = DPHMPINN(
        node_in_dim=features.node_feature_dim,
        edge_in_dim=features.edge_feature_dim,
        seq_in_dim=x_seq.shape[-1],
        hidden_dim=16,
        num_setpoint_outputs=2,
    )
    out = model(x_seq, features)
    assert out["pressure"].shape == (net.num_nodes,)
    assert out["flow"].shape == (net.num_edges,)
    assert out["demand_forecast"].shape == (net.num_nodes,)
    assert out["setpoint_advisory"].shape == (2,)
    for name, t in out.items():
        assert torch.isfinite(t).all().item(), f"non-finite values in {name}"


def test_dphm_pinn_forward_single_loop_shapes() -> None:
    net = make_single_loop_network()
    features = build_graph_features(net)
    x_seq = torch.randn(32, net.num_nodes, 2)
    model = DPHMPINN(
        node_in_dim=features.node_feature_dim,
        edge_in_dim=features.edge_feature_dim,
        seq_in_dim=x_seq.shape[-1],
        hidden_dim=8,
    )
    out = model(x_seq, features)
    assert out["pressure"].shape == (net.num_nodes,)
    assert out["flow"].shape == (net.num_edges,)


def test_dphm_pinn_forward_pump_shapes() -> None:
    net = make_pump_network()
    features = build_graph_features(net)
    x_seq = torch.randn(32, net.num_nodes, 2)
    model = DPHMPINN(
        node_in_dim=features.node_feature_dim,
        edge_in_dim=features.edge_feature_dim,
        seq_in_dim=x_seq.shape[-1],
        hidden_dim=8,
    )
    out = model(x_seq, features)
    assert out["pressure"].shape == (net.num_nodes,)
    assert out["flow"].shape == (net.num_edges,)


def test_dphm_pinn_backward_produces_finite_gradients(windowed_branch) -> None:
    net, features, x_seq = windowed_branch
    model = DPHMPINN(
        node_in_dim=features.node_feature_dim,
        edge_in_dim=features.edge_feature_dim,
        seq_in_dim=x_seq.shape[-1],
        hidden_dim=8,
    )
    out = model(x_seq, features)
    loss = (
        out["pressure"].pow(2).mean()
        + out["flow"].pow(2).mean()
        + out["demand_forecast"].pow(2).mean()
        + out["setpoint_advisory"].pow(2).mean()
    )
    loss.backward()

    grad_seen = False
    for name, p in model.named_parameters():
        if p.grad is not None:
            assert torch.isfinite(p.grad).all().item(), f"non-finite grad in {name}"
            if p.grad.abs().sum().item() > 0:
                grad_seen = True
    assert grad_seen, "no parameter received a non-zero gradient"


def test_dphm_pinn_uses_fallback_when_pyg_missing(monkeypatch) -> None:
    # Force the model to construct the fallback encoder regardless of
    # whether torch_geometric is importable.
    net = make_branch_network()
    features = build_graph_features(net)
    x_seq = torch.randn(32, features.num_nodes, 2)
    model = DPHMPINN(
        node_in_dim=features.node_feature_dim,
        edge_in_dim=features.edge_feature_dim,
        seq_in_dim=x_seq.shape[-1],
        hidden_dim=8,
        force_fallback=True,
    )
    assert isinstance(model.graph_encoder, FallbackGraphEncoder)
    out = model(x_seq, features)
    assert out["pressure"].shape == (features.num_nodes,)
