"""Sprint 28 tests for Pillar A interpretable health baselines.

Subset-only / fixture-based. Verifies:
* EWMA/SPC flags an injected step deviation; pure-normal stays largely within
  limits (low false-alarm rate).
* Mahalanobis: out-of-envelope synthetic point scores high; in-envelope low.
* Residual vs physical: a configured strong linear relationship is detected with
  high confidence; missing features / weak relationships drop to low_confidence.
* Determinism: identical seed/data => bit-identical fitted params and scores.
* Leakage guard: an input containing a ``2026-03`` key fails before any fit.
* Suite: held-in normal-data false-alarm rate stays low and is reportable.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from aquaoptima.advisory.health_baselines import (
    DEFAULT_RESIDUAL_MIN_R2,
    EwmaSpcModel,
    HealthBaselineSuite,
    LeakageError,
    MahalanobisModel,
    PhysicalResidualModel,
    fit_ewma_spc,
    fit_health_baseline_suite,
    fit_mahalanobis,
    residual_vs_physical,
)


# --- fixtures --------------------------------------------------------------

# A small set of canonical continuous axes -- a strict subset of the production set
# so tests stay fast and deterministic.
TEST_AXES = (
    "edge_flow",
    "edge_power",
    "edge_pump_speed",
    "node_pressure",
)


def _synthetic_2025_normal(n_rows: int = 600, seed: int = 17) -> pd.DataFrame:
    """A small auto-mode 2025 normal-operation frame keyed by minute timestamps."""
    rng = np.random.default_rng(seed)
    n = n_rows
    # Centres roughly match the cached 2025 train stats scale -- not the exact values
    # (we are deliberately fitting on this synthetic, not on the real CSV).
    flow = rng.normal(loc=1500.0, scale=80.0, size=n)
    speed = rng.normal(loc=42.0, scale=1.5, size=n)
    # Strong physical relationship power ~ 0.05*flow + 1.5*speed + small noise so
    # residual_vs_physical lands in high-confidence territory on this fixture.
    power = 0.05 * flow + 1.5 * speed + rng.normal(loc=0.0, scale=2.0, size=n)
    pressure = rng.normal(loc=18.0, scale=0.5, size=n)
    start = pd.Timestamp("2025-07-01 00:00:00")
    ts = pd.date_range(start, periods=n, freq="1min").strftime("%Y-%m-%d %H:%M:%S")
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
def normal_frames():
    return _synthetic_2025_normal()


# --- 1) EWMA / SPC ---------------------------------------------------------

def test_fit_ewma_spc_produces_finite_limits(normal_frames):
    model = fit_ewma_spc(normal_frames, list(TEST_AXES))
    assert isinstance(model, EwmaSpcModel)
    assert model.axes == TEST_AXES
    for a in TEST_AXES:
        limits = model.axis_limits()[a]
        assert np.isfinite(limits["mu"])
        assert np.isfinite(limits["sigma"])
        assert limits["sigma"] > 0
        assert limits["upper"] > limits["lower"]


def test_ewma_spc_low_false_alarm_on_normal_data(normal_frames):
    # Held-in normal data: a 3-sigma EWMA chart should trip on a small fraction
    # of rows (we conservatively allow up to 5% across axes).
    model = fit_ewma_spc(normal_frames, list(TEST_AXES))
    scored = model.score(normal_frames)
    any_axis_trip = (scored["spc_fraction_axes_out"] > 0).mean()
    assert any_axis_trip < 0.05, f"normal-data SPC false-alarm rate too high: {any_axis_trip}"


def test_ewma_spc_flags_injected_step_deviation(normal_frames):
    model = fit_ewma_spc(normal_frames, list(TEST_AXES))
    perturbed = normal_frames.copy()
    # Inject a large persistent step deviation in edge_power well outside the 3-sigma
    # control limits for the last quarter of the series.
    n = len(perturbed)
    step_start = n - n // 4
    perturbed.loc[step_start:, "edge_power"] = (
        perturbed.loc[step_start:, "edge_power"] + 8.0 * float(model.sigma["edge_power"])
    )
    scored = model.score(perturbed)
    trips_in_step = scored.loc[step_start + 50 :, f"flag_edge_power"].mean()
    assert trips_in_step > 0.9, f"EWMA must flag the injected step (got {trips_in_step})"
    # Sanity: the unmodified prefix is overwhelmingly in-control on edge_power.
    trips_pre_step = scored.loc[: step_start - 1, f"flag_edge_power"].mean()
    assert trips_pre_step < 0.05


def test_ewma_spc_rejects_bad_lambda(normal_frames):
    with pytest.raises(ValueError):
        fit_ewma_spc(normal_frames, list(TEST_AXES), lam=0.0)
    with pytest.raises(ValueError):
        fit_ewma_spc(normal_frames, list(TEST_AXES), lam=1.5)


# --- 2) Mahalanobis --------------------------------------------------------

def test_fit_mahalanobis_invertible(normal_frames):
    m = fit_mahalanobis(normal_frames, list(TEST_AXES))
    assert isinstance(m, MahalanobisModel)
    assert m.axes == TEST_AXES
    summary = m.covariance_summary()
    assert summary["min_eig"] > 0
    assert np.isfinite(summary["condition_number"])


def test_mahalanobis_low_score_in_envelope_high_score_out(normal_frames):
    m = fit_mahalanobis(normal_frames, list(TEST_AXES))
    # In-envelope: row close to the mean of every axis.
    mu = np.asarray(m.mu)
    in_row = pd.DataFrame([dict(zip(TEST_AXES, mu))])
    out_row = pd.DataFrame(
        [
            {
                # Out-of-envelope: well outside 6-sigma on every axis.
                "edge_flow": mu[0] + 12.0 * float(m.sigma[0]),
                "edge_power": mu[1] - 12.0 * float(m.sigma[1]),
                "edge_pump_speed": mu[2] + 12.0 * float(m.sigma[2]),
                "node_pressure": mu[3] - 12.0 * float(m.sigma[3]),
            }
        ]
    )
    d_in = m.score(in_row)["maha_distance"].iloc[0]
    d_out = m.score(out_row)["maha_distance"].iloc[0]
    assert d_out > d_in
    assert d_out > m.calib_distance
    # In-envelope score normalises near zero; out-of-envelope saturates at 1.0.
    assert m.score(in_row)["maha_norm_score"].iloc[0] < 0.3
    assert m.score(out_row)["maha_norm_score"].iloc[0] == pytest.approx(1.0)


def test_mahalanobis_needs_enough_rows():
    tiny = pd.DataFrame(
        {
            "timestamp": ["2025-01-01 00:00:00", "2025-01-01 00:01:00"],
            "edge_flow": [1.0, 2.0],
            "edge_power": [3.0, 4.0],
            "edge_pump_speed": [5.0, 6.0],
            "node_pressure": [7.0, 8.0],
        }
    )
    with pytest.raises(ValueError):
        fit_mahalanobis(tiny, list(TEST_AXES))


# --- 3) Residual vs physical ----------------------------------------------

def test_residual_vs_physical_high_confidence(normal_frames):
    model = residual_vs_physical(normal_frames)
    assert isinstance(model, PhysicalResidualModel)
    assert model.high_confidence is True
    assert model.r2 >= DEFAULT_RESIDUAL_MIN_R2
    assert model.residual_sigma > 0
    scored = model.score(normal_frames)
    assert "residual" in scored.columns
    # Most rows have small normalised residual.
    assert scored["residual_norm_score"].mean() < 0.3


def test_residual_vs_physical_flags_anomalous_row(normal_frames):
    model = residual_vs_physical(normal_frames)
    assert model.high_confidence
    # Build a single row whose power blatantly violates the fitted expectation.
    anom = pd.DataFrame(
        [
            {
                "timestamp": "2025-07-01 12:00:00",
                "edge_flow": 1500.0,
                "edge_pump_speed": 42.0,
                "edge_power": float(
                    model.intercept
                    + model.coefficients[0] * 1500.0
                    + model.coefficients[1] * 42.0
                    + 20.0 * model.residual_sigma  # 20-sigma deviation
                ),
                "node_pressure": 18.0,
            }
        ]
    )
    scored = model.score(anom)
    assert scored["residual_norm_score"].iloc[0] == pytest.approx(1.0)


def test_residual_vs_physical_low_confidence_when_features_missing():
    # No edge_pump_speed column -> immediately low_confidence, emits zeros.
    frame = pd.DataFrame(
        {
            "timestamp": pd.date_range("2025-06-01", periods=20, freq="1min").strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            "edge_flow": np.arange(20, dtype=float),
            "edge_power": np.arange(20, dtype=float) * 0.05,
        }
    )
    model = residual_vs_physical(frame)
    assert model.high_confidence is False
    scored = model.score(frame)
    assert (scored["residual_norm_score"] == 0.0).all()
    assert (scored["residual_high_confidence"] == 0).all()


def test_residual_vs_physical_low_confidence_when_no_signal():
    # Power is pure noise w.r.t. flow/speed -> R^2 below min_r2 -> low_confidence.
    rng = np.random.default_rng(0)
    n = 400
    frame = pd.DataFrame(
        {
            "timestamp": pd.date_range("2025-08-01", periods=n, freq="1min").strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            "edge_flow": rng.normal(0.0, 1.0, size=n),
            "edge_pump_speed": rng.normal(0.0, 1.0, size=n),
            "edge_power": rng.normal(0.0, 1.0, size=n),  # no relationship
        }
    )
    model = residual_vs_physical(frame)
    assert model.high_confidence is False
    assert "low_confidence" in model.reason


# --- 4) Determinism -------------------------------------------------------

def test_ewma_spc_is_deterministic(normal_frames):
    m1 = fit_ewma_spc(normal_frames.copy(), list(TEST_AXES))
    m2 = fit_ewma_spc(normal_frames.copy(), list(TEST_AXES))
    for a in TEST_AXES:
        assert m1.mu[a] == m2.mu[a]
        assert m1.sigma[a] == m2.sigma[a]
        assert m1.upper[a] == m2.upper[a]
        assert m1.lower[a] == m2.lower[a]
    s1 = m1.score(normal_frames)
    s2 = m2.score(normal_frames)
    pd.testing.assert_frame_equal(s1, s2, check_exact=True)


def test_mahalanobis_is_deterministic(normal_frames):
    m1 = fit_mahalanobis(normal_frames.copy(), list(TEST_AXES))
    m2 = fit_mahalanobis(normal_frames.copy(), list(TEST_AXES))
    assert m1.mu == m2.mu
    assert m1.cov == m2.cov
    assert m1.cov_inv == m2.cov_inv
    s1 = m1.score(normal_frames)
    s2 = m2.score(normal_frames)
    pd.testing.assert_frame_equal(s1, s2, check_exact=True)


def test_suite_score_is_deterministic(normal_frames):
    s1 = fit_health_baseline_suite(normal_frames.copy(), list(TEST_AXES))
    s2 = fit_health_baseline_suite(normal_frames.copy(), list(TEST_AXES))
    pd.testing.assert_frame_equal(
        s1.score(normal_frames), s2.score(normal_frames), check_exact=True
    )


# --- 5) Leakage guard -----------------------------------------------------

def _inject_holdout_row(frames: pd.DataFrame) -> pd.DataFrame:
    bad = frames.copy()
    bad.loc[bad.index[0], "timestamp"] = "2026-03-15 08:00:00"
    return bad


def test_fit_ewma_spc_rejects_holdout_leakage(normal_frames):
    bad = _inject_holdout_row(normal_frames)
    with pytest.raises(LeakageError) as exc:
        fit_ewma_spc(bad, list(TEST_AXES))
    assert "2026-03" in str(exc.value)


def test_fit_mahalanobis_rejects_holdout_leakage(normal_frames):
    bad = _inject_holdout_row(normal_frames)
    with pytest.raises(LeakageError):
        fit_mahalanobis(bad, list(TEST_AXES))


def test_residual_vs_physical_rejects_holdout_leakage(normal_frames):
    bad = _inject_holdout_row(normal_frames)
    with pytest.raises(LeakageError):
        residual_vs_physical(bad)


def test_fit_health_baseline_suite_rejects_holdout_leakage(normal_frames):
    bad = _inject_holdout_row(normal_frames)
    with pytest.raises(LeakageError):
        fit_health_baseline_suite(bad, list(TEST_AXES))


def test_leakage_guard_uses_index_when_no_timestamp_column():
    # Index-based fall-back: a March-2026 index key must also trip.
    idx = ["2025-04-01", "2025-04-02", "2026-03-15"]
    frame = pd.DataFrame(
        {
            "edge_flow": [1.0, 2.0, 3.0],
            "edge_power": [4.0, 5.0, 6.0],
            "edge_pump_speed": [7.0, 8.0, 9.0],
            "node_pressure": [10.0, 11.0, 12.0],
        },
        index=idx,
    )
    with pytest.raises(LeakageError):
        fit_ewma_spc(frame, list(TEST_AXES))


# --- 6) Suite & false-alarm summary --------------------------------------

def test_suite_score_columns_and_health_range(normal_frames):
    suite = fit_health_baseline_suite(normal_frames, list(TEST_AXES))
    scored = suite.score(normal_frames)
    for col in (
        "spc_norm_score",
        "maha_norm_score",
        "residual_norm_score",
        "combined_deviation",
        "health_score",
        "anomaly_flag",
        "components_used",
    ):
        assert col in scored.columns
    assert scored["health_score"].min() >= 0.0
    assert scored["health_score"].max() <= 1.0
    assert set(scored["anomaly_flag"].unique()).issubset({0, 1})


def test_suite_false_alarm_summary_low_on_normal_data(normal_frames):
    suite = fit_health_baseline_suite(normal_frames, list(TEST_AXES))
    summary = suite.false_alarm_summary(normal_frames)
    assert summary["n_rows"] == len(normal_frames)
    # Held-in normal data: every reported alarm rate stays modest.
    assert summary["combined_anomaly_flag_rate"] < 0.05
    assert summary["spc_any_axis_alarm_rate"] < 0.05
    assert summary["mahalanobis_alarm_rate"] <= 0.05
    assert 0.0 <= summary["health_score_mean"] <= 1.0


def test_suite_to_summary_dict_is_json_safe(normal_frames):
    import json

    suite = fit_health_baseline_suite(normal_frames, list(TEST_AXES))
    blob = suite.to_summary_dict()
    # Must serialise cleanly so the report script can dump it.
    json.dumps(blob)
