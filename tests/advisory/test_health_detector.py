"""Sprint 29 tests for the learned health detector.

Subset / fixture only. Verifies:
* Same seed + same data produce bit-identical fitted state and scores.
* Different seeds produce different fitted state (so the seed actually matters).
* The Sprint-27 leakage guard fires on a March-2026 key before any fit.
* The detector returns the documented columns and ranges.
* Frozen normalisation stats (explicit mapping / JSON path) take priority over
  input-frame statistics.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from aquaoptima.advisory.health_baselines import LeakageError
from aquaoptima.advisory.health_detector import (
    DEFAULT_HIDDEN_DIM,
    DEFAULT_LATENT_DIM,
    FittedHealthDetector,
    HealthAutoencoder,
    fit_health_detector,
)


TEST_AXES = ("edge_flow", "edge_power", "edge_pump_speed", "node_pressure")


def _synthetic_2025_normal(n_rows: int = 400, seed: int = 17) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    flow = rng.normal(loc=1500.0, scale=80.0, size=n_rows)
    speed = rng.normal(loc=42.0, scale=1.5, size=n_rows)
    power = 0.05 * flow + 1.5 * speed + rng.normal(loc=0.0, scale=2.0, size=n_rows)
    pressure = rng.normal(loc=18.0, scale=0.5, size=n_rows)
    ts = pd.date_range("2025-07-01 00:00:00", periods=n_rows, freq="1min").strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    return pd.DataFrame(
        {
            "timestamp": ts,
            "edge_flow": flow,
            "edge_power": power,
            "edge_pump_speed": speed,
            "node_pressure": pressure,
        }
    )


@pytest.fixture()
def normal_frames() -> pd.DataFrame:
    return _synthetic_2025_normal()


@pytest.fixture()
def fit_kwargs() -> dict:
    return {
        "axes": list(TEST_AXES),
        "seed": 0,
        "epochs": 15,
        "batch_size": 64,
        "hidden_dim": DEFAULT_HIDDEN_DIM,
        "latent_dim": DEFAULT_LATENT_DIM,
    }


def test_fit_returns_fitted_detector(normal_frames, fit_kwargs):
    det = fit_health_detector(normal_frames, **fit_kwargs)
    assert isinstance(det, FittedHealthDetector)
    assert det.axes == TEST_AXES
    assert det.n_train_rows + det.n_val_rows == len(normal_frames)
    assert det.train_error_p995 >= 0.0
    assert det.flag_threshold_error >= 0.0


def test_score_returns_documented_columns(normal_frames, fit_kwargs):
    det = fit_health_detector(normal_frames, **fit_kwargs)
    scored = det.score(normal_frames)
    assert list(scored.columns) == [
        "detector_recon_error",
        "detector_anomaly_score",
        "detector_flag",
    ]
    assert (scored["detector_anomaly_score"].to_numpy() >= 0).all()
    assert (scored["detector_anomaly_score"].to_numpy() <= 1).all()
    assert set(scored["detector_flag"].unique().tolist()) <= {0, 1}


def test_determinism_same_seed_same_scores(normal_frames, fit_kwargs):
    det1 = fit_health_detector(normal_frames, **fit_kwargs)
    det2 = fit_health_detector(normal_frames, **fit_kwargs)
    # Same training final loss (rounded for float jitter).
    assert det1.train_final_loss == pytest.approx(det2.train_final_loss, rel=0, abs=0.0)
    # Same state_dict (bit-identical) across the whole model.
    keys = sorted(det1.state_dict.keys())
    assert keys == sorted(det2.state_dict.keys())
    for k in keys:
        np.testing.assert_array_equal(
            det1.state_dict[k].numpy(), det2.state_dict[k].numpy()
        )
    s1 = det1.score(normal_frames)
    s2 = det2.score(normal_frames)
    np.testing.assert_array_equal(
        s1["detector_recon_error"].to_numpy(),
        s2["detector_recon_error"].to_numpy(),
    )
    np.testing.assert_array_equal(
        s1["detector_anomaly_score"].to_numpy(),
        s2["detector_anomaly_score"].to_numpy(),
    )


def test_different_seed_changes_scores(normal_frames, fit_kwargs):
    kwargs_a = dict(fit_kwargs)
    kwargs_a["seed"] = 0
    kwargs_b = dict(fit_kwargs)
    kwargs_b["seed"] = 7
    det_a = fit_health_detector(normal_frames, **kwargs_a)
    det_b = fit_health_detector(normal_frames, **kwargs_b)
    s_a = det_a.score(normal_frames)["detector_recon_error"].to_numpy()
    s_b = det_b.score(normal_frames)["detector_recon_error"].to_numpy()
    # The two detectors must NOT produce identical reconstruction errors.
    assert not np.array_equal(s_a, s_b)


def test_leakage_guard_fires_on_march_2026_key(normal_frames, fit_kwargs):
    leaked = normal_frames.copy()
    leaked.loc[0, "timestamp"] = "2026-03-15 00:00:00"
    with pytest.raises(LeakageError) as exc_info:
        fit_health_detector(leaked, **fit_kwargs)
    assert "2026-03" in str(exc_info.value)


def test_explicit_norm_stats_take_priority(normal_frames, fit_kwargs):
    explicit = {
        a: {"mu": 0.0, "sigma": 1.0} for a in TEST_AXES
    }
    det = fit_health_detector(normal_frames, norm_stats=explicit, **fit_kwargs)
    assert det.norm_source == "explicit_mapping"
    assert det.mu == tuple(0.0 for _ in TEST_AXES)
    assert det.sigma == tuple(1.0 for _ in TEST_AXES)


def test_norm_stats_from_json_file(tmp_path, normal_frames, fit_kwargs):
    stats_path = tmp_path / "stats.json"
    stats_payload = {
        "split_version": "test",
        "stats": {
            a: {"mu": 0.0, "sigma": 1.0, "n": 100} for a in TEST_AXES
        },
    }
    stats_path.write_text(json.dumps(stats_payload))
    det = fit_health_detector(
        normal_frames, norm_stats_path=stats_path, **fit_kwargs
    )
    assert det.norm_source == str(stats_path)


def test_input_frames_fallback_when_no_stats(normal_frames, fit_kwargs):
    det = fit_health_detector(normal_frames, **fit_kwargs)
    assert det.norm_source == "input_frames"


def test_score_only_uses_axes_columns(normal_frames, fit_kwargs):
    det = fit_health_detector(normal_frames, **fit_kwargs)
    # Drop an unrelated column; scoring should still work.
    minimal = normal_frames[list(TEST_AXES)].copy()
    s1 = det.score(normal_frames)["detector_recon_error"].to_numpy()
    s2 = det.score(minimal)["detector_recon_error"].to_numpy()
    np.testing.assert_array_equal(s1, s2)


def test_missing_axis_raises_on_score(normal_frames, fit_kwargs):
    det = fit_health_detector(normal_frames, **fit_kwargs)
    bad = normal_frames.drop(columns=["edge_power"])
    with pytest.raises(KeyError):
        det.score(bad)


def test_to_summary_dict_is_json_safe(normal_frames, fit_kwargs):
    det = fit_health_detector(normal_frames, **fit_kwargs)
    summary = det.to_summary_dict()
    # round-trips to JSON without raising
    encoded = json.dumps(summary)
    assert "axes" in encoded
    assert "architecture" in encoded
    assert "calibration" in encoded


def test_autoencoder_seed_reproducible_init():
    a = HealthAutoencoder(n_axes=4, hidden_dim=8, latent_dim=4, seed=42)
    b = HealthAutoencoder(n_axes=4, hidden_dim=8, latent_dim=4, seed=42)
    for (n1, p1), (n2, p2) in zip(a.named_parameters(), b.named_parameters()):
        assert n1 == n2
        np.testing.assert_array_equal(p1.detach().numpy(), p2.detach().numpy())


def test_autoencoder_distinct_seeds_distinct_init():
    a = HealthAutoencoder(n_axes=4, hidden_dim=8, latent_dim=4, seed=1)
    b = HealthAutoencoder(n_axes=4, hidden_dim=8, latent_dim=4, seed=2)
    diffs = []
    for (n1, p1), (n2, p2) in zip(a.named_parameters(), b.named_parameters()):
        diffs.append(not np.array_equal(p1.detach().numpy(), p2.detach().numpy()))
    assert any(diffs), "different seeds should change at least one tensor"
