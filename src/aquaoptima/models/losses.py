"""Composite training losses for the dPHM-PINN.

Three loss primitives compose the training objective:

* :func:`masked_supervised_loss` — MSE on observed (SCADA) entries
  only. Virtual nodes contribute nothing; an all-virtual mask yields
  exactly zero (and not NaN from a division by zero). Accepts
  ``[N]``-shaped and ``[B, N]``-shaped tensors interchangeably as long
  as predictions, targets, and mask all share the same shape.
* :func:`physics_residual_loss` — squared L2 norm of the dPHM mass +
  energy residual evaluated on the model's predicted heads and flows.
  Differentiates through :func:`aquaoptima.dphm.assemble_residuals`.
  Accepts ``[N]/[E]`` (unbatched) and ``[B, N]/[B, E]`` (batched), in
  which case the returned scalar is the sum of per-batch residual
  norms — preserving the legacy semantics under a B=1 reduction.
* :func:`composite_loss` — returns the data term, the physics term,
  and the lambda-weighted aggregate as separate keys so the training
  loop can log them independently.

The composite never folds components into the total — callers always
get the unweighted parts back and can re-weight or log them however
they want.
"""

from __future__ import annotations

from typing import Optional

import torch

from aquaoptima.dphm import Network, assemble_residuals, assemble_residuals_batched


def masked_supervised_loss(
    predictions: torch.Tensor,
    targets: torch.Tensor,
    mask: torch.Tensor,
) -> torch.Tensor:
    """Mean squared error over entries where ``mask`` is ``True``.

    Returns a zero scalar (with the same dtype/device as ``predictions``)
    when the mask selects no entries — important so the physics-only
    ablation path does not produce NaNs. Supports any matching shape,
    including ``[N]`` and ``[B, N]``.
    """
    if predictions.shape != targets.shape:
        raise ValueError(
            f"predictions shape {tuple(predictions.shape)} != targets shape "
            f"{tuple(targets.shape)}"
        )
    if mask.shape != predictions.shape:
        raise ValueError(
            f"mask shape {tuple(mask.shape)} != predictions shape "
            f"{tuple(predictions.shape)}"
        )
    if mask.dtype != torch.bool:
        raise ValueError(f"mask must be bool, got dtype={mask.dtype}")

    count = int(mask.sum().item())
    if count == 0:
        return torch.zeros((), dtype=predictions.dtype, device=predictions.device)

    diff = (predictions - targets) ** 2
    return diff[mask].sum() / count


def physics_residual_loss(
    network: Network,
    predicted_heads: torch.Tensor,
    predicted_flows: torch.Tensor,
) -> torch.Tensor:
    """Squared L2 norm of the dPHM residual at the predicted state.

    The residual stacks per-node mass balance (on free nodes only) and
    per-edge energy balance — Hazen-Williams on pipe edges, the affinity
    pump curve on pump edges. Gradients flow through both terms.

    Batched inputs ``[B, N]`` / ``[B, E]`` produce the sum of per-batch
    squared residual norms — equivalent to looping the unbatched call
    over the batch axis and adding. Sprint 7 evaluates this in a
    single vectorized assembly via
    :func:`aquaoptima.dphm.solver.assemble_residuals_batched` rather
    than a Python loop.
    """
    if predicted_heads.dim() == 1 and predicted_flows.dim() == 1:
        residual = assemble_residuals(network, predicted_heads, predicted_flows)
        return (residual ** 2).sum()
    if predicted_heads.dim() == 2 and predicted_flows.dim() == 2:
        if predicted_heads.shape[0] != predicted_flows.shape[0]:
            raise ValueError(
                "predicted_heads and predicted_flows batch dims must match; "
                f"got {predicted_heads.shape[0]} vs {predicted_flows.shape[0]}"
            )
        residual = assemble_residuals_batched(
            network, predicted_heads, predicted_flows
        )  # [B, R]
        return (residual ** 2).sum()
    raise ValueError(
        "physics_residual_loss requires matching rank-1 or rank-2 inputs, "
        f"got heads={tuple(predicted_heads.shape)} "
        f"flows={tuple(predicted_flows.shape)}"
    )


def composite_loss(
    *,
    network: Network,
    sensor_mask: torch.Tensor,
    predicted_pressure: torch.Tensor,
    target_pressure: torch.Tensor,
    predicted_flow: torch.Tensor,
    target_flow: Optional[torch.Tensor] = None,
    flow_sensor_mask: Optional[torch.Tensor] = None,
    lambda_data: float = 1.0,
    lambda_physics: float = 1.0,
) -> dict[str, torch.Tensor]:
    """Return data, physics, and weighted total loss as a dict.

    The "data" term is the masked supervised loss on pressure (and on
    flow if both ``target_flow`` and ``flow_sensor_mask`` are supplied).
    The "physics" term is :func:`physics_residual_loss` over the
    predicted pressure-as-head and flow tensors. The total is
    ``lambda_data * data + lambda_physics * physics``.

    All tensors may carry a leading batch dimension; shapes just have
    to be internally consistent (predictions, targets, and masks must
    match shape).
    """
    data_pressure = masked_supervised_loss(
        predicted_pressure, target_pressure, sensor_mask
    )

    data_flow: torch.Tensor
    if target_flow is not None and flow_sensor_mask is not None:
        data_flow = masked_supervised_loss(
            predicted_flow, target_flow, flow_sensor_mask
        )
    else:
        data_flow = torch.zeros(
            (), dtype=data_pressure.dtype, device=data_pressure.device
        )

    data = data_pressure + data_flow

    physics = physics_residual_loss(network, predicted_pressure, predicted_flow)

    total = lambda_data * data + lambda_physics * physics

    return {
        "data": data,
        "data_pressure": data_pressure,
        "data_flow": data_flow,
        "physics": physics,
        "total": total,
    }


__all__ = ["composite_loss", "masked_supervised_loss", "physics_residual_loss"]
