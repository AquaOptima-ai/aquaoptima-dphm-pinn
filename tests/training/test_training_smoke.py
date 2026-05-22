"""Smoke tests for the Sprint 4 dPHM-PINN training loop.

These tests do not measure convergence quality. They prove that:

* a single ``train_step`` produces finite loss components and finite
  gradients, and updates at least one model parameter;
* a short multi-iteration run on the synthetic SCADA generator keeps
  losses finite throughout (no NaN/Inf explosion);
* the supervised-only and supervised-plus-physics paths both run;
* per-iteration metrics are recorded and reported.
"""

from __future__ import annotations

import torch

from aquaoptima.dataio import WindowDataset, generate_synthetic_scada
from aquaoptima.dphm import make_branch_network
from aquaoptima.models import DPHMPINN
from aquaoptima.models.lambda_scheduler import FixedLambda
from aquaoptima.topology import build_graph_features, sensor_mask_from_indices
from aquaoptima.training import (
    TrainConfig,
    TrainingMetrics,
    train_loop,
    train_step,
)


def _make_setup(seed: int = 0):
    torch.manual_seed(seed)
    network = make_branch_network()
    sensor_mask = sensor_mask_from_indices(network.num_nodes, [0, 2])
    features = build_graph_features(network, sensor_mask=sensor_mask)

    series = generate_synthetic_scada(network, num_steps=40, seed=seed, window=32)
    dataset = WindowDataset(series, window=32)

    model = DPHMPINN(
        node_in_dim=features.node_feature_dim,
        edge_in_dim=features.edge_feature_dim,
        seq_in_dim=dataset.node_feature_dim,
        hidden_dim=16,
        force_fallback=True,
    )
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    return network, features, dataset, model, optimizer


def test_train_step_returns_finite_components() -> None:
    network, features, dataset, model, optimizer = _make_setup()
    batch = dataset[0]

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

    assert "loss_total" in metrics
    assert "loss_data" in metrics
    assert "loss_physics" in metrics
    assert torch.isfinite(torch.tensor(metrics["loss_total"]))
    assert torch.isfinite(torch.tensor(metrics["loss_data"]))
    assert torch.isfinite(torch.tensor(metrics["loss_physics"]))


def test_train_step_updates_at_least_one_parameter() -> None:
    network, features, dataset, model, optimizer = _make_setup(seed=1)
    batch = dataset[0]

    # snapshot every parameter
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
    assert len(changed) >= 1, "expected at least one parameter to update"


def test_train_step_gradients_are_finite() -> None:
    network, features, dataset, model, optimizer = _make_setup(seed=2)
    batch = dataset[0]

    train_step(
        model=model,
        batch=batch,
        features=features,
        network=network,
        optimizer=optimizer,
        lambda_data=FixedLambda(1.0),
        lambda_physics=FixedLambda(1e-4),
        step=0,
        return_grads=True,
    )

    for name, p in model.named_parameters():
        if p.grad is None:
            continue
        assert torch.isfinite(p.grad).all(), (
            f"parameter {name} has non-finite gradient"
        )


def test_train_loop_runs_a_few_iterations_finite() -> None:
    network, features, dataset, model, optimizer = _make_setup(seed=3)

    config = TrainConfig(
        num_iterations=4,
        lambda_data=FixedLambda(1.0),
        lambda_physics=FixedLambda(1e-4),
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
    assert len(metrics.history) == 4
    for record in metrics.history:
        assert torch.isfinite(torch.tensor(record["loss_total"]))
        assert torch.isfinite(torch.tensor(record["loss_data"]))
        assert torch.isfinite(torch.tensor(record["loss_physics"]))


def test_train_loop_sensor_only_mode_skips_physics() -> None:
    network, features, dataset, model, optimizer = _make_setup(seed=4)

    config = TrainConfig(
        num_iterations=3,
        lambda_data=FixedLambda(1.0),
        lambda_physics=FixedLambda(0.0),  # sensor-only
    )

    metrics = train_loop(
        model=model,
        dataset=dataset,
        features=features,
        network=network,
        optimizer=optimizer,
        config=config,
    )

    # Physics term is still reported (unweighted), but its contribution
    # to the weighted total is zero — total should equal data.
    last = metrics.history[-1]
    assert abs(last["loss_total"] - last["loss_data"]) < 1e-5


def test_training_metrics_summary_keys() -> None:
    network, features, dataset, model, optimizer = _make_setup(seed=5)
    config = TrainConfig(
        num_iterations=3,
        lambda_data=FixedLambda(1.0),
        lambda_physics=FixedLambda(1e-4),
    )
    metrics = train_loop(
        model=model,
        dataset=dataset,
        features=features,
        network=network,
        optimizer=optimizer,
        config=config,
    )
    summary = metrics.summary()
    assert "final_total" in summary
    assert "final_data" in summary
    assert "final_physics" in summary
    assert summary["num_iterations"] == 3
