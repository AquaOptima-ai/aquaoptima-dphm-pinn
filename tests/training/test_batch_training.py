"""Sprint 6 — Batched window training path.

Coverage:

* :class:`TrainConfig` exposes a ``batch_size`` field (default ``1``)
  so callers can opt into multi-window training.
* A single ``train_step`` over a batched window dict produces finite
  loss components and updates at least one parameter.
* ``train_loop`` with ``batch_size > 1`` runs the configured number of
  iterations and records per-step metrics.
* ``B=1`` batched train_step is numerically equivalent to the legacy
  unbatched train_step (modulo a clone of the model + dataset to keep
  randomness aligned).
"""

from __future__ import annotations

import torch

from aquaoptima.dataio import WindowDataset, generate_synthetic_scada
from aquaoptima.dphm import make_branch_network
from aquaoptima.models import DPHMPINN
from aquaoptima.models.lambda_scheduler import FixedLambda
from aquaoptima.topology import build_graph_features, sensor_mask_from_indices
from aquaoptima.training import TrainConfig, TrainingMetrics, train_loop, train_step
from aquaoptima.training.train import collate_windows


def _make_setup(seed: int = 0):
    torch.manual_seed(seed)
    network = make_branch_network()
    sensor_mask = sensor_mask_from_indices(network.num_nodes, [0, 2])
    features = build_graph_features(network, sensor_mask=sensor_mask)
    series = generate_synthetic_scada(network, num_steps=48, seed=seed, window=32)
    dataset = WindowDataset(series, window=32)
    model = DPHMPINN(
        node_in_dim=features.node_feature_dim,
        edge_in_dim=features.edge_feature_dim,
        seq_in_dim=dataset.node_feature_dim,
        hidden_dim=12,
        force_fallback=True,
    )
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    return network, features, dataset, model, optimizer


# ---------------------------------------------------------------------------
# collate helper
# ---------------------------------------------------------------------------


def test_collate_windows_stacks_batch_axis() -> None:
    _, _, dataset, _, _ = _make_setup(seed=0)
    samples = [dataset[i] for i in range(3)]
    batch = collate_windows(samples)
    assert batch["x_seq"].dim() == 4
    assert batch["x_seq"].shape[0] == 3
    assert batch["target_pressure"].shape[0] == 3
    assert batch["target_flow"].shape[0] == 3
    assert batch["target_demand"].shape[0] == 3


def test_collate_windows_single_sample_unbatched() -> None:
    _, _, dataset, _, _ = _make_setup(seed=0)
    sample = dataset[0]
    batch = collate_windows([sample])
    # single-sample collate produces B=1 batched layout
    assert batch["x_seq"].shape[0] == 1
    assert batch["x_seq"].dim() == 4


# ---------------------------------------------------------------------------
# TrainConfig.batch_size
# ---------------------------------------------------------------------------


def test_train_config_has_batch_size_default_one() -> None:
    config = TrainConfig(
        num_iterations=1,
        lambda_data=FixedLambda(1.0),
        lambda_physics=FixedLambda(0.0),
    )
    assert getattr(config, "batch_size", None) == 1


# ---------------------------------------------------------------------------
# batched train_step
# ---------------------------------------------------------------------------


def test_train_step_accepts_batched_window() -> None:
    network, features, dataset, model, optimizer = _make_setup(seed=1)
    samples = [dataset[i] for i in range(4)]
    batch = collate_windows(samples)

    metrics = train_step(
        model=model,
        batch=batch,
        features=features,
        network=network,
        optimizer=optimizer,
        lambda_data=FixedLambda(1.0),
        lambda_physics=FixedLambda(1e-4),
        step=0,
    )
    assert torch.isfinite(torch.tensor(metrics["loss_total"]))
    assert torch.isfinite(torch.tensor(metrics["loss_data"]))
    assert torch.isfinite(torch.tensor(metrics["loss_physics"]))


def test_train_step_batched_updates_a_parameter() -> None:
    network, features, dataset, model, optimizer = _make_setup(seed=2)
    samples = [dataset[i] for i in range(3)]
    batch = collate_windows(samples)

    before = {n: p.detach().clone() for n, p in model.named_parameters()}
    train_step(
        model=model,
        batch=batch,
        features=features,
        network=network,
        optimizer=optimizer,
        lambda_data=FixedLambda(1.0),
        lambda_physics=FixedLambda(1e-4),
        step=0,
    )
    after = {n: p.detach().clone() for n, p in model.named_parameters()}
    changed = [n for n in before if not torch.allclose(before[n], after[n])]
    assert len(changed) >= 1


def test_train_step_batched_gradients_finite() -> None:
    network, features, dataset, model, optimizer = _make_setup(seed=3)
    samples = [dataset[i] for i in range(3)]
    batch = collate_windows(samples)
    train_step(
        model=model,
        batch=batch,
        features=features,
        network=network,
        optimizer=optimizer,
        lambda_data=FixedLambda(1.0),
        lambda_physics=FixedLambda(1e-4),
        step=0,
    )
    for n, p in model.named_parameters():
        if p.grad is not None:
            assert torch.isfinite(p.grad).all().item(), f"non-finite grad in {n}"


# ---------------------------------------------------------------------------
# batched train_loop
# ---------------------------------------------------------------------------


def test_train_loop_batch_size_greater_than_one_runs() -> None:
    network, features, dataset, model, optimizer = _make_setup(seed=4)
    config = TrainConfig(
        num_iterations=3,
        lambda_data=FixedLambda(1.0),
        lambda_physics=FixedLambda(1e-4),
        batch_size=4,
    )
    metrics = train_loop(
        model=model,
        dataset=dataset,
        features=features,
        network=network,
        optimizer=optimizer,
        config=config,
    )
    assert isinstance(metrics, TrainingMetrics)
    assert len(metrics.history) == 3
    for record in metrics.history:
        assert torch.isfinite(torch.tensor(record["loss_total"]))


def test_train_loop_batch_size_one_matches_unbatched() -> None:
    """A ``batch_size=1`` train_loop should produce per-step metric
    values numerically equivalent to legacy unbatched training (within
    a small float tolerance)."""
    # unbatched legacy run
    network_a, features_a, dataset_a, model_a, opt_a = _make_setup(seed=7)
    config_legacy = TrainConfig(
        num_iterations=3,
        lambda_data=FixedLambda(1.0),
        lambda_physics=FixedLambda(1e-4),
    )
    legacy = train_loop(
        model=model_a, dataset=dataset_a, features=features_a,
        network=network_a, optimizer=opt_a, config=config_legacy,
    )

    # batched B=1 run with identical seed / setup
    network_b, features_b, dataset_b, model_b, opt_b = _make_setup(seed=7)
    config_b1 = TrainConfig(
        num_iterations=3,
        lambda_data=FixedLambda(1.0),
        lambda_physics=FixedLambda(1e-4),
        batch_size=1,
    )
    batched = train_loop(
        model=model_b, dataset=dataset_b, features=features_b,
        network=network_b, optimizer=opt_b, config=config_b1,
    )

    for a, b in zip(legacy.history, batched.history):
        assert abs(a["loss_total"] - b["loss_total"]) < 1e-4
        assert abs(a["loss_data"] - b["loss_data"]) < 1e-4
        assert abs(a["loss_physics"] - b["loss_physics"]) < 1e-4
