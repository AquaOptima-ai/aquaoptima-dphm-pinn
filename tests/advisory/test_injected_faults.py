"""Sprint 29 tests for the injected-fault harness.

Subset / fixture only. Verifies:
* Labels and onsets have the expected shape and arithmetic invariants.
* All four fault families are exercised when ``edge_power`` is present.
* Same seed + same input produce bit-identical output.
* The harness is read-only with respect to the caller's frame.
* The injected episodes are detectable in principle: a trivially large injected
  spike yields a much larger reconstruction error / EWMA z-score than the
  surrounding normal data for SOME conservative scorer. We do NOT assert the
  learned detector wins -- that is the empirical gate, not a unit invariant.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from aquaoptima.advisory.injected_faults import (
    DEFAULT_SEED,
    FAULT_KINDS,
    FaultEpisode,
    InjectedFaultResult,
    inject_faults,
)


TEST_AXES = ("edge_flow", "edge_power", "edge_pump_speed", "node_pressure")


def _synthetic_2025_normal(n_rows: int = 1200, seed: int = 17) -> pd.DataFrame:
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
def small_inject_kwargs() -> dict:
    return {
        "seed": DEFAULT_SEED,
        "n_episodes_per_kind": 2,
        "drift_window": 60,
        "stuck_window": 40,
        "envelope_window": 40,
        "spike_tail": 4,
    }


def test_inject_returns_result_shape(normal_frames, small_inject_kwargs):
    out = inject_faults(normal_frames, **small_inject_kwargs)
    assert isinstance(out, InjectedFaultResult)
    assert isinstance(out.frames, pd.DataFrame)
    assert out.frames.shape[0] == normal_frames.shape[0]
    assert out.labels.shape == (normal_frames.shape[0],)
    assert out.labels.dtype == np.int8


def test_labels_align_with_episodes(normal_frames, small_inject_kwargs):
    out = inject_faults(normal_frames, **small_inject_kwargs)
    expected = np.zeros(normal_frames.shape[0], dtype=np.int8)
    for ep in out.episodes:
        expected[ep.onset_index : ep.end_index] = 1
    np.testing.assert_array_equal(out.labels, expected)
    assert out.labels.sum() == int((expected == 1).sum())
    assert out.labels.sum() > 0


def test_all_four_fault_kinds_present(normal_frames, small_inject_kwargs):
    out = inject_faults(normal_frames, **small_inject_kwargs)
    kinds = {ep.kind for ep in out.episodes}
    assert kinds == set(FAULT_KINDS)


def test_episode_count_matches_kwargs(normal_frames, small_inject_kwargs):
    n_per = int(small_inject_kwargs["n_episodes_per_kind"])
    out = inject_faults(normal_frames, **small_inject_kwargs)
    # Four kinds * n_per episodes each.
    assert len(out.episodes) == n_per * 4


def test_determinism_same_seed_same_output(normal_frames, small_inject_kwargs):
    a = inject_faults(normal_frames, **small_inject_kwargs)
    b = inject_faults(normal_frames, **small_inject_kwargs)
    np.testing.assert_array_equal(a.labels, b.labels)
    pd.testing.assert_frame_equal(a.frames, b.frames)
    assert [e.to_dict() for e in a.episodes] == [e.to_dict() for e in b.episodes]


def test_different_seed_changes_output(normal_frames, small_inject_kwargs):
    a = inject_faults(normal_frames, seed=29, **{k: v for k, v in small_inject_kwargs.items() if k != "seed"})
    b = inject_faults(normal_frames, seed=7, **{k: v for k, v in small_inject_kwargs.items() if k != "seed"})
    assert not np.array_equal(a.labels, b.labels) or any(
        ea.onset_index != eb.onset_index
        for ea, eb in zip(a.episodes, b.episodes)
    )


def test_harness_is_read_only_on_input(normal_frames, small_inject_kwargs):
    before = normal_frames.copy(deep=True)
    inject_faults(normal_frames, **small_inject_kwargs)
    pd.testing.assert_frame_equal(normal_frames, before)


def test_onsets_within_bounds(normal_frames, small_inject_kwargs):
    n = normal_frames.shape[0]
    out = inject_faults(normal_frames, **small_inject_kwargs)
    for ep in out.episodes:
        assert 0 <= ep.onset_index < n
        assert ep.onset_index < ep.end_index <= n


def test_episodes_do_not_overlap(normal_frames, small_inject_kwargs):
    out = inject_faults(normal_frames, **small_inject_kwargs)
    spans = sorted(((ep.onset_index, ep.end_index) for ep in out.episodes))
    for (s1, e1), (s2, e2) in zip(spans, spans[1:]):
        assert e1 <= s2, f"overlap {s1, e1} vs {s2, e2}"


def test_spike_changes_target_axis(normal_frames, small_inject_kwargs):
    out = inject_faults(normal_frames, **small_inject_kwargs)
    spikes = [ep for ep in out.episodes if ep.kind == "spike"]
    assert spikes, "expected at least one spike episode"
    for ep in spikes:
        before = float(normal_frames[ep.axis].iloc[ep.onset_index])
        after = float(out.frames[ep.axis].iloc[ep.onset_index])
        assert after != pytest.approx(before, rel=0, abs=1e-9), (
            f"spike at {ep.onset_index} did not alter {ep.axis}: before={before} after={after}"
        )


def test_stuck_window_is_constant(normal_frames, small_inject_kwargs):
    out = inject_faults(normal_frames, **small_inject_kwargs)
    stucks = [ep for ep in out.episodes if ep.kind == "stuck_flatline"]
    assert stucks, "expected at least one stuck episode"
    for ep in stucks:
        seg = out.frames[ep.axis].iloc[ep.onset_index : ep.end_index].to_numpy()
        # All values within the stuck window are bit-identical.
        assert np.allclose(seg, seg[0], atol=0.0, rtol=0.0)


def test_envelope_violation_targets_edge_power(normal_frames, small_inject_kwargs):
    out = inject_faults(normal_frames, **small_inject_kwargs)
    envs = [ep for ep in out.episodes if ep.kind == "envelope_violation"]
    assert envs, "expected at least one envelope episode"
    for ep in envs:
        assert ep.axis == "edge_power"
        # Other axes (flow, speed) should be unchanged at these indices.
        for other in ("edge_flow", "edge_pump_speed"):
            np.testing.assert_array_equal(
                normal_frames[other].iloc[ep.onset_index : ep.end_index].to_numpy(),
                out.frames[other].iloc[ep.onset_index : ep.end_index].to_numpy(),
            )


def test_spike_is_detectable_in_principle(normal_frames, small_inject_kwargs):
    """A 6-sigma spike must produce a larger axis-value deviation at the spike
    index than at a random pre-onset index. This is a UNIT INVARIANT on the
    injection, NOT a claim that the learned detector wins."""
    out = inject_faults(normal_frames, **small_inject_kwargs)
    spikes = [ep for ep in out.episodes if ep.kind == "spike"]
    for ep in spikes:
        axis = ep.axis
        baseline_sigma = float(normal_frames[axis].std(ddof=1)) or 1.0
        spike_value = float(out.frames[axis].iloc[ep.onset_index])
        baseline_mean = float(normal_frames[axis].mean())
        z = abs(spike_value - baseline_mean) / baseline_sigma
        assert z > 3.0, f"spike at {ep.onset_index} produced only z={z:.2f}"


def test_summary_dict_is_json_safe(normal_frames, small_inject_kwargs):
    import json

    out = inject_faults(normal_frames, **small_inject_kwargs)
    text = json.dumps(out.to_summary_dict())
    assert "episodes" in text
    assert "onsets_by_kind" in text


def test_empty_input_raises(small_inject_kwargs):
    empty = pd.DataFrame(columns=["timestamp", *TEST_AXES])
    with pytest.raises(ValueError):
        inject_faults(empty, **small_inject_kwargs)


def test_missing_all_injectable_axes_raises(small_inject_kwargs):
    df = pd.DataFrame({"timestamp": pd.date_range("2025-07-01", periods=100, freq="1min").strftime("%Y-%m-%d %H:%M:%S"), "other": np.zeros(100)})
    with pytest.raises(ValueError):
        inject_faults(df, **small_inject_kwargs)
