"""Sprint 6 — Batched ``[B, T, N, F]`` path through the dPHM-PINN.

Coverage:

* :class:`GRUTemporalEncoder` accepts both ``[T, N, F]`` (legacy) and
  ``[B, T, N, F]`` (new batched) inputs and returns ``[N, H]`` and
  ``[B, N, H]`` respectively.
* :class:`DPHMPINN.forward` accepts either layout and returns the
  appropriately shaped pressure / flow / demand_forecast /
  setpoint_advisory tensors.
* Per-task heads broadcast cleanly over the batch dimension.
* Batched outputs are finite and differentiable (a scalar reduction
  produces finite gradients).
* The unbatched path is numerically equivalent to the batched path
  with ``B=1`` under matched parameters and inputs.
"""

from __future__ import annotations

import pytest
import torch

from aquaoptima.dphm import make_branch_network, make_pump_network
from aquaoptima.models import DPHMPINN, GRUTemporalEncoder
from aquaoptima.models.heads import (
    DemandForecastHead,
    FlowHead,
    PressureHead,
    SetpointAdvisoryHead,
)
from aquaoptima.topology import build_graph_features


# ---------------------------------------------------------------------------
# GRUTemporalEncoder batched path
# ---------------------------------------------------------------------------


def test_gru_encoder_unbatched_unchanged() -> None:
    enc = GRUTemporalEncoder(input_dim=2, hidden_dim=8)
    x_seq = torch.randn(32, 4, 2)
    out = enc(x_seq)
    assert out.shape == (4, 8)
    assert torch.isfinite(out).all().item()


def test_gru_encoder_accepts_batched_input() -> None:
    enc = GRUTemporalEncoder(input_dim=2, hidden_dim=8)
    x_seq = torch.randn(3, 32, 4, 2)  # [B, T, N, F]
    out = enc(x_seq)
    assert out.shape == (3, 4, 8)
    assert torch.isfinite(out).all().item()


def test_gru_encoder_batched_b1_matches_unbatched() -> None:
    torch.manual_seed(0)
    enc = GRUTemporalEncoder(input_dim=2, hidden_dim=8)
    enc.eval()
    x_seq = torch.randn(32, 4, 2)
    x_seq_b = x_seq.unsqueeze(0)  # [1, 32, 4, 2]

    with torch.no_grad():
        out_unbatched = enc(x_seq)
        out_batched = enc(x_seq_b)

    assert out_batched.shape == (1, 4, 8)
    assert torch.allclose(out_batched.squeeze(0), out_unbatched, atol=1e-6)


def test_gru_encoder_rejects_unknown_rank() -> None:
    enc = GRUTemporalEncoder(input_dim=2, hidden_dim=8)
    with pytest.raises(ValueError):
        enc(torch.randn(4, 2))  # 2-D
    with pytest.raises(ValueError):
        enc(torch.randn(2, 3, 32, 4, 2))  # 5-D


# ---------------------------------------------------------------------------
# Heads broadcasting
# ---------------------------------------------------------------------------


def test_pressure_head_batched_shape() -> None:
    head = PressureHead(hidden_dim=8)
    h = torch.randn(3, 5, 8)  # [B, N, H]
    out = head(h)
    assert out.shape == (3, 5)
    assert torch.isfinite(out).all().item()


def test_demand_head_batched_shape() -> None:
    head = DemandForecastHead(hidden_dim=8)
    h = torch.randn(3, 5, 8)
    out = head(h)
    assert out.shape == (3, 5)
    assert torch.isfinite(out).all().item()


def test_flow_head_batched_shape() -> None:
    head = FlowHead(hidden_dim=8)
    edge_index = torch.tensor([[0, 1, 2], [1, 2, 3]])
    h = torch.randn(3, 5, 8)  # [B, N, H]
    out = head(h, edge_index)
    assert out.shape == (3, 3)  # [B, E]
    assert torch.isfinite(out).all().item()


def test_setpoint_head_batched_shape() -> None:
    head = SetpointAdvisoryHead(hidden_dim=8, num_outputs=4)
    h = torch.randn(3, 5, 8)
    out = head(h)
    assert out.shape == (3, 4)  # [B, K]
    assert torch.isfinite(out).all().item()


def test_heads_unbatched_unchanged() -> None:
    """Unbatched calls (legacy ``[N, H]``) still return ``[N]`` / ``[E]``
    / ``[K]`` shapes, not ``[1, ...]``."""
    h = torch.randn(5, 8)
    edge_index = torch.tensor([[0, 1, 2], [1, 2, 3]])

    assert PressureHead(8)(h).shape == (5,)
    assert DemandForecastHead(8)(h).shape == (5,)
    assert FlowHead(8)(h, edge_index).shape == (3,)
    assert SetpointAdvisoryHead(8, num_outputs=2)(h).shape == (2,)


# ---------------------------------------------------------------------------
# DPHMPINN end-to-end batched
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def branch_setup() -> tuple:
    net = make_branch_network()
    features = build_graph_features(net)
    return net, features


def test_dphm_pinn_batched_output_shapes_branch(branch_setup) -> None:
    net, features = branch_setup
    B, T = 4, 32
    x_seq = torch.randn(B, T, features.num_nodes, 2)
    model = DPHMPINN(
        node_in_dim=features.node_feature_dim,
        edge_in_dim=features.edge_feature_dim,
        seq_in_dim=2,
        hidden_dim=12,
        num_setpoint_outputs=3,
        force_fallback=True,
    )
    out = model(x_seq, features)
    assert out["pressure"].shape == (B, net.num_nodes)
    assert out["flow"].shape == (B, net.num_edges)
    assert out["demand_forecast"].shape == (B, net.num_nodes)
    assert out["setpoint_advisory"].shape == (B, 3)
    for name, t in out.items():
        assert torch.isfinite(t).all().item(), f"non-finite values in {name}"


def test_dphm_pinn_batched_output_shapes_pump() -> None:
    net = make_pump_network()
    features = build_graph_features(net)
    B, T = 2, 32
    x_seq = torch.randn(B, T, net.num_nodes, 2)
    model = DPHMPINN(
        node_in_dim=features.node_feature_dim,
        edge_in_dim=features.edge_feature_dim,
        seq_in_dim=2,
        hidden_dim=8,
        force_fallback=True,
    )
    out = model(x_seq, features)
    assert out["pressure"].shape == (B, net.num_nodes)
    assert out["flow"].shape == (B, net.num_edges)


def test_dphm_pinn_batched_backward_finite_gradients(branch_setup) -> None:
    net, features = branch_setup
    B, T = 3, 32
    x_seq = torch.randn(B, T, features.num_nodes, 2)
    model = DPHMPINN(
        node_in_dim=features.node_feature_dim,
        edge_in_dim=features.edge_feature_dim,
        seq_in_dim=2,
        hidden_dim=8,
        force_fallback=True,
    )
    out = model(x_seq, features)
    loss = (
        out["pressure"].pow(2).mean()
        + out["flow"].pow(2).mean()
        + out["demand_forecast"].pow(2).mean()
        + out["setpoint_advisory"].pow(2).mean()
    )
    loss.backward()

    seen = False
    for n, p in model.named_parameters():
        if p.grad is None:
            continue
        assert torch.isfinite(p.grad).all().item(), f"non-finite grad in {n}"
        if p.grad.abs().sum().item() > 0:
            seen = True
    assert seen, "no parameter received a non-zero gradient"


def test_dphm_pinn_b1_matches_unbatched(branch_setup) -> None:
    """A ``B=1`` batched forward must equal the unbatched forward on the
    same window. This is the deterministic parity contract."""
    net, features = branch_setup
    torch.manual_seed(42)

    x_seq = torch.randn(32, features.num_nodes, 2)
    x_seq_b = x_seq.unsqueeze(0)

    model = DPHMPINN(
        node_in_dim=features.node_feature_dim,
        edge_in_dim=features.edge_feature_dim,
        seq_in_dim=2,
        hidden_dim=8,
        force_fallback=True,
    )
    model.eval()
    with torch.no_grad():
        out_un = model(x_seq, features)
        out_b = model(x_seq_b, features)

    for key in ("pressure", "flow", "demand_forecast", "setpoint_advisory"):
        assert out_b[key].shape[0] == 1
        assert torch.allclose(
            out_b[key].squeeze(0), out_un[key], atol=1e-5
        ), f"batched/unbatched mismatch on {key}"


def test_dphm_pinn_batched_rejects_wrong_node_count(branch_setup) -> None:
    _, features = branch_setup
    model = DPHMPINN(
        node_in_dim=features.node_feature_dim,
        edge_in_dim=features.edge_feature_dim,
        seq_in_dim=2,
        hidden_dim=8,
        force_fallback=True,
    )
    bad = torch.randn(2, 32, features.num_nodes + 1, 2)
    with pytest.raises(ValueError):
        model(bad, features)
