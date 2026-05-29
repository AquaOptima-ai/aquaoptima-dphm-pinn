"""Sprint 26: residual-over-persistence target construction & reconstruction."""
import numpy as np
import pytest

from aquaoptima.training.evaluation import reconstruct_absolute


def test_residual_reconstruction_recovers_absolute():
    """residual mode: last_value + Delta_hat (un-normalized) == absolute pred."""
    n, k = 5, 3
    rng = np.random.default_rng(0)
    mu = rng.normal(size=k) * 10
    sigma = np.abs(rng.normal(size=k)) + 0.5
    # ground-truth absolute (physical) values at t+h
    true_abs = rng.normal(size=(n, k)) * 5 + mu
    last_phys = rng.normal(size=(n, k)) * 5 + mu
    last_norm = (last_phys - mu) / sigma
    # a perfect residual model emits exactly the normalized delta
    perfect_delta = (true_abs - mu) / sigma - last_norm
    pred_abs = reconstruct_absolute(
        perfect_delta, last_norm, mu, sigma,
        target_mode="residual", active_axes=["a", "b", "c"], binary_axes=(),
    )
    assert np.allclose(pred_abs, true_abs, atol=1e-6)


def test_persistence_equals_zero_residual():
    """Predicting Delta=0 must reproduce the persistence (last-value) prediction."""
    n, k = 4, 2
    mu = np.array([1.0, -2.0])
    sigma = np.array([2.0, 0.5])
    last_phys = np.array([[3.0, 0.0], [1.0, -2.0], [5.0, 1.0], [0.0, -1.0]])
    last_norm = (last_phys - mu) / sigma
    zero_delta = np.zeros((n, k))
    pred_abs = reconstruct_absolute(
        zero_delta, last_norm, mu, sigma,
        target_mode="residual", active_axes=["a", "b"], binary_axes=(),
    )
    assert np.allclose(pred_abs, last_phys, atol=1e-6)


def test_absolute_mode_unaffected_by_anchor():
    """absolute mode: model output is the normalized absolute value (anchor ignored)."""
    n, k = 3, 2
    mu = np.array([10.0, 0.0])
    sigma = np.array([1.0, 4.0])
    true_abs = np.array([[11.0, 8.0], [9.0, -4.0], [10.0, 0.0]])
    norm_abs = (true_abs - mu) / sigma
    junk_anchor = np.full((n, k), 99.0)
    pred_abs = reconstruct_absolute(
        norm_abs, junk_anchor, mu, sigma,
        target_mode="absolute", active_axes=["a", "b"], binary_axes=(),
    )
    assert np.allclose(pred_abs, true_abs, atol=1e-6)
