"""Sprint 7 — DataLoader ergonomics around :class:`WindowDataset`.

Coverage:

* :func:`make_window_dataloader` wraps a ``WindowDataset`` with the
  Sprint 6 :func:`collate_windows` collator and yields batches with
  ``[B, T, N, F]`` window tensors and ``[B, N]`` / ``[B, E]`` targets.
* Batches respect ``batch_size`` and a sequential (``shuffle=False``)
  pass over the dataset covers every window exactly once.
* No future leakage: every window in a batch is a strict prefix of
  its associated target (this just re-asserts the existing
  :class:`WindowDataset` contract under DataLoader batching).
* :func:`train_loop_dataloader` (or :func:`train_loop` with a
  DataLoader path) advances training over several DataLoader batches,
  keeping finite loss components and changing at least one model
  parameter.
"""

from __future__ import annotations

import torch
from torch.utils.data import DataLoader

from aquaoptima.dataio import WindowDataset, generate_synthetic_scada
from aquaoptima.dphm import make_branch_network
from aquaoptima.models import DPHMPINN
from aquaoptima.models.lambda_scheduler import FixedLambda
from aquaoptima.topology import build_graph_features, sensor_mask_from_indices
from aquaoptima.training import TrainConfig, train_step
from aquaoptima.training.train import (
    collate_windows,
    make_window_dataloader,
    train_loop_dataloader,
)


def _make_setup(seed: int = 0, num_steps: int = 48, window: int = 32):
    torch.manual_seed(seed)
    network = make_branch_network()
    sensor_mask = sensor_mask_from_indices(network.num_nodes, [0, 2])
    features = build_graph_features(network, sensor_mask=sensor_mask)
    series = generate_synthetic_scada(network, num_steps=num_steps, seed=seed, window=window)
    dataset = WindowDataset(series, window=window)
    model = DPHMPINN(
        node_in_dim=features.node_feature_dim,
        edge_in_dim=features.edge_feature_dim,
        seq_in_dim=dataset.node_feature_dim,
        hidden_dim=12,
        force_fallback=True,
    )
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    return network, features, dataset, model, optimizer


def test_make_window_dataloader_returns_dataloader() -> None:
    _, _, dataset, _, _ = _make_setup(seed=0)
    loader = make_window_dataloader(dataset, batch_size=4, shuffle=False)
    assert isinstance(loader, DataLoader)


def test_make_window_dataloader_yields_batched_shapes() -> None:
    network, _, dataset, _, _ = _make_setup(seed=1)
    loader = make_window_dataloader(dataset, batch_size=4, shuffle=False)
    batch = next(iter(loader))
    assert batch["x_seq"].dim() == 4
    assert batch["x_seq"].shape[0] == 4
    # [B, T, N, F]
    assert batch["x_seq"].shape[2] == network.num_nodes
    assert batch["target_pressure"].shape == (4, network.num_nodes)
    assert batch["target_flow"].shape == (4, network.num_edges)
    assert batch["target_demand"].shape == (4, network.num_nodes)


def test_make_window_dataloader_drop_last_false_yields_partial_tail() -> None:
    _, _, dataset, _, _ = _make_setup(seed=2)
    bs = 5
    loader = make_window_dataloader(dataset, batch_size=bs, shuffle=False)
    batches = list(loader)
    total = sum(b["x_seq"].shape[0] for b in batches)
    assert total == len(dataset)
    # last batch may be smaller, but never larger.
    assert all(b["x_seq"].shape[0] <= bs for b in batches)


def test_make_window_dataloader_uses_collate_windows() -> None:
    """The dataloader must produce batches indistinguishable from a
    direct :func:`collate_windows` call over the same indices."""
    _, _, dataset, _, _ = _make_setup(seed=3)
    loader = make_window_dataloader(dataset, batch_size=3, shuffle=False)
    first = next(iter(loader))
    manual = collate_windows([dataset[i] for i in range(3)])
    for key in ("x_seq", "target_pressure", "target_flow", "target_demand"):
        assert torch.allclose(first[key], manual[key])


def test_window_dataloader_does_not_leak_future_into_input() -> None:
    """Each batched x_seq[b] is a strict prefix of the underlying telemetry;
    target tensors must not appear inside the window."""
    _, _, dataset, _, _ = _make_setup(seed=4)
    loader = make_window_dataloader(dataset, batch_size=2, shuffle=False)
    for batch in loader:
        x_seq = batch["x_seq"]              # [B, T, N, 2]
        target_pressure = batch["target_pressure"]  # [B, N]
        # x_seq[..., 1] is the pressure channel
        for b in range(x_seq.shape[0]):
            for t in range(x_seq.shape[1]):
                assert not torch.equal(x_seq[b, t, :, 1], target_pressure[b]), (
                    "future target pressure leaked into x_seq window"
                )


def test_train_loop_dataloader_runs_and_updates_params() -> None:
    network, features, dataset, model, optimizer = _make_setup(seed=5)
    loader = make_window_dataloader(dataset, batch_size=4, shuffle=False)

    before = {n: p.detach().clone() for n, p in model.named_parameters()}
    metrics = train_loop_dataloader(
        model=model,
        loader=loader,
        features=features,
        network=network,
        optimizer=optimizer,
        config=TrainConfig(
            num_iterations=3,
            lambda_data=FixedLambda(1.0),
            lambda_physics=FixedLambda(1e-4),
            batch_size=4,
        ),
    )
    after = {n: p.detach().clone() for n, p in model.named_parameters()}

    assert len(metrics.history) == 3
    for record in metrics.history:
        assert torch.isfinite(torch.tensor(record["loss_total"]))
        assert torch.isfinite(torch.tensor(record["loss_data"]))
        assert torch.isfinite(torch.tensor(record["loss_physics"]))

    changed = [n for n in before if not torch.allclose(before[n], after[n])]
    assert len(changed) >= 1


def test_train_loop_dataloader_cycles_when_iterations_exceed_loader_len() -> None:
    """If num_iterations > number of DataLoader batches, the loop cycles
    through the loader instead of stopping early."""
    network, features, dataset, model, optimizer = _make_setup(seed=6)
    loader = make_window_dataloader(dataset, batch_size=8, shuffle=False)
    n_batches = len(loader)
    iters = n_batches * 2 + 1  # guaranteed to require cycling

    metrics = train_loop_dataloader(
        model=model,
        loader=loader,
        features=features,
        network=network,
        optimizer=optimizer,
        config=TrainConfig(
            num_iterations=iters,
            lambda_data=FixedLambda(1.0),
            lambda_physics=FixedLambda(1e-4),
            batch_size=8,
        ),
    )
    assert len(metrics.history) == iters


def test_dataloader_b1_train_step_matches_legacy_unbatched_step() -> None:
    """A DataLoader with batch_size=1 produces a [1, T, N, F] window; the
    resulting train_step output should track the legacy unbatched
    train_step on the same window within numerical tolerance."""
    network_a, features_a, dataset_a, model_a, opt_a = _make_setup(seed=11)
    legacy = train_step(
        model=model_a,
        batch=dataset_a[0],
        features=features_a,
        network=network_a,
        optimizer=opt_a,
        lambda_data=FixedLambda(1.0),
        lambda_physics=FixedLambda(1e-4),
        step=0,
    )

    network_b, features_b, dataset_b, model_b, opt_b = _make_setup(seed=11)
    loader = make_window_dataloader(dataset_b, batch_size=1, shuffle=False)
    batch = next(iter(loader))
    batched = train_step(
        model=model_b,
        batch=batch,
        features=features_b,
        network=network_b,
        optimizer=opt_b,
        lambda_data=FixedLambda(1.0),
        lambda_physics=FixedLambda(1e-4),
        step=0,
    )
    assert abs(legacy["loss_total"] - batched["loss_total"]) < 1e-4
    assert abs(legacy["loss_data"] - batched["loss_data"]) < 1e-4
    assert abs(legacy["loss_physics"] - batched["loss_physics"]) < 1e-4
