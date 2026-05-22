"""Tests for Sprint 4 composite training losses.

Coverage:

* ``masked_supervised_loss`` averages MSE only over observed entries
  (the sensor mask) and ignores virtual nodes — including the edge
  case where ``observed.sum() == 0`` (no usable signal) which must
  return a zero loss instead of dividing by zero.
* ``physics_residual_loss`` evaluates ``||assemble_residuals||^2`` on
  the model's predicted heads and flows for a given ``Network``.
* ``composite_loss`` returns each component plus the aggregate, and
  the aggregate is the lambda-weighted sum.
"""

from __future__ import annotations

import pytest
import torch

from aquaoptima.dphm import make_branch_network, make_pump_network
from aquaoptima.models.losses import (
    composite_loss,
    masked_supervised_loss,
    physics_residual_loss,
)
from aquaoptima.topology import sensor_mask_from_indices


def test_masked_supervised_loss_ignores_virtual_nodes() -> None:
    predictions = torch.tensor([1.0, 2.0, 3.0, 4.0])
    targets = torch.tensor([1.0, 5.0, 3.0, 9.0])  # virtual entries differ
    mask = torch.tensor([True, False, True, False])  # observe only 0 and 2

    loss = masked_supervised_loss(predictions, targets, mask)

    # Only entries 0 and 2 contribute; both are exact matches → loss == 0.
    assert torch.isclose(loss, torch.tensor(0.0))


def test_masked_supervised_loss_averages_over_observed_only() -> None:
    predictions = torch.tensor([0.0, 0.0, 0.0])
    targets = torch.tensor([3.0, 4.0, 100.0])
    mask = torch.tensor([True, True, False])

    loss = masked_supervised_loss(predictions, targets, mask)

    # MSE over the two observed entries: (9 + 16) / 2 = 12.5
    assert torch.isclose(loss, torch.tensor(12.5))


def test_masked_supervised_loss_empty_mask_returns_zero() -> None:
    predictions = torch.tensor([1.0, 2.0])
    targets = torch.tensor([3.0, 4.0])
    mask = torch.tensor([False, False])

    loss = masked_supervised_loss(predictions, targets, mask)

    assert torch.isclose(loss, torch.tensor(0.0))


def test_masked_supervised_loss_gradients_flow() -> None:
    predictions = torch.tensor([1.0, 2.0, 3.0], requires_grad=True)
    targets = torch.tensor([2.0, 2.0, 5.0])
    mask = torch.tensor([True, False, True])

    loss = masked_supervised_loss(predictions, targets, mask)
    loss.backward()

    # Only positions 0 and 2 contribute; position 1's gradient must be 0.
    assert predictions.grad is not None
    assert torch.isclose(predictions.grad[1], torch.tensor(0.0))
    assert predictions.grad[0].abs() > 0
    assert predictions.grad[2].abs() > 0


def test_physics_residual_loss_finite_on_branch_network() -> None:
    network = make_branch_network()
    heads = torch.tensor([100.0, 90.0, 80.0, 80.0], requires_grad=True)
    flows = torch.tensor([0.05, 0.03, 0.02], requires_grad=True)

    loss = physics_residual_loss(network, heads, flows)

    assert torch.isfinite(loss)
    assert loss.item() >= 0.0  # squared L2 norm is non-negative
    # gradients reach predicted state
    loss.backward()
    assert heads.grad is not None and torch.isfinite(heads.grad).all()
    assert flows.grad is not None and torch.isfinite(flows.grad).all()


def test_physics_residual_loss_zero_on_consistent_state() -> None:
    """If heads + flows satisfy the residual exactly, the physics loss is 0."""
    network = make_branch_network()
    # Trivial consistent state: zero flows and demands set to zero would
    # be perfect, but our fixture has non-zero demands. Instead we use
    # the solver to produce a converged state and confirm residual loss
    # is tiny (it is a steady-state solution).
    from aquaoptima.dphm import newton_solve

    result = newton_solve(network, tol=1e-10)
    assert result.converged

    loss = physics_residual_loss(
        network, result.heads.to(torch.get_default_dtype()),
        result.flows.to(torch.get_default_dtype()),
    )
    # Converged solver gives ~0 residual; squared norm should be tiny.
    assert loss.item() < 1e-6


def test_physics_residual_loss_pump_network() -> None:
    network = make_pump_network()
    heads = torch.tensor([5.0, 30.0, 25.0], requires_grad=True)
    flows = torch.tensor([0.02, 0.02], requires_grad=True)

    loss = physics_residual_loss(network, heads, flows)

    assert torch.isfinite(loss)
    loss.backward()
    assert flows.grad is not None and torch.isfinite(flows.grad).all()


def test_composite_loss_returns_components() -> None:
    network = make_branch_network()
    mask = sensor_mask_from_indices(network.num_nodes, [0, 2])

    pred_pressure = torch.tensor([100.0, 90.0, 80.0, 80.0])
    target_pressure = torch.tensor([100.0, 88.0, 79.0, 75.0])
    flows = torch.tensor([0.05, 0.03, 0.02])

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

    assert "data" in out and "physics" in out and "total" in out
    assert torch.isfinite(out["data"])
    assert torch.isfinite(out["physics"])
    assert torch.isfinite(out["total"])
    expected_total = out["data"] + 0.5 * out["physics"]
    assert torch.isclose(out["total"], expected_total)


def test_composite_loss_disable_physics_with_zero_lambda() -> None:
    network = make_branch_network()
    mask = sensor_mask_from_indices(network.num_nodes, [0])

    pred_pressure = torch.tensor([100.0, 90.0, 80.0, 80.0])
    target_pressure = torch.tensor([100.0, 88.0, 79.0, 75.0])
    flows = torch.tensor([0.05, 0.03, 0.02])

    out = composite_loss(
        network=network,
        sensor_mask=mask,
        predicted_pressure=pred_pressure,
        target_pressure=target_pressure,
        predicted_flow=flows,
        target_flow=None,
        flow_sensor_mask=None,
        lambda_data=1.0,
        lambda_physics=0.0,
    )

    # With lambda_physics=0, total reduces to just lambda_data * data.
    assert torch.isclose(out["total"], out["data"])


def test_masked_supervised_loss_shape_mismatch_raises() -> None:
    with pytest.raises(ValueError):
        masked_supervised_loss(
            torch.zeros(3), torch.zeros(4), torch.ones(3, dtype=torch.bool)
        )
