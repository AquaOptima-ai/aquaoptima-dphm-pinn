"""Sprint 6 — Batched loss primitives.

Coverage:

* ``masked_supervised_loss`` accepts ``[N]`` and ``[B, N]`` predictions
  with matching mask shapes. The ``[B, N]`` path is numerically
  consistent with averaging per-batch MSE — i.e. summing squared
  errors over all observed entries and dividing by the total observed
  count.
* ``masked_supervised_loss`` accepts ``[N]`` predictions with a single
  ``[N]`` mask broadcast across a ``[B, N]`` target stack? — no, we
  keep the strict same-shape contract for predictability. The batched
  shapes must match across all three tensors.
* ``physics_residual_loss`` accepts a single ``[N]`` head + ``[E]``
  flow (legacy) and stacks ``[B, N]`` heads + ``[B, E]`` flows (new),
  in which case it returns the *sum* of the per-batch physics
  residuals — mirroring the legacy behaviour (squared L2 norm) so the
  composite loss aggregates cleanly.
* ``composite_loss`` round-trips through the batched path on both
  pressure and flow predictions.
"""

from __future__ import annotations

import pytest
import torch

from aquaoptima.dphm import make_branch_network
from aquaoptima.models.losses import (
    composite_loss,
    masked_supervised_loss,
    physics_residual_loss,
)
from aquaoptima.topology import sensor_mask_from_indices


# ---------------------------------------------------------------------------
# masked_supervised_loss batched paths
# ---------------------------------------------------------------------------


def test_masked_supervised_loss_batched_shape() -> None:
    predictions = torch.zeros(2, 3)
    targets = torch.tensor([[3.0, 4.0, 100.0], [1.0, 2.0, 100.0]])
    mask = torch.tensor([[True, True, False], [True, True, False]])

    loss = masked_supervised_loss(predictions, targets, mask)

    # Observed entries: (3,4,1,2) -> squared (9,16,1,4) -> sum 30, count 4
    assert loss.ndim == 0
    assert torch.isclose(loss, torch.tensor(30.0 / 4.0))


def test_masked_supervised_loss_batched_mask_can_vary_across_batch() -> None:
    predictions = torch.zeros(2, 3)
    targets = torch.tensor([[3.0, 4.0, 100.0], [1.0, 2.0, 5.0]])
    mask = torch.tensor([[True, True, False], [False, False, True]])

    loss = masked_supervised_loss(predictions, targets, mask)

    # Observed sum-of-squares: 9 + 16 + 25 = 50, count 3 -> 50/3
    assert torch.isclose(loss, torch.tensor(50.0 / 3.0))


def test_masked_supervised_loss_batched_empty_mask_returns_zero() -> None:
    predictions = torch.zeros(2, 3)
    targets = torch.ones(2, 3)
    mask = torch.zeros(2, 3, dtype=torch.bool)

    loss = masked_supervised_loss(predictions, targets, mask)
    assert torch.isclose(loss, torch.tensor(0.0))


def test_masked_supervised_loss_batched_gradients_flow() -> None:
    predictions = torch.zeros(2, 3, requires_grad=True)
    targets = torch.ones(2, 3)
    mask = torch.tensor([[True, False, True], [False, True, False]])

    loss = masked_supervised_loss(predictions, targets, mask)
    loss.backward()
    assert predictions.grad is not None
    # only masked entries have non-zero grad
    assert predictions.grad[0, 0].abs() > 0
    assert torch.isclose(predictions.grad[0, 1], torch.tensor(0.0))
    assert predictions.grad[0, 2].abs() > 0
    assert torch.isclose(predictions.grad[1, 0], torch.tensor(0.0))
    assert predictions.grad[1, 1].abs() > 0
    assert torch.isclose(predictions.grad[1, 2], torch.tensor(0.0))


def test_masked_supervised_loss_b1_matches_unbatched() -> None:
    predictions = torch.tensor([0.0, 0.0, 0.0])
    targets = torch.tensor([3.0, 4.0, 100.0])
    mask = torch.tensor([True, True, False])

    loss_u = masked_supervised_loss(predictions, targets, mask)
    loss_b = masked_supervised_loss(
        predictions.unsqueeze(0), targets.unsqueeze(0), mask.unsqueeze(0)
    )
    assert torch.isclose(loss_b, loss_u)


# ---------------------------------------------------------------------------
# physics_residual_loss batched paths
# ---------------------------------------------------------------------------


def test_physics_residual_loss_batched_finite_and_sum() -> None:
    net = make_branch_network()
    B = 3
    heads_b = (torch.randn(B, net.num_nodes) * 0.1 + 100.0).requires_grad_()
    flows_b = (torch.randn(B, net.num_edges) * 0.01 + 0.05).requires_grad_()

    loss_b = physics_residual_loss(net, heads_b, flows_b)
    assert torch.isfinite(loss_b)
    # gradients flow through both inputs
    loss_b.backward()
    assert heads_b.grad is not None and torch.isfinite(heads_b.grad).all()
    assert flows_b.grad is not None and torch.isfinite(flows_b.grad).all()


def test_physics_residual_loss_batched_equals_sum_of_unbatched() -> None:
    net = make_branch_network()
    torch.manual_seed(0)
    B = 4
    heads_b = torch.randn(B, net.num_nodes) * 0.1 + 100.0
    flows_b = torch.randn(B, net.num_edges) * 0.01 + 0.05

    loss_b = physics_residual_loss(net, heads_b, flows_b)
    loss_sum = sum(
        physics_residual_loss(net, heads_b[i], flows_b[i]) for i in range(B)
    )
    assert torch.isclose(loss_b, loss_sum, atol=1e-5)


def test_physics_residual_loss_b1_matches_unbatched() -> None:
    net = make_branch_network()
    heads = torch.tensor([100.0, 90.0, 80.0, 80.0])
    flows = torch.tensor([0.05, 0.03, 0.02])
    loss_u = physics_residual_loss(net, heads, flows)
    loss_b = physics_residual_loss(net, heads.unsqueeze(0), flows.unsqueeze(0))
    assert torch.isclose(loss_b, loss_u, atol=1e-6)


# ---------------------------------------------------------------------------
# composite_loss batched paths
# ---------------------------------------------------------------------------


def test_composite_loss_batched_components() -> None:
    network = make_branch_network()
    B = 2
    mask_single = sensor_mask_from_indices(network.num_nodes, [0, 2])
    mask = mask_single.unsqueeze(0).expand(B, -1)

    pred_pressure = torch.tensor(
        [[100.0, 90.0, 80.0, 80.0], [101.0, 89.0, 81.0, 79.0]]
    )
    target_pressure = torch.tensor(
        [[100.0, 88.0, 79.0, 75.0], [101.0, 88.0, 80.0, 75.0]]
    )
    flows = torch.tensor([[0.05, 0.03, 0.02], [0.06, 0.03, 0.01]])

    out = composite_loss(
        network=network,
        sensor_mask=mask,
        predicted_pressure=pred_pressure,
        target_pressure=target_pressure,
        predicted_flow=flows,
        target_flow=None,
        flow_sensor_mask=None,
        lambda_data=1.0,
        lambda_physics=0.5,
    )

    assert torch.isfinite(out["data"])
    assert torch.isfinite(out["physics"])
    assert torch.isfinite(out["total"])
    assert torch.isclose(out["total"], out["data"] + 0.5 * out["physics"])


def test_composite_loss_b1_matches_unbatched() -> None:
    network = make_branch_network()
    mask = sensor_mask_from_indices(network.num_nodes, [0, 2])

    pred_pressure = torch.tensor([100.0, 90.0, 80.0, 80.0])
    target_pressure = torch.tensor([100.0, 88.0, 79.0, 75.0])
    flows = torch.tensor([0.05, 0.03, 0.02])

    out_u = composite_loss(
        network=network,
        sensor_mask=mask,
        predicted_pressure=pred_pressure,
        target_pressure=target_pressure,
        predicted_flow=flows,
        lambda_data=1.0,
        lambda_physics=0.5,
    )
    out_b = composite_loss(
        network=network,
        sensor_mask=mask.unsqueeze(0),
        predicted_pressure=pred_pressure.unsqueeze(0),
        target_pressure=target_pressure.unsqueeze(0),
        predicted_flow=flows.unsqueeze(0),
        lambda_data=1.0,
        lambda_physics=0.5,
    )
    assert torch.isclose(out_b["data"], out_u["data"], atol=1e-6)
    assert torch.isclose(out_b["physics"], out_u["physics"], atol=1e-6)
    assert torch.isclose(out_b["total"], out_u["total"], atol=1e-6)


def test_masked_supervised_loss_shape_mismatch_still_raises() -> None:
    with pytest.raises(ValueError):
        masked_supervised_loss(
            torch.zeros(2, 3), torch.zeros(2, 4),
            torch.ones(2, 3, dtype=torch.bool),
        )


# ---------------------------------------------------------------------------
# Sprint 7 — physics_residual_loss now uses vectorized batched assembly
# ---------------------------------------------------------------------------


def test_physics_residual_loss_batched_uses_vectorized_helper(monkeypatch) -> None:
    """The batched path must call ``assemble_residuals_batched`` exactly
    once (no Python loop over the batch axis).
    """
    import aquaoptima.models.losses as losses_mod
    from aquaoptima.dphm.solver import assemble_residuals_batched

    net = make_branch_network()
    B = 4
    heads = torch.randn(B, net.num_nodes) * 0.1 + 100.0
    flows = torch.randn(B, net.num_edges) * 0.01 + 0.05

    call_count = {"batched": 0, "unbatched": 0}

    real_batched = assemble_residuals_batched

    def counting_batched(network, h, f):
        call_count["batched"] += 1
        return real_batched(network, h, f)

    def counting_unbatched(*args, **kwargs):
        call_count["unbatched"] += 1
        from aquaoptima.dphm.solver import assemble_residuals as real_unbatched
        return real_unbatched(*args, **kwargs)

    monkeypatch.setattr(losses_mod, "assemble_residuals_batched", counting_batched)
    if hasattr(losses_mod, "assemble_residuals"):
        monkeypatch.setattr(losses_mod, "assemble_residuals", counting_unbatched)

    out = physics_residual_loss(net, heads, flows)
    assert torch.isfinite(out)
    assert call_count["batched"] == 1, (
        f"expected exactly one batched call, got {call_count}"
    )
    assert call_count["unbatched"] == 0, (
        f"batched path must not fall back into the unbatched loop; got {call_count}"
    )


def test_physics_residual_loss_batched_large_b_matches_stack() -> None:
    """At B=16, the vectorized result must still match the stacked loop."""
    net = make_branch_network()
    torch.manual_seed(7)
    B = 16
    heads = torch.randn(B, net.num_nodes) * 0.1 + 100.0
    flows = torch.randn(B, net.num_edges) * 0.01 + 0.05

    loss_b = physics_residual_loss(net, heads, flows)
    loss_sum = sum(
        physics_residual_loss(net, heads[i], flows[i]) for i in range(B)
    )
    assert torch.isclose(loss_b, loss_sum, atol=1e-5, rtol=1e-5)
