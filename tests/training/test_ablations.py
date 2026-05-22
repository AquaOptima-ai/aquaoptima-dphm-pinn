"""Tests for the sensor-only vs sensor-plus-physics ablation harness.

The harness reuses the same data, model architecture, and optimizer
hyperparameters across both modes — only the loss weighting differs.
That way any apples-to-apples comparison is meaningful.
"""

from __future__ import annotations

import pytest
import torch

from aquaoptima.training.ablations import (
    ABLATION_MODES,
    run_ablation,
)


def test_ablation_modes_list() -> None:
    assert "sensor_only" in ABLATION_MODES
    assert "sensor_plus_physics" in ABLATION_MODES


def test_sensor_only_runs_and_returns_metrics() -> None:
    result = run_ablation(
        mode="sensor_only",
        num_iterations=3,
        seed=0,
    )

    assert "mode" in result
    assert result["mode"] == "sensor_only"
    assert "summary" in result
    assert "history" in result
    assert len(result["history"]) == 3
    for record in result["history"]:
        for key in ("loss_total", "loss_data", "loss_physics"):
            assert torch.isfinite(torch.tensor(record[key]))


def test_sensor_plus_physics_runs_and_returns_metrics() -> None:
    result = run_ablation(
        mode="sensor_plus_physics",
        num_iterations=3,
        seed=0,
    )

    assert result["mode"] == "sensor_plus_physics"
    assert len(result["history"]) == 3
    for record in result["history"]:
        for key in ("loss_total", "loss_data", "loss_physics"):
            assert torch.isfinite(torch.tensor(record[key]))


def test_sensor_only_has_zero_physics_weight_in_total() -> None:
    result = run_ablation(
        mode="sensor_only",
        num_iterations=2,
        seed=1,
    )
    # In sensor_only, lambda_physics is exactly zero — so loss_total
    # must equal lambda_data * loss_data; with default lambda_data=1
    # this means loss_total == loss_data.
    last = result["history"][-1]
    assert abs(last["loss_total"] - last["loss_data"]) < 1e-5


def test_sensor_plus_physics_uses_nonzero_physics_weight() -> None:
    result = run_ablation(
        mode="sensor_plus_physics",
        num_iterations=2,
        seed=1,
    )
    # The reported per-step lambda_physics is non-zero in this mode.
    for record in result["history"]:
        assert record["lambda_physics"] > 0.0


def test_unknown_ablation_mode_raises() -> None:
    with pytest.raises(ValueError):
        run_ablation(mode="not_a_real_mode", num_iterations=1, seed=0)


def test_ablation_summary_has_num_iterations() -> None:
    result = run_ablation(
        mode="sensor_only",
        num_iterations=4,
        seed=2,
    )
    assert result["summary"]["num_iterations"] == 4
