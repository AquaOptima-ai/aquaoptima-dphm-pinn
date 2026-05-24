"""Training loop for the dPHM-PINN.

A single :func:`train_step` runs forward + composite loss + backward +
optimizer step on one window (or one batched mini-batch of windows).
:func:`train_loop` iterates a number of training steps over a
:class:`WindowDataset`, optionally batching ``batch_size`` consecutive
windows per step.

Two lambda schedulers (``lambda_data`` and ``lambda_physics``) feed
:func:`aquaoptima.models.losses.composite_loss`. The per-step weights
are sampled at each iteration so the linear-ramp schedule does what
its name says.

Batching contract (Sprint 6):

* ``batch_size == 1`` — legacy single-window path. The batch dict
  carries ``[T, N, F]`` / ``[N]`` / ``[E]`` shaped tensors and the
  model receives the unbatched layout.
* ``batch_size > 1`` — :func:`collate_windows` stacks ``batch_size``
  consecutive samples into ``[B, T, N, F]`` / ``[B, N]`` / ``[B, E]``.
  The model is invoked on the batched layout and the sensor mask is
  broadcast across the batch dimension.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Sequence

import torch
from torch.utils.data import DataLoader, Dataset

from aquaoptima.dphm import Network
from aquaoptima.models.losses import composite_loss
from aquaoptima.models.lambda_scheduler import LambdaScheduler
from aquaoptima.topology import GraphFeatures

from .metrics import TrainingMetrics


def collate_windows(samples: Sequence[dict[str, torch.Tensor]]) -> dict[str, torch.Tensor]:
    """Stack a list of window dicts along a new leading batch axis.

    Each sample is the per-window dict produced by
    :class:`aquaoptima.dataio.WindowDataset` — keys ``x_seq``,
    ``target_pressure``, ``target_flow``, ``target_demand``. The
    collated dict carries identically named tensors with an extra
    leading ``B`` dimension. Even a single-element list produces a
    batched layout (``B=1``) so downstream code can treat the result
    uniformly.
    """
    if len(samples) == 0:
        raise ValueError("collate_windows requires at least one sample")
    keys = samples[0].keys()
    out: dict[str, torch.Tensor] = {}
    for k in keys:
        out[k] = torch.stack([s[k] for s in samples], dim=0)
    return out


def _expand_sensor_mask(mask: torch.Tensor, batch_size: int) -> torch.Tensor:
    if mask.dim() == 1:
        return mask.unsqueeze(0).expand(batch_size, -1)
    if mask.dim() == 2 and mask.shape[0] == batch_size:
        return mask
    raise ValueError(
        f"sensor_mask shape {tuple(mask.shape)} incompatible with batch={batch_size}"
    )


def train_step(
    *,
    model: torch.nn.Module,
    batch: dict[str, torch.Tensor],
    features: GraphFeatures,
    network: Network,
    optimizer: torch.optim.Optimizer,
    lambda_data: LambdaScheduler,
    lambda_physics: LambdaScheduler,
    step: int,
    return_grads: bool = False,
) -> dict[str, float]:
    """Run one forward / backward / optimizer step. Returns a metrics dict.

    Accepts both legacy unbatched batch dicts (``x_seq[T, N, F]``,
    ``target_pressure[N]``) and Sprint 6 batched dicts (``x_seq
    [B, T, N, F]``, ``target_pressure[B, N]``). The sensor mask carried
    by ``features`` is broadcast across the batch dimension as needed.
    """
    model.train()
    optimizer.zero_grad()

    x_seq = batch["x_seq"]
    batched = x_seq.dim() == 4

    outputs = model(x_seq, features)

    if batched:
        B = x_seq.shape[0]
        sensor_mask = _expand_sensor_mask(features.sensor_mask, B)
    else:
        sensor_mask = features.sensor_mask

    ld = float(lambda_data.value(step))
    lp = float(lambda_physics.value(step))

    losses = composite_loss(
        network=network,
        sensor_mask=sensor_mask,
        predicted_pressure=outputs["pressure"],
        target_pressure=batch["target_pressure"],
        predicted_flow=outputs["flow"],
        target_flow=None,
        flow_sensor_mask=None,
        lambda_data=ld,
        lambda_physics=lp,
    )
    total = losses["total"]
    total.backward()
    optimizer.step()

    metrics: dict[str, float] = {
        "step": float(step),
        "lambda_data": ld,
        "lambda_physics": lp,
        "loss_total": float(total.detach().item()),
        "loss_data": float(losses["data"].detach().item()),
        "loss_data_pressure": float(losses["data_pressure"].detach().item()),
        "loss_data_flow": float(losses["data_flow"].detach().item()),
        "loss_physics": float(losses["physics"].detach().item()),
    }

    if return_grads:
        pass

    return metrics


@dataclass
class TrainConfig:
    """Config for :func:`train_loop`."""

    num_iterations: int
    lambda_data: LambdaScheduler
    lambda_physics: LambdaScheduler
    sample_indices: Optional[list[int]] = None  # If None, cycle dataset.
    batch_size: int = 1


def train_loop(
    *,
    model: torch.nn.Module,
    dataset: Dataset,
    features: GraphFeatures,
    network: Network,
    optimizer: torch.optim.Optimizer,
    config: TrainConfig,
) -> TrainingMetrics:
    """Run ``config.num_iterations`` training steps and collect metrics.

    When ``config.batch_size > 1``, each iteration consumes
    ``batch_size`` consecutive (cyclically indexed) dataset entries
    and runs a single batched forward/backward step over them.
    """
    if config.num_iterations <= 0:
        raise ValueError(
            f"num_iterations must be positive, got {config.num_iterations}"
        )
    if config.batch_size < 1:
        raise ValueError(
            f"batch_size must be >= 1, got {config.batch_size}"
        )

    n = len(dataset)  # type: ignore[arg-type]
    if n == 0:
        raise ValueError("dataset must be non-empty")

    if config.sample_indices is not None:
        idx_source: list[int] = list(config.sample_indices)
    else:
        # Enough indices to cover num_iterations * batch_size with cycling.
        total_needed = config.num_iterations * config.batch_size
        idx_source = [i % n for i in range(total_needed)]

    metrics = TrainingMetrics()
    cursor = 0
    for step in range(config.num_iterations):
        if config.batch_size == 1:
            sample_idx = idx_source[step % len(idx_source)]
            batch: dict[str, Any] = dataset[sample_idx]  # type: ignore[index]
        else:
            samples = []
            for _ in range(config.batch_size):
                samples.append(dataset[idx_source[cursor % len(idx_source)]])  # type: ignore[index]
                cursor += 1
            batch = collate_windows(samples)
        record = train_step(
            model=model,
            batch=batch,
            features=features,
            network=network,
            optimizer=optimizer,
            lambda_data=config.lambda_data,
            lambda_physics=config.lambda_physics,
            step=step,
        )
        metrics.record(record)

    return metrics


def make_window_dataloader(
    dataset: Dataset,
    batch_size: int,
    *,
    shuffle: bool = False,
    drop_last: bool = False,
    num_workers: int = 0,
) -> DataLoader:
    """Wrap a window dataset in a :class:`DataLoader` that uses
    :func:`collate_windows`.

    The collate function is the same Sprint 6 helper used by
    :func:`train_loop` — single-sample lists produce a ``B=1`` batched
    layout, so callers can flip between batched and unbatched paths by
    only changing ``batch_size``. ``shuffle`` defaults to ``False`` so
    sequential passes over the dataset are reproducible; set it to
    ``True`` for stochastic mini-batches.
    """
    if batch_size < 1:
        raise ValueError(f"batch_size must be >= 1, got {batch_size}")
    return DataLoader(
        dataset,
        batch_size=int(batch_size),
        shuffle=bool(shuffle),
        drop_last=bool(drop_last),
        num_workers=int(num_workers),
        collate_fn=collate_windows,
    )


def train_loop_dataloader(
    *,
    model: torch.nn.Module,
    loader: DataLoader,
    features: GraphFeatures,
    network: Network,
    optimizer: torch.optim.Optimizer,
    config: TrainConfig,
) -> TrainingMetrics:
    """Run ``config.num_iterations`` :func:`train_step` calls using
    batches drawn from ``loader``.

    The loader is treated as a cyclic stream: when it is exhausted
    mid-loop, a fresh iterator is created. This keeps the training
    contract identical to :func:`train_loop` (the iteration count is
    decoupled from the dataset length) while letting callers control
    batching, shuffling, and worker concurrency via standard PyTorch
    ``DataLoader`` knobs.
    """
    if config.num_iterations <= 0:
        raise ValueError(
            f"num_iterations must be positive, got {config.num_iterations}"
        )

    metrics = TrainingMetrics()
    it = iter(loader)
    for step in range(config.num_iterations):
        try:
            batch = next(it)
        except StopIteration:
            it = iter(loader)
            batch = next(it)
        record = train_step(
            model=model,
            batch=batch,
            features=features,
            network=network,
            optimizer=optimizer,
            lambda_data=config.lambda_data,
            lambda_physics=config.lambda_physics,
            step=step,
        )
        metrics.record(record)
    return metrics


__all__ = [
    "TrainConfig",
    "collate_windows",
    "make_window_dataloader",
    "train_loop",
    "train_loop_dataloader",
    "train_step",
]
