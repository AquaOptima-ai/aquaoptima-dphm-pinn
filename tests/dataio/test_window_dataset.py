"""Tests for synthetic SCADA generation and 32-step window dataset."""

from __future__ import annotations

import pytest
import torch

from aquaoptima.dataio import (
    ScadaSeries,
    WindowDataset,
    generate_synthetic_scada,
)
from aquaoptima.dphm import make_branch_network


# --- synthetic SCADA ------------------------------------------------------


def test_generate_synthetic_scada_returns_correct_shapes() -> None:
    net = make_branch_network()
    series = generate_synthetic_scada(net, num_steps=64, seed=0)

    assert isinstance(series, ScadaSeries)
    assert series.pressure.shape == (64, net.num_nodes)
    assert series.flow.shape == (64, net.num_edges)
    assert series.demand.shape == (64, net.num_nodes)


def test_generate_synthetic_scada_is_seeded_and_reproducible() -> None:
    net = make_branch_network()
    s1 = generate_synthetic_scada(net, num_steps=32, seed=42)
    s2 = generate_synthetic_scada(net, num_steps=32, seed=42)
    assert torch.equal(s1.pressure, s2.pressure)
    assert torch.equal(s1.flow, s2.flow)
    assert torch.equal(s1.demand, s2.demand)


def test_generate_synthetic_scada_different_seeds_differ() -> None:
    net = make_branch_network()
    s1 = generate_synthetic_scada(net, num_steps=32, seed=1)
    s2 = generate_synthetic_scada(net, num_steps=32, seed=2)
    assert not torch.equal(s1.demand, s2.demand)


def test_generate_synthetic_scada_finite_values() -> None:
    net = make_branch_network()
    series = generate_synthetic_scada(net, num_steps=33, seed=7)
    assert torch.isfinite(series.pressure).all().item()
    assert torch.isfinite(series.flow).all().item()
    assert torch.isfinite(series.demand).all().item()


def test_generate_synthetic_scada_rejects_too_short() -> None:
    net = make_branch_network()
    with pytest.raises(ValueError):
        # Not enough room for at least one 32-step window + 1-step target.
        generate_synthetic_scada(net, num_steps=10, seed=0, window=32)


# --- WindowDataset --------------------------------------------------------


def test_window_dataset_length_excludes_target_step() -> None:
    # With T=64 steps and window=32 we can build 64 - 32 = 32 windows whose
    # target step (idx + window) stays within [0, T).
    net = make_branch_network()
    series = generate_synthetic_scada(net, num_steps=64, seed=0)
    ds = WindowDataset(series, window=32)
    assert len(ds) == 32


def test_window_dataset_item_shapes() -> None:
    net = make_branch_network()
    series = generate_synthetic_scada(net, num_steps=64, seed=0)
    ds = WindowDataset(series, window=32)
    sample = ds[0]

    assert sample["x_seq"].shape == (32, net.num_nodes, ds.node_feature_dim)
    assert sample["target_pressure"].shape == (net.num_nodes,)
    assert sample["target_flow"].shape == (net.num_edges,)
    assert sample["target_demand"].shape == (net.num_nodes,)


def test_window_dataset_no_future_leakage() -> None:
    # The features at window index t must come from SCADA step ``idx + t``,
    # never from any step ``>= idx + window``.
    net = make_branch_network()
    series = generate_synthetic_scada(net, num_steps=64, seed=0)
    ds = WindowDataset(series, window=32)
    sample = ds[5]

    # x_seq[:, :, 0] is the demand by builder contract — verify it matches.
    expected_demand = series.demand[5 : 5 + 32]
    assert torch.allclose(sample["x_seq"][:, :, 0], expected_demand)

    # The target step is step 5 + 32 = 37 and must NOT appear inside x_seq.
    target_demand = series.demand[5 + 32]
    assert torch.allclose(sample["target_demand"], target_demand)
    # Confirm the target is strictly beyond the window's last step.
    last_window_step_demand = series.demand[5 + 32 - 1]
    assert not torch.equal(last_window_step_demand, target_demand) or torch.allclose(
        sample["x_seq"][-1, :, 0], last_window_step_demand
    )


def test_window_dataset_out_of_range() -> None:
    net = make_branch_network()
    series = generate_synthetic_scada(net, num_steps=64, seed=0)
    ds = WindowDataset(series, window=32)
    with pytest.raises(IndexError):
        ds[len(ds)]


def test_window_dataset_rejects_inconsistent_window() -> None:
    net = make_branch_network()
    series = generate_synthetic_scada(net, num_steps=64, seed=0)
    with pytest.raises(ValueError):
        WindowDataset(series, window=0)
